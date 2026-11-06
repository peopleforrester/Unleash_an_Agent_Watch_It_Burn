# ABOUTME: The prompt wall's card-rate check (#933): runs prompts-agenticburn's templates/wall.html on a fake clock under
# ABOUTME: prompt floods and holds that the prompts arriving after the first snapshot add at most one card per 1.5 s.
"""Shared by test_wall_throttle_e2e.py (the pinned copy, tools tier) and test_wall_throttle_upstream_e2e.py (the
wall repo's main, live suite). Not a test itself: the runners pick up only test_*.

The criterion is #927's, for the wall's page: prompts that arrive faster than one per 1.5 s add at most one card per
1.5 s window. "Any 1.5 s window holds at most one card" is the same as "no two cards go up less than 1.5 s apart",
so each scenario reads the time of every card the page draws off the harness's clock and checks the gaps. The cards
the first snapshot draws at once are not part of it: that is what was said before the page opened (#18), and only
what arrives after it is sampled. Every prompt is generated, with its own seq and text, and nothing is random.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
HARNESS = REPO / "verify/wall-clock-harness.js"
WINDOW_MS = 1500  # Michael's decision of 2026-11-05 (#924): about one new card every 1.5 s
FRAME_MS = 250
CLUSTERS = ["attackme", "burritobot-private"]


def _entry(seq: int, label: str) -> dict:
    return {"seq": seq, "cluster": CLUSTERS[seq % 2], "text": f"{label} prompt {seq:05d}", "ts": 0,
            "witch": f"Witch {seq:05d}"}


SNAPSHOT_SEQ = 1
SNAPSHOT = {"boot": "boot-933", "prompts": [_entry(SNAPSHOT_SEQ, "before the page opened")],
            "clusters": [{"name": c, "ok": True, "enabled": True} for c in CLUSTERS]}


def run_harness(wall: pathlib.Path, steps: list[dict]) -> dict:
    """Runs the page with SNAPSHOT as its first /api/prompts answer, then the steps; returns the harness's JSON."""
    if shutil.which("node") is None:
        raise RuntimeError("node is not on PATH; the wall's script runs in verify/wall-clock-harness.js")
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "script.json"
        p.write_text(json.dumps({"snapshot": SNAPSHOT, "steps": steps}), encoding="utf-8")
        out = subprocess.run(["node", str(HARNESS), str(wall), str(p)], capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"the harness exited {out.returncode}: {(out.stderr or out.stdout).strip()[:800]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def _push(entries: list[dict]) -> dict:
    return {"push": {"boot": SNAPSHOT["boot"], "prompts": entries}}


def flood_batched(per_second: int, seconds: int) -> tuple[list[dict], int]:
    """per_second prompts in one SSE frame each second, as the wall's events() sends them (one frame a second)."""
    steps, seq = [], SNAPSHOT_SEQ
    for _ in range(seconds):
        batch = [_entry(seq + i + 1, "batched") for i in range(per_second)]
        seq += per_second
        steps.append(_push(batch))
        steps += [{"advance": FRAME_MS}] * (1000 // FRAME_MS)
    steps += [{"advance": FRAME_MS}] * 12  # 3 s of quiet, so the last held prompt is drawn
    return steps, seq - SNAPSHOT_SEQ


def flood_spaced(gap_ms: int, total_ms: int, label: str) -> tuple[list[dict], int]:
    """One prompt every gap_ms for total_ms, each in its own frame."""
    steps, seq, t = [], SNAPSHOT_SEQ, 0
    while t < total_ms:
        seq += 1
        steps.append(_push([_entry(seq, label)]))
        steps.append({"advance": gap_ms})
        t += gap_ms
    steps += [{"advance": FRAME_MS}] * 12
    return steps, seq - SNAPSHOT_SEQ


def bursts_around_a_card() -> tuple[list[dict], int]:
    """200 prompts in one instant; wait for the card they bring; 200 more 10 ms after it; then 1 more 30 ms on."""
    seq = SNAPSHOT_SEQ
    first = [_entry(seq + i + 1, "first burst") for i in range(200)]
    seq += 200
    second = [_entry(seq + i + 1, "second burst") for i in range(200)]
    seq += 201
    steps = [{"advance": 400}, _push(first), {"until_card": 3 * WINDOW_MS}, {"advance": 10}, _push(second),
             {"advance": 30}, _push([_entry(seq, "straggler")])]
    steps += [{"advance": FRAME_MS}] * 16
    return steps, seq - SNAPSHOT_SEQ


SCENARIOS = {
    "17 prompts a second for 60 s, one SSE frame of 17 a second": lambda: flood_batched(17, 60),
    "17 prompts a second for 60 s, one prompt every 59 ms": lambda: flood_spaced(59, 60_000, "spaced"),
    "one prompt every 1.4 s for 30 s, just faster than one per window": lambda: flood_spaced(1400, 30_000, "near"),
    "a burst of 200, then 200 more 10 ms after its card": bursts_around_a_card,
}
# A page that drew nothing would meet "at most one per window" by doing nothing; each flood must keep drawing.
MIN_CARDS = {
    "17 prompts a second for 60 s, one SSE frame of 17 a second": 30,
    "17 prompts a second for 60 s, one prompt every 59 ms": 30,
    "one prompt every 1.4 s for 30 s, just faster than one per window": 10,
    "a burst of 200, then 200 more 10 ms after its card": 2,
}


def criterion_checks(wall: pathlib.Path) -> list[tuple[str, bool, str]]:
    """Every check of the criterion on one copy of wall.html, as (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []
    for name, build in SCENARIOS.items():
        steps, sent = build()
        got = run_harness(wall, steps)
        snap = [c for c in got["cards"] if c["seq"] <= SNAPSHOT_SEQ]
        live = [c for c in got["cards"] if c["seq"] > SNAPSHOT_SEQ]
        gaps = [b["t"] - a["t"] for a, b in zip(live, live[1:])]
        close = [(a["t"], b["t"]) for a, b in zip(live, live[1:]) if b["t"] - a["t"] < WINDOW_MS]
        results.append((f"{name}: the first snapshot's prompt went up at once, as its only card",
                        [c["t"] for c in snap] == [0], f"snapshot cards: {snap}"))
        results.append((f"{name}: no two cards are less than {WINDOW_MS} ms apart (at most one per window)",
                        not close, f"{len(close)} pairs closer than {WINDOW_MS} ms, first: {close[:3]}; "
                                   f"{len(live)} cards for {sent} prompts"))
        windows: dict[int, int] = {}
        for c in live:
            windows[c["t"] // WINDOW_MS] = windows.get(c["t"] // WINDOW_MS, 0) + 1
        crowded = {k: n for k, n in windows.items() if n > 1}
        results.append((f"{name}: each fixed {WINDOW_MS} ms window from the page's start holds at most one card",
                        not crowded, f"windows with more than one card (index: count): {crowded}"))
        arrived = {e["seq"]: e["text"] for st in steps if "push" in st for e in st["push"]["prompts"]}
        results.append((f"{name}: every card is a prompt that arrived, drawn once",
                        len(arrived) == sent and all(arrived.get(c["seq"]) == c["text"] for c in live)
                        and len({c["seq"] for c in live}) == len(live), f"cards: {live[:5]}"))
        results.append((f"{name}: the flood keeps drawing cards (at least {MIN_CARDS[name]})",
                        len(live) >= MIN_CARDS[name], f"{len(live)} cards, gaps {gaps[:10]}"))
    return results
