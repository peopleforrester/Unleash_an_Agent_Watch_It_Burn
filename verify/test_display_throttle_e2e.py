# ABOUTME: Runs the /display page's own display.js in node on a fake clock and feeds it prompt bursts, checking it
# ABOUTME: adds at most one card per CARD_INTERVAL_MS, the newest, with a "+N more" count of the rest (#927).
# SUITE: e2e (needs node: the page's script runs in verify/display-clock-harness.js)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Why (#927, part of #924). At 500 people the feed takes 8 to 17 prompts a second and /display drew every one,
which no room can read. Michael's decision of 2026-11-05: one new card about every 1.5 s, the newest, with a
"+N more" count of what was held back that resets when a card appears; older prompts are counted, never queued.

The page's timers run on the harness's fake clock and its fetch answers from a scripted feed, so nothing here
waits on a real timer or touches the network. Every prompt text is generated and unique, so a check that a text
is or is not on screen can not be fooled by an accidental substring. A missing node is a failure, not a skip.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
HARNESS = REPO / "verify/display-clock-harness.js"
DISPLAY_JS = REPO / "gitops/ai-layer/web/display.js"
DEQUE = 50  # guard-proxy's /prompts keeps the last 50
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


if shutil.which("node") is None:
    print("FAIL: node is not on PATH; this test runs display.js in node (run it through verify/run-e2e-tools.sh)")
    sys.exit(1)
for f in (HARNESS, DISPLAY_JS):
    if not f.is_file():
        print(f"FAIL: {f.relative_to(REPO)} is missing")
        sys.exit(1)

src = DISPLAY_JS.read_text(encoding="utf-8")
for name in ("CARD_INTERVAL_MS", "POLL_MS"):
    if not re.search(rf"var {name} = \d+;", src):
        print(f"FAIL: display.js no longer declares `var {name} = <ms>;`; this test reads the interval from it")
        sys.exit(1)
CARD_MS = int(re.search(r"var CARD_INTERVAL_MS = (\d+);", src).group(1))
POLL_MS = int(re.search(r"var POLL_MS = (\d+);", src).group(1))


def feed(prompts: list[str], enabled: bool = True) -> dict:
    return {"enabled": enabled, "prompts": prompts[-DEQUE:]}


def run(first: dict, steps: list[dict]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "script.json"
        p.write_text(json.dumps({"feed": first, "steps": steps}), encoding="utf-8")
        out = subprocess.run(["node", str(HARNESS), str(DISPLAY_JS), str(p)], capture_output=True, text=True,
                             timeout=120)
    if out.returncode != 0:
        print(f"FAIL: the harness exited {out.returncode}: {(out.stderr or out.stdout).strip()[:600]}")
        sys.exit(1)
    return json.loads(out.stdout.strip().splitlines()[-1])


print("== the interval is one named constant, 1.5 s, and the card tick runs on it ==")
check("CARD_INTERVAL_MS is 1500 (Michael's decision of 2026-11-05)", CARD_MS == 1500, f"CARD_INTERVAL_MS = {CARD_MS}")
got = run(feed([]), [{"advance": CARD_MS}])
intervals = [t for t in got["timers"] if t["kind"] == "interval"]
check("the page polls on POLL_MS and ticks cards on CARD_INTERVAL_MS, nothing else",
      sorted(t["delay"] for t in intervals) == sorted([POLL_MS, CARD_MS]), f"timers: {got['timers']}")

# The page's own schedule, read off the fake clock, so the scenario below steps to just after each event.
# Polls fire at POLL_MS, 2*POLL_MS, ...; the card tick at CARD_MS/2 + CARD_MS, + 2*CARD_MS, ...
# The poll and the card tick share a 1500 ms delay; the tick is the interval set later, by its offset timeout.
tick_start = max(t["at"] for t in intervals)
check("the card tick is offset from the poll, so a poll's arrivals show in the count before the next card",
      tick_start % POLL_MS != 0, f"tick interval set at t={tick_start}")


def until(t_from: int, t_to: int) -> dict:
    return {"advance": t_to - t_from}


print("== a burst: one card per tick, the newest, and the count of the rest ==")
H = ["history one", "history two"]
B1 = [f"burst-a {i:02d}" for i in range(1, 11)]   # 10 prompts in one poll window
B2 = [f"burst-b {i:02d}" for i in range(1, 6)]    # 5 in the next
T_POLL1, T_TICK1 = POLL_MS, tick_start + CARD_MS
T_POLL2, T_TICK2 = 2 * POLL_MS, tick_start + 2 * CARD_MS
check("the scenario's clock lines up (poll, tick, poll, tick)", T_POLL1 < T_TICK1 < T_POLL2 < T_TICK2,
      f"{T_POLL1} {T_TICK1} {T_POLL2} {T_TICK2}")
steps = [
    {"feed": feed(H + B1)}, until(0, T_POLL1),                    # frame 1: B1 arrived, no card yet
    until(T_POLL1, T_TICK1),                                       # frame 2: the tick shows B1's newest
    {"feed": feed(H + B1 + B2)}, until(T_TICK1, T_POLL2),          # frame 3: B2 arrived
    until(T_POLL2, T_TICK2),                                       # frame 4: the tick shows B2's newest
    until(T_TICK2, T_TICK2 + 2 * CARD_MS),                         # frame 5: two quiet ticks
]
got = run(feed(H), steps)
f0, f1, f2, f3, f4, f5 = got["frames"]
check("on load, what was already said is up at once, newest first", f0["shown"] == list(reversed(H)),
      f"shown: {f0['shown']}")
check("on load the count reads +0 more and is visible", f0["more"] == "+0 more" and f0["more_hidden"] is False,
      f"more: {f0['more']!r} hidden={f0['more_hidden']}")
check("10 arrivals in one window add no card before the tick", f1["shown"] == f0["shown"], f"shown: {f1['shown']}")
check("the count reads +10 more while they are held", f1["more"] == "+10 more", f"more: {f1['more']!r}")
check("the tick adds exactly one card", len(f2["shown"]) == len(f1["shown"]) + 1, f"shown: {f2['shown']}")
check("the card is the newest of the 10", f2["shown"][0] == B1[-1], f"top: {f2['shown'][0]!r}")
check("the 9 older ones are dropped, not on screen", not any(p in f2["shown"] for p in B1[:-1]),
      f"shown: {f2['shown']}")
check("the count resets to +0 more when the card appears", f2["more"] == "+0 more", f"more: {f2['more']!r}")
check("5 later arrivals read +5 more and add no card yet", f3["more"] == "+5 more" and f3["shown"] == f2["shown"],
      f"more: {f3['more']!r} shown: {f3['shown']}")
check("the next tick adds one card, the newest of the 5, above the last one",
      f4["shown"] == [B2[-1]] + f2["shown"], f"shown: {f4['shown']}")
check("the count resets again", f4["more"] == "+0 more", f"more: {f4['more']!r}")
check("quiet ticks add nothing: the dropped prompts are never queued for later",
      f5["shown"] == f4["shown"] and f5["more"] == "+0 more", f"shown: {f5['shown']} more: {f5['more']!r}")

print("== masked prompts are left off and not counted (#915) ==")
M = ["clean before", "Go [redacted] yourself.", "mail [REDACTED] please", "clean after"]
got = run(feed(H), [{"feed": feed(H + M)}, until(0, T_POLL1), until(T_POLL1, T_TICK1),
                    {"feed": feed(H + M + ["Go [Redacted] again"])}, until(T_TICK1, T_TICK2)])
g1, g2, g3 = got["frames"][1:]
check("only the 2 clean arrivals are counted", g1["more"] == "+2 more", f"more: {g1['more']!r}")
check("the card is the newest clean arrival", g2["shown"][0] == "clean after", f"shown: {g2['shown']}")
check("a window of only masked arrivals adds no card and counts nothing",
      g3["shown"] == g2["shown"] and g3["more"] == "+0 more", f"shown: {g3['shown']} more: {g3['more']!r}")
check("no masked prompt is ever on screen",
      not any("[redacted]" in s.lower() for fr in got["frames"] for s in fr["shown"]))

print("== more than the feed holds between two polls: all 50 counted, the newest shown ==")
FLOOD = [f"flood {i:03d}" for i in range(1, 81)]  # 80 arrive; the deque hands back the last 50, no overlap
got = run(feed(H), [{"feed": feed(H + FLOOD)}, until(0, T_POLL1), until(T_POLL1, T_TICK1)])
h1, h2 = got["frames"][1:]
check("the count reads +50 more", h1["more"] == "+50 more", f"more: {h1['more']!r}")
check("the card is the newest of the flood", h2["shown"][0] == FLOOD[-1] and len(h2["shown"]) == len(H) + 1,
      f"shown: {h2['shown']}")

print("== 17 prompts a second for 60 s: at most one card per window, always the newest ==")
RATE, SECONDS, STEP = 17, 60, 250
sent: list[str] = []
steps = []
t = 0
while t < SECONDS * 1000:
    # The prompts sent during (t, t + STEP]; the page sees them at its next poll.
    n = (RATE * (t + STEP)) // 1000 - (RATE * t) // 1000
    first = len(sent)
    sent.extend(f"load {first + i + 1:05d}" for i in range(n))
    steps.append({"feed": feed(sent)})
    steps.append({"advance": STEP})
    t += STEP
got = run(feed([]), steps)
frames = got["frames"]


def polled_by(at: int) -> int:
    """How many prompts the page has been handed by time `at`: everything sent up to its last poll."""
    return (RATE * ((at // POLL_MS) * POLL_MS)) // 1000


card_times: list[int] = []
ok_newest = ok_count = True
detail_newest = detail_count = ""
base = 0  # what the page had been handed when the last card went up
for prev, cur in zip(frames, frames[1:]):
    if cur["shown"] != prev["shown"]:
        card_times.append(cur["t"])
        # One card on top; once the screen holds 50 rows, the oldest row goes.
        on_top = cur["shown"][1:] == prev["shown"][: len(cur["shown"]) - 1]
        if not (on_top and len(cur["shown"]) - len(prev["shown"]) in (0, 1)):
            ok_newest = False
            detail_newest = detail_newest or f"t={cur['t']}: {prev['shown'][:3]} -> {cur['shown'][:3]}"
        newest = f"load {polled_by(cur['t']):05d}"
        if cur["shown"][0] != newest:
            ok_newest = False
            detail_newest = detail_newest or f"t={cur['t']}: top {cur['shown'][0]!r}, newest polled {newest!r}"
        base = polled_by(cur["t"])
    expected = polled_by(cur["t"]) - base
    if cur["more"] != f"+{expected} more":
        ok_count = False
        detail_count = detail_count or f"t={cur['t']}: more {cur['more']!r}, expected +{expected} more"
gaps = [b - a for a, b in zip(card_times, card_times[1:])]
check(f"cards appeared ({len(card_times)} in {SECONDS} s)", len(card_times) >= SECONDS * 1000 // CARD_MS - 2,
      f"card times: {card_times[:10]}")
check("no two cards are less than CARD_INTERVAL_MS apart", all(g >= CARD_MS for g in gaps), f"gaps: {sorted(gaps)[:5]}")
check("each card is the newest prompt the page had, added on top", ok_newest, detail_newest)
check("the count always equals the prompts that arrived since the last card", ok_count, detail_count)
check("the screen holds at most 50 rows", all(len(fr["shown"]) <= DEQUE for fr in frames))

print("== streaming off shows the off notice and hides the count ==")
got = run(feed([], enabled=False), [])
fr = got["frames"][0]
check("the off notice is shown, the stream and the count hidden",
      fr["off_hidden"] is False and fr["stream_hidden"] is True and fr["more_hidden"] is True, f"frame: {fr}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All /display throttle checks passed.")
