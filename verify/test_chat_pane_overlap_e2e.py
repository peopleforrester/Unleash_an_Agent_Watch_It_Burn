# ABOUTME: Renders the BurritoBot chat page in headless Chromium at phone, Fold and tablet sizes and fails when the
# ABOUTME: menu, chat and Backend Insights panes overlap (#1213), on the public bot's page and the private bot's.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The rendered check for #1213, the band #355 left out.

#355 made the phone layout one page scroll with every pane at its natural height, below 760px. From 761 to 980px
the panes still stacked into one column with the desktop's viewport-fraction heights, and Backend Insights was
drawn over the burrito menu: Michael's screenshot from a Pixel 10 Pro Fold, unfolded, on 2026-11-08.

At each size the page is served from the repo file under the real host name, every request answered by a route
(no network), with /controls reporting that host (`{"host": ...}`, the one field the banner reads) as guard-proxy does. Two pages are rendered:

- the public bot, https://attackme.burritobot.co/, which shows no private banner;
- the private bot, https://burritobot-private.burritobot.co/, where /controls names the private host and the
  red "private (administrator)" banner is shown at the top of Backend Insights, so that pane is taller.

These must hold:

- the bounding boxes of .menu, .chatcol and .infra do not intersect, at 390x844, 761x900, 768x1024, 840x900
  (the Fold), 884x1000 and 980x800;
- at those sizes the page scrolls once: no pane, the menu's list and the .wrap band clip their content to a
  private scroller, so every pane is at its natural height;
- at 1280x800 and 1920x1080 the desktop layout stands: the three panes side by side, top-aligned, and the page
  itself does not scroll, so the message stream is the one scroller as the app shell intends.

`python3 verify/test_chat_pane_overlap_e2e.py --live` renders the two real hosts over the network instead, with
nothing routed: that is the issue's check on the deployed pages, run by hand, never by the tier.

Needs uv and network on a cold host, for the playwright pinned in verify/python.lock (verify/package_cache.py) and
a Chromium when one is missing (verify/playwright_browsers.py). A missing tool, a browser that cannot be installed
or a failed launch is a failure.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from playwright_browsers import UV, ensure  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
WEB = REPO / "gitops/ai-layer/web"
PAGE = WEB / "burritbot.html"
EVENT_JS = WEB / "event.js"
PUBLIC = "https://attackme.burritobot.co/"
PRIVATE = "https://burritobot-private.burritobot.co/"
# (width, height): the four sizes the issue names, the band's lower edge, and one wider Fold reading, since the
# Fold's CSS width was read from a screenshot and not measured on the device.
STACKED = [(390, 844), (761, 900), (768, 1024), (840, 900), (884, 1000), (980, 800)]
DESKTOP = [(1280, 800), (1920, 1080)]
LIVE = sys.argv[1:] == ["--live"]
if sys.argv[1:] and not LIVE:
    print(f"FAILED: unknown arguments {sys.argv[1:]}; the only one is --live")
    sys.exit(2)

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("uv") is None:
    print("FAILED: uv is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)
for f in (PAGE, EVENT_JS):
    if not f.is_file():
        print(f"FAILED: {f} is missing, so there is no page to render")
        sys.exit(1)

not_ready = ensure()
if not_ready:
    print("FAILED: Chromium cannot run; this is a failure, not a skip:\n" + "\n".join(f"  - {p}" for p in not_ready))
    sys.exit(1)

# Runs inside the uv environment. Prints one JSON object per page and size.
MEASURE = r"""
import json, sys
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
page_path, event_path, live = sys.argv[1], sys.argv[2], sys.argv[3] == '1'
pages, sizes = json.loads(sys.argv[4]), json.loads(sys.argv[5])
html, event_js = open(page_path, encoding='utf-8').read(), open(event_path, encoding='utf-8').read()
JS = '''() => {
  const y = window.scrollY, x = window.scrollX;
  const box = e => { const r = e.getBoundingClientRect();
    return {l: r.left + x, t: r.top + y, r: r.right + x, b: r.bottom + y}; };
  // A box that clips what it holds: its content is taller than the box and it does not show the rest.
  const clips = e => { const s = getComputedStyle(e);
    return e.scrollHeight > e.clientHeight + 1 && s.overflowY !== 'visible'; };
  const q = s => document.querySelector(s);
  const ban = q('#privatebanner');
  return {
    boxes: Object.fromEntries(['.menu', '.chatcol', '.infra'].map(s => [s, box(q(s))])),
    clipped: ['.wrap', '.store', '.menu', '.menu .mscroll', '.chatcol', '.infra'].filter(s => clips(q(s))),
    docH: document.scrollingElement.scrollHeight, viewH: window.innerHeight,
    docW: document.scrollingElement.scrollWidth,
    banner: !!ban && !ban.hidden && ban.getBoundingClientRect().height > 0,
  };
}'''
def route(host):
    def handle(r):
        u = urlsplit(r.request.url)
        if u.netloc != host:
            return r.abort()
        if u.path == '/':
            return r.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
        if u.path == '/event.js':
            return r.fulfill(status=200, content_type='application/javascript', body=event_js)
        if u.path == '/controls':
            return r.fulfill(status=200, content_type='application/json',
                             body=json.dumps({'host': host}))
        return r.fulfill(status=404, body='')
    return handle
with sync_playwright() as p:
    b = p.chromium.launch()
    for label, url, private in pages:
        host = urlsplit(url).netloc
        for w, h in sizes:
            pg = b.new_page(viewport={'width': w, 'height': h})
            if not live:
                pg.route('**/*', route(host))
            pg.goto(url, wait_until='load')
            pg.wait_for_load_state('networkidle')
            if private:
                try:
                    pg.wait_for_function("() => { const b = document.querySelector('#privatebanner'); return b && !b.hidden; }",
                                         timeout=15000)
                except Exception:
                    pass  # measured below: the check names a banner that never showed
            print(json.dumps({'page': label, 'private': private, 'w': w, 'h': h, **pg.evaluate(JS)}))
            pg.close()
    b.close()
"""
PAGES = [["public bot", PUBLIC, False], ["private bot", PRIVATE, True]]
run = subprocess.run([*UV, "python", "-I", "-c", MEASURE, str(PAGE), str(EVENT_JS), "1" if LIVE else "0",
                      json.dumps(PAGES), json.dumps(STACKED + DESKTOP)], capture_output=True, text=True)
if run.returncode != 0:
    print(f"FAILED: the Chromium render exited {run.returncode}:\n{run.stdout}{run.stderr}")
    sys.exit(1)


def overlap(a: dict, b: dict) -> float:
    """The area two boxes share; 0 when they only touch or do not meet."""
    return max(0.0, min(a["r"], b["r"]) - max(a["l"], b["l"])) * max(0.0, min(a["b"], b["b"]) - max(a["t"], b["t"]))


def span(m: dict, k: str) -> str:
    return f"{k} x {m[k]['l']:.0f}-{m[k]['r']:.0f} y {m[k]['t']:.0f}-{m[k]['b']:.0f}"


# Keyed by selector: a bare pane name would read to verify/scope_tests.py as the repo's top-level directory.
PANES = [".menu", ".chatcol", ".infra"]
print(f"Rendering {'the deployed hosts over the network' if LIVE else 'the repo page under each host name, no network'}")
seen = 0
for m in map(json.loads, run.stdout.splitlines()):
    seen += 1
    w, h = m["w"], m["h"]
    m.update(m.pop("boxes"))
    tag = f"{m['page']} {w}x{h}"
    print(f"== {tag} ==  " + "; ".join(span(m, k) for k in PANES) + f"; page {m['docH']}px tall")
    check(f"{tag}: the private banner is {'shown' if m['private'] else 'not shown'}", m["banner"] == m["private"])
    check(f"{tag}: nothing scrolls sideways", m["docW"] <= w, f"scrollWidth {m['docW']}")
    pairs = [(a, b) for i, a in enumerate(PANES) for b in PANES[i + 1:]]
    for a, b in pairs:
        area = overlap(m[a], m[b])
        check(f"{tag}: {a} and {b} do not overlap", area == 0, f"{area:.0f} px² shared; {span(m, a)}, {span(m, b)}")
    if w <= 980:
        check(f"{tag}: one page scroll, every pane at its natural height", not m["clipped"],
              f"clipping to a private scroller: {m['clipped']}")
        tops = sorted(PANES, key=lambda k: m[k]["t"])
        check(f"{tag}: the panes stack in one column", all(m[a]["b"] <= m[b]["t"] + 1 for a, b in zip(tops, tops[1:])),
              f"order by top {tops}")
    else:
        menu, chat, insights = (m[k] for k in PANES)
        check(f"{tag}: desktop keeps menu, chat and Backend Insights side by side, top-aligned",
              menu["r"] <= chat["l"] and chat["r"] <= insights["l"]
              and max(m[k]["t"] for k in PANES) - min(m[k]["t"] for k in PANES) < 2,
              "; ".join(span(m, k) for k in PANES))
        check(f"{tag}: desktop page does not scroll; the message stream is the one scroller",
              m["docH"] <= m["viewH"] + 1, f"page {m['docH']}px in a {m['viewH']}px window")
check("every page and size was rendered", seen == len(PAGES) * len(STACKED + DESKTOP),
      f"{seen} of {len(PAGES) * len(STACKED + DESKTOP)}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All chat pane overlap checks passed.")
