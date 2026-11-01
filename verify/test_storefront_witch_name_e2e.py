# ABOUTME: Runs the storefront's own witch-name block in node with the support desk's real cookie, so the chat page is
# ABOUTME: proven to show the name the desk gave this browser, assign one on a first visit, and link nowhere (#685, #762, #763).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The desk (gitops/ai-layer/ticket_site.py) hands each browser a generated name in the wib_witch cookie on
.burritobot.co, and the chat page on the same domain reads it. Since #762 the page also assigns a name itself on a
first visit, from the same vocabulary, and sets the same cookie; since #763 it shows the name as plain text with no
link. Here the cookie comes from the real desk: the ticket site runs on localhost, its Set-Cookie value is fed to the
page's block, cut from burritbot.html, in a node vm with a stub element, and the name it shows is checked against
the one the desk's /me page prints for that cookie.

Needs node. A missing node is a failure, not a skip. Nothing here touches the network or a cluster.
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
import urllib.request
from http.server import ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("node") is None:
    print("FAILED: node is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)

# The block runs from the vocabulary (#762 moved the helpers witchFromSlug, randWitch and setWitchCookie ahead of
# the witchName function) to the greet() call that follows it.
start = PAGE.find("  var WITCH_FIRST=[")
end = PAGE.find("  greet();", start)
if start < 0 or end < 0 or "(function witchName(){" not in PAGE[start:end]:
    print("FAILED: no witch vocabulary and witchName block before greet() in burritbot.html to execute")
    sys.exit(1)
BLOCK = PAGE[start:end]

spec = importlib.util.spec_from_file_location("ticket_site_witch", REPO / "gitops/ai-layer/ticket_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
site.Handler.log_message = lambda *a: None
srv = ThreadingHTTPServer(("127.0.0.1", 0), site.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/",
                             headers={"Host": "support-attackme.burritobot.co", "User-Agent": "phone",
                                      "X-Forwarded-For": "203.0.113.9"})
with urllib.request.urlopen(req, timeout=5) as r:
    set_cookie = r.headers["Set-Cookie"]
    r.read()
cookie = set_cookie.split(";", 1)[0]
# The front page sets the cookie but no longer prints the name (#764); /me does, for the cookie it is sent. Reading it
# there, with the cookie the front page set, is what proves the desk's name is the one this browser carries.
me = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/me",
                            headers={"Host": "support-attackme.burritobot.co", "Cookie": cookie})
with urllib.request.urlopen(me, timeout=5) as r:
    me_page = r.read().decode()
srv.shutdown()
if 'id="witch-name">' not in me_page:
    print("FAILED: the desk's /me page shows no witch-name for the cookie the front page set")
    sys.exit(1)
given = me_page.split('id="witch-name">', 1)[1].split("<", 1)[0]

# The stub element records the attributes the block strips (#763) and the cookie the block writes (#762).
HARNESS = r"""
const vm = require('vm');
const [src, cases] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = cases.map(([host, cookie]) => {
  const el = {hidden: true, textContent: '', href: 'https://example.invalid/', removed: [],
              removeAttribute(a) { this.removed.push(a); if (a === 'href') this.href = ''; }};
  const document = {cookie, getElementById: (id) => id === 'witch' ? el : null};
  const ctx = {location: {hostname: host}, document};
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  return {hidden: el.hidden, textContent: el.textContent, href: el.href, removed: el.removed, cookie: document.cookie};
});
process.stdout.write(JSON.stringify(out));
"""
CASES = [
    ("attackme.burritobot.co", f"other=1; {cookie}"),
    ("attackme.burritobot.co", "other=1"),
    ("attackme.agenticburn.com", cookie),
    ("burritobot-private.burritobot.co", cookie),
    ("attackme.burritobot.co", "wib_witch=big-rude-word"),
]
r = subprocess.run(["node", "-e", HARNESS], input=json.dumps([BLOCK, CASES]), capture_output=True, text=True)
if r.returncode != 0:
    print(f"FAILED: node exited {r.returncode}: {r.stderr[-400:]}")
    sys.exit(1)
named, none, other_domain, private, rude = json.loads(r.stdout)
SHOWN = re.compile(r"You are ([A-Z][a-z]+ the [A-Z][a-z]+)$")


def shown_name(el: dict) -> str | None:
    """The name the block put on the element, if it is one the desk's vocabulary makes."""
    m = SHOWN.search(el["textContent"])
    return m.group(1) if m and site.name_from_slug(site.slug(m.group(1))) == m.group(1) else None


def assigned_cookie(el: dict) -> str | None:
    """The slug the block wrote into wib_witch on .burritobot.co, if it did."""
    m = re.search(r"wib_witch=([a-z]+-the-[a-z]+); Path=/; Max-Age=172800; SameSite=Lax; Domain=\.burritobot\.co$",
                  el["cookie"])
    return m.group(1) if m else None


print("== the chat page shows the name the desk gave this browser (#685) ==")
check("the desk set wib_witch on .burritobot.co", "Domain=.burritobot.co" in set_cookie, set_cookie)
check("the page shows that exact name", not named["hidden"] and shown_name(named) == given,
      f"{given!r} / {named['textContent']!r}")
check("and keeps the desk's cookie rather than writing its own", named["cookie"] == f"other=1; {cookie}", named["cookie"])
check("the private bot shows the same name for the same cookie", shown_name(private) == given, private["textContent"])
print("== the name is plain text: no link to the desk (#763) ==")
for label, el in (("with the desk's cookie", named), ("without a cookie", none)):
    check(f"{label}: href, target and rel are stripped and no href is set",
          el["href"] == "" and {"href", "target", "rel"} <= set(el["removed"]), f"{el['href']!r} {el['removed']}")
print("== without a name, the page assigns one from the desk's vocabulary and sets the cookie (#762) ==")
check("no cookie: a vocabulary name is shown", not none["hidden"] and shown_name(none) is not None, none["textContent"])
check("no cookie: wib_witch is set on .burritobot.co to that name's slug",
      shown_name(none) is not None and assigned_cookie(none) == site.slug(shown_name(none)), none["cookie"])
check("a cookie that is not a generated name is replaced, not shown",
      "rude" not in rude["textContent"] and shown_name(rude) is not None
      and assigned_cookie(rude) == site.slug(shown_name(rude)), f"{rude['textContent']!r} {rude['cookie']!r}")
check("agenticburn.com shows nothing and sets nothing (the cookie is not sent there)",
      other_domain["hidden"] is True and other_domain["cookie"] == cookie, other_domain["cookie"])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The chat page shows the support desk's name for this browser, assigns one on a first visit, and links nowhere.")
