# ABOUTME: Holds segment 3's beat budget in the KubeCon run-of-show (#1040): each time column's beats add up to
# ABOUTME: its Segment 3 row, and the budget names the 2026-11-07 deck's close on slides 28 to 42.
"""Segment 3's 'Timing' budget adds up (#1040).

The run-of-show's segment 3 'Timing' carries a beat table: one row per beat, the deck's slides, the time as the
deck has it, the time with the proposed cut, and a Rehearsal column that Michael and Whitney fill with a stopwatch.
Its last row, "Segment 3", is each column's total. This test holds:

  1. The table is there, under the Timing paragraph of "### Segment 3:", with those five columns.
  2. In the "As the deck has it" and "With the cut" columns every beat is an m:ss time and the beats add up to the
     Segment 3 row. The Rehearsal column, once every beat in it is filled, adds up too; while any is empty it is
     left as written, since the rehearsal has not run.
  3. The paragraph's own totals agree with the table: "about 8 minutes 40 seconds" for the deck as it is, and the
     cut's "about 6 minutes", to the nearest minute of the cut's total.
  4. The budget is for the 2026-11-07 deck: it names slide 29's retry and the guardrail sets on slides 30 to 42,
     and no longer the four single guardrail slides.

Each cut on repo text first checks its literal is there and exits naming the literal and the file when it is not
("Tests own their inputs"). Each check is also run on a copy of the text with one beat changed, so a check that
could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
SEG3 = "### Segment 3:"
SEG4 = "### Segment 4:"
TIMING = "**Timing (#1003, #1040).**"
HEADER = ["Beat", "Slides", "As the deck has it", "With the cut", "Rehearsal"]
TOTAL = "Segment 3"

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def need(text: str, literal: str) -> None:
    if literal not in text:
        sys.exit(f"ANCHOR MISSING: {literal!r} is not in {ROS_PATH}; the segment 3 timing checks cut on it")


def timing_block(ros: str) -> str:
    for lit in (SEG3, SEG4, TIMING):
        need(ros, lit)
    seg3 = ros.split(SEG3, 1)[1].split(SEG4, 1)[0]
    need(seg3, TIMING)
    block = seg3.split(TIMING, 1)[1]
    # The block runs to the segment's first numbered step.
    return re.split(r"\n1\. ", block, maxsplit=1)[0]


def table(block: str) -> list[list[str]]:
    rows = [ln for ln in block.splitlines() if ln.startswith("|")]
    return [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in rows]


def secs(cell: str) -> int | None:
    m = re.fullmatch(r"(\d+):([0-5]\d)", cell)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def verdicts(block: str) -> dict[str, bool]:
    out: dict[str, bool] = {}
    rows = table(block)
    out["the beat table has the five columns"] = bool(rows) and rows[0] == HEADER
    body = [r for r in rows[2:] if len(r) == len(HEADER)] if len(rows) > 2 else []
    out["every row has a cell per column"] = len(body) == len(rows) - 2 and len(body) >= 3
    beats = [r for r in body if r[0] != TOTAL]
    totals = [r for r in body if r[0] == TOTAL]
    out["one Segment 3 row, the last"] = len(totals) == 1 and bool(body) and body[-1][0] == TOTAL
    sums: dict[str, int] = {}
    for col in (2, 3):
        vals = [secs(r[col]) for r in beats]
        tot = secs(totals[0][col]) if totals else None
        ok = bool(vals) and all(v is not None for v in vals) and tot is not None
        out[f"'{HEADER[col]}' beats are m:ss and add up to the Segment 3 row"] = ok and sum(vals) == tot
        if tot is not None:
            sums[HEADER[col]] = tot
    reh = [r[4] for r in beats]
    if reh and all(reh):
        vals = [secs(c) for c in reh]
        tot = secs(totals[0][4]) if totals else None
        out["the filled Rehearsal column adds up"] = all(v is not None for v in vals) and tot == sum(vals)
    flat = " ".join(block.split())
    deck = sums.get("As the deck has it")
    out["the paragraph's 'about 8 minutes 40 seconds' is the deck column's total"] = (
        deck == 8 * 60 + 40 and "about 8 minutes 40 seconds" in flat)
    cut = sums.get("With the cut")
    m = re.search(r"That comes to about (\d+) minutes", flat)
    out["the paragraph's cut total rounds the cut column's"] = bool(m) and cut is not None and (
        int(m.group(1)) == round(cut / 60))
    out["the budget names slide 29's retry and the sets on slides 30 to 42"] = (
        "slide 29's retry" in flat and "one set per guardrail on slides 30 to 42" in flat)
    out["the budget names the 2026-11-07 deck commit it was read from"] = "deck commit `903f26cb`" in flat
    return out


def main() -> None:
    ros = ROS_PATH.read_text()
    block = timing_block(ros)
    real = verdicts(block)
    for name, ok in real.items():
        check(name, ok)

    print("== each check can fail ==")
    rows = table(block)
    beat = next((r for r in rows[2:] if r and r[0] != TOTAL), None)
    if beat is None:
        sys.exit(f"ANCHOR MISSING: no beat row under {TIMING!r} in {ROS_PATH}")
    line = next(ln for ln in block.splitlines() if ln.startswith("| " + beat[0] + " |"))
    for col, label in ((2, "As the deck has it"), (3, "With the cut")):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        cells[col] = "9:59"
        broken = block.replace(line, "| " + " | ".join(cells) + " |")
        name = f"'{label}' beats are m:ss and add up to the Segment 3 row"
        check(f"a beat changed in '{label}' fails its sum", not verdicts(broken)[name])
    full = block
    for r in rows[2:]:
        ln = next(x for x in block.splitlines() if x.startswith("| " + r[0] + " |"))
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        cells[4] = "0:01" if r[0] != TOTAL else "0:02"
        full = full.replace(ln, "| " + " | ".join(cells) + " |")
    check("a filled Rehearsal column that does not add up fails",
          verdicts(full).get("the filled Rehearsal column adds up") is False)
    check("a moved deck total fails the paragraph check",
          not verdicts(re.sub(r"about\s+8\s+minutes\s+40\s+seconds", "about 6 minutes 40 seconds", block))[
              "the paragraph's 'about 8 minutes 40 seconds' is the deck column's total"])
    check("the old four-slide close fails the deck check",
          not verdicts(re.sub(r"one\s+set\s+per\s+guardrail\s+on\s+slides\s+30\s+to\s+42", "four guardrail slides",
                              block))[
              "the budget names slide 29's retry and the sets on slides 30 to 42"])

    if failures:
        print(f"\n{len(failures)} FAILED", file=sys.stderr)
        sys.exit(1)
    print("\nSEGMENT 3 TIMING GREEN")


if __name__ == "__main__":
    main()
