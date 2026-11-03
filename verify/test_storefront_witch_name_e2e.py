# ABOUTME: Runs the storefront's own witch-name code in node against the real support desk, so the chat page is proven
# ABOUTME: to show and send the desk's name, and that a name it assigns or re-rolls is the one the desk's /me shows (#685, #762, #802).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The desk (gitops/ai-layer/ticket_site.py) hands each browser a generated name in the wib_witch cookie on
.burritobot.co. The chat page on the same domain reads it. Here the desk is real: ticket_site.py runs on localhost
for the whole test. The page's witch-name code and its send(), cut from burritbot.html, run in a node vm with stub
elements, a stub /chat fetch and a cookie store that behaves as a browser's does for these cookies (keyed by name,
domain and path; a Domain the page is not under is dropped; a host is sent only the cookies whose domain it is
under). The desk's Set-Cookie seeds that store, and the Cookie header the store would send the desk goes back to the
desk's /me, whose witch-name element is the name the desk uses.

Since #763 the name is plain text with no link to the desk, and since #762 a visitor with no name, or with a cookie
the vocabulary did not make, gets a fresh one from the page itself, written back to wib_witch for the desk to read.
Since #802 the test clicks the "Get a new witch name" button: the header, the cookie, the desk's /me and the next
/chat call all move to the new name, and the button only ever shows its label.

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
LABEL = "Get a new witch name"
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
send_start = PAGE.find("  async function send(){")
send_end = PAGE.find("  // The left menu is a static reference", send_start)
if send_start < 0 or send_end < 0 or "witch:WITCH_NAME" not in PAGE[send_start:send_end]:
    print("FAILED: no send() carrying witch:WITCH_NAME in burritbot.html to execute")
    sys.exit(1)
SEND = PAGE[send_start:send_end]

spec = importlib.util.spec_from_file_location("ticket_site_witch", REPO / "gitops/ai-layer/ticket_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
site.Handler.log_message = lambda *a: None
srv = ThreadingHTTPServer(("127.0.0.1", 0), site.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
DESK_HOST = "support-attackme.burritobot.co"
DESK_HEADERS = {"Host": DESK_HOST, "User-Agent": "phone", "X-Forwarded-For": "203.0.113.9"}


def desk(path: str, cookie: str = "") -> tuple[str, str]:
    """GET a desk page as a browser on DESK_HOST: (its Set-Cookie, its body)."""
    headers = {**DESK_HEADERS, **({"Cookie": cookie} if cookie else {})}
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.headers["Set-Cookie"] or "", r.read().decode()


def desk_name(cookie: str) -> tuple[str | None, str]:
    """The name the desk's /me shows a browser sending this Cookie header, and any cookie the desk set instead."""
    set_cookie, page = desk("/me", cookie)
    if 'id="witch-name">' not in page:
        return None, set_cookie
    return page.split('id="witch-name">', 1)[1].split("<", 1)[0], set_cookie


set_cookie, _ = desk("/")
cookie = set_cookie.split(";", 1)[0]
given, _ = desk_name(cookie)
if given is None:
    srv.shutdown()
    print("FAILED: the desk's /me page shows no witch-name element to read the given name from")
    sys.exit(1)

HARNESS = r"""
const vm = require('vm');
const [block, send, deskHost, cases] = JSON.parse(require('fs').readFileSync(0, 'utf8'));

function cookieStore() {
  const rows = [];
  const under = (host, domain) => host === domain || host.endsWith('.' + domain);
  return {
    rows,
    set(raw, from) {
      const [nv, ...parts] = raw.split(';');
      const a = {};
      for (const p of parts) {
        const i = p.indexOf('=');
        a[(i < 0 ? p : p.slice(0, i)).trim().toLowerCase()] = i < 0 ? '' : p.slice(i + 1).trim();
      }
      const eq = nv.indexOf('=');
      const row = {name: nv.slice(0, eq).trim(), value: nv.slice(eq + 1).trim(), hostOnly: !('domain' in a),
                   domain: 'domain' in a ? a.domain.toLowerCase().replace(/^\./, '') : from, path: a.path || '/',
                   maxAge: a['max-age'] ?? null, sameSite: a.samesite ?? null};
      if (!under(from, row.domain)) return;
      const i = rows.findIndex(r => r.name === row.name && r.domain === row.domain && r.path === row.path);
      if (row.maxAge !== null && Number(row.maxAge) <= 0) { if (i >= 0) rows.splice(i, 1); return; }
      if (i >= 0) rows[i] = row; else rows.push(row);
    },
    header(host) {
      return rows.filter(r => r.hostOnly ? r.domain === host : under(host, r.domain))
                 .map(r => r.name + '=' + r.value).join('; ');
    },
  };
}

// An element that records every property the page writes on it, and keeps attributes apart.
function element(attrs) {
  const writes = [];
  const el = {hidden: true, textContent: '', attrs: Object.assign({}, attrs), listeners: {},
              removeAttribute(n) { delete this.attrs[n]; },
              setAttribute(n, v) { writes.push('@' + n); this.attrs[n] = String(v); },
              addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }};
  return {el: new Proxy(el, {set(o, k, v) { writes.push(String(k)); o[k] = v; return true; }}), writes};
}

async function run(c) {
  const jar = cookieStore();
  for (const [raw, from] of c.seed) jar.set(raw, from === 'desk' ? deskHost : c.host);
  // The markup's own attributes: <a id="witch" hidden target="_blank" rel="noopener"> and <button type="button">.
  const witch = element({target: '_blank', rel: 'noopener'}), btn = element({type: 'button'});
  const inp = {value: '', focus() {}, style: {}};
  const stub = () => ({textContent: '', disabled: false, style: {}, appendChild() {}, remove() {}});
  const chats = [];
  const known = {witch: witch.el, newwitch: btn.el, inp, mydeploys: null};
  const doc = {getElementById: id => id in known ? known[id] : stub(), createElement: stub};
  Object.defineProperty(doc, 'cookie', {get: () => jar.header(c.host), set: v => jar.set(String(v), c.host)});
  const ctx = {location: {hostname: c.host}, document: doc, CHAT_ENDPOINT: '/chat',
               busy: false, tokens: 0, costUsd: 0, unreachable: 0, getSession: () => 'sess-802',
               bubble() {}, save() {}, growComposer() {}, botReply() {}, noBurritos() {}, winBubble() {},
               fetch: async (url, opt) => { chats.push({url, body: JSON.parse(opt.body)});
                                            return {ok: true, json: async () => ({reply: 'ok'})}; }};
  // Every Math.random the page calls is one of this case's pinned draws, so no result depends on the run (#797).
  const left = c.draws.slice();
  const M = Object.assign(Object.create(Math), {random: () => {
    if (!left.length) throw new Error('the page drew more random values than this case pinned');
    return left.shift();
  }});
  ctx.Math = M;
  vm.createContext(ctx);
  vm.runInContext(block + send, ctx);
  const steps = [];
  for (let i = 0; i <= c.clicks; i++) {
    if (i > 0) for (const f of btn.el.listeners.click || []) f.call(btn.el, {type: 'click'});
    const before = chats.length;
    inp.value = 'one burrito, please (' + i + ')';
    await ctx.send();
    steps.push({hidden: witch.el.hidden, text: witch.el.textContent, attrs: Object.assign({}, witch.el.attrs),
                cookie: doc.cookie, store: jar.rows.map(r => Object.assign({}, r)), desk: jar.header(deskHost),
                sent: ctx.WITCH_NAME, chats: chats.slice(before)});
  }
  return {steps, unused: left.length, witchWrites: witch.writes,
          button: {hidden: btn.el.hidden, attrs: Object.assign({}, btn.el.attrs),
                   writes: btn.writes, clicks: (btn.el.listeners.click || []).length}};
}

(async () => {
  const out = [];
  for (const c of cases) out.push(await run(c));
  process.stdout.write(JSON.stringify(out));
})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""
DESK_SEED = [set_cookie, "desk"]
OTHER = ["other=1; Path=/", "page"]
# A cookie the vocabulary did not make, on the desk's domain, where only the desk or this page would have put one.
RUDE = ["wib_witch=big-rude-word; Path=/; Domain=.burritobot.co", "desk"]
N_FIRST, N_CREATURES = len(site.FIRST), len(site.CREATURES)
N_NAMES = N_FIRST * N_CREATURES


def draws(i: int) -> list[float]:
    """The two Math.random values that make randWitch() pick first name i and creature i, wrapping (#797)."""
    return [(i % N_FIRST + 0.5) / N_FIRST, (i % N_CREATURES + 0.5) / N_CREATURES]


def name_at(k: int) -> str:
    """The k-th name of the page's vocabulary, first names major, the order otherWitch() counts in."""
    return f"{site.FIRST[k // N_CREATURES]} the {site.CREATURES[k % N_CREATURES]}"


def reroll(j: int) -> float:
    """The one Math.random value that makes otherWitch() pick the j-th of the other N_NAMES - 1 names."""
    return (j + 0.5) / (N_NAMES - 1)


def case(host: str, seed: list, pinned: list[float], clicks: int = 0) -> dict:
    return {"host": host, "seed": seed, "draws": pinned, "clicks": clicks}


# A name drawn at random once made a check fail one run in 32 (#583: "Prudence" contains "rude"). Each case pins its
# draws, and the harness fails a case that draws more, so every run checks the same names; a case that pins none also
# proves the page draws none. The replaced cookie is tried once per first name, so every first name and creature the
# page can pick on a first visit is checked, and the re-roll cases reach the first and last names and the skip over
# the current one. The sweep below enumerates every re-roll from every name.
CASES = {
    "named": case("attackme.burritobot.co", [OTHER, DESK_SEED], []),
    "none": case("attackme.burritobot.co", [OTHER], draws(0)),
    "other_domain": case("attackme.agenticburn.com", [DESK_SEED], []),
    "private": case("burritobot-private.burritobot.co", [DESK_SEED], []),
    # A first visit, then three clicks on the button: to the first name, the last, and one in between.
    "reroll_fresh": case("attackme.burritobot.co", [OTHER], draws(3) + [reroll(0), reroll(N_NAMES - 2), reroll(400)],
                         3),
    # The desk's name, then one click: the page's cookie must replace the desk's, not sit beside it.
    "reroll_desk": case("burritobot-private.burritobot.co", [OTHER, DESK_SEED], [reroll(N_NAMES // 2)], 1),
    # Every draw 0.5: the old randWitch() re-roll repeats the name here, and the second click lands on the current
    # name's own index, so otherWitch() must step over it.
    "reroll_pinned": case("attackme.burritobot.co", [OTHER], [0.5, 0.5, 0.5, 0.5], 2),
}
RUDE_KEYS = [f"rude_{i}" for i in range(len(site.FIRST))]
CASES.update({key: case("attackme.burritobot.co", [RUDE], draws(i)) for i, key in enumerate(RUDE_KEYS)})


def index_of(name: str) -> int:
    first, creature = name.split(" the ")
    return site.FIRST.index(first) * N_CREATURES + site.CREATURES.index(creature)


def after(old: str, j: int) -> str:
    """The name otherWitch(old) picks on the draw reroll(j): the j-th name, counting past old."""
    return name_at(j + (j >= index_of(old)))


# The names each re-roll case must show, first visit then each click, worked out here from the pinned draws.
FIRST_FRESH = name_at(3 * N_CREATURES + 3)
MID = name_at(int(0.5 * N_FIRST) * N_CREATURES + int(0.5 * N_CREATURES))
EXPECT = {
    "reroll_fresh": [FIRST_FRESH, after(FIRST_FRESH, 0), name_at(N_NAMES - 1), after(name_at(N_NAMES - 1), 400)],
    "reroll_desk": [given, after(given, N_NAMES // 2)],
    "reroll_pinned": [MID, after(MID, int(0.5 * (N_NAMES - 1))), after(after(MID, int(0.5 * (N_NAMES - 1))),
                                                                      int(0.5 * (N_NAMES - 1)))],
}
r = subprocess.run(["node", "-e", HARNESS], input=json.dumps([BLOCK, SEND, DESK_HOST, list(CASES.values())]),
                   capture_output=True, text=True)
if r.returncode != 0:
    srv.shutdown()
    print(f"FAILED: node exited {r.returncode}: {r.stderr[-600:]}")
    sys.exit(1)
RESULTS = dict(zip(CASES, json.loads(r.stdout)))
named, none, other_domain, private = (RESULTS[k]["steps"][0] for k in ("named", "none", "other_domain", "private"))


def witch_rows(step: dict) -> list[dict]:
    return [c for c in step["store"] if c["name"] == "wib_witch"]


def written_name(step: dict) -> str | None:
    """The name in the browser's one wib_witch cookie, as the desk reads it, or None when there is not exactly one
    or the desk does not accept it."""
    rows = witch_rows(step)
    return site.name_from_slug(rows[0]["value"]) if len(rows) == 1 else None


def on_domain(step: dict, name: str) -> bool:
    """The browser holds exactly one wib_witch, on .burritobot.co for every host under it, carrying name's slug."""
    rows = witch_rows(step)
    return len(rows) == 1 and rows[0]["domain"] == "burritobot.co" and not rows[0]["hostOnly"] \
        and rows[0]["path"] == "/" and rows[0]["value"] == site.slug(name) and rows[0]["maxAge"] == "172800"


def plain(step: dict) -> bool:
    """Shown, and an anchor with no href, target or rel left: text, not a link."""
    return not step["hidden"] and step["attrs"] == {}


def shown(step: dict) -> str:
    return step["text"].split("You are ", 1)[1] if "You are " in step["text"] else ""


def chat_witch(step: dict) -> str | None:
    """The witch field of the one /chat call made at this step, or None when there was not exactly one."""
    calls = [c for c in step["chats"] if c["url"] == "/chat"]
    return calls[0]["body"].get("witch") if len(calls) == 1 else None


def desk_takes(step: dict, name: str) -> bool:
    """The real desk's /me, sent the Cookie header this browser would send it, shows name and sets no cookie."""
    seen, reset = desk_name(step["desk"])
    return seen == name and reset == ""


print("== the chat page shows the name the desk gave this browser, as plain text (#685, #763) ==")
check("the desk set wib_witch on .burritobot.co", "Domain=.burritobot.co" in set_cookie, set_cookie)
check("the page shows that exact name", plain(named) and named["text"].endswith(f"You are {given}"),
      f"{given!r} / {named['text']!r}")
check("and sends that name with each /chat call", named["sent"] == given and chat_witch(named) == given,
      repr(named["chats"]))
check("and links nowhere: no href, target or rel on the name", named["attrs"] == {}, repr(named["attrs"]))
check("and keeps the desk's cookie as it was", named["cookie"] == f"other=1; {cookie}"
      and on_domain(named, given), repr(named["store"]))
check("the desk's /me still shows that name", desk_takes(named, given), named["desk"])
check("the private bot shows the same name, with no link", plain(private)
      and private["text"].endswith(f"You are {given}") and chat_witch(private) == given, repr(private))

print("== a first visit with no cookie: the page assigns a name and the real desk takes it (#762, #802) ==")
fresh = written_name(none)
check("no cookie: the page writes a vocabulary name to wib_witch", fresh is not None, repr(none["store"]))
check("on .burritobot.co, for the desk to read", fresh is not None and on_domain(none, fresh), repr(none["store"]))
check("no cookie: the name is the one the pinned draws pick", fresh == name_at(0), repr(fresh))
check("and shows it as plain text with no link", plain(none) and shown(none) == fresh, repr(none))
check("and sends it with the /chat call", none["sent"] == fresh and chat_witch(none) == fresh, repr(none["chats"]))
check("the desk's /me then shows that same name, and sets no cookie of its own",
      fresh is not None and desk_takes(none, fresh), f"{none['desk']!r} -> {desk_name(none['desk'])!r}")

print("== a cookie the vocabulary did not make is replaced; off the domain the page shows nothing (#762) ==")
bad, unaccepted = [], []
for i, key in enumerate(RUDE_KEYS):
    rude = RESULTS[key]["steps"][0]
    replaced = written_name(rude)
    # The bad cookie's words, not the bare "rude": a vocabulary name such as "Prudence the Pixie" contains "rude".
    if not (replaced == f"{site.FIRST[i]} the {site.CREATURES[i % N_CREATURES]}"
            and "big-rude-word" not in rude["cookie"] and "rude word" not in rude["text"].lower()
            and on_domain(rude, replaced) and shown(rude) == replaced):
        bad.append(repr(rude))
    elif not desk_takes(rude, replaced):
        unaccepted.append(f"{replaced!r}: {desk_name(rude['desk'])!r}")
check(f"a cookie that is not a generated name is replaced with one, for each of the {N_FIRST} first names"
      " (Prudence among them)", len(RUDE_KEYS) == N_FIRST and "Prudence" in site.FIRST and not bad, "; ".join(bad[:3]))
check("and the desk's /me shows each replacement", not unaccepted, "; ".join(unaccepted[:3]))
check("agenticburn.com shows nothing (the cookie is not sent there)", other_domain["hidden"] is True
      and other_domain["sent"] == "" and other_domain["cookie"] == "" and chat_witch(other_domain) == "",
      repr(other_domain))
check("and writes no cookie there: the browser holds only the desk's", [c["name"] for c in other_domain["store"]]
      == ["wib_witch"] and witch_rows(other_domain)[0]["value"] == cookie.split("=", 1)[1], repr(other_domain["store"]))

print("== the 'Get a new witch name' button re-rolls the name everywhere the name is used (#762, #802) ==")
for key in ("reroll_fresh", "reroll_desk", "reroll_pinned"):
    steps = RESULTS[key]["steps"]
    check(f"{key}: the button is shown with one click handler",
          RESULTS[key]["button"]["hidden"] is False and RESULTS[key]["button"]["clicks"] == 1,
          repr(RESULTS[key]["button"]))
    for n in range(1, len(steps)):
        old, new = written_name(steps[n - 1]), written_name(steps[n])
        tag = f"{key}, click {n}"
        check(f"{tag}: the header shows a different vocabulary name, as plain text",
              new is not None and new != old and shown(steps[n]) == new and plain(steps[n]),
              f"{old!r} -> {steps[n]['text']!r}")
        check(f"{tag}: the name is {EXPECT[key][n]!r}, the one the pinned draw picks", new == EXPECT[key][n], repr(new))
        check(f"{tag}: wib_witch on .burritobot.co is replaced, not joined, by the new slug",
              new is not None and on_domain(steps[n], new) and site.slug(old or "") not in steps[n]["cookie"],
              repr(steps[n]["store"]))
        check(f"{tag}: the desk's /me then shows the new name and sets no cookie",
              new is not None and desk_takes(steps[n], new), f"{steps[n]['desk']!r} -> {desk_name(steps[n]['desk'])!r}")
        check(f"{tag}: the next /chat call carries the new name",
              steps[n]["sent"] == new and chat_witch(steps[n]) == new, repr(steps[n]["chats"]))
SWEEP = r"""
const vm = require('vm');
const [block, names] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
let k = 0;
const M = Object.assign(Object.create(Math), {random: () => (k + 0.5) / (names.length - 1)});
const ctx = {location: {hostname: 'off.example'}, Math: M, document: {cookie: '', getElementById: () => null}};
vm.createContext(ctx);
vm.runInContext(block, ctx);
const bad = [];
for (const old of names) {
  const seen = new Set();
  for (k = 0; k < names.length - 1; k++) seen.add(ctx.otherWitch(old));
  if (seen.has(old) || seen.size !== names.length - 1 || [...seen].some(n => !names.includes(n))) bad.push(old);
}
process.stdout.write(JSON.stringify(bad));
"""
sweep = subprocess.run(["node", "-e", SWEEP], input=json.dumps([BLOCK, list(site.NAME_SPACE)]),
                       capture_output=True, text=True)
check(f"from every one of the {len(site.NAME_SPACE)} names, a re-roll reaches each of the others once and never itself",
      sweep.returncode == 0 and json.loads(sweep.stdout or "null") == [], (sweep.stdout or sweep.stderr)[:300])
for key, names in EXPECT.items():
    check(f"{key}: the first name is {names[0]!r}" + (", the desk's own" if key == "reroll_desk" else ""),
          written_name(RESULTS[key]["steps"][0]) == names[0], repr(RESULTS[key]["steps"][0]["store"]))
check("every case drew exactly the values it pinned, none left over",
      all(res["unused"] == 0 for res in RESULTS.values()),
      repr({k: res["unused"] for k, res in RESULTS.items() if res["unused"]}))

print("== the button only ever shows its label: nothing on it is written, before or after a click (#762, #802) ==")
for key, res in RESULTS.items():
    b = res["button"]
    check(f"{key}: the page writes nothing on the button but hidden",
          set(b["writes"]) <= {"hidden"} and b["attrs"] == {"type": "button"}, repr(b))
    check(f"{key}: and nothing on the name but its text and hidden, never markup or a link",
          set(res["witchWrites"]) <= {"hidden", "textContent"}, repr(res["witchWrites"]))
button_tags = PAGE.count('id="newwitch"')
markup = PAGE[PAGE.find('<button type="button" class="newwitch"'):]
check("the page has one button, whose markup is exactly its label",
      button_tags == 1 and markup.startswith(f'<button type="button" class="newwitch" id="newwitch" hidden>{LABEL}</button>'),
      markup[:120])

srv.shutdown()
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The chat page shows the support desk's name, assigns one the desk takes, and re-rolls it everywhere at a click.")
