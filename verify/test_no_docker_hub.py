# ABOUTME: Offline gate for #714's pull side (#805): no image this repo hands a cluster is a Docker Hub pull, by name or
# ABOUTME: by having no registry, and nothing a cluster applies or runs names Docker Hub except to refuse it.
"""Why this exists (#805, from #714).

Michael, 2026-10-30, on #714: no Docker Hub anywhere. It costs money and it rate-limits pulls, and a node pulling
anonymously on a fresh cluster is exactly where that bites. Every image a cluster pulls now comes from ghcr.io:
this repo's package, ghcr.io/peopleforrester/watch-it-burn, or lab-platform's mirror/ copies, by digest. Before this
test, nothing held that as a whole: test_enforce_floor judges the directory apps' images only, and a Docker Hub
name added anywhere else would pass every offline test.

Two checks, each of which a new Docker Hub pull fails:

1. No image field resolves to Docker Hub, in any tracked file outside the dated records. A reference with no
   registry (nginx:1.27, busybox, curlimages/curl) is a Docker Hub pull exactly as docker.io/library/nginx is
   (verify/docker_hub.py). The fields read are YAML `image:` keys, with a Helm values map's registry, repository
   and tag joined and an Argo CD Application's `values:` string parsed too; `--image` flags in shell scripts; and,
   in Python, every NAME_IMAGE string and every NAME_IMAGES dict value (ticket_site.py's C6 and room images,
   workshop-mcp's PUBLIC_IMAGES). A name a kustomization or an Application's kustomize.images replaces (llm-guard,
   set by the ai-layer Application) is not a pull, and neither is a placeholder images.lock lists as not-an-image.
2. Nothing a cluster applies or runs names Docker Hub: `git grep` for its hosts finds only the lines in REFUSED,
   which name it in order to refuse it, and finds each of them, so the list cannot go stale.

What a Helm chart renders is test_no_docker_hub_render.py's (tools tier): it renders every Application's sources.

The build side of #714 is not held here, because it is not done: Dockerfile FROM lines, images/villains/build.sh's
JOKER_BASE, the Backstage README's buildah base, images.lock's rows for them, and the two tests that read the
Joker's busybox from Docker Hub wait on lab-platform#353's ghcr.io copies of busybox 1.38.0, debian bookworm-slim and
node 24.22.2-trixie-slim. images/, images.lock and verify/ are outside check 2 and Dockerfiles outside check 1 for
that reason; #714 brings them in when it moves those bases.
"""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
from bootstrap_chart import IMAGE_REGISTRY, LAB_PLATFORM_GHCR  # noqa: E402
from docker_hub import HUB_NAMES, docker_hub, image_fields  # noqa: E402

# Records kept as written, by path or directory prefix: decisions.md is append-only, and the others say what was
# true when they were written. A path with a date in it (docs/spike-prompt-guard-2-2026-10-28.md, a dated research
# directory) is one too.
RECORDS = ("decisions.md", "PROJECT_STATE.md", "ACTION_ITEMS.md", "transcripts/", "docs/DECISION-LOG.md",
           "docs/RUN-OF-SHOW-2026-08.md")
DATED = re.compile(r"\d{4}-\d{2}-\d{2}")
# Check 2's scope ends where #714's build side begins (the docstring says why): the image builds and their lock, and
# the tests, which name Docker Hub to refuse it.
BUILD_AND_TESTS = ("images/", "images.lock", "verify/")
# (file, the text on the line): the lines a cluster runs that name Docker Hub in order to refuse it.
REFUSED = (
    # deploy_app refuses a Docker Hub image PUBLIC_IMAGES does not carry, so it lists every name Docker Hub goes by.
    ("gitops/ai-layer/workshop-mcp-server.py", '_DOCKER_HUB = ("", "docker.io", "index.docker.io", "registry-1.docker.io"'),
    # Its docstring says how those names are read.
    ("gitops/ai-layer/workshop-mcp-server.py", "and nginx under docker.io's"),
)
PLAIN_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def recorded(path: str) -> bool:
    return bool(DATED.search(path)) or any(path == r or (r.endswith("/") and path.startswith(r)) for r in RECORDS)


def tracked() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], check=True, capture_output=True).stdout
    return [f for f in out.decode().split("\0") if f and (REPO / f).is_file() and not recorded(f)]


def not_images() -> set[str]:
    """images.lock's not-an-image rows: placeholders a person fills in, and deliberate bad examples."""
    rows = (REPO / "images.lock").read_text(encoding="utf-8").splitlines()
    return {r.split()[0] for r in rows if r.strip() and not r.startswith("#") and " not-an-image:" in r}


def kustomize_names(doc, path: str) -> set[tuple[str, str]]:
    """(directory, name) for each image name a kustomization or an Application's kustomize.images replaces there.

    Such a name is not a pull in that directory: kustomize writes the replacement in before anything applies it."""
    names: set[tuple[str, str]] = set()
    if not isinstance(doc, dict):
        return names
    if path.rsplit("/", 1)[-1] == "kustomization.yaml":
        here = path.rsplit("/", 1)[0] if "/" in path else ""
        names |= {(here, e["name"]) for e in doc.get("images") or [] if isinstance(e, dict) and e.get("name")}
    spec = doc.get("spec") if isinstance(doc.get("spec"), dict) else {}
    for src in [spec.get("source")] + list(spec.get("sources") or []):
        src = src if isinstance(src, dict) else {}
        for img in (src.get("kustomize") or {}).get("images") or []:
            if isinstance(img, str) and "=" in img and src.get("path"):
                names.add((src["path"].rstrip("/"), img.split("=", 1)[0]))
    return names


def yaml_refs(path: str, text: str) -> tuple[list[tuple[str, str, str]], set[tuple[str, str]]]:
    """(file, where, reference) for each image field in a YAML file, and the names it replaces by kustomize."""
    try:
        docs = list(yaml.load_all(text, Loader=yaml.BaseLoader))
    except yaml.YAMLError:
        # A Helm template or a file the loader cannot read: its image: lines, one by one.
        refs = []
        for n, line in enumerate(text.splitlines(), 1):
            m = re.match(r"^\s*(?:-\s+)?image:\s*[\"']?([^\"'#\s]+)", line)
            if m:
                refs.append((path, str(n), m.group(1)))
        return refs, set()
    refs, renamed = [], set()
    for d in docs:
        refs += [(path, where, ref) for where, ref in image_fields(d)]
        renamed |= kustomize_names(d, path)
    return refs, renamed


def shell_refs(path: str, text: str) -> list[tuple[str, str, str]]:
    """--image flags, and NAME_IMAGE= assignments (beat-01.sh's IMAGE, beat-02.sh's CURL_IMAGE)."""
    refs = []
    for n, line in enumerate(text.splitlines(), 1):
        refs += [(path, str(n), m.group(1)) for m in re.finditer(r"--image[= ]\s*[\"']?([^\"'\s;)]+)", line)]
        m = re.match(r"^\s*(?:export\s+|local\s+|readonly\s+)?(?:[A-Z0-9_]+_)?IMAGE=[\"']?([^\"'\s;]+)", line)
        if m:
            refs.append((path, str(n), m.group(1)))
    return refs


def python_refs(path: str, text: str) -> list[tuple[str, str, str]]:
    """NAME_IMAGE strings and NAME_IMAGES dict values at a module's top level."""
    refs = []
    for node in ast.parse(text, filename=path).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for t in targets:
            if not isinstance(t, ast.Name) or node.value is None:
                continue
            if t.id.endswith("_IMAGE") and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                refs.append((path, f"{node.lineno} {t.id}", node.value.value))
            elif t.id.endswith("_IMAGES") and isinstance(node.value, ast.Dict):
                refs += [(path, f"{v.lineno} {t.id}", v.value) for v in node.value.values
                         if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    return refs


def replaced(path: str, ref: str, renamed: set[tuple[str, str]]) -> bool:
    name = re.split(r"[:@]", ref, maxsplit=1)[0]
    return any(name == n and (d == "" or path.startswith(d + "/")) for d, n in renamed)


def judged(refs: list[tuple[str, str, str]], placeholders: set[str], renamed: set[tuple[str, str]]) -> list[tuple[str, str]]:
    """(file and where, reference) for each one a pull would resolve: a placeholder, a name kustomize replaces in
    that directory and template text are not pulls."""
    out = []
    for path, where, ref in refs:
        ref = ref.replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR).replace("{{.Values.imageRegistry}}", LAB_PLATFORM_GHCR)
        if ref not in placeholders and not replaced(path, ref, renamed) and PLAIN_REF.match(ref):
            out.append((f"{path}:{where}", ref))
    return out


print("== the judgement itself ==")
for ref, hub in (("nginx:1.27", True), ("busybox", True), ("curlimages/curl:8.10.1", True),
                 ("docker.io/library/nginx:1.27-alpine", True), ("index.docker.io/x/y", True),
                 ("registry-1.docker.io/library/busybox", True),
                 ("ghcr.io/peopleforrester/watch-it-burn:nginx-1.27-alpine", False),
                 ("public.ecr.aws/docker/library/busybox:1.38.0", False),
                 ("localhost:5000/x", False), ("registry.k8s.io/pause:3.9", False)):
    check(f"{ref} {'is' if hub else 'is not'} a Docker Hub pull", docker_hub(ref) is hub)
FIXTURE_YAML = """
spec:
  template: {spec: {containers: [{name: a, image: "nginx:1.27"}]}}
---
spec:
  source:
    helm:
      valuesObject:
        image: {registry: "", repository: falcosecurity/falco, tag: "0.45.1"}
      values: |
        relay:
          image: kubearmor/kubearmor-relay-server:latest
"""
found = sorted(r for _, r in judged(yaml_refs("fixture.yaml", FIXTURE_YAML)[0], set(), set()) if docker_hub(r))
check("a pod image, a Helm values map and an Application's values string are each read and judged", found == [
    "falcosecurity/falco:0.45.1", "kubearmor/kubearmor-relay-server:latest", "nginx:1.27"], str(found))
found = [r for _, _, r in python_refs("fixture.py", 'C6_IMAGE = "busybox:1.38"\nPUBLIC_IMAGES = {"web": "nginx"}\n'
                                      'SHELL_IMAGES = ("busybox",)\n')]
check("a Python NAME_IMAGE string and NAME_IMAGES dict value are read, a tuple of names is not",
      found == ["busybox:1.38", "nginx"], str(found))
found = [r for _, _, r in shell_refs("fixture.sh", 'kubectl run x --image=curlimages/curl:8 --restart=Never\n'
                                     'readonly CURL_IMAGE="curlimages/curl:8.10.1"\nIMAGE="${1:?usage}"\n')]
check("a --image flag and a NAME_IMAGE= assignment in a shell script are read",
      found == ["curlimages/curl:8", "curlimages/curl:8.10.1", "${1:?usage}"], str(found))
names = kustomize_names(yaml.safe_load("images: [{name: web, newName: ghcr.io/x/web}]"), "demo/kustomization.yaml")
found = [w for w, _ in judged([("demo/deployment.yaml", "", "web"), ("other/deployment.yaml", "", "web")], set(), names)]
check("a name a kustomization replaces is a pull everywhere but under that kustomization's directory",
      found == ["other/deployment.yaml:"], str(found))

print("== 1. no image field resolves to Docker Hub ==")
files = tracked()
refs: list[tuple[str, str, str]] = []
renamed: set[tuple[str, str]] = set()
for f in files:
    text = (REPO / f).read_text(encoding="utf-8", errors="replace")
    if f.endswith((".yml", ".yaml")):
        found_refs, names = yaml_refs(f, text)
        refs += found_refs
        renamed |= names
    elif f.endswith(".sh"):
        refs += shell_refs(f, text)
    elif f.endswith(".py") and "IMAGE" in text:
        refs += python_refs(f, text)
placeholders = not_images()
pulls = judged(refs, placeholders, renamed)
check(f"the scan reads image fields across the repo ({len(pulls)} judged, {len(refs)} found)", len(pulls) >= 40)
bad = sorted({f"{w}: {r}" for w, r in pulls if docker_hub(r)})
check("no image field resolves to Docker Hub", not bad, "\n      ".join([""] + bad[:25]))
for scope in ("gitops/", "games/", "challenges/", "backstage/", "verify/beat-0"):
    check(f"{scope}'s image fields are among those judged", any(w.startswith(scope) for w, _ in pulls))
for where in ("gitops/ai-layer/ticket_site.py", "gitops/ai-layer/workshop-mcp-server.py"):
    check(f"{where}'s images are among those judged", any(w.startswith(where) for w, _ in pulls))
for d, n in (("gitops/ai-layer", "llm-guard"), ("backstage", "postgres"), ("gitops/manifests/demo-app-wombat", "web")):
    check(f"{n}, a name kustomize replaces under {d}/, is judged as replaced there, not as a pull", (d, n) in renamed)
check("images.lock's placeholder REGISTRY/evil-mcp-shim is not judged as a pull",
      "REGISTRY/evil-mcp-shim@sha256:REPLACE_AT_BUILD" in placeholders)

print("== 2. nothing a cluster applies or runs names Docker Hub but to refuse it ==")
grep = ["git", "-C", str(REPO), "grep", "-n", "-I"]
for h in HUB_NAMES:
    grep += ["-e", re.escape(h)]
hits = subprocess.run(grep, capture_output=True, text=True).stdout.splitlines()
check(f"git grep finds Docker Hub's names in the tree ({len(hits)} lines), so the sweep is reading", len(hits) > 0)
seen = set()
stray = []
for hit in hits:
    path, _, rest = hit.partition(":")
    line = rest.partition(":")[2]
    if recorded(path) or path.startswith(BUILD_AND_TESTS):
        continue
    entry = next((e for e in REFUSED if e[0] == path and e[1] in line), None)
    if entry is None:
        stray.append(f"{path}: {line.strip()[:110]}")
    else:
        seen.add(entry)
check(f"no other line names Docker Hub ({len(stray)} found)", not stray, "\n      ".join([""] + stray[:20]))
missing = [e for e in REFUSED if e not in seen]
check("every line REFUSED lists is still in its file, so the list holds only what is there", not missing,
      str(missing))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("Nothing this repo hands a cluster pulls from Docker Hub.")
