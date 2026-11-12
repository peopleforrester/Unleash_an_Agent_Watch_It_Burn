# ABOUTME: Moves every deck citation of the hash form in the files it is given from an old-to-new slide map, in one
# ABOUTME: pass so none moves twice; reports cut slides and dated-history lines it leaves, with a dry run (#1391).
"""Renumber the deck's URL-hash citations in a set of files from an old-to-new map (#1391, for #1390).

A citation is a hash: a number sign, a slash and the deck's zero-based slide index, the form the run-of-show,
/kubecon and the tests' quoted citations use. Bare integers (a FIRST constant in a test, an index into a deck list)
are not citations here; the apply run edits those by hand.

Each line is rewritten with one regex substitution, so every hash is looked up in the map once, against its old
number: under #1390's map hash 42 becomes 43 and hash 43 becomes 42 in the same pass, and hash 46 becomes 45 and is
not then looked up again as a 45 (which the map cuts).

What the tool leaves, and prints with its file and line number:

  CUT      a line citing a slide the map sends to nothing. The hash is not rewritten; the apply run removes or
           rewrites that passage by hand. Other hashes on the line are still moved.
  HISTORY  a line that records history, so it points at the deck of its date and keeps every number on it. A
           line is history when it matches a pattern passed with --history, or, unless --no-default-history, the
           default rule: it names a commit SHA, seven to forty hex digits with at least one digit and one letter,
           standing alone (not a word's tail, not an HTML colour after a number sign).
  UNMAPPED a hash the map has no entry for. It is left as it is.

Maps:
  --preset 1390   #1390's map: hashes 0 to 41 and 44 stay; 42 and 43 swap; 45 is cut; 46 to 126 become 45 to 125.
  --map FILE      a JSON object from old hash to new hash, or null for a cut slide: {"42": 43, "45": null}.
                  Hashes the object does not name are UNMAPPED, so a map that keeps a slide names it.

Usage:
  python3 verify/deck_renumber.py --preset 1390 --dry-run FILE...
  python3 verify/deck_renumber.py --map moves.json --history 'Read from rounds' FILE...

--dry-run prints every CHANGE line, old and new, and writes nothing. Without it the files are rewritten in place,
byte for byte except for the hashes moved. The exit code is 0 when the run completes, 2 on a bad map or argument.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field

SIGN = "#/"
HASH = re.compile(re.escape(SIGN) + r"(\d+)(?!\d)")
# A commit SHA standing alone: 7 to 40 hex digits, at least one digit and one letter, not preceded by a word
# character or a number sign (an HTML colour), and not followed by a word character.
SHA = re.compile(r"(?<![\w#])(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?!\w)")
DEFAULT_HISTORY = (SHA,)


def preset_1390() -> dict[int, int | None]:
    """#1390's map: 0..41 and 44 unchanged, 42 and 43 swap, 45 cut, 46..126 down one."""
    m: dict[int, int | None] = {n: n for n in range(0, 42)}
    m[42], m[43], m[44], m[45] = 43, 42, 44, None
    m.update({n: n - 1 for n in range(46, 127)})
    return m


PRESETS = {"1390": preset_1390}


def check_map(mapping: dict[int, int | None]) -> None:
    """A map that sends two old hashes to one new hash would merge two slides' citations; refuse it."""
    seen: dict[int, int] = {}
    for old, new in sorted(mapping.items()):
        if new is None:
            continue
        if not isinstance(new, int) or isinstance(new, bool) or new < 0:
            raise ValueError(f"hash {old} maps to {new!r}, not a slide index or null")
        if new in seen:
            raise ValueError(f"hashes {seen[new]} and {old} both map to {new}")
        seen[new] = old


def load_map(path: pathlib.Path) -> dict[int, int | None]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: the map is a JSON object from old hash to new hash or null")
    out: dict[int, int | None] = {}
    for k, v in raw.items():
        key = str(k).removeprefix(SIGN)
        if not key.isdigit():
            raise ValueError(f"{path}: key {k!r} is not a slide index")
        out[int(key)] = v
    check_map(out)
    return out


@dataclass
class Report:
    changes: list[tuple[str, int, str, str, list[tuple[int, int]]]] = field(default_factory=list)
    cut: list[tuple[str, int, list[int], str]] = field(default_factory=list)
    history: list[tuple[str, int, list[int], str]] = field(default_factory=list)
    unmapped: list[tuple[str, int, list[int], str]] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)


def renumber_text(text: str, mapping: dict[int, int | None], history: list[re.Pattern[str]],
                  name: str = "<text>", report: Report | None = None) -> tuple[str, Report]:
    """Rewrite every hash in `text` once from `mapping`, line by line, leaving history lines whole."""
    report = report if report is not None else Report()
    out = []
    for no, line in enumerate(text.splitlines(keepends=True), 1):
        nums = [int(m.group(1)) for m in HASH.finditer(line)]
        if not nums:
            out.append(line)
            continue
        body = line.rstrip("\r\n")
        if any(p.search(line) for p in history):
            report.history.append((name, no, nums, body))
            out.append(line)
            continue
        moved: list[tuple[int, int]] = []
        cut: list[int] = []
        unmapped: list[int] = []

        def sub(m: re.Match[str]) -> str:
            old = int(m.group(1))
            if old not in mapping:
                unmapped.append(old)
                return m.group(0)
            new = mapping[old]
            if new is None:
                cut.append(old)
                return m.group(0)
            if new != old:
                moved.append((old, new))
            return f"{SIGN}{new}"

        new_line = HASH.sub(sub, line)
        if cut:
            report.cut.append((name, no, cut, body))
        if unmapped:
            report.unmapped.append((name, no, unmapped, body))
        if moved:
            report.changes.append((name, no, body, new_line.rstrip("\r\n"), moved))
        out.append(new_line)
    return "".join(out), report


def renumber_files(paths: list[pathlib.Path], mapping: dict[int, int | None], history: list[re.Pattern[str]],
                   dry_run: bool) -> Report:
    """Renumber each file, naming it in the report as the caller gave its path."""
    report = Report()
    for p in paths:
        name = str(p)
        with p.open(encoding="utf-8", newline="") as fh:
            text = fh.read()
        new, _ = renumber_text(text, mapping, history, name, report)
        if new != text:
            report.changed_files.append(name)
            if not dry_run:
                with p.open("w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
    return report


def hashes(nums: list[int]) -> str:
    return ", ".join(f"{SIGN}{n}" for n in nums)


def print_report(report: Report, dry_run: bool, out=sys.stdout) -> None:
    for name, no, old, new, moved in report.changes:
        print(f"CHANGE {name}:{no}: " + ", ".join(f"{SIGN}{a} -> {SIGN}{b}" for a, b in moved), file=out)
        if dry_run:
            print(f"  - {old}", file=out)
            print(f"  + {new}", file=out)
    for name, no, nums, line in report.cut:
        print(f"CUT {name}:{no}: {hashes(nums)} cites a cut slide, left as it is; remove the passage by hand",
              file=out)
        print(f"  | {line}", file=out)
    for name, no, nums, line in report.history:
        print(f"HISTORY {name}:{no}: left as dated history: {hashes(nums)}", file=out)
        print(f"  | {line}", file=out)
    for name, no, nums, line in report.unmapped:
        print(f"UNMAPPED {name}:{no}: {hashes(nums)} not in the map, left as it is", file=out)
        print(f"  | {line}", file=out)
    moved = sum(len(c[4]) for c in report.changes)
    verb = "would rewrite" if dry_run else "rewrote"
    print(f"{verb} {moved} hash(es) on {len(report.changes)} line(s) in {len(report.changed_files)} file(s); "
          f"{len(report.cut)} cut line(s), {len(report.history)} history line(s), "
          f"{len(report.unmapped)} unmapped line(s) left" + ("; dry run, nothing written" if dry_run else ""),
          file=out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--preset", choices=sorted(PRESETS), help="a named map shipped with the tool")
    src.add_argument("--map", type=pathlib.Path, help="a JSON object from old hash to new hash or null")
    ap.add_argument("--history", action="append", default=[], metavar="REGEX",
                    help="a line matching this keeps its numbers as dated history (repeatable)")
    ap.add_argument("--no-default-history", action="store_true",
                    help="drop the default rule that a line naming a commit SHA is history")
    ap.add_argument("--dry-run", action="store_true", help="print what would change and write nothing")
    ap.add_argument("files", nargs="+", type=pathlib.Path)
    args = ap.parse_args(argv)
    try:
        mapping = PRESETS[args.preset]() if args.preset else load_map(args.map)
        check_map(mapping)
        history = [re.compile(h) for h in args.history]
    except (ValueError, OSError, re.error) as e:
        print(f"deck_renumber.py: {e}", file=sys.stderr)
        return 2
    if not args.no_default_history:
        history += DEFAULT_HISTORY
    missing = [str(p) for p in args.files if not p.is_file()]
    if missing:
        print(f"deck_renumber.py: no such file: {', '.join(missing)}", file=sys.stderr)
        return 2
    report = renumber_files(args.files, mapping, history, args.dry_run)
    print_report(report, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
