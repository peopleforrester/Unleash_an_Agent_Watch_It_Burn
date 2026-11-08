# ABOUTME: Holds #1178: on a Host of support-burritobot-private.*, the desk, /wall and /me open with the red private
# ABOUTME: (administrator) banner in the chat page's .combanner look; on any other Host they render as before.
"""The real ticket site (gitops/ai-layer/ticket_site.py) runs on localhost and is driven over HTTP with the Host header
the console passes on (console.conf sets `proxy_set_header Host $host` on the support server). No cluster, no model.

support.burritobot.co and the private cluster's support-burritobot-private.burritobot.co served the same pages. The
desk now reads the Host and, on the private one, puts one banner at the top of `/`, `/wall` and `/me`, built by one
helper (private_banner) so the deployments page can reuse it. Each page is checked on its own:

- on the private Host (and the same Host with a port or in capitals), the banner's sentence is there once, inside the
  .combanner div, before the page's heading, and the page with the banner taken out is the public page;
- on support.burritobot.co, on a lookalike Host and with no Host at all, the page carries neither the sentence nor the
  .combanner class, and is the page rendered with no banner;
- the helper's style holds the chat page's .combanner declarations, read from gitops/ai-layer/web/burritbot.html, and
  the values the issue names: bold white text on #C62222, a #8E1414 border, rounded corners.
"""
from __future__ import annotations

import http.client
import importlib.util
import pathlib
import re
import sys
import threading
from http.server import ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parent.parent
CHAT_PAGE = REPO / "gitops/ai-layer/web/burritbot.html"
SENTENCE = "This is the private (administrator) support desk."
PRIVATE = "support-burritobot-private.burritobot.co"
PUBLIC = "support.burritobot.co"
# A visitor who already holds a name, so /me renders the same page on every request.
COOKIE = "wib_witch=edgar-the-kelpie"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


spec = importlib.util.spec_from_file_location("ticket_site_banner", REPO / "gitops/ai-layer/ticket_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
site.Handler.log_message = lambda *a: None
srv = ThreadingHTTPServer(("127.0.0.1", 0), site.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(path: str, host: str | None) -> tuple[int, str]:
    """GET a page as the console forwards it; host None sends no Host header at all."""
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    try:
        conn.putrequest("GET", path, skip_host=True)
        if host is not None:
            conn.putheader("Host", host)
        conn.putheader("Cookie", COOKIE)
        conn.putheader("User-Agent", "banner-test")
        conn.endheaders()
        r = conn.getresponse()
        return r.status, r.read().decode()
    finally:
        conn.close()


# The pages as rendered with no banner: what every Host but the private one must get, byte for byte.
PLAIN = {"/": site.desk(), "/wall": site.wall_page(), "/me": site.me_page("Edgar the Kelpie")}
BANNER = site.private_banner("support desk")

print("== the helper ==")
check("private_banner names the page it is given",
      "This is the private (administrator) deployments page." in site.private_banner("deployments page"))
check("the desk's banner carries the issue's sentence", SENTENCE in BANNER, BANNER)
check("the banner is one .combanner div", BANNER.count('class="combanner"') == 1, BANNER)
check("the banner carries its own style", f"<style>{site.BANNER_STYLE}</style>" in BANNER, BANNER)
check("the module's WALL is still the wall with no banner", site.WALL == PLAIN["/wall"])

print("== the style is the chat page's .combanner ==")
chat = CHAT_PAGE.read_text()
m = re.search(r"\.combanner\{([^}]*)\}", chat)
if m is None:
    print(f"FAIL: the literal `.combanner{{` is not in {CHAT_PAGE.relative_to(REPO)}; the style check reads the chat "
          "page's rule from there", file=sys.stderr)
    sys.exit(1)


def decls(body: str) -> dict[str, str]:
    out = {}
    for part in body.split(";"):
        k, _, v = part.partition(":")
        if k.strip():
            out[k.strip()] = " ".join(v.split())
    return out


chat_decls = decls(m.group(1))
ours = re.fullmatch(r"\.combanner\{([^}]*)\}", site.BANNER_STYLE)
check("BANNER_STYLE is one .combanner rule", ours is not None, site.BANNER_STYLE)
our_decls = decls(ours.group(1)) if ours else {}
check("the desk's banner has every declaration of the chat page's .combanner", our_decls == chat_decls,
      f"desk {our_decls} vs chat page {chat_decls}")
weight = our_decls.get("font-weight", "")
check("bold text", weight == "bold" or (weight.isdigit() and int(weight) >= 700), weight)
check("white text", our_decls.get("color", "").lower() in ("#fff", "#ffffff", "white"), our_decls.get("color", ""))
check("on #C62222", our_decls.get("background", "").upper() == "#C62222", our_decls.get("background", ""))
check("a #8E1414 border", "#8E1414" in our_decls.get("border", "").upper(), our_decls.get("border", ""))
radius = our_decls.get("border-radius", "")
check("rounded corners", bool(re.fullmatch(r"[1-9]\d*(px|rem|em)", radius)), radius)

for path in ("/", "/wall", "/me"):
    print(f"== {path} ==")
    for host in (PRIVATE, f"{PRIVATE}:443", PRIVATE.upper(), "support-burritobot-private.agenticburn.com"):
        status, body = get(path, host)
        check(f"{path} on Host {host} answers 200", status == 200, str(status))
        check(f"{path} on Host {host} shows the banner once", body.count(SENTENCE) == 1, body[:300])
        check(f"{path} on Host {host} shows it in the .combanner div",
              f'<div class="combanner" id="privatebanner">{SENTENCE}</div>' in body, body[:300])
        check(f"{path} on Host {host}: the banner is at the top, before the page's heading",
              SENTENCE in body and "<h1>" in body and body.index(SENTENCE) < body.index("<h1>"), body[:300])
        check(f"{path} on Host {host}: taking the banner out leaves the public page",
              body.replace(BANNER, "", 1) == PLAIN[path])
    for host in (PUBLIC, "support-burritobot-private-x.burritobot.co", "support-watch-it-burn-private.burritobot.co",
                 "burritobot-private.burritobot.co", None):
        label = "no Host" if host is None else f"Host {host}"
        status, body = get(path, host)
        check(f"{path} with {label} answers 200", status == 200, str(status))
        check(f"{path} with {label} shows no banner", SENTENCE not in body and "combanner" not in body, body[:300])
        check(f"{path} with {label} is the page as it was", body == PLAIN[path], body[:300])

srv.shutdown()
if failures:
    print(f"\n{len(failures)} check(s) failed:", *failures, sep="\n  ")
    sys.exit(1)
print("\nOK: the private desk's banner shows on /, /wall and /me on the private Host only")
