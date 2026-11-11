# ABOUTME: Holds the KubeCon run-of-show's segments table row 3 and the paragraph under the table to the 2026-11-07
# ABOUTME: deck's close (#1095, #1112): slide 28's text, then slide 29's retry, then one set per guardrail.
"""The segments table's segment 3 row and the paragraph under it follow the 2026-11-07 deck (#1112).

#1095 moved segment 3 of `facilitation/kubecon-na-2026-run-of-show.md` onto the deck Whitney walked on 2026-11-07:
slide 28 reads "Let's turn on Kubernetes guardrails.", slide 29 is the room's retry, "Try your attacks again.", and
slides 30 to 42 are one set per guardrail. Its other tests read the segment's own steps; this one reads the two
places in "## The segments, in order" that summarise it:

  1. Row 3 of the segments table (the row whose "#" cell is 3) names slide 28's text, then slide 29's retry, then
     one set per guardrail on slides 30 to 42, in that order.
  2. The paragraph under the table ("Total 30 minutes. ...") names the same three, in the same order.
  3. Neither says "one slide per guardrail" or "four slides" any more (the 2026-11-06 deck's "its four slides").

Each cut on repo text checks its literal first and exits naming the literal and the file when it is gone ("Tests own
their inputs"). Each check is then run on a copy with one phrase removed, the order swapped, or the old wording put
back, so a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
SECTION = "## The segments, in order"
HEADER = "| # | Min | Who | On screen | The room | Abstract points |"
PARAGRAPH = "Total 30 minutes."

# What each place must name, in this order (whitespace is flattened before matching).
ROW_PHRASES = [
    ("slide 28's text", "\"Let's turn on Kubernetes guardrails.\" (slide 28)"),
    ("slide 29's retry", "\"Try your attacks again.\" (slide 29)"),
    ("one set per guardrail", "one set per guardrail on slides 30 to 42"),
]
PARA_PHRASES = [
    ("slide 28's text", "\"Let's turn on Kubernetes guardrails.\" on slide 28"),
    ("slide 29's retry", "slide 29's retry, \"Try your attacks again.\""),
    ("one set per guardrail", "one set per guardrail on slides 30 to 42"),
]
STALE = ("one slide per guardrail", "four slides")

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def need(text: str, literal: str, where: str) -> None:
    if literal not in text:
        sys.exit(f"ANCHOR MISSING: {literal!r} is not in {where} of {ROS_PATH}; the segments table checks cut on it")


def flat(text: str) -> str:
    return " ".join(text.split())


def parts(ros: str) -> tuple[str, str]:
    """Row 3 of the segments table and the paragraph under the table."""
    need(ros, SECTION, "the file")
    section = ros.split(SECTION, 1)[1].split("\n## ", 1)[0]
    need(section, HEADER, f"{SECTION!r}")
    lines = section.split(HEADER, 1)[1].lstrip("\n").splitlines()
    table = []
    for ln in lines:
        if not ln.startswith("|"):
            break
        table.append(ln)
    rows = [ln for ln in table if re.match(r"\|\s*3\s*\|", ln)]
    if len(rows) != 1:
        sys.exit(f"ANCHOR MISSING: the segments table under {HEADER!r} in {ROS_PATH} has {len(rows)} rows numbered 3")
    rest = "\n".join(lines[len(table):]).lstrip("\n")
    if not rest.startswith(PARAGRAPH):
        sys.exit(f"ANCHOR MISSING: the paragraph under the segments table in {ROS_PATH} does not start {PARAGRAPH!r}")
    return rows[0], rest.split("\n\n", 1)[0]


def verdicts(row: str, para: str) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for label, text, phrases in (("row 3", row, ROW_PHRASES), ("the paragraph under the table", para, PARA_PHRASES)):
        f = flat(text)
        for what, phrase in phrases:
            out[f"{label} names {what}"] = phrase in f
        pos = [f.find(p) for _, p in phrases]
        out[f"{label} names slide 28's text, then slide 29's retry, then one set per guardrail"] = (
            all(p >= 0 for p in pos) and pos == sorted(pos))
        for old in STALE:
            out[f"{label} no longer says {old!r}"] = old not in f.lower()
    return out


def main() -> None:
    row, para = parts(ROS_PATH.read_text(encoding="utf-8"))
    real = verdicts(row, para)
    for name, ok in real.items():
        check(name, ok)

    print("== each check can fail ==")
    for idx, (label, phrases) in enumerate((("row 3", ROW_PHRASES), ("the paragraph under the table", PARA_PHRASES))):
        def run(text: str) -> dict[str, bool]:
            return verdicts(text, para) if idx == 0 else verdicts(row, text)
        text = flat(row if idx == 0 else para)
        for what, phrase in phrases:
            name = f"{label} names {what}"
            check(f"{label} without {what} fails", not run(text.replace(phrase, "the guardrail slides"))[name])
        first, last = phrases[0][1], phrases[2][1]
        swapped = text.replace(first, "\0").replace(last, first).replace("\0", last)
        check(f"{label} with slide 28's text and the sets swapped fails the order check",
              not run(swapped)[f"{label} names slide 28's text, then slide 29's retry, then one set per guardrail"])
        for old in STALE:
            check(f"{label} with {old!r} put back fails",
                  not run(text + f" {old.capitalize()}.")[f"{label} no longer says {old!r}"])
        broken = re.sub(r"one set per guardrail", "its four slides", text)
        check(f"{label} with the 2026-11-06 close's 'its four slides' fails",
              not run(broken)[f"{label} no longer says 'four slides'"])

    if failures:
        print(f"\n{len(failures)} FAILED", file=sys.stderr)
        sys.exit(1)
    print("\nSEGMENTS TABLE SEGMENT 3 GREEN")


if __name__ == "__main__":
    main()
