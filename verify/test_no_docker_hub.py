# ABOUTME: Offline gate for #714 (#805): no image this repo hands a cluster or builds on is a Docker Hub pull, by name or
# ABOUTME: by having no registry, and no tracked line names Docker Hub except one marked as refusing it.
"""Why this exists (#805, from #714).

Michael, 2026-10-30, on #714: no Docker Hub anywhere. It costs money and it rate-limits pulls, and a node pulling
anonymously on a fresh cluster is exactly where that bites. Every image a cluster pulls now comes from ghcr.io:
this repo's package, ghcr.io/peopleforrester/watch-it-burn, or lab-platform's mirror/ copies, by digest. Before this
test, nothing held that as a whole: test_enforce_floor judges the directory apps' images only, and a Docker Hub
name added anywhere else would pass every offline test.

Two checks, each of which a new Docker Hub pull fails:

1. No image field or build base resolves to Docker Hub, in any tracked file outside the dated records. A reference with no
   registry (nginx:1.27, busybox, curlimages/curl) is a Docker Hub pull exactly as docker.io/library/nginx is
   (verify/docker_hub.py). The fields read are YAML `image:` keys, with a Helm values map's registry, repository
   and tag joined and an Argo CD Application's `values:` string parsed too; `--image` flags in shell scripts; and,
   in Python, every NAME_IMAGE string and every NAME_IMAGES dict value (ticket_site.py's C6 and room images,
   workshop-mcp's PUBLIC_IMAGES). A build base is one too: a Dockerfile FROM line, a `buildah from` line in any
   tracked file (the Backstage README's), and a shell NAME_BASE= assignment (images/villains/build.sh's JOKER_BASE).
   A name a kustomization or an Application's kustomize.images replaces (llm-guard, set by the ai-layer Application)
   is not a pull, and neither is a placeholder images.lock lists as not-an-image, nor a FROM naming an earlier stage.
2. No tracked line names Docker Hub but to refuse it: `git grep` for its hosts finds only the lines in REFUSED, each
   of which carries a comment with (#714) saying it names Docker Hub to refuse it, and finds each of them, so the
   list cannot go stale. The files in GATE are the one exception: the gate's own three, whose job is naming Docker
   Hub, and the fixtures of #603's live judge, which are the Docker Hub names a node reports for an image it cached.

What a Helm chart renders is test_no_docker_hub_render.py's (tools tier): it renders every Application's sources.

The build side came in with #714's last step, once lab-platform#353's ghcr.io copies of busybox 1.38.0, debian
bookworm-slim and node 24.22.2-trixie-slim answered an anonymous pull (2026-11-05): images/, images.lock and verify/
are inside check 2, and Dockerfile FROM lines, buildah bases and NAME_BASE= assignments inside check 1.
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
from docker_hub import HUB_NAMES, docker_hub, image_fields, live_hub_images  # noqa: E402

# Records kept as written, by path or directory prefix: decisions.md is append-only, and the others say what was
# true when they were written. A path with a date in it (docs/spike-prompt-guard-2-2026-10-28.md, a dated research
# directory) is one too.
RECORDS = ("decisions.md", "PROJECT_STATE.md", "ACTION_ITEMS.md", "transcripts/", "docs/DECISION-LOG.md",
           "docs/RUN-OF-SHOW-2026-08.md")
DATED = re.compile(r"\d{4}-\d{2}-\d{2}")
# The gate itself: the judgement of what Docker Hub is, this file, and the render check. Their fixtures and their lists
# of Docker Hub's names are what they detect, so check 2 does not read them.
GATE = ("verify/docker_hub.py", "verify/test_no_docker_hub.py", "verify/test_no_docker_hub_render.py",
        # #603's live judge takes Docker Hub's host off the name a node reports for an image it pulled before #623 and
        # #714 moved it (images_live.norm, which reads the hosts from docker_hub.py); these fixtures are those names.
        "verify/test_images_lock_live_judge.py")
# (file, the text on the line): the lines that name Docker Hub in order to refuse it. Each carries (#714) in a comment.
REFUSED = (
    # deploy_app refuses a Docker Hub image PUBLIC_IMAGES does not carry, so it lists every name Docker Hub goes by.
    ("gitops/ai-layer/workshop-mcp-server.py", '_DOCKER_HUB = ("", "docker.io", "index.docker.io", "registry-1.docker.io"'),
    # A render must not carry the Docker Hub reference a lab-platform mirror/ copy replaces.
    ("verify/mirror_copies.py", 'HUB = "docker.io"'),
    # The registry rule's lesson: an untrusted registry and Docker Hub's library are both refused at admission.
    ("verify/test_kyverno_cel_policies.py", 'c("docker.io/someone/nginx:1")'),
    ("verify/test_kyverno_cel_policies.py", 'c("docker.io/library/nginx:1.27-alpine")'),
    # images.lock keeps no row for the demo apps' old Docker Hub nginx.
    ("verify/test_demo_app_web_image.py", '"docker.io/library/nginx:1.27-alpine" not in lock'),
    # The run-of-show's C2 fallback row names no Docker Hub image.
    ("verify/test_promo_villains.py", '"docker.io/" not in row'),
    # deploy_app reads a Docker Hub name for PUBLIC_IMAGES' pinned copy, and refuses one the list does not carry.
    ("verify/test_public_images.py", '("docker.io/library/nginx:1.27-alpine", "nginx"), ("docker.io/nginx", "nginx")'),
    ("verify/test_public_images.py", '"docker.io/someone/tron", "index.docker.io/library/tron"'),
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
    """--image flags, NAME_IMAGE= assignments (beat-01.sh's IMAGE, beat-02.sh's CURL_IMAGE) and NAME_BASE= ones
    (images/villains/build.sh's JOKER_BASE, the image crane append builds the Joker on)."""
    refs = []
    for n, line in enumerate(text.splitlines(), 1):
        refs += [(path, str(n), m.group(1)) for m in re.finditer(r"--image[= ]\s*[\"']?([^\"'\s;)]+)", line)]
        m = re.match(r"^\s*(?:export\s+|local\s+|readonly\s+)?(?:[A-Z0-9_]+_)?(?:IMAGE|BASE)=[\"']?([^\"'\s;]+)", line)
        if m:
            refs.append((path, str(n), m.group(1)))
    return refs


def dockerfile_refs(path: str, text: str) -> list[tuple[str, str, str]]:
    """A Dockerfile's FROM lines: flags skipped; scratch and an earlier stage of the same file are not pulls."""
    refs, stages = [], set()
    for n, line in enumerate(text.splitlines(), 1):
        t = line.split()
        if not t or t[0].upper() != "FROM":
            continue
        i = 1
        while i < len(t) and t[i].startswith("--"):
            i += 1
        if i >= len(t):
            continue
        if t[i].lower() != "scratch" and t[i].lower() not in stages:
            refs.append((path, f"{n} FROM", t[i]))
        if i + 2 < len(t) and t[i + 1].upper() == "AS":
            stages.add(t[i + 2].lower())
    return refs


def buildah_refs(path: str, text: str) -> list[tuple[str, str, str]]:
    """`buildah from <image>`, in a script or a README's build steps: the base a by-hand build pulls."""
    return [(path, f"{n} buildah from", m.group(1)) for n, line in enumerate(text.splitlines(), 1)
            for m in re.finditer(r"buildah from\s+(?:--\S+\s+)*[\"']?([^\"'\s;)]+)", line)]


def dockerfile(path: str) -> bool:
    return path.rsplit("/", 1)[-1].lower().startswith(("dockerfile", "containerfile")) or path.endswith(".dockerfile")


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
LIVE = [
    {"kind": "Pod", "metadata": {"namespace": "agent", "name": "tron-1"},
     "spec": {"containers": [{"name": "tron", "image": "trongame/tron:latest"}]},
     "status": {"containerStatuses": [{"name": "tron", "image": "docker.io/trongame/tron:latest"}]}},
    {"kind": "Pod", "metadata": {"namespace": "kubearmor", "name": "relay-1"},
     "spec": {"initContainers": [{"name": "init", "image": "ghcr.io/example/mirror/kubearmor/kubearmor-init:stable"}],
              "containers": [{"name": "relay", "image": "ghcr.io/example/mirror/kubearmor/relay:latest"}]},
     "status": {"containerStatuses": [{"name": "relay", "image": "docker.io/kubearmor/relay:latest"}]}},
    {"kind": "Deployment", "metadata": {"namespace": "agent", "name": "idle"},
     "spec": {"replicas": 0, "template": {"spec": {"containers": [{"name": "w", "image": "nginx:1.27"}]}}}},
    {"kind": "CronJob", "metadata": {"namespace": "ops", "name": "tick"},
     "spec": {"jobTemplate": {"spec": {"template": {"spec": {"containers": [
         {"name": "t", "image": "registry-1.docker.io/library/busybox"}]}}}}}},
    {"kind": "Service", "metadata": {"namespace": "agent", "name": "web"}, "spec": {"ports": [{"port": 80}]}},
    {"kind": "ReplicaSet", "metadata": {"namespace": "apps", "name": "old-revision"},
     "spec": {"replicas": 0, "template": {"spec": {"containers": [{"name": "w", "image": "nginx:1.27"}]}}}},
    {"kind": "ReplicaSet", "metadata": {"namespace": "apps", "name": "live-revision"},
     "spec": {"replicas": 1, "template": {"spec": {"containers": [{"name": "w", "image": "busybox"}]}}}},
    {"kind": "Job", "metadata": {"namespace": "ops", "name": "done"},
     "spec": {"template": {"spec": {"containers": [{"name": "j", "image": "alpine"}]}}},
     "status": {"conditions": [{"type": "Complete", "status": "True"}]}},
    {"kind": "Job", "metadata": {"namespace": "ops", "name": "running"},
     "spec": {"template": {"spec": {"containers": [{"name": "j", "image": "alpine"}]}}}, "status": {"active": 1}},
]
found = live_hub_images(LIVE)
check("the live judge reads a Pod's spec, a scaled-to-0 Deployment's template and a CronJob's job template",
      found == [("Pod/agent/tron-1 containers:tron", "trongame/tron:latest"),
                ("Deployment/agent/idle containers:w", "nginx:1.27"),
                ("CronJob/ops/tick containers:t", "registry-1.docker.io/library/busybox"),
                ("ReplicaSet/apps/live-revision containers:w", "busybox"),
                ("Job/ops/running containers:j", "alpine")], str(found))
check("the live judge leaves out a Deployment's old ReplicaSet at 0 replicas and a finished Job, which start no pod",
      not any("old-revision" in w or "Job/ops/done" in w for w, _ in found), str(found))
check("the live judge leaves a ghcr.io spec alone whatever cached Docker Hub name its status reports",
      not any("relay" in w for w, _ in found), str(found))
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
found = [r for _, _, r in shell_refs("fixture.sh", 'JOKER_BASE="busybox@sha256:' + "0" * 64 + '"\n')]
check("a NAME_BASE= assignment, the base crane append builds on, is read", found == ["busybox@sha256:" + "0" * 64], str(found))
found = [r for _, _, r in dockerfile_refs("Dockerfile", "FROM --platform=$B python:3.12-slim AS build\nFROM build\n"
                                          "FROM scratch\nfrom debian:bookworm-slim\n")]
check("a Dockerfile's FROM lines are read, after flags, and an earlier stage or scratch is not a pull",
      found == ["python:3.12-slim", "debian:bookworm-slim"], str(found))
found = [r for _, _, r in buildah_refs("README.md", "ctr=$(buildah from docker.io/library/node:24)\n")]
check("a `buildah from` base is read", found == ["docker.io/library/node:24"], str(found))
check("a Dockerfile is known by its name", [dockerfile(p) for p in ("images/x/Dockerfile", "a/Containerfile",
      "a/b.dockerfile", "a/Dockerfile.dev", "a/dockerfile.md")] == [True, True, True, True, True])
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
    if dockerfile(f):
        refs += dockerfile_refs(f, text)
    if "buildah from" in text and f not in GATE:  # the gate's own fixture names a Docker Hub base on purpose
        refs += buildah_refs(f, text)
placeholders = not_images()
pulls = judged(refs, placeholders, renamed)
check(f"the scan reads image fields across the repo ({len(pulls)} judged, {len(refs)} found)", len(pulls) >= 40)
bad = sorted({f"{w}: {r}" for w, r in pulls if docker_hub(r)})
check("no image field resolves to Docker Hub", not bad, "\n      ".join([""] + bad[:25]))
for scope in ("gitops/", "games/", "challenges/", "backstage/", "verify/beat-0"):
    check(f"{scope}'s image fields are among those judged", any(w.startswith(scope) for w, _ in pulls))
for where in ("gitops/ai-layer/ticket_site.py", "gitops/ai-layer/workshop-mcp-server.py",
              "images/web-terminal/Dockerfile", "images/watch-it-burn-backstage/packages/backend/Dockerfile",
              "images/watch-it-burn-backstage/README.md", "images/villains/build.sh"):
    check(f"{where}'s images are among those judged", any(w.startswith(where + ":") for w, _ in pulls))
for d, n in (("gitops/ai-layer", "llm-guard"), ("backstage", "postgres"), ("gitops/manifests/demo-app-wombat", "web")):
    check(f"{n}, a name kustomize replaces under {d}/, is judged as replaced there, not as a pull", (d, n) in renamed)
check("images.lock's placeholder REGISTRY/evil-mcp-shim is not judged as a pull",
      "REGISTRY/evil-mcp-shim@sha256:REPLACE_AT_BUILD" in placeholders)

print("== 2. no tracked line names Docker Hub but to refuse it ==")
grep = ["git", "-C", str(REPO), "grep", "-n", "-I"]
for h in HUB_NAMES:
    grep += ["-e", re.escape(h)]
hits = subprocess.run(grep, capture_output=True, text=True).stdout.splitlines()
check(f"git grep finds Docker Hub's names in the tree ({len(hits)} lines), so the sweep is reading", len(hits) > 0)
seen = set()
stray: list[str] = []
unmarked: list[str] = []
for hit in hits:
    path, _, rest = hit.partition(":")
    line = rest.partition(":")[2]
    if recorded(path) or path in GATE:
        continue
    entry = next((e for e in REFUSED if e[0] == path and e[1] in line), None)
    if entry is None:
        stray.append(f"{path}: {line.strip()[:110]}")
    else:
        seen.add(entry)
        if "(#714)" not in line.partition("#")[2]:
            unmarked.append(f"{path}: {line.strip()[:110]}")
check(f"no other line names Docker Hub ({len(stray)} found)", not stray, "\n      ".join([""] + stray[:20]))
check("each of them carries a comment with (#714) saying it names Docker Hub to refuse it", not unmarked,
      "\n      ".join([""] + unmarked))
missing = [e for e in REFUSED if e not in seen]
check("every line REFUSED lists is still in its file, so the list holds only what is there", not missing,
      str(missing))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("Nothing this repo hands a cluster or builds on pulls from Docker Hub.")
