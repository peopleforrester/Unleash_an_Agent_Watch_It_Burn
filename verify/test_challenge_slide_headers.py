# ABOUTME: Holds the challenge slide header the KubeCon run-of-show quotes (#1039): every quoted header line in
# ABOUTME: segments 2 to 5 reads "Challenge N - attackme.burritobot.co", with N the segment's own challenge.
"""The run-of-show quotes each challenge slide's header as the deck has it (#1039).

rounds-agenticburn#68 changed the header line on every challenge slide to "Challenge N - attackme.burritobot.co",
so a late arrival can find the public bot again. Segment 3 quoted it first (#1003); #1039 brought segment 2's
challenge slide and hint slide in line. This test holds:

  1. Segment 2 quotes the header twice, once on the challenge slide and once on the hint slide, and the hint
     slide's quote opens on the header and carries "Hint: The CEO's name is Ophelia Thorn."
  2. In segments 2 to 5, every quoted line that starts with "Challenge" followed by a number is the full header,
     and the number is the segment's own challenge (segment 2 is Challenge 1, segment 5 is Challenge 4). A bare
     "> Challenge 3" quote added to segment 4 when its slides are reviewed fails here.

facilitation/runbook.md, the 2-hour format, is left out: it is not run from the KubeCon deck.

Each cut on repo text first checks its literal is there and exits naming the literal and the file when it is not
("Tests own their inputs"). Each check is also run on a copy of the text with the old bare header put back, so a
check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
HOST = "attackme.burritobot.co"
HINT = "Hint: The CEO's name is Ophelia Thorn."
# Segment heading -> the challenge it runs, and the heading that ends it.
SEGMENTS = [
    ("### Segment 2:", 1, "### Segment 3:"),
    ("### Segment 3:", 2, "### Segment 4:"),
    ("### Segment 4:", 3, "### Segment 5:"),
    ("### Segment 5:", 4, "### Segment 6:"),
]
QUOTED_CHALLENGE = re.compile(r"^\s*>\s*(Challenge\s+\d+\b.*?)\s*$", re.M)

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def need(text: str, literal: str, where: pathlib.Path = ROS_PATH) -> None:
    if literal not in text:
        sys.exit(f"ANCHOR MISSING: {literal!r} is not in {where}; the challenge header checks cut on it")


def segment(ros: str, start: str, end: str) -> str:
    need(ros, start)
    need(ros, end)
    return ros.split(start, 1)[1].split(end, 1)[0]


def header(n: int) -> str:
    return f"Challenge {n} - {HOST}"


def quote_blocks(text: str) -> list[list[str]]:
    """Each run of consecutive '>' lines, as its lines with the '>' and indentation stripped."""
    blocks: list[list[str]] = []
    cur: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(">"):
            cur.append(s[1:].strip())
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def problems(ros: str) -> dict[str, list[str]]:
    """Every check's failures on one copy of the run-of-show, keyed by the check's name."""
    out: dict[str, list[str]] = {}
    seg2 = segment(ros, *SEGMENTS[0][::2])
    blocks = [b for b in quote_blocks(seg2) if b and b[0].startswith("Challenge")]
    out["segment 2 quotes the Challenge 1 header on both its challenge slide and its hint slide"] = (
        [] if [b[0] for b in blocks] == [header(1), header(1)]
        else [f"segment 2's quoted headers are {[b[0] for b in blocks]!r}"])
    hint = [b for b in blocks if HINT in b]
    out["segment 2's hint slide quote opens on the header and adds the Ophelia Thorn hint"] = (
        [] if len(hint) == 1 and hint[0][0] == header(1) and hint[0][-1] == HINT
        else [f"the hint quotes are {hint!r}"])
    bad: list[str] = []
    for start, n, end in SEGMENTS:
        for m in QUOTED_CHALLENGE.finditer(segment(ros, start, end)):
            if m.group(1) != header(n):
                bad.append(f"{start} quotes {m.group(1)!r}, not {header(n)!r}")
    out["every quoted challenge header in segments 2 to 5 is 'Challenge N - attackme.burritobot.co' for its own N"] = bad
    return out


ros = ROS_PATH.read_text(encoding="utf-8")
for name, errs in problems(ros).items():
    for e in errs:
        print("  " + e)
    check(name, not errs)

# Segments 4 and 5 quote no challenge slide yet; Challenge 3 and 4's slides are reviewed later, and their quotes
# come in under check 2 when they do. Name that here so the count reads as checked, not missed.
for start, n, end in SEGMENTS[2:]:
    count = len(QUOTED_CHALLENGE.findall(segment(ros, start, end)))
    print(f"INFO {start} Challenge {n}: {count} quoted header line(s)")

# The checks can fail: put the bare header back where #1039 changed it, and a wrong number in segment 3.
need(ros, f"> {header(1)}")
bare = ros.replace(f"> {header(1)}", "> Challenge 1")
got = problems(bare)
check("a bare '> Challenge 1' in segment 2 fails the segment 2 check",
      bool(got["segment 2 quotes the Challenge 1 header on both its challenge slide and its hint slide"]))
check("a bare '> Challenge 1' in segment 2 fails the hint slide check",
      bool(got["segment 2's hint slide quote opens on the header and adds the Ophelia Thorn hint"]))
check("a bare '> Challenge 1' in segment 2 fails the every-header check",
      bool(got["every quoted challenge header in segments 2 to 5 is 'Challenge N - attackme.burritobot.co' for its own N"]))
need(ros, f"> {header(2)}")
wrong = ros.replace(f"> {header(2)}", f"> {header(3)}", 1)
check("a Challenge 3 header quoted in segment 3 fails the every-header check",
      bool(problems(wrong)["every quoted challenge header in segments 2 to 5 is "
                           "'Challenge N - attackme.burritobot.co' for its own N"]))
seg4_start = SEGMENTS[2][0]
bare4 = ros.replace(seg4_start, seg4_start + "\n\n  > Challenge 3\n", 1)
check("a bare '> Challenge 3' added to segment 4 fails the every-header check",
      bool(problems(bare4)["every quoted challenge header in segments 2 to 5 is "
                           "'Challenge N - attackme.burritobot.co' for its own N"]))

if failures:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
print("\nall challenge header checks passed")
