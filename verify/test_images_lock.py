# ABOUTME: Static gate for #603: images.lock has a well-formed row for every image a tracked Dockerfile or YAML file
# ABOUTME: names, and its digests agree with the pins, VERSIONS.lock, lab-platform's mirror copies and the ai-layer app.
"""Why this exists (#603, llm-coding-workflow#182).

The fleet's image-retention rule gives every image a repo depends on an images.lock row: its digest, where its
source lives, and the date its tarball was saved. llm-coding-workflow's scripts/mirror-images.sh `check` holds a
repo to it, but that script lives in another repo, so the offline gate cannot run it. This test reads references
the way the script does (Dockerfile FROM lines and `image:` keys in YAML, tracked files only), so a new image
fails here, in this repo, the day it is added, rather than going unsaved until somebody next runs `check`.

It also holds the copies of each digest this repo keeps elsewhere: a reference pinned name:tag@sha256 must carry the
same digest in the lock, the laiyer/llm-guard-api row must match VERSIONS.lock, each mirror/ row must match
verify/mirror_copies.py, and the llm-guard row must match the ai-layer Application's kustomize.images entry (#652).

The saved column is not required here: a tarball is taken by `mirror-images.sh save .` on netcup, which a run with
no Docker daemon cannot do, and `- ` there is what `check` reports as never saved.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, REPO, kustomize_images  # noqa: E402
from mirror_copies import COPIES  # noqa: E402

LOCK = REPO / "images.lock"
SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
NAMED_SHA = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
DOCKERFILE = re.compile(r"^(Dockerfile(\..*)?|.*\.[Dd]ockerfile|Containerfile(\..*)?)$")
# The registry an app file names a lab-platform image under, as the lock writes it: whitespace removed (#622).
REGISTRY_REF = IMAGE_REGISTRY.replace(" ", "")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def tracked() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], check=True, capture_output=True).stdout
    return [p for p in out.decode().split("\0") if p and (REPO / p).is_file()]


def from_refs(path: str) -> list[str]:
    """FROM images, as mirror-images.sh reads them: flags skipped, scratch and earlier stages left out."""
    refs, stages = [], set()
    for line in (REPO / path).read_text(encoding="utf-8").splitlines():
        t = line.strip().split()
        if not t or t[0].lower() != "from":
            continue
        t = [w for w in t[1:] if not w.startswith("--")]
        if not t:
            continue
        img = t[0]
        if img.lower() != "scratch" and img.lower() not in stages:
            refs.append(img)
        if len(t) >= 3 and t[1].lower() == "as":
            stages.add(t[2].lower())
    return refs


def yaml_refs(path: str) -> list[str]:
    """`image:` values on one line, as mirror-images.sh reads them, less what cannot be an image at all."""
    refs = []
    for line in (REPO / path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^[ \t]*(-[ \t]+)?image:(.*)$", line)
        if not m:
            continue
        v = re.sub(r"[ \t]#.*$", "", m.group(2))
        v = re.sub(r"[ \t\"']", "", v)
        if not v:
            continue
        if "$" not in v and "{{" not in v:
            if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$", v) or "//" in v:
                continue
            if re.search(r"\.(png|jpe?g|gif|svg|webp|ico|bmp)$", v, re.I):
                continue
        refs.append(v)
    return refs


def references() -> dict[str, str]:
    """Every reference in the tracked files, each with the first file that names it."""
    found: dict[str, str] = {}
    for p in tracked():
        base = p.rsplit("/", 1)[-1]
        if base == "images.lock":
            continue
        if DOCKERFILE.match(base):
            refs = from_refs(p)
        elif base.endswith((".yaml", ".yml")):
            refs = yaml_refs(p)
        else:
            continue
        for r in refs:
            found.setdefault(r, p)
    return found


def lock_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for n, line in enumerate(LOCK.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split()
        check(f"images.lock:{n} has four columns: ref digest source saved", len(f) == 4, line)
        if len(f) == 4:
            check(f"images.lock:{n} names {f[0]} once", f[0] not in rows)
            rows[f[0]] = f[1:]
    return rows


print("== images.lock rows are well formed ==")
check("images.lock exists at the repo root", LOCK.is_file())
rows = lock_rows() if LOCK.is_file() else {}
for ref, (digest, source, saved) in rows.items():
    kind = source.split(":", 1)[0]
    check(f"{ref}: source is repo:, build:, upstream:, none or not-an-image:",
          source == "none" or (kind in ("repo", "build", "upstream", "not-an-image") and len(source) > len(kind) + 1),
          source)
    check(f"{ref}: saved is - or a date", saved == "-" or bool(DATE.match(saved)), saved)
    if kind == "not-an-image":
        check(f"{ref}: a not-an-image row takes - as its digest", digest == "-", digest)
        continue
    if kind == "build":
        check(f"{ref}: build path {source[6:]} exists", (REPO / source[6:]).exists())
        if digest == "-":
            continue
    templated = "$" in ref or "{{" in ref
    if templated:
        check(f"{ref}: a templated reference's digest is name@sha256", bool(NAMED_SHA.match(digest)), digest)
    else:
        check(f"{ref}: digest is sha256 or name@sha256", bool(SHA.match(digest) or NAMED_SHA.match(digest)), digest)
    if "@" in ref and not templated:
        pin = ref.split("@", 1)[1]
        check(f"{ref}: the lock's digest is the one pinned in the reference", digest.split("@")[-1] == pin, digest)
    if kind == "upstream":
        check(f"{ref}: an upstream source is a URL", source[9:].startswith("https://"), source)

print("\n== every image a tracked file names has a row ==")
refs = references()
check("the sweep finds the references (more than twenty)", len(refs) > 20, str(len(refs)))
for ref, where in refs.items():
    check(f"{ref} ({where}) has an images.lock row", ref in rows)

print("\n== laiyer/llm-guard-api matches VERSIONS.lock (#603) ==")
versions = (REPO / "VERSIONS.lock").read_text(encoding="utf-8")
m = re.search(r"^llm-guard-api\s+laiyer/llm-guard-api:0\.3\.16.*?\n\s+digest: (sha256:[0-9a-f]{64})", versions, re.M)
check("VERSIONS.lock pins laiyer/llm-guard-api:0.3.16 to a digest", m is not None)
row = rows.get("laiyer/llm-guard-api:0.3.16")
check("images.lock has a laiyer/llm-guard-api:0.3.16 row", row is not None)
if m and row:
    check("its digest is VERSIONS.lock's", row[0] == m.group(1), row[0])
    check("its source is protectai/llm-guard upstream", row[1] == "upstream:https://github.com/protectai/llm-guard", row[1])

print("\n== the llm-guard row is the image the ai-layer Application sets (#652) ==")
entries = [e for e in kustomize_images(yaml.safe_load((APPS / "ai-layer.yaml").read_text(encoding="utf-8")))
           if e["name"] == "llm-guard"]
check("ai-layer.yaml sets the llm-guard image once", len(entries) == 1, str(entries))
row = rows.get("llm-guard")
check("images.lock has an llm-guard row", row is not None)
if len(entries) == 1 and row:
    e = entries[0]
    want = e["newName"].replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR) + "@" + e.get("digest", "")
    check("its digest is the Application's, at the chart's default registry", row[0] == want, f"{row[0]} != {want}")
    check("its source is llm-guard-cpu-offline, the images/llm-guard submodule",
          row[1] == "repo:peopleforrester/llm-guard-cpu-offline", row[1])

print("\n== each mirror/ copy an app file names has its row (#623) ==")
# Most are image: lines or Helm registry/repository/tag splits; the snitch is an env value, RELATED_IMAGE_KUBEARMOR_SNITCH.
# The sweep above sees only the image: lines, so the lock declares the rest by hand.
for c in COPIES:
    check(f"{c.path} is named by its app file",
          any(c.tag in (APPS / f"{a}.yaml").read_text(encoding="utf-8") for a in c.apps))
    ref = f"{REGISTRY_REF}/{c.path}"
    row = rows.get(ref)
    check(f"{c.path} has a row", row is not None)
    if row:
        want = f"{LAB_PLATFORM_GHCR}/{c.path.rsplit(':', 1)[0]}@{c.digest}"
        check(f"{c.path}: digest is the copy's", row[0] == want, row[0])
        check(f"{c.path}: source is upstream", row[1].startswith("upstream:https://"), row[1])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All images.lock checks passed.")
