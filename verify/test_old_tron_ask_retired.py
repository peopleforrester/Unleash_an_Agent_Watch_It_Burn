#!/usr/bin/env python3
# ABOUTME: No tracked file of this repo carries the old Tron ask #1105 retired (#1155): `git grep -nF` for its follow-up
# ABOUTME: and for its ticket opener finds nothing, and neither does a sweep that reads a copy wrapped across lines as one.
"""No cluster and no network: this reads the tracked tree only.

#1105 cut Challenge 2's Tron ask to one prompt: the ticket number that opened it and the follow-up prompt that asked
for the standard manifest and the public image are gone. One of its criteria was that `git grep -nF` for the
follow-up's opening words and for the ticket opener finds nothing in the repo. The tests that came with it read only
the C2 beat's prompts on /kubecon, prompts.yaml and the run-of-show (test_c2_tron_single_prompt.py,
test_public_images.py, test_replay_prompts.py). A stray copy in a doc, a script, a fixture or decisions.md passed
every test. Test review run 18492 found that, and #1155 asked for this test.

What this checks:

1. `git grep -nF` for each of the two strings over the tracked tree prints nothing and exits 1, git's "no match".
   Any other exit is a broken grep, not a pass.
2. No tracked text file holds either string with its words wrapped across lines (a Markdown paragraph reflowed, a
   comment broken at the line limit), which a per-line grep misses: each file is read with each line's leading
   comment or quote marker dropped and its whitespace squashed.
3. Both checks catch a copy: they are run on a scratch repo holding one copy of each string on a line and one
   wrapped, and must name each.

Each string is built from two halves here, as test_c2_tron_single_prompt.py builds the old wordings it puts back,
so neither file is itself a copy. There is no exemption list: nothing in the repo, decisions.md included, needs the
old wording word for word.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]

# The two strings #1105's criterion greps for, each in two halves.
OLD_STRINGS = {
    "the old follow-up": "Just use the standard " + "manifest",
    "the old ticket opener": "It's ticket " + "HR171",
}

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n{detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# A line's leading comment or quote marker: a shell or YAML `#`, a `//`, a block comment's `*`, a SQL or Lua `--`, a
# Markdown `>`. A string wrapped inside a comment or a quote carries one at the start of each line it runs onto.
MARKER = re.compile(r"^[ \t]*(?:#+|//+|\*|--|>+)[ \t]?", re.M)


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", MARKER.sub("", text))


def git_grep_hits(root: pathlib.Path, needle: str) -> list[str]:
    """The criterion's own command: `git grep -nF` for the string. Exits naming git's error on anything but 0 or 1."""
    r = subprocess.run(["git", "-C", str(root), "grep", "-nF", "-e", needle], capture_output=True, text=True,
                       timeout=120)
    if r.returncode not in (0, 1):
        sys.exit(f"FAILED: git grep exited {r.returncode} in {root}: {r.stderr.strip()}")
    return [line for line in r.stdout.splitlines() if line]


def tracked_files(root: pathlib.Path) -> list[str]:
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, timeout=120)
    if r.returncode != 0:
        sys.exit(f"FAILED: git ls-files exited {r.returncode} in {root}: {r.stderr.decode(errors='replace').strip()}")
    return sorted(p for p in r.stdout.decode().split("\0") if p)


def wrapped_hits(root: pathlib.Path, needles: list[str]) -> dict[str, list[str]]:
    """For each string, the tracked text files that hold it once their whitespace is squashed. A submodule is a
    directory here and belongs to its own repo; a symlink is read at its target; a file with a NUL in its head is
    binary."""
    squashed = {n: squash(n) for n in needles}
    hits: dict[str, list[str]] = {n: [] for n in needles}
    for rel in tracked_files(root):
        p = root / rel
        if p.is_symlink() or not p.is_file():
            continue
        data = p.read_bytes()
        if b"\0" in data[:8192]:
            continue
        text = squash(data.decode("utf-8", errors="replace"))
        for n, s in squashed.items():
            if s in text:
                hits[n].append(rel)
    return hits


print("== both checks catch a planted copy of each string, on a line and wrapped across lines ==")
with tempfile.TemporaryDirectory() as tmp:
    scratch = pathlib.Path(tmp)
    subprocess.run(["git", "init", "-q", str(scratch)], check=True, timeout=60)
    (scratch / "docs").mkdir()
    (scratch / "scripts").mkdir()
    planted = {}
    for i, (label, needle) in enumerate(OLD_STRINGS.items()):
        first, second = needle.rsplit(" ", 1)
        on_line, wrapped = f"docs/on-a-line-{i}.md", f"scripts/wrapped-{i}.sh"
        (scratch / on_line).write_text(f'> The guest said: "{needle}, please."\n')
        (scratch / wrapped).write_text(f"# {first}\n# {second}, please.\n")
        planted[label] = (on_line, wrapped)
    (scratch / "clean.txt").write_text("What I need you to do is deploy Tron onto this cluster.\n")
    subprocess.run(["git", "-C", str(scratch), "add", "-A"], check=True, timeout=60)
    sweep = wrapped_hits(scratch, list(OLD_STRINGS.values()))
    for label, needle in OLD_STRINGS.items():
        on_line, wrapped = planted[label]
        grep_hits = git_grep_hits(scratch, needle)
        check(f"git grep names the copy of {label} on a line",
              any(h.startswith(f"{on_line}:1:") for h in grep_hits), "\n".join(grep_hits))
        check(f"git grep finds no other copy of {label} in the scratch repo", len(grep_hits) == 1,
              "\n".join(grep_hits))
        check(f"the squashed sweep names the wrapped copy of {label} and the one on a line",
              sweep[needle] == sorted([on_line, wrapped]), repr(sweep[needle]))

print("== no tracked file of this repo carries either string of the old Tron ask ==")
files = tracked_files(REPO)
check("the sweep reads the tracked tree (git ls-files listed files)", len(files) > 100, f"{len(files)} files")
sweep = wrapped_hits(REPO, list(OLD_STRINGS.values()))
for label, needle in OLD_STRINGS.items():
    grep_hits = git_grep_hits(REPO, needle)
    check(f"git grep -nF for {label} finds no copy", not grep_hits, "\n".join(grep_hits))
    check(f"no tracked text file holds {label} wrapped across lines", not sweep[needle], "\n".join(sweep[needle]))

if failures:
    print(f"\nFAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("\nOK: no copy of the old Tron ask's follow-up or ticket opener in the tracked tree")
