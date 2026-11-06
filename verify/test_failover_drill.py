# ABOUTME: Offline half of the KubeCon failover drill (#986): its router copies the apex router's cluster leg, its table is
# ABOUTME: fleet.sh's for attackme, its watcher runs backups.py watch's settings, and judge() fails each attendee-side defect.
"""verify/failover_drill.py is run live by verify/test_kubecon_failover_attendee_live.py. What it builds and how it
judges a drill are pure, so they are held here with no cluster, browser or network:

  - the local router's Caddyfile carries the options of apex-agenticburn's cluster leg (Host and X-Forwarded-For,
    the 5-second retry budget, TLS with tls_insecure_skip_verify, the 2-second dial timeout) and its support and
    deployments name maps;
  - the table is attackme's 14 rows as fleet.sh writes them, burritobot.co twins first, and backups.py's Watcher
    moves every one of them to the standby;
  - the drill's watcher runs backups.py watch's defaults, its chats carry the probe marker, and the dead address is
    in TEST-NET-1, so nothing answers it;
  - judge() passes a drill where everything held, and each defect an attendee would see (a reload, a new witch name,
    a new session, the primary still answering, the composer greying out again, the no-burritos screen, a promotion
    that never came) fails the check that names it.
"""
from __future__ import annotations

import copy
import ipaddress
import json
import pathlib
import re
import sys
import tempfile

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import failover_drill as d  # noqa: E402

b = d.b
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


print("== the local router is the apex router's cluster leg ==")
cf = d.caddyfile(pathlib.Path("/x"), 18080, 12019)
for want in ("header_up Host {host}", "header_up X-Forwarded-For {client_ip}", "lb_try_duration 5s",
             "lb_try_interval 250ms", "tls_insecure_skip_verify", "dial_timeout 2s",
             "support.burritobot.co support-attackme.burritobot.co",
             "deployments.burritobot.co deployments-attackme.burritobot.co", "import /x/routes.map",
             "@routed `{upstream} != \"\"`", "admin localhost:12019", ":18080 {"):
    check(f"the Caddyfile carries `{want}`", want in cf)
check("both legs, the live one and the dead one, carry the same proxy options", cf.count(d.PROXY_OPTS.strip()) == 2)
check("with no --page-from-repo the router serves no page of its own: every page is the console's",
      "@repo_page" not in cf and "file_server" not in cf)
cfp = d.caddyfile(pathlib.Path("/x"), 18080, 12019, d.PAGE)
check("--page-from-repo serves this checkout's burritbot.html for / and /burritobot, from the router's own address",
      f"root * {d.PAGE.parent}" in cfp and f"rewrite * /{d.PAGE.name}" in cfp and "path / /burritobot" in cfp)
check("--page-from-repo serves it only while the upstream is alive, so a dead cluster's / still answers 502",
      'expression `{dead} == ""`' in cfp and cfp.index("@repo_page") < cfp.index("@gone"))
check("the dead address is in TEST-NET-1, so a dial to it times out",
      ipaddress.ip_address(d.DEAD.rsplit(":", 1)[0]) in ipaddress.ip_network("192.0.2.0/24"))

print("== the table is fleet.sh's for attackme, and the watcher moves all of it ==")
table = d.table_for("lb-primary.example")
rows = b.table_rows(table)
hosts = [h for h, _ in rows]
check("14 rows: attackme, its six service and villain hosts, and the burritobot.co twin of each", len(rows) == 14, hosts)
check("the burritobot.co twins come first, as fleet.sh writes them",
      all(h.endswith(".burritobot.co") for h in hosts[:7]) and all(h.endswith(".agenticburn.com") for h in hosts[7:]))
for h in ("attackme.burritobot.co", "support-attackme.burritobot.co", "deployments-attackme.burritobot.co",
          "attackme.agenticburn.com"):
    check(f"the table routes {h}", h in hosts)
check("every row is on the primary's console LB at :443", all(up == "lb-primary.example:443" for _, up in rows))
check("the drill's hostname is attackme on the room's domain", d.public_host() == "attackme.burritobot.co")


class FakeRouter(b.Router):
    def apply(self) -> bool:
        return True


with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    (t / "routes.map").write_text(table)
    pools = {"community": [b.Cluster("p", "community", "us-west-2", "roster"),
                           b.Cluster("s", "community", "us-west-2", "night-before", "a")]}
    w = b.Watcher(pools, {"community": "attackme.burritobot.co"}, FakeRouter(t), t / "promoted.tsv", t / "ev.jsonl",
                  lb_of=lambda c: {"p": "lb-primary.example", "s": "lb-standby.example"}[c.name],
                  check=lambda lb, h, chat: (lb != "lb-primary.example", "dead" if lb == "lb-primary.example" else "ok"),
                  fail_after=d.FAIL_AFTER)
    w.refresh()
    for _ in range(d.FAIL_AFTER):
        w.tick()
    moved = b.table_rows((t / "routes.map").read_text())
    ev = [json.loads(line) for line in (t / "ev.jsonl").read_text().splitlines()]
    check(f"after {d.FAIL_AFTER} failed checks the watcher promotes the standby and repoints all 14 rows",
          len(moved) == 14 and all(up == "lb-standby.example:443" for _, up in moved)
          and ev[-1].get("promoted") == "s" and ev[-1].get("rows") == 14, json.dumps(ev))

src = (b.HERE / "backups.py").read_text()
for flag, val in (("--interval", d.INTERVAL), ("--chat-every", d.CHAT_EVERY), ("--fail-after", d.FAIL_AFTER)):
    m = re.search(rf'add_argument\("{flag}", type=\w+, default=(\d+)', src)
    check(f"the drill's watcher runs backups.py watch's {flag} default ({m.group(1) if m else None})",
          bool(m) and int(m.group(1)) == val)
check("every chat the drill sends carries backups.py's probe marker", all(p.startswith(b.PROBE_MARKER) for p in d.PROMPTS))
# #985's watcher arms Kyverno on a public standby and links the new pair; on the drill's two live clusters that would
# change them, so the drill's Watcher is built with neither.
drill_src = pathlib.Path(d.__file__).read_text()
watcher_call = drill_src[drill_src.index("w = b.Watcher("):drill_src.index("w.refresh()")]
check("the drill's Watcher is built with no arm and no link, so it leaves both live clusters as found",
      "arm" not in watcher_call and "link" not in watcher_call, watcher_call)

print("== judge() passes a drill where everything held, and fails each defect ==")
W = "\U0001F9D9 You are Hazel the Imp"
P, S = "lb-p.example", "lb-s.example"
GOOD = {
    "primary": "watch-it-burn-community", "standby": "watch-it-burn-private",
    "lbs": {"watch-it-burn-community": P, "watch-it-burn-private": S}, "rows": 14,
    "routes_after": d.table_for(S),
    "events": [{"role": "community", "promoted": "watch-it-burn-private", "rows": 14, "applied": True}],
    "before": {"witch": W, "cookie": "hazel-the-imp", "marker": "m", "disabled": False},
    "after": {"witch": W, "cookie": "hazel-the-imp", "marker": "m", "disabled": False},
    "reloaded": {"witch": W, "cookie": "hazel-the-imp", "session": "sess-1", "disabled": False},
    "chat_before": {"status": 200, "upstream": f"{P}:443", "witch": "Hazel the Imp", "session": "sess-1",
                    "shown": "Bases: ...", "error_shown": False},
    "chat_during": {"status": 502, "shown": "Hmm, the kitchen isn't answering right now (502)."},
    "chat_after": {"status": 200, "upstream": f"{S}:443", "witch": "Hazel the Imp", "session": "sess-1",
                   "shown": "Welcome back, Hazel the Imp!", "error_shown": False},
    "navigations": ["http://attackme.burritobot.co:1/"],
    "fault_at": 5.0, "promoted_at": 85.0, "enabled_at": 87.0,
    "timeline": [{"at": 26.0, "disabled": True, "noburritos": "none", "placeholder": "starting up"},
                 {"at": 85.0, "event": "promoted"},
                 {"at": 87.0, "disabled": False, "noburritos": "none", "placeholder": "Tell"}],
}
bad = [n for n, ok, _ in d.judge(GOOD) if not ok]
check("a drill where everything held passes every check", not bad, bad)
check("judge() makes 13 checks", len(d.judge(GOOD)) == 13)


def mutated(fn) -> dict:
    r = copy.deepcopy(GOOD)
    fn(r)
    return r


DEFECTS = [
    ("the page reloaded", lambda r: r["navigations"].append("http://attackme.burritobot.co:1/"), "never reloaded"),
    ("the page lost its marker", lambda r: r["after"].update(marker=None), "never reloaded"),
    ("a new witch name in the header", lambda r: r["after"].update(witch="\U0001F9D9 You are Silas the Ogre"),
     "witch name in the page header"),
    ("a new wib_witch cookie", lambda r: r["after"].update(cookie="silas-the-ogre"), "wib_witch cookie"),
    ("a new session on the second chat", lambda r: r["chat_after"].update(session="sess-2"), "same witch name and session"),
    ("the primary still answering", lambda r: r["chat_after"].update(upstream=f"{P}:443"), "chats again"),
    ("an error shown after the switch", lambda r: r["chat_after"].update(error_shown=True, status=502), "chats again"),
    ("the composer greying out again", lambda r: r["timeline"].append({"at": 95.0, "disabled": True,
                                                                        "noburritos": "none", "placeholder": "x"}),
     "stayed on"),
    ("the composer off at the end", lambda r: r["after"].update(disabled=True), "stayed on"),
    ("the no-burritos screen", lambda r: r["timeline"][0].update(noburritos="flex"), "no-burritos"),
    ("no promotion", lambda r: r.update(events=[], promoted_at=None, enabled_at=None), "promoted"),
    ("a row left on the primary", lambda r: r.update(routes_after=d.table_for(S).replace(S, P, 1)), "rows now route"),
    ("a slow composer", lambda r: r.update(enabled_at=85.0 + d.SETTLE + 1), f"within {d.SETTLE} s"),
    ("a wait past the bound", lambda r: r.update(promoted_at=d.MAX_WAIT + 10.0, enabled_at=d.MAX_WAIT + 11.0),
     f"under {d.MAX_WAIT} s"),
    ("a refresh that lost the session", lambda r: r["reloaded"].update(session="sess-9"), "refresh"),
]
for what, fn, needle in DEFECTS:
    failed = [n for n, ok, _ in d.judge(mutated(fn)) if not ok]
    check(f"{what} fails the check about '{needle}'", any(needle in n for n in failed), failed)

sm = "\n".join(d.summary(GOOD))
check("summary() names the wait, the outage message and the witch name",
      "promoted at 85.0 s" in sm and "kitchen isn't answering" in sm and "Hazel the Imp" in sm, sm)

if failures:
    print(f"\nFAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("\nALL FAILOVER DRILL CHECKS PASSED")
