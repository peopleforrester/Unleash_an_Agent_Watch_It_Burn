#!/usr/bin/env python3
# ABOUTME: Checks the KubeCon recorded fallback is really on this machine: every segment video and every
# ABOUTME: screenshot in facilitation/kubecon-na-2026/fallback/assets.yaml is present and is the file type it claims (#452).
"""Run the Night Before, on each presenter laptop, after copying the rehearsal videos into place:

    python3 scripts/check-fallback-assets.py

Lists every file and exits 1 if any is missing, empty, or not an MP4 or PNG by its first bytes. A deck
with a missing slide, or a video that is a zero-byte download, is found here and not in front of the room.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO / "facilitation/kubecon-na-2026/fallback/assets.yaml"


def kind_ok(path: pathlib.Path, head: bytes) -> bool:
    """MP4 carries an 'ftyp' box at byte 4; PNG starts with its 8-byte signature."""
    if path.suffix == ".mp4":
        return head[4:8] == b"ftyp"
    if path.suffix == ".png":
        return head[:8] == b"\x89PNG\r\n\x1a\n"
    return False


def load(manifest: pathlib.Path) -> dict:
    doc = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise ValueError(f"{manifest}: expected a mapping with version: 1")
    for key in ("videos", "screenshots"):
        if not isinstance(doc.get(key), list) or not doc[key]:
            raise ValueError(f"{manifest}: {key} must be a non-empty list")
    if not isinstance(doc.get("deck"), str):
        raise ValueError(f"{manifest}: deck must name the deck page")
    return doc


def check(manifest: pathlib.Path) -> list[tuple[str, str]]:
    """(relative path, problem) for every file not ready; empty when everything is."""
    doc = load(manifest)
    base = manifest.parent
    wanted = [doc["deck"]] + [v["path"] for v in doc["videos"]] + [s["file"] for s in doc["screenshots"]]
    problems = []
    for rel in wanted:
        path = base / rel
        if not path.is_file():
            problems.append((rel, "missing"))
            continue
        if path.stat().st_size == 0:
            problems.append((rel, "empty"))
            continue
        if path.suffix in (".mp4", ".png"):
            with path.open("rb") as fh:
                if not kind_ok(path, fh.read(8)):
                    problems.append((rel, f"not a {path.suffix[1:].upper()} by its first bytes"))
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--manifest", type=pathlib.Path, default=DEFAULT_MANIFEST)
    args = ap.parse_args(argv)
    try:
        doc = load(args.manifest)
        problems = check(args.manifest)
    except (OSError, ValueError, yaml.YAMLError, KeyError, TypeError) as exc:
        print(f"check-fallback-assets: {exc}", file=sys.stderr)
        return 2
    bad = dict(problems)
    total = 1 + len(doc["videos"]) + len(doc["screenshots"])
    for rel in [doc["deck"]] + [v["path"] for v in doc["videos"]] + [s["file"] for s in doc["screenshots"]]:
        print(f"  {'FAIL  ' + bad[rel] + ':' if rel in bad else 'ok   '} {rel}")
    if problems:
        print(f"\nRECORDED FALLBACK NOT READY: {len(problems)} of {total} files are not in place under "
              f"{args.manifest.parent}", file=sys.stderr)
        return 1
    print(f"\nrecorded fallback ready: all {total} files in place")
    return 0


if __name__ == "__main__":
    sys.exit(main())
