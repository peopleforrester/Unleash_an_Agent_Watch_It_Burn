# ABOUTME: Renders burritbot.html in headless Chromium at phone widths and measures the title bar and the
# ABOUTME: chat card title, so "the stacking of the title" (#387) is proven by geometry, not by a CSS grep.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The rendered half of verify/test_mobile_titles.py.

At each width the page is loaded from the file with every network request aborted (only layout is under
test), and these must hold:

- the title "BurritoBot · agenticburn" is one line on a row of its own;
- the four header buttons are one even row (two even rows of two under 360px), none clipped, none past
  the right edge;
- in the chat card, the avatar, "BurritoBot" and Reset share one row, Reset is one line, and the tagline
  starts below them;
- nothing makes the page scroll sideways.

At 1280 the header is still a single row, so the desktop layout is unchanged.

Needs uv and network on the first run: playwright 1.64.1 comes in through `uv run`, and `playwright install
chromium` fetches the browser if it is not cached. A missing tool or a failed browser launch is a failure.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = REPO / "gitops/ai-layer/web/burritbot.html"
PLAYWRIGHT = "playwright==1.64.1"
WIDTHS = [320, 359, 360, 390, 412, 430, 680, 1280]

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("uv") is None:
    print("FAILED: uv is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)

UV = ["uv", "run", "--no-project", "--with", PLAYWRIGHT]
install = subprocess.run([*UV, "playwright", "install", "chromium"], capture_output=True, text=True)
if install.returncode != 0:
    print(f"FAILED: `playwright install chromium` exited {install.returncode}:\n{install.stdout}{install.stderr}")
    sys.exit(1)

# Runs inside the uv environment. Prints one JSON object per width: the boxes the checks below need.
MEASURE = r"""
import json, sys
from playwright.sync_api import sync_playwright
page_url, widths = sys.argv[1], json.loads(sys.argv[2])
JS = '''() => {
  const box = e => { const r = e.getBoundingClientRect(); return {l:r.left, t:r.top, r:r.right, b:r.bottom, h:r.height}; };
  const hdr = document.querySelector('body>header'), ch = document.querySelector('.chathead');
  const btns = [...hdr.querySelectorAll('a.hb')];
  // Line boxes, counted from the content itself: a Range's rects, where a rect that starts below the
  // current line's bottom opens a new line. Overlap, not equal tops, because the title mixes an icon and
  // two type sizes on one line.
  const lines = e => { const rg = document.createRange(); rg.selectNodeContents(e);
    const rs = [...rg.getClientRects()].filter(r => r.width > 0 && r.height > 0).sort((x, y) => x.top - y.top);
    let n = 0, bottom = -Infinity;
    for (const r of rs) { if (r.top >= bottom - 1) { n++; bottom = r.bottom; } else bottom = Math.max(bottom, r.bottom); }
    return n; };
  return {
    brand: box(hdr.querySelector('.brand')), brandLines: lines(hdr.querySelector('.brand')),
    btns: btns.map(box), clipped: btns.filter(a => a.scrollWidth > a.clientWidth).map(a => a.id),
    avatar: box(ch.querySelector('.avatar')), h2: box(ch.querySelector('h2')),
    h2Lines: lines(ch.querySelector('h2')),
    reset: box(ch.querySelector('.reset')), resetLines: lines(ch.querySelector('.reset')),
    sub: box(ch.querySelector('.sub')),
    docW: document.documentElement.scrollWidth,
  };
}'''
with sync_playwright() as p:
    b = p.chromium.launch()
    for w in widths:
        pg = b.new_page(viewport={'width': w, 'height': 844})
        pg.route('http*://**', lambda r: r.abort())
        pg.goto(page_url)
        print(json.dumps({'w': w, **pg.evaluate(JS)}))
        pg.close()
    b.close()
"""
run = subprocess.run([*UV, "python", "-I", "-c", MEASURE, PAGE.as_uri(), json.dumps(WIDTHS)],
                     capture_output=True, text=True)
if run.returncode != 0:
    print(f"FAILED: the Chromium render exited {run.returncode}:\n{run.stdout}{run.stderr}")
    sys.exit(1)


for m in map(json.loads, run.stdout.splitlines()):
    w, btns = m["w"], m["btns"]
    print(f"== {w}px ==")
    check(f"{w}: nothing scrolls sideways", m["docW"] <= w, f"scrollWidth {m['docW']}")
    check(f"{w}: the title is one line", m["brandLines"] == 1, f"{m['brandLines']} lines")
    check(f"{w}: no header button is clipped", not m["clipped"], f"clipped {m['clipped']}")
    check(f"{w}: no header button runs past the edge", max(b["r"] for b in btns) <= w, "")
    rows = sorted({round(b["t"]) for b in btns})
    if w >= 1280:
        check(f"{w}: desktop keeps one row, title beside the buttons",
              len(rows) == 1 and abs(btns[0]["t"] - m["brand"]["t"]) < m["brand"]["h"], f"rows {rows}")
    else:
        check(f"{w}: the buttons sit below the title, not beside it",
              min(b["t"] for b in btns) >= m["brand"]["b"], f"title bottom {m['brand']['b']}, rows {rows}")
        want = 2 if w < 360 else 1
        check(f"{w}: {want} even row(s) of buttons", len(rows) == want, f"rows {rows}")
        widths = [round(b["r"] - b["l"]) for b in btns]
        check(f"{w}: every button the same width", max(widths) - min(widths) <= 1, f"widths {widths}")
        check(f"{w}: avatar, chat title and Reset share a row",
              all(abs(x["t"] - m["avatar"]["t"]) < m["avatar"]["h"] for x in (m["h2"], m["reset"])), "")
        check(f"{w}: the chat title is one line", m["h2Lines"] == 1, f"{m['h2Lines']} lines")
        check(f"{w}: Reset is one line", m["resetLines"] == 1, f"{m['resetLines']} lines")
        check(f"{w}: the tagline starts below that row",
              m["sub"]["t"] >= max(m["avatar"]["b"], m["h2"]["b"], m["reset"]["b"]) - 1, "")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All rendered mobile-title checks passed.")
