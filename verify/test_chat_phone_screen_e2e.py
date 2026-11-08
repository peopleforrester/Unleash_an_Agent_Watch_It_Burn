# ABOUTME: Renders the BurritoBot chat page in headless Chromium on phone screens, sends a prompt whose reply is long, and
# ABOUTME: measures that the conversation gets the screen (#1214): a one-row top bar, a compact card header, a reply read from its start.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The rendered check for #1214, the chat page on a normal phone.

Michael's screenshot from a Pixel, about 412 CSS px wide, on 2026-11-08: the purple bar took two rows (about 170px),
the chat card's header about 220px before any message, a long reply opened at its last lines with its first ones
hidden under the card header, and about 40% of the screen showed message text.

The page is served from the repo file under the real host names, every request answered by a route (no network):
the public bot, https://attackme.burritobot.co/, where event.js hides the Terminal and Datadog buttons, and the
private bot, https://burritobot-private.burritobot.co/, which shows all four. /chat answers one long reply, which
opens "Salt Lake City, Utah" as the screenshot's did. The witch name is pinned (#797): the page's own vocabulary is
measured in the witch line's font and the widest of its 768 names is set in the wib_witch cookie, so the card header
is checked with the longest line it can carry.

At 320x640, 360x780, 390x844 and 412x915 (the issue names the last two), on both pages, these must hold:

- the top bar is one row: the brand and every shown button share it, none clipped or past the right edge;
- the chat card header is one row: the avatar, the title, the ⓘ toggle and Reset share it; the witch name and its
  re-roll button are the short line under that row, inside the card header; the tagline is folded and the ⓘ toggle
  opens it. At 390 and 412 the witch line is one line and the card header at most 72px tall. At 320 and 360 the
  widest name and its button wrap to a second line, and the card header is at most 92px;
- the whole chat card, composer included, fits on the screen;
- after the long reply lands, its first line is inside the stream's visible box and on the screen, and the reply
  shows over at least 60% of the viewport's height.

At 840x900 (#1213's band) and 1280x800 (desktop) the phone changes are not in force: the bar keeps its labels, the
tagline shows with no ⓘ toggle, and the stream keeps its cap (60vh at 840). The reply opens at its first line there
too, since a reply taller than the stream was cut off at its top on any screen.

`python3 verify/test_chat_phone_screen_e2e.py --live` loads the two real hosts over the network instead, with only
/chat answered by the test, so no prompt reaches either bot: the issue's check on the deployed pages, run by hand,
never by the tier.

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
PHONES = [(320, 640), (360, 780), (390, 844), (412, 915)]
WIDER = [(840, 900), (1280, 800)]
FIRST_LINE = "Salt Lake City, Utah"
# A long reply, as the screenshot's was: about 3,000 characters in short paragraphs, taller than any phone's stream.
REPLY = (FIRST_LINE + " sits in a valley ringed by the Wasatch and Oquirrh mountains. ") + " ".join(
    f"\n\nPart {i}: the Hex & Cauldron would deliver a burrito here by broomstick, crossing the valley floor at dusk, "
    f"past the old rail yards and the salt flats to the west, and it would arrive warm." for i in range(1, 19))
# The chat card header's height on a phone, in px; it was about 220 in the screenshot. From 390px the widest witch
# line is one line; on a narrower phone it may take two.
HEADER_MAX = {True: 72, False: 92}   # keyed by "the phone is at least 390px wide"
SHARE = 0.60      # the share of the viewport's height the long reply must show over
LIVE = sys.argv[1:] == ["--live"]
if sys.argv[1:] and not LIVE:
    print(f"FAILED: unknown arguments {sys.argv[1:]}; the only one is --live")
    sys.exit(1)

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

# Runs inside the uv environment. Prints one JSON object per page and size, or {"error": ...} for a page that
# cannot be measured (a served page without the elements this reads, a reply that never landed).
MEASURE = r"""
import json, sys
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
page_path, event_path, live, reply = sys.argv[1], sys.argv[2], sys.argv[3] == '1', sys.argv[4]
pages, sizes = json.loads(sys.argv[5]), json.loads(sys.argv[6])
html, event_js = open(page_path, encoding='utf-8').read(), open(event_path, encoding='utf-8').read()
CHAT = json.dumps({'reply': reply, 'input_tokens': 1, 'output_tokens': 1, 'cost_usd': 0})
# The widest name the page's own vocabulary can make, measured in the witch line's font.
WIDEST = '''() => { const el = document.getElementById('witch'); if (!el || typeof WITCH_FIRST === 'undefined') return null;
  const c = document.createElement('canvas').getContext('2d'); c.font = getComputedStyle(el).font;
  let best = null, w = -1;
  for (const f of WITCH_FIRST) for (const k of WITCH_CREATURES) {
    const n = f + ' the ' + k, x = c.measureText('🧙 You are ' + n).width; if (x > w) { w = x; best = n; } }
  return best.toLowerCase().replace(/ /g, '-'); }'''
MEASURE_JS = '''() => {
  const q = s => document.querySelector(s);
  const box = e => { if (!e) return null; const r = e.getBoundingClientRect();
    return {l: r.left, t: r.top, r: r.right, b: r.bottom, h: r.height, w: r.width}; };
  const shown = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).display !== 'none';
  const bar = q('body>header'), ch = q('.chathead'), s = q('#stream');
  const need = {'body>header': bar, '.chathead': ch, '#stream': s, '#witch': q('#witch'),
                '.chathead h2': ch && ch.querySelector('h2'), '.chathead .reset': ch && ch.querySelector('.reset')};
  const missing = Object.keys(need).filter(k => !need[k]);
  if (missing.length) return {missing};
  const btns = [...bar.querySelectorAll('a.hb')].filter(shown);
  const bots = [...s.querySelectorAll('.msg.bot')], reply = bots[bots.length - 1];
  // The reply's first line: the first line box of its text, from a Range over its first text node.
  let first = null;
  if (reply) { const w = document.createTreeWalker(reply, NodeFilter.SHOW_TEXT); const n = w.nextNode();
    if (n) { const rg = document.createRange(); rg.setStart(n, 0); rg.setEnd(n, Math.min(n.length, 8));
      const r = rg.getClientRects()[0]; if (r) first = {t: r.top, b: r.bottom, text: n.data.slice(0, 40)}; } }
  const sr = s.getBoundingClientRect(), cs = getComputedStyle(s);
  const inner = {t: sr.top + parseFloat(cs.borderTopWidth), b: sr.bottom - parseFloat(cs.borderBottomWidth)};
  let showsOver = 0;
  if (reply) { const r = reply.getBoundingClientRect();
    showsOver = Math.max(0, Math.min(r.bottom, inner.b, innerHeight) - Math.max(r.top, inner.t, 0)); }
  return {
    vh: innerHeight, vw: innerWidth, docW: document.scrollingElement.scrollWidth,
    bar: box(bar), barOver: bar.scrollWidth - bar.clientWidth, icons: bar.classList.contains('hbicons'),
    brand: box(bar.querySelector('.brand')),
    btns: btns.map(a => ({id: a.id, ...box(a), clipped: a.scrollWidth > a.clientWidth,
                          label: shown(a.querySelector('.hbl'))})),
    card: box(q('.chatcol')), head: box(ch), avatar: box(ch.querySelector('.avatar')), h2: box(ch.querySelector('h2')),
    about: shown(q('#aboutbtn')) ? box(q('#aboutbtn')) : null, reset: box(ch.querySelector('.reset')),
    sub: shown(q('#chatsub')), witch: shown(q('#witch')) ? box(q('#witch')) : null,
    newwitch: shown(q('#newwitch')) ? box(q('#newwitch')) : null,
    witchText: q('#witch').textContent,
    stream: {t: inner.t, b: inner.b, clientH: s.clientHeight, scrollTop: s.scrollTop,
             max: s.scrollHeight - s.clientHeight, cap: cs.maxHeight},
    reply: reply ? box(reply) : null, first, showsOver, bots: bots.length,
  };
}'''
def route(host, page_too):
    def handle(r):
        u = urlsplit(r.request.url)
        if u.path == '/chat' and r.request.method == 'POST':
            return r.fulfill(status=200, content_type='application/json', body=CHAT)
        if not page_too:
            return r.continue_()
        if u.netloc != host:
            return r.abort()
        if u.path == '/':
            return r.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
        if u.path == '/event.js':
            return r.fulfill(status=200, content_type='application/javascript', body=event_js)
        if u.path == '/controls':
            return r.fulfill(status=200, content_type='application/json', body=json.dumps({'host': host}))
        if u.path == '/deployments.json':
            return r.fulfill(status=200, content_type='application/json', body='[]')
        return r.fulfill(status=404, body='')
    return handle
with sync_playwright() as p:
    b = p.chromium.launch()
    for label, url in pages:
        host = urlsplit(url).netloc
        for w, h in sizes:
            ctx = b.new_context(viewport={'width': w, 'height': h})
            pg = ctx.new_page()
            pg.route('**/*', route(host, not live))
            try:
                pg.goto(url, wait_until='load')
                widest = pg.evaluate(WIDEST)
                if widest:
                    ctx.add_cookies([{'name': 'wib_witch', 'value': widest, 'domain': '.burritobot.co', 'path': '/'}])
                    pg.reload(wait_until='load')
                pg.wait_for_function("() => !document.getElementById('inp').disabled", timeout=20000)
                pg.fill('#inp', 'Where should the Hex & Cauldron open next?')
                pg.click('#sendbtn')
                pg.wait_for_function("() => document.querySelectorAll('#stream .msg.bot').length >= 2", timeout=20000)
                pg.wait_for_timeout(200)
                m = pg.evaluate(MEASURE_JS)
                if 'missing' not in m:
                    about = pg.query_selector('#aboutbtn')
                    if m['about']:
                        about.click()
                        m['subOpened'] = pg.evaluate("() => { const s = document.getElementById('chatsub'); return getComputedStyle(s).display !== 'none' && s.getClientRects().length > 0; }")
                        m['expanded'] = about.get_attribute('aria-expanded')
                print(json.dumps({'page': label, 'w': w, 'h': h, 'widest': widest, **m}))
            except Exception as e:
                print(json.dumps({'page': label, 'w': w, 'h': h, 'error': f'{type(e).__name__}: {e}'.splitlines()[0]}))
            ctx.close()
    b.close()
"""
PAGES = [["public bot", PUBLIC], ["private bot", PRIVATE]]
run = subprocess.run([*UV, "python", "-I", "-c", MEASURE, str(PAGE), str(EVENT_JS), "1" if LIVE else "0", REPLY,
                      json.dumps(PAGES), json.dumps(PHONES + WIDER)], capture_output=True, text=True)
if run.returncode != 0:
    print(f"FAILED: the Chromium render exited {run.returncode}:\n{run.stdout}{run.stderr}")
    sys.exit(1)


def same_row(a: dict, b: dict) -> bool:
    """Two boxes share a row when each one's vertical middle lies inside the other's height."""
    return a["t"] <= (b["t"] + b["b"]) / 2 <= a["b"] and b["t"] <= (a["t"] + a["b"]) / 2 <= b["b"]


print(f"Rendering {'the deployed hosts over the network, /chat answered here' if LIVE else 'the repo page under each host name, no network'}")
seen = 0
for m in map(json.loads, run.stdout.splitlines()):
    seen += 1
    w, h = m["w"], m["h"]
    tag = f"{m['page']} {w}x{h}"
    check(f"{tag}: the page loads, takes a prompt and shows the reply", "error" not in m, m.get("error", ""))
    if "error" in m:
        continue
    check(f"{tag}: the page has every element this measures", "missing" not in m, f"no {m.get('missing')}")
    if "missing" in m:
        continue
    phone = w <= 760
    s, rep, first = m["stream"], m["reply"], m["first"]
    ft, fb = (first["t"], first["b"]) if first else (float("nan"), float("nan"))
    print(f"== {tag} ==  bar {m['bar']['h']:.0f}px ({'icons' if m['icons'] else 'labels'}, "
          f"{[b['id'] for b in m['btns']]}); card header {m['head']['h']:.0f}px; stream {s['clientH']}px, cap {s['cap']}; "
          f"reply {rep['h']:.0f}px, shows over {m['showsOver']:.0f}px = {m['showsOver'] / m['vh']:.0%} of {m['vh']}px; "
          f"{m['witchText']!r}")
    check(f"{tag}: the witch name is the widest the vocabulary makes", bool(m["widest"])
          and m["witchText"].endswith(m["widest"].replace("-", " ").title().replace(" The ", " the ")),
          f"widest {m['widest']}, shown {m['witchText']!r}")
    check(f"{tag}: nothing scrolls sideways", m["docW"] <= w, f"scrollWidth {m['docW']}")
    check(f"{tag}: no header button is clipped or past the right edge",
          not any(b["clipped"] or b["r"] > w for b in m["btns"]), f"buttons {m['btns']}")
    check(f"{tag}: the long reply is taller than the stream, so the case is the one the issue saw",
          rep["h"] > s["clientH"], f"reply {rep['h']:.0f}px, stream {s['clientH']}px")
    check(f"{tag}: the reply's first line ({FIRST_LINE!r}) is the text measured",
          bool(first) and first["text"].startswith(FIRST_LINE), f"first text {first}")
    check(f"{tag}: the reply's first line is inside the stream's visible box, not scrolled above it",
          bool(first) and s["t"] <= first["t"] and first["b"] <= s["b"],
          f"first line y {ft:.0f}-{fb:.0f}, stream y {s['t']:.0f}-{s['b']:.0f}, "
          f"scrollTop {s['scrollTop']} of {s['max']}")
    check(f"{tag}: the reply's first line is on the screen", bool(first) and 0 <= first["t"] and first["b"] <= m["vh"],
          f"first line y {ft:.0f}, viewport {m['vh']}px")
    if phone:
        btns = m["btns"]
        check(f"{tag}: the top bar is one row, the brand and every button on it",
              bool(btns) and all(same_row(m["brand"], b) for b in btns), f"brand {m['brand']}, buttons {btns}")
        check(f"{tag}: the top bar fits its width", m["barOver"] <= 0, f"{m['barOver']}px over")
        row = [m["avatar"], m["h2"], m["about"], m["reset"]]
        check(f"{tag}: the card header is one row: avatar, title, the ⓘ toggle and Reset",
              m["about"] is not None and all(same_row(m["avatar"], x) for x in row),
              f"head {m['head']}, avatar {m['avatar']}, title {m['h2']}, about {m['about']}, reset {m['reset']}")
        top = max(x["b"] for x in row if x)
        most = HEADER_MAX[w >= 390]
        check(f"{tag}: the card header is at most {most}px tall", m["head"]["h"] <= most, f"{m['head']['h']:.0f}px")
        wb, nb = m["witch"], m["newwitch"]
        check(f"{tag}: the witch name and its re-roll button show under that row, inside the card header",
              wb is not None and nb is not None and min(wb["t"], nb["t"]) >= top - 1
              and max(wb["b"], nb["b"]) <= m["head"]["b"] and max(wb["r"], nb["r"]) <= m["head"]["r"],
              f"witch {wb}, button {nb}, row bottom {top:.0f}, head {m['head']}")
        if w >= 390:
            check(f"{tag}: the witch line is one line", wb is not None and nb is not None and same_row(wb, nb),
                  f"witch {wb}, button {nb}")
        check(f"{tag}: the tagline is folded", not m["sub"])
        check(f"{tag}: the ⓘ toggle opens the tagline and says so",
              m.get("subOpened") is True and m.get("expanded") == "true",
              f"shown {m.get('subOpened')}, aria-expanded {m.get('expanded')}")
        check(f"{tag}: the whole chat card fits on the screen, so the sticky composer covers none of the stream",
              m["card"]["b"] <= m["vh"], f"card bottom {m['card']['b']:.0f}px, viewport {m['vh']}px")
        check(f"{tag}: the long reply shows over at least {SHARE:.0%} of the viewport's height",
              m["showsOver"] >= SHARE * m["vh"], f"{m['showsOver']:.0f}px of {m['vh']}px")
    else:
        check(f"{tag}: the top bar keeps its labels", not m["icons"] and all(b["label"] for b in m["btns"]),
              f"icons {m['icons']}, buttons {m['btns']}")
        check(f"{tag}: the tagline shows and there is no ⓘ toggle", m["sub"] and m["about"] is None,
              f"tagline {m['sub']}, toggle {m['about']}")
        if w <= 980:
            check(f"{tag}: the stream keeps #355's 60vh cap", s["cap"] == f"{0.6 * h:g}px", f"max-height {s['cap']}")
check("every page and size was rendered", seen == len(PAGES) * len(PHONES + WIDER),
      f"{seen} of {len(PAGES) * len(PHONES + WIDER)}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All chat phone screen checks passed.")
