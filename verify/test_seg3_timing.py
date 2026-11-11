# ABOUTME: Holds segment 3's beat budget in the KubeCon run-of-show (#1040): each time column's beats add up to
# ABOUTME: its Segment 3 row, the budget names the deck's close on slides 29 to 43, and the rehearsal's beat times
# ABOUTME: are all there or all waiting, tied to the Run-through record (#1297).
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
  4. The budget is for the 2026-11-07 deck: it names slide 30's retry and the guardrail sets on slides 31 to 43,
     and no longer the four single guardrail slides. It also names its re-read of 2026-11-09 against deck commit
     4dd5bbb0, the deck the rehearsal times, with the 326 words slides 31 to 43 then read.
  5. Michael and Whitney time segment 3 in a rehearsal, beat by beat, against that budget (#1297). The Rehearsal
     column is either empty on every row or an m:ss time on every row, never part-timed. It is tied to the
     "Run-through record": once a run-through's Date row reads anything but "not yet run", or its Segment 3 row
     holds a time, every beat must be timed; once the column is timed, its Segment 3 total must be the Segment 3
     time of run-through 1 or 2. While the column is empty, the Timing paragraph must say it waits on a timed run;
     once it is timed, the paragraph may no longer say so. So the test is green while the rehearsal has not run
     and that is on record, and fails on a run-through recorded without its beat times.

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
RECORD = "### Run-through record"
RECORD_HEAD = "| | Run-through 1 | Run-through 2 | Delivered |"
DATE_ROW = "Date"
SEG3_ROW = "Segment 3 (target 5:00)"
NOT_RUN = "not yet run"
WAITS = "Rehearsal column waits on a later one"

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
    out["the budget names slide 30's retry and the sets on slides 31 to 43"] = (
        "slide 30's retry" in flat and "one set per guardrail on slides 31 to 43" in flat)
    out["the budget names the 2026-11-07 deck commit it was read from"] = "deck commit `903f26cb`" in flat
    out["the budget names the 2026-11-09 re-read, deck commit 4dd5bbb0, and its 326 words on slides 31 to 43"] = (
        "deck commit `4dd5bbb0`" in flat and "slides 31 to 43 read 326 words" in flat)
    return out


def record_table(ros: str) -> str:
    """The Run-through record's table, its header line to the first line that is not a table row."""
    for lit in (RECORD, RECORD_HEAD, "| " + DATE_ROW + " |", "| " + SEG3_ROW + " |"):
        need(ros, lit)
    rec = ros.split(RECORD, 1)[1]
    need(rec, RECORD_HEAD)
    lines = rec.split(RECORD_HEAD, 1)[1].splitlines()[1:]
    rows = [RECORD_HEAD]
    for ln in lines:
        if not ln.startswith("|"):
            break
        rows.append(ln)
    return "\n".join(rows)


def record_row(record: str, label: str) -> list[str]:
    for r in table(record):
        if r and r[0] == label:
            return r[1:]
    return []


def rehearsal_verdicts(block: str, record: str) -> dict[str, bool]:
    """The rehearsal's beat-by-beat times against the budget and the Run-through record (#1297)."""
    out: dict[str, bool] = {}
    rows = table(block)
    body = [r for r in rows[2:] if len(r) == len(HEADER)] if len(rows) > 2 else []
    beats = [r[4] for r in body if r[0] != TOTAL]
    totals = [r[4] for r in body if r[0] == TOTAL]
    cells = beats + totals
    timed = bool(beats) and all(secs(c) is not None for c in cells)
    empty = bool(beats) and not any(cells)
    out["the Rehearsal column is timed on every beat or on none"] = timed or empty

    dates = record_row(record, DATE_ROW)
    seg3 = record_row(record, SEG3_ROW)
    out["the Run-through record has its Date and Segment 3 rows, one cell per run"] = len(dates) == 3 == len(seg3)
    runs = list(zip(dates[:2], seg3[:2]))
    ran = [i for i, (d, t) in enumerate(runs) if d != NOT_RUN or t]
    out["a run-through on record has segment 3 timed beat by beat in the Rehearsal column"] = not ran or timed
    if timed:
        total = totals[0] if totals else ""
        out["the Rehearsal column's total is a run-through's Segment 3 time"] = any(t == total for _, t in runs)

    flat = " ".join(block.split())
    if empty:
        out["the empty Rehearsal column is stated as waiting on a timed run"] = WAITS in flat
    if timed:
        out["the timed Rehearsal column is no longer stated as waiting"] = WAITS not in flat
    return out


def with_rehearsal(block: str, times: dict[str, str]) -> str:
    """The block with each named row's Rehearsal cell set; rows not named keep their cell."""
    out = block
    for ln in block.splitlines():
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) == len(HEADER) and cells[0] in times:
            cells[4] = times[cells[0]]
            out = out.replace(ln, "| " + " | ".join(cells) + " |")
    return out


def with_record(record: str, label: str, run: int, value: str) -> str:
    for ln in record.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if cells and cells[0] == label:
            cells[1 + run] = value
            return record.replace(ln, "| " + " | ".join(cells) + " |")
    sys.exit(f"ANCHOR MISSING: no {label!r} row in the Run-through record of {ROS_PATH}")


def rehearsal_cases(block: str, record: str) -> None:
    """Each rehearsal check fails on a copy built to break it, and a full, consistent rehearsal passes."""
    rows = [r for r in table(block)[2:] if len(r) == len(HEADER)]
    beats = [r for r in rows if r[0] != TOTAL]
    if not beats:
        sys.exit(f"ANCHOR MISSING: no beat row under {TIMING!r} in {ROS_PATH}")
    deck = {r[0]: r[2] for r in rows}  # a stopwatch that read the deck column, total included
    if WAITS not in " ".join(block.split()):
        sys.exit(f"ANCHOR MISSING: {WAITS!r} is not in the Timing paragraph of {ROS_PATH}")
    total = deck[TOTAL]
    timed = with_rehearsal(block, deck)
    timed = re.sub(r"\s+".join(WAITS.split()), "Rehearsal column holds run-through 1", timed)
    ran = with_record(with_record(record, DATE_ROW, 0, "2026-11-10"), SEG3_ROW, 0, total)

    def fails(name: str, b: str, r: str, key: str) -> None:
        check(name, rehearsal_verdicts(b, r).get(key) is False)

    good = {**verdicts(timed), **rehearsal_verdicts(timed, ran)}
    check("a rehearsal timed on every beat, adding up and on record as run-through 1, passes",
          "the filled Rehearsal column adds up" in good and all(good.values()))
    fails("one beat timed and the rest empty fails", with_rehearsal(block, {beats[0][0]: "0:45"}), record,
          "the Rehearsal column is timed on every beat or on none")
    fails("a timed column with one beat emptied fails", with_rehearsal(timed, {beats[-1][0]: ""}), ran,
          "the Rehearsal column is timed on every beat or on none")
    fails("run-through 1 dated with no beat timed fails", block, with_record(record, DATE_ROW, 0, "2026-11-10"),
          "a run-through on record has segment 3 timed beat by beat in the Rehearsal column")
    fails("run-through 2's Segment 3 time with no beat timed fails", block,
          with_record(record, SEG3_ROW, 1, "5:10"),
          "a run-through on record has segment 3 timed beat by beat in the Rehearsal column")
    fails("a timed column whose total is in no run-through's Segment 3 row fails", timed,
          with_record(record, DATE_ROW, 0, "2026-11-10"),
          "the Rehearsal column's total is a run-through's Segment 3 time")
    fails("a total written only under Delivered fails", timed,
          with_record(record, SEG3_ROW, 2, total),
          "the Rehearsal column's total is a run-through's Segment 3 time")
    fails("an empty column the paragraph no longer says waits fails",
          re.sub(r"\s+".join(WAITS.split()), "Rehearsal column", block), record,
          "the empty Rehearsal column is stated as waiting on a timed run")
    fails("a timed column the paragraph still says waits fails", with_rehearsal(block, deck), ran,
          "the timed Rehearsal column is no longer stated as waiting")


def main() -> None:
    ros = ROS_PATH.read_text()
    block = timing_block(ros)
    record = record_table(ros)
    real = verdicts(block)
    real.update(rehearsal_verdicts(block, record))
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
          not verdicts(re.sub(r"one\s+set\s+per\s+guardrail\s+on\s+slides\s+31\s+to\s+43", "four guardrail slides",
                              block))[
              "the budget names slide 30's retry and the sets on slides 31 to 43"])

    check("a budget without the 2026-11-09 re-read fails the re-read check",
          not verdicts(block.replace("`4dd5bbb0`", "`903f26cb`"))[
              "the budget names the 2026-11-09 re-read, deck commit 4dd5bbb0, and its 326 words on slides 31 to 43"])

    rehearsal_cases(block, record)

    if failures:
        print(f"\n{len(failures)} FAILED", file=sys.stderr)
        sys.exit(1)
    print("\nSEGMENT 3 TIMING GREEN")


if __name__ == "__main__":
    main()
