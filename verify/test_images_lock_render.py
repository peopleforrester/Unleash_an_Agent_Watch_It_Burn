# ABOUTME: E2E gate for #603: every image a chart render or kustomize build of gitops/bootstrap/apps hands a cluster,
# ABOUTME: and every image the Argo CD chart deploy-full-idp.sh installs, has an images.lock row with its digest.
# SUITE: e2e (needs helm, kubectl kustomize, and the network for each app's upstream chart)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Why this exists (#603, from the follow-up run 12649 left on it).

The fleet's image-retention rule (claude-config/rules/infra/image-retention.md in llm-coding-workflow) gives every
image a repo depends on an images.lock row: its digest, where its source lives, and the date its tarball was saved.
llm-coding-workflow's scripts/mirror-images.sh finds the images a tracked file names on an `image:` line or a FROM
line, and test_images_lock.py holds those to rows. The images a Helm chart pulls (Argo CD, Kyverno, cert-manager,
Istio, kagent and the rest) are named in the chart, not here, so neither of them sees one, and a chart bump that
brings a new image would leave it with no saved copy and no recorded digest.

This renders what Argo CD would hand the cluster, through verify/app_render.py (the render #805's Docker Hub gate
uses), plus the Argo CD chart at the version and values infra/deploy-full-idp.sh installs it with, and holds every
image it finds to a row. A row covers a rendered reference when its ref is the reference; when its ref, with the
root's `{{.Values.imageRegistry}}` filled in with the default, is the reference; or when the reference pins a digest
and the row's digest is that same name@sha256 (a kustomize image name such as `llm-guard`, whose row records what it
is set to). The rows' columns are test_images_lock.py's to judge, and save is mirror-images.sh's.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from app_render import Renderer, pulled_images  # noqa: E402
from bootstrap_chart import LAB_PLATFORM_GHCR, REPO  # noqa: E402

LOCK = REPO / "images.lock"
IDP = REPO / "infra/deploy-full-idp.sh"
REGISTRY_TEMPLATES = ("{{.Values.imageRegistry}}", "{{ .Values.imageRegistry }}")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def strip_tag(ref: str) -> str:
    """name@sha256:... for a reference that pins a digest, its tag dropped; "" for one that pins none."""
    if "@" not in ref:
        return ""
    name, digest = ref.split("@", 1)
    last = name.rsplit("/", 1)
    if ":" in last[-1]:
        name = name[: len(name) - len(last[-1])] + last[-1].split(":", 1)[0]
    return f"{name}@{digest}"


def row_keys(ref: str, digest: str) -> set[str]:
    """The rendered references a row covers."""
    keys = {ref}
    for t in REGISTRY_TEMPLATES:
        if ref.startswith(t):
            keys.add(LAB_PLATFORM_GHCR + ref[len(t):])
    if "@sha256:" in digest:
        keys.add(digest)
    if strip_tag(ref):
        keys.add(strip_tag(ref))
    return keys


def covered(ref: str, keys: set[str]) -> bool:
    return ref in keys or (bool(strip_tag(ref)) and strip_tag(ref) in keys)


HELM = shutil.which("helm")
KUBECTL = shutil.which("kubectl")
if not HELM or not KUBECTL:
    print("FAIL: helm and kubectl must be on PATH (run through verify/run-e2e-tools.sh, which puts the pinned ones "
          "first)", file=sys.stderr)
    sys.exit(1)
if not LOCK.is_file():
    print(f"FAIL: {LOCK.relative_to(REPO)} is missing", file=sys.stderr)
    sys.exit(1)

print("== the matching, on known rows ==")
fixture = set()
for r, d in [("{{.Values.imageRegistry}}/mirror/x/y:1-abc", "ghcr.io/peopleforrester/lab-platform/mirror/x/y@sha256:"
              + "a" * 64), ("llm-guard", "ghcr.io/o/llm-guard@sha256:" + "b" * 64), ("quay.io/x/z:1", "sha256:" + "c" * 64)]:
    fixture |= row_keys(r, d)
check("a templated row covers its default-registry render",
      covered("ghcr.io/peopleforrester/lab-platform/mirror/x/y:1-abc", fixture))
check("a kustomize-name row covers the name@digest it is set to, tag or no tag",
      covered("ghcr.io/o/llm-guard:v1@sha256:" + "b" * 64, fixture) and covered("ghcr.io/o/llm-guard@sha256:" + "b" * 64,
                                                                                fixture))
check("a plain row covers its own ref, and nothing covers another tag or digest",
      covered("quay.io/x/z:1", fixture) and not covered("quay.io/x/z:2", fixture)
      and not covered("ghcr.io/o/llm-guard:v1@sha256:" + "d" * 64, fixture))

keys: set[str] = set()
for line in LOCK.read_text(encoding="utf-8").splitlines():
    parts = line.split()
    if len(parts) >= 3 and not line.startswith("#"):
        keys |= row_keys(parts[0], parts[1])

renderer = Renderer(HELM, KUBECTL, check)
found: dict[str, str] = {}
apps = renderer.apps()
print(f"== every source of every Application, {len(apps)} apps/ files ==")
for name in apps:
    rendered = renderer.app(name)
    for images, docs in rendered or []:
        for obj, _where, ref in pulled_images(docs, images):
            found.setdefault(ref, f"{name}: {obj}")
check(f"the chart sources are read ({renderer.charts} rendered)", renderer.charts >= 15)

print("== the Argo CD chart deploy-full-idp.sh installs ==")
idp = IDP.read_text(encoding="utf-8")
repo_url = re.search(r"repo add argo (\S+)", idp)
install = re.search(r"argo/argo-cd --version (\S+)\s*\\?\s*\n?.*?--values \"\$\{SCRIPT_DIR\}/(\S+?)\"", idp, re.S)
check("infra/deploy-full-idp.sh adds the argo repo and installs argo/argo-cd --version <v> --values <file>",
      bool(repo_url and install), "the literals 'repo add argo' and 'argo/argo-cd --version' are not in it")
if repo_url and install:
    app = {"metadata": {"name": "argocd"}, "spec": {"destination": {"namespace": "argocd"}}}
    src = {"chart": "argo-cd", "repoURL": repo_url.group(1), "targetRevision": install.group(1),
           "helm": {"releaseName": "argocd", "valueFiles": [f"infra/{install.group(2)}"]}}
    docs = renderer.source_docs("argocd", app, src, 0)
    for obj, _where, ref in pulled_images(docs or [], []):
        found.setdefault(ref, f"argocd: {obj}")
renderer.close()

print(f"== every one of the {len(found)} rendered images has an images.lock row ==")
missing = [(ref, where) for ref, where in found.items() if not covered(ref, keys)]
for ref, where in missing:
    print(f"        {where}  {ref}")
check(f"no rendered image without a row ({len(missing)} missing: add a row with its digest and source, then run "
      "mirror-images.sh save on netcup)", not missing)
check("the render finds Argo CD, Istio and Kyverno, so the rows are not judged against an empty list",
      all(any(n in ref for ref in found) for n in ("argoproj/argocd", "istio.io/release/pilot", "kyverno/kyverno:")))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every image the renders hand a cluster has an images.lock row.")
