# ABOUTME: Offline checks for verify/stage_switch_run.py (#1183, #1351): talk order through TERMINAL_EXEC, each switch's printed
# ABOUTME: read, the -off switches on a failing, raising or interrupted switch, and both clusters' guard lock, all faked.
"""Runs the stage-switch command against a fake pair of clusters, with no cluster and no network.

FakeWorld answers every kubectl call the command and verify/guard_lease.py make: the Lease agent/wib-guard-lock and the
guardrails-peer name on each context, through one verify/fake_lease_kubectl.py FakeLeaseApi per context, the private
cluster's cluster-identity, and the terminal commands, which change the fake /controls the way the
terminal's own commands change the real ones, and end, as each real one does (_controls, #1349), on both clusters'
/controls printed by the entrypoint's own _ctlfmt code. The lock code is the real guard_lease.hold_switch, so "held" here means
a Lease naming this run was in the fake API on both contexts when each terminal command ran.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import pathlib
import re
import signal
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import guard_lease  # noqa: E402
import kubecon_probe as kp  # noqa: E402
from fake_lease_kubectl import FakeLeaseApi  # noqa: E402
import stage_switch_check as ssc  # noqa: E402
import stage_switch_run as ssr  # noqa: E402

PRIVATE, COMMUNITY = "watch-it-burn-private", "watch-it-burn-community"
ENTRY = REPO / "gitops/ai-layer/web-terminal/entrypoint.sh"
_term = ENTRY.read_text(encoding="utf-8")
_OPEN, _SHUT = "_ctlfmt() { python3 -c '", "' \"$1\"; }"
if _OPEN not in _term or _SHUT not in _term.split(_OPEN, 1)[1]:
    sys.exit(f"ANCHOR MISSING: the _ctlfmt() {{ python3 -c '...' \"$1\"; }} formatter in {ENTRY.relative_to(REPO)}")
CTLFMT = compile(_term.split(_OPEN, 1)[1].split(_SHUT, 1)[0], "_ctlfmt", "exec")


def ctlfmt(label: str, read: dict) -> str:
    """The terminal's _ctlfmt on one cluster's /controls, run in this process: what _controls prints for it."""
    out, argv, stdin = io.StringIO(), sys.argv, sys.stdin
    try:
        sys.argv, sys.stdin = ["-c", label], io.StringIO(json.dumps(read))
        with contextlib.redirect_stdout(out):
            exec(CTLFMT, {"__name__": "__main__"})
    finally:
        sys.argv, sys.stdin = argv, stdin
    return out.getvalue()
CONTEXT_OF = {"private": PRIVATE, "community": COMMUNITY}
TALK_ORDER = ["guardrails-k8s-on", "guardrails-agency-on", "guardrails-input-on", "guardrails-mcp-on"]

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def start_read(host: str, falco: bool, agency: bool) -> dict:
    """The shape both clusters' /controls answered on 2026-11-08; agency_scoped only once guard-proxy is repinned."""
    infra = {"networkpolicy": False, "kyverno": False, "kubearmor": False, "falco": falco, "tool_allowlist": False,
             "rbac_scoped": False}
    if agency:
        infra["agency_scoped"] = False
    return {"ai": {"input_blocklist": False, "input_classifier": False, "output": False, "budget": False,
                   "topic": False}, "infra": infra, "host": host}


class FakeWorld:
    """Both clusters as kubectl and HTTPS see them. `effects` maps a terminal command to the clusters it reaches."""

    def __init__(self, agency: bool = True) -> None:
        self.controls = {"private": start_read("burritobot-private.agenticburn.com", True, agency),
                         "community": start_read("attackme.agenticburn.com", False, agency)}
        self.agency = agency
        # Each cluster's own Lease; the private cluster's guardrails-peer names the community one.
        self.apis = {PRIVATE: FakeLeaseApi(peer=COMMUNITY), COMMUNITY: FakeLeaseApi(peer=PRIVATE)}
        self.events: list[tuple] = []
        self.identity = "burritobot-private.agenticburn.com"
        self.reach = {name: ("private", "community") for name in [*TALK_ORDER, *ssr.CLOSE]}
        # A command whose own closing read could not read a cluster, as _controls says it.
        self.unread: dict[str, tuple[str, ...]] = {}
        self.rc: dict[str, int] = {}
        self.raise_on: dict[str, BaseException] = {}
        self.during: dict[str, callable] = {}
        self.kubectl_calls: list[list[str]] = []
        self.terminal_kw: list[dict] = []

    # --- what each terminal command does to /controls ----------------------------------------------------------
    def _apply(self, name: str) -> None:
        on = name.endswith("-on")
        # Each -off turns off what its -on turned on, and nothing else.
        fields = ssc.SWITCHES[name if on else {off: n for n, off in ssc.OFF.items()}[name]]
        for cluster in self.reach[name]:
            for section, key in fields:
                if key == "agency_scoped" and not self.agency:
                    continue
                self.controls[cluster][section][key] = on

    def printed(self, name: str) -> str:
        """The read a switch ends on: both clusters' /controls by name, or the line saying one could not be read."""
        out = "Read back from guard-proxy's /controls, what each chat page's badges show:\n"
        for cluster, label in (("private", f"{PRIVATE} (this cluster)"), ("community", COMMUNITY)):
            if cluster in self.unread.get(name, ()):
                out += f"  ⚠️  {label}: /controls could not be read, so its state is not shown.\n"
            else:
                out += ctlfmt(label, self.controls[cluster])
        return out

    @property
    def leases(self) -> dict[str, dict]:
        return {c: api.lease for c, api in self.apis.items() if api.lease}

    def _lease_holders(self) -> dict[str, str]:
        return {c: (l.get("spec") or {}).get("holderIdentity", "") for c, l in self.leases.items()}

    # --- subprocess.run's shape ---------------------------------------------------------------------------------
    def run(self, cmd, capture_output=True, text=True, timeout=None, env=None, input=None, **kw):
        self.kubectl_calls.append(list(cmd))
        assert cmd[0] == "kubectl" and cmd[1] == "--context", cmd
        ctx, args = cmd[2], cmd[3:]

        def done(rc=0, out="", err=""):
            return subprocess.CompletedProcess(cmd, rc, out, err)

        if args[:len(kp.TERMINAL_EXEC)] == kp.TERMINAL_EXEC:
            name = args[-1].rsplit("/", 1)[-1]
            self.events.append(("terminal", name, ctx, dict(self._lease_holders())))
            self.terminal_kw.append(kw)
            if name in self.during:
                self.during[name]()
            if name in self.raise_on:
                raise self.raise_on[name]
            self._apply(name)
            return done(self.rc.get(name, 0), f"{name} ran\n" + self.printed(name))
        if "cluster-identity" in args:
            return done(0, self.identity)
        before = self.apis[ctx].lease
        p = self.apis[ctx].run(cmd, input=input)
        assert p.returncode != 9, p.stderr
        if before is None and self.apis[ctx].lease is not None:
            self.events.append(("lease-create", ctx))
        if before is not None and self.apis[ctx].lease is None:
            self.events.append(("lease-delete", ctx))
        return p

    def fetch(self, host: str):
        cluster = {h: c for c, h in ssc.CLUSTERS.items()}[host]
        self.events.append(("fetch", cluster))
        return json.dumps(self.controls[cluster]).encode()

    def sleep(self, s: float) -> None:
        self.events.append(("sleep", s))

    def terminals(self) -> list[str]:
        return [e[1] for e in self.events if e[0] == "terminal"]


def go(world: FakeWorld, argv: list[str] | None = None, **kw) -> tuple[int, str]:
    """main() against the world, its stdout and stderr captured together."""
    buf = io.StringIO()
    kw.setdefault("lease_kw", {"sleep": lambda s: None})
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = ssr.main(argv if argv is not None else ["--context", PRIVATE, "--lock-wait", "0"],
                        runner=world.run, fetch=world.fetch, sleep=world.sleep, **kw)
    return code, buf.getvalue()


def rows(text: str) -> dict[tuple[str, str], str]:
    """(step, cluster) -> PASS or FAIL, from the printed lines."""
    out = {}
    for m in re.finditer(r"^  (PASS|FAIL)  (\S+)\s+(\S+)\s", text, re.M):
        out[(m.group(2), m.group(3))] = m.group(1)
    return out


def held_by_us(world: FakeWorld) -> bool:
    """Every terminal command ran while both contexts' Leases named the same holder, this run's."""
    terms = [e for e in world.events if e[0] == "terminal"]
    return bool(terms) and all(set(e[3]) == {PRIVATE, COMMUNITY} and len(set(e[3].values())) == 1
                               and "stage_switch_run.py" in next(iter(e[3].values())) for e in terms)


# --- the commands, held to the probe's and the terminal's ------------------------------------------------------

check(list(ssr.SWITCHES) == TALK_ORDER, "the switches run in talk order, the judge's own list")
check(ssr.CLOSE == ("guardrails-mcp-off", "guardrails-input-off", "guardrails-agency-off", "guardrails-k8s-off"),
      f"the run closes with each switch's -off, the last switch first ({ssr.CLOSE})")
check(ssr.terminal_command("guardrails-k8s-on") == kp.GUARDRAILS_ON
      and ssr.terminal_command("guardrails-k8s-off") == kp.GUARDRAILS_OFF,
      "guardrails-k8s-on and guardrails-k8s-off are the probe's own terminal commands")
check(all(ssr.terminal_command(n)[:len(kp.TERMINAL_EXEC)] == kp.TERMINAL_EXEC for n in [*TALK_ORDER, *ssr.CLOSE]),
      "every command runs through the probe's TERMINAL_EXEC")
for entry in ("gitops/ai-layer/web-terminal/entrypoint.sh", "images/web-terminal/entrypoint.sh"):
    text = (REPO / entry).read_text(encoding="utf-8")
    # The run types the names since #1350 (#1351), each a heredoc of its own, not an alias of one.
    missing = [n for n in [*TALK_ORDER, *ssr.CLOSE] if text.count(f'cat > "$HOME/{n}" <<') != 1]
    check(not missing, f"{entry} writes every command the run types into /home/student (missing: {missing})")
src = (REPO / "verify/stage_switch_run.py").read_text(encoding="utf-8")
check("terminal-auth" not in src.replace("agent/terminal-auth Secret: it runs", "")
      and "TTYD_CREDENTIAL" not in src,
      "the command never names the presenter terminal login's Secret beyond saying it does not touch it")
check(ssr.START_ALSO == (("ai", "output"), ("ai", "budget"), ("ai", "topic"))
      and ssr.START_FIELDS == (*(f for fs in ssc.SWITCHES.values() for f in fs), *ssr.START_ALSO),
      "the start-state fields are every switch's fields plus the AI guards no switch here turns on")
for name in [*TALK_ORDER, *ssr.CLOSE]:
    check(name not in ("guardrails-on", "guardrails-off", "guards-off") and not name.startswith("guard-"),
          f"{name} is a name since #1350, not an old alias")

# --- no context: nothing is run ---------------------------------------------------------------------------------

w = FakeWorld()
code, text = go(w, argv=[])
check(code == 2 and not w.kubectl_calls and "needs --context" in text,
      "with no --context it exits 2, saying so, before any kubectl call")
try:
    ssr.StageSwitchRun("")
    check(False, "StageSwitchRun refuses an empty context")
except ValueError:
    check(True, "StageSwitchRun refuses an empty context")

# --- every switch reaches both clusters (guard-proxy repinned) --------------------------------------------------

w = FakeWorld(agency=True)
code, text = go(w)
r = rows(text)
check(code == 0 and "STAGE SWITCH CHECK GREEN" in text, f"all four switches on both clusters: exit 0, GREEN ({code})")
check(w.terminals() == [*TALK_ORDER, *ssr.CLOSE],
      f"the terminal ran the switches in talk order, then each -off, last first ({w.terminals()})")
check(all(r.get((s, c)) == "PASS" for s in TALK_ORDER for c in ssc.CLUSTERS),
      "PASS is printed per switch per cluster")
check(all(r.get((s, f"{c}/printed")) == "PASS" for s in [*TALK_ORDER, *ssr.CLOSE] for c in ssc.CLUSTERS),
      "the read each switch and each -off printed at its end is PASS per cluster")
check(sum(1 for k in r if k[1].endswith("/printed")) == 2 * (len(TALK_ORDER) + len(ssr.CLOSE)),
      "one printed-read line per command per cluster")
check(all(r.get((s, "terminal")) is None for s in [*TALK_ORDER, *ssr.CLOSE]), "no terminal FAIL line on a clean run")
check(all(r.get((s, c)) == "PASS" for s in ("start-state", "as-found") for c in ssc.CLUSTERS),
      "both clusters are back at the start state and as found")
check(all(c[2] == PRIVATE for c in w.kubectl_calls if c[3:3 + len(kp.TERMINAL_EXEC)] == kp.TERMINAL_EXEC),
      "every terminal command runs in the private cluster's terminal")
check(all(c[1] == "--context" for c in w.kubectl_calls), "every kubectl call names its --context")
check(all(kw.get("start_new_session") for kw in w.terminal_kw),
      "every terminal command runs in a session of its own, so a ^C reaches the script, not the command midway")
check(held_by_us(w), "every terminal command, the closing four included, ran with this run's Lease on both clusters")
first_create = next(i for i, e in enumerate(w.events) if e[0] == "lease-create")
first_fetch = next(i for i, e in enumerate(w.events) if e[0] == "fetch")
last_fetch = max(i for i, e in enumerate(w.events) if e[0] == "fetch")
deletes = [i for i, e in enumerate(w.events) if e[0] == "lease-delete"]
check(first_create < first_fetch and len(deletes) == 2 and min(deletes) > last_fetch,
      "the lock is taken before the first /controls read and released after the last")
check(sorted(e[1] for e in w.events if e[0] == "lease-create") == [COMMUNITY, PRIVATE] and not w.leases,
      "the lock is taken on both clusters and nothing is left in either")
# After each terminal command, the cache is waited out before both clusters are read.
ok = True
for i, e in enumerate(w.events):
    if e[0] == "terminal" and e[1] not in ssr.CLOSE[:-1]:
        nxt = [x for x in w.events[i + 1:] if x[0] in ("sleep", "fetch", "terminal")]
        if not nxt or nxt[0][0] != "sleep" or nxt[0][1] < 5.0:
            ok = False
check(ok, "after each switch, and after the closing four, it waits out guard-proxy's 5-second cache before reading")
check(sum(1 for e in w.events if e[0] == "fetch") == 2 * (1 + len(TALK_ORDER) + 1),
      "both clusters are read once at the start, once after each switch and once after the closing four")

# --- a switch whose own read does not show it ---------------------------------------------------------------------

w = FakeWorld()
w.unread["guardrails-input-on"] = ("community",)
code, text = go(w)
r = rows(text)
check(code == 1 and r.get(("guardrails-input-on", "community")) == "PASS"
      and r.get(("guardrails-input-on", "community/printed")) == "FAIL"
      and r.get(("guardrails-input-on", "private/printed")) == "PASS",
      "a switch whose closing read could not read the community cluster is FAIL there, though /controls shows it on")
check("could not be read" in text and "STAGE SWITCH CHECK RED" in text, "the FAIL quotes the terminal's warning")

# --- a guard-proxy that sends no agency_scoped (the pin before #1132) ---------------------------------------

w = FakeWorld(agency=False)
code, text = go(w)
r = rows(text)
check(code == 1 and "STAGE SWITCH CHECK RED" in text, "without agency_scoped the run is RED, exit 1")
check(r.get(("start", "private")) == "PASS" and r.get(("start", "community")) == "PASS",
      "a field the pinned guard-proxy does not send yet does not stop the run from starting")
check(all(r.get(("guardrails-agency-on", c)) == "FAIL" and r.get(("guardrails-agency-on", f"{c}/printed")) == "FAIL"
          for c in ssc.CLUSTERS)
      and all(r.get((s, c)) == "PASS" for s in ("guardrails-k8s-on", "guardrails-input-on", "guardrails-mcp-on")
              for c in ssc.CLUSTERS),
      "guardrails-agency-on is FAIL on both clusters, the other three PASS")
check(all(r.get(("start-state", c)) == "FAIL" and r.get(("as-found", c)) == "PASS" for c in ssc.CLUSTERS),
      "the start state is FAIL (agency_scoped cannot be read as off) while as-found is PASS")
m = re.search(r"^waiting on #1132 .*$", text, re.M)
check(bool(m) and "guardrails-agency-on on private, community" in m.group(0)
      and "start-state on private, community" in m.group(0),
      f"the summary names what waits on #1132, per cluster ({m.group(0) if m else 'no line'})")
check(w.terminals() == [*TALK_ORDER, *ssr.CLOSE] and held_by_us(w), "the closing four still ran, under the lock")

# --- a switch that does not reach the room's cluster ------------------------------------------------------------

w = FakeWorld()
w.reach["guardrails-input-on"] = ("private",)
w.rc["guardrails-input-on"] = 1
code, text = go(w)
r = rows(text)
check(code == 1 and r.get(("guardrails-input-on", "private")) == "PASS"
      and r.get(("guardrails-input-on", "community")) == "FAIL"
      and r.get(("guardrails-input-on", "community/printed")) == "FAIL",
      "guardrails-input-on reaching the private cluster alone is PASS there and FAIL on community, its read too")
check(r.get(("guardrails-input-on", "terminal")) == "FAIL" and "exited 1" in text,
      "the terminal's non-zero exit is a FAIL line of its own")
check(w.terminals() == [*TALK_ORDER, *ssr.CLOSE], "the run goes on to guardrails-mcp-on, then closes")
check(all(r.get(("start-state", c)) == "PASS" for c in ssc.CLUSTERS), "and both clusters end at the start state")

# --- a switch that raises -----------------------------------------------------------------------------------------

w = FakeWorld()
w.raise_on["guardrails-agency-on"] = subprocess.TimeoutExpired(["kubectl"], ssr.TERMINAL_TIMEOUT_S)
code, text = go(w)
r = rows(text)
check(code == 1 and r.get(("guardrails-agency-on", "terminal")) == "FAIL" and "raised TimeoutExpired" in text,
      "a switch whose kubectl times out is a FAIL naming the raise")
check(all(r.get(("guardrails-agency-on", c)) == "FAIL" for c in ssc.CLUSTERS),
      "and the switch, never run, is FAIL on both clusters")
check(w.terminals() == [*TALK_ORDER, *ssr.CLOSE] and held_by_us(w),
      "the next switches and the closing four still run, under the lock")

# --- a failing guardrails-mcp-off: the other -off switches still run -----------------------------------------------

w = FakeWorld()
w.raise_on["guardrails-mcp-off"] = RuntimeError("exec failed")
code, text = go(w)
r = rows(text)
check(w.terminals()[-4:] == list(ssr.CLOSE) and r.get(("guardrails-mcp-off", "terminal")) == "FAIL",
      "a guardrails-mcp-off that raises is a FAIL, and the other three -off switches still run")
check(r.get(("start-state", "community")) == "FAIL" and r.get(("as-found", "community")) == "FAIL" and code == 1
      and "infra.tool_allowlist reads true" in text, "the tool allow-list left on fails the start state and as-found")

# --- interrupted mid-run: ^C ----------------------------------------------------------------------------------------

w = FakeWorld()
w.raise_on["guardrails-input-on"] = KeyboardInterrupt()
code, text = go(w)
check(code == ssr.INTERRUPTED_EXIT and "STAGE SWITCH CHECK INTERRUPTED" in text, f"a ^C exits 130 ({code})")
check(w.terminals() == ["guardrails-k8s-on", "guardrails-agency-on", "guardrails-input-on", *ssr.CLOSE],
      f"after a ^C during guardrails-input-on no other switch runs, and the closing four do ({w.terminals()})")
check(held_by_us(w) and not w.leases, "the closing four ran under the lock, and the lock was released after")
r = rows(text)
check(all(r.get(("start-state", c)) == "PASS" for c in ssc.CLUSTERS), "both clusters end at the start state")

# --- a SIGTERM during the switches, and a ^C during the closing four ---------------------------------------------

w = FakeWorld()
w.during["guardrails-mcp-on"] = lambda: os.kill(os.getpid(), signal.SIGTERM)
code, text = go(w)
check(code == 128 + signal.SIGTERM and w.terminals() == [*TALK_ORDER, *ssr.CLOSE] and not w.leases,
      f"a SIGTERM unwinds like a ^C: the closing four run, the lock is released, exit 143 ({code})")
check(signal.getsignal(signal.SIGTERM) == signal.SIG_DFL,
      "main puts the SIGTERM handler back after the run")

w = FakeWorld()
w.during["guardrails-mcp-off"] = lambda: os.kill(os.getpid(), signal.SIGINT)
# The test owns the handler it expects back. A non-interactive shell starts a background job (`cmd &`, how a run
# keeps the suite's output in a log) with SIGINT ignored, Python then keeps SIG_IGN instead of installing its own
# handler, and _close puts back what it found; so the check below is pinned to the default handler here rather than
# read from however the suite was launched (#878, run 18772: the suite failed this check from a background job
# and passed it in the foreground).
signal.signal(signal.SIGINT, signal.default_int_handler)
code, text = go(w)
check(w.terminals() == [*TALK_ORDER, *ssr.CLOSE] and code == ssr.INTERRUPTED_EXIT and "held" in text,
      "a ^C during guardrails-mcp-off is held until every -off, guardrails-k8s-off last, has run, then ends the run")
check(signal.getsignal(signal.SIGINT) is signal.default_int_handler, "the ^C handler is put back after the close")

# --- the lock ------------------------------------------------------------------------------------------------------

w = FakeWorld()
w.apis[COMMUNITY].lease = {"apiVersion": "coordination.k8s.io/v1", "kind": "Lease",
                       "metadata": {"name": guard_lease.NAME, "resourceVersion": "99"},
                       "spec": {"holderIdentity": "kubecon_probe.py community pid 1 by x@y in z",
                                "leaseDurationSeconds": 300,
                                "acquireTime": guard_lease.micro_time(__import__("time").time()),
                                "renewTime": guard_lease.micro_time(__import__("time").time())}}
code, text = go(w)
check(code == guard_lease.BUSY_EXIT and not w.terminals() and "NOT RUN" in text and "kubecon_probe.py" in text,
      "with the community cluster's lock held by another run, nothing is switched and it exits 3 naming the holder")
check(PRIVATE not in w.leases and COMMUNITY in w.leases, "the private lock it took is released; the other's is kept")

w = FakeWorld()
w.apis[PRIVATE].peer = ""
code, text = go(w)
check(not any(e[0] == "lease-create" and e[1] == COMMUNITY for e in w.events),
      "an unlinked private cluster holds its own lock only (guard_lease's rule)")

w = FakeWorld()
w.during["guardrails-k8s-off"] = lambda: setattr(w.apis[COMMUNITY], "lease", None)
code, text = go(w)
r = rows(text)
check(code == 1 and r.get(("guard-lock", "-")) == "FAIL", "a lock lost during the run is a FAIL line")

# --- what keeps it from starting -----------------------------------------------------------------------------------

w = FakeWorld()
w.controls["community"]["ai"]["input_blocklist"] = True
code, text = go(w)
check(code == ssr.NOT_AT_START_EXIT and not w.terminals() and "ai.input_blocklist reads true" in text,
      "an input guard already on on the community cluster stops the run before any switch, exit 4")
check(not w.leases, "and the lock is released")

for section, key in ssr.START_ALSO:
    w = FakeWorld()
    w.controls["private"][section][key] = True
    code, _ = go(w)
    check(code == ssr.NOT_AT_START_EXIT and not w.terminals(),
          f"{section}.{key} on at the start stops the run too: the talk starts with every guard off")

w = FakeWorld()
w.controls["private"]["infra"]["falco"] = False
code, _ = go(w)
check(code == 0, "Falco is not something the closing four touch, so it decides nothing")

w = FakeWorld()
w.controls["community"]["infra"]["kubearmor"] = None
code, text = go(w)
check(code == ssr.NOT_AT_START_EXIT and "infra.kubearmor reads null" in text, "a field read null stops the run")

w = FakeWorld()
w.fetch = lambda host: None if host == ssc.CLUSTERS["community"] else json.dumps(w.controls["private"]).encode()
code, text = go(w)
check(code == ssr.NOT_AT_START_EXIT and not w.terminals(), "an unreadable /controls at the start stops the run")

w = FakeWorld()
w.identity = "attackme.agenticburn.com"
code, text = go(w)
check(code == 1 and not w.terminals() and "STOP" in text and not w.leases,
      "a context whose cluster-identity is not the private cluster switches nothing")

# --- the as-found judge on its own ---------------------------------------------------------------------------------

a = {"private": start_read("burritobot-private.agenticburn.com", True, False),
     "community": start_read("attackme.agenticburn.com", False, False)}
b = copy.deepcopy(a)
b["community"]["infra"]["agency_scoped"] = False
v = ssr.judge_as_found(a, b)
check(v["private"].result == ssc.PASS and v["community"].result == ssc.FAIL
      and "agency_scoped read missing at the start and false at the end" in v["community"].reason,
      "as-found names a field that appeared between the reads")
v = ssr.judge_as_found(a, {"private": a["community"], "community": a["community"]})
check(v["private"].result == ssc.FAIL and "answers as" in v["private"].reason,
      "a closing read that answers as the other cluster is not compared as this one")

print()
if failures:
    print(f"{len(failures)} FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ALL STAGE-SWITCH RUN CHECKS PASSED")
