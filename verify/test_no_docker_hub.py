# ABOUTME: Offline gate for #714: no tracked file names Docker Hub but the refused examples listed here, no image field
# ABOUTME: is a bare name that Docker Hub would serve, and every watch-it-burn tag a cluster runs names a version.
"""Why this exists (#714).

Michael, 2026-10-30: no Docker Hub anywhere. It costs money and it rate-limits pulls, and a node pulling
anonymously on a fresh cluster is exactly where that bites. Every image this repo builds or pulls comes from
ghcr.io: our own package, ghcr.io/peopleforrester/watch-it-burn, or lab-platform's mirror/ copies, by digest.

Three checks, each of which a new Docker Hub reference fails:

1. `git grep "docker.io"` (and hub.docker.com) finds only the lines in REFUSED, each of which carries a comment
   saying it names Docker Hub to refuse it, and finds every one of them, so the list cannot go stale. RECORDS are
   files that keep their words as written: decisions.md is append-only, and the others are dated records of what
   was true then. This file is left out too, since it has to name what it looks for.
2. No image field resolves to Docker Hub by being bare. A reference whose first path component has no "." or ":"
   (nginx:1.27, busybox, curlimages/curl) is a Docker Hub pull, exactly as an explicit docker.io/ one is. The
   fields read are YAML `image:` keys, with a Helm values map's registry and repository joined and an Argo CD
   Application's `values:` string parsed too, Dockerfile FROM lines, and `kubectl --image` flags in shell scripts.
   A kustomize image name (llm-guard, set by the ai-layer Application) is not a pull and is judged as replaced.
3. Every ghcr.io/peopleforrester/watch-it-burn tag that gitops/ or the C6 build names carries a version
   (Michael, 2026-10-30, on #714: a tag must match the version of the software inside). That the version is the
   one inside each image is verify/test_image_version_tags.py's (tools tier), which reads it from the image.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
from image_refs import from_refs  # noqa: E402

SELF = "verify/test_no_docker_hub.py"
# Records kept as written, by path or directory prefix.
RECORDS = ("decisions.md", "transcripts/", "ACTION_ITEMS.md", "docs/DECISION-LOG.md", "docs/RUN-OF-SHOW-2026-08.md",
           "docs/spike-prompt-guard-2-2026-10-28.md")
# (file, the text on the line): the lines that name Docker Hub on purpose, to refuse it.
REFUSED = (
    ("verify/test_kyverno_cel_policies.py", 'pod("docker-user", "apps", [c("docker.io/someone/nginx:1")])'),
    ("verify/test_kyverno_cel_policies.py", 'pod("docker-library", "apps", [c("docker.io/library/nginx:1.27-alpine")])'),
    ("verify/mirror_copies.py", 'HUB = "docker.io"'),
)
HUB_HOSTS = ("docker.io", "index.docker.io", "registry-1.docker.io")
# Not pulls: a value a person fills in before anything applies it (images.lock lists each as not-an-image).
PLACEHOLDERS = {"REGISTRY/evil-mcp-shim@sha256:REPLACE_AT_BUILD"}
IMAGE_REGISTRY_DEFAULT = "ghcr.io/peopleforrester/lab-platform"
PLAIN_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$")
OURS = re.compile(r"ghcr\.io/peopleforrester/watch-it-burn:([A-Za-z0-9._${}-]+)")
VERSIONED = re.compile(r"-v?\d+(\.\d+)+(\b|-|$)")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def recorded(path: str) -> bool:
    return any(path == r or (r.endswith("/") and path.startswith(r)) for r in RECORDS)


def tracked() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], check=True, capture_output=True).stdout
    return [f for f in out.decode().split("\0") if f and (REPO / f).is_file() and not recorded(f)]


def docker_hub(ref: str) -> bool:
    """Whether a pull of ref goes to Docker Hub: an explicit Docker Hub host, or no host at all."""
    ref = ref.replace("{{ .Values.imageRegistry }}", IMAGE_REGISTRY_DEFAULT)
    ref = ref.replace("{{.Values.imageRegistry}}", IMAGE_REGISTRY_DEFAULT)
    first = ref.split("/", 1)[0]
    if "/" in ref and ("." in first or ":" in first or first == "localhost"):
        return first in HUB_HOSTS
    return True


def templated(ref: str) -> bool:
    return "$" in ref or "{{" in ref.replace("{{ .Values.imageRegistry }}", "").replace("{{.Values.imageRegistry}}", "")


print("== 1. nothing names Docker Hub but the refused examples ==")
hits = subprocess.run(["git", "-C", str(REPO), "grep", "-n", "-I", "-e", r"docker\.io", "-e", "hub.docker.com"],
                      capture_output=True, text=True).stdout.splitlines()
found = set()
stray = []
for hit in hits:
    path, _, rest = hit.partition(":")
    line = rest.partition(":")[2]
    if recorded(path) or path == SELF:
        continue
    entry = next((e for e in REFUSED if e[0] == path and e[1] in line), None)
    if entry is None:
        stray.append(f"{path}: {line.strip()[:110]}")
        continue
    found.add(entry)
    check(f"{path}: the refused example says so on its line ({entry[1][:50]})",
          "(#714)" in line and "refuse" in line.lower(), line.strip())
check(f"no other line names Docker Hub ({len(stray)} found)", not stray, "\n      ".join([""] + stray[:20]))
missing = [e for e in REFUSED if e not in found]
check("every refused example listed here is still in its file, so the list holds only what is there", not missing,
      str(missing))

print("== 2. no image field is a bare name Docker Hub would serve ==")


def walk(node, where: str, refs: list[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "image" and isinstance(v, str):
                refs.append((where, v))
            elif k == "image" and isinstance(v, dict) and isinstance(v.get("repository"), str):
                reg = v.get("registry")
                refs.append((where, f"{reg}/{v['repository']}" if isinstance(reg, str) and reg else v["repository"]))
            elif k == "values" and isinstance(v, str) and "image" in v:
                try:
                    for d in yaml.safe_load_all(v):
                        walk(d, where + " (values)", refs)
                except yaml.YAMLError:
                    pass
            else:
                walk(v, where, refs)
    elif isinstance(node, list):
        for v in node:
            walk(v, where, refs)


def kustomize_names(doc) -> set[str]:
    """Image names a kustomization or an Application's kustomize.images replaces, which are not pulls themselves."""
    names = set()
    if not isinstance(doc, dict):
        return names
    for entry in doc.get("images") or []:
        if isinstance(entry, dict) and entry.get("name"):
            names.add(entry["name"])
    spec = doc.get("spec") if isinstance(doc.get("spec"), dict) else {}
    for src in [spec.get("source")] + list(spec.get("sources") or []):
        for img in ((src or {}).get("kustomize") or {}).get("images") or []:
            if isinstance(img, str) and "=" in img:
                names.add(img.split("=", 1)[0])
    return names


refs: list[tuple[str, str]] = []
renamed: set[str] = set()
files = tracked()
for f in files:
    base = f.rsplit("/", 1)[-1]
    text = (REPO / f).read_text(encoding="utf-8", errors="replace")
    if base.endswith((".yml", ".yaml")):
        try:
            docs = list(yaml.load_all(text, Loader=yaml.BaseLoader))
        except yaml.YAMLError:
            # A Helm template or a multi-part file the loader cannot read: its image: lines, one by one.
            docs = []
            for n, line in enumerate(text.splitlines(), 1):
                m = re.match(r"^\s*(?:-\s+)?image:\s*[\"']?([^\"'#\s]+)", line)
                if m:
                    refs.append((f"{f}:{n}", m.group(1)))
        for d in docs:
            walk(d, f, refs)
            renamed |= kustomize_names(d)
    elif re.match(r"^(Dockerfile|Containerfile)(\..*)?$|.*\.[Dd]ockerfile$", base):
        refs += [(f"{f}:{n}", r) for n, r in from_refs(text)]
    elif base.endswith(".sh"):
        for n, line in enumerate(text.splitlines(), 1):
            for m in re.finditer(r"--image[= ]\s*[\"']?([^\"'\s;)]+)", line):
                refs.append((f"{f}:{n}", m.group(1)))

judged = [(w, r) for w, r in refs if r not in PLACEHOLDERS and r not in renamed and not templated(r)
          and PLAIN_REF.match(r.replace("{{ .Values.imageRegistry }}", "x").replace("{{.Values.imageRegistry}}", "x"))]
check(f"the scan reads image fields across the repo ({len(judged)} judged, {len(refs)} found)", len(judged) > 40)
bad = sorted({f"{w}: {r}" for w, r in judged if docker_hub(r)})
check("no image field resolves to Docker Hub", not bad, "\n      ".join([""] + bad[:25]))
for scope in ("gitops/", "games/"):
    check(f"{scope}'s image fields are among those judged", any(w.startswith(scope) for w, _ in judged))
# infra/ holds no image field today (its Terraform and scripts pull nothing; the clusters' images are gitops/'s), so
# what can be checked is that its files are read, and a field added there is judged like any other.
check("infra/'s files are read", any(f.startswith("infra/") for f in files))
check("llm-guard, the kustomize name the ai-layer Application replaces, is judged as replaced, not as a pull",
      "llm-guard" in renamed)

print("== the judgement itself ==")
for ref, hub in (("nginx:1.27", True), ("busybox", True), ("curlimages/curl:8.10.1", True),
                 ("docker.io/library/nginx:1.27-alpine", True), ("index.docker.io/x/y", True),
                 ("ghcr.io/peopleforrester/watch-it-burn:busybox-1.36", False),
                 ("{{ .Values.imageRegistry }}/mirror/kubearmor/kubearmor:stable-bf867783eb30", False),
                 ("localhost:5000/x", False), ("registry.k8s.io/pause:3.9", False)):
    check(f"{ref} {'is' if hub else 'is not'} a Docker Hub pull", docker_hub(ref) is hub)

print("== 3. every watch-it-burn tag a cluster runs names a version ==")
tags = set()
for f in files:
    if f.startswith("gitops/") or f == "images/villains/build.sh":
        for m in OURS.finditer((REPO / f).read_text(encoding="utf-8", errors="replace")):
            tags.add((f, m.group(1)))
check(f"the scan finds our tags ({len(tags)})", len(tags) >= 5)
bare = sorted(f"{f}: {t}" for f, t in tags if "$" not in t and not VERSIONED.search(t))
check("each one carries the version of the software inside", not bare, "\n      ".join([""] + bare))
for t in ("workshop-mcp-mcp-1.29.1", "web-terminal-ttyd-1.7.7", "joker-busybox-1.38.0"):
    check(f"{t} is among them", any(tag == t for _, tag in tags))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("No Docker Hub reference, and every tag names its version.")
