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
    check(f"{c.name}: its bootstrap profile is its roster cluster's",
          fleet("bootstrap_profile_for_role", want_role) == ("burn" if c.role == "community" else "admin"))
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
check("night-before stands up 18 hours out", by["night-before"].startswith("0 0 5 3 * /fleet/backups.py up night-before"))
check("six-hours stands up 6 hours out", by["six-hours"].startswith("0 12 5 3 * /fleet/backups.py up six-hours"))
check("the watcher starts an hour after the night-before wave and stops 90 minutes after the start",
      by["watch"].startswith("0 1 5 3 * /fleet/backups.py watch --until 2030-03-05T19:30:00Z"))
check("the standbys come down two hours after the start, and the lines remove themselves",
      by["down"].startswith("0 20 5 3 * /fleet/backups.py down all --apply") and "unschedule" in by["down"])
mt = b.schedule_lines(start, zoneinfo.ZoneInfo("America/Denver"), pathlib.Path("/fleet"))
check("in the cron host's own time zone", any(l.startswith("0 17 4 3 * /fleet/backups.py up night-before") for l in mt))
check("every line is tagged so unschedule finds it", all(b.CRON_TAG in l for l in lines))
try:
    b.parse_when("2030-03-05T18:00:00")
    check("a start with no UTC offset is refused", False)
except SystemExit:
    check("a start with no UTC offset is refused", True)

print("== up and down, dry run: one fleet.sh run per region, standbys kept out of the router ==")
r = subprocess.run([sys.executable, str(FLEET_DIR / "backups.py"), "up", "night-before", "--dry-run"],
                   capture_output=True, text=True, timeout=120)
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
check("a dry run writes no roster file", not any(p.name.startswith("backups-") for p in pathlib.Path(tempfile.gettempdir()).iterdir()))

import shutil  # noqa: E402
shutil.rmtree(T, ignore_errors=True)
print()
if failures:
    print(f"FAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("ALL PASS")
