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

3. No row of the two lock files names a Docker Hub image, by host or by having no registry (run 17694's test review
   found a bare `nginx:1.27 sha256:...` row would pass checks 1 and 2, which read image fields and hostnames only).
   Every images.lock row's reference is judged, and so is the reference a kustomize image name's row resolves to; in
   VERSIONS.lock, each `image:` label's reference, a component's value shaped as an image reference, and every
   registry-path reference with a tag or digest. The one exception is RETAINED: #603's retention copy of the
   archived upstream the deployed llm-guard replaced, which nothing pulls or builds on (check 1 holds that) and
   which lab-platform keeps no ghcr.io copy of. It must stay a declared, upstream, saved row, so a new Docker Hub
   row fails, and RETAINED must name only rows that are there.

4. No Markdown page outside the records names a Docker Hub image in a code span. A spec table that says a component
   runs `python:3.12-slim` names Docker Hub, though the cluster runs the ghcr.io copy. A span is read as an image
   when it is shaped as one with a tag or digest; a repo path with a line number (`verify/x.py:9`) and a host and
   port (`agentgateway:3000`) are not. Plans as written (prds/, docs/prd*) are records like the dated ones.

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
# images.lock rows kept on their Docker Hub name on purpose (check 3). laiyer/llm-guard-api:0.3.16 is #603's retention
# copy of the upstream llm-guard image, whose source repo protectai/llm-guard was archived in July 2026: the row
# records the bytes netcup's archive saved (2026-11-05) under the name they were pulled by. The deployed llm-guard is
# llm-guard-cpu-offline's ghcr.io image, and lab-platform has no mirror/ copy of this one (#714's decisions.md entry).
RETAINED = ("laiyer/llm-guard-api:0.3.16",)
# A string shaped as an image reference: lowercase repository path, an optional tag, an optional digest. A digest
# VERSIONS.lock shortens to sha256:60216aaf... still reads as one.
IMAGE_SHAPE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(?::[A-Za-z0-9_][A-Za-z0-9._-]*)?(?:@sha256:[0-9a-f]+(?:\.\.\.)?)?$")

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


def lock_rows(text: str) -> list[tuple[int, list[str], bool]]:
    """(line, columns, whether it sits under the "# Declared:" header) for each images.lock row."""
    rows, declared = [], False
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("# Declared:"):
            declared = True
        if line.strip() and not line.startswith("#"):
            rows.append((n, line.split(), declared))
    return rows


def unregistry(ref: str) -> str:
    return ref.replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR).replace("{{.Values.imageRegistry}}", LAB_PLATFORM_GHCR)


def lock_refs(text: str, kustomize: set[str]) -> list[tuple[str, str]]:
    """(images.lock:line, reference) for every reference a row names, placeholders left out.

    A row's first column is its reference. A kustomize image name (llm-guard, web, postgres) is no pull itself: its
    row's second column is the reference kustomize writes in, and that is judged in its place. A second column that
    is a reference and not a bare digest is judged on any row."""
    out = []
    for n, cols, _ in lock_rows(text):
        ref, second = unregistry(cols[0]), unregistry(cols[1]) if len(cols) > 1 else "-"
        source = cols[2] if len(cols) > 2 else ""
        if source.startswith("not-an-image:"):
            continue
        is_ref = second != "-" and not second.startswith("sha256:")
        if not (ref in kustomize and is_ref):
            out.append((f"images.lock:{n}", ref))
        if is_ref:
            out.append((f"images.lock:{n}", second))
    return out


def versions_refs(text: str) -> list[tuple[str, str]]:
    """(VERSIONS.lock:line, reference) for each image reference VERSIONS.lock names: the first word after an `image:`
    label, whatever it is; a component's value (an unindented line's second column) shaped as a reference with a
    tag, a path or a digest; and anywhere, a reference with a registry path and a tag or digest."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        toks = [t.strip("`,;()'\"") for t in line.split()]
        for i, t in enumerate(toks):
            if not t:
                continue
            last = t.rsplit("/", 1)[-1]
            labelled = i > 0 and toks[i - 1] == "image:"
            value = i == 1 and not line[0].isspace() and IMAGE_SHAPE.match(t) and re.search(r"[:/@]", t)
            pathed = "/" in t and IMAGE_SHAPE.match(t) and (":" in last or "@sha256:" in t)
            if labelled or value or pathed:
                out.append((f"VERSIONS.lock:{n}", t))
    return out


FILE_EXT = re.compile(r"\.(py|sh|tf|ya?ml|md|json|txt|lock|tsv|js|ts|html|go|toml|cfg|ini)$")


def plan(path: str) -> bool:
    """A plan as written: a PRD, under prds/ or a docs/prd* page."""
    return path.startswith("prds/") or path.rsplit("/", 1)[-1].startswith("prd")


def markdown_refs(path: str, text: str) -> list[tuple[str, str]]:
    """(file:line, reference) for each code span on a Markdown page shaped as an image reference with a tag or digest.
    A span whose name is a file (a path with an extension, or one in the repo) is a line reference. A name with no
    path is read only with a version tag, one that opens with a digit and is not all digits: `python:3.12-slim` is an
    image, and `agentgateway:3000` (a host and port), `s3:PutObject` (an IAM action) and `ml_app:burritobot` (a tag)
    are not."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for span in re.findall(r"`([^`\s]+)`", line):
            if not IMAGE_SHAPE.match(span) or not re.search(r":[A-Za-z0-9_]|@sha256:", span):
                continue
            name, _, tag = span.partition("@")[0].partition(":")
            if FILE_EXT.search(name) or (REPO / name).exists():
                continue
            if "/" not in name and not tag[:1].isdigit() or "/" not in name and tag.isdigit():
                continue
            out.append((f"{path}:{n}", span))
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

print("== 3. no lock-file row names a Docker Hub image ==")
LOCK_FIXTURE = (
    "# Declared: fixture\n"
    "nginx:1.27 sha256:" + "0" * 64 + " upstream:https://github.com/nginx/docker-nginx -\n"
    "docker.io/library/busybox:1.38 sha256:" + "1" * 64 + " upstream:x -\n"
    "web ghcr.io/peopleforrester/lab-platform/web@sha256:" + "2" * 64 + " repo:x -\n"
    "stray ghcr.io/x/stray@sha256:" + "3" * 64 + " repo:x -\n"
    "{{.Values.imageRegistry}}/mirror/x/y:1 ghcr.io/peopleforrester/lab-platform/mirror/x/y@sha256:" + "4" * 64
    + " upstream:x -\n"
    "REGISTRY/evil@sha256:REPLACE - not-an-image:placeholder -\n")
found = sorted(r for _, r in lock_refs(LOCK_FIXTURE, {"web"}) if docker_hub(r))
check("an images.lock row with a bare or docker.io name is judged a Docker Hub pull, a kustomize name's ghcr.io "
      "target and a placeholder are not, and a bare name kustomize does not set is",
      found == ["docker.io/library/busybox:1.38", "nginx:1.27", "stray"], str(found))
VERSIONS_FIXTURE = ("redis        bitnami/redis:7.4  (note)\n"
                    "otel         chart 1.0\n"
                    "                       image: the mirror's otel/opentelemetry-collector-contrib:0.160.0\n"
                    "                       image: nginx:1.27 (pinned)\n"
                    "                       see gitops/bootstrap/apps/x.yaml and protectai/llm-guard, schema/config.json\n"
                    "LIVE RESULT: green\n")
found = [r for _, r in versions_refs(VERSIONS_FIXTURE)]
check("VERSIONS.lock's component values, image: labels and tagged registry paths are read, and prose paths are not",
      found == ["bitnami/redis:7.4", "the", "otel/opentelemetry-collector-contrib:0.160.0", "nginx:1.27"], str(found))
check("an image: label that opens with prose is read as such, so it fails as no pinned reference",
      [r for r in found if not (IMAGE_SHAPE.match(r) and re.search(r"[:@]", r))] == ["the"], str(found))
lock_text = (REPO / "images.lock").read_text(encoding="utf-8")
kustomize = {n for _, n in renamed}
lrefs = lock_refs(lock_text, kustomize)
check(f"images.lock's rows are read ({len(lrefs)} references)", len(lrefs) >= 60)
bad = [f"{w}: {r}" for w, r in lrefs if docker_hub(r) and r not in RETAINED]
check("no images.lock row names a Docker Hub image", not bad, "\n      ".join([""] + bad))
vtext = (REPO / "VERSIONS.lock").read_text(encoding="utf-8")
vrefs = versions_refs(vtext)
check(f"VERSIONS.lock's image references are read ({len(vrefs)})", len(vrefs) >= 4)
unshaped = [f"{w}: {r}" for w, r in vrefs if not (IMAGE_SHAPE.match(r) and re.search(r"[:@]", r))]
check("every VERSIONS.lock image: label names a pinned reference (a tag or digest) first", not unshaped,
      "\n      ".join([""] + unshaped))
bad = [f"{w}: {r}" for w, r in vrefs if docker_hub(r) and r not in RETAINED]
check("no VERSIONS.lock image reference is a Docker Hub image", not bad, "\n      ".join([""] + bad))
rows = {cols[0]: (n, cols, declared) for n, cols, declared in lock_rows(lock_text)}
for ref in RETAINED:
    n, cols, declared = rows.get(ref, (0, [], False))
    check(f"RETAINED's {ref} is an images.lock row, so the list holds only what is there", bool(cols))
    check(f"{ref} sits under images.lock's Declared header, which no tracked file pulls", declared)
    check(f"{ref} is an upstream image pinned by digest, its tarball saved (a dated saved column)",
          len(cols) == 4 and cols[1].startswith("sha256:") and cols[2].startswith("upstream:")
          and bool(DATED.fullmatch(cols[3])), " ".join(cols))
    name = re.split(r"[:@]", ref, maxsplit=1)[0]
    pulled = [f"{w}: {r}" for w, r in pulls if re.split(r"[:@]", r.rsplit("/", 1)[-1], maxsplit=1)[0]
              == name.rsplit("/", 1)[-1] and docker_hub(r)]
    check(f"no image field check 1 read pulls {name}", not pulled, str(pulled))

print("== 4. no Markdown page names a Docker Hub image ==")
MD_FIXTURE = ("| guard-proxy | `python:3.12-slim` | `nginxinc/nginx-unprivileged:1.27-alpine` |\n"
              "see `verify/test_x.py:9` and `infra/terraform/aws/cluster/main.tf:229-231`, on `agentgateway:3000`\n"
              "grant `s3:PutObject`, tag `ml_app:burritobot`, base `debian:bookworm-slim`\n"
              "runs `ghcr.io/peopleforrester/watch-it-burn:python-3.12-slim@sha256:" + "5" * 64 + "`, `kubectl`\n")
found = [r for _, r in markdown_refs("fixture.md", MD_FIXTURE)]
check("a Markdown code span naming an image with a path or a version tag is read; a file:line reference, a host and "
      "port, an IAM action, a key:value tag, a bare name with a word tag and a plain word are not",
      found == ["python:3.12-slim", "nginxinc/nginx-unprivileged:1.27-alpine",
                "ghcr.io/peopleforrester/watch-it-burn:python-3.12-slim@sha256:" + "5" * 64], str(found))
mrefs: list[tuple[str, str]] = []
pages = [f for f in files if f.endswith((".md", ".mdx")) and not plan(f)]
for f in pages:
    mrefs += markdown_refs(f, (REPO / f).read_text(encoding="utf-8", errors="replace"))
check(f"Markdown pages' image spans are read ({len(mrefs)} in {len(pages)} pages)", len(mrefs) >= 10)
bad = [f"{w}: {r}" for w, r in mrefs if docker_hub(r)]
check("no Markdown page outside the records names a Docker Hub image", not bad, "\n      ".join([""] + bad))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("Nothing this repo hands a cluster or builds on pulls from Docker Hub.")
