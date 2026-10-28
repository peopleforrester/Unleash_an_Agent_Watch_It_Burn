# ABOUTME: Static gate for #622 and #623: nothing lab-bootstrap deploys names ghcr.io/peopleforrester/lab-platform
# ABOUTME: literally, and every mirror/ copy a chart pulls is named through the root's imageRegistry, by its digest tag.
#
# Why. lab-bootstrap takes the registry lab-platform's images come from as the Helm value imageRegistry, default
# ghcr.io/peopleforrester/lab-platform. lab-platform#214 passed each cluster's ECR pull-through cache path there,
# when those packages were private; lab-platform 5192c1a reverted that, the packages are public (the mirror/
# copies were read back anonymously on 2026-10-28), and today nothing passes the value. It stays the one switch
# that points every lab-platform image at a cache or another mirror at once, which only works if the reference
# itself names the value. A literal ghcr.io/peopleforrester/lab-platform image anywhere the root deploys from is
# an image that switch misses. The one place the literal belongs is the chart's default in
# gitops/bootstrap/values.yaml, which infra/deploy-full-idp.sh gets.
#
# Only an apps/ file is rendered with the value (through tpl), so a lab-platform image belongs in an app file's
# Helm values as "{{ .Values.imageRegistry }}/<path>:<tag>". A plain manifest a directory source applies cannot
# take it. test_image_registry_render.py renders the chart with and without the value, and the charts themselves.
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import (APPS, CHART, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, MIRROR_COPIES,  # noqa: E402
                             MIRROR_COPIES_NOT_PULLED, REPO, REPO_URL, chart_helm, mirror_reference)

failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


def sources(app: dict) -> list[dict]:
    sp = app.get("spec") or {}
    return ([sp["source"]] if "source" in sp else []) + list(sp.get("sources") or [])


def uncommented(line: str) -> str:
    """The line without a YAML or shell comment: a comment can say where an image comes from."""
    if line.lstrip().startswith("#"):
        return ""
    return line.split(" #", 1)[0]


print("== the root's default is ghcr.io/peopleforrester/lab-platform ==")
DEFAULT_FILE = CHART / "values.yaml"
check(f"values.yaml sets imageRegistry to {LAB_PLATFORM_GHCR}",
      (yaml.safe_load(DEFAULT_FILE.read_text(encoding="utf-8")) or {}).get("imageRegistry") == LAB_PLATFORM_GHCR)

print("== nothing the root deploys names the registry literally ==")
# gitops/ whole (the chart, every Helm values file a source reads by $values, apps-disabled too), and every other
# Unleashed path an app file sources.
roots = {REPO / "gitops"}
for f in sorted(APPS.glob("*.yaml")):
    for d in yaml.safe_load_all(f.read_text(encoding="utf-8")):
        for s in sources(d or {}):
            url = s.get("repoURL", "").rstrip("/").removesuffix(".git").lower()
            if url == REPO_URL.removesuffix(".git").lower() and s.get("path"):
                roots.add(REPO / s["path"])
missing = sorted(str(r.relative_to(REPO)) for r in roots if not r.is_dir())
check(f"every Unleashed source path is a directory {missing}", not missing)
check("the sweep reaches beyond gitops/ (policies/, security/, observability-idp/)",
      {"policies", "security", "observability-idp"} <= {r.relative_to(REPO).parts[0] for r in roots})

literal = []
scanned = 0
for root in sorted(roots):
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p == DEFAULT_FILE:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        for i, line in enumerate(text.splitlines(), 1):
            if LAB_PLATFORM_GHCR in uncommented(line):
                literal.append(f"{p.relative_to(REPO)}:{i}")
check(f"files were read ({scanned})", scanned > 100)
check(f"no file names {LAB_PLATFORM_GHCR} outside a comment; an app file says {IMAGE_REGISTRY} instead {literal}",
      not literal)

print("== the value is only used where tpl renders it ==")
# A plain manifest or a $values file reaches the cluster as written, so the template text would be the image.
outside = []
for root in sorted(roots):
    for p in sorted(root.rglob("*")):
        if not p.is_file() or APPS in p.parents or p == DEFAULT_FILE:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if any(IMAGE_REGISTRY in uncommented(ln) for ln in text.splitlines()):
            outside.append(str(p.relative_to(REPO)))
check(f"{IMAGE_REGISTRY} appears only in apps/ files, the ones the chart renders {outside}", not outside)

print("== every mirror/ copy a chart pulls is named through the value, by its digest-suffixed tag (#623) ==")
# lab-platform's deploy/mirror/copies.tsv (lab-platform#183): a copy's tag is the upstream tag with the first twelve
# characters of its linux/amd64 digest appended, so it never moves. test_image_registry_render.py renders each chart
# and finds the copy in the pod spec, and no upstream reference a copy replaces.
digest_tag = re.compile(r"^[a-z0-9./-]+:[\w.-]+-[0-9a-f]{12}$")
for copy in [c for _, c, _, _ in MIRROR_COPIES] + [c for _, c in MIRROR_COPIES_NOT_PULLED]:
    check(f"{copy} is a path under mirror/ and a digest-suffixed tag", bool(digest_tag.match(copy)))


def application(name: str) -> dict:
    docs = yaml.safe_load_all((APPS / f"{name}.yaml").read_text(encoding="utf-8"))
    return next((d for d in docs if d and d.get("kind") == "Application"), {})


app_docs = {a: application(a) for _, _, apps, _ in MIRROR_COPIES for a in apps}
for upstream, copy, apps, where in MIRROR_COPIES:
    for app in apps:
        got = mirror_reference(chart_helm(app_docs[app]), where)
        want = f"{IMAGE_REGISTRY}/mirror/{copy}"
        check(f"apps/{app}.yaml names {upstream} as {want}" + ("" if got == want else f" (it says {got!r})"),
              got == want)
# The operator reads the pinned images only with imagePinning on, and they are the only way to set the snitch.
check("apps/kubearmor.yaml turns imagePinning on, so the operator runs the five KubeArmorConfig images from mirror/",
      chart_helm(app_docs["kubearmor"]).get("imagePinning") is True)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All image registry checks passed.")
