# ABOUTME: Renders gitops/bootstrap with the pinned Helm with and without imageRegistry (#622): set, no
# ABOUTME: ghcr.io/peopleforrester reference is left; unset, the render is today's, lab-platform images on ghcr.io.
# SUITE: e2e (needs helm, and the network for each mirror/ copy app's upstream chart)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. A root can pass lab-bootstrap an ECR pull-through cache path as imageRegistry (lab-platform#214 did, until
# lab-platform 5192c1a reverted it; the packages are public). infra/deploy-full-idp.sh passes nothing, and must
# get the default. test_image_registry.py holds that no file names the registry literally; this asks Helm what the
# value does to every profile's render, through a fixture app in a copy of the chart, and, for every mirror/ copy
# a chart pulls (#623, verify/mirror_copies.py), what the app's own chart hands the cluster: the copy at the cache
# path when the value is set and at ghcr.io when it is not. test_mirror_copies_public.py reads each copy there.
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import CHART, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, REPO, profiles, values_path  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


HELM = shutil.which("helm")
if not HELM:
    print("FAIL: helm is not on PATH (run through verify/run-e2e-tools.sh, which puts the pinned one first)",
          file=sys.stderr)
    sys.exit(1)
version = subprocess.run([HELM, "version", "--short"], capture_output=True, text=True).stdout.strip()
check(f"helm is the pinned v4.2.1 ({version})", version.startswith("v4.2.1"))

COMMIT = "0123456789abcdef0123456789abcdef01234567"
# The shape lab-platform#214 passes: <account>.dkr.ecr.<region>.amazonaws.com/<cache prefix>/peopleforrester/lab-platform.
CACHE = "123456789012.dkr.ecr.us-west-2.amazonaws.com/lp-shared/peopleforrester/lab-platform"
GHCR_OWNER = "ghcr.io/peopleforrester"


def render(chart: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([HELM, "template", "lab-bootstrap", str(chart), "--set", f"revision={COMMIT}", *args],
                          capture_output=True, text=True)


def strings(node):
    """Every string in a rendered document, keys included: an image in a Helm values block is inside one."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from strings(k)
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)
    elif isinstance(node, str):
        yield node


def fixture_helm(out: str) -> dict:
    """The fixture Application's helm block (the render also holds the chart's ghcr-kagent-oci Secret)."""
    app = next(d for d in yaml.safe_load_all(out) if d and d["metadata"]["name"] == "registry-fixture")
    return app["spec"]["source"]["helm"]


def naming(out: str, needle: str) -> list[str]:
    return [s for d in yaml.safe_load_all(out) if d for s in strings(d) if needle in s]


for profile in profiles():
    print(f"== {profile}: rendered with and without imageRegistry ==")
    values = ("-f", str(values_path(profile)))
    unset = render(CHART, *values)
    default = render(CHART, *values, "--set", f"imageRegistry={LAB_PLATFORM_GHCR}")
    cache = render(CHART, *values, "--set", f"imageRegistry={CACHE}")
    ok = all(r.returncode == 0 for r in (unset, default, cache))
    check(f"{profile} renders unset, at the default and at the cache path", ok,
          " / ".join(r.stderr.strip()[:200] for r in (unset, default, cache) if r.returncode))
    if not ok:
        continue
    check(f"{profile}: unset is the render at {LAB_PLATFORM_GHCR}, the chart's default", unset.stdout == default.stdout)
    left = naming(cache.stdout, GHCR_OWNER)
    check(f"{profile}: at the cache path, no {GHCR_OWNER} reference is left {left[:3]}", not left)
    today = naming(unset.stdout, LAB_PLATFORM_GHCR + "/")
    check(f"{profile}: at the cache path, the render is today's with each of its {len(today)} lab-platform "
          "reference(s) moved to the cache, and nothing else changed",
          cache.stdout.replace(CACHE + "/", LAB_PLATFORM_GHCR + "/") == unset.stdout
          and len(naming(cache.stdout, CACHE + "/")) == len(today))

print("== an app naming a mirror/ copy, in a copy of the chart ==")
# A KubeArmorConfig image from lab-platform's deploy/mirror/copies.tsv, in both places an app file's Helm values
# can hold one: valuesObject, and a values string block.
COPY = "mirror/kubearmor/kubearmor:stable-bf867783eb30"
FIXTURE = f"""apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: registry-fixture
  namespace: argocd
spec:
  project: default
  source:
    chart: kubearmor-operator
    repoURL: https://kubearmor.github.io/charts
    targetRevision: "1.7.4"
    helm:
      valuesObject:
        kubearmorConfig:
          kubearmorImage:
            image: "{IMAGE_REGISTRY}/{COPY}"
      values: |
        relay:
          image: "{IMAGE_REGISTRY}/mirror/kubearmor/kubearmor-relay-server:latest-e4fd875cc1e4"
  destination:
    server: https://kubernetes.default.svc
    namespace: kubearmor
"""
with tempfile.TemporaryDirectory() as tmp:
    chart = pathlib.Path(tmp) / "bootstrap"
    shutil.copytree(CHART, chart)
    (chart / "apps" / "registry-fixture.yaml").write_text(FIXTURE, encoding="utf-8")
    only = ("--set", "apps={registry-fixture}")
    unset = render(chart, *only)
    cache = render(chart, *only, "--set", f"imageRegistry={CACHE}")
    check("the fixture renders unset and at the cache path", unset.returncode == 0 and cache.returncode == 0,
          (unset.stderr + cache.stderr).strip()[:300])
    if unset.returncode == 0 and cache.returncode == 0:
        helm = fixture_helm(unset.stdout)
        check(f"unset: valuesObject names {LAB_PLATFORM_GHCR}/{COPY}",
              helm["valuesObject"]["kubearmorConfig"]["kubearmorImage"]["image"] == f"{LAB_PLATFORM_GHCR}/{COPY}")
        check(f"unset: the values block names {LAB_PLATFORM_GHCR}/mirror/...",
              f'image: "{LAB_PLATFORM_GHCR}/mirror/kubearmor/kubearmor-relay-server:' in helm["values"])
        helm = fixture_helm(cache.stdout)
        check("set: valuesObject names the copy at the cache path",
              helm["valuesObject"]["kubearmorConfig"]["kubearmorImage"]["image"] == f"{CACHE}/{COPY}")
        check("set: the values block names the cache path",
              f'image: "{CACHE}/mirror/kubearmor/kubearmor-relay-server:' in helm["values"])
        left = naming(cache.stdout, GHCR_OWNER)
        check(f"set: no {GHCR_OWNER} reference is left {left}", not left)

print("== every mirror/ copy a chart pulls, rendered by its chart (#623) ==")
# The root renders each app file alone, unset and at the cache path; the app's own chart is then rendered with
# the helm values the root produced, so what is checked is the image the chart would hand the cluster, whichever
# keys the chart builds it from. The five KubeArmor images the operator has compiled in appear in the render as
# the KubeArmorConfig's fields and the snitch's RELATED_IMAGE_KUBEARMOR_SNITCH env, which is where the operator
# reads them. The upstream charts are fetched from their repositories, so this needs the network.
from mirror_copies import COPIES, UNPULLED, apps as copy_apps  # noqa: E402

WORK = pathlib.Path(tempfile.mkdtemp(prefix="mirror-copies-"))
pulled: dict[tuple[str, str, str], pathlib.Path] = {}


def upstream_chart(src: dict) -> pathlib.Path | str:
    """The app's chart, pulled once into WORK; on failure, Helm's error."""
    key = (src["repoURL"], src["chart"], str(src["targetRevision"]))
    if key not in pulled:
        repo, chart, version = key
        dest = WORK / f"{chart}-{len(pulled)}"
        ref = ([f"oci://{repo.removeprefix('oci://').rstrip('/')}/{chart}"] if not repo.startswith("http")
               else [chart, "--repo", repo])
        r = subprocess.run([HELM, "pull", *ref, "--version", version, "--untar", "--untardir", str(dest)],
                           capture_output=True, text=True)
        if r.returncode:
            return r.stderr.strip()[:200]
        pulled[key] = dest / chart
    return pulled[key]


def chart_render(name: str, app: dict) -> str | None:
    """The app's chart rendered with the helm block the root produced; None (and a FAIL) if it cannot be."""
    sp = app["spec"]
    src = next(s for s in ([sp["source"]] if "source" in sp else sp["sources"]) if "chart" in s)
    chart = upstream_chart(src)
    if not isinstance(chart, pathlib.Path):
        check(f"{name}: chart {src['chart']} {src['targetRevision']} is fetched", False, chart)
        return None
    helm = src.get("helm") or {}
    args = []
    for vf in helm.get("valueFiles", []):
        args += ["-f", str(REPO / vf.removeprefix("$values/"))]
    for key, text in (("values", helm.get("values")), ("valuesObject", helm.get("valuesObject"))):
        if text is not None:
            f = WORK / f"{name}-{key}.yaml"
            f.write_text(text if isinstance(text, str) else yaml.safe_dump(text), encoding="utf-8")
            args += ["-f", str(f)]
    r = subprocess.run([HELM, "template", helm.get("releaseName", app["metadata"]["name"]), str(chart),
                        "-n", sp["destination"]["namespace"], *args], capture_output=True, text=True)
    check(f"{name}: chart {src['chart']} renders with the root's values", r.returncode == 0,
          r.stderr.strip()[:300])
    return r.stdout if r.returncode == 0 else None


def chart_strings(out: str) -> list[str]:
    """Every string in a chart's render; charts emit tags the safe loader rejects, so BaseLoader."""
    return [s for d in yaml.load_all(out, Loader=yaml.BaseLoader) if d for s in strings(d)]


def app_render(name: str, *args: str) -> dict | None:
    r = render(CHART, "--set", f"apps={{{name}}}", *args)
    check(f"{name}: the root renders it alone{' at the cache path' if args else ''}", r.returncode == 0,
          r.stderr.strip()[:200])
    if r.returncode:
        return None
    return next(d for d in yaml.safe_load_all(r.stdout) if d and d.get("kind") == "Application")


def pulls(ref: str, found: list[str]) -> bool:
    """Whether a render names ref itself: a mirror/ copy's path holds the upstream one, so it is bounded."""
    pat = re.compile(r"(?<![\w./-])" + re.escape(ref) + r"(?![\w.-])")
    return any(pat.search(s) for s in found)


for name in copy_apps() + ["falco"]:
    print(f"-- {name}")
    rendered = {}
    for label, args in (("unset", ()), ("cache", ("--set", f"imageRegistry={CACHE}"))):
        app = app_render(name, *args)
        out = chart_render(name, app) if app else None
        rendered[label] = chart_strings(out) if out is not None else None
    if rendered["unset"] is None or rendered["cache"] is None:
        continue
    for c in (c for c in COPIES if name in c.apps):
        check(f"{name}: unset, the chart names {LAB_PLATFORM_GHCR}/{c.path}",
              any(f"{LAB_PLATFORM_GHCR}/{c.path}" in s for s in rendered["unset"]))
        check(f"{name}: at the cache path, the chart names {CACHE}/{c.path}",
              any(f"{CACHE}/{c.path}" in s for s in rendered["cache"]))
        check(f"{name}: nothing names {c.upstream}, the image the copy replaces",
              not pulls(c.upstream, rendered["unset"] + rendered["cache"]))
    left = [s for s in rendered["cache"] if GHCR_OWNER + "/lab-platform" in s]
    check(f"{name}: at the cache path, no {GHCR_OWNER}/lab-platform reference is left {left[:3]}", not left)
    for c in (c for c in UNPULLED if name in c.apps):
        # A copy of a tag the chart no longer pulls: if the chart ever pulls it again, name the copy.
        check(f"{name}: the chart does not pull {c.upstream}, so its copy {c.tag} is rightly not named",
              not pulls(c.upstream, rendered["unset"]))
shutil.rmtree(WORK, ignore_errors=True)

print("== a value no image can be named under fails by name ==")
for bad, why in (("", "empty"), (f"https://{CACHE}", "a scheme"), (f"{CACHE}/", "a trailing slash")):
    r = render(CHART, "-f", str(values_path("attendee")), "--set", f"imageRegistry={bad}")
    check(f"imageRegistry with {why}: the render fails, naming the value", r.returncode != 0
          and "imageRegistry is the registry path lab-platform's images are pulled from" in r.stderr,
          r.stderr.strip()[:200])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All image registry render checks passed.")
