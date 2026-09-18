# ABOUTME: Reports every pinned component against its latest GA, reading the repos the Applications
# ABOUTME: actually name, and separating chart version from the appVersion the chart installs.
"""What is behind its latest GA, measured rather than remembered.

Why this exists (issue #401). The upgrade in PRD #389 was built on a measurement made by a script
written ad hoc and then thrown away, leaving `docs/UPGRADE-INVENTORY.md` as a dated snapshot nobody
could refresh. This is that measurement, kept and made re-runnable.

Two things it gets right that are easy to get wrong, both of which produced a wrong answer the first
time this was done by hand:

**The chart version is not the app version.** Charts number independently of what they install. The
opentelemetry-collector chart 0.172.1 ships collector 0.159.0; kube-prometheus-stack 90.0.0 ships
Prometheus Operator v0.93.1; argo-cd 10.8.4 ships Argo CD v3.5.2. "Upgrade to the latest GA" is a
statement about the APP, so both are reported and the appVersion is the one that answers the question.

**Read the repository the Application actually names.** `tempo` is pinned from
grafana-community.github.io, and querying grafana.github.io returns a different chart line entirely.
That single mistake produced an "UNVERIFIED" row in the inventory and a claim that had to be retracted.
The repo URL is therefore parsed out of the manifests, never assumed.

Usage:
    python3 verify/version-drift.py            # table, exit 1 if anything is behind
    python3 verify/version-drift.py --json     # machine-readable
Network: reads Helm repo index.yaml files, the GitHub releases API, PyPI, and (if AWS creds exist)
`aws eks describe-cluster-versions`. No web search, no interpretation.
"""
from __future__ import annotations

import gzip
import json
import os
import pathlib
import subprocess
import sys
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
TIMEOUT = 45


def version_key(v: str) -> list[int]:
    """Sort key that tolerates v-prefixes and non-numeric segments."""
    parts: list[int] = []
    for p in str(v).lstrip("v").split("+")[0].replace("-", ".").split("."):
        parts.append(int(p) if p.isdigit() else -1)
    return parts


def is_prerelease(v: str) -> bool:
    return any(t in str(v) for t in ("-rc", "-beta", "-alpha", "-dev", "-snapshot"))


def pinned_charts() -> dict[str, tuple[str, str]]:
    """Every Helm chart an Application pins, as {chart: (revision, repoURL)}.

    Parsed from the manifests so the repo URL is whatever the Application really names.
    """
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML is required: uv run --with pyyaml python3 verify/version-drift.py")
    out: dict[str, tuple[str, str]] = {}
    for f in sorted((REPO / "gitops").rglob("*.yaml")):
        try:
            docs = list(yaml.safe_load_all(f.read_text(encoding="utf-8")))
        except Exception:
            continue
        for d in docs:
            if not isinstance(d, dict) or d.get("kind") != "Application":
                continue
            spec = d.get("spec") or {}
            sources = spec.get("sources") or ([spec["source"]] if spec.get("source") else [])
            for s in sources:
                if isinstance(s, dict) and s.get("chart"):
                    out[s["chart"]] = (str(s.get("targetRevision", "?")), str(s.get("repoURL", "")))
    return out


_index_cache: dict[str, dict] = {}


def helm_index(repo: str) -> dict:
    if repo in _index_cache:
        return _index_cache[repo]
    # An OCI registry serves no index.yaml. kagent ships its chart from ghcr.io, so it is resolved from
    # its GitHub releases instead of guessed at; reporting "ERR unknown url type" for a component that is
    # perfectly fine reads as breakage.
    if not repo.startswith(("http://", "https://")):
        _index_cache[repo] = {"_oci": True}
        return _index_cache[repo]
    try:
        req = urllib.request.Request(repo.rstrip("/") + "/index.yaml", headers={"User-Agent": "curl/8"})
        raw = urllib.request.urlopen(req, timeout=TIMEOUT).read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        import yaml
        _index_cache[repo] = yaml.safe_load(raw) or {}
    except Exception as e:  # a repo that will not answer is reported, not fatal
        _index_cache[repo] = {"_error": str(e)[:70]}
    return _index_cache[repo]


def latest_chart(chart: str, repo: str) -> tuple[str, str]:
    """(latest chart version, its appVersion) for a chart in the repo the manifest names."""
    idx = helm_index(repo)
    if idx.get("_oci"):
        return "(OCI, see releases)", ""
    if "_error" in idx:
        return f"ERR {idx['_error']}", ""
    entries = (idx.get("entries") or {}).get(chart)
    if not entries:
        return "not in index", ""
    stable = [e for e in entries if not is_prerelease(e.get("version", ""))]
    top = max(stable or entries, key=lambda e: version_key(e.get("version", "0")))
    return str(top.get("version", "?")), str(top.get("appVersion", "") or "")


def gh_latest(repo: str) -> str:
    """Highest NON-prerelease tag. /releases/latest can return an alpha, and this file exists to answer
    'what is the latest GA'; kagent's newest tag at time of writing is v1.0.0-alpha1, which is not it."""
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases?per_page=30",
                                     headers={"User-Agent": "curl/8"})
        rels = json.load(urllib.request.urlopen(req, timeout=TIMEOUT))
        stable = [r for r in rels if not r.get("prerelease") and not is_prerelease(r.get("tag_name", ""))]
        if not stable:
            return "?"
        return max(stable, key=lambda r: version_key(r.get("tag_name", "0"))).get("tag_name", "?")
    except Exception:
        return "?"


def pypi_latest(pkg: str) -> str:
    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=TIMEOUT) as r:
            return json.load(r)["info"]["version"]
    except Exception:
        return "?"


def eks_versions() -> str:
    """Highest EKS version in STANDARD_SUPPORT. Upstream Kubernetes is irrelevant: EKS trails it, and
    CreateCluster rejects a version EKS does not offer, whatever kubernetes/kubernetes has tagged."""
    try:
        out = subprocess.run(
            ["aws", "eks", "describe-cluster-versions", "--region", os.environ.get("WIB_REGION", "us-west-2"),
             "--query", "clusterVersions[?status=='STANDARD_SUPPORT'].clusterVersion", "--output", "text"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "AWS_PROFILE": os.environ.get("AWS_PROFILE", "accen-dev")})
        vs = out.stdout.split()
        return max(vs, key=version_key) if vs else "?"
    except Exception:
        return "?"


def main() -> int:
    as_json = "--json" in sys.argv
    charts = pinned_charts()
    rows, behind = [], 0
    for chart, (pin, repo) in sorted(charts.items()):
        lv, av = latest_chart(chart, repo)
        is_behind = lv.isprintable() and not lv.startswith(("ERR", "not in")) and version_key(lv) > version_key(pin)
        behind += bool(is_behind)
        rows.append({"component": chart, "pinned": pin, "latest_chart": lv,
                     "latest_app": av, "behind": bool(is_behind), "source": repo})

    # Components that are not Helm charts need their own sources.
    for name, pin_hint, getter in (
        ("kagent", "gitops/apps/kagent.yaml", lambda: gh_latest("kagent-dev/kagent")),
        ("agentgateway", "gitops/ai-layer/agentgateway.yaml", lambda: gh_latest("agentgateway/agentgateway")),
        ("llm-guard", "images/llm-guard", lambda: pypi_latest("llm-guard")),
        ("eks-control-plane", "infra/terraform/aws/cluster/main.tf", eks_versions),
    ):
        rows.append({"component": name, "pinned": "(see " + pin_hint + ")", "latest_chart": "",
                     "latest_app": getter(), "behind": None, "source": "non-helm"})

    if as_json:
        print(json.dumps(rows, indent=2))
        return 1 if behind else 0

    print(f"{'component':28}{'pinned':14}{'latest chart':16}{'latest appVersion':20}status")
    print("-" * 94)
    for r in rows:
        st = "BEHIND" if r["behind"] else ("" if r["behind"] is None else "current")
        print(f"{r['component']:28}{r['pinned']:14}{r['latest_chart']:16}{r['latest_app']:20}{st}")
    print(f"\n{behind} chart(s) behind their latest release.")
    print("The appVersion column is what 'latest GA' means; a chart can lag the app it installs.")
    return 1 if behind else 0


if __name__ == "__main__":
    sys.exit(main())
