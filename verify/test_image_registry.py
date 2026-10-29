# ABOUTME: Static gate for #622: no file the lab-bootstrap root deploys names ghcr.io/peopleforrester/lab-platform
# ABOUTME: literally; app files take that registry from the root's imageRegistry value, which defaults to it.
#
# Why. A root can pass lab-bootstrap an ECR pull-through cache path as the Helm value imageRegistry, e.g.
# <account>.dkr.ecr.us-west-2.amazonaws.com/lp-shared/peopleforrester/lab-platform, as lab-platform's bootstrap did
# (lab-platform#214) until 5192c1a reverted it; the packages are public, so today every root takes the default. A
# containerd mirror for ghcr.io cannot carry ECR's credential, so a cache only works if the reference itself names
# the cache path, and a literal ghcr.io/peopleforrester/lab-platform image anywhere the root deploys from is one
# such a cluster would not pull through it. The one place the literal belongs is the chart's default in
# gitops/bootstrap/values.yaml, which infra/deploy-full-idp.sh and every root that passes nothing get.
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

# The one literal path allowed is promo/, Challenge 2's villains (#653). /lab hands the student that reference to paste
# into a chat, and the cluster pulls it as typed: it is the unvetted image the lesson is about, not one the root
# deploys, and restrict-image-registries refuses it wherever it appears, a cache path included.
PROMO = f"{LAB_PLATFORM_GHCR}/promo/"
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
            if LAB_PLATFORM_GHCR in uncommented(line).replace(PROMO, ""):
                literal.append(f"{p.relative_to(REPO)}:{i}")
check(f"files were read ({scanned})", scanned > 100)
check(f"no file names {LAB_PLATFORM_GHCR} outside a comment or {PROMO}; an app file says {IMAGE_REGISTRY} instead "
      f"{literal}", not literal)
handed = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
check(f"the {PROMO} exemption is in use: /lab hands out the C2 villains there", PROMO in handed)

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

print("== each mirror/ copy a chart pulls is named in its app files, through the value (#623) ==")
# test_image_registry_render.py renders each chart to see the whole reference; this is the offline half: the
# table is self-consistent and every app file it names says the copy's tag and the value.
from mirror_copies import COPIES, UNPULLED  # noqa: E402


def code(name: str) -> str:
    return "\n".join(uncommented(ln) for ln in (APPS / f"{name}.yaml").read_text(encoding="utf-8").splitlines())


for c in COPIES + UNPULLED:
    check(f"{c.path}: the tag ends in the first twelve characters of {c.digest[:19]}...",
          c.digest.startswith("sha256:") and len(c.digest) == 71 and c.tag.endswith("-" + c.digest[7:19]))
for c in COPIES:
    for app in c.apps:
        text = code(app)
        check(f"{app}.yaml names {c.path.split(':')[0]} by its tag {c.tag}, under {IMAGE_REGISTRY}/mirror",
              f'{c.tag}"' in text and f'"{IMAGE_REGISTRY}/mirror' in text)
for c in UNPULLED:
    named = [p.name for p in sorted(APPS.glob("*.yaml")) if c.tag in code(p.stem)]
    check(f"{c.path}, a copy of a tag no chart pulls, is named nowhere {named}", not named)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All image registry checks passed.")
