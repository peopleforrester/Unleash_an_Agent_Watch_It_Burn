# ABOUTME: Offline half of #936: verify/wall_clock_burst.py passes a page test written to #927's criterion and fails each
# ABOUTME: way one can stop holding it (a real timer, a real fetch, no burst, a tick with no assert, no count, text or counter).
"""Why (#936). verify/test_wall_clock_burst_sister_e2e.py reads prompts-agenticburn's test_wall_page.py over the network
and holds it to #927's criterion through wall_clock_burst.analyse(). This runs that reading on sources written here, so
the offline suite fails when the analyser stops telling a test that holds the criterion from one that does not.

GOOD is a made-up page test in the shape the criterion asks for: a fake browser in V8 with timers, performance.now(),
fetch and EventSource on one virtual clock, the page from /, a burst of prompts, and an assert on the page after every
tick that between them reads the card count, the shown prompt and "+N more". Each case below changes one thing, and
every edit's anchor is checked to be in GOOD first, so a reworded anchor reads as that and not as a missed failure.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wall_clock_burst  # noqa: E402

GOOD = r'''
import json
import re

from py_mini_racer import MiniRacer

import app as wall

FAKE = r"""
let clock = 0;
const timers = new Map();
function setTimeout(fn, ms){ timers.set(1, {fn, at: clock + ms}); return 1; }
function setInterval(fn, ms){ timers.set(2, {fn, at: clock + ms, every: ms}); return 2; }
var performance = { now(){ return clock; } };
function fetch(url){ return new Promise(() => {}); }
class EventSource { constructor(url){ this.url = url; } }
var browser = {
  advance(ms){ clock += ms; },
  more(){ return '+0 more'; },
};
"""


class Browser:
    def __init__(self, client):
        html = client.get("/").data.decode()
        script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
        self.js = MiniRacer()
        self.js.eval(FAKE)
        self.js.eval(script)


def test_a_burst_shows_the_newest(page):
    wall.ingest("attackme", [f"burst {n}" for n in range(1, 11)])
    page.pump(0)
    assert page.call("browser.more()") == "+10 more"
    page.advance(0.749)
    assert len(page.cards()) == 0
    page.advance(0.001)
    assert page.cards()[0]["text"] == "burst 10"
    assert page.call("browser.more()") == "+0 more"
'''

GOOD_CONFTEST = 'import os\n\nos.environ["WALL_POLLER"] = "off"\n'

BURST_CHECK = "at least one page test feeds a burst and, after each tick, asserts card count, shown prompt and counter"

# (what is broken, the anchor in GOOD, its replacement, the check or checks that must fail and no others, a gap the
# burst check's detail must name)
CASES = [
    ("MiniRacer is not imported", "from py_mini_racer import MiniRacer", "from somewhere import MiniRacer",
     "the page runs in MiniRacer, a bare V8 with no timers or network of its own", ""),
    # With no fake browser in V8, nothing the page's timers or network run on is fake, so every check of the fake fails.
    ("the fake browser is never evaluated", "self.js.eval(FAKE)", "self.js.eval('1')",
     ["a fake browser is evaluated into V8 (a module constant defining setTimeout, passed to .eval())",
      "its setTimeout, setInterval and performance.now() run on one virtual clock",
      "it advances that clock only when the test says so (an advance(ms) that fires due timers)",
      "its fetch is a fake that only queues the request",
      "its EventSource is a fake that only records the stream"], ""),
    ("setTimeout schedules on real time", "timers.set(1, {fn, at: clock + ms})", "timers.set(1, {fn, at: Date.now() + ms})",
     "its setTimeout, setInterval and performance.now() run on one virtual clock", ""),
    ("performance.now() reads the real clock", "now(){ return clock; }", "now(){ return Date.now(); }",
     "its setTimeout, setInterval and performance.now() run on one virtual clock", ""),
    ("setInterval is the real one", "function setInterval(fn, ms){ timers.set(2, {fn, at: clock + ms, every: ms}); return 2; }",
     "", "its setTimeout, setInterval and performance.now() run on one virtual clock", ""),
    ("the clock cannot be advanced", "advance(ms){ clock += ms; },", "",
     "it advances that clock only when the test says so (an advance(ms) that fires due timers)", ""),
    ("fetch is the real one", "function fetch(url){ return new Promise(() => {}); }", "",
     "its fetch is a fake that only queues the request", ""),
    ("EventSource is the real one", "class EventSource { constructor(url){ this.url = url; } }", "",
     "its EventSource is a fake that only records the stream", ""),
    ("the page script comes from another route", 'client.get("/")', 'client.get("/display")',
     "the page's script is the one the wall serves at / (wall.html)", ""),
    ("the test reaches the network", "import json\n", "import json\nimport urllib.request\n",
     "the test module imports no network client", ""),
    ("one prompt, not a burst", '[f"burst {n}" for n in range(1, 11)]', '["only one"]', BURST_CHECK, "feeds no burst"),
    ("a burst of one by range", "range(1, 11)", "range(1, 2)", BURST_CHECK, "feeds no burst"),
    ("one tick only", "    page.advance(0.749)\n    assert len(page.cards()) == 0\n", "", BURST_CHECK,
     "fewer than 2"),
    ("a tick with no assert after it", "    assert len(page.cards()) == 0\n", "    len(page.cards())\n", BURST_CHECK,
     "asserts nothing on the page after the tick"),
    ("no card count", "assert len(page.cards()) == 0", "assert page.cards() == []", BURST_CHECK,
     "never asserts the card count"),
    ("no shown prompt", 'assert page.cards()[0]["text"] == "burst 10"', 'assert page.cards()[0]["seq"] == 10',
     BURST_CHECK, "never asserts which prompt was shown"),
    ("no counter after a tick", '    assert page.call("browser.more()") == "+0 more"\n', "", BURST_CHECK,
     "never asserts the counter"),
]

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


good = wall_clock_burst.analyse(GOOD, GOOD_CONFTEST)
check("a page test written to the criterion passes every check", not good.failed, f"failed: {good.failed}")
check("it is named as the burst test", good.burst_tests == ["test_a_burst_shows_the_newest"], str(good.burst_tests))
names = [name for name, _, _ in good.checks]
expected = [[case[3]] if isinstance(case[3], str) else case[3] for case in CASES]
check("every check below is one analyse() makes", all(n in names for exp in expected for n in exp), str(names))

off = wall_clock_burst.analyse(GOOD, 'import os\n\nos.environ["WALL_POLLER"] = "on"\n')
check("a conftest that leaves the fleet poller on fails only that check",
      off.failed == ["conftest.py turns the wall's fleet poller off before the app is imported"], str(off.failed))

for (what, anchor, replacement, _, gap), expect in zip(CASES, expected):
    if GOOD.count(anchor) != 1:
        check(f"{what}: the anchor {anchor!r} is in GOOD once", False, f"found {GOOD.count(anchor)} times in GOOD")
        continue
    res = wall_clock_burst.analyse(GOOD.replace(anchor, replacement), GOOD_CONFTEST)
    detail = dict((n, d) for n, _, d in res.checks).get(expect[0], "")
    check(f"{what}: fails only '{expect[0]}'" + (f" and the {len(expect) - 1} checks of the fake" if len(expect) > 1 else "")
          + (f", naming '{gap}'" if gap else ""),
          res.failed == expect and gap in detail, f"failed: {res.failed}; detail: {detail}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"\n{len(CASES) + 4}/{len(CASES) + 4} wall clock-burst analyser checks passed")
