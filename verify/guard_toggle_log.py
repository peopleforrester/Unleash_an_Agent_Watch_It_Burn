# ABOUTME: Reads and judges guard-proxy's guard_toggle log lines (#1052, #1068): one line per guard a /toggle changed,
# ABOUTME: none for a read, each naming the guard, its new and old value, the peer and the X-WIB-Caller header.
"""Shared by the live check (verify/test_guard_toggle_log_live.py), which flips one guard on watch-it-burn-private and
reads guard-proxy's log, and the offline check (verify/test_guard_toggle_record.py), which holds decisions.md's
record of that read and runs these judges on made-up logs.

guard-proxy writes one JSON object per log line (proxy.py's _TraceJsonFormatter). A /toggle that changes a guard
writes, per changed guard, `"event": "guard_toggle"` with `guard`, `value`, `was`, `peer` and `caller`
(proxy.py's _log_toggles, guard-proxy-agenticburn#67, commit 0e7f15b); a /toggle that changes nothing writes none.
"""
from __future__ import annotations

import json
import re

EVENT = "guard_toggle"
FIELDS = ("guard", "value", "was", "peer", "caller")
# proxy.py's TOGGLE_CALLER_MAX: how much of the X-WIB-Caller header a line keeps.
CALLER_MAX = 200
# The guard the live check flips: the output guard, the exfil sidecar. It changes no other guard and no cost cap.
GUARD = "output"

# The line the live check prints and decisions.md records.
RECORD_PREFIX = "guard_toggle read:"
RECORD_RE = re.compile(
    r"guard_toggle read: (?P<context>[\w.-]+) proxy-py (?P<checksum>[0-9a-f]{12}) guard (?P<guard>\w+) "
    r"changes (?P<changes>\d+) reads (?P<reads>\d+) lines (?P<lines>\d+) matched (?P<matched>\d+)")


def parse(log_text: str) -> list[dict]:
    """Every guard_toggle object in `log_text`, in order. A line that is not a JSON object, or is another event, is
    passed over: guard-proxy logs its /chat turns between them."""
    found = []
    for line in log_text.splitlines():
        start = line.find("{")
        if start < 0:
            continue
        try:
            obj = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("event") == EVENT:
            found.append(obj)
    return found


def judge(lines: list[dict], changes: list[tuple[str, object, object]], caller: str) -> list[str]:
    """Each way the log does not hold the criterion, empty when it holds: exactly one line per change, in order, none
    for a read; each naming the changed guard, the value it took and the one it had, a peer, and the caller's
    X-WIB-Caller cut as guard-proxy cuts it. `changes` is (guard, value, was) per /toggle that changed something."""
    problems = []
    if not changes:
        problems.append("no /toggle changed a guard, so there is no line to read")
    if len(lines) != len(changes):
        problems.append(f"{len(lines)} guard_toggle line(s) for {len(changes)} change(s): one per change is owed, "
                        f"and none for a read")
    for i, (line, change) in enumerate(zip(lines, changes), 1):
        problems += [f"line {i} {p}" for p in line_problems(line, change, caller)]
    return problems


def line_problems(line: dict, change: tuple[str, object, object], caller: str) -> list[str]:
    """What one guard_toggle line gets wrong about one change, empty when it names it right."""
    guard, value, was = change
    missing = [f for f in FIELDS if f not in line]
    if missing:
        return [f"names no {', '.join(missing)}: {json.dumps(line)[:200]}"]
    problems = []
    if (line["guard"], line["value"], line["was"]) != (guard, value, was):
        problems.append(f"says {line['guard']} {line['was']!r} -> {line['value']!r}, the change was "
                        f"{guard} {was!r} -> {value!r}")
    if not line["peer"]:
        problems.append("has an empty peer")
    if line["caller"] != caller[:CALLER_MAX]:
        problems.append(f"names caller {line['caller']!r}, the X-WIB-Caller sent was {caller[:CALLER_MAX]!r}")
    return problems


def matched(lines: list[dict], changes: list[tuple[str, object, object]], caller: str) -> int:
    """How many lines, read in order against the changes, name their change right."""
    return sum(not line_problems(line, change, caller) for line, change in zip(lines, changes))


def record_line(context: str, checksum: str, guard: str, changes: int, reads: int, lines: int, matched: int) -> str:
    """The `guard_toggle read:` line the live check prints, for decisions.md."""
    return (f"{RECORD_PREFIX} {context} proxy-py {checksum} guard {guard} changes {changes} reads {reads} "
            f"lines {lines} matched {matched}")
