# ABOUTME: Runs prompts-agenticburn's templates/wall.html, pinned at its main of #22, in node on a fake clock and holds that
# ABOUTME: its "+N more" count equals the prompts that arrived since the last card and resets to 0 on each (#935).
# SUITE: e2e (needs node: the page's script runs in verify/wall-more-harness.js)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Why (#935). Test review run 17682 found that nothing checked #927's third criterion on the wall itself: a visible
"+N more" counter equals the number of prompts that arrived and were not shown since the last card, and resets to 0
when a card appears. Only /display's display.js was checked (test_display_throttle_e2e.py). The wall is
prompts-agenticburn's templates/wall.html, private, so this runs #933's byte copy of it (8e32eda since #1108),
verify/fixtures/prompts-agenticburn/wall.html.fixture, held to the SHA-256 test_wall_throttle_e2e.py pins. When that
copy is refreshed the pin moves there and this runs on the new page. test_wall_more_count_live.py runs the same checks
on the wall the room reads.

The checks are verify/wall_more_count.py's. Eight mutations of the copy, each a way the count could stop holding, must
each fail them, so the checks are seen to bite. A missing node is a failure, not a skip.
"""
from __future__ import annotations

import hashlib
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_wall_throttle_e2e as pinned  # noqa: E402
import wall_more_count  # noqa: E402

REPO = wall_more_count.REPO

# Each mutation is (what it breaks, the literal it replaces in the copy, what it puts there).
MUTATIONS = [
    ("the card does not reset the count", "    show(e);\n    setCount(0);", "    show(e);"),
    ("the count leaves out the prompt about to be drawn", "      setCount(count);", "      setCount(count - 1);"),
    ("the card does not zero the running count", "held = null; count = 0; last = now();", "held = null; last = now();"),
    ("the count ships hidden", '<div class="more zero" id="more" aria-live="off">',
     '<div class="more zero" id="more" aria-live="off" hidden>'),
    ("the CSS hides the count at 0", ".more.zero{opacity:.55}", ".more.zero{display:none}"),
    ("the script hides the count at 0", "  moreEl.classList.toggle('zero', n === 0);",
     "  moreEl.classList.toggle('zero', n === 0);\n  moreEl.hidden = n === 0;"),
    ("a replayed prompt is counted again", "    if (shown.has(e.seq)) continue;\n", ""),
    ("an arrival does not update the count", "      setCount(count);\n", ""),
]

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


def main() -> int:
    for f in (wall_more_count.HARNESS, pinned.WALL):
        if not f.is_file():
            print(f"FAIL: {f.relative_to(REPO)} is missing")
            return 1
    raw = pinned.WALL.read_bytes()
    print(f"== the copy is {pinned.WALL_REPO}'s {pinned.WALL_PATH} at {pinned.WALL_COMMIT[:8]} ==")
    got = hashlib.sha256(raw).hexdigest()
    check("the copy's SHA-256 is the one test_wall_throttle_e2e.py pins", got == pinned.WALL_SHA256, f"sha256 {got}")
    src = raw.decode("utf-8")

    print('== the "+N more" count equals the prompts not shown since the last card, and resets on each ==')
    try:
        for name, ok, detail in wall_more_count.criterion_checks(src):
            check(name, ok, detail)
    except RuntimeError as e:
        print(f"FAIL: {e}")
        return 1

    print("== each mutation of the copy fails those checks ==")
    for what, literal, replacement in MUTATIONS:
        if src.count(literal) != 1:
            print(f"FAIL: the mutation '{what}' replaces `{literal}`, which {pinned.WALL.relative_to(REPO)} holds "
                  f"{src.count(literal)} times, not once")
            return 1
        try:
            failed = [n for n, ok, _ in wall_more_count.criterion_checks(src.replace(literal, replacement)) if not ok]
        except RuntimeError as e:
            print(f"FAIL: the mutation '{what}' did not run: {e}")
            return 1
        check(f"'{what}' fails the criterion", bool(failed), "every check passed on the mutant")
        if failed:
            print(f"        it fails {len(failed)} checks, the first: {failed[0]}")

    if failures:
        print(f"\nFAIL: {len(failures)} check(s) failed")
        return 1
    print('\nPASS: the wall\'s "+N more" count holds in every frame, and every mutation of it fails')
    return 0


if __name__ == "__main__":
    sys.exit(main())
