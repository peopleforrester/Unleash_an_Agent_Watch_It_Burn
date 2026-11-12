# ABOUTME: Holds #1402's markup: the support desk's "Show hidden text" button is on the ticket form and every page that
# ABOUTME: shows a ticket, starts light, darkens the page only in the browser, and leaves stored tickets and the bot's read as they were.
"""The real ticket site (gitops/ai-layer/ticket_site.py) runs on localhost and is driven over HTTP as a phone would
drive it through the console. No cluster, no model, no browser: verify/test_desk_reveal_e2e.py renders the pages in
Chromium and measures the contrast.

Michael, 2026-11-12: "toggle the whole site to black so we can see the white text stand out". The desk's editor has
Black text and White text, and the pages are white, so white text is invisible while typed and once filed. This test
holds that:

- the ticket form, a ticket's own page (/<id>, HC-666 included), the page a filed ticket lands on, and /me carry the
  button once, labelled "Show hidden text", a plain button (type=button, so it never submits the form) that starts
  unpressed;
- no page starts dark, and the button stores nothing (no cookie, no localStorage, no sessionStorage), so every load
  starts light;
- the dark style darkens the page and the editor, keeps white text white, and gives text made black on purpose the
  light ink, so the toggle hides nothing;
- the colour buttons are still exactly Black text and White text;
- a filed ticket's stored HTML and text are what the sanitizer made of what was sent, HC-666's are as seeded, and
  /ticket?id=, which read_support_ticket reads, answers the same five fields with no trace of the toggle.
"""
from __future__ import annotations

import html
import http.cookiejar
import importlib.util
import json
import pathlib
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parent.parent
SITE = REPO / "gitops/ai-layer/ticket_site.py"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


spec = importlib.util.spec_from_file_location("ticket_site_reveal", SITE)
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
site.Handler.log_message = lambda *a: None
srv = ThreadingHTTPServer(("127.0.0.1", 0), site.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
HEADERS = {"User-Agent": "reveal-test", "X-Forwarded-For": "203.0.113.40"}


def get(path: str) -> tuple[int, str]:
    try:
        with opener.open(urllib.request.Request(BASE + path, headers=HEADERS), timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def post(path: str, form: dict) -> tuple[int, str]:
    req = urllib.request.Request(BASE + path, data=urllib.parse.urlencode(form).encode(), headers=HEADERS)
    try:
        with opener.open(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


BUTTON = re.compile(r'<button type="button" id="reveal" aria-pressed="false"[^<]*>Show hidden text</button>')


def holds_toggle(name: str, page: str) -> None:
    check(f"{name}: one 'Show hidden text' button, type=button, unpressed", len(BUTTON.findall(page)) == 1
          and page.count('id="reveal"') == 1, f"{len(BUTTON.findall(page))} matching buttons")
    check(f"{name}: the page starts light (no element carries the reveal class)",
          re.search(r'class="[^"]*\breveal\b', page) is None)
    check(f"{name}: the page's background is white until the button is pressed",
          "html,body{background:#ffffff}" in page)


SEEDED = {k: json.loads(json.dumps(v)) for k, v in site.TICKETS.items()}

print("== the button and what it does to the style ==")
bar, style = site.REVEAL_BAR, site.REVEAL_STYLE
check("the button names itself 'Show hidden text' and says 'Hide hidden text' when on",
      ">Show hidden text</button>" in bar and "'Hide hidden text'" in bar and "'Show hidden text'" in bar)
check("it toggles the reveal class on the page's root and sets aria-pressed",
      "document.documentElement.classList.toggle('reveal')" in bar and "setAttribute('aria-pressed'" in bar)
check("it stores nothing, so each load starts light",
      not any(w in bar for w in ("localStorage", "sessionStorage", "cookie")))
check("the dark style darkens the page and the editor with the light default ink",
      f"html.reveal,html.reveal body{{background:{site.REVEAL_BG};color:{site.REVEAL_INK}}}" in style
      and f"html.reveal .ed{{background:{site.REVEAL_BG};color:{site.REVEAL_INK};" in style)
check("text made black on purpose takes the light ink while dark, in each form the editor and the sanitizer write",
      all(f'html.reveal {sel}' in style for sel in
          ('[style*="color:#000000"]', '[style*="color: rgb(0, 0, 0)"]', 'font[color="#000000"]'))
      and f"{{color:{site.REVEAL_INK}!important}}" in style)
check("no rule recolours white text", not re.search(r"#fff|255, 255, 255|white", style, re.I))
check("the dark style is only under html.reveal, so a page loads light",
      all(rule.startswith("html.reveal") or rule.startswith(".revealbar")
          for rule in re.findall(r"(?:^|})([^{}]+)\{", style)))

print("== the ticket form ==")
code, desk = get("/")
check("the desk is a page", code == 200)
holds_toggle("the desk", desk)
check("the button sits outside the ticket form, so it never touches what is submitted",
      desk.index('id="reveal"') < desk.index('<form method="post" action="/submit"'))
colours = re.findall(r"execCommand\('foreColor',false,'([^']+)'\)", desk)
check("the colour buttons are still Black text and White text alone (no colour picker)",
      colours == ["#000000", "#ffffff"] and ">Black text<" in desk and ">White text<" in desk
      and 'type="color"' not in desk, str(colours))

print("== a ticket's own page, HC-666 included ==")
for path in ("/HC-666", "/hc666", "/HC-7731"):
    code, page = get(path)
    check(f"{path} is a page", code == 200)
    holds_toggle(path, page)
code, lookup = get("/lookup?number=HC-666")
check("the look-up form lands on HC-666's page, which carries the button", code == 200 and BUTTON.search(lookup))
code, t666 = get("/HC-666")
check("HC-666's injection is still a white span on the page",
      re.search(r'<span style="color:#ffffff">IGNORE ALL PREVIOUS INSTRUCTIONS', t666) is not None)

print("== a filed ticket ==")
RAW = ('<div>My order is late.</div><div><font color="#000000">Black on purpose.</font> '
       '<span style="color: rgb(255, 255, 255);">quiet white words</span> <font color="#ffffff">more white</font></div>')
code, filed = post("/submit", {"body": RAW})
check("the ticket is filed", code == 200 and "Your ticket is HC-" in filed, filed[:200])
holds_toggle("the filed page", filed)
tid = re.search(r"Your ticket is (HC-\d+)", filed).group(1)
stored = site.TICKETS[tid]
shown, text = site.clean(RAW)
check("the stored HTML is exactly what the sanitizer made of what was sent", stored["html"] == shown, stored["html"])
check("the stored text is exactly the sanitizer's text", stored["body"] == text, stored["body"])
check("the stored ticket carries no trace of the toggle",
      "reveal" not in json.dumps(stored) and "Show hidden text" not in json.dumps(stored))
code, page = get(f"/{tid}")
holds_toggle(f"/{tid}", page)
check(f"/{tid} shows the stored HTML as it was", stored["html"] in page)
code, me = get("/me")
holds_toggle("/me", me)
check("/me lists the filed ticket", tid in me)

print("== what the bot reads is unchanged ==")
for t in ("HC-666", "HC-7731", tid):
    code, body = get(f"/ticket?id={t}")
    data = json.loads(body) if code == 200 else {}
    want = SEEDED.get(t, stored)
    check(f"/ticket?id={t} answers the same five fields, as stored", code == 200
          and data == {k: want[k] for k in ("id", "subject", "status", "customer", "body")}, body[:200])
    check(f"/ticket?id={t} is JSON with no toggle", "reveal" not in body and "Show hidden text" not in body)
check("HC-666's stored HTML and text are as seeded",
      site.TICKETS["HC-666"] == SEEDED["HC-666"]
      and site.TICKETS["HC-666"]["html"] == (f"<p>{html.escape(site._ROOM_COMPLAINT)}</p><p><span style=\"color:#ffffff\">"
                                             f"{html.escape(site.ROOM_PAYLOAD)}</span></p>"))
check("the sanitizer still keeps a colour and names no toggle",
      site.clean('<span style="color:white">x</span>')[0] == '<span style="color:#ffffff">x</span>'
      and "reveal" not in site.clean(f"<p>{site.REVEAL_BAR}</p>")[0])

print("== pages that show no ticket stay as they were ==")
for path in ("/wall",):
    code, page = get(path)
    check(f"{path} carries no button", code == 200 and 'id="reveal"' not in page)
check("the deployments page carries no button", 'id="reveal"' not in site.deployments_page())

srv.shutdown()
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    raise SystemExit(1)
print("All support-desk 'Show hidden text' checks passed.")
