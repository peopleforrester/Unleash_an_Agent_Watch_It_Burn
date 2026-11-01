# ABOUTME: Runs the storefront's own witch-name code in node with the support desk's real cookie: the chat page shows the
# ABOUTME: desk's name as plain text, and a visitor with no name is given one from the desk's vocabulary (#685, #762, #763).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The desk (gitops/ai-layer/ticket_site.py) hands each browser a generated name in the wib_witch cookie on
.burritobot.co. The chat page on the same domain reads it, and since #762 a visitor without one is given a name by the
page itself, which sets the same cookie. Since #763 the name is plain text, never a link to the desk. Here the cookie
comes from the real desk: the ticket site runs on localhost and its Set-Cookie value is fed to the page's witch-name
code (the vocabulary, its helpers and the witchName block, cut from burritbot.html) in a node vm with stub elements.

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
    desk_page = r.read().decode()
srv.shutdown()
cookie = set_cookie.split(";", 1)[0]
given = desk_page.split('id="witch-name">', 1)[1].split("<", 1)[0]

HARNESS = r"""
const vm = require('vm');
const [src, cases] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = cases.map(([host, cookie]) => {
  const el = {hidden: true, textContent: '', attrs: ['href', 'target', 'rel'],
              removeAttribute(a) { this.attrs = this.attrs.filter((x) => x !== a); }};
  const btn = {hidden: true, click: null, addEventListener(ev, fn) { if (ev === 'click') this.click = fn; }};
  const written = [];
  const document = {getElementById: (id) => (id === 'witch' ? el : id === 'newwitch' ? btn : null)};
  Object.defineProperty(document, 'cookie', {get: () => cookie, set: (v) => written.push(v)});
  const ctx = {location: {hostname: host}, document, Math};
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  const first = {hidden: el.hidden, text: el.textContent, attrs: el.attrs, button: !btn.hidden,
                 sent: ctx.WITCH_NAME, written: written.slice()};
  let reroll = null;
  if (btn.click) { btn.click(); reroll = {text: el.textContent, sent: ctx.WITCH_NAME, written: written.slice(first.written.length)}; }
  return {...first, reroll};
});
process.stdout.write(JSON.stringify(out));
"""
CASES = [
    ("attackme.burritobot.co", f"other=1; {cookie}"),
    ("attackme.burritobot.co", "other=1"),
    ("attackme.agenticburn.com", cookie),
    ("burritobot-private.burritobot.co", cookie),
    ("attackme.burritobot.co", "wib_witch=big-the-rude"),
]
r = subprocess.run(["node", "-e", HARNESS], input=json.dumps([BLOCK, CASES]), capture_output=True, text=True)
if r.returncode != 0:
    print(f"FAILED: node exited {r.returncode}: {r.stderr[-400:]}")
    sys.exit(1)
named, none, other_domain, private, rude = json.loads(r.stdout)
FIRST, CREATURES = set(site.FIRST), set(site.CREATURES)


def from_vocab(name: str) -> bool:
    first, _, creature = name.partition(" the ")
    return first in FIRST and creature in CREATURES


def sets_cookie_for(written: list[str], name: str) -> bool:
    slug = name.lower().replace(" ", "-")
    return len(written) == 1 and written[0].startswith(f"wib_witch={slug};") and "Domain=.burritobot.co" in written[0]


print("== the chat page shows the name the desk gave this browser, as plain text (#685, #763) ==")
check("the desk set wib_witch on .burritobot.co", "Domain=.burritobot.co" in set_cookie, set_cookie)
check("the page shows that exact name", not named["hidden"] and named["text"].endswith(f"You are {given}"),
      f"{given!r} / {named['text']!r}")
check("and sends it to the bot with each /chat call", named["sent"] == given, named["sent"])
check("the name is not a link: href, target and rel are removed", named["attrs"] == [], str(named["attrs"]))
check("the desk's cookie is kept, not replaced", named["written"] == [], str(named["written"]))
check("the private bot shows the same name, unlinked", private["text"] == named["text"] and private["attrs"] == [])
print("== without a desk name, the page gives one from the desk's vocabulary (#762) ==")
check("no cookie: a name from the desk's vocabulary is shown", not none["hidden"] and from_vocab(none["sent"])
      and none["text"].endswith(f"You are {none['sent']}"), none["text"])
check("and set as wib_witch on .burritobot.co, so the desk and wall use it", sets_cookie_for(none["written"], none["sent"]),
      str(none["written"]))
check("a cookie that is not a desk name is replaced by one that is", "Rude" not in rude["text"] and from_vocab(rude["sent"])
      and sets_cookie_for(rude["written"], rude["sent"]), rude["text"])
check("the re-roll button draws a name from the vocabulary and sets its cookie", named["button"] and named["reroll"] is not None
      and from_vocab(named["reroll"]["sent"]) and named["reroll"]["text"].endswith(f"You are {named['reroll']['sent']}")
      and sets_cookie_for(named["reroll"]["written"], named["reroll"]["sent"]), str(named["reroll"]))
check("agenticburn.com shows nothing and sets no cookie", other_domain["hidden"] is True and other_domain["written"] == []
      and not other_domain["button"])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The chat page shows the support desk's name for this browser, or gives it one from the same vocabulary.")
