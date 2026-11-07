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

Which fonts the host has decides how wide a label renders, and four across at 360px leave the BurritoBot label no
room to spare: it fit on netcup and was cut off on Tanjiro's CI runner (#1047). So the page steps the four buttons'
font down together until none overflows, and this test does not rest on the host's fonts to prove it. It renders the
page twice: as shipped, and as a copy whose header buttons carry 1px of letter-spacing, about 12px wider per label
than any font the host could pick. That copy must still pass every check, with its buttons at one size below 11px, so
the fit is shown to work on the widest fonts, not only on the ones this host happens to have.

Needs uv and network on the first run: the playwright pinned in verify/playwright_browsers.py comes in through
`uv run`, and `playwright install chromium` fetches a browser only when one is missing, because it locks the browsers
directory even when nothing is (#658). A missing tool, a browser that cannot be installed or a failed browser launch
is a failure.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from playwright_browsers import UV, ensure  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = REPO / "gitops/ai-layer/web/burritbot.html"
EVENT_JS = PAGE.parent / "event.js"
WIDTHS = [320, 359, 360, 390, 412, 430, 680, 1280]
# The copy's widening: inserted before the page's one </head>, after its own stylesheet, so it wins.
HEAD_END = "</head>"
WIDEN = "<style>header a.hb{letter-spacing:1px}</style>"
CSS_PX = 11.0   # the phone header buttons' font size in the page's CSS, under 760px

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("uv") is None:
    print("FAILED: uv is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)

html = PAGE.read_text(encoding="utf-8")
if html.count(HEAD_END) != 1:
    print(f"FAILED: {PAGE} has {html.count(HEAD_END)} {HEAD_END!r}, not one, so the wide-font copy cannot be built")
    sys.exit(1)

not_ready = ensure()
if not_ready:
    print("FAILED: Chromium cannot run; this is a failure, not a skip:\n" + "\n".join(f"  - {p}" for p in not_ready))
    sys.exit(1)

# The wide-font copy sits beside its own copy of event.js, which the page loads by a relative path.
scratch = pathlib.Path(tempfile.mkdtemp(prefix="mobile-titles-"))
WIDE = scratch / PAGE.name
WIDE.write_text(html.replace(HEAD_END, WIDEN + HEAD_END), encoding="utf-8")
shutil.copy(EVENT_JS, scratch / EVENT_JS.name)

# Runs inside the uv environment. Prints one JSON object per width: the boxes the checks below need.
MEASURE = r"""
import json, sys
from playwright.sync_api import sync_playwright
pages, widths = json.loads(sys.argv[1]), json.loads(sys.argv[2])
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
    over: btns.filter(a => a.scrollWidth > a.clientWidth).map(a => `${a.id} ${a.scrollWidth}>${a.clientWidth}`),
    px: btns.map(a => parseFloat(getComputedStyle(a).fontSize)),
    avatar: box(ch.querySelector('.avatar')), h2: box(ch.querySelector('h2')),
    h2Lines: lines(ch.querySelector('h2')),
    reset: box(ch.querySelector('.reset')), resetLines: lines(ch.querySelector('.reset')),
    sub: box(ch.querySelector('.sub')),
    docW: document.documentElement.scrollWidth,
  };
}'''
with sync_playwright() as p:
    b = p.chromium.launch()
    for label, page_url in pages:
        for w in widths:
            pg = b.new_page(viewport={'width': w, 'height': 844})
            pg.route('http*://**', lambda r: r.abort())
            pg.goto(page_url)
            print(json.dumps({'page': label, 'w': w, **pg.evaluate(JS)}))
            pg.close()
    b.close()
"""
PAGES = [["as shipped", PAGE.as_uri()], ["wide fonts", WIDE.as_uri()]]
run = subprocess.run([*UV, "python", "-I", "-c", MEASURE, json.dumps(PAGES), json.dumps(WIDTHS)],
                     capture_output=True, text=True)
shutil.rmtree(scratch, ignore_errors=True)
if run.returncode != 0:
    print(f"FAILED: the Chromium render exited {run.returncode}:\n{run.stdout}{run.stderr}")
    sys.exit(1)


shrunk_wide = False
for m in map(json.loads, run.stdout.splitlines()):
    w, btns, label = m["w"], m["btns"], m["page"]
    tag = f"{w}" if label == "as shipped" else f"{w} {label}"
    print(f"== {w}px ==" if label == "as shipped" else f"== {w}px, {label} ==")
    check(f"{tag}: nothing scrolls sideways", m["docW"] <= w, f"scrollWidth {m['docW']}")
    check(f"{tag}: the title is one line", m["brandLines"] == 1, f"{m['brandLines']} lines")
    check(f"{tag}: no header button is clipped", not m["clipped"],
          f"clipped {m['clipped']}, scrollWidth>clientWidth {m['over']}, font px {m['px']}")
    check(f"{tag}: the header buttons share one font size", len(set(m["px"])) == 1, f"font px {m['px']}")
    if label != "as shipped" and 360 <= w <= 430:
        shrunk_wide = shrunk_wide or max(m["px"]) < CSS_PX
    check(f"{tag}: no header button runs past the edge", max(b["r"] for b in btns) <= w, "")
    rows = sorted({round(b["t"]) for b in btns})
    if w >= 1280:
        check(f"{tag}: desktop keeps one row, title beside the buttons",
              len(rows) == 1 and abs(btns[0]["t"] - m["brand"]["t"]) < m["brand"]["h"], f"rows {rows}")
    else:
        check(f"{tag}: the buttons sit below the title, not beside it",
              min(b["t"] for b in btns) >= m["brand"]["b"], f"title bottom {m['brand']['b']}, rows {rows}")
        want = 2 if w < 360 else 1
        check(f"{tag}: {want} even row(s) of buttons", len(rows) == want, f"rows {rows}")
        widths = [round(b["r"] - b["l"]) for b in btns]
        check(f"{tag}: every button the same width", max(widths) - min(widths) <= 1, f"widths {widths}")
        check(f"{tag}: avatar, chat title and Reset share a row",
              all(abs(x["t"] - m["avatar"]["t"]) < m["avatar"]["h"] for x in (m["h2"], m["reset"])), "")
        check(f"{tag}: the chat title is one line", m["h2Lines"] == 1, f"{m['h2Lines']} lines")
        check(f"{tag}: Reset is one line", m["resetLines"] == 1, f"{m['resetLines']} lines")
        check(f"{tag}: the tagline starts below that row",
              m["sub"]["t"] >= max(m["avatar"]["b"], m["h2"]["b"], m["reset"]["b"]) - 1, "")

print("== the fit engaged on the wide-font copy ==")
check(f"at 360-430px the wide-font copy's buttons were stepped below {CSS_PX:g}px, so the fit ran and was "
      "measured, not skipped", shrunk_wide)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All rendered mobile-title checks passed.")
