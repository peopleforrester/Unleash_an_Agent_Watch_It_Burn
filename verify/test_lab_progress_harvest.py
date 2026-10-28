# ABOUTME: The post-event lab-progress pass (scripts/harvest/06-lab-progress.py) turns witb.lab.calls series into
# ABOUTME: the right per-attendee timeline, funnel, unused and abandoned counts, and a CSV keyed for the feedback join.
"""Runs the pass's reducer on a synthetic room, offline. The Datadog fetch is the only part not exercised here.

The room: one attendee who opened C1, needed the prompt, and fixed it 7 minutes later, then opened C2 and fixed
nothing; one who opened the lab and left within a few minutes; one whose cluster ran all session and whose lab
was never opened; and the instructors' and presenters' clusters, which are not attendees whatever their lab
page reports as its role.
"""
from __future__ import annotations

import csv
import importlib.util
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("lab_progress", REPO / "scripts/harvest/06-lab-progress.py")
lp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lp)

failures: list[str] = []


def check(n: str, c: bool) -> None:
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


T0 = 1_788_000_000  # a minute boundary, seconds


def s(cluster: str, alias: str, span: str, minutes: dict[int, float], challenge: str = "", kind: str = "") -> dict:
    tags = [f"kube_cluster_name:{cluster}", f"witb.lab.alias:{alias}", f"span.name:{span}"]
    if challenge:
        tags.append(f"witb.lab.challenge:{challenge}")
    if kind:
        tags.append(f"witb.lab.kind:{kind}")
    return {"tag_set": tags, "pointlist": [[(T0 + m * 60) * 1000, v] for m, v in sorted(minutes.items())]}


A, B = "watch-it-burn-attendee-001", "watch-it-burn-attendee-002"
lab = [
    s(A, "bane-agatha", "lab.session.start", {0: 1}),
    s(A, "bane-agatha", "lab.heartbeat", {m: 1 for m in range(0, 30)}),
    s(A, "bane-agatha", "lab.step.open", {2: 1, 20: 1}, "1"),
    s(A, "bane-agatha", "lab.hint.open", {5: 1}, "1", "hint"),
    s(A, "bane-agatha", "lab.hint.open", {6: 1}, "1", "solution"),
    s(A, "bane-agatha", "lab.control.installed", {9: 1}, "1"),
    s(A, "bane-agatha", "lab.step.open", {12: 2}, "2"),
    s(A, "bane-agatha", "lab.hint.open", {14: 3}, "2", "hint"),
    s(A, "bane-agatha", "lab.step.open", {1: 1}, "0"),   # the tour is not a challenge
    s(B, "hexhen-zelda", "lab.session.start", {3: 1}),
    s(B, "hexhen-zelda", "lab.heartbeat", {3: 1, 4: 1, 5: 1}),
    s(B, "hexhen-zelda", "lab.step.open", {4: 1}, "1"),
    {"tag_set": [f"kube_cluster_name:{B}", "span.name:lab.heartbeat"], "pointlist": [[T0 * 1000, None]]},
]
running = lambda n: {"tag_set": [f"kube_cluster_name:{n}"], "pointlist": [[T0 * 1000, 1]]}
agents = [running(A), running(B), running("watch-it-burn-attendee-003"), running("watch-it-burn-private"),
          running("watch-it-burn-community"), running("watch-it-burn-michael-student")]
# An admin cluster's lab opened without ?role= reports role=student; it is still not an attendee.
lab.append(s("watch-it-burn-private", "michael-admin", "lab.session.start", {0: 1}))

summary = lp.summarize(lab, agents)
by = {r["cluster"]: r for r in summary["clusters"]}
a, b = by[A], by[B]

print("== the per-attendee timeline ==")
check("only the attendee clusters that opened the lab are present, keyed by cluster with the friendly alias",
      set(by) == {A, B} and a["alias"] == "bane-agatha" and b["alias"] == "hexhen-zelda")
check("active minutes are minutes with a heartbeat", a["active_minutes"] == 30 and b["active_minutes"] == 3)
check("C1: first open at minute 2, fixed at minute 9, so 7 minutes to fix",
      a["challenges"]["1"]["opened_at"] == T0 + 120 and a["challenges"]["1"]["minutes_to_fix"] == 7)
check("C1: one hint and one prompt reveal, counted apart",
      a["challenges"]["1"]["hints"] == 1 and a["challenges"]["1"]["solutions"] == 1)
check("C2: opened twice, three hints, not fixed",
      a["challenges"]["2"]["opens"] == 2 and a["challenges"]["2"]["hints"] == 3 and a["challenges"]["2"]["fixed_at"] is None)
check("the tour (0) is not counted as a challenge", "0" not in a["challenges"])
check("furthest fix and totals", a["furthest_fixed"] == 1 and a["fixed"] == ["1"] and a["hints_total"] == 4 and a["solutions_total"] == 1)
check("a cluster that stayed and fixed something is not abandoned", a["abandoned_early"] is False)
check("a cluster that left within 10 minutes with no fix is abandoned", b["abandoned_early"] is True)
check("an empty point does not count as seen", b["first_seen"] == T0 + 180)

print("== the room ==")
check("unused = an attendee cluster running with no lab session; admin, Community and presenter clusters are not",
      summary["unused"] == ["watch-it-burn-attendee-003"])
check("running counts attendee clusters only", summary["running"] == [A, B, "watch-it-burn-attendee-003"])
f = {x["challenge"]: x for x in summary["funnel"]}
check("C1 funnel: 2 opened, 1 hint, 1 prompt, 1 fixed, median 7 minutes",
      (f["1"]["opened"], f["1"]["hint"], f["1"]["solution"], f["1"]["fixed"], f["1"]["median_minutes_to_fix"]) == (2, 1, 1, 1, 7))
check("C2 funnel: 1 opened, 1 hint, none fixed", (f["2"]["opened"], f["2"]["hint"], f["2"]["fixed"]) == (1, 1, 0))
check("all eight challenges are in the funnel, even untouched ones", list(f) == [str(n) for n in range(1, 9)])

print("== the outputs ==")
with tempfile.TemporaryDirectory() as tmp:
    path = pathlib.Path(tmp) / "lab-progress.csv"
    lp.write_csv(summary, path)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
check("the CSV's first column is alias, the feedback app's cluster value", list(rows[0])[0] == "alias")
check("one row per cluster that opened the lab", [r["alias"] for r in rows] == ["bane-agatha", "hexhen-zelda"])
check("fixed challenges are listed", rows[0]["fixed"] == "1" and rows[1]["abandoned_early"] == "yes")
md = lp.report(summary)
check("the report is aggregate: no cluster or alias named in it", not any(n in md for n in (A, B, "bane-agatha", "hexhen-zelda")))
check("the report says anonymous feedback is never joined", "anonymous" in md)
check("the report has the funnel row for C1", "| C1 | 2 | 1 | 1 | 1 | 7 |" in md)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All lab-progress harvest checks passed.")
