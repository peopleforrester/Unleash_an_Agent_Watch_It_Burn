# ABOUTME: Offline gate for #603: every image reference in a tracked file has an images.lock row with a digest
# ABOUTME: and a source, as the fleet's image-retention rule asks, so an image added without one goes red here.
"""Why this exists (#603, llm-coding-workflow#182).

kubeauto-unicorn-party:2.0.2 lived only in an ECR account that was later lost, and nothing held the source that
built it. The fleet rule that followed (claude-config/rules/infra/image-retention.md in llm-coding-workflow) gives
each repo an images.lock: one row per image with its registry digest, where its source lives, and the date its
tarball was saved. llm-coding-workflow's scripts/mirror-images.sh finds the references, checks the rows and saves
the tarballs, but it lives in another repo and its save needs Docker on netcup, so nothing here ran it and an
image added later would go unrecorded until someone did.

This check finds references the way `mirror-images.sh refs` does (Dockerfile FROM lines and YAML `image:` keys in
tracked files, dropping what cannot be an image) and holds each to a row, and each row to the rule's columns:
a known source kind, a build: path that exists, a sha256 digest or name@sha256 where one is due, a digest that
agrees with the one pinned in the reference, and saved either a date or the - it carries before save runs. It
does not require the date: that is the netcup step, and `mirror-images.sh check .` is the check that owes it.
The declared llm-guard-api row must also carry the digest VERSIONS.lock pins.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
LOCK = REPO / "images.lock"
SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
NAMED_SHA = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
DOCKERFILE = re.compile(r"^(Dockerfile|Dockerfile\..*|.*\.Dockerfile|.*\.dockerfile|Containerfile|Containerfile\..*)$")
IMAGE_KEY = re.compile(r"^[ \t]*(-[ \t]+)?image:")
PLAIN_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$")
PICTURE = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico|bmp)$")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def templated(ref: str) -> bool:
    return "$" in ref or "{{" in ref


def keep(ref: str) -> bool:
    """mirror-images.sh's filter: templated values stay, what cannot be an image reference goes."""
    if templated(ref):
        return True
    return bool(PLAIN_REF.match(ref)) and "//" not in ref and not PICTURE.search(ref.lower())


def from_refs(text: str):
    """FROM lines: flags skipped, scratch and an earlier AS stage of the same file are not pulls."""
    stages: set[str] = set()
    for n, line in enumerate(text.splitlines(), 1):
        line = line.rstrip("\r").lstrip(" \t")
        if line[:4].lower() != "from" or line[4:5] not in (" ", "\t"):
            continue
        t = re.split(r"[ \t]+", line)
        i = 1
        while i < len(t) and t[i].startswith("--"):
            i += 1
        if i >= len(t):
            continue
        img = t[i]
        if img.lower() != "scratch" and img.lower() not in stages:
            yield n, img
        if i + 2 < len(t) and t[i + 1].lower() == "as":
            stages.add(t[i + 2].lower())


def yaml_refs(text: str):
    """`image:` keys with a value on the line; comment, quotes and whitespace removed."""
    for n, line in enumerate(text.splitlines(), 1):
        line = line.rstrip("\r")
        if not IMAGE_KEY.match(line):
            continue
        v = IMAGE_KEY.sub("", line, count=1)
        v = re.sub(r"[ \t]#.*$", "", v)
        v = re.sub(r"[ \t\"']", "", v)
        if v:
            yield n, v


def references() -> dict[str, str]:
    """Every reference in tracked files, first location kept, in mirror-images.sh's order."""
    files = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], check=True,
                           capture_output=True).stdout.decode().split("\0")
    dockerfiles, yamls = [], []
    for f in files:
        p = REPO / f
        if not f or not p.is_file():
            continue
        base = f.rsplit("/", 1)[-1]
        if base == "images.lock":
            continue
        if DOCKERFILE.match(base):
            dockerfiles.append(f)
        elif base.endswith((".yml", ".yaml")):
            yamls.append(f)
    found: dict[str, str] = {}
    for group, parse in ((dockerfiles, from_refs), (yamls, yaml_refs)):
        for f in group:
            for n, ref in parse((REPO / f).read_text(encoding="utf-8", errors="replace")):
                if keep(ref):
                    found.setdefault(ref, f"{f}:{n}")
    return found


def lock_rows() -> tuple[dict[str, tuple[str, str, str]], list[str]]:
    rows: dict[str, tuple[str, str, str]] = {}
    bad: list[str] = []
    for n, line in enumerate(LOCK.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) not in (3, 4):
            bad.append(f"images.lock:{n}: expected 'ref digest source [saved]', got: {line}")
            continue
        ref, digest, source = parts[:3]
        rows[ref] = (digest, source, parts[3] if len(parts) == 4 else "-")
    return rows, bad


def row_problems(ref: str, digest: str, source: str, saved: str) -> list[str]:
    out: list[str] = []
    inline = ref.split("@", 1)[1] if "@" in ref else ""
    if source.startswith("not-an-image:") and len(source) > len("not-an-image:"):
        return [] if digest == "-" else ["a not-an-image row takes - as its digest"]
    if source.startswith("build:") and len(source) > len("build:"):
        if not (REPO / source[len("build:"):]).exists():
            out.append(f"build path {source[len('build:'):]} does not exist")
        if digest == "-":
            return out
    elif not (re.match(r"^(repo|upstream):.+", source) or source == "none"):
        out.append(f"source {source} is not repo:, build:, upstream:, none or not-an-image:")
    if templated(ref):
        if not NAMED_SHA.match(digest):
            out.append("templated: the digest must be name@sha256:<64 hex>")
    elif not (SHA.match(digest) or NAMED_SHA.match(digest)):
        out.append(f"digest {digest} is not sha256:<64 hex> or name@sha256:<64 hex>")
    if inline and digest.rsplit("@", 1)[-1] != inline:
        out.append("the digest differs from the one pinned in the reference")
    if not (saved == "-" or DATE.match(saved)):
        out.append(f"saved {saved} is neither - nor YYYY-MM-DD")
    return out


print("== the reference finder matches mirror-images.sh on known lines ==")
check("a FROM after --platform is found, and a FROM naming an earlier stage is not",
      list(from_refs("FROM --platform=$B python:3.12-slim AS build\nFROM build\nFROM scratch\n"))
      == [(1, "python:3.12-slim")])
check("an image: key loses its comment and quotes, and a map-valued image: is not a reference",
      list(yaml_refs('      image: "nginx:1.27-alpine"  # pinned\n    image:\n      repository: x\n'))
      == [(1, "nginx:1.27-alpine")])
check("a templated value is kept, a Kyverno pattern and a picture are dropped",
      keep("{{.Values.imageRegistry}}/x:1") and not keep("ghcr.io/*") and not keep("logo.png"))

print("== images.lock parses ==")
check("images.lock exists at the repo root", LOCK.is_file())
rows, bad = lock_rows() if LOCK.is_file() else ({}, ["images.lock is missing"])
for b in bad:
    print(f"        {b}")
check(f"every row has ref, digest, source and an optional saved ({len(bad)} malformed)", not bad)

refs = references()
print(f"== every one of the {len(refs)} references has a row ==")
missing = [(r, loc) for r, loc in refs.items() if r not in rows]
for r, loc in missing:
    print(f"        {loc}  {r}")
check(f"no reference without a row ({len(missing)} missing; add them, then run mirror-images.sh save on netcup)",
      not missing)

print("== every row meets the rule's columns ==")
problem_rows = [(r, row_problems(r, *rows[r])) for r in rows]
problem_rows = [(r, p) for r, p in problem_rows if p]
for r, p in problem_rows:
    print(f"        {r}: {'; '.join(p)}")
check(f"no row with a problem ({len(problem_rows)} with one)", not problem_rows)

print("== the declared llm-guard-api row agrees with VERSIONS.lock ==")
pinned = re.search(r"llm-guard-api\s+laiyer/llm-guard-api:0\.3\.16.*?\n\s+digest: (sha256:[0-9a-f]{64})",
                   (REPO / "VERSIONS.lock").read_text(encoding="utf-8"))
check("VERSIONS.lock pins a digest for laiyer/llm-guard-api:0.3.16", pinned is not None)
row = rows.get("laiyer/llm-guard-api:0.3.16")
check("images.lock declares laiyer/llm-guard-api:0.3.16 with that digest and its archived upstream",
      row is not None and pinned is not None and row[0] == pinned.group(1)
      and row[1] == "upstream:https://github.com/protectai/llm-guard")

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll images.lock checks passed.")
