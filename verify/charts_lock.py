# ABOUTME: Lists every upstream Helm chart the repo pins and writes verify/charts.lock, each chart's version and tarball
# ABOUTME: SHA-256 as its repository's index.yaml or OCI manifest publishes it (#1118); chart_fetch.py serves by that sum.
"""The pinned charts are every chart source of an Argo CD Application in gitops/bootstrap/apps/ and every
`helm upgrade --install <alias>/<chart> --version <v>` in infra/deploy-full-idp.sh, its alias resolved by the same
file's `helm repo add`. Those are what the tier's renders pull through chart_fetch.pull(); test_chart_fetch.py holds
that the lock names each of them and nothing else, offline.

  python3 verify/charts_lock.py write          read each chart's digest from its repository and write charts.lock
  python3 verify/charts_lock.py check <helm>   pull every locked chart through chart_fetch, which checks its sum

`write` reads an HTTP repository's index.yaml for the version's `digest`, and an OCI registry's manifest for the
chart layer's digest, anonymously; both are the SHA-256 of the tarball `helm pull` saves. A chart the repository does
not list at its pinned version, or lists with no digest, fails by name and nothing is written. `check` then has the
host artifact cache fetch each one on a miss and compare the bytes with the lock."""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
sys.path.insert(0, str(VERIFY))
import chart_fetch  # noqa: E402

APPS = REPO / "gitops" / "bootstrap" / "apps"
DEPLOY = REPO / "infra" / "deploy-full-idp.sh"
HELM_LAYER = "application/vnd.cncf.helm.chart.content.v1.tar+gzip"
TIMEOUT = 60

HEADER = """\
# ABOUTME: The upstream Helm charts the tier renders, each pinned by version and the SHA-256 of its tarball (#1118).
# ABOUTME: chart_fetch.pull() serves a chart only by this sum, from the host artifact cache; written by charts_lock.py.
#
# One chart a line: chart, version, SHA-256 of the tarball `helm pull` saves, repository (an HTTP repository, or an
# OCI registry path as the Application's repoURL names it). The sums are the digests the repository's index.yaml or
# OCI manifest publishes. A chart pinned in gitops/bootstrap/apps/ or infra/deploy-full-idp.sh and missing here fails
# test_chart_fetch.py and every render that pulls it; after a version bump run python3 verify/charts_lock.py write.
"""


def app_pins() -> set[tuple[str, str, str]]:
    """(repo, chart, version) for every chart source of every Application under gitops/bootstrap/apps/. The files are
    templates of the lab-bootstrap chart, but every template action in them sits in a comment or a quoted string, so
    they read as YAML."""
    pins = set()
    for f in sorted(APPS.glob("*.yaml")):
        for doc in yaml.safe_load_all(f.read_text()):
            if not isinstance(doc, dict) or doc.get("kind") != "Application":
                continue
            spec = doc.get("spec") or {}
            for src in ([spec["source"]] if spec.get("source") else []) + list(spec.get("sources") or []):
                if "chart" in src:
                    pins.add((src["repoURL"], src["chart"], str(src["targetRevision"])))
    return pins


def deploy_pins(text: str | None = None) -> set[tuple[str, str, str]]:
    """(repo, chart, version) for every Helm install infra/deploy-full-idp.sh makes from a repository it adds."""
    text = DEPLOY.read_text() if text is None else text
    repos = dict(re.findall(r"\brepo add (\S+) (https?://\S+)", text))
    pins = set()
    for alias, chart, version in re.findall(r"\bupgrade --install \S+ (\S+)/(\S+) --version (\S+)", text):
        if alias not in repos:
            raise SystemExit(f"FAIL: {DEPLOY.name} installs {alias}/{chart} but adds no repository {alias}")
        pins.add((repos[alias], chart, version))
    return pins


def pins() -> set[tuple[str, str, str]]:
    return app_pins() | deploy_pins()


def render(digests: dict[tuple[str, str, str], str]) -> str:
    rows = sorted(digests.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][0]))
    width = max(len(c) for (_, c, _) in digests) if digests else 0
    vwidth = max(len(v) for (_, _, v) in digests) if digests else 0
    return HEADER + "".join(f"{c:<{width}}  {v:<{vwidth}}  {sha}  {r}\n" for (r, c, v), sha in rows)


def get(url: str, headers: dict[str, str] | None = None) -> tuple[bytes, dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "wib-charts-lock", **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(), dict(r.headers)


def index_digest(repo: str, chart: str, version: str, cache: dict[str, dict]) -> str:
    if repo not in cache:
        body, _ = get(repo.rstrip("/") + "/index.yaml")
        cache[repo] = yaml.safe_load(body) or {}
    entries = (cache[repo].get("entries") or {}).get(chart) or []
    # Helm reads --version as semver, so 1.7.4 pulls the entry kubearmor's index lists as v1.7.4: the exact version
    # first, else the one entry that differs from it by a leading v alone.
    found = ([e for e in entries if str(e.get("version")) == version]
             or [e for e in entries if str(e.get("version")).removeprefix("v") == version.removeprefix("v")])
    if len(found) != 1:
        raise SystemExit(f"FAIL: {repo}/index.yaml lists {chart} {version} {len(found)} times, not once")
    digest = str(found[0].get("digest") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise SystemExit(f"FAIL: {repo} lists {chart} {version} with no SHA-256 digest ({digest!r})")
    return digest


def oci_digest(repo: str, chart: str, version: str) -> str:
    """The chart layer's digest in the registry's manifest for the tag, with the anonymous token its 401 asks for."""
    host, _, path = repo.removeprefix("oci://").rstrip("/").partition("/")
    name = f"{path}/{chart}"
    url = f"https://{host}/v2/{name}/manifests/{version}"
    accept = {"Accept": "application/vnd.oci.image.manifest.v1+json"}
    try:
        body, _ = get(url, accept)
    except urllib.error.HTTPError as e:
        challenge = e.headers.get("WWW-Authenticate", "")
        if e.code != 401 or not challenge.lower().startswith("bearer "):
            raise
        params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        query = urllib.parse.urlencode({"service": params.get("service", host), "scope": f"repository:{name}:pull"})
        token = json.loads(get(f"{params['realm']}?{query}")[0])
        body, _ = get(url, {**accept, "Authorization": f"Bearer {token.get('token') or token.get('access_token')}"})
    layers = [ly for ly in json.loads(body).get("layers", []) if ly.get("mediaType") == HELM_LAYER]
    if len(layers) != 1 or not str(layers[0].get("digest", "")).startswith("sha256:"):
        raise SystemExit(f"FAIL: {url} has no one Helm chart layer with a sha256 digest: {layers}")
    return layers[0]["digest"].removeprefix("sha256:")


def write() -> int:
    cache: dict[str, dict] = {}
    digests = {}
    for repo, chart, version in sorted(pins()):
        http = repo.startswith(("http://", "https://"))
        digests[(repo, chart, version)] = (index_digest(repo, chart, version, cache) if http
                                           else oci_digest(repo, chart, version))
        print(f"  {chart} {version}  {digests[(repo, chart, version)]}  {repo}")
    chart_fetch.LOCK.write_text(render(digests))
    print(f"wrote {len(digests)} charts to {chart_fetch.LOCK}")
    return 0


def check(helm: str) -> int:
    bad = 0
    for (repo, chart, version) in sorted(chart_fetch.load_lock()):
        try:
            path = chart_fetch.pull(helm, repo, chart, version)
            print(f"  ok    {chart} {version}  {path}")
        except chart_fetch.ChartFetchError as e:
            bad += 1
            print(f"  FAIL  {e}")
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["write"]:
        sys.exit(write())
    if len(sys.argv) == 3 and sys.argv[1] == "check":
        sys.exit(check(sys.argv[2]))
    sys.exit("usage: python3 verify/charts_lock.py write | python3 verify/charts_lock.py check <helm>")
