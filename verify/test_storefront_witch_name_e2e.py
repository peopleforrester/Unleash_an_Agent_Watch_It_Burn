# ABOUTME: Runs the storefront's own witch-name code in node with the support desk's real cookie, so the chat page is
# ABOUTME: proven to show the desk's name as plain text, and to assign a name the desk accepts on a first visit (#685, #762).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The desk (gitops/ai-layer/ticket_site.py) hands each browser a generated name in the wib_witch cookie on
.burritobot.co. The chat page on the same domain reads it. Here the cookie comes from the real desk: the ticket site
runs on localhost, its Set-Cookie value is fed to the page's witch-name code, cut from burritbot.html, in a node vm
with a stub element, and the name the desk gave is read from its /me page.

Since #763 the name is plain text with no link to the desk, and since #762 a visitor with no name, or with a cookie
the vocabulary did not make, gets a fresh one from the page itself, written back to wib_witch for the desk to read.

Needs node. A missing node is a failure, not a skip. Nothing here touches the network or a cluster.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
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

start = PAGE.find("  var WITCH_FIRST=")
end = PAGE.find("  greet();", start)
if start < 0 or end < 0 or "(function witchName(){" not in PAGE[start:end]:
    print("FAILED: no witch-name vocabulary and witchName block before greet() in burritbot.html to execute")
    sys.exit(1)
BLOCK = PAGE[start:end]

spec = importlib.util.spec_from_file_location("ticket_site_witch", REPO / "gitops/ai-layer/ticket_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
site.Handler.log_message = lambda *a: None
srv = ThreadingHTTPServer(("127.0.0.1", 0), site.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
DESK_HEADERS = {"Host": "support-attackme.burritobot.co", "User-Agent": "phone", "X-Forwarded-For": "203.0.113.9"}
req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/", headers=DESK_HEADERS)
with urllib.request.urlopen(req, timeout=5) as r:
    set_cookie = r.headers["Set-Cookie"] or ""
cookie = set_cookie.split(";", 1)[0]
req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/me", headers={**DESK_HEADERS, "Cookie": cookie})
with urllib.request.urlopen(req, timeout=5) as r:
    me_page = r.read().decode()
srv.shutdown()
if 'id="witch-name">' not in me_page:
    print("FAILED: the desk's /me page shows no witch-name element to read the given name from")
    sys.exit(1)
given = me_page.split('id="witch-name">', 1)[1].split("<", 1)[0]

HARNESS = r"""
const vm = require('vm');
const [src, cases] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = cases.map(([host, cookie, draws]) => {
  const el = {hidden: true, textContent: '', href: '', removeAttribute(a) { this[a] = ''; }};
  // Every Math.random the page calls is one of this case's pinned draws, so no result depends on the run.
  const left = draws.slice();
  const M = Object.assign(Object.create(Math), {random: () => {
    if (!left.length) throw new Error('the page drew more random values than this case pinned');
    return left.shift();
  }});
  const ctx = {location: {hostname: host}, Math: M,
               document: {cookie, getElementById: (id) => id === 'witch' ? el : null}};
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  return {hidden: el.hidden, textContent: el.textContent, href: el.href, cookie: ctx.document.cookie,
          sent: ctx.WITCH_NAME};
});
process.stdout.write(JSON.stringify(out));
"""


def draws(i: int) -> list[float]:
    """The two Math.random values that make randWitch() pick first name i and creature i, wrapping (#797)."""
    return [(i % len(site.FIRST) + 0.5) / len(site.FIRST), (i % len(site.CREATURES) + 0.5) / len(site.CREATURES)]


# A name drawn at random once made a check fail one run in 32 (#583: "Prudence" contains "rude"). Each case pins its
# draws instead, and the replaced cookie is tried once per first name, so every first name and every creature the page
# can pick is checked on every run. A case that pins no draws also proves the page draws none.
CASES = [
    ("attackme.burritobot.co", f"other=1; {cookie}", []),
    ("attackme.burritobot.co", "other=1", draws(0)),
    ("attackme.agenticburn.com", cookie, []),
    ("burritobot-private.burritobot.co", cookie, []),
] + [("attackme.burritobot.co", "wib_witch=big-rude-word", draws(i)) for i in range(len(site.FIRST))]
r = subprocess.run(["node", "-e", HARNESS], input=json.dumps([BLOCK, CASES]), capture_output=True, text=True)
if r.returncode != 0:
    print(f"FAILED: node exited {r.returncode}: {r.stderr[-400:]}")
    sys.exit(1)
named, none, other_domain, private, *rude_cases = json.loads(r.stdout)



def written_name(case: dict) -> str | None:
    """The name the page wrote back to wib_witch, as the desk reads it, or None when it wrote none it accepts."""
    if not case["cookie"].startswith("wib_witch="):
        return None
    return site.name_from_slug(case["cookie"].split(";", 1)[0].split("=", 1)[1])


print("== the chat page shows the name the desk gave this browser, as plain text (#685, #763) ==")
check("the desk set wib_witch on .burritobot.co", "Domain=.burritobot.co" in set_cookie, set_cookie)
check("the page shows that exact name", not named["hidden"] and named["textContent"].endswith(f"You are {given}"),
      f"{given!r} / {named['textContent']!r}")
check("and sends that name with each /chat call", named["sent"] == given, repr(named["sent"]))
check("and links nowhere", named["href"] == "", named["href"])
check("and keeps the desk's cookie as it was", named["cookie"] == f"other=1; {cookie}", named["cookie"])
check("the private bot shows the same name, with no link", not private["hidden"]
      and private["textContent"].endswith(f"You are {given}") and private["href"] == "", repr(private))

print("== without a name the page assigns one the desk accepts; off the domain it shows nothing (#762) ==")
fresh = written_name(none)
check("no cookie: the page writes a vocabulary name to wib_witch", fresh is not None, none["cookie"])
check("on .burritobot.co, for the desk to read", "; Domain=.burritobot.co" in none["cookie"], none["cookie"])
check("and shows and sends that name", not none["hidden"] and none["textContent"].endswith(f"You are {fresh}")
      and none["sent"] == fresh, repr(none))
check("no cookie: the name is the one the pinned draws pick", fresh == f"{site.FIRST[0]} the {site.CREATURES[0]}",
      repr(fresh))
# The bad cookie's words, not the bare "rude": a vocabulary name such as "Prudence the Pixie" contains "rude".
bad = []
for i, rude in enumerate(rude_cases):
    replaced = written_name(rude)
    if not (replaced == f"{site.FIRST[i]} the {site.CREATURES[i % len(site.CREATURES)]}"
            and "big-rude-word" not in rude["cookie"] and "rude word" not in rude["textContent"].lower()
            and rude["textContent"].endswith(f"You are {replaced}")):
        bad.append(repr(rude))
check(f"a cookie that is not a generated name is replaced with one, for each of the {len(site.FIRST)} first names"
      " (Prudence among them)", len(rude_cases) == len(site.FIRST) and not bad, "; ".join(bad[:3]))
check("agenticburn.com shows nothing (the cookie is not sent there)", other_domain["hidden"] is True
      and other_domain["sent"] == "", repr(other_domain))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The chat page shows the support desk's name for this browser, and assigns one the desk accepts.")
