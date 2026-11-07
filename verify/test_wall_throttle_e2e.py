# ABOUTME: Runs prompts-agenticburn's templates/wall.html, pinned at its main of #22, in node on a fake clock and holds
# ABOUTME: that prompts arriving faster than one per 1.5 s add at most one card per 1.5 s window (#933, #927's criterion).
# SUITE: e2e (needs node: the page's script runs in verify/wall-clock-harness.js)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Why (#933). #927 asked the prompt wall, prompts-agenticburn's templates/wall.html, to add at most one card per
1.5 s however fast prompts arrive, and this repo's tests only checked the same rule on its own /display page. The
wall's change landed there as prompts-agenticburn#18, commit 6601313a. That repo is private and the gate has no
GitHub login, so the page this test runs is a byte copy of templates/wall.html, since #1108 at main's 8e32eda, the
page as #22 (a07dcad, per-viewer pause and click-to-pin) left it,
verify/fixtures/prompts-agenticburn/wall.html.fixture (not .html, so the prose gate does not read another repo's
page as this repo's prose), held here to its SHA-256. test_wall_throttle_upstream_e2e.py, in the live suite, reads
the wall repo's main and runs the same checks on it, and fails when main has moved past this copy.

The checks themselves are verify/wall_throttle.py's: four floods (17 a second in one-second SSE frames and spaced
59 ms apart, one every 1.4 s, and two bursts of 200 either side of a card), each read off the harness's clock. Three
mutations of the copy (draw every arrival, drop the 1.5 s floor from the card's timer, a 1 s interval) must each
fail them, so the checks are seen to bite. A missing node is a failure, not a skip.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wall_throttle  # noqa: E402

REPO = wall_throttle.REPO
WALL = REPO / "verify/fixtures/prompts-agenticburn/wall.html.fixture"
WALL_REPO = "peopleforrester/prompts-agenticburn"
WALL_PATH = "templates/wall.html"
# main on 2026-11-07 (#1108); the page last changed at a07dcad, "Add per-viewer pause ... and click-to-pin" (#22)
WALL_COMMIT = "8e32eda46d0744d8f94a987fc52b46aa92aae534"
WALL_SHA256 = "7eab1e2b2bfb225b31aa758d50f11dd043d8b3e8ae98e6edebff59cc2ca60366"

# Each mutation is (what it breaks, the literal it replaces in the copy, what it puts there).
MUTATIONS = [
    ("draw every arrival", "else if (!filter || e.cluster === filter) throttle.offer(e);",
     "else if (!filter || e.cluster === filter) addCard(e);"),
    ("drop the 1.5 s floor from the card's timer",
     "schedule(() => tick(armedAs), Math.max(intervalMs / 2, last + intervalMs - now()));",
     "schedule(() => tick(armedAs), intervalMs / 2);"),
    ("a 1 s interval", "const CARD_INTERVAL_MS = 1500;", "const CARD_INTERVAL_MS = 1000;"),
]

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


def main() -> int:
    for f in (wall_throttle.HARNESS, WALL):
        if not f.is_file():
            print(f"FAIL: {f.relative_to(REPO)} is missing")
            return 1
    raw = WALL.read_bytes()
    print(f"== the copy is {WALL_REPO}'s {WALL_PATH} at {WALL_COMMIT[:8]} ==")
    got = hashlib.sha256(raw).hexdigest()
    check("the copy's SHA-256 is the pinned one", got == WALL_SHA256,
          f"sha256 {got}; refresh the copy from {WALL_COMMIT} or move WALL_COMMIT and WALL_SHA256 together")
    src = raw.decode("utf-8")
    m = re.search(r"const CARD_INTERVAL_MS = (\d+);", src)
    check(f"the page's CARD_INTERVAL_MS is {wall_throttle.WINDOW_MS}", bool(m) and int(m.group(1)) == wall_throttle.WINDOW_MS,
          f"read {m.group(0) if m else 'no `const CARD_INTERVAL_MS = <ms>;`'}")

    print("== prompts faster than one per 1.5 s add at most one card per 1.5 s window ==")
    try:
        for name, ok, detail in wall_throttle.criterion_checks(WALL):
            check(name, ok, detail)
    except RuntimeError as e:
        print(f"FAIL: {e}")
        return 1

    print("== each mutation of the copy fails those checks ==")
    for what, literal, replacement in MUTATIONS:
        if src.count(literal) != 1:
            print(f"FAIL: the mutation '{what}' replaces `{literal}`, which {WALL.relative_to(REPO)} holds "
                  f"{src.count(literal)} times, not once")
            return 1
        with tempfile.TemporaryDirectory() as tmp:
            mutant = pathlib.Path(tmp) / "wall.html"
            mutant.write_text(src.replace(literal, replacement), encoding="utf-8")
            try:
                failed = [n for n, ok, _ in wall_throttle.criterion_checks(mutant) if not ok]
            except RuntimeError as e:
                print(f"FAIL: the mutation '{what}' did not run: {e}")
                return 1
        check(f"'{what}' fails the criterion", bool(failed), "every check passed on the mutant")
        if failed:
            print(f"        it fails {len(failed)} checks, the first: {failed[0]}")

    if failures:
        print(f"\nFAIL: {len(failures)} check(s) failed")
        return 1
    print("\nPASS: the wall adds at most one card per 1.5 s window under every flood")
    return 0


if __name__ == "__main__":
    sys.exit(main())
