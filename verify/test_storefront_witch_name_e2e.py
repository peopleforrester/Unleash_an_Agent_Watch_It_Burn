# ABOUTME: Runs the storefront's own witchName block in node with the support desk's real cookie, so the chat page is
# ABOUTME: proven to show the name the desk gave this browser and link to that visitor's Jokers (#685).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The desk (gitops/ai-layer/ticket_site.py) hands each browser a generated name in the wib_witch cookie on
.burritobot.co. The chat page on the same domain reads it. Here the cookie comes from the real desk: the ticket site
runs on localhost and its Set-Cookie value is fed to the page's block, cut from burritbot.html, in a node vm with a
stub element.

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

start = PAGE.find("  (function witchName(){")
end = PAGE.find("  greet();", start)
if start < 0 or end < 0:
    print("FAILED: no witchName block before greet() in burritbot.html to execute")
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
    desk_page = r.read().decode()
srv.shutdown()
cookie = set_cookie.split(";", 1)[0]
given = desk_page.split('id="witch-name">', 1)[1].split("<", 1)[0]

HARNESS = r"""
const vm = require('vm');
const [src, cases] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = cases.map(([host, cookie]) => {
  const el = {hidden: true, textContent: '', href: ''};
  const ctx = {location: {hostname: host}, document: {cookie, getElementById: (id) => id === 'witch' ? el : null}};
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  return el;
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

print("== the chat page shows the name the desk gave this browser (#685) ==")
check("the desk set wib_witch on .burritobot.co", "Domain=.burritobot.co" in set_cookie, set_cookie)
check("the page shows that exact name", not named["hidden"] and f"You are {given} " in named["textContent"],
      f"{given!r} / {named['textContent']!r}")
check("and links to this cluster's desk /me", named["href"] == "https://support-attackme.burritobot.co/me", named["href"])
check("the private bot links to its own desk", private["href"] == "https://support-burritobot-private.burritobot.co/me")
print("== without a name, the page points at the desk; off the domain, it shows nothing ==")
check("no cookie: a link to get a name", not none["hidden"] and "Get your witch name" in none["textContent"]
      and none["href"] == "https://support-attackme.burritobot.co/")
check("a cookie that is not a generated name is not shown", "rude" not in rude["textContent"]
      and "Get your witch name" in rude["textContent"])
check("agenticburn.com shows nothing (the cookie is not sent there)", other_domain["hidden"] is True)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The chat page shows the support desk's name for this browser.")
