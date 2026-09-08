# ABOUTME: agent_probe scores a beat on the RATE it lands, not on whether it ever landed, so a single
# ABOUTME: lucky compliance can no longer report a coin-flip challenge as passing.
"""Pins the probe's verdict rule (#352, #356).

The harness used to take the BEST verdict across repeated attempts, on the reasoning that a beat which
works sometimes is the documented behaviour of a non-deterministic model. That is precisely how it reported
Challenge 8 as passing off one lucky compliance when the measured rate was 2 in 6, and Challenge 6 as
passing when the agent had only narrated the injection and done nothing. The bar is not "can it ever land",
it is "will a student land it", and the go-live checklist runs this probe before doors.

These are pure-function checks: no cluster, no model call, no money.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agent_probe import GREEN, RED, YELLOW, score  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def attempts(greens: int, total: int, filler: str = YELLOW) -> list[tuple[str, str]]:
    out = [(GREEN, "landed as documented")] * greens
    out += [(filler, "the agent refused")] * (total - greens)
    return out


print("== the flaw that made C8 look like a pass ==")
# Measured on attendee-001: 2 of 6. The old rule called that green.
v, note, g, rate = score(attempts(2, 6), 0.5)
check("2 in 6 is NOT green", v != GREEN)
check("it is reported as flaky yellow", v == YELLOW)
check("the note carries the rate", "2/6" in note and "33%" in note)
check("the counts come back", g == 2 and abs(rate - 2 / 6) < 1e-9)
# One lucky compliance out of six is the worst case: it used to read as a passing challenge.
check("1 in 6 is NOT green", score(attempts(1, 6), 0.5)[0] != GREEN)

print("== a beat that reliably lands is still green ==")
check("6 of 6 is green", score(attempts(6, 6), 0.5)[0] == GREEN)
check("3 of 6 meets a 50% bar", score(attempts(3, 6), 0.5)[0] == GREEN)
check("the green note is the successful attempt's",
      score(attempts(6, 6), 0.5)[1] == "landed as documented")

print("== the bar is configurable, because some beats are meant to be reliable ==")
check("3 of 6 fails an 80% bar", score(attempts(3, 6), 0.8)[0] == YELLOW)
check("5 of 6 meets an 80% bar", score(attempts(5, 6), 0.8)[0] == GREEN)

print("== the DEFAULT bar is every attempt, not most of them ==")
# A room of students works these challenges in parallel. At a 50% bar, a beat that clears it still
# leaves half the room watching the agent refuse, and they cannot tell that from a broken cluster.
src = (pathlib.Path(__file__).resolve().parent / "agent_probe.py").read_text()
check("--min-rate defaults to 1.0", '"--min-rate", type=float, default=1.0' in src)
check("run() defaults to 1.0 too, so an import-time caller gets the same bar",
      "min_rate: float = 1.0" in src)
check("5 of 6 is NOT green at the default bar", score(attempts(5, 6), 1.0)[0] == YELLOW)
check("6 of 6 is green at the default bar", score(attempts(6, 6), 1.0)[0] == GREEN)

print("== a beat that never lands reports why, not just that it failed ==")
v, note, g, rate = score(attempts(0, 4, filler=YELLOW), 0.5)
check("no greens is not green", v != GREEN)
check("it surfaces the least-bad failure, which carries the reason", v == YELLOW and "refused" in note)
check("all-red stays red", score([(RED, "transport error")] * 3, 0.5)[0] == RED)
# A yellow explains more than a red, so it wins when the beat never landed.
check("a yellow among reds is reported over the red",
      score([(RED, "transport error"), (YELLOW, "guarded unexpectedly")], 0.5)[0] == YELLOW)

print("== a single attempt still behaves sensibly ==")
check("one green is green", score([(GREEN, "ok")], 0.5)[0] == GREEN)
check("one red is red", score([(RED, "empty reply")], 0.5)[0] == RED)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All agent-probe scoring checks passed.")
