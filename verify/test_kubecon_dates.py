# ABOUTME: Holds the KubeCon NA 2026 dates (#447) in the run-of-show: the build order with no forecast dates,
# ABOUTME: the people's dates, and a run-through record whose targets agree with the segment table.
"""The KubeCon breakout's dates and its run-through record (#447).

The dates moved here from the archived BurritoBot repo. Michael's revision of 2026-10-24 keeps dates only for
people: the cold read once the platform is live, the Datadog pool the week of 10-26, two timed run-throughs by
11-08, delivery on 11-12. The 10-28 rehearsal with Whitney is kept too (question 845 on #457): the cold read's
slot if it has not run live by then, otherwise run-through 1. Everything agents build is listed in order, with no forecast date.

The record's targets are derived from the segment table, not typed twice: if a segment's minutes change, the
whole-slot and demo targets have to change with them, and this test says so. The delivery date is the same
one `verify/model_pin_check.py` checks the model against. The slot time and room stay in conference-knowledge
(#417), so this file must name the registry entry and must not copy them.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
PIN = (REPO / "verify/model_pin_check.py").read_text(encoding="utf-8")
WHITNEY = (REPO / "facilitation/WHITNEY-START-HERE.md").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def section(text: str, heading: str) -> str:
    """The body under a markdown heading, up to the next heading of the same or a higher level."""
    m = re.search(rf"^(#+) {re.escape(heading)}\s*$", text, re.M)
    if not m:
        return ""
    level = len(m.group(1))
    rest = text[m.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


def table_rows(body: str) -> list[list[str]]:
    rows = []
    for line in body.splitlines():
        if line.startswith("|") and not re.match(r"^\|[-| ]+\|$", line):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def mmss(minutes: int) -> str:
    return f"{minutes}:00"


dates = section(ROS, "Dates to hold (#447)")
record = section(ROS, "Run-through record")

print("== the dates section exists and names its source ==")
check("a 'Dates to hold (#447)' section", bool(dates))
check("it names Michael's 2026-10-24 revision", "2026-10-24" in dates and "Michael" in dates)

print("== agent-built work is in order, with no forecast date ==")
build = re.findall(r"^\d+\. \*\*(.+?)\*\*", dates, re.M)
check("three build steps", len(build) == 3)
order = ["Platform live on AWS", "Every abstract point READY", "recorded fallback"]  # no deck upload (2026-10-28)
check("in Michael's order: platform, points, fallback",
      len(build) == 3 and all(o.lower() in b.lower() for o, b in zip(order, build)))
check("the build steps carry no 'by <date>' deadline",
      not re.search(r"^\d+\. .*\b[Bb]y \d{4}-\d{2}-\d{2}", dates, re.M))
check("the platform comes up from fleet.sh", "`fleet.sh`" in dates)

print("== dates for people ==")
people = {r[0]: r for r in table_rows(dates) if len(r) == 4}
cold = people.get("Cold read of this run-of-show", [])
check("cold read: Whitney, once the platform is live",
      len(cold) == 4 and cold[1] == "Whitney" and cold[2].startswith("Once the platform is live"))
check("cold read: the calendar hold, Mon 2026-10-26 10:00 to 16:00 Central",
      len(cold) == 4 and "2026-10-26, 10:00 to 16:00 Central" in cold[2])
check("cold read: against the live platform, each stop filed as an issue",
      len(cold) == 4 and "live platform" in cold[3] and "issue" in cold[3])
reh = people.get("Rehearsal with Whitney", [])
check("rehearsal: the calendar hold Michael kept, Wed 2026-10-28 09:00 to 12:00 Central (#457)",
      len(reh) == 4 and reh[1] == "Michael and Whitney"
      and "2026-10-28, 09:00 to 12:00 Central" in reh[2] and "question 845" in reh[2])
check("rehearsal: the cold read if it has not run live yet, otherwise run-through 1",
      len(reh) == 4 and "cold read" in reh[3] and "run-through 1" in reh[3] and "Run-through record" in reh[3])
dd = people.get("Datadog org pool (abstract point 7)", [])
check("Datadog pool: Whitney, the week of 2026-10-26",
      len(dd) == 4 and dd[1] == "Whitney" and "2026-10-26" in dd[2])
runs = people.get("Two timed run-throughs", [])
check("run-throughs: Michael and Whitney, by 2026-11-08",
      len(runs) == 4 and runs[1] == "Michael and Whitney" and runs[2] == "By 2026-11-08")
check("run-throughs: demo included, timed against the 30-minute slot, findings filed",
      len(runs) == 4 and "demo included" in runs[3] and "30-minute slot" in runs[3] and "filed" in runs[3])
deliv = people.get("Delivered", [])
check("delivered: 2026-11-12", len(deliv) == 4 and deliv[2] == "2026-11-12")
pin = re.search(r'^DELIVERY_DATE = "(\d{4}-\d{2}-\d{2})"', PIN, re.M)
check("the model pin check holds the same delivery date",
      bool(pin) and len(deliv) == 4 and pin.group(1) == deliv[2])

print("== slot time and room stay in conference-knowledge (#417) ==")
check("the delivered row names the registry entry and its schedule",
      len(deliv) == 4 and "`kubecon-na-2026`" in deliv[3] and "`schedule`" in deliv[3])
check("no Mountain-time slot copied into the run-of-show",
      not re.search(r"\d{1,2}:\d{2}\s*(to|-)\s*\d{1,2}:\d{2}\s*M[SD]T", ROS))
check("no room copied into the run-of-show", "Ballroom" not in ROS)

print("== the run-through record agrees with the segment table ==")
seg_rows = [r for r in table_rows(section(ROS, "The segments, in order (30 minutes)")) if r[0].isdigit()]
minutes = {int(r[0]): int(r[1]) for r in seg_rows}
check("the segment table has segments 1 to 6", sorted(minutes) == list(range(1, 7)))  # three challenges (#639)
rec = table_rows(record)
check("a record table with one column per run",
      bool(rec) and rec[0][1:] == ["Run-through 1", "Run-through 2", "Delivered"])
labels = {r[0]: r for r in rec[1:]}
whole = sum(minutes.values())
demo = sum(m for s, m in minutes.items() if 2 <= s <= 5)
check(f"whole-slot target is the segments' total, {mmss(whole)}",
      f"Whole slot (target {mmss(whole)})" in labels)
check("the whole slot is the 30-minute slot", whole == 30)
check(f"demo target is segments 2 to 5, {mmss(demo)}",
      f"Demo, segments 2 to 5 (target {mmss(demo)})" in labels)
for s, m in sorted(minutes.items()):
    check(f"segment {s} row, target {mmss(m)}", f"Segment {s} (target {mmss(m)})" in labels)
check("every row has a cell per run", all(len(r) == 4 for r in rec))
for row in ("Date", "Presenters", "Fallbacks driven (beat and script)", "Findings filed (issue numbers)"):
    check(f"a '{row}' row", row in labels)
check("findings go to issues in this repo", "issue in\nthis repo" in record or "issue in this repo" in record)
check("the cold read has its own entry, untimed",
      "**Cold read**" in record and "Findings filed (issue numbers):" in record)

print("== Whitney's start page points at the dates ==")
check("WHITNEY-START-HERE names the 'Dates to hold' section", '"Dates to hold"' in WHITNEY)

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nKUBECON DATES GREEN")
