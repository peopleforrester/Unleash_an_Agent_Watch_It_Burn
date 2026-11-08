# ABOUTME: Holds #1179: on a Host of deployments-burritobot-private.*, the deployments page and its per-witch view open
# ABOUTME: with the red private (administrator) banner from the desk's helper; on any other Host they render as before.
"""The real ticket site (gitops/ai-layer/ticket_site.py) runs on localhost and is driven over HTTP with the Host header
the console passes on. No cluster, no model.

deployments.burritobot.co (deck slide #/46) and the private cluster's deployments-burritobot-private.burritobot.co
(#/47) served the same page. On the private Host the page (`/`) and its per-witch view (`/mine`, with a witch named,
with only the cookie, and with no name at all) now open with the banner "This is the private (administrator)
deployments page.", built by the support desk's helper (private_banner, #1178) in its .combanner style. Each view is
checked on its own:

- on the private Host (and the same Host with a port or in capitals), the sentence is there once, inside the
  .combanner div, with the desk's own BANNER_STYLE, before the page's heading, and the page with the banner taken out is
  the public page;
- on deployments.burritobot.co, on the community cluster's deployments-<label> Host, on a lookalike and with no Host,
  the view carries neither the sentence nor the .combanner class, and on each deployments Host it answers 200 and is
  the page rendered with no banner (the lookalike and no Host reach the desk, where /mine is a 404);
- /deployments.json, on the private Host and on the chat page's own host, is the same JSON as on the public Host, and
  the support desk's private Host still gets the desk's banner, not this one.
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import pathlib
import sys
import threading
from http.server import ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parent.parent
SENTENCE = "This is the private (administrator) deployments page."
PRIVATE = "deployments-burritobot-private.burritobot.co"
PUBLIC = "deployments.burritobot.co"
WITCH = "Edgar the Kelpie"
WITCH_SLUG = "edgar-the-kelpie"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


spec = importlib.util.spec_from_file_location("ticket_site_deploy_banner", REPO / "gitops/ai-layer/ticket_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
site.Handler.log_message = lambda *a: None
srv = ThreadingHTTPServer(("127.0.0.1", 0), site.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

if site.name_from_slug(WITCH_SLUG) != WITCH:
    print(f"FAIL: name_from_slug({WITCH_SLUG!r}) is not {WITCH!r} in gitops/ai-layer/ticket_site.py; the per-witch "
          "checks name that witch", file=sys.stderr)
    sys.exit(1)


def get(path: str, host: str | None, cookie: str = "") -> tuple[int, str]:
    """GET a page as the console forwards it; host None sends no Host header at all."""
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    try:
        conn.putrequest("GET", path, skip_host=True)
        if host is not None:
            conn.putheader("Host", host)
        if cookie:
            conn.putheader("Cookie", cookie)
        conn.putheader("User-Agent", "deployments-banner-test")
        conn.endheaders()
        r = conn.getresponse()
        return r.status, r.read().decode()
    finally:
        conn.close()


BANNER = site.private_banner("deployments page")
# Each view as (label, path, cookie, the page rendered with no banner).
VIEWS = [
    ("the deployments page /", "/", "", site.deployments_page()),
    ("/mine?witch=<slug>", f"/mine?witch={WITCH_SLUG}", "", site.mine_page(WITCH)),
    ("/mine with only the cookie", "/mine", f"wib_witch={WITCH_SLUG}", site.mine_page(WITCH)),
    ("/mine with no name", "/mine", "", site.mine_page(None)),
]

print("== the helper ==")
check("the deployments banner is the desk's helper naming the deployments page",
      site.deployments_banner(PRIVATE) == BANNER, site.deployments_banner(PRIVATE))
check("the banner carries the issue's sentence", SENTENCE in BANNER, BANNER)
check("the banner is one .combanner div", BANNER.count('class="combanner"') == 1, BANNER)
check("the banner carries the desk's .combanner style", f"<style>{site.BANNER_STYLE}</style>" in BANNER, BANNER)
for value in ("#C62222", "#8E1414", "#fff", "font-weight:800"):
    check(f"the style holds {value}", value in site.BANNER_STYLE, site.BANNER_STYLE)
check("the desk's banner is unchanged by this one", site.desk_banner("support-burritobot-private.burritobot.co")
      == site.private_banner("support desk"))
check("the deployments banner is empty on the public Host", site.deployments_banner(PUBLIC) == "")
check("the deployments banner is empty on the private desk's Host",
      site.deployments_banner("support-burritobot-private.burritobot.co") == "")

for label, path, cookie, plain in VIEWS:
    print(f"== {label} ==")
    for host in (PRIVATE, f"{PRIVATE}:443", PRIVATE.upper(), "deployments-burritobot-private.agenticburn.com"):
        status, body = get(path, host, cookie)
        check(f"{label} on Host {host} answers 200", status == 200, str(status))
        check(f"{label} on Host {host} shows the banner once", body.count(SENTENCE) == 1, body[:300])
        check(f"{label} on Host {host} shows it in the .combanner div",
              f'<div class="combanner" id="privatebanner">{SENTENCE}</div>' in body, body[:300])
        check(f"{label} on Host {host}: the banner is at the top, before the page's heading",
              SENTENCE in body and "<h1>" in body and body.index(SENTENCE) < body.index("<h1>"), body[:300])
        check(f"{label} on Host {host}: taking the banner out leaves the public page",
              body.replace(BANNER, "", 1) == plain)
    for host in (PUBLIC, "deployments-watch-it-burn-community.burritobot.co",
                 "deployments-burritobot-private-x.burritobot.co", "deployments-burritobot-privatex.burritobot.co",
                 "burritobot-private.burritobot.co", None):
        hostlabel = "no Host" if host is None else f"Host {host}"
        status, body = get(path, host, cookie)
        check(f"{label} with {hostlabel} shows no banner", SENTENCE not in body and "combanner" not in body,
              body[:300])
        # A Host that is not a deployments one is the support desk's (DEPLOYMENTS_HOST), where /mine is a 404.
        if host is not None and site.DEPLOYMENTS_HOST.match(host):
            check(f"{label} with {hostlabel} answers 200", status == 200, str(status))
            check(f"{label} with {hostlabel} is the page as it was", body == plain, body[:300])

print("== /deployments.json ==")
site.record_landing("deploy-banner-probe", True, "", "ghcr.io/example/tron:1", WITCH, "Deployment", None)
_, public_json = get("/deployments.json", PUBLIC)
for host in (PRIVATE, "burritobot-private.burritobot.co", "burritobot.co"):
    status, body = get("/deployments.json", host)
    check(f"/deployments.json on Host {host} answers 200", status == 200, str(status))
    check(f"/deployments.json on Host {host} is the public JSON, with no banner",
          body == public_json and "combanner" not in body, body[:300])
check("the probe deployment is in the JSON", any(r["name"] == "deploy-banner-probe" for r in json.loads(public_json)),
      public_json[:300])

print("== the support desk keeps its own banner ==")
status, body = get("/", "support-burritobot-private.burritobot.co")
check("the private desk shows the desk's sentence, not this one",
      "This is the private (administrator) support desk." in body and SENTENCE not in body, body[:300])

srv.shutdown()
if failures:
    print(f"\n{len(failures)} check(s) failed:", *failures, sep="\n  ")
    sys.exit(1)
print("\nOK: the private deployments page's banner shows on / and /mine on the private Host only")
