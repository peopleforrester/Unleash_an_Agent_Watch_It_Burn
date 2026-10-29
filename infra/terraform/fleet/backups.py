#!/usr/bin/env python3
# ABOUTME: Standby clusters for attackme and burritobot-private (#643): builds backups.tsv's waves region by region,
# ABOUTME: self-checks each console, and hands a role's hostname to the next healthy standby with nobody acting.
"""Standbys for the two roster hostnames, and the watcher that promotes them.

    backups.py list                         the standbys, their region, wave and promotion order
    backups.py up <wave|name...>            build them, one fleet.sh run per region, then self-check each one
    backups.py down <wave|all|name...>      destroy them (dry run unless --apply); refuses a cluster that
                                            holds a hostname
    backups.py check [name...]              self-check clusters on their own console LB; exit 1 on any failure
    backups.py status                       which cluster each hostname is routed to now
    backups.py watch [--until T]            the automatic promotion loop
    backups.py promote <role> <name>        hand a role's hostname to a named cluster now (failing back, or a drill)
    backups.py schedule <session-start>     the crontab lines for both waves, the watcher and the teardown
    backups.py unschedule                   remove those lines

The self-check runs against a cluster's console load balancer directly, never through the router, with the Host
header of the role's hostname, so it asks exactly what the router would ask:

    GET /healthz    200 "ok"                   the console's nginx is up
    GET /           200, titled BurritoBot     the storefront the room opens
    GET /controls   200 and a JSON object      guard-proxy answers
    POST /chat      200 and a non-empty reply  the agent, the gateway and Bedrock answer (one model call,
                                               carrying the probe marker, so it never reaches the prompt wall)

`watch` checks the cluster each hostname is routed to every --interval seconds (the chat part every --chat-every
ticks). After --fail-after failures in a row it walks the role's pool in backups.tsv order, starting after the
cluster that failed and wrapping round, self-checks each standby in full and gives the hostname to the first that
passes: every row of the apex router's table that pointed at the failed console LB, the burritobot.co twins and
the service hosts included, is repointed at the new one, and the table is applied to the live router with the
apex repo's reload script. promoted.tsv records the holder so a later `fleet.sh routes roster` keeps it. Nothing
fails back on its own: a cluster that failed once is not trusted with the room again until a person says so with
`promote`.

Every kubectl call is made with an isolated kubeconfig and an explicit --context, and every aws call with an
explicit AWS_PROFILE and --region (AGENTS.md, kube-context safety).
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import pathlib
import shlex
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zoneinfo
from dataclasses import dataclass
from typing import Callable, Iterable

HERE = pathlib.Path(__file__).resolve().parent
FLEET = HERE / "fleet.sh"
ROLES = ("community", "admin")
WAVES = ("night-before", "six-hours")
# Hours before the session start each wave stands up, and when the watcher starts and the standbys come down.
WAVE_LEAD_HOURS = {"night-before": 18, "six-hours": 6}
WATCH_FROM_HOURS = 17      # an hour after the night-before wave starts, once its standbys can be checked
WATCH_UNTIL_MINUTES = 90   # after the session start: the 30-minute session and an hour's margin
DOWN_AFTER_MINUTES = 120
CRON_TAG = "# wib-backups (#643)"
PROBE_MARKER = "[[wib-probe]]"   # guard-proxy answers it normally and keeps it out of the feed the room sees
CHAT_PROMPT = f"{PROBE_MARKER} name one salsa"
STOREFRONT_TITLE = "<title>BurritoBot</title>"
# Where linuxbrew keeps terraform, aws, kubectl and helm; cron's PATH has none of them (scheduled-up.sh).
EXTRA_PATH = ["/home/linuxbrew/.linuxbrew/bin", "/home/linuxbrew/.linuxbrew/sbin",
              str(pathlib.Path.home() / ".local/bin"), "/usr/local/bin", "/usr/bin", "/bin"]


def log(msg: str) -> None:
    print(f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ}  {msg}", file=sys.stderr, flush=True)


@dataclass(frozen=True)
class Cluster:
    name: str
    role: str
    region: str
    wave: str          # "roster" for the role's own roster cluster


# --- the fleet's own settings and naming rules, read from fleet.sh rather than restated ------------------------
def fleet_env() -> dict[str, str]:
    """The settings backups.py shares with fleet.sh, as fleet.sh resolves them."""
    names = ["WIB_DEFAULT_ACCOUNT", "WIB_REGION", "WIB_HOME_REGION", "WIB_APEX_DIR", "STATE_DIR", "LOG_DIR",
             "LAB_VPC_DIR", "WIB_BACKUPS_FILE", "WIB_PROMOTED_FILE", "WIB_ROSTER_FILE", "WIB_EVENT"]
    script = f'source {shlex.quote(str(FLEET))} >/dev/null 2>&1; ' + "; ".join(
        f'printf "%s=%s\\n" {n} "${{{n}}}"' for n in names)
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, cwd=HERE)
    env = dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)
    missing = [n for n in names if not env.get(n)]
    if missing:
        raise SystemExit(f"backups: could not read {', '.join(missing)} from {FLEET}: {out.stderr.strip()[-300:]}")
    return env


def fleet_call(func: str, *args: str) -> str:
    """One fleet.sh function's output, e.g. public_host_for watch-it-burn-community."""
    script = f'source {shlex.quote(str(FLEET))} >/dev/null 2>&1; {func} ' + " ".join(shlex.quote(a) for a in args)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, cwd=HERE).stdout.strip()


def read_rows(path: pathlib.Path) -> list[list[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = "".join(line.split())
        if line and not line.startswith("#"):
            rows.append(line.split("|"))
    return rows


def load_pools(roster: pathlib.Path, backups: pathlib.Path, home_region: str) -> dict[str, list[Cluster]]:
    """Each role's pool in promotion order: its roster cluster, then its standbys in backups.tsv order."""
    pools: dict[str, list[Cluster]] = {r: [] for r in ROLES}
    for row in read_rows(roster):
        if row[1] in pools and not pools[row[1]]:
            pools[row[1]].append(Cluster(row[0], row[1], home_region, "roster"))
    for row in read_rows(backups):
        name, role, region, wave = (row + ["", "", "", ""])[:4]
        if role not in pools:
            raise SystemExit(f"backups: {name} has role '{role}', not one of {', '.join(ROLES)}")
        if wave not in WAVES:
            raise SystemExit(f"backups: {name} has wave '{wave}', not one of {', '.join(WAVES)}")
        pools[role].append(Cluster(name, role, region, wave))
    return pools


# --- the apex router's table -----------------------------------------------------------------------------------
def table_rows(text: str) -> list[tuple[str, str]]:
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and not line.lstrip().startswith("#"):
            rows.append((parts[0], parts[1]))
    return rows


def upstream_of(text: str, host: str) -> str | None:
    """The upstream (LB:443) the table sends a host to, or None when it carries no row for it."""
    return next((up for h, up in table_rows(text) if h == host), None)


def repoint(text: str, old: str, new: str) -> tuple[str, int]:
    """Every row whose upstream is `old` now points at `new`; comments and every other row are kept as they are."""
    out, n = [], 0
    for line in text.splitlines(keepends=True):
        parts = line.split()
        if len(parts) >= 2 and not line.lstrip().startswith("#") and parts[1] == old:
            out.append(f"{parts[0]}  {new}\n"); n += 1
        else:
            out.append(line)
    return "".join(out), n


def read_promoted(path: pathlib.Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return dict(line.split("\t", 1) for line in path.read_text(encoding="utf-8").splitlines() if "\t" in line)


def write_promoted(path: pathlib.Path, holders: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(f"{r}\t{n}\n" for r, n in sorted(holders.items())), encoding="utf-8")
    tmp.replace(path)


# --- the self-check --------------------------------------------------------------------------------------------
def self_check(base: str, host: str, chat: bool = True, timeout: float = 10, chat_timeout: float = 60) -> tuple[bool, str]:
    """(passed, why) for one console. `base` is https://<lb> live, or a local test server's URL."""
    ctx = ssl.create_default_context()
    # The console answers with its own certificate, which names neither the LB nor the hostname; the router
    # does not verify it either (tls_insecure_skip_verify, #139). What is checked is that the console works.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    def call(path: str, body: dict | None = None, t: float = timeout) -> tuple[int, str]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Host": host}
        if data is not None:
            headers.update({"Content-Type": "application/json", "Origin": f"https://{host}"})
        req = urllib.request.Request(base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=t, context=ctx if base.startswith("https") else None) as r:
                return r.status, r.read(200_000).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return 0, str(getattr(e, "reason", e))

    code, body = call("/healthz")
    if code != 200 or body.strip() != "ok":
        return False, f"/healthz answered {code or body}"
    code, body = call("/")
    if code != 200 or STOREFRONT_TITLE not in body:
        return False, f"/ answered {code}" + ("" if code != 200 else " without the BurritoBot storefront")
    code, body = call("/controls")
    try:
        ok = code == 200 and isinstance(json.loads(body), dict)
    except ValueError:
        ok = False
    if not ok:
        return False, f"/controls answered {code}" + ("" if code != 200 else " with no JSON object")
    if chat:
        code, body = call("/chat", {"prompt": CHAT_PROMPT}, t=chat_timeout)
        try:
            reply = (json.loads(body).get("reply") or "").strip() if code == 200 else ""
        except (ValueError, AttributeError):
            reply = ""
        if not reply:
            return False, f"/chat answered {code or body} with no reply"
    return True, "healthy" + ("" if chat else " (no chat this tick)")


# --- AWS: a cluster's console LB -------------------------------------------------------------------------------
def console_lb(c: Cluster, account: str) -> str | None:
    """The console Service's LB hostname, read with an isolated kubeconfig and the cluster's own context."""
    with tempfile.TemporaryDirectory() as d:
        kcfg = os.path.join(d, "kubeconfig")
        env = {**os.environ, "AWS_PROFILE": account}
        try:
            r = subprocess.run(["aws", "eks", "update-kubeconfig", "--kubeconfig", kcfg, "--name", c.name,
                                "--region", c.region], capture_output=True, text=True, timeout=45, env=env)
            if r.returncode != 0:
                return None
            ctx = subprocess.run(["kubectl", "--kubeconfig", kcfg, "config", "current-context"],
                                 capture_output=True, text=True, timeout=15, env=env).stdout.strip()
            if not ctx.endswith(f"/{c.name}"):   # rule 8: the context must be the cluster asked for
                log(f"  {c.name}: its kubeconfig points at '{ctx or 'nothing'}', not this cluster; not used")
                return None
            r = subprocess.run(["kubectl", "--kubeconfig", kcfg, "--context", ctx, "-n", "agent", "get", "svc",
                                "console", "-o", "jsonpath={.status.loadBalancer.ingress[0].hostname}"],
                               capture_output=True, text=True, timeout=30, env=env)
        except (subprocess.TimeoutExpired, OSError):
            return None
        return r.stdout.strip() or None


# --- promotion -------------------------------------------------------------------------------------------------
class Router:
    """The apex router's table: the checkout's routes.map, applied with the apex repo's reload script."""

    def __init__(self, apex_dir: pathlib.Path, retries: int = 3, backoff: float = 20):
        self.table = apex_dir / "routes.map"
        self.reload = apex_dir / "scripts" / "reload-routes.sh"
        self.retries, self.backoff = retries, backoff

    def read(self) -> str:
        return self.table.read_text(encoding="utf-8")

    def write(self, text: str) -> None:
        tmp = self.table.with_suffix(".map.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.table)

    def apply(self) -> bool:
        if not os.access(self.reload, os.X_OK):
            log(f"  router: no reload script at {self.reload}; the table is NOT live")
            return False
        for attempt in range(1, self.retries + 1):
            if subprocess.run(["bash", str(self.reload), str(self.table)], timeout=300).returncode == 0:
                log(f"  router: applied (attempt {attempt})")
                return True
            log(f"  router: reload attempt {attempt} failed")
            if attempt < self.retries:
                time.sleep(self.backoff)
        return False


class Watcher:
    """Holds each role's hostname on a healthy cluster. Every outside effect is injected, so it is testable."""

    def __init__(self, pools: dict[str, list[Cluster]], hosts: dict[str, str], router: Router,
                 promoted: pathlib.Path, events: pathlib.Path, lb_of: Callable[[Cluster], str | None],
                 check: Callable[[str, str, bool], tuple[bool, str]], fail_after: int = 3, drill: str = ""):
        self.pools, self.hosts, self.router = pools, hosts, router
        self.promoted, self.events = promoted, events
        self.lb_of, self._check, self.fail_after, self.drill = lb_of, check, fail_after, drill
        self.fails = {r: 0 for r in pools}
        self.lbs: dict[str, str | None] = {}

    def refresh(self) -> None:
        for pool in self.pools.values():
            for c in pool:
                self.lbs[c.name] = self.lb_of(c)

    def check(self, upstream: str, host: str, chat: bool) -> tuple[bool, str]:
        lb = upstream.rsplit(":", 1)[0]
        if self.drill and self.lbs.get(self.drill) == lb:
            return False, f"drill: {self.drill} is treated as failing"
        return self._check(lb, host, chat)

    def holder(self, upstream: str) -> Cluster | None:
        for pool in self.pools.values():
            for c in pool:
                if self.lbs.get(c.name) and f"{self.lbs[c.name]}:443" == upstream:
                    return c
        return None

    def event(self, **fields) -> None:
        self.events.parent.mkdir(parents=True, exist_ok=True)
        with self.events.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ}", **fields}) + "\n")

    def tick(self, chat: bool = True) -> None:
        for role in self.pools:
            self.tick_role(role, chat)

    def tick_role(self, role: str, chat: bool) -> None:
        host = self.hosts[role]
        try:
            table = self.router.read()
        except OSError as e:
            log(f"{role}: cannot read the router table: {e}"); return
        up = upstream_of(table, host)
        if up is None:
            log(f"{role}: the router table has no row for {host}; run 'fleet.sh routes roster'"); return
        held = self.holder(up)
        name = held.name if held else f"an unknown cluster at {up}"
        ok, why = self.check(up, host, chat)
        if ok:
            if self.fails[role]:
                log(f"{role}: {host} on {name} is healthy again after {self.fails[role]} failed check(s)")
            self.fails[role] = 0
            return
        self.fails[role] += 1
        log(f"{role}: {host} on {name} FAILED its self-check ({self.fails[role]}/{self.fail_after}): {why}")
        if self.fails[role] < self.fail_after:
            return
        cand = self.next_healthy(role, held, up, host)
        if cand is None:
            log(f"{role}: NO healthy standby to take {host}; it stays on {name}, and the next tick tries again")
            self.event(role=role, host=host, failed=name, why=why, promoted=None)
            return
        if self.promote(role, cand, up, table, why=why, failed=name):
            self.fails[role] = 0

    def next_healthy(self, role: str, held: Cluster | None, failed_up: str, host: str) -> Cluster | None:
        pool = self.pools[role]
        start = pool.index(held) + 1 if held in pool else 0
        for c in pool[start:] + pool[:start]:
            lb = self.lbs.get(c.name)
            if c == held or not lb or f"{lb}:443" == failed_up:
                continue
            ok, why = self.check(f"{lb}:443", host, True)
            log(f"  {role}: candidate {c.name} ({c.region}): {'passes' if ok else 'fails: ' + why}")
            if ok:
                return c
        return None

    def promote(self, role: str, c: Cluster, old_up: str, table: str, why: str = "", failed: str = "") -> bool:
        host, new_up = self.hosts[role], f"{self.lbs[c.name]}:443"
        text, n = repoint(table, old_up, new_up)
        if n == 0:
            log(f"{role}: no row of the table points at {old_up}; nothing to repoint"); return False
        self.router.write(text)
        if not self.router.apply():
            self.router.write(table)
            log(f"{role}: the router did NOT take the new table, so {host} stays on {failed or old_up}; "
                f"the table on disk is put back and the next tick tries again")
            self.event(role=role, host=host, failed=failed, why=why, promoted=c.name, applied=False)
            return False
        holders = read_promoted(self.promoted)
        if c.wave == "roster":
            holders.pop(role, None)
        else:
            holders[role] = c.name
        write_promoted(self.promoted, holders)
        log(f"{role}: PROMOTED {c.name} ({c.region}): {n} host(s) now route to {new_up}, {host} included")
        self.event(role=role, host=host, failed=failed, why=why, promoted=c.name, region=c.region, rows=n,
                   applied=True)
        return True


# --- the commands ----------------------------------------------------------------------------------------------
class Ctx:
    def __init__(self) -> None:
        self.env = fleet_env()
        self.account = self.env["WIB_DEFAULT_ACCOUNT"]
        self.home = self.env["WIB_HOME_REGION"]
        self.pools = load_pools(pathlib.Path(self.env["WIB_ROSTER_FILE"]), pathlib.Path(self.env["WIB_BACKUPS_FILE"]),
                                self.env["WIB_REGION"])
        self.hosts = {r: fleet_call("public_host_for", p[0].name) for r, p in self.pools.items() if p}
        self.promoted = pathlib.Path(self.env["WIB_PROMOTED_FILE"])
        self.logs = pathlib.Path(self.env["LOG_DIR"])

    def standbys(self) -> list[Cluster]:
        return [c for p in self.pools.values() for c in p if c.wave != "roster"]

    def select(self, sels: Iterable[str], allow_all: bool = False) -> list[Cluster]:
        out = []
        for s in sels:
            if s in WAVES:
                out += [c for c in self.standbys() if c.wave == s]
            elif allow_all and s == "all":
                out += self.standbys()
            else:
                hit = [c for p in self.pools.values() for c in p if c.name == s]
                if not hit:
                    raise SystemExit(f"backups: '{s}' is not a wave ({', '.join(WAVES)}) or a cluster backups.tsv lists")
                out += hit
        return list(dict.fromkeys(out))

    def router(self) -> Router:
        return Router(pathlib.Path(self.env["WIB_APEX_DIR"]), int(os.environ.get("WIB_RELOAD_RETRIES", "3")),
                      float(os.environ.get("WIB_RELOAD_BACKOFF", "20")))


def by_region(cs: list[Cluster]) -> dict[str, list[Cluster]]:
    groups: dict[str, list[Cluster]] = {}
    for c in cs:
        groups.setdefault(c.region, []).append(c)
    return groups


def roster_row_for(c: Cluster, roster: pathlib.Path) -> str:
    """The standby's roster.tsv row: its role's roster cluster's row under the standby's name."""
    row = next(r for r in read_rows(roster) if r[1] == c.role)
    return "|".join([c.name] + row[1:6] + [""])


def run_env() -> dict[str, str]:
    path = os.environ.get("PATH", "/usr/bin:/bin").split(":")
    return {**os.environ, "PATH": ":".join(path + [p for p in EXTRA_PATH if p not in path])}


def vpc_state(x: Ctx, region: str) -> pathlib.Path | None:
    """The lab VPC state a run in `region` reads (fleet.sh lab_vpc_state_for), None in the home region."""
    if region == x.home:
        return None
    return pathlib.Path(x.env["LAB_VPC_DIR"]) / "states" / f"{x.account}.{region}.tfstate"


def cmd_list(x: Ctx, _a) -> int:
    for role, pool in x.pools.items():
        print(f"{role}  ->  {x.hosts.get(role, '?')}")
        for i, c in enumerate(pool):
            print(f"  {i:>2}  {c.name:<30} {c.region:<10} {c.wave}")
    return 0


def region_steps(x: Ctx, region: str, cs: list[Cluster], verb: str, apply: bool = False) -> list[tuple[dict, list[str]]]:
    """The fleet.sh runs that build (verb up) or destroy (verb down) one region's standbys. The roster file is a
    placeholder here; run_steps writes it. Standbys stay out of the router (WIB_NO_ROUTES), the provisioning pool
    (WIB_NO_INGEST) and the walkthrough, which reaches a cluster by its routed hostname: after a build each one is
    converged (repairs, the Bedrock pin in its region, the Datadog verifier) and then self-checked on its own LB."""
    env = {"WIB_ROSTER_FILE": "<roster>", "WIB_REGION": region, "WIB_NO_ROUTES": "1", "WIB_NO_INGEST": "1"}
    if verb == "up":
        return [({**env, "WIB_NO_VERIFY": "1"}, [str(FLEET), "instructors", "up", "all"]),
                ({"WIB_REGION": region}, [str(FLEET), "converge"] + [c.name for c in cs])]
    return [({**env, **({"WIB_APPLY": "1"} if apply else {})}, [str(FLEET), "instructors", "down", "all"])]


def run_steps(x: Ctx, region: str, cs: list[Cluster], steps: list[tuple[dict, list[str]]], dry_run: bool) -> int:
    rows = "".join(roster_row_for(c, pathlib.Path(x.env["WIB_ROSTER_FILE"])) + "\n" for c in cs)
    tmp = None
    try:
        for e, cmd in steps:
            if e.get("WIB_ROSTER_FILE") == "<roster>":
                if dry_run:
                    e = {**e, "WIB_ROSTER_FILE": "<" + " ".join(rows.split()) + ">"}
                else:
                    if tmp is None:
                        fd, tmp = tempfile.mkstemp(suffix=".tsv", prefix=f"backups-{region}-")
                        with os.fdopen(fd, "w") as f:
                            f.write(rows)
                    e = {**e, "WIB_ROSTER_FILE": tmp}
            line = " ".join(f"{k}={shlex.quote(v)}" for k, v in e.items()) + " " + shlex.join(cmd)
            if dry_run:
                print(line); continue
            log(f"{region}: {line}")
            if subprocess.run(cmd, env={**run_env(), **e}, cwd=HERE).returncode != 0:
                log(f"{region}: that step failed"); return 1
    finally:
        if tmp:
            os.unlink(tmp)
    return 0


def cmd_up(x: Ctx, a) -> int:
    targets = x.select(a.selectors)
    rc = 0
    for region, cs in by_region(targets).items():
        state = vpc_state(x, region)
        if state is not None and not state.exists():
            lab = x.env["LAB_VPC_DIR"]
            log(f"up: {region} has no lab VPC for {x.account}. Apply it first:")
            log(f"  terraform -chdir={lab} init && terraform -chdir={lab} apply -state=states/{state.name} "
                f"-var profile={x.account} -var region={region} -var event={x.env['WIB_EVENT']}")
            rc = 1
            if not a.dry_run:
                continue
        rc |= run_steps(x, region, cs, region_steps(x, region, cs, "up"), a.dry_run)
    if a.dry_run:
        return rc
    return check_clusters(x, targets) | rc


def check_clusters(x: Ctx, cs: list[Cluster], chat: bool = True) -> int:
    rc = 0
    for c in cs:
        lb = console_lb(c, x.account)
        if not lb:
            ok, why = False, "no console LB (cluster unreachable, or the Service has no hostname yet)"
        else:
            ok, why = self_check(f"https://{lb}", x.hosts[c.role], chat)
        print(f"  {'PASS' if ok else 'FAIL'}  {c.name:<30} {c.region:<10} {why}")
        rc |= 0 if ok else 1
    return rc


def cmd_check(x: Ctx, a) -> int:
    cs = x.select(a.names) if a.names else [c for p in x.pools.values() for c in p]
    return check_clusters(x, cs, chat=not a.no_chat)


def cmd_down(x: Ctx, a) -> int:
    targets = x.select(a.selectors, allow_all=True)
    holders = set(read_promoted(x.promoted).values())
    held = [c.name for c in targets if c.name in holders]
    if held and not a.force:
        log(f"down: REFUSING: {', '.join(held)} holds a hostname now. Promote another cluster first, or pass --force.")
        return 1
    rc = 0
    for region, cs in by_region(targets).items():
        rc |= run_steps(x, region, cs, region_steps(x, region, cs, "down", a.apply), a.dry_run)
    return rc


def make_watcher(x: Ctx, a) -> Watcher:
    return Watcher(x.pools, x.hosts, x.router(), x.promoted, x.logs / "failover.jsonl",
                   lb_of=lambda c: console_lb(c, x.account),
                   check=lambda lb, host, chat: self_check(f"https://{lb}", host, chat),
                   fail_after=getattr(a, "fail_after", 3), drill=getattr(a, "drill", "") or "")


def cmd_status(x: Ctx, a) -> int:
    w = make_watcher(x, a)
    w.refresh()
    table = w.router.read()
    holders = read_promoted(x.promoted)
    for role, host in x.hosts.items():
        up = upstream_of(table, host)
        held = w.holder(up) if up else None
        print(f"{role}  {host}  ->  {held.name + ' (' + held.region + ')' if held else up or 'NO ROW'}"
              f"   promoted.tsv: {holders.get(role, 'none (the roster cluster)')}")
    return 0


def parse_when(s: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise SystemExit(f"backups: '{s}' has no UTC offset; give one, e.g. 2030-01-01T18:00:00Z")
    return t


def cmd_watch(x: Ctx, a) -> int:
    until = parse_when(a.until) if a.until else None
    x.logs.mkdir(parents=True, exist_ok=True)
    lock = (x.logs / ".backups-watch.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("watch: another watcher holds the lock; exiting"); return 1
    w = make_watcher(x, a)
    log(f"watch: {', '.join(f'{r} {h}' for r, h in x.hosts.items())}; every {a.interval}s, chat every "
        f"{a.chat_every} tick(s), promoting after {a.fail_after} failures in a row"
        + (f", until {until:%Y-%m-%dT%H:%M:%SZ}" if until else "") + (f"; DRILL on {a.drill}" if a.drill else ""))
    tick, refreshed = 0, 0.0
    while until is None or dt.datetime.now(dt.timezone.utc) < until:
        if time.monotonic() - refreshed > a.refresh or not refreshed:
            w.refresh(); refreshed = time.monotonic()
            log("watch: console LBs: " + ", ".join(f"{n}={'yes' if lb else 'none'}" for n, lb in w.lbs.items()))
        w.tick(chat=tick % a.chat_every == 0)
        tick += 1
        time.sleep(a.interval)
    log("watch: --until reached; exiting")
    return 0


def cmd_promote(x: Ctx, a) -> int:
    if a.role not in x.pools:
        raise SystemExit(f"backups: role must be one of {', '.join(ROLES)}")
    c = next((c for c in x.pools[a.role] if c.name == a.name), None)
    if c is None:
        raise SystemExit(f"backups: {a.name} is not in the {a.role} pool")
    w = make_watcher(x, a)
    w.refresh()
    if not w.lbs.get(c.name):
        log(f"promote: {c.name} has no console LB"); return 1
    ok, why = self_check(f"https://{w.lbs[c.name]}", x.hosts[a.role], True)
    if not ok and not a.force:
        log(f"promote: REFUSING: {c.name} fails its self-check ({why}); --force overrides"); return 1
    table = w.router.read()
    up = upstream_of(table, x.hosts[a.role])
    if up is None:
        log(f"promote: the router table has no row for {x.hosts[a.role]}; run 'fleet.sh routes roster'"); return 1
    held = w.holder(up)
    return 0 if w.promote(a.role, c, up, table, why="by hand", failed=held.name if held else up) else 1


def schedule_lines(start: dt.datetime, tz: dt.tzinfo, here: pathlib.Path = HERE) -> list[str]:
    """Crontab lines for one session, in the cron host's time zone. Cron has no year, so `unschedule` (the
    teardown line runs it) removes them once the session is over."""
    def at(t: dt.datetime, cmd: str, what: str) -> str:
        lt = t.astimezone(tz)
        return f"{lt.minute} {lt.hour} {lt.day} {lt.month} * {cmd}  {CRON_TAG} {what} {t.astimezone(dt.timezone.utc):%Y-%m-%dT%H:%MZ}"
    me = shlex.quote(str(here / "backups.py"))
    logs = shlex.quote(str(here / "logs"))
    until = start + dt.timedelta(minutes=WATCH_UNTIL_MINUTES)
    lines = [f"{CRON_TAG} session {start.astimezone(dt.timezone.utc):%Y-%m-%dT%H:%MZ}"]
    for wave in WAVES:
        lines.append(at(start - dt.timedelta(hours=WAVE_LEAD_HOURS[wave]),
                        f"{me} up {wave} >>{logs}/backups-{wave}.log 2>&1", wave))
    lines.append(at(start - dt.timedelta(hours=WATCH_FROM_HOURS),
                    f"{me} watch --until {until.astimezone(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ} >>{logs}/backups-watch.log 2>&1",
                    "watch"))
    lines.append(at(start + dt.timedelta(minutes=DOWN_AFTER_MINUTES),
                    f"{me} down all --apply >>{logs}/backups-down.log 2>&1; {me} unschedule", "down"))
    return lines


def cmd_schedule(_x, a) -> int:
    start = parse_when(a.session_start)
    tz = zoneinfo.ZoneInfo(a.tz) if a.tz else dt.datetime.now().astimezone().tzinfo
    print("\n".join(schedule_lines(start, tz)))
    log("schedule: append these to the crontab of the host that holds the fleet profiles: "
        "(crontab -l; backups.py schedule <start>) | crontab -")
    return 0


def cmd_unschedule(_x, _a) -> int:
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    keep = "".join(line + "\n" for line in cur.splitlines() if CRON_TAG not in line)
    subprocess.run(["crontab", "-"], input=keep, text=True, check=True)
    log("unschedule: removed the backups lines from the crontab")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="backups.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("up"); s.add_argument("selectors", nargs="+"); s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("down"); s.add_argument("selectors", nargs="+"); s.add_argument("--apply", action="store_true")
    s.add_argument("--force", action="store_true"); s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("check"); s.add_argument("names", nargs="*"); s.add_argument("--no-chat", action="store_true")
    sub.add_parser("status")
    s = sub.add_parser("watch")
    s.add_argument("--interval", type=float, default=15)
    s.add_argument("--chat-every", type=int, default=4, help="ticks between chat checks (each one is a model call)")
    s.add_argument("--fail-after", type=int, default=3)
    s.add_argument("--refresh", type=float, default=300, help="seconds between re-reading every console LB")
    s.add_argument("--until", help="UTC time to exit, e.g. 2030-01-01T19:30:00Z")
    s.add_argument("--drill", help="treat this cluster as failing: the rehearsal of a promotion")
    s = sub.add_parser("promote"); s.add_argument("role"); s.add_argument("name"); s.add_argument("--force", action="store_true")
    s = sub.add_parser("schedule"); s.add_argument("session_start"); s.add_argument("--tz")
    sub.add_parser("unschedule")
    a = p.parse_args(argv)
    if a.cmd == "watch" and a.chat_every < 1:
        p.error("--chat-every must be 1 or more")
    if a.cmd in ("schedule", "unschedule"):
        return {"schedule": cmd_schedule, "unschedule": cmd_unschedule}[a.cmd](None, a)
    x = Ctx()
    return {"list": cmd_list, "up": cmd_up, "down": cmd_down, "check": cmd_check, "status": cmd_status,
            "watch": cmd_watch, "promote": cmd_promote}[a.cmd](x, a)


if __name__ == "__main__":
    sys.exit(main())
