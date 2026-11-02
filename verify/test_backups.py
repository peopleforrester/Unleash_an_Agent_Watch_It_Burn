# ABOUTME: Offline test of the standby clusters and their automatic promotion (#643): backups.tsv's pools and waves,
# ABOUTME: the self-check, the watcher handing a hostname to the next healthy standby, and the schedule.
"""What #643 asks, held without a cluster:

- 12 public standbys and 3 private ones, across regions; 3 public stand up the night before and 9 six hours out.
- If the cluster serving attackme fails its self-check, the next healthy public cluster takes the hostname with
  nobody acting; the same for burritobot-private.

The watcher is driven with a fake self-check and a fake console-LB lookup, and writes a real routes.map in a temp
apex checkout whose reload script records what it was given. The self-check runs against a local HTTP server
that plays a console. Nothing here reaches AWS, the router or a model.
"""
from __future__ import annotations

import datetime as dt
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import zoneinfo

REPO = pathlib.Path(__file__).resolve().parent.parent
FLEET_DIR = REPO / "infra/terraform/fleet"
sys.path.insert(0, str(FLEET_DIR))
import backups as b  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  -> {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def fleet(func: str, name: str, then: str = "") -> str:
    """A fleet.sh function's output, or with `then` ("&& echo yes", "|| echo no") its status as a word."""
    script = f"source '{b.FLEET}' >/dev/null 2>&1; {func} '{name}' {then}"
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60).stdout.strip()


print("== backups.tsv: 12 public standbys and 3 private, across regions ==")
pools = b.load_pools(FLEET_DIR / "roster.tsv", FLEET_DIR / "backups.tsv", "us-west-2")
pub = [c for c in pools["community"] if c.wave != "roster"]
priv = [c for c in pools["admin"] if c.wave != "roster"]
check("12 public standbys", len(pub) == 12, str(len(pub)))
check("3 private standbys", len(priv) == 3, str(len(priv)))
check("each pool starts with its roster cluster",
      [pools["community"][0].name, pools["admin"][0].name] == ["watch-it-burn-community", "watch-it-burn-private"])
check("3 public stand up the night before", sum(c.wave == "night-before" for c in pub) == 3)
check("9 public stand up six hours out", sum(c.wave == "six-hours" for c in pub) == 9)
check("the night-before public standbys are the first three in promotion order",
      [c.wave for c in pub[:3]] == ["night-before"] * 3)
check("the private standbys stand up the night before", all(c.wave == "night-before" for c in priv))
for role, pool in pools.items():
    regions = [c.region for c in pool]
    check(f"{role}: the pool spans three regions", len(set(regions)) == 3, str(sorted(set(regions))))
    check(f"{role}: no two clusters next to each other in promotion order share a region",
          all(x != y for x, y in zip(regions, regions[1:])), str(regions))
    check(f"{role}: the first standby is outside us-west-2, where the roster cluster is",
          pool[1].region != "us-west-2", pool[1].region)
print("== and across zones: the standbys up at any moment cover both lab zones of every region ==")
check("every standby names zone a or b", all(c.zone in ("a", "b") for c in pub + priv),
      str([(c.name, c.zone) for c in pub + priv if c.zone not in ("a", "b")]))
for label, up_now in (("the night before", [c for c in pub + priv if c.wave == "night-before"]),
                      ("from six hours out", pub + priv)):
    for region in sorted({c.region for c in pub + priv}):
        zs = {c.zone for c in up_now if c.region == region}
        check(f"{label}: {region} has standbys in both zones", zs == {"a", "b"}, str(zs))
for region in sorted({c.region for c in pub}):
    zs = [c.zone for c in pub if c.region == region]
    check(f"public standbys in {region} alternate zones down the pool", all(x != y for x, y in zip(zs, zs[1:])), str(zs))
T0 = pathlib.Path(tempfile.mkdtemp(prefix=".backups-zone.", dir=REPO))
(T0 / "b.tsv").write_text("watch-it-burn-community-b01|community|us-east-2|night-before|c\n")
try:
    b.load_pools(FLEET_DIR / "roster.tsv", T0 / "b.tsv", "us-west-2")
    check("a zone other than a or b is refused", False)
except SystemExit as e:
    check("a zone other than a or b is refused", "zone 'c'" in str(e), str(e))
(T0 / "b.tsv").write_text("watch-it-burn-community-b01|community|us-east-2|night-before\n")
try:
    b.load_pools(FLEET_DIR / "roster.tsv", T0 / "b.tsv", "us-west-2")
    check("and so is a row with no zone", False)
except SystemExit as e:
    check("and so is a row with no zone", "zone ''" in str(e), str(e))
import shutil as _sh  # noqa: E402
_sh.rmtree(T0, ignore_errors=True)
tf = (REPO / "infra/terraform/aws/cluster/main.tf").read_text(encoding="utf-8")
check("the cluster module takes node_subnet_ids, null by default (every private subnet)",
      'variable "node_subnet_ids"' in tf and "default     = null" in tf.split('variable "node_subnet_ids"')[1][:200])
check("and the node group places its node in them",
      "subnet_ids = var.node_subnet_ids" in " ".join(tf.split("eks_managed_node_groups = {")[1][:800].split()))
check("fleet.sh reads a standby's zone from backups.tsv", fleet("standby_zone", pub[3].name) == pub[3].zone == "b")
check("a roster cluster has no zone", fleet("standby_zone", "watch-it-burn-community") == "")
SUBS = '\'["subnet-a1","subnet-b2"]\''
check("zone a is the lab VPC's first private subnet", fleet("node_subnets_for", pub[0].name, SUBS) == '["subnet-a1"]')
check("zone b is its second", fleet("node_subnets_for", priv[0].name, SUBS) == '["subnet-b2"]')
# A roster cluster's node stays in the zone its EBS volumes live in (kagent-postgresql, student-work, Tempo): a node
# that rolls into the other zone leaves them unattachable and the bot down. Measured 2026-11-01: community's node
# and volumes in us-west-2a (zone a, the first private subnet), private's in us-west-2b (zone b).
check("the community roster cluster is pinned to zone a, where its volumes are",
      fleet("node_subnets_for", "watch-it-burn-community", SUBS) == '["subnet-a1"]')
check("the private roster cluster is pinned to zone b, where its volumes are",
      fleet("node_subnets_for", "watch-it-burn-private", SUBS) == '["subnet-b2"]')
check("an attendee cluster keeps every subnet", fleet("node_subnets_for", "watch-it-burn-attendee-007", SUBS) == "")
check("a lab VPC with no subnet for the zone fails rather than landing elsewhere",
      fleet("node_subnets_for", priv[0].name, "'[\"subnet-a1\"]' || echo refused") == "refused")

names = [c.name for p in pools.values() for c in p]
check("every name is unique", len(names) == len(set(names)))
check("every name is under 30 characters (the IAM name_prefix cap)", all(len(n) < 30 for n in names),
      str([n for n in names if len(n) >= 30]))

print("== fleet.sh knows a standby by its name ==")
for c in pub[:1] + pub[-1:] + priv[:1]:
    want_role = {"community": "community", "admin": "admin"}[c.role]
    check(f"{c.name}: is_standby_name", fleet("is_standby_name", c.name, "&& echo yes") == "yes")
    check(f"{c.name}: its role is {want_role}", fleet("role_of_instructor_name", c.name) == want_role)
    check(f"{c.name}: its role= tag is {want_role}", fleet("role_for_cluster", c.name) == want_role)
    check(f"{c.name}: it gets the presenters' terminal login, as its roster cluster does",
          fleet("is_instructor_name", c.name, "&& echo yes") == "yes")
    check(f"{c.name}: not the attendee pool", fleet("is_attendee_name", c.name, "|| echo no") == "no")
    # event.sh's WIB_ROSTER_PROFILES is kubecon (#774), so a standby builds the KubeCon profile its role gets.
    check(f"{c.name}: its bootstrap profile is its roster cluster's",
          fleet("bootstrap_profile_for_role", want_role)
          == ("kubecon-community" if c.role == "community" else "kubecon-private"))
check("a public standby answers to attackme", fleet("public_host_for", pub[0].name) == "attackme.agenticburn.com")
check("a private standby answers to burritobot-private",
      fleet("public_host_for", priv[0].name) == "burritobot-private.agenticburn.com")
check("fleet.sh reads a standby's region from backups.tsv", fleet("standby_region", pub[0].name) == pub[0].region)
check("the roster clusters are not standbys",
      fleet("is_standby_name", "watch-it-burn-community", "|| echo no") == "no"
      and fleet("is_standby_name", "watch-it-burn-private", "|| echo no") == "no")
ident = (REPO / "infra/datadog-cluster-identity.sh").read_text(encoding="utf-8")
check("a public standby reports to Datadog as burritobot-public, so Whitney's tab follows a promotion",
      'watch-it-burn-community-b[0-9][0-9]) DATADOG_CLUSTER_NAME="burritobot-public"' in " ".join(ident.split()))
check("a private standby reports as burritobot-private",
      'watch-it-burn-private-b[0-9][0-9]) DATADOG_CLUSTER_NAME="burritobot-private"' in " ".join(ident.split()))

print("== a standby's roster row is its roster cluster's, under its own name ==")
check("public: burn, pids -1", b.roster_row_for(pub[0], FLEET_DIR / "roster.tsv")
      == "watch-it-burn-community-b01|community|||-1|burn|")
check("private: admin", b.roster_row_for(priv[0], FLEET_DIR / "roster.tsv") == "watch-it-burn-private-b01|admin||||admin|")

print("== the router table ==")
TABLE = """# ABOUTME: Host -> cluster LB routing for the agenticburn.com wildcard router.
attackme.burritobot.co  lb-primary:443
grafana-attackme.burritobot.co  lb-primary:443
burritobot-private.burritobot.co  lb-private:443
attackme.agenticburn.com  lb-primary:443
grafana-attackme.agenticburn.com  lb-primary:443
burritobot-private.agenticburn.com  lb-private:443
"""
check("upstream_of reads a host's row", b.upstream_of(TABLE, "attackme.agenticburn.com") == "lb-primary:443")
check("and None for a host with no row", b.upstream_of(TABLE, "nope.agenticburn.com") is None)
moved, n = b.repoint(TABLE, "lb-primary:443", "lb-b01:443")
check("repoint moves every row of the failed console, twins and service hosts included", n == 4, str(n))
check("and leaves the private rows and the comment as they were",
      [l for l in moved.splitlines() if "private" in l or l.startswith("#")]
      == [l for l in TABLE.splitlines() if "private" in l or l.startswith("#")])
check("no row still names the failed console", "lb-primary" not in moved)

print("== the watcher ==")
T = pathlib.Path(tempfile.mkdtemp(prefix=".backups-test.", dir=REPO))
apex = T / "apex"; (apex / "scripts").mkdir(parents=True)
reload_log = T / "reloads"
(apex / "scripts/reload-routes.sh").write_text(
    "#!/usr/bin/env bash\n"
    f'[[ -f "{T}/reload_fails" ]] && exit 1\n'
    f'cp "$1" "{T}/live.map"; echo "$1" >>"{reload_log}"\n')
os.chmod(apex / "scripts/reload-routes.sh", 0o755)
LBS = {"watch-it-burn-community": "lb-primary", "watch-it-burn-private": "lb-private"}
LBS.update({c.name: f"lb-{c.name[-3:]}-{c.role}" for c in pub + priv})
HOSTS = {"community": "attackme.agenticburn.com", "admin": "burritobot-private.agenticburn.com"}
down: set[str] = set()     # console LBs whose self-check fails
calls: list[tuple[str, bool]] = []


def fake_check(lb: str, host: str, chat: bool) -> tuple[bool, str]:
    calls.append((lb, chat))
    return (lb not in down), ("healthy" if lb not in down else "/healthz answered 502")


def watcher(fail_after: int = 3, drill: str = "") -> b.Watcher:
    (apex / "routes.map").write_text(TABLE)
    for f in (T / "promoted.tsv", T / "events.jsonl", reload_log, T / "reload_fails", T / "live.map"):
        f.unlink(missing_ok=True)
    down.clear(); calls.clear()
    w = b.Watcher(pools, HOSTS, b.Router(apex, retries=1, backoff=0), T / "promoted.tsv", T / "events.jsonl",
                  lb_of=lambda c: LBS.get(c.name), check=fake_check, fail_after=fail_after, drill=drill)
    w.refresh()
    return w


def routed(host: str) -> str | None:
    return b.upstream_of((apex / "routes.map").read_text(), host)


w = watcher()
w.tick()
check("a healthy attackme is left where it is", routed("attackme.agenticburn.com") == "lb-primary:443")
check("only the two routed consoles are checked", sorted(lb for lb, _ in calls) == ["lb-primary", "lb-private"])
check("the router is not reloaded", not reload_log.exists())

down.add("lb-primary")
w.tick(); w.tick()
check("two failures in a row do not promote yet", routed("attackme.agenticburn.com") == "lb-primary:443")
w.tick()
check("the third does: attackme goes to the first healthy standby, b01 in us-east-2",
      routed("attackme.agenticburn.com") == "lb-b01-community:443")
check("every attackme row moved, the burritobot.co twins and service hosts included",
      all(routed(h) == "lb-b01-community:443" for h in
          ("attackme.burritobot.co", "grafana-attackme.burritobot.co", "grafana-attackme.agenticburn.com")))
check("burritobot-private did not move", routed("burritobot-private.agenticburn.com") == "lb-private:443")
check("the new table was applied to the live router",
      reload_log.exists() and (T / "live.map").read_text() == (apex / "routes.map").read_text())
check("promoted.tsv records the holder for fleet.sh routes",
      (T / "promoted.tsv").read_text() == "community\twatch-it-burn-community-b01\n")
ev = [json.loads(l) for l in (T / "events.jsonl").read_text().splitlines()]
check("the promotion is in the event log, with the failure that caused it",
      ev and ev[-1]["promoted"] == "watch-it-burn-community-b01" and ev[-1]["failed"] == "watch-it-burn-community"
      and ev[-1]["applied"] is True and "502" in ev[-1]["why"], str(ev))
check("the candidate was checked in full, chat included", ("lb-b01-community", True) in calls)

calls.clear(); w.tick()
check("the next tick watches the new holder", "lb-b01-community" in [lb for lb, _ in calls]
      and "lb-primary" not in [lb for lb, _ in calls])
check("and does not fail back on its own when the old cluster recovers",
      (down.discard("lb-primary") or True) and (w.tick() or True) and routed("attackme.agenticburn.com") == "lb-b01-community:443")

print("== the next healthy one, in order, skipping the unhealthy ==")
w = watcher()
down.update({"lb-primary", "lb-b01-community", "lb-b02-community"})
for _ in range(3):
    w.tick()
check("b01 and b02 failing, b03 in us-west-2 takes attackme", routed("attackme.agenticburn.com") == "lb-b03-community:443")
down.add("lb-b03-community")
for _ in range(3):
    w.tick()
check("then b03 failing, b04 takes it, the order continuing after the holder",
      routed("attackme.agenticburn.com") == "lb-b04-community:443")

print("== the private bot is promoted the same way ==")
w = watcher()
down.add("lb-private")
for _ in range(3):
    w.tick()
check("burritobot-private goes to the first private standby",
      routed("burritobot-private.agenticburn.com") == "lb-b01-admin:443"
      and routed("burritobot-private.burritobot.co") == "lb-b01-admin:443")
check("attackme did not move", routed("attackme.agenticburn.com") == "lb-primary:443")
check("promoted.tsv names the private holder", "admin\twatch-it-burn-private-b01" in (T / "promoted.tsv").read_text())

print("== wrapping round: the last standby failing hands back to the first healthy one ==")
w = watcher()
(apex / "routes.map").write_text(TABLE.replace("lb-primary", "lb-b12-community"))
down.add("lb-b12-community")
for _ in range(3):
    w.tick()
check("after b12 the pool starts again from the roster cluster", routed("attackme.agenticburn.com") == "lb-primary:443")
check("and promoted.tsv drops the role, since its roster cluster holds it again",
      "community" not in (T / "promoted.tsv").read_text())

print("== nothing healthy: the hostname stays, and the watcher keeps trying ==")
w = watcher()
down.update(LBS[c.name] for c in pools["community"])
for _ in range(4):
    w.tick()
check("attackme stays on its cluster", routed("attackme.agenticburn.com") == "lb-primary:443")
check("nothing was reloaded", not reload_log.exists())
ev = [json.loads(l) for l in (T / "events.jsonl").read_text().splitlines()]
check("the event log says no standby was healthy", ev and all(e["promoted"] is None for e in ev))
down.discard(LBS["watch-it-burn-community-b05"])
w.tick()
check("the next tick promotes the first standby that recovers", routed("attackme.agenticburn.com") == "lb-b05-community:443")

print("== a reload the router refuses changes nothing ==")
w = watcher()
(T / "reload_fails").touch()
down.add("lb-primary")
for _ in range(3):
    w.tick()
check("the table on disk is put back", (apex / "routes.map").read_text() == TABLE)
check("promoted.tsv is not written", not (T / "promoted.tsv").exists())
ev = [json.loads(l) for l in (T / "events.jsonl").read_text().splitlines()]
check("the event log records the refused apply", ev and ev[-1]["applied"] is False)
(T / "reload_fails").unlink()
w.tick()
check("and the next tick, with the router back, promotes", routed("attackme.agenticburn.com") == "lb-b01-community:443")

print("== a console whose LB cannot be read is never a candidate ==")
w = watcher()
w.lbs["watch-it-burn-community-b01"] = None
down.add("lb-primary")
for _ in range(3):
    w.tick()
check("b01 has no LB, so b02 takes attackme", routed("attackme.agenticburn.com") == "lb-b02-community:443")

print("== the drill: the rehearsal treats one cluster as failing ==")
w = watcher(drill="watch-it-burn-community")
for _ in range(3):
    w.tick()
check("a drill on the roster cluster promotes b01 with every console healthy",
      routed("attackme.agenticburn.com") == "lb-b01-community:443")
check("and leaves the private bot alone", routed("burritobot-private.agenticburn.com") == "lb-private:443")

print("== a region outage does not stall or blind the watcher ==")
import time as _t  # noqa: E402
w = watcher()
w.lb_of = lambda c: (_t.sleep(0.4), LBS.get(c.name))[1]
t0 = _t.monotonic(); w.refresh(); took = _t.monotonic() - t0
check("every console LB is read at once, not one after another (17 slow lookups in well under 17 x 0.4 s)",
      took < 2.5, f"{took:.1f}s")
w.lb_of = lambda c: None if c.region == "us-east-2" else LBS.get(c.name)
w.refresh()
check("a lookup that fails keeps the LB already known", w.lbs["watch-it-burn-community-b01"] == LBS["watch-it-burn-community-b01"])


def boom(c):
    if c.name == "watch-it-burn-community-b02":
        raise RuntimeError("EKS API unreachable")
    return LBS.get(c.name)


w.lb_of = boom
w.refresh()
check("a lookup that raises fails only its own cluster", w.lbs["watch-it-burn-community-b03"] == LBS["watch-it-burn-community-b03"])
w2 = b.Watcher(pools, HOSTS, b.Router(apex, retries=1, backoff=0), T / "promoted.tsv", T / "events.jsonl",
               lb_of=lambda c: None, check=fake_check)
w2.refresh()
check("a cluster never seen has no LB, so it is never a candidate", w2.lbs["watch-it-burn-community-b01"] is None)

w = watcher()
w._check = lambda lb, host, chat: (_ for _ in ()).throw(RuntimeError("socket exploded"))
try:
    w.tick(); survived = True
except Exception:  # noqa: BLE001
    survived = False
check("a tick that hits an unexpected error logs it and the watcher carries on", survived)

w = watcher()
(apex / "scripts/reload-routes.sh").write_text("#!/usr/bin/env bash\nsleep 5\n")
w.router.timeout = 0.5
down.add("lb-primary")
for _ in range(3):
    w.tick()
check("a reload that hangs counts as refused: the table is put back", (apex / "routes.map").read_text() == TABLE)
check("and promoted.tsv is not written", not (T / "promoted.tsv").exists())
(apex / "scripts/reload-routes.sh").write_text(
    "#!/usr/bin/env bash\n"
    f'[[ -f "{T}/reload_fails" ]] && exit 1\n'
    f'cp "$1" "{T}/live.map"; echo "$1" >>"{reload_log}"\n')

print("== the self-check, against a local console ==")


class Console(http.server.BaseHTTPRequestHandler):
    mode: dict = {}
    seen: list = []

    def log_message(self, *_a):
        pass

    def _send(self, code: int, body: str, ctype: str = "text/plain") -> None:
        data = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        Console.seen.append(("GET", self.path, self.headers.get("Host")))
        m = Console.mode
        if self.path == "/healthz":
            self._send(m.get("healthz", 200), "ok\n")
        elif self.path == "/":
            self._send(200, m.get("page", "<html><head><title>BurritoBot</title></head></html>"), "text/html")
        elif self.path == "/controls":
            self._send(m.get("controls", 200), m.get("controls_body", '{"input": false}'), "application/json")
        else:
            self._send(404, "")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        Console.seen.append(("POST", self.path, body.get("prompt")))
        self._send(200, json.dumps({"reply": Console.mode.get("reply", "Salsa verde.")}), "application/json")


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Console)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def sc(chat: bool = True, **mode) -> tuple[bool, str]:
    Console.mode = mode; Console.seen = []
    return b.self_check(BASE, "attackme.agenticburn.com", chat=chat, timeout=5, chat_timeout=5)


ok, why = sc()
check("a working console passes", ok, why)
check("it asks with the role's Host header, as the router does",
      all(h == "attackme.agenticburn.com" for m, _p, h in Console.seen if m == "GET"))
check("the chat carries the probe marker, so it never reaches the prompt wall",
      any(m == "POST" and b.PROBE_MARKER in (p or "") for m, _x, p in Console.seen))
ok, why = sc(healthz=502)
check("/healthz down fails, and says so", not ok and "/healthz" in why, why)
ok, why = sc(page="<html>nginx default page</html>")
check("a page that is not the storefront fails", not ok and "storefront" in why, why)
ok, why = sc(controls=502)
check("guard-proxy down (/controls 502) fails", not ok and "/controls" in why, why)
ok, why = sc(controls_body="not json")
check("/controls without a JSON object fails", not ok and "JSON" in why, why)
ok, why = sc(reply="")
check("an empty chat reply fails: the bot does not answer", not ok and "/chat" in why, why)
ok, why = sc(chat=False, reply="")
check("a tick without chat makes no model call", ok and not any(m == "POST" for m, *_ in Console.seen), why)
srv.shutdown()
ok, why = b.self_check(BASE, "attackme.agenticburn.com", timeout=2)
check("a console that does not answer at all fails", not ok, why)

print("== the schedule: three public the night before, nine six hours out ==")
start = dt.datetime(2030, 3, 5, 18, 0, tzinfo=dt.timezone.utc)   # a sample start; the real one is passed in (#417)
lines = b.schedule_lines(start, dt.timezone.utc, pathlib.Path("/fleet"))
by = {l.split(b.CRON_TAG)[1].split()[0]: l for l in lines[1:]}
check("one line per wave, the watcher and the teardown", sorted(by) == ["down", "night-before", "six-hours", "watch"])
check("night-before stands up 18 hours out", by["night-before"].startswith("0 0 5 3 * mkdir -p /fleet/logs; /fleet/backups.py up night-before"))
check("six-hours stands up 6 hours out", by["six-hours"].startswith("0 12 5 3 * mkdir -p /fleet/logs; /fleet/backups.py up six-hours"))
check("the watcher runs from an hour after the night-before wave until 90 minutes after the start",
      "/fleet/backups.py watch --from 2030-03-05T01:00:00Z --until 2030-03-05T19:30:00Z" in by["watch"], by["watch"])
check("and cron starts it again every 5 minutes, so a watcher that died is back with nobody acting",
      by["watch"].startswith("*/5 * * * * mkdir -p /fleet/logs; /fleet/backups.py watch "), by["watch"])
check("the standbys come down two hours after the start, and the lines remove themselves",
      by["down"].startswith("0 20 5 3 * mkdir -p /fleet/logs; /fleet/backups.py down all --apply") and "unschedule" in by["down"])
mt = b.schedule_lines(start, zoneinfo.ZoneInfo("America/Denver"), pathlib.Path("/fleet"))
check("in the cron host's own time zone", any(l.startswith("0 17 4 3 * mkdir -p /fleet/logs; /fleet/backups.py up night-before") for l in mt))
check("every line is tagged so unschedule finds it", all(b.CRON_TAG in l for l in lines))
# 2026-10-31: netcup's crontab sets PATH=~/.local/bin:/usr/local/bin:/usr/bin:/bin, and terraform, kubectl, aws,
# helm and python3 are all in /home/linuxbrew/.linuxbrew/bin, so the night-before wave would have died at 02:50 UTC
# on the day. Each line carries the PATH `schedule` was run with.
pl = b.schedule_lines(start, dt.timezone.utc, pathlib.Path("/fleet"), path="/opt/brew/bin:/usr/bin")
check("with a PATH given, every scheduled command runs under it",
      all(" export PATH=/opt/brew/bin:/usr/bin; " in f" {' '.join(l.split()[5:])}" for l in pl[1:]), str(pl[1:2]))
check("cmd_schedule passes cron_path()", "path=cron_path()" in (FLEET_DIR / "backups.py").read_text())
_fake_which = {"terraform": "/home/linuxbrew/.linuxbrew/bin/terraform", "kubectl": "/home/linuxbrew/.linuxbrew/bin/kubectl",
               "aws": "/home/linuxbrew/.linuxbrew/bin/aws", "helm": "/home/linuxbrew/.linuxbrew/bin/helm",
               "jq": "/usr/bin/jq", "curl": "/usr/bin/curl", "python3": "/home/linuxbrew/.linuxbrew/bin/python3"}.get
check("cron_path names each tool's directory once, then the standard ones",
      b.cron_path(_fake_which) == "/home/linuxbrew/.linuxbrew/bin:/usr/bin:/usr/local/bin:/bin", b.cron_path(_fake_which))
try:
    b.cron_path(lambda t: None if t == "helm" else "/x/" + t)
    check("a tool missing from PATH stops schedule", False)
except SystemExit as e:
    check("a tool missing from PATH stops schedule", "helm" in str(e))
_long = b.schedule_lines(start, dt.timezone.utc, pathlib.Path("/home/michael/repos/talks/Unleash_an_Agent_Watch_It_Burn/infra/terraform/fleet"),
                         path=b.cron_path(_fake_which))
check("every line fits cron's limit (crontab refused one on 2026-10-31 with the whole interactive PATH)",
      max(len(l) for l in _long) < 900, str(max(len(l) for l in _long)))
# Run each line's command the way cron does, with sh, on a checkout that has no logs directory yet.
fresh = T / "fresh"; fresh.mkdir()
(fresh / "backups.py").write_text(f'#!/bin/sh\necho "$@" >>"{fresh}/ran"\n'); os.chmod(fresh / "backups.py", 0o755)
for l in b.schedule_lines(start, dt.timezone.utc, fresh)[1:]:
    subprocess.run(["sh", "-c", " ".join(l.split()[5:])], capture_output=True, text=True, timeout=30)
ran = (fresh / "ran").read_text().splitlines() if (fresh / "ran").exists() else []
check("on a fresh checkout with no logs directory, cron's shell still runs every line",
      [r.split()[0] for r in ran] == ["up", "up", "watch", "down", "unschedule"] and (fresh / "logs").is_dir(), str(ran))
try:
    b.parse_when("2030-03-05T18:00:00")
    check("a start with no UTC offset is refused", False)
except SystemExit:
    check("a start with no UTC offset is refused", True)

print("== a failed build still runs the region's converge, the repair step ==")
# 2026-10-31, the #643 rehearsal: watch-it-burn-private-b02's build failed on bedrock-profiles (two ModelConfigs
# arrived after the 300 s wait) and run_steps returned before the converge that pins them.
_x = type("X", (), {"env": {"WIB_ROSTER_FILE": "/dev/null"}})()
_ran: list[str] = []
_converge_rc = {"rc": 0}
_real_run = b.subprocess.run
def _fake(cmd, **kw):  # noqa: E306
    _ran.append(cmd[1])
    return type("R", (), {"returncode": _converge_rc["rc"] if cmd[1] == "converge" else 1})()
b.subprocess.run = _fake
_steps = [({}, ["fleet.sh", "instructors", "up", "all"]), ({}, ["fleet.sh", "converge", "watch-it-burn-private-b02"])]
try:
    rc_repaired = b.run_steps(_x, "us-east-1", [], _steps, False)
    ran_repaired = list(_ran); _ran.clear(); _converge_rc["rc"] = 1
    rc_broken = b.run_steps(_x, "us-east-1", [], _steps, False)
    ran_broken = list(_ran)
finally:
    b.subprocess.run = _real_run
check("after a failed build the converge still runs", ran_repaired == ["instructors", "converge"], str(ran_repaired))
check("a converge that repairs it makes the region green", rc_repaired == 0)
check("a converge that cannot repair it leaves the region failed", rc_broken == 1 and ran_broken == ["instructors", "converge"])

print("== up and down, dry run: one fleet.sh run per region, standbys kept out of the router ==")
# A live `backups.py up` on this host writes its own backups-* roster files; only the dry runs' would be a fault.
_tmp_before = {p.name for p in pathlib.Path(tempfile.gettempdir()).iterdir() if p.name.startswith("backups-")}
# A lab VPC directory holding the home region's state and no us-east-2 one, whatever is deployed today: #643
# applied the real us-east-2 and us-east-1 VPCs on 2026-10-31, and the refusal below is about a region without one.
_net = pathlib.Path(tempfile.mkdtemp(prefix=".backups-net-", dir=REPO))
(_net / "states").mkdir()
_home_state = REPO / "infra/terraform/aws/network/terraform.tfstate"
if _home_state.exists():
    (_net / "terraform.tfstate").symlink_to(_home_state)
r = subprocess.run([sys.executable, str(FLEET_DIR / "backups.py"), "up", "night-before", "--dry-run"],
                   capture_output=True, text=True, timeout=120, env={**os.environ, "WIB_LAB_VPC_DIR": str(_net)})
shutil.rmtree(_net)
out = r.stdout.splitlines()
ups = [l for l in out if l.endswith("instructors up all")]
check("three regions, three builds", len(ups) == 3, r.stdout + r.stderr)
check("each with its own region, out of the router, the pool and the walkthrough",
      all("WIB_NO_ROUTES=1" in l and "WIB_NO_INGEST=1" in l and "WIB_NO_VERIFY=1" in l for l in ups)
      and sorted(l.split("WIB_REGION=")[1].split()[0] for l in ups) == ["us-east-1", "us-east-2", "us-west-2"])
check("the us-east-2 build carries b01 and private-b01 and nothing else",
      any("WIB_REGION=us-east-2" in l and "watch-it-burn-community-b01|" in l and "watch-it-burn-private-b01|" in l
          and "b02" not in l for l in ups))
check("each build is followed by a converge of the same clusters in the same region",
      any(l == f"WIB_REGION=us-east-2 {FLEET_DIR}/fleet.sh converge watch-it-burn-community-b01 watch-it-burn-private-b01"
          for l in out))
check("a region with no lab VPC is named with the apply that makes one, and fails the run",
      r.returncode == 1 and "apply -state=states/accen-dev.us-east-2.tfstate" in r.stderr
      and "-var region=us-east-2" in r.stderr, r.stderr)
r = subprocess.run([sys.executable, str(FLEET_DIR / "backups.py"), "up", "six-hours", "--dry-run"],
                   capture_output=True, text=True, timeout=120)
check("six-hours builds nine clusters", sum(r.stdout.count(f"watch-it-burn-community-b{i:02d}|") for i in range(1, 13)) == 9)
r = subprocess.run([sys.executable, str(FLEET_DIR / "backups.py"), "down", "all", "--dry-run"],
                   capture_output=True, text=True, timeout=120)
downs = [l for l in r.stdout.splitlines() if l.endswith("instructors down all")]
check("down all destroys every standby, region by region", len(downs) == 3 and
      sum(l.count("|") // 6 for l in downs) == 15, r.stdout)
check("and without --apply it is fleet.sh's dry run", all("WIB_APPLY" not in l for l in downs))
# `down` with neither --apply nor --dry-run is a dry run too (2026-10-31: it destroyed five us-west-2 standbys,
# because it ran `instructors down all`, which did not check WIB_APPLY). It must print the plan and run nothing.
_ran_down: list = []
_ctx = b.Ctx()
_real_run2 = b.subprocess.run
b.subprocess.run = lambda cmd, **kw: _ran_down.append(cmd) or type("R", (), {"returncode": 0})()
try:
    _rc = b.cmd_down(_ctx, type("A", (), {"selectors": ["all"], "apply": False, "force": False, "dry_run": False})())
finally:
    b.subprocess.run = _real_run2
check("down without --apply runs no fleet.sh step at all", _rc == 0 and _ran_down == [], str(_ran_down)[:300])
print("== preflight before any spend, in each region ==")
r = subprocess.run([sys.executable, str(FLEET_DIR / "backups.py"), "up", "six-hours", "--dry-run"],
                   capture_output=True, text=True, timeout=120)
pre = [l for l in r.stdout.splitlines() if " preflight " in l]
check("up runs fleet.sh preflight once per region, for the default account alone",
      len(pre) == 3 and all("WIB_ATTENDEE_ACCOUNTS=accen-dev" in l for l in pre), r.stdout)
check("sized to that region's clusters in the wave (three each for six-hours)",
      all(l.endswith("fleet.sh preflight 3") for l in pre), str(pre))
lines_ = r.stdout.splitlines()
check("and each preflight comes before its region's build",
      all(lines_.index(p) < lines_.index(next(l for l in lines_ if l.endswith("instructors up all")
                                              and l.split("WIB_REGION=")[1].split()[0] == p.split("WIB_REGION=")[1].split()[0]))
          for p in pre))
r = subprocess.run([sys.executable, str(FLEET_DIR / "backups.py"), "up", "six-hours", "--dry-run", "--no-preflight"],
                   capture_output=True, text=True, timeout=120)
check("--no-preflight leaves it out", " preflight " not in r.stdout)
r = subprocess.run([sys.executable, str(FLEET_DIR / "backups.py"), "preflight", "night-before", "--dry-run"],
                   capture_output=True, text=True, timeout=120)
check("backups.py preflight night-before: two clusters in each of three regions",
      sorted(l.split("WIB_REGION=")[1].split()[0] for l in r.stdout.splitlines() if l.endswith("preflight 2"))
      == ["us-east-1", "us-east-2", "us-west-2"], r.stdout + r.stderr)

print("== the teardown keeps a promoted standby and destroys the rest ==")
prom = T / "promoted-down.tsv"
prom.write_text("community\twatch-it-burn-community-b01\n")
r = subprocess.run([sys.executable, str(FLEET_DIR / "backups.py"), "down", "all", "--dry-run"],
                   capture_output=True, text=True, timeout=120, env={**os.environ, "WIB_PROMOTED_FILE": str(prom)})
downs = [l for l in r.stdout.splitlines() if l.endswith("instructors down all")]
check("the other 14 still come down", sum(l.count("|") // 6 for l in downs) == 14, r.stdout)
check("the holder is not among them", "watch-it-burn-community-b01|" not in r.stdout)
check("and the run says so and fails, so the cron log shows it",
      r.returncode == 1 and "KEEPING watch-it-burn-community-b01" in r.stderr, r.stderr[-400:])

print("== cron's restarts of the watcher outside its window exit at once ==")
far = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
gone = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
r = subprocess.run([sys.executable, str(FLEET_DIR / "backups.py"), "watch", "--from", far, "--until", far],
                   capture_output=True, text=True, timeout=120)
check("before --from it exits 0 and does nothing", r.returncode == 0 and "watch:" not in r.stderr, r.stderr[-300:])
r = subprocess.run([sys.executable, str(FLEET_DIR / "backups.py"), "watch", "--until", gone],
                   capture_output=True, text=True, timeout=120)
check("after --until it exits 0 and does nothing", r.returncode == 0 and "watch:" not in r.stderr, r.stderr[-300:])

check("a dry run writes no roster file",
      not {p.name for p in pathlib.Path(tempfile.gettempdir()).iterdir() if p.name.startswith("backups-")} - _tmp_before)

import shutil  # noqa: E402
shutil.rmtree(T, ignore_errors=True)
print()
if failures:
    print(f"FAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("ALL PASS")
