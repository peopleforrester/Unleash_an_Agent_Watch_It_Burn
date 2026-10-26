# ABOUTME: Renders gitops/bootstrap with the pinned Helm with and without imageRegistry (#622): set, no
# ABOUTME: ghcr.io/peopleforrester reference is left; unset, the render is today's, lab-platform images on ghcr.io.
# SUITE: e2e (needs helm: the chart is Helm's to render)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. lab-platform's bootstrap passes each cluster's ECR pull-through cache path to lab-bootstrap as imageRegistry
# (lab-platform#214), because its ghcr.io packages are private and a node can only pull them through the cache.
# infra/deploy-full-idp.sh passes nothing, and must get the render it gets today. test_image_registry.py holds
# that no file names the registry literally; this asks Helm what the value does to every profile's render, and,
# through a fixture app in a copy of the chart, that an app naming a mirror/ copy as the value says is rendered
# at the cache path when it is set and at ghcr.io when it is not.
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import CHART, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, profiles, values_path  # noqa: E402

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
