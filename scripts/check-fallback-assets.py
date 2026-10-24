#!/usr/bin/env python3
# ABOUTME: Checks the KubeCon recorded fallback is really on this machine: every segment video and every
# ABOUTME: screenshot in facilitation/kubecon-na-2026/fallback/assets.yaml is present and is the file type it claims (#452).
"""Run the Night Before, on each presenter laptop, after copying the rehearsal videos into place:

    python3 scripts/check-fallback-assets.py
    python3 scripts/check-fallback-assets.py --write-deck   # after editing assets.yaml: rewrite deck.html's lists

Lists every file and exits 1 if any is missing, empty, or not an MP4 or PNG by its first bytes. A deck
with a missing slide, or a video that is a zero-byte download, is found here and not in front of the room.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO / "facilitation/kubecon-na-2026/fallback/assets.yaml"
CLUSTERS = ("community", "private")
# A /controls key, as `group.key`: the two groups the storefront's /controls answers with.
CONTROL_RE = re.compile(r"(ai|infra)\.[a-z_]+")


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
    for shot in doc["screenshots"]:
        capture_problem = check_capture(shot.get("capture"))
        if capture_problem:
            raise ValueError(f"{manifest}: {shot.get('file')}: {capture_problem}")
    return doc


def check_capture(cap) -> str:
    """'' when a shot's capture is one of the three shapes assets.yaml's header describes, else what is wrong."""
    if not isinstance(cap, dict) or len({"chat", "page", "by_hand"} & set(cap)) != 1:
        return "capture must hold exactly one of chat, page or by_hand"
    if "page" in cap:
        ok = set(cap) == {"page"} and isinstance(cap["page"], str) and cap["page"].startswith("https://")
        return "" if ok else "a page capture is one https:// URL and nothing else"
    if "by_hand" in cap:
        ok = set(cap) == {"by_hand"} and isinstance(cap["by_hand"], str) and cap["by_hand"].strip()
        return "" if ok else "a by_hand capture says what to take, and nothing else"
    fields = {"chat", "cluster", "controls", "toggle"}
    if set(cap) - fields:
        return f"unknown chat capture field(s) {sorted(map(str, set(cap) - fields))}"
    if cap.get("cluster") not in CLUSTERS:
        return f"a chat capture's cluster must be one of {CLUSTERS}"
    controls = cap.get("controls")
    if (not isinstance(controls, dict) or not controls
            or not all(CONTROL_RE.fullmatch(str(k)) and isinstance(v, bool) for k, v in controls.items())):
        return "a chat capture's controls map ai.<key> or infra.<key> to true or false"
    if "toggle" in cap and cap["cluster"] != "private":
        return "only the private cluster's terminal flips guards for a shot"
    return ""


def deck_lists(doc: dict) -> tuple[dict, list]:
    """What deck.html embeds: each segment's title, and each shot's segment, file and caption, in order."""
    segments = {str(v["segment"]): v["title"] for v in doc["videos"]}
    shots = [{"segment": s["segment"], "file": s["file"], "caption": s["caption"]} for s in doc["screenshots"]]
    return segments, shots


def embedded(deck_html: str, block: str):
    m = re.search(rf'<script type="application/json" id="{block}">\n(.*?)\n</script>', deck_html, re.S)
    if not m:
        raise ValueError(f"the deck page has no {block} block")
    return json.loads(m.group(1))


def write_deck(manifest: pathlib.Path) -> pathlib.Path:
    doc = load(manifest)
    deck = manifest.parent / doc["deck"]
    html = deck.read_text(encoding="utf-8")
    segments, shots = deck_lists(doc)
    for block, value in (("segments", segments), ("shots", shots)):
        embedded(html, block)  # refuses a page that lost its block, rather than writing nothing
        text = json.dumps(value, indent=2, ensure_ascii=False)
        html = re.sub(rf'(<script type="application/json" id="{block}">\n).*?(\n</script>)',
                      lambda m: m.group(1) + text + m.group(2), html, count=1, flags=re.S)
    deck.write_text(html, encoding="utf-8")
    return deck


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
    ap.add_argument("--write-deck", action="store_true",
                    help="rewrite the deck page's segment and shot lists from the manifest, then check")
    args = ap.parse_args(argv)
    try:
        if args.write_deck:
            print(f"wrote the deck's lists into {write_deck(args.manifest)}")
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
