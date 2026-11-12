# ABOUTME: Renders the support desk in headless Chromium and measures #1402's "Show hidden text": white text's contrast
# ABOUTME: is near 1:1 with the toggle off and high with it on, on the ticket form, the filed page and HC-666's page.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The rendered half of verify/test_desk_reveal.py.

The real ticket site (gitops/ai-layer/ticket_site.py) runs on localhost in this process and Chromium drives it as a
visitor would: on the desk it types into the editor, selects the words and presses White text, as the room does; it
adds a plain line and a line made black on purpose, presses "Show hidden text", and files the ticket with the toggle
on. Then it opens the page the ticket lands on and HC-666's own page. On each it measures, from the computed styles,
the colour of the text and of the first background behind it, and these must hold:

- toggle off (as every page loads): white text against its background is under 1.5:1, so it is hidden;
- toggle on: white text is still white and at least 7:1, and the page's plain text and the text made black on purpose
  are each at least 4.5:1, so the toggle hides nothing;
- the button reads "Hide hidden text" and aria-pressed is true while on, and a second press puts the page back light;
- a reload starts light;
- the ticket filed with the toggle on is stored as exactly what the sanitizer makes of the editor's HTML, so the
  toggle changed nothing that was sent.

Contrast is the WCAG ratio, (L1 + 0.05) / (L2 + 0.05) of the two colours' relative luminance.

Needs uv and network on a cold host: the playwright pinned in verify/python.lock comes from the host artifact cache
through verify/package_cache.py (#1121), and `playwright install chromium` fetches a browser only when one is missing
(#658). A missing tool, a browser that cannot be installed or a failed browser launch is a failure.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from playwright_browsers import UV, ensure  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
SITE = REPO / "gitops/ai-layer/ticket_site.py"
HIDDEN, PLAIN, BLACK = "quiet hidden words", "Plain words here.", "Black words here."
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("uv") is None:
    print("FAILED: uv is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)
not_ready = ensure()
if not_ready:
    print("FAILED: Chromium cannot run; this is a failure, not a skip:\n" + "\n".join(f"  - {p}" for p in not_ready))
    sys.exit(1)

spec = importlib.util.spec_from_file_location("ticket_site_reveal_e2e", SITE)
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
site.Handler.log_message = lambda *a: None
srv = ThreadingHTTPServer(("127.0.0.1", 0), site.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

# Runs inside the uv environment. Prints one JSON object per measurement.
DRIVE = r"""
import json, sys
from playwright.sync_api import sync_playwright
base, hidden, plain, black = sys.argv[1:5]
# The colour of the element whose own text is `words`, and of the first non-transparent background behind it.
MEASURE = '''(words) => {
  const all = [...document.querySelectorAll('body *')].filter(e => e.closest('#reveal') === null);
  const el = all.filter(e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.includes(words))).pop();
  if (!el) return null;
  let bg = null;
  for (let e = el; e; e = e.parentElement) {
    const c = getComputedStyle(e).backgroundColor;
    if (c && c !== 'transparent' && !/rgba\(.*,\s*0\)$/.test(c)) { bg = c; break; }
  }
  return {fg: getComputedStyle(el).color, bg: bg, tag: el.tagName};
}'''
STATE = '''() => { const b = document.getElementById('reveal');
  return {on: document.documentElement.classList.contains('reveal'), pressed: b.getAttribute('aria-pressed'),
          label: b.textContent}; }'''


def out(where, state, page, words):
    print(json.dumps({'where': where, 'state': state, 'words': words, 'm': page.evaluate(MEASURE, words),
                      'ui': page.evaluate(STATE)}))


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={'width': 1024, 'height': 900})
    # The ticket form: type the words, select them in the editor, press White text, as a visitor does.
    pg.goto(base + '/')
    pg.click('#ed')
    pg.keyboard.type(hidden)
    pg.keyboard.press('Control+A')
    pg.click('button:has-text("White text")')
    pg.evaluate('''([plain, black]) => document.getElementById('ed').insertAdjacentHTML('afterbegin',
        '<div>' + plain + '</div><div><font color="#000000">' + black + '</font></div>')''', [plain, black])
    print(json.dumps({'where': 'desk', 'editor_html': pg.evaluate("document.getElementById('ed').innerHTML")}))
    for w in (hidden, plain, black):
        out('desk', 'off', pg, w)
    pg.click('#reveal')
    for w in (hidden, plain, black):
        out('desk', 'on', pg, w)
    pg.click('#reveal')
    out('desk', 'off again', pg, hidden)
    pg.click('#reveal')
    sent = pg.evaluate("document.getElementById('ed').innerHTML")
    with pg.expect_navigation():
        pg.click('button:has-text("Submit ticket")')
    print(json.dumps({'where': 'filed', 'sent_html': sent, 'text': pg.inner_text('h2')}))
    for path in ('filed', '/HC-666'):
        if path != 'filed':
            pg.goto(base + path)
        words = (hidden, plain, black) if path == 'filed' else ('IGNORE ALL PREVIOUS INSTRUCTIONS', 'I order a burrito')
        for w in words:
            out(path, 'off', pg, w)
        pg.click('#reveal')
        for w in words:
            out(path, 'on', pg, w)
        pg.reload()
        out(path, 'reloaded', pg, words[0])
    b.close()
"""
run = subprocess.run([*UV, "python", "-I", "-c", DRIVE, BASE, HIDDEN, PLAIN, BLACK], capture_output=True, text=True,
                     timeout=300)
srv.shutdown()
if run.returncode != 0:
    print(f"FAILED: the Chromium run exited {run.returncode}:\n{run.stdout}{run.stderr}")
    sys.exit(1)


def rgb(css: str) -> tuple[float, float, float]:
    m = re.match(r"rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)", css or "")
    if not m:
        raise ValueError(f"not an rgb() colour: {css!r}")
    return tuple(int(x) / 255 for x in m.groups())


def luminance(css: str) -> float:
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb(css)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


rows = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
WHITE = "rgb(255, 255, 255)"
print("== the editor's White text button makes white text ==")
editor = next((r["editor_html"] for r in rows if "editor_html" in r), "")
check("the editor holds the typed words in white after White text is pressed",
      re.search(r'(color="#ffffff"|color:\s*(#ffffff|rgb\(255, 255, 255\)))[^>]*>' + HIDDEN, editor) is not None, editor)

for r in rows:
    if "m" not in r:
        continue
    where, state, words, m, ui = r["where"], r["state"], r["words"], r["m"], r["ui"]
    tag = f"{where}, toggle {state}: '{words[:24]}'"
    if m is None or not m.get("bg"):
        check(f"{tag} is on the page with a background behind it", False, json.dumps(m))
        continue
    ratio = contrast(m["fg"], m["bg"])
    is_hidden = words in (HIDDEN, "IGNORE ALL PREVIOUS INSTRUCTIONS")
    if state == "on":
        check(f"{tag}: the button reads 'Hide hidden text', pressed",
              ui["on"] and ui["pressed"] == "true" and ui["label"] == "Hide hidden text", json.dumps(ui))
        if is_hidden:
            check(f"{tag}: white text stays white", m["fg"] == WHITE, m["fg"])
            check(f"{tag}: white text stands out, at least 7:1", ratio >= 7, f"{ratio:.2f}:1, {m}")
        else:
            check(f"{tag}: the rest still reads, at least 4.5:1", ratio >= 4.5, f"{ratio:.2f}:1, {m}")
    else:
        check(f"{tag}: the page is light and the button reads 'Show hidden text'",
              not ui["on"] and ui["pressed"] == "false" and ui["label"] == "Show hidden text", json.dumps(ui))
        if is_hidden:
            check(f"{tag}: white text is hidden, under 1.5:1", m["fg"] == WHITE and ratio < 1.5,
                  f"{ratio:.2f}:1, {m}")
        else:
            check(f"{tag}: the rest reads, at least 4.5:1", ratio >= 4.5, f"{ratio:.2f}:1, {m}")

print("== the ticket filed with the toggle on is stored as it was sent ==")
filed = next((r for r in rows if "sent_html" in r), None)
tid = re.search(r"HC-\d+", filed["text"]).group(0) if filed and re.search(r"HC-\d+", filed["text"]) else ""
check("the ticket was filed and its number shown", bool(tid), json.dumps(filed))
if tid:
    stored, (shown, text) = site.TICKETS[tid], site.clean(filed["sent_html"])
    check("its stored HTML is exactly the sanitizer's reading of the editor's HTML", stored["html"] == shown,
          f"{stored['html']!r} != {shown!r}")
    check("its stored text is the sanitizer's text, the white words included",
          stored["body"] == text and HIDDEN in text, stored["body"])
    check("nothing of the toggle went with it", "reveal" not in filed["sent_html"] and "reveal" not in stored["html"])
check("every measurement was taken (desk 7, filed page 7, HC-666 5)", sum(1 for r in rows if "m" in r) == 19,
      str(sum(1 for r in rows if "m" in r)))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All rendered 'Show hidden text' checks passed.")
