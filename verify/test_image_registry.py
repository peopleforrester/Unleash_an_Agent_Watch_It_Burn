# ABOUTME: Static gate for #622: no file the lab-bootstrap root deploys names ghcr.io/peopleforrester/lab-platform
# ABOUTME: literally; app files take that registry from the root's imageRegistry value, which defaults to it.
#
# Why. lab-platform's packages on ghcr.io are private. Each workshop cluster pulls them through its AWS account's
# ECR pull-through cache, and lab-platform's bootstrap passes the cache path to lab-bootstrap as the Helm value
# imageRegistry (lab-platform#214), e.g. <account>.dkr.ecr.us-west-2.amazonaws.com/lp-shared/peopleforrester/
# lab-platform. A containerd mirror for ghcr.io cannot carry ECR's credential, so the cache only works if the
# reference itself names the cache path. A literal ghcr.io/peopleforrester/lab-platform image anywhere the root
# deploys from is an image that cluster cannot pull. The one place the literal belongs is the chart's default in
# gitops/bootstrap/values.yaml, which infra/deploy-full-idp.sh and an account with no cache get.
#
# Only an apps/ file is rendered with the value (through tpl), so a lab-platform image belongs in an app file's
# Helm values as "{{ .Values.imageRegistry }}/<path>:<tag>". A plain manifest a directory source applies cannot
# take it. test_image_registry_render.py renders the chart with and without the value.
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, CHART, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, REPO, REPO_URL  # noqa: E402

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

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All image registry checks passed.")
