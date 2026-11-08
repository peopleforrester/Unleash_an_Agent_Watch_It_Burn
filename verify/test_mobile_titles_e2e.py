# ABOUTME: Renders burritbot.html in headless Chromium at phone widths and measures the title bar and the chat card
# ABOUTME: title, so the one-row bar and compact card header (#1214, after #387) are proven by geometry, not a CSS grep.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The rendered half of verify/test_mobile_titles.py.

At each width the page is loaded from the file with every network request aborted (only layout is under
test), so all four header buttons show and no witch name does. These must hold:

- the title "BurritoBot" is one line;
- below 760px the bar is one row (#1214): every header button sits on the title's row, none clipped, none past
  the right edge, all at one font size; with four buttons a phone shows their icons and 680px and up their labels;
- in the chat card, the avatar, "BurritoBot", the ⓘ toggle and Reset share one row, the title and Reset are one
  line each, and the tagline is folded;
- nothing makes the page scroll sideways.

At 1280 the bar is one row with its labels and the card shows its tagline with no ⓘ toggle, so the desktop layout is
unchanged.

Which fonts the host has decides how wide a label renders (#1047: a label fit on netcup and was cut off on Tanjiro's
CI runner). So the page measures the bar and falls back to icons, then to a smaller font, rather than resting on the
host's fonts, and this test does not rest on them to prove it. It renders the page twice: as shipped, and as a copy
whose header buttons carry 4px of letter-spacing, about 40px wider per label than any font the host could pick. That
copy must still pass every check, and at 680px, where the shipped page keeps its four labels, it must show icons,
so the fit is shown to work on the widest fonts, not only on the ones this host happens to have.

Needs uv and network on a cold host: the playwright pinned in verify/python.lock comes from the host artifact cache
through verify/package_cache.py (#1121), and `playwright install chromium` fetches a browser only when one is missing, because it locks the browsers
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
WIDTHS = [320, 359, 360, 390, 412, 430, 680, 760, 1280]
# The copy's widening: inserted before the page's one </head>, after its own stylesheet, so it wins.
HEAD_END = "</head>"
WIDEN = "<style>header a.hb{letter-spacing:4px}</style>"

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
  const shown = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).display !== 'none';
  return {
    icons: hdr.classList.contains('hbicons'), labels: btns.map(a => shown(a.querySelector('.hbl'))),
    brand: box(hdr.querySelector('.brand')), brandLines: lines(hdr.querySelector('.brand')),
    btns: btns.map(box), clipped: btns.filter(a => a.scrollWidth > a.clientWidth).map(a => a.id),
    over: btns.filter(a => a.scrollWidth > a.clientWidth).map(a => `${a.id} ${a.scrollWidth}>${a.clientWidth}`),
    px: btns.map(a => parseFloat(getComputedStyle(a).fontSize)),
    avatar: box(ch.querySelector('.avatar')), h2: box(ch.querySelector('h2')),
    h2Lines: lines(ch.querySelector('h2')),
    reset: box(ch.querySelector('.reset')), resetLines: lines(ch.querySelector('.reset')),
    about: shown(ch.querySelector('.about')) ? box(ch.querySelector('.about')) : null,
    sub: shown(ch.querySelector('.sub')),
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


def same_row(a: dict, b: dict) -> bool:
    """Two boxes share a row when each one's vertical middle lies inside the other's height."""
    return a["t"] <= (b["t"] + b["b"]) / 2 <= a["b"] and b["t"] <= (a["t"] + a["b"]) / 2 <= b["b"]


icons = {}
for m in map(json.loads, run.stdout.splitlines()):
    w, btns, label = m["w"], m["btns"], m["page"]
    icons[(label, w)] = m["icons"]
    tag = f"{w}" if label == "as shipped" else f"{w} {label}"
    print(f"== {w}px ==" if label == "as shipped" else f"== {w}px, {label} ==")
    check(f"{tag}: nothing scrolls sideways", m["docW"] <= w, f"scrollWidth {m['docW']}")
    check(f"{tag}: the title is one line", m["brandLines"] == 1, f"{m['brandLines']} lines")
    check(f"{tag}: no header button is clipped", not m["clipped"],
          f"clipped {m['clipped']}, scrollWidth>clientWidth {m['over']}, font px {m['px']}")
    check(f"{tag}: the header buttons share one font size", len(set(m["px"])) == 1, f"font px {m['px']}")
    check(f"{tag}: no header button runs past the edge", max(b["r"] for b in btns) <= w, "")
    check(f"{tag}: the bar is one row, every button on the title's row", all(same_row(m["brand"], b) for b in btns),
          f"title {m['brand']}, buttons {btns}")
    check(f"{tag}: the buttons show {'icons' if m['icons'] else 'labels'}, all of them alike",
          all(x == (not m["icons"]) for x in m["labels"]), f"labels shown {m['labels']}")
    if w >= 1280:
        check(f"{tag}: desktop keeps the labels", not m["icons"])
        check(f"{tag}: desktop shows the tagline and no ⓘ toggle", m["sub"] and m["about"] is None,
              f"tagline {m['sub']}, toggle {m['about']}")
    else:
        if label == "as shipped":
            check(f"{tag}: four buttons show {'labels' if w >= 680 else 'icons'} at this width",
                  m["icons"] == (w < 680), f"icons {m['icons']}")
        check(f"{tag}: avatar, chat title, ⓘ and Reset share a row",
              m["about"] is not None and all(same_row(m["avatar"], x) for x in (m["h2"], m["about"], m["reset"])),
              f"avatar {m['avatar']}, title {m['h2']}, about {m['about']}, reset {m['reset']}")
        check(f"{tag}: the chat title is one line", m["h2Lines"] == 1, f"{m['h2Lines']} lines")
        check(f"{tag}: Reset is one line", m["resetLines"] == 1, f"{m['resetLines']} lines")
        check(f"{tag}: the tagline is folded", not m["sub"])

print("== the fit engaged on the wide-font copy ==")
for w in (680,):
    check(f"at {w}px the shipped page keeps its labels and the wide-font copy falls back to icons, so the fit ran "
          "and was measured", icons.get(("as shipped", w)) is False and icons.get(("wide fonts", w)) is True,
          f"shipped icons {icons.get(('as shipped', w))}, wide-font icons {icons.get(('wide fonts', w))}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All rendered mobile-title checks passed.")
