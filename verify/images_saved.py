# ABOUTME: Judge for #603's save half (#836): which images.lock rows owe a saved tarball, and whether the image
# ABOUTME: archive's manifest.tsv holds each one at its current digest with a file that hashes to what it recorded.
"""Shared by test_images_saved.py (the archive on netcup) and test_images_saved_judge.py (fixture archives).

llm-coding-workflow's scripts/mirror-images.sh `save` pulls each row's image by digest, writes it under
MIRROR_IMAGES_DEST (default ~/repos/private/image-archive) as a .tar.gz, appends `saved_at source_repo ref digest platform file file_sha256` to that directory's manifest.tsv, and writes the
date into the row's saved column. It skips a not-an-image: row and a build: row whose digest is -; every other row
owes a save. For a name@sha256 digest (a templated or kustomize ref) the saved digest is the part after the @.

A row is saved here when its saved column is a date and the manifest has a line for its ref at its current digest
whose file is in the archive and hashes to the manifest's file_sha256. A digest bumped after the save has no line,
so it reads as unsaved again: mirror-images.sh keeps the old date in the saved column, and that date alone would
claim a copy of an image nobody saved.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re

DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
MANIFEST_HEADER = ["saved_at", "source_repo", "ref", "digest", "platform", "file", "file_sha256"]


def default_archive() -> pathlib.Path:
    """mirror-images.sh's DEST: MIRROR_IMAGES_DEST, else ~/repos/private/image-archive."""
    dest = os.environ.get("MIRROR_IMAGES_DEST")
    return pathlib.Path(dest) if dest else pathlib.Path.home() / "repos/private/image-archive"


def lock_rows(text: str) -> list[tuple[str, str, str, str]]:
    """(ref, digest, source, saved) for each row, in file order; saved is - when the column is absent."""
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) in (3, 4):
            rows.append((parts[0], parts[1], parts[2], parts[3] if len(parts) == 4 else "-"))
    return rows


def owes_save(digest: str, source: str) -> bool:
    """save_one's skips: a not-an-image: row, and a build: row with no digest (its FROM bases are saved instead)."""
    if source.startswith("not-an-image:"):
        return False
    if source.startswith("build:") and digest == "-":
        return False
    return True


def saved_digest(digest: str) -> str:
    """The digest save pulls and records: the sha256 part of a name@sha256 digest, else the digest itself."""
    return digest.rsplit("@", 1)[-1]


def manifest_lines(text: str) -> tuple[dict[tuple[str, str], list[dict[str, str]]], list[str]]:
    """manifest.tsv by (ref, digest), and the problems with its shape."""
    by_key: dict[tuple[str, str], list[dict[str, str]]] = {}
    bad: list[str] = []
    lines = text.splitlines()
    if not lines or lines[0].split("\t") != MANIFEST_HEADER:
        bad.append(f"manifest.tsv does not start with the header {chr(9).join(MANIFEST_HEADER)!r}")
        return by_key, bad
    for n, line in enumerate(lines[1:], 2):
        if not line:
            continue
        cols = line.split("\t")
        if len(cols) != len(MANIFEST_HEADER):
            bad.append(f"manifest.tsv:{n}: {len(cols)} columns, not {len(MANIFEST_HEADER)}")
            continue
        entry = dict(zip(MANIFEST_HEADER, cols))
        by_key.setdefault((entry["ref"], entry["digest"]), []).append(entry)
    return by_key, bad


def file_sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def row_save_problems(ref: str, digest: str, saved: str, archive: pathlib.Path,
                      manifest: dict[tuple[str, str], list[dict[str, str]]],
                      hashes: dict[pathlib.Path, str] | None = None) -> list[str]:
    """Why a row that owes a save is not saved, or [] when it is."""
    out: list[str] = []
    if not DATE.match(saved):
        out.append(f"saved is {saved}, not the YYYY-MM-DD mirror-images.sh save writes")
    want = saved_digest(digest)
    if not SHA.match(want):
        return out + [f"digest {digest} names no sha256 to save by"]
    entries = manifest.get((ref, want), [])
    if not entries:
        return out + [f"manifest.tsv has no line for {ref} at {want}"]
    hashes = {} if hashes is None else hashes
    reasons: list[str] = []
    for e in entries:
        if not DATE.match(e["saved_at"]):
            reasons.append(f"its line's saved_at {e['saved_at']!r} is not a date")
            continue
        rel = pathlib.PurePosixPath(e["file"])
        if rel.is_absolute() or ".." in rel.parts:
            reasons.append(f"its line's file {e['file']} is outside the archive")
            continue
        path = archive / rel
        if not path.is_file() or path.stat().st_size == 0:
            reasons.append(f"{e['file']} is not in the archive, or is empty")
            continue
        if path not in hashes:
            hashes[path] = file_sha256(path)
        if hashes[path] != e["file_sha256"]:
            reasons.append(f"{e['file']} hashes to {hashes[path][:12]}..., not the recorded {e['file_sha256'][:12]}...")
            continue
        return out
    return out + reasons
