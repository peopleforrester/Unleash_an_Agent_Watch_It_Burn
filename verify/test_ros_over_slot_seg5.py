# ABOUTME: Holds the KubeCon run-of-show's "Over the slot" paragraph to segment 5's length (#1275): its time, words,
# ABOUTME: slides and diagram words are the ones segment 5's Timing paragraph gives (#1270), read on rounds faf4005.
"""The "Over the slot" paragraph states segment 5's length (#1275, from #1270).

Under "## The segments, in order" of `facilitation/kubecon-na-2026-run-of-show.md`, the paragraph
"**Over the slot (#1196, #1270).**" says how long the spoken notes alone run for segments 4 and 5. #1270 moved
segment 5 to the 127-slide deck: about 5 minutes 30 seconds, 823 words over its 49 slides, 478 of them on the
thirty-eight diagram slides. Segment 5's own "**Timing.**" paragraph is where those numbers are counted, slide range
by slide range. This test holds:

  1. The paragraph states segment 5's length in one phrase: "about M minutes [S seconds] for segment 5 (W words over
     its N slides, D of them on the <number> diagram slides)".
  2. Its words and its time are the Timing paragraph's: the same W, and the same "about M minutes S seconds".
  3. The time is W words at 150 words a minute, to the nearest 30 seconds, and the Timing paragraph's three parts
     (the challenge, the diagrams, the YAML) add up to W, with D the diagrams' part.
  4. Its N is the slides of the segment's range as the Timing paragraph cites it, `#/67` to `#/115` since rounds
     `8f53ce2` renumbered the deck (rounds-agenticburn#170, #1327), and its diagram slide count is the slides of the
     diagrams' range, `#/76` to `#/113`. The segments table's row cites that range, or opens one slide earlier on
     Challenge 4's title card, `#/66`, which `8f53ce2` added and the figures predate.
  5. Both paragraphs name the same rounds commit they were read from, and the paragraph says segment 5 runs past its
     5 minutes on speech alone exactly when its time is over the segments table's 5 minutes.
  6. The paragraph keeps none of the 154-slide deck's segment 5 length it replaced (744 words, about 5 minutes).

Each cut on repo text first checks its literal is there and exits naming the literal and the file when it is not
("Tests own their inputs"). Each check is run again on a copy of the text with one number changed, so a check that
could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
SEGMENTS = "## The segments, in order"
SEG1 = "### Segment 1:"
SEG5 = "### Segment 5:"
SEG6 = "### Segment 6:"
OVER = "**Over the slot ("
TIMING = "**Timing.**"
ROW5 = "| 5 | 5 |"
WPM = 150

LENGTH = re.compile(
    r"about (\d+) minutes(?: (\d+) seconds)? for segment 5 \((\d+) words over its (\d+) slides, (\d+) of them on "
    r"the ([a-z-]+) diagram slides\)")
TIME = re.compile(r"come to (\d+) words, about (\d+) minutes(?: (\d+) seconds)? at 150 words a minute")
PARTS = re.compile(r"(\d+) on the challenge's `#/(\d+)` to `#/(\d+)`, (\d+) on the diagrams' `#/(\d+)` to `#/(\d+)` "
                   r"and (\d+) on the YAML's `#/(\d+)` and `#/(\d+)`")
SPAN = re.compile(r"notes on `#/(\d+)` to `#/(\d+)` come to")
ROUNDS = re.compile(r"rounds main `([0-9a-f]{7,40})`")
PAST = "so segment 5 runs past its 5 minutes on speech alone"

UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def need(text: str, literal: str, where: str) -> None:
    if literal not in text:
        sys.exit(f"ANCHOR MISSING: {literal!r} is not in {where} of {ROS_PATH}; the over-the-slot checks cut on it")


def number(word: str) -> int | None:
    """An English number word up to ninety-nine, as the run-of-show spells slide counts."""
    if word in UNITS:
        return UNITS.index(word)
    if word in TENS:
        return TENS[word]
    tens, _, unit = word.partition("-")
    if tens in TENS and unit in UNITS[1:10]:
        return TENS[tens] + UNITS.index(unit)
    return None


def paragraph(text: str, lead: str) -> str:
    """The paragraph that opens on `lead`, flattened to one line."""
    body = text.split(lead, 1)[1].split("\n\n", 1)[0]
    return " ".join((lead + body).split())


def blocks(ros: str) -> tuple[str, str, str]:
    """The over-the-slot paragraph, segment 5's Timing paragraph and the segments table's segment 5 row."""
    need(ros, SEGMENTS, "the file")
    segments = ros.split(SEGMENTS, 1)[1]
    need(segments, SEG1, "the part after " + repr(SEGMENTS))
    segments = segments.split(SEG1, 1)[0]
    need(segments, OVER, repr(SEGMENTS))
    need(segments, ROW5, repr(SEGMENTS))
    row = next(ln for ln in segments.splitlines() if ln.startswith(ROW5))
    need(ros, SEG5, "the file")
    seg5 = ros.split(SEG5, 1)[1]
    need(seg5, SEG6, "the part after " + repr(SEG5))
    seg5 = seg5.split(SEG6, 1)[0]
    need(seg5, TIMING, repr(SEG5))
    return paragraph(segments, OVER), paragraph(seg5, TIMING), row


def secs(minutes: str, seconds: str | None) -> int:
    return int(minutes) * 60 + int(seconds or 0)


def verdicts(over: str, timing: str, row: str) -> dict[str, bool]:
    out: dict[str, bool] = {}
    length = LENGTH.search(over)
    time = TIME.search(timing)
    parts = PARTS.search(timing)
    span = SPAN.search(timing)
    out["the paragraph states segment 5's time, words, slides and diagram words"] = bool(length)
    out["segment 5's Timing paragraph gives its words and time at 150 words a minute"] = bool(time)
    if not (length and time):
        return out
    minutes, seconds, words, slides, diagram_words, diagram_slides = length.groups()
    over_secs = secs(minutes, seconds)
    timing_secs = secs(time.group(2), time.group(3))
    out["the paragraph's word count is the Timing paragraph's"] = int(words) == int(time.group(1))
    out["the paragraph's time is the Timing paragraph's"] = over_secs == timing_secs
    out["the time is the words at 150 a minute, to the nearest 30 seconds"] = (
        over_secs == round(int(words) * 60 / WPM / 30) * 30)
    out["the Timing paragraph's three parts add up to its words"] = bool(parts) and (
        int(parts.group(1)) + int(parts.group(4)) + int(parts.group(7)) == int(time.group(1)))
    out["the paragraph's diagram words are the Timing paragraph's diagram part"] = bool(parts) and (
        int(diagram_words) == int(parts.group(4)))
    out["the paragraph's slide count is the segment's range in the Timing paragraph"] = bool(span) and (
        int(slides) == int(span.group(2)) - int(span.group(1)) + 1)
    count = number(diagram_slides)
    out["the paragraph's diagram slide count is the diagrams' range"] = bool(parts) and count is not None and (
        count == int(parts.group(6)) - int(parts.group(5)) + 1)
    # The row may open one slide earlier, on Challenge 4's title card, which rounds 8f53ce2 added after the Timing
    # paragraph's figures were read (rounds-agenticburn#170, #1327); the length is left as it is (Michael, 2026-11-11).
    out["the segments table's segment 5 row cites the same range"] = bool(span) and (
        f"`#/{span.group(1)}` to `#/{span.group(2)}`" in row
        or (f"`#/{int(span.group(1)) - 1}` to `#/{span.group(2)}`" in row and "title card" in row))
    over_rounds, timing_rounds = ROUNDS.findall(over), ROUNDS.findall(timing)
    out["both paragraphs were read from the same rounds commit"] = (
        len(over_rounds) == 1 and over_rounds == timing_rounds)
    slot = row.split("|")[2].strip()
    out["the paragraph says segment 5 runs past its slot exactly when it does"] = slot.isdigit() and (
        (PAST in over) == (over_secs > int(slot) * 60))
    out["the paragraph keeps none of the 154-slide deck's segment 5 length"] = (
        "744 words" not in over and "about 5 minutes for segment 5" not in over and "154 slides" not in over)
    return out


def main() -> None:
    ros = ROS_PATH.read_text()
    over, timing, row = blocks(ros)
    for name, ok in verdicts(over, timing, row).items():
        check(name, ok)

    print("== each check can fail ==")
    length = LENGTH.search(over)
    if not length:
        sys.exit(f"ANCHOR MISSING: segment 5's length phrase is not in the over-the-slot paragraph of {ROS_PATH}")
    phrase = length.group(0)

    def fails(name: str, o: str = over, t: str = timing, r: str = row) -> bool:
        return verdicts(o, t, r).get(name) is False

    w = int(length.group(3))
    cases = [
        ("a dropped length phrase", "the paragraph states segment 5's time, words, slides and diagram words",
         over.replace(phrase, "about as long as before"), timing),
        ("a word count off by one", "the paragraph's word count is the Timing paragraph's",
         over.replace(f"({w} words", f"({w + 1} words"), timing),
        ("a time moved by a minute", "the paragraph's time is the Timing paragraph's",
         over.replace(phrase, phrase.replace(f"about {length.group(1)} minutes",
                                             f"about {int(length.group(1)) + 1} minutes")), timing),
        ("a slide count off by one", "the paragraph's slide count is the segment's range in the Timing paragraph",
         over.replace(f"over its {length.group(4)} slides", f"over its {int(length.group(4)) + 1} slides"), timing),
        ("diagram words off by one", "the paragraph's diagram words are the Timing paragraph's diagram part",
         over.replace(f", {length.group(5)} of them", f", {int(length.group(5)) + 1} of them"), timing),
        ("a diagram slide count of twenty-three", "the paragraph's diagram slide count is the diagrams' range",
         over.replace(f"the {length.group(6)} diagram slides", "the twenty-three diagram slides"), timing),
        ("a Timing part that no longer adds up", "the Timing paragraph's three parts add up to its words",
         over, re.sub(r"(\d+) on the YAML's", lambda m: f"{int(m.group(1)) + 1} on the YAML's", timing)),
        ("another rounds commit", "both paragraphs were read from the same rounds commit",
         ROUNDS.sub("rounds main `0000000`", over), timing),
        ("the run-past sentence dropped", "the paragraph says segment 5 runs past its slot exactly when it does",
         over.replace(PAST, "so segment 5 fits"), timing),
        ("the old 744-word length kept", "the paragraph keeps none of the 154-slide deck's segment 5 length",
         over + " It used to come to 744 words.", timing),
    ]
    for label, name, o, t in cases:
        if o == over and t == timing:
            sys.exit(f"SELF-CHECK BROKEN: {label!r} changed nothing in {ROS_PATH}; its literal moved")
        check(f"{label} fails '{name}'", fails(name, o, t))
    both = re.sub(r"come to (\d+) words", lambda m: f"come to {int(m.group(1)) + 150} words", timing)
    check("a Timing word count that moved alone fails the paragraph's word count check",
          fails("the paragraph's word count is the Timing paragraph's", over, both))
    moved = over.replace(phrase, phrase.replace(f"({w} words", f"({w + 150} words"))
    check("a word count moved by a minute fails the 150-a-minute check",
          fails("the time is the words at 150 a minute, to the nearest 30 seconds", moved, timing))
    check("a segments table row with another range fails the row check",
          fails("the segments table's segment 5 row cites the same range", over, timing,
                row.replace("`#/115`", "`#/98`")))
    check("a segments table row opening on the card without naming it fails the row check",
          fails("the segments table's segment 5 row cites the same range", over, timing,
                row.replace("the title card, ", "")))

    if failures:
        print(f"\n{len(failures)} FAILED", file=sys.stderr)
        sys.exit(1)
    print("\nOVER-THE-SLOT SEGMENT 5 LENGTH GREEN")


if __name__ == "__main__":
    main()
