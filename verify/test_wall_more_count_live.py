# ABOUTME: Downloads the prompt wall the room sees (prompts.agenticburn.com) and runs its own script on a fake clock,
# ABOUTME: checking its "+N more" count equals the prompts that arrived since the last card, and resets on each (#935).
# SUITE: e2e (needs the live wall over the network, and node: the page's script runs in verify/wall-clock-harness.js)
"""Why (#935, a test for #927's third criterion). #927, part of #924, put a throttle on the fleet prompt wall: at 500
people it gets 8 to 17 prompts a second, so it draws one card about every 1.5 s, the newest, and a visible "+N more"
count shows how many prompts arrived and were not shown since the last card, resetting to 0 when a card appears.
The wall is prompts-agenticburn's templates/wall.html (prompts-agenticburn#18), served at prompts.agenticburn.com;
its tests there run the template, and test_display_throttle_e2e.py here runs only /display's display.js. Nothing
checked the wall the room actually reads, so a deploy that lacked the count, or shipped it hidden or wrong, passed.

This downloads the served page and runs its own inline script in node (verify/wall-clock-harness.js) on a fake clock
with a fake /api/prompts and /events, so nothing waits on a real timer and no prompt is sent to the live wall. It
feeds a burst of 10, a steady flood of one prompt every 100 ms for 6 s, a dropped stream with 7 prompts picked up by
the polling fallback, and a replay of prompts the page already holds, and after every step reads the #more line.
The count it expects is worked out from the harness's ordered log of what reached the page and which cards went up:
every prompt with a seq the page had not seen, since the last card. A replayed prompt is not a new arrival.

Usage: python3 verify/test_wall_more_count_live.py [--page <rendered wall.html>]
WALL_URL (default https://prompts.agenticburn.com/) names the wall. --page reads a local copy instead; a template
straight from a prompts-agenticburn checkout is rendered first ({{ pinned | tojson }} and {{ interval }}), which
checks a change before it is deployed. An unreachable wall or a missing node is a failure, not a skip.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
HARNESS = REPO / "verify/wall-clock-harness.js"
WALL_URL = os.environ.get("WALL_URL", "https://prompts.agenticburn.com/")
MORE = re.compile(r"^\+(\d+) more$")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


def fail_now(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def render_template(src: str) -> str:
    """app.py's wall_page() renders wall.html with pinned and interval; the page's script needs both filled in."""
    src = re.sub(r"\{\{\s*pinned\s*\|\s*tojson\s*\}\}", '"attackme"', src)
    src = re.sub(r"\{\{\s*interval\s*\}\}", "3", src)
    left = re.findall(r"\{\{.*?\}\}|\{%.*?%\}", src)
    if left:
        fail_now(f"--page has template expressions this test does not render: {left[:3]}")
    return src


def load_page(argv: list[str]) -> tuple[str, str]:
    if argv[:1] == ["--page"]:
        if len(argv) != 2:
            fail_now("usage: test_wall_more_count_live.py [--page <wall.html>]")
        p = pathlib.Path(argv[1])
        if not p.is_file():
            fail_now(f"--page {p} is not a file")
        return render_template(p.read_text(encoding="utf-8")), str(p)
    if argv:
        fail_now(f"unknown arguments {argv}; usage: test_wall_more_count_live.py [--page <wall.html>]")
    req = urllib.request.Request(WALL_URL, headers={"User-Agent": "watch-it-burn-verify (#935)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                fail_now(f"GET {WALL_URL} answered {r.status}, not 200")
            return r.read().decode("utf-8"), WALL_URL
    except OSError as e:
        fail_now(f"GET {WALL_URL} failed: {e}")
    raise AssertionError("unreachable")


if shutil.which("node") is None:
    fail_now("node is not on PATH; this test runs the wall's script in node (verify/wall-clock-harness.js)")
if not HARNESS.is_file():
    fail_now(f"{HARNESS.relative_to(REPO)} is missing")

page, where = load_page(sys.argv[1:])
print(f"== the wall page, from {where} ==")

# --- the count is on the page, in the header, and nothing in the markup or the CSS hides it ---------------------
markup = re.sub(r"<script[\s\S]*?</script>", "", page)
tag = re.search(r"<[a-zA-Z][\w-]*\b[^>]*\bid=\"more\"[^>]*>", markup)
check('the page has a "+N more" element, id="more"', tag is not None,
      "no element with id=\"more\" in the served markup: the wall has no +N more count (prompts-agenticburn#18 not deployed?)")
if tag is None:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
header = re.search(r"<header\b[\s\S]*?</header>", markup)
check("it sits in the wall's header, which is always on screen", bool(header) and tag.group(0) in header.group(0))
check("it does not ship with the hidden attribute", not re.search(r"\shidden(\s|=|>|/)", tag.group(0)), tag.group(0))
check("it carries no inline style that hides it",
      not re.search(r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(\.0*)?\s*[;\"']", tag.group(0)),
      tag.group(0))
classes = (re.search(r"\bclass=\"([^\"]*)\"", tag.group(0)) or [None, ""])[1].split()
style = "\n".join(re.findall(r"<style[^>]*>([\s\S]*?)</style>", page))
style = re.sub(r"/\*[\s\S]*?\*/", "", style)
hiders = []
for sel, decl in re.findall(r"([^{}]+)\{([^{}]*)\}", style):
    names = {s.strip() for s in sel.split(",")}
    hits = [s for s in names if re.fullmatch(r"(?:#more|\.(?:%s))(?:[.#:][\w:-]+)*" % "|".join(map(re.escape, classes or ["-"])), s)
            or s.startswith("#more")]
    if hits and re.search(r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(\.0*)?\s*(;|$)", decl):
        hiders.append(f"{sel.strip()}{{{decl.strip()}}}")
check("no CSS rule for its classes or id hides it (display:none, visibility:hidden, opacity:0)", not hiders,
      "; ".join(hiders))

# --- the scenario --------------------------------------------------------------------------------------------------
n = 0


def prompts(k: int, label: str, cluster: str = "attackme") -> list[dict]:
    global n
    out = []
    for _ in range(k):
        n += 1
        out.append({"cluster": cluster, "text": f"wall-935 {label} {n:04d}", "witch": f"Witch {n:04d}"})
    return out


history = prompts(2, "history")
steps: list[dict] = [{"sse": True}]                           # the stream's first frame: nothing new
steps += [{"ingest": prompts(10, "burst")}, {"sse": True}]    # a burst of 10 in one frame
steps += [{"advance": 50}] * 60                               # 3 s in 50 ms steps: the card goes up, the count resets
for _ in range(60):                                           # one prompt every 100 ms for 6 s, from two clusters
    steps += [{"ingest": prompts(1, "flood", "attackme" if n % 3 else "bane")}, {"sse": True}, {"advance": 100}]
steps += [{"advance": 100}] * 30                              # the flood drains
steps += [{"drop": True}, {"ingest": prompts(7, "polled")}]   # the stream drops; the fallback polls these 7 up
steps += [{"advance": 100}] * 120                             # 12 s: polls, a card, the stream reopens
steps += [{"ingest": prompts(3, "after")}, {"sse": True}]     # 3 new on the reopened stream
steps += [{"sse": {"since": n - 8}}]                          # a replay of 8 the page holds: not new arrivals
steps += [{"advance": 100}] * 60                              # 6 s quiet

with tempfile.TemporaryDirectory() as tmp:
    pp = pathlib.Path(tmp) / "wall.html"
    pp.write_text(page, encoding="utf-8")
    sp = pathlib.Path(tmp) / "script.json"
    sp.write_text(json.dumps({"history": history, "steps": steps}), encoding="utf-8")
    out = subprocess.run(["node", str(HARNESS), str(pp), str(sp)], capture_output=True, text=True, timeout=300)
if out.returncode != 0:
    fail_now(f"the harness exited {out.returncode}: {(out.stderr or out.stdout).strip()[:800]}")
got = json.loads(out.stdout.strip().splitlines()[-1])
frames, log = got["frames"], got["log"]


def expected_at(log_len: int) -> int:
    """Prompts with a seq the page had not seen, delivered after the last card it put up, in log order."""
    seen: set[int] = set()
    since = 0
    for ev in log[:log_len]:
        if "deliver" in ev:
            for s in ev["deliver"]:
                if s not in seen:
                    seen.add(s)
                    since += 1
        elif "card" in ev:
            since = 0
    return since


print("== the count after every step ==")
shown = [MORE.match(f["more"] or "") for f in frames]
check('the count always reads "+N more"', all(shown),
      "; ".join(f"t={f['t']} {f['more']!r}" for f, m in zip(frames, shown) if not m)[:600])
check("the count is never hidden (hidden attribute or display:none) in any frame",
      all(f["more_hidden"] is False and f["more_display"] != "none" for f in frames),
      "; ".join(f"t={f['t']} hidden={f['more_hidden']} display={f['more_display']!r}" for f in frames
                if f["more_hidden"] is not False or f["more_display"] == "none")[:600])
check("no reload happened (one boot id throughout)", frames[-1]["reloads"] == 0)

wrong = []
for f, m in zip(frames, shown):
    want = expected_at(f["log_len"])
    if not m or int(m.group(1)) != want:
        wrong.append(f"t={f['t']} after {f['step']}: shows {f['more']!r}, {want} arrived since the last card")
check("in every frame the count equals the prompts that arrived and were not shown since the last card", not wrong,
      f"{len(wrong)} of {len(frames)} frames wrong; first: " + "; ".join(wrong[:4]))

burst = frames[3]  # frame i+1 follows steps[i]: load, the first sse frame, the ingest, then the burst's frame
check("the burst of 10 reads +10 more before its card goes up", burst["more"] == "+10 more" and burst["cards"] == 2,
      f"{burst}")
check("the counter climbs past +1 during the flood, so it is not a constant",
      max(int(m.group(1)) for m in shown if m) >= 10)

resets, misses = 0, []
for prev, f in zip(frames, frames[1:]):
    if f["cards"] > prev["cards"]:
        tail = log[prev["log_len"]:f["log_len"]]
        last_card = max(i for i, ev in enumerate(tail) if "card" in ev)
        if not any("deliver" in ev and ev["deliver"] for ev in tail[last_card + 1:]):
            resets += 1
            if f["more"] != "+0 more":
                misses.append(f"t={f['t']}: a card went up and the count reads {f['more']!r}")
check("it resets to +0 more every time a card appears", not misses, "; ".join(misses[:4]))
check("the scenario put up enough cards to exercise the reset (at least 6)", resets >= 6, f"{resets} cards")
check("it reads +0 more once the wall has gone quiet", frames[-1]["more"] == "+0 more", f"{frames[-1]}")
check("the replay added no card and no count", frames[-61]["more"] == frames[-62]["more"]
      and frames[-61]["cards"] == frames[-62]["cards"], f"{frames[-62]} then {frames[-61]}")

print()
if failures:
    print(f"{len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print(f"ALL {len(frames)} FRAMES CHECKED: the wall's +N more count holds (#935)")
