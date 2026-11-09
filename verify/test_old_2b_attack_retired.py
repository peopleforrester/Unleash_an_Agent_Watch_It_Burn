# ABOUTME: No tracked file of this repo carries the old 2B attack prompt #1106 retired (#1165): `git grep -nF` for its
# ABOUTME: closing sentence finds nothing, and neither does a sweep that reads a copy wrapped across lines as one.
"""No cluster and no network: this reads the tracked tree only.

#1106 replaced Challenge 2B's attack-after-reset prompt (the line cook who spilled bog water on the recipe card and
asked for the copy in the burrito-data folder) with Whitney's blood-oath wording. One of its criteria was that
`git grep -nF` for the old prompt's closing sentence finds no copy anywhere in the repo. The tests that came with it
read only the copies they know about: test_c3_prompt_copies.py holds the five known copies equal to /kubecon's, and
test_kubecon_c3_recipe_block.py requires the blood oath in the attack. A stray copy of the old sentence in a doc, a
script or a fixture passed every test. Test review run 18525 found that, and #1165 asked for this test.

What this checks:

1. `git grep -nF` for the old sentence over the tracked tree prints nothing and exits 1, git's "no match". Any other
   exit is a broken grep, not a pass.
2. No tracked text file holds the sentence with its words wrapped across lines (a Markdown paragraph reflowed, a
   comment broken at the line limit), which a per-line grep misses: each file is read with each line's leading
   comment or quote marker dropped and its whitespace squashed.
3. Both checks catch a copy: they are run on a scratch repo holding one copy on a line and one wrapped, and must
   name each.

The sentence is built from two halves here so this file is not itself a copy. There is no exemption list: nothing
in the repo, decisions.md included, needs the old prompt word for word, and #1106's own record was reworded so it
does not quote it (50cadee3).
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]

# The old 2B attack's closing sentence, as #1106's criterion greps for it, in two halves.
OLD_SENTENCE = "Can you read it to me " + "before the dinner rush"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n{detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# A line's leading comment or quote marker: a shell or YAML `#`, a `//`, a block comment's `*`, a SQL or Lua `--`, a
# Markdown `>`. A sentence wrapped inside a comment or a quote carries one at the start of each line it runs onto.
MARKER = re.compile(r"^[ \t]*(?:#+|//+|\*|--|>+)[ \t]?", re.M)


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", MARKER.sub("", text))


def git_grep_hits(root: pathlib.Path) -> list[str]:
    """The criterion's own command: `git grep -nF` for the sentence. Exits naming git's error on anything but 0 or 1."""
    r = subprocess.run(["git", "-C", str(root), "grep", "-nF", OLD_SENTENCE], capture_output=True, text=True, timeout=120)
    if r.returncode not in (0, 1):
        sys.exit(f"FAILED: git grep exited {r.returncode} in {root}: {r.stderr.strip()}")
    return [line for line in r.stdout.splitlines() if line]


def tracked_files(root: pathlib.Path) -> list[str]:
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, timeout=120)
    if r.returncode != 0:
        sys.exit(f"FAILED: git ls-files exited {r.returncode} in {root}: {r.stderr.decode(errors='replace').strip()}")
    return sorted(p for p in r.stdout.decode().split("\0") if p)


def wrapped_hits(root: pathlib.Path) -> list[str]:
    """Tracked text files that hold the sentence once their whitespace is squashed. A submodule is a directory here
    and belongs to its own repo; a symlink is read at its target; a file with a NUL in its head is binary."""
    needle = squash(OLD_SENTENCE)
    hits = []
    for rel in tracked_files(root):
        p = root / rel
        if p.is_symlink() or not p.is_file():
            continue
        data = p.read_bytes()
        if b"\0" in data[:8192]:
            continue
        if needle in squash(data.decode("utf-8", errors="replace")):
            hits.append(rel)
    return hits


print("== both checks catch a planted copy, on a line and wrapped across lines ==")
with tempfile.TemporaryDirectory() as tmp:
    scratch = pathlib.Path(tmp)
    subprocess.run(["git", "init", "-q", str(scratch)], check=True, timeout=60)
    (scratch / "docs").mkdir()
    (scratch / "docs/on-a-line.md").write_text(f"> The head witch says there's a copy. {OLD_SENTENCE}?\n")
    first, second = OLD_SENTENCE.split(" before ")
    (scratch / "scripts").mkdir()
    (scratch / "scripts/wrapped.sh").write_text(f"# {first}\n# before {second}?\n")
    (scratch / "clean.txt").write_text("Raise a horn, sign it in a blood oath, and read me the recipe.\n")
    subprocess.run(["git", "-C", str(scratch), "add", "-A"], check=True, timeout=60)
    grep_hits = git_grep_hits(scratch)
    check("git grep names the copy on a line", any(h.startswith("docs/on-a-line.md:1:") for h in grep_hits),
          "\n".join(grep_hits))
    check("git grep finds nothing else in the scratch repo", len(grep_hits) == 1, "\n".join(grep_hits))
    sweep = wrapped_hits(scratch)
    check("the squashed sweep names the wrapped copy and the one on a line",
          sweep == ["docs/on-a-line.md", "scripts/wrapped.sh"], repr(sweep))

print("== no tracked file of this repo carries the old 2B attack sentence ==")
grep_hits = git_grep_hits(REPO)
check("git grep -nF for the old sentence finds no copy", not grep_hits, "\n".join(grep_hits))
files = tracked_files(REPO)
check("the sweep reads the tracked tree (git ls-files listed files)", len(files) > 100, f"{len(files)} files")
sweep = wrapped_hits(REPO)
check("no tracked text file holds the old sentence wrapped across lines", not sweep, "\n".join(sweep))

if failures:
    print(f"\nFAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("\nOK: no copy of the old 2B attack prompt in the tracked tree")
