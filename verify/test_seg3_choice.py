# ABOUTME: Holds #1040's choice for segment 3's extra time in the KubeCon run-of-show (#1298): while open, the three
# ABOUTME: options stand and no rehearsal time is written without a choice; once settled, one option and both tables agree.
"""Segment 3's choice: take the cut, change the deck's waits, or move time from another segment (#1040, #1298).

#1040 has Michael and Whitney time segment 3 and settle its extra time one of three ways. The run-of-show's
segment 3 "Timing" paragraph offers the three ("The rehearsal settles one of three: ...") and says how the choice
is written: a paragraph after the beat table opening `**Settled (YYYY-MM-DD).**` that names one option in the
paragraph's words. Until they rehearse, the choice is open, so this test holds both states:

Open (no Settled paragraph):
  1. The "settles one of three" sentence still offers the criterion's three: take the cut, change the deck's
     waits, and a minute moved in from another segment, and still says to write the choice here.
  2. No beat in the Rehearsal column is filled: times written with no choice mean the rehearsal ran and the
     criterion was not met.
  3. The segments table still gives segment 3 its 5 minutes.

Settled (a Settled paragraph, dated):
  1. Exactly one Settled paragraph, naming exactly one of "take the cut and move about a minute in from segment N",
     "change the deck's waits", "drop slides from the guardrail sets".
  2. For the first, N is 1, 2, 5 or 6 (not 3, and not 4, whose Challenge 3 also grew); segment 3's row in the
     segments table reads 6 and the other rows still add to 30. For the other two, segment 3 stays at 5.
  3. Every beat in the Rehearsal column is an m:ss time: the choice comes from a timed run.
  4. The Run-through record's Segment 3 row carries an m:ss time in at least one column.

In both states the segments table's minutes add up to 30, the slot.

Each cut on repo text first checks its literal and exits naming it and the file when it is gone ("Tests own their
inputs"). The real file is checked, then a settled copy built from it is checked for each option, then broken
copies of each state are checked to fail, so a check that could never fail shows up here.
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
OFFER = "The rehearsal settles one of three:"
OFFER_END = "Michael and Whitney time each beat in the Rehearsal column"
SEGMENTS = "## The segments, in order"
SEG_HEADER = "| # | Min | Who | On screen | The room | Abstract points |"
RUN_ROW = "| Segment 3 (target"
BEAT_HEADER = "| Beat | Slides | As the deck has it | With the cut | Rehearsal |"
TOTAL = "Segment 3"
SETTLED = re.compile(r"^\*\*Settled \((\d{4}-\d{2}-\d{2})\)\.\*\*", re.M)

# The criterion's three, as the open sentence must still offer them (whitespace flattened before matching).
OFFERED = {
    "take the cut": "take the cut",
    "change the deck's waits": "change the deck's waits",
    "move time from another segment": "move about a minute in from another segment",
}
# The three a Settled paragraph may name, in the open sentence's words.
CHOICES = {
    "move": re.compile(r"take the cut and move about a minute in from segment (\d)"),
    "waits": re.compile(re.escape("change the deck's waits")),
    "drop": re.compile(re.escape("drop slides from the guardrail sets")),
}
GIVERS = {1, 2, 5, 6}
SLOT = 30

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def need(text: str, literal: str, where: str = "") -> None:
    if literal not in text:
        sys.exit(f"ANCHOR MISSING: {literal!r} is not in {where or 'the text'} of {ROS_PATH}; "
                 "the segment 3 choice checks cut on it")


def flat(text: str) -> str:
    return " ".join(text.split())


def secs(cell: str) -> int | None:
    m = re.fullmatch(r"(\d+):([0-5]\d)", cell)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def timing_block(ros: str) -> str:
    for lit in (SEG3, SEG4, TIMING):
        need(ros, lit)
    seg3 = ros.split(SEG3, 1)[1].split(SEG4, 1)[0]
    need(seg3, TIMING, "segment 3")
    # The block runs to the segment's first numbered step.
    return re.split(r"\n1\. ", seg3.split(TIMING, 1)[1], maxsplit=1)[0]


def beat_rows(block: str) -> list[list[str]]:
    need(block, BEAT_HEADER, "segment 3's Timing block")
    lines = block.split(BEAT_HEADER, 1)[1].splitlines()[2:]
    rows = []
    for ln in lines:
        if not ln.startswith("|"):
            break
        rows.append(cells(ln))
    return [r for r in rows if r and r[0] != TOTAL]


def segment_minutes(ros: str) -> dict[int, int]:
    need(ros, SEGMENTS)
    section = ros.split(SEGMENTS, 1)[1]
    need(section, SEG_HEADER, SEGMENTS)
    out: dict[int, int] = {}
    for ln in section.split(SEG_HEADER, 1)[1].splitlines()[2:]:
        if not ln.startswith("|"):
            break
        c = cells(ln)
        if len(c) > 1 and c[0].isdigit() and c[1].isdigit():
            out[int(c[0])] = int(c[1])
    return out


def run_through_times(ros: str) -> list[str]:
    need(ros, RUN_ROW)
    line = next(ln for ln in ros.splitlines() if ln.startswith(RUN_ROW))
    return [c for c in cells(line)[1:] if secs(c) is not None]


def verdicts(ros: str) -> dict[str, bool]:
    out: dict[str, bool] = {}
    block = timing_block(ros)
    beats = beat_rows(block)
    reh = [r[4] if len(r) > 4 else "" for r in beats]
    mins = segment_minutes(ros)
    out["the segments table has six rows adding to the 30-minute slot"] = (
        sorted(mins) == [1, 2, 3, 4, 5, 6] and sum(mins.values()) == SLOT)
    settled = SETTLED.findall(block)
    if not settled:
        fb = flat(block)
        need(fb, OFFER, "segment 3's Timing block")
        need(fb, OFFER_END, "segment 3's Timing block")
        offer = fb.split(OFFER, 1)[1].split(OFFER_END, 1)[0]
        for label, words in OFFERED.items():
            out[f"open: the choice still offers '{label}'"] = words in offer
        out["open: the paragraph still says to write the choice here"] = "write the choice here" in flat(block)
        out["open: no Rehearsal time is written while no choice is"] = bool(beats) and not any(reh)
        out["open: segment 3 keeps its 5 minutes"] = mins.get(3) == 5
        return out
    out["settled: one Settled paragraph"] = len(settled) == 1
    para = flat(block[SETTLED.search(block).start():].split("\n\n", 1)[0])
    named = {k: rx.search(para) for k, rx in CHOICES.items()}
    hits = [k for k, m in named.items() if m]
    out["settled: it names exactly one of the three"] = len(hits) == 1
    if hits == ["move"]:
        giver = int(named["move"].group(1))
        out["settled: the minute comes from segment 1, 2, 5 or 6"] = giver in GIVERS
        out["settled: segment 3's row reads 6 minutes"] = mins.get(3) == 6
    else:
        out["settled: segment 3's row stays at 5 minutes"] = mins.get(3) == 5
    out["settled: every beat in the Rehearsal column is an m:ss time"] = (
        bool(reh) and all(secs(c) is not None for c in reh))
    out["settled: the Run-through record's Segment 3 row has a time"] = bool(run_through_times(ros))
    return out


def settle(ros: str, choice: str, *, minutes: dict[int, int] | None = None, fill: bool = True,
           run_time: bool = True, extra: str = "") -> str:
    """A copy of the run-of-show with the rehearsal run and `choice` written as the paragraph asks."""
    block = timing_block(ros)
    new = block
    if fill:
        for ln in block.splitlines():
            if ln.startswith("|") and not ln.startswith(BEAT_HEADER) and not ln.startswith("|---"):
                c = cells(ln)
                if len(c) == 5:
                    c[4] = "0:30"
                    new = new.replace(ln, "| " + " | ".join(c) + " |")
    para = f"**Settled (2026-11-10).** At the rehearsal they chose to {choice}.{extra}\n"
    new = new.rstrip("\n") + "\n\n" + para + "\n"
    out = ros.replace(block, new)
    if minutes:
        section = out.split(SEGMENTS, 1)[1]
        table = section.split(SEG_HEADER, 1)[1]
        for ln in table.splitlines()[2:]:
            if not ln.startswith("|"):
                break
            c = cells(ln)
            if c[0].isdigit() and int(c[0]) in minutes:
                c[1] = str(minutes[int(c[0])])
                out = out.replace(ln, "| " + " | ".join(c) + " |", 1)
    if run_time:
        line = next(ln for ln in out.splitlines() if ln.startswith(RUN_ROW))
        c = cells(line)
        c[1] = "05:55"
        out = out.replace(line, "| " + " | ".join(c) + " |", 1)
    return out


def all_pass(v: dict[str, bool]) -> bool:
    return bool(v) and all(v.values())


def main() -> None:
    ros = ROS_PATH.read_text()
    real = verdicts(ros)
    for name, ok in real.items():
        check(name, ok)

    mins = segment_minutes(ros)
    move = "take the cut and move about a minute in from segment 1"
    moved = {3: mins.get(3, 5) + 1, 1: mins.get(1, 3) - 1}

    print("== a settled copy passes, for each of the three ==")
    check("settled on the cut and a minute from segment 1 passes", all_pass(verdicts(settle(ros, move, minutes=moved))))
    check("settled on the deck's waits passes", all_pass(verdicts(settle(ros, "change the deck's waits"))))
    check("settled on the guardrail sets passes",
          all_pass(verdicts(settle(ros, "drop slides from the guardrail sets"))))

    print("== each check can fail ==")
    name = "open: no Rehearsal time is written while no choice is"
    beat = next(ln for ln in timing_block(ros).splitlines()
                if ln.startswith("|") and not ln.startswith(BEAT_HEADER) and not ln.startswith("|---"))
    c = cells(beat)
    c[4] = "0:50"
    timed = ros.replace(beat, "| " + " | ".join(c) + " |", 1)
    check("a Rehearsal time with no choice written fails", verdicts(timed).get(name) is False)
    start = re.search(r"\s+".join(map(re.escape, OFFER.split())), ros).end()
    end = re.search(r"\s+".join(map(re.escape, OFFER_END.split())), ros).start()
    for label, words in OFFERED.items():
        cut = re.sub(r"\s+".join(map(re.escape, words.split())), "do something else", ros[start:end])
        broken = ros[:start] + cut + ros[end:]
        check(f"an open choice that no longer offers '{label}' fails",
              verdicts(broken).get(f"open: the choice still offers '{label}'") is False)
    check("an open choice with segment 3 at 6 minutes fails",
          verdicts(settle(ros, move, minutes=moved).replace(
              "**Settled (2026-11-10).**", "**Unsettled.**")).get("open: segment 3 keeps its 5 minutes") is False)
    check("a choice that names none of the three fails",
          verdicts(settle(ros, "shorten the talk"))["settled: it names exactly one of the three"] is False)
    check("a choice that names two of the three fails",
          verdicts(settle(ros, "change the deck's waits and drop slides from the guardrail sets"))[
              "settled: it names exactly one of the three"] is False)
    check("two Settled paragraphs fail",
          verdicts(settle(settle(ros, "change the deck's waits", fill=False, run_time=False),
                          "change the deck's waits"))["settled: one Settled paragraph"] is False)
    check("a minute taken from segment 4 fails",
          verdicts(settle(ros, move.replace("segment 1", "segment 4"), minutes={3: 6, 4: mins.get(4, 7) - 1}))[
              "settled: the minute comes from segment 1, 2, 5 or 6"] is False)
    check("a moved minute with segment 3 still at 5 fails",
          verdicts(settle(ros, move))["settled: segment 3's row reads 6 minutes"] is False)
    check("a moved minute that no segment gives up fails the 30-minute slot",
          verdicts(settle(ros, move, minutes={3: 6}))[
              "the segments table has six rows adding to the 30-minute slot"] is False)
    check("the deck's waits with segment 3 at 6 fails",
          verdicts(settle(ros, "change the deck's waits", minutes=moved))[
              "settled: segment 3's row stays at 5 minutes"] is False)
    check("a choice with the Rehearsal column empty fails",
          verdicts(settle(ros, "change the deck's waits", fill=False))[
              "settled: every beat in the Rehearsal column is an m:ss time"] is False)
    check("a choice with no time in the Run-through record fails",
          verdicts(settle(ros, "change the deck's waits", run_time=False))[
              "settled: the Run-through record's Segment 3 row has a time"] is False)

    if failures:
        print(f"\n{len(failures)} FAILED", file=sys.stderr)
        sys.exit(1)
    print("\nSEGMENT 3 CHOICE GREEN")


if __name__ == "__main__":
    main()
