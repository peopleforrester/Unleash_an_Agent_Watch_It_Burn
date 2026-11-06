# ABOUTME: Downloads the prompt wall the room sees (prompts.agenticburn.com) and runs its own script on a fake clock,
# ABOUTME: checking its "+N more" count equals the prompts that arrived since the last card, and resets on each (#935).
# SUITE: e2e (needs the live wall over the network, and node: the page's script runs in verify/wall-more-harness.js)
"""Why (#935, a test for #927's third criterion). #927, part of #924, put a throttle on the fleet prompt wall: at 500
people it gets 8 to 17 prompts a second, so it draws one card about every 1.5 s, the newest, and a visible "+N more"
count shows how many prompts arrived and were not shown since the last card, resetting to 0 when a card appears.
The wall is prompts-agenticburn's templates/wall.html (prompts-agenticburn#18), deployed to Railway with `railway up`
and served at prompts.agenticburn.com. test_wall_more_count_e2e.py, in the gate's tools tier, runs the checks on the
pinned copy of that file; this is the live half, on the wall the room actually reads, so a deploy that lacks the count,
or ships it hidden or wrong, fails here. The checks are verify/wall_more_count.py's. Only the one GET of the page
reaches the wall; no prompt is sent.

Usage: python3 verify/test_wall_more_count_live.py [--page <wall.html>]
WALL_URL (default https://prompts.agenticburn.com/) names the wall. --page reads a local copy instead (a template from a
prompts-agenticburn checkout is rendered first), which checks a change before it is deployed. An unreachable wall or a
missing node is a failure, not a skip.
"""
from __future__ import annotations

import os
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wall_more_count  # noqa: E402

WALL_URL = os.environ.get("WALL_URL", "https://prompts.agenticburn.com/")
USAGE = "usage: test_wall_more_count_live.py [--page <wall.html>]"


def load_page(argv: list[str]) -> tuple[str, str]:
    if argv[:1] == ["--page"]:
        if len(argv) != 2:
            raise RuntimeError(USAGE)
        p = pathlib.Path(argv[1])
        if not p.is_file():
            raise RuntimeError(f"--page {p} is not a file")
        return p.read_text(encoding="utf-8"), str(p)
    if argv:
        raise RuntimeError(f"unknown arguments {argv}; {USAGE}")
    req = urllib.request.Request(WALL_URL, headers={"User-Agent": "watch-it-burn-verify (#935)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                raise RuntimeError(f"GET {WALL_URL} answered {r.status}, not 200")
            return r.read().decode("utf-8"), WALL_URL
    except OSError as e:
        raise RuntimeError(f"GET {WALL_URL} failed: {e}") from e


def main() -> int:
    try:
        page, where = load_page(sys.argv[1:])
        print(f"== the wall page, from {where} ==")
        results = wall_more_count.criterion_checks(page)
    except RuntimeError as e:
        print(f"FAIL: {e}")
        return 1
    failures = []
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failures.append(name)
            if detail:
                print(f"        {detail}")
    if failures:
        print(f"\nFAIL: {len(failures)} check(s) failed on {where}: {failures}")
        return 1
    print(f"\nPASS: the +N more count on {where} holds in every frame (#935)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
