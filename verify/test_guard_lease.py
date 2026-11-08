# ABOUTME: Offline checks for the cluster guard lock (#1024, #1016): the Lease is taken, waited on, taken over, renewed
# ABOUTME: and released; every check that flips guards or switches guardrails holds it, on both clusters for a switch.
"""Holds verify/guard_lease.py and its callers to #1024 and #1016 without a cluster.

The Lease API is verify/fake_lease_kubectl.py: in process as a runner, and as a program behind a fake kubectl first
on PATH for the CLI and the shell scripts. The clock is a counter the fake sleep moves, so no wait here is real.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
VERIFY = REPO / "verify"
sys.path.insert(0, str(VERIFY))
import fake_lease_kubectl as fk  # noqa: E402
import guard_lease as gl  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        {detail}"))
    if not ok:
        failures.append(name)


class Clock:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def other_lease(api: fk.FakeLeaseApi, holder: str, renewed: float, duration: int = 300) -> None:
    api.lease = api._stamp({"apiVersion": "coordination.k8s.io/v1", "kind": "Lease",
                            "metadata": {"name": gl.NAME, "namespace": gl.NAMESPACE},
                            "spec": {"holderIdentity": holder, "leaseDurationSeconds": duration,
                                     "acquireTime": gl.micro_time(renewed - 30), "renewTime": gl.micro_time(renewed)}})


def lease(api: fk.FakeLeaseApi, clock: Clock, logs: list[str], **kw) -> gl.GuardLease:
    return gl.GuardLease("ctx-private", what="test", runner=api.run, clock=clock, sleep=clock.sleep,
                         log=logs.append, **kw)


def verbs(api: fk.FakeLeaseApi) -> list[str]:
    return [c[3] if c[3] != "-n" else c[5] for c in api.calls]


os.environ.pop(gl.ENV, None)

print("== a free lock is created, names its holder, and is deleted on release ==")
api, clock, logs = fk.FakeLeaseApi(), Clock(), []
lk = lease(api, clock, logs)
lk.acquire(wait=60)
spec = (api.lease or {}).get("spec") or {}
check("acquire on a free cluster creates the Lease", lk.held and verbs(api) == ["create"], str(api.calls))
check("the holder names the script, the pid and this checkout",
      spec.get("holderIdentity") == lk.holder and lk.holder.startswith("test pid ")
      and lk.holder.endswith(f" in {REPO.name}"), lk.holder)
check("the Lease lasts LEASE_S and was renewed now",
      spec.get("leaseDurationSeconds") == gl.LEASE_S and gl.parse_micro_time(spec.get("renewTime")) == clock.t,
      json.dumps(spec))
check("every kubectl call names --context ctx-private first",
      all(c[0] == "kubectl" and c[1:3] == ["--context", "ctx-private"] for c in api.calls), str(api.calls))
lk.release()
check("release deletes it with the resourceVersion it read as the precondition",
      api.lease is None and verbs(api)[-2:] == ["get", "delete"] and api.calls[-1][5:7] == [gl.API_PATH, "-f"],
      str(api.calls[-2:]))
try:
    gl.GuardLease("", runner=api.run)
    check("GuardLease('') raises", False, "no error")
except ValueError as e:
    check("GuardLease('') raises ValueError naming the context", "kube-context" in str(e), str(e))

print("== a lock another run holds is waited on, then given up naming the holder; nothing is written ==")
api, clock, logs = fk.FakeLeaseApi(), Clock(), []
other_lease(api, "kubecon_probe.py admin pid 7 in 1-489-17946", renewed=clock.t - 10)
before = json.dumps(api.lease)
lk = lease(api, clock, logs)
try:
    lk.acquire(wait=120)
    check("acquire gives up", False, "it acquired a held lock")
except gl.LeaseBusy as e:
    check("LeaseBusy names the holder and the context",
          "1-489-17946" in str(e) and "ctx-private" in str(e) and "gave up after 120 s" in str(e), str(e))
check("it polled every POLL_S seconds while it waited", clock.slept and set(clock.slept) == {gl.POLL_S},
      str(clock.slept))
check("it said whom it waits on at least once a minute",
      sum("waiting for ctx-private" in m for m in logs) >= 120 // gl.WAIT_NOTE_S
      and all("1-489-17946" in m for m in logs if "waiting" in m), "\n".join(logs))
check("the holder's Lease is untouched: no replace, no delete",
      json.dumps(api.lease) == before and set(verbs(api)) == {"create", "get"}, str(set(verbs(api))))

print("== a holder that releases while another waits hands the lock over ==")
api, clock, logs = fk.FakeLeaseApi(), Clock(), []
other_lease(api, "beat-02.sh pid 9", renewed=clock.t)
real_sleep = clock.sleep


def release_on_second(s: float) -> None:
    real_sleep(s)
    if len(clock.slept) == 2:
        api.lease = None


lk = gl.GuardLease("ctx-private", what="test", runner=api.run, clock=clock, sleep=release_on_second, log=logs.append)
lk.acquire(wait=600)
check("the waiter holds it once the first holder released it",
      lk.held and api.lease["spec"]["holderIdentity"] == lk.holder and len(clock.slept) == 2, str(clock.slept))

print("== an expired lock is taken over with a replace carrying its resourceVersion ==")
api, clock, logs = fk.FakeLeaseApi(), Clock(), []
other_lease(api, "killed run pid 3", renewed=clock.t - gl.LEASE_S - 1)
lk = lease(api, clock, logs)
lk.acquire(wait=0)
check("a Lease renewed more than its duration ago is taken over at once",
      lk.held and api.lease["spec"]["holderIdentity"] == lk.holder and verbs(api) == ["create", "get", "replace"]
      and not clock.slept, str(verbs(api)))
check("the takeover is logged with the old holder", any("killed run pid 3" in m and "took over" in m for m in logs),
      "\n".join(logs))
check("a Lease whose holder is blank is free", gl.expired({"spec": {"holderIdentity": ""}}, clock.t))
check("a Lease renewed inside its duration is not expired",
      not gl.expired({"spec": {"holderIdentity": "x", "leaseDurationSeconds": 300,
                               "renewTime": gl.micro_time(clock.t - 299)}}, clock.t))

print("== two runs racing for an expired lock cannot both win ==")
api, clock, logs = fk.FakeLeaseApi(), Clock(), []
other_lease(api, "killed run pid 3", renewed=clock.t - 1000)
api.conflict_next = "replace"
lk = lease(api, clock, logs)
lk.acquire(wait=60)
check("a replace that answers Conflict is not a win: it reads again and retries",
      verbs(api) == ["create", "get", "replace", "create", "get", "replace"] and lk.held, str(verbs(api)))
api2 = fk.FakeLeaseApi()
other_lease(api2, "killed run pid 3", renewed=clock.t - 1000)
stale = json.loads(json.dumps(api2.lease))
other_lease(api2, "the run that won", renewed=clock.t)
rc, _, err = api2.handle(["--context", "c", "replace", "-f", "-"],
                         json.dumps({**stale, "spec": {**stale["spec"], "holderIdentity": "loser"}}))
check("the fake API server refuses a replace on a stale resourceVersion (the race's guarantee)",
      rc == 1 and "Conflict" in err and api2.lease["spec"]["holderIdentity"] == "the run that won", err)

print("== the holder renews; a lost lock is reported and someone else's Lease is never deleted ==")
api, clock, logs = fk.FakeLeaseApi(), Clock(), []
lk = lease(api, clock, logs)
lk.acquire(wait=0)
acquired = api.lease["spec"]["acquireTime"]
clock.t += 120
check("renew returns True", lk.renew())
check("renew moves renewTime to now and keeps acquireTime",
      gl.parse_micro_time(api.lease["spec"]["renewTime"]) == clock.t and api.lease["spec"]["acquireTime"] == acquired,
      json.dumps(api.lease["spec"]))
other_lease(api, "a run that took it", renewed=clock.t)
check("renew returns False when the Lease names someone else", lk.renew() is False)
check("lost names the new holder", bool(lk.lost) and "a run that took it" in lk.lost, str(lk.lost))
n = len(api.calls)
lk.release()
check("release after a loss deletes nothing", api.lease["spec"]["holderIdentity"] == "a run that took it"
      and "delete" not in verbs(api)[n:], str(verbs(api)[n:]))
api, clock, logs = fk.FakeLeaseApi(), Clock(), []
api.handle = (lambda real: lambda argv, stdin: (1, "", "Error from server (Forbidden): leases is forbidden\n")
              if "create" in argv else real(argv, stdin))(api.handle)
try:
    lease(api, clock, logs).acquire(wait=600)
    check("a Forbidden create raises", False, "acquired")
except RuntimeError as e:
    check("a create refused for any reason but AlreadyExists raises at once, never loops",
          "Forbidden" in str(e) and not clock.slept, str(e))

print("== hold: the body sees WIB_GUARD_LEASE, renewals run, and a nested hold makes no call ==")
api, clock, logs = fk.FakeLeaseApi(), Clock(), []
with gl.hold("ctx-private", what="outer", runner=api.run, clock=clock, sleep=clock.sleep, log=logs.append,
             renew_every=0.05) as outer:
    inside = gl.held_map()
    deadline = time.time() + 5
    while verbs(api).count("replace") < 2 and time.time() < deadline:
        time.sleep(0.02)
    n = len(api.calls)
    with gl.hold("ctx-private", what="inner", runner=api.run, log=logs.append) as inner:
        nested_calls = len(api.calls) - n
check("the body's WIB_GUARD_LEASE names the context and the holder", inside == {"ctx-private": outer.holder},
      str(inside))
check("the background renewal replaced the Lease while the body ran", verbs(api).count("replace") >= 2,
      str(verbs(api)))
check("a nested hold on the same context joins the outer one with no kubectl call",
      inner.nested and inner.holder == outer.holder and nested_calls == 0, f"{inner.nested} {nested_calls}")
check("after hold the Lease is gone and WIB_GUARD_LEASE is unset", api.lease is None and gl.ENV not in os.environ,
      str(api.lease))

# --- the CLI, behind a fake kubectl first on PATH -----------------------------------------------------------------
work = pathlib.Path(tempfile.mkdtemp())
(work / "bin").mkdir()
(work / "bin/kubectl").write_text(f'#!/usr/bin/env bash\nexec {sys.executable} {VERIFY / "fake_lease_kubectl.py"} "$@"\n')
(work / "bin/kubectl").chmod(0o755)
STATE = work / "lease.json"
ENV = {**{k: v for k, v in os.environ.items() if k != gl.ENV}, "PATH": f"{work / 'bin'}:{os.environ['PATH']}",
       "FAKE_LEASE_STATE": str(STATE), "FAKE_LEASE_LOG": str(work / "calls")}


def cli(*args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(VERIFY / "guard_lease.py"), *args], capture_output=True, text=True,
                          env=ENV, timeout=60, **kw)


def saved() -> dict | None:
    return json.loads(STATE.read_text())["lease"] if STATE.exists() else None


print("== the CLI ==")
r = cli("hold", "--context", "ctx-cli", "--what", "cli test", "--", "bash", "-c",
        f'echo "$WIB_GUARD_LEASE" > {work / "env"}; exit 7')
check("hold runs the command and exits with its code", r.returncode == 7, r.stderr)
check("the command saw WIB_GUARD_LEASE name ctx-cli", "ctx-cli" in (work / "env").read_text())
check("the Lease is released after the command", saved() is None, str(saved()))
check("held exits 1 with no WIB_GUARD_LEASE", cli("held", "--context", "ctx-cli").returncode == 1)
check("held exits 0 when WIB_GUARD_LEASE names the context",
      subprocess.run([sys.executable, str(VERIFY / "guard_lease.py"), "held", "--context", "ctx-cli"],
                     env={**ENV, gl.ENV: json.dumps({"ctx-cli": "x"})}).returncode == 0)
api = fk.FakeLeaseApi()
other_lease(api, "another run pid 5 in 1-467-17944", renewed=time.time())
STATE.write_text(json.dumps({"lease": api.lease, "rv": api.rv}))
r = cli("hold", "--context", "ctx-cli", "--wait", "0", "--", "touch", str(work / "ran"))
check("hold on a busy lock exits BUSY_EXIT and runs nothing",
      r.returncode == gl.BUSY_EXIT and not (work / "ran").exists(), f"rc {r.returncode}: {r.stderr}")
check("its message names the holder", "1-467-17944" in r.stderr and "nothing was run" in r.stderr, r.stderr)
r = cli("show", "--context", "ctx-cli")
check("show names the holder", r.returncode == 0 and "held by 'another run pid 5 in 1-467-17944'" in r.stdout,
      r.stdout + r.stderr)
STATE.unlink()
p = subprocess.Popen([sys.executable, str(VERIFY / "guard_lease.py"), "hold", "--context", "ctx-cli", "--", "bash",
                      "-c", f"touch {work / 'started'}; sleep 30"], env=ENV, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True)
deadline = time.time() + 20
while not (work / "started").exists() and time.time() < deadline:
    time.sleep(0.05)
held_then = saved() is not None
p.send_signal(signal.SIGTERM)
_, err = p.communicate(timeout=20)
check("a SIGTERM'd hold stops its command and releases the lock instead of leaving it to expire",
      held_then and saved() is None and p.returncode == 143, f"held {held_then} rc {p.returncode} {err}")
# A SIGTERM while the lock is being taken (the Lease written, the answer not yet read) still deletes it.
api = fk.FakeLeaseApi()
interrupted = gl.GuardLease("ctx-private", what="t", runner=api.run, log=lambda m: None)
real_try = interrupted.try_acquire


def try_then_interrupt():
    real_try()
    raise KeyboardInterrupt


interrupted.try_acquire = try_then_interrupt
real_cls = gl.GuardLease
gl.GuardLease = lambda *a, **k: interrupted
try:
    with gl.hold("ctx-private", what="t"):
        pass
    check("an interrupted acquire raises", False, "no interrupt")
except KeyboardInterrupt:
    check("an acquire interrupted after its create deletes the Lease it wrote", api.lease is None
          and interrupted.lost is None, str(api.lease))
finally:
    gl.GuardLease = real_cls

# --- every script that flips guards through the cluster takes the lock ------------------------------------------
print("== every verify script that flips guards takes the lock ==")
TAKERS = ["verify/kubecon_probe.py", "verify/agent_probe.py", "verify/input-guard.sh", "verify/beat-02.sh",
          "verify/beat-cost.sh", "verify/stage_traces.py"]
# A script flips guards when it sends a /toggle query itself, or runs the KubeCon probe's beats, which end on
# guards-off (GUARDS_OFF_BEAT).
FLIPS = ("/toggle?", "GUARDS_OFF_BEAT")
flippers = sorted(str(f.relative_to(REPO)) for f in list(VERIFY.glob("*.py")) + list(VERIFY.glob("*.sh"))
                  if not f.name.startswith("test_") and f.name not in ("guard_lease.py", "fake_lease_kubectl.py")
                  and any(m in f.read_text(encoding="utf-8") for m in FLIPS))
check("the verify scripts that flip guards are exactly the six this test names", flippers == sorted(TAKERS),
      f"found {flippers}: a new one takes the lock and joins TAKERS here")
for f in TAKERS:
    check(f"{f} uses guard_lease", "guard_lease" in (REPO / f).read_text(encoding="utf-8"))

SH_ENV = {**ENV, "AWS_PROFILE": "accen-dev"}
(work / "bin/kubectl").write_text(f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >>"{work}/sh-calls"
case "$*" in
    *" lease "*|*"/leases/"*|*" create -f - -o json"*|*" replace -f - -o json"*)
        exec {sys.executable} {VERIFY / "fake_lease_kubectl.py"} "$@" ;;
esac
echo '{{}}'
""")
(work / "bin/curl").write_text("#!/usr/bin/env bash\necho '{\"ai\": {\"input_blocklist\": false, "
                               "\"input_classifier\": false}, \"reply\": \"x\"}'\n")
(work / "bin/curl").chmod(0o755)
for script, args in (("verify/beat-02.sh", ["ctx-sh", "agent"]), ("verify/beat-cost.sh", ["ctx-sh", "agent"]),
                     ("verify/input-guard.sh", ["burritobot-private.burritobot.co", "ctx-sh", "accen-dev"])):
    (work / "sh-calls").write_text("")
    if STATE.exists():
        STATE.unlink()
    subprocess.run(["bash", str(REPO / script), *args], env=SH_ENV, capture_output=True, text=True, timeout=120,
                   cwd=REPO)
    calls = (work / "sh-calls").read_text().splitlines()
    toggles = [i for i, c in enumerate(calls) if "toggle?" in c]
    check(f"{script}: every kubectl call names --context ctx-sh",
          bool(calls) and all(c.startswith(("--context ctx-sh ", "--context=ctx-sh ")) for c in calls),
          "\n".join(calls[:5]))
    check(f"{script}: it creates the Lease before its first toggle and deletes it after its last",
          bool(toggles) and "create -f -" in calls[0] and "delete --raw" in calls[-1]
          and 0 < toggles[0] and toggles[-1] < len(calls) - 1, "\n".join(calls))
    check(f"{script}: the Lease is gone when it exits", saved() is None, str(saved()))
    check(f"{script}: every toggle names the lock's holder for guard-proxy's toggle log (X-WIB-Caller)",
          bool(toggles) and all(f"{script} " in calls[i] and " pid " in calls[i] for i in toggles),
          "\n".join(calls[i] for i in toggles))

# --- the probes' toggles name the holder ----------------------------------------------------------------------------
print("== the probes' toggles send the lock's holder as X-WIB-Caller ==")
import agent_probe as ap  # noqa: E402
import kubecon_probe as kp  # noqa: E402

sent: list[list[str]] = []


def toggle_runner(argv, **kw):
    sent.append(argv)
    return subprocess.CompletedProcess(argv, 0, stdout='{"output": true}\n', stderr="")


os.environ[gl.ENV] = json.dumps({"ctx-p": "kubecon_probe.py admin pid 7 in 1-1024-18104"})
try:
    kp.KubeconCluster("h", "ctx-p", None, None, 5, runner=toggle_runner).toggle("output=on")
    real_sp_run = ap.subprocess.run
    ap.subprocess.run = toggle_runner
    try:
        ap.Cluster("h", "ctx-p", None, 5).set_guards(output="on")
    finally:
        ap.subprocess.run = real_sp_run
finally:
    os.environ.pop(gl.ENV, None)
check("kubecon_probe and agent_probe send /toggle with X-WIB-Caller naming the holder",
      len(sent) == 2 and all("toggle?output=on" in a[-1] and "'X-WIB-Caller':'kubecon_probe.py admin pid 7 in "
                             "1-1024-18104'" in a[-1] for a in sent), str([a[-1] for a in sent]))
kp.KubeconCluster("h", "ctx-p", None, None, 5, runner=toggle_runner).toggle("output=off")
check("with no lock held the header is empty, and the query is unchanged",
      gl.caller("ctx-p") == "" and "toggle?output=off" in sent[-1][-1] and "'X-WIB-Caller':''" in sent[-1][-1],
      sent[-1][-1])

# --- the probes hold it around their beats ------------------------------------------------------------------------
print("== the KubeCon probe and agent_probe hold the lock around their beats ==")

seen: dict = {}


class FakeLease:
    def __init__(self, lost=None):
        self.lost, self.holder = lost, "fake"


def fake_hold(lost=None, busy=False, kind="hold"):
    @contextlib.contextmanager
    def hold(context, kubeconfig=None, profile=None, what="", wait=gl.WAIT_S, **kw):
        seen.update(context=context, kubeconfig=kubeconfig, profile=profile, what=what, wait=wait, inside=False,
                    kind=kind)
        if busy:
            raise gl.LeaseBusy("held by 'another run'")
        seen["inside"] = True
        try:
            yield FakeLease(lost)
        finally:
            seen["inside"] = False
    return hold


def fake_run(self, beats, final=None):
    seen["ran_inside"] = seen.get("inside")
    seen["final"] = final
    return []


real = (kp.guard_lease.hold, kp.guard_lease.hold_switch, kp.Probe.run, kp.KubeconCluster.get_json)
kp.Probe.run, kp.KubeconCluster.get_json = fake_run, lambda self, path: None
try:
    # An admin probe runs guardrails-on and guardrails-off, which switch both KubeCon clusters, so it holds the lock
    # through hold_switch (#1016); a community probe switches nothing beyond its guards-free start and holds one.
    kp.guard_lease.hold, kp.guard_lease.hold_switch = fake_hold(), fake_hold(kind="hold_switch")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = kp.main(["admin", "burritobot-private.burritobot.co", "--context", "watch-it-burn-private",
                      "--kubeconfig", "/tmp/k", "--profile", "accen-dev"])
    check("kubecon_probe admin runs its beats inside the lock, guards-off included",
          rc == 0 and seen.get("ran_inside") is True and seen["final"] is kp.GUARDS_OFF_BEAT and not seen["inside"],
          str(seen))
    check("kubecon_probe admin holds it on both KubeCon clusters (hold_switch), since its guardrails-on switches both",
          seen.get("kind") == "hold_switch", str(seen))
    check("it takes the lock on --context with the probe's kubeconfig and profile",
          (seen["context"], seen["kubeconfig"], seen["profile"]) == ("watch-it-burn-private", "/tmp/k", "accen-dev")
          and seen["what"] == "kubecon_probe.py admin burritobot-private.burritobot.co"
          and seen["wait"] == gl.WAIT_S, str(seen))
    seen.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        kp.main(["community", "attackme.burritobot.co", "--context", "watch-it-burn-community", "--lock-wait", "5"])
    check("kubecon_probe community holds it too, with --lock-wait", seen.get("ran_inside") is True
          and seen["context"] == "watch-it-burn-community" and seen["wait"] == 5.0 and seen["kind"] == "hold",
          str(seen))
    seen.clear()
    kp.guard_lease.hold_switch = fake_hold(busy=True)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = kp.main(["admin", "burritobot-private.burritobot.co", "--context", "watch-it-burn-private"])
    check("a busy lock: the probe exits BUSY_EXIT, runs no beat, and says KUBECON PROBE NOT RUN",
          rc == gl.BUSY_EXIT and "ran_inside" not in seen and "KUBECON PROBE NOT RUN" in out.getvalue(),
          f"{rc} {seen} {out.getvalue()}")
    seen.clear()
    kp.guard_lease.hold_switch = fake_hold(lost="the lock was lost: held by 'someone'")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = kp.main(["admin", "burritobot-private.burritobot.co", "--context", "watch-it-burn-private"])
    check("a lock lost mid-run turns the probe RED on a guard-lock beat",
          rc == 1 and "The guard lock was held for the whole run" in out.getvalue() and "KUBECON PROBE RED" in out.getvalue(), out.getvalue())
finally:
    kp.guard_lease.hold, kp.guard_lease.hold_switch, kp.Probe.run, kp.KubeconCluster.get_json = real

real_ap = (ap.guard_lease.hold, ap.run, ap.Cluster.cost, sys.argv)


def ap_run(cluster, probes, max_calls, **kw):
    seen["ran_inside"] = seen.get("inside")
    return []


def ap_cost(self):
    raise OSError("no network here")


ap.run, ap.Cluster.cost = ap_run, ap_cost
try:
    seen.clear()
    ap.guard_lease.hold = fake_hold()
    sys.argv = ["agent_probe.py", "h.example", "--context", "ctx-a", "--profile", "accen-dev"]
    with contextlib.redirect_stdout(io.StringIO()):
        rc = ap.main()
    check("agent_probe with --context runs its beats inside the lock on that context",
          rc == 0 and seen.get("ran_inside") is True and seen["context"] == "ctx-a" and seen["profile"] == "accen-dev",
          str(seen))
    seen.clear()
    sys.argv = ["agent_probe.py", "h.example"]
    with contextlib.redirect_stdout(io.StringIO()):
        ap.main()
    check("agent_probe without --context flips nothing and takes no lock",
          "context" not in seen and seen.get("ran_inside") is None, str(seen))
    seen.clear()
    ap.guard_lease.hold = fake_hold(busy=True)
    sys.argv = ["agent_probe.py", "h.example", "--context", "ctx-a"]
    with contextlib.redirect_stdout(io.StringIO()):
        rc = ap.main()
    check("agent_probe on a busy lock exits BUSY_EXIT and runs nothing",
          rc == gl.BUSY_EXIT and "ran_inside" not in seen, str(seen))
finally:
    ap.guard_lease.hold, ap.run, ap.Cluster.cost, sys.argv = real_ap

# --- #1016: a guardrails switch holds the lock on both clusters it reaches --------------------------------------------
print("== hold_switch: the lock on this cluster and on its guardrails peer, in sorted order ==")


class Fleet:
    """One fake API server per kube-context; a context the kubeconfig does not have answers as kubectl does."""

    def __init__(self, **apis: fk.FakeLeaseApi) -> None:
        self.apis = {k.replace("_", "-"): v for k, v in apis.items()}
        self.order: list[str] = []

    def run(self, argv, input=None, **kw):
        ctx = argv[2]
        if ctx not in self.apis:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr=f'error: context "{ctx}" does not exist\n')
        self.order.append(f"{ctx} {' '.join(argv[3:6])}")
        return self.apis[ctx].run(argv, input=input, **kw)


def creates(fleet: Fleet) -> list[str]:
    return [o.split()[0] for o in fleet.order if o.split()[1:3] == ["create", "-f"]]


fleet = Fleet(wib_private=fk.FakeLeaseApi(peer="wib-community"), wib_community=fk.FakeLeaseApi(peer="wib-private"))
check("peer_context reads the cluster the guardrails-peer Secret names",
      gl.peer_context("wib-private", runner=fleet.run) == "wib-community", str(fleet.order))
check("peer_context is '' on a cluster with no guardrails-peer Secret",
      gl.peer_context("ctx-alone", runner=Fleet(ctx_alone=fk.FakeLeaseApi()).run) == "")
inside_both = None
with gl.hold_switch("wib-private", what="kubecon_probe.py admin", runner=fleet.run, log=lambda m: None) as sw:
    inside_both = {c: (fleet.apis[c].lease or {}).get("spec", {}).get("holderIdentity") for c in fleet.apis}
    env_both = gl.held_map()
check("held from the private side, it takes community first, then private (sorted, so either side takes the same "
      "order and two switches cannot deadlock)", creates(fleet) == ["wib-community", "wib-private"], str(fleet.order))
check("both Leases name the same holder while it is held, and WIB_GUARD_LEASE names both contexts",
      len(set(inside_both.values())) == 1 and None not in inside_both.values() and set(env_both) == set(fleet.apis)
      and sw.contexts == ["wib-community", "wib-private"], f"{inside_both} {env_both}")
check("both are released after", all(a.lease is None for a in fleet.apis.values()) and gl.ENV not in os.environ,
      str({c: a.lease for c, a in fleet.apis.items()}))
fleet.order.clear()
with gl.hold_switch("wib-community", what="t", runner=fleet.run, log=lambda m: None):
    pass
check("held from the community side, the order is the same", creates(fleet) == ["wib-community", "wib-private"],
      str(fleet.order))
alone = Fleet(ctx_alone=fk.FakeLeaseApi())
with gl.hold_switch("ctx-alone", what="t", runner=alone.run, log=lambda m: None) as sw:
    pass
check("a cluster with no peer holds only its own lock", creates(alone) == ["ctx-alone"] and sw.contexts == ["ctx-alone"],
      str(alone.order))

busy = Fleet(wib_private=fk.FakeLeaseApi(peer="wib-community"), wib_community=fk.FakeLeaseApi(peer="wib-private"))
other_lease(busy.apis["wib-private"], "test_kyverno_cel_live.py pid 4 in 1-467-17944", renewed=time.time())
clock = Clock(time.time())
try:
    with gl.hold_switch("wib-private", what="t", wait=30, runner=busy.run, clock=clock, sleep=clock.sleep,
                        log=lambda m: None):
        check("hold_switch gives up when the peer's lock is held", False, "it ran")
except gl.LeaseBusy as e:
    check("hold_switch on a held cluster raises LeaseBusy naming the holder and the cluster",
          "1-467-17944" in str(e) and "wib-private" in str(e), str(e))
check("and the lock it took on the other cluster first is released, so a switch that gives up holds nothing",
      busy.apis["wib-community"].lease is None and creates(busy)[0] == "wib-community", str(busy.order))
check("the holder's Lease is untouched",
      (busy.apis["wib-private"].lease or {}).get("spec", {}).get("holderIdentity", "").endswith("1-467-17944"))

missing = Fleet(wib_private=fk.FakeLeaseApi(peer="wib-community"))
try:
    with gl.hold_switch("wib-private", what="t", runner=missing.run, log=lambda m: None):
        check("a peer the kubeconfig lacks is an error", False, "it ran")
except RuntimeError as e:
    check("a peer the kubeconfig has no context for raises, naming the peer and asking for a kubeconfig with it",
          "also switches wib-community" in str(e) and "context named wib-community" in str(e), str(e))
check("and leaves no Lease behind", missing.apis["wib-private"].lease is None, str(missing.apis["wib-private"].lease))
lost_one = gl.SwitchHold([gl.GuardLease("wib-community", runner=fleet.run), gl.GuardLease("wib-private", runner=fleet.run)])
lost_one.leases[1].lost = "the lock was lost: held by 'x'"
check("a SwitchHold reports a loss on either cluster, naming it",
      lost_one.lost == "wib-private: the lock was lost: held by 'x'", str(lost_one.lost))

print("== run_held: a live check's body runs only inside the lock ==")
api = fk.FakeLeaseApi()
ran, notes, said = [], [], []
real_hold = gl.hold


@contextlib.contextmanager
def hold_on_api(context, kubeconfig=None, profile=None, what="", wait=gl.WAIT_S, **kw):
    with real_hold(context, kubeconfig, profile, what=what, wait=wait, runner=api.run, log=lambda m: None) as h:
        yield h


gl.hold = hold_on_api
try:
    ok = gl.run_held("ctx-private", lambda: ran.append((api.lease or {}).get("spec", {}).get("holderIdentity")),
                     lambda n, c, d: notes.append((n, c)), "verify/test_x_live.py", wait=0)
    check("run_held runs the body holding the Lease, then checks the lock held throughout",
          ok and ran and ran[0] and api.lease is None and notes == [(notes[0][0], True)], f"{ran} {notes}")
    other_lease(api, "kubecon_probe.py admin pid 7 in 1-900-17950", renewed=time.time())
    ran.clear()
    ok = gl.run_held("ctx-private", lambda: ran.append(1), lambda n, c, d: notes.append((n, c)), "t", wait=0,
                     out=said.append)
    check("on a busy lock run_held returns False, runs nothing and prints FAILED naming the holder",
          ok is False and not ran and said and said[0].startswith("FAILED") and "1-900-17950" in said[0], str(said))
finally:
    gl.hold = real_hold
check("WIB_GUARD_LEASE_WAIT sets the default wait", gl.default_wait({gl.WAIT_ENV: "12"}) == 12.0
      and gl.default_wait({}) == gl.WAIT_S)
try:
    gl.default_wait({gl.WAIT_ENV: "soon"})
    check("a WIB_GUARD_LEASE_WAIT that is not a number is an error", False, "accepted")
except ValueError as e:
    check("a WIB_GUARD_LEASE_WAIT that is not a number is an error", gl.WAIT_ENV in str(e), str(e))

print("== the CLI: hold --with-peer, and WIB_GUARD_LEASE_WAIT ==")
(work / "bin/kubectl").write_text(f'#!/usr/bin/env bash\nFAKE_LEASE_STATE="{work}/lease-$2.json" '
                                  f'exec {sys.executable} {VERIFY / "fake_lease_kubectl.py"} "$@"\n')
PEER_ENV = {**ENV, "FAKE_LEASE_PEERS": json.dumps({"wib-private": "wib-community", "wib-community": "wib-private"})}


def ctx_lease(ctx: str) -> dict | None:
    f = work / f"lease-{ctx}.json"
    return json.loads(f.read_text())["lease"] if f.exists() else None


r = subprocess.run([sys.executable, str(VERIFY / "guard_lease.py"), "hold", "--with-peer", "--context", "wib-private",
                    "--what", "guardrails-on by hand", "--", "bash", "-c", f'echo "$WIB_GUARD_LEASE" > {work / "env2"}'],
                   env=PEER_ENV, capture_output=True, text=True, timeout=60)
held_env = json.loads((work / "env2").read_text() or "{}") if (work / "env2").exists() else {}
check("hold --with-peer runs the command holding the lock on both clusters",
      r.returncode == 0 and set(held_env) == {"wib-private", "wib-community"}, r.stderr + str(held_env))
check("and releases both", ctx_lease("wib-private") is None and ctx_lease("wib-community") is None)
api = fk.FakeLeaseApi()
other_lease(api, "beat-01.sh pid 3 in 1-1016-18150", renewed=time.time())
(work / "lease-wib-community.json").write_text(json.dumps({"lease": api.lease, "rv": api.rv}))
t0 = time.monotonic()
r = subprocess.run([sys.executable, str(VERIFY / "guard_lease.py"), "hold", "--with-peer", "--context", "wib-private",
                    "--", "touch", str(work / "ran2")], env={**PEER_ENV, gl.WAIT_ENV: "0"}, capture_output=True,
                   text=True, timeout=60)
check("with WIB_GUARD_LEASE_WAIT=0 and the peer held, it exits BUSY_EXIT at once, names the holder, runs nothing, and "
      "leaves no Lease of its own", r.returncode == gl.BUSY_EXIT and "1-1016-18150" in r.stderr
      and not (work / "ran2").exists() and ctx_lease("wib-private") is None and time.monotonic() - t0 < 30,
      f"rc {r.returncode}: {r.stderr}")
(work / "lease-wib-community.json").unlink()

# --- #1016: every live check that switches guardrails or policies takes the lock --------------------------------------
print("== every live check that switches guardrails or policies takes the lock ==")
# What a check changes when it switches the Kubernetes guardrails or the policies in `agent`: the terminal's
# guardrails-on and guardrails-off (GUARDRAILS_ON, or the probe's beats, which end on GUARDS_OFF_BEAT), a
# ValidatingPolicy's action (a /spec/validationActions patch, or toggle-kyverno-enforce.sh), the Challenge 1
# NetworkPolicies, or another NetworkPolicy deleted. The readers are the live checks whose verdict needs the
# guardrails to stay put while they run, and which said "never during" a probe before #1016.
SWITCH_MARKS = ("GUARDRAILS_ON", "GUARDS_OFF_BEAT", "/spec/validationActions", "toggle-kyverno-enforce",
                "c1-network-policy", '"delete", "networkpolicy"')
# bootstrap_chart.py renders the chart: its /spec/validationActions is Argo CD's ignoreDifferences, and it runs no kubectl.
NOT_LIVE = {"verify/bootstrap_chart.py"}
SWITCHERS = {"verify/kubecon_probe.py": "hold_switch", "verify/stage_traces.py": "hold_switch",
             "verify/test_recipe_block_live.py": "with_peer=True", "verify/test_kyverno_cel_live.py": "guard_lease.hold(",
             "verify/beat-01.sh": "guard_lease.py\" hold", "verify/c1-exfil-block.sh": "guard_lease.py\" hold",
             "verify/test_drift_selfheal_live.py": "guard_lease.run_held(",
             "verify/test_deployments_removed_live.py": "guard_lease.run_held("}
READERS = {"verify/test_kubecon_c3_live.py": "guard_lease.run_held(", "verify/test_two_hour_flow_live.py":
           "guard_lease.run_held(", "verify/test_room_cleanup_live.py": "guard_lease.hold("}
live_files = [f for f in list(VERIFY.glob("*.py")) + list(VERIFY.glob("*.sh"))
              if (not f.name.startswith("test_") or "_live" in f.name)
              and f.name not in ("guard_lease.py", "fake_lease_kubectl.py")]
switchers = sorted(str(f.relative_to(REPO)) for f in live_files
                   if any(m in f.read_text(encoding="utf-8") for m in SWITCH_MARKS))
check("the live checks that switch guardrails or policies are exactly the ones this test names",
      sorted(set(switchers) - NOT_LIVE) == sorted(SWITCHERS),
      f"found {sorted(set(switchers) - NOT_LIVE)}: a new one takes the lock and joins SWITCHERS here")
for f, how in {**SWITCHERS, **READERS}.items():
    text = (REPO / f).read_text(encoding="utf-8")
    check(f"{f} takes the guard lock ({how})", how in text.replace("${GUARD_LEASE}\"", "guard_lease.py\"")
          .replace('$HERE/guard_lease.py"', 'guard_lease.py"'), how)
for f in sorted(SWITCHERS):
    text = (REPO / f).read_text(encoding="utf-8")
    if "GUARDRAILS_ON" in text or "GUARDS_OFF_BEAT" in text:
        check(f"{f} runs the terminal's guardrails switch, so it holds the lock on both clusters",
              "hold_switch" in text or "with_peer=True" in text)

print("== beat-01.sh holds the lock from before its first flip until after its cleanup ==")
(work / "bin/kubectl").write_text(f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >>"{work}/sh-calls"
case "$*" in
    *" lease "*|*"/leases/"*|*" create -f - -o json"*|*" replace -f - -o json"*)
        exec {sys.executable} {VERIFY / "fake_lease_kubectl.py"} "$@" ;;
esac
echo '{{}}'
""")
for name, extra, want_busy in (("free", {}, False), ("busy", {gl.WAIT_ENV: "0"}, True)):
    (work / "sh-calls").write_text("")
    if STATE.exists():
        STATE.unlink()
    if want_busy:
        api = fk.FakeLeaseApi()
        other_lease(api, "kubecon_probe.py admin pid 7 in 1-900-17950", renewed=time.time())
        STATE.write_text(json.dumps({"lease": api.lease, "rv": api.rv}))
    r = subprocess.run(["bash", str(REPO / "verify/beat-01.sh"), "ctx-sh", "agent"], env={**SH_ENV, **extra},
                       capture_output=True, text=True, timeout=120, cwd=REPO)
    calls = (work / "sh-calls").read_text().splitlines()
    flips = [i for i, c in enumerate(calls) if "patch validatingpolicy" in c]
    if want_busy:
        check("beat-01.sh on a held lock exits 3 naming the holder and flips nothing",
              r.returncode == gl.BUSY_EXIT and "1-900-17950" in r.stderr and not flips,
              f"rc {r.returncode}: {r.stderr[-400:]}\n" + "\n".join(calls))
    else:
        check("beat-01.sh: every kubectl call names --context ctx-sh",
              bool(calls) and all(c.startswith(("--context ctx-sh ", "--context=ctx-sh ")) for c in calls),
              "\n".join(calls[:5]))
        check("beat-01.sh creates the Lease before its first policy flip and deletes it after its cleanup's last",
              bool(flips) and "create -f -" in calls[0] and "delete --raw" in calls[-1]
              and 0 < flips[0] and flips[-1] < len(calls) - 1, "\n".join(calls))
        check("beat-01.sh: the Lease is gone when it exits", saved() is None, str(saved()))
if STATE.exists():
    STATE.unlink()

# --- #1016: no agent identity can write the Lease --------------------------------------------------------------------
print("== no agent identity holds a grant that writes the Lease ==")
import yaml  # noqa: E402

WRITE = {"create", "update", "patch", "delete", "deletecollection", "*"}
roles: dict[tuple[str, str], list[dict]] = {}
bindings: list[tuple[str, dict]] = []


def rbac_docs():
    for f in sorted((REPO / "gitops").rglob("*.y*ml")):
        if "templates" in f.parts:
            continue  # Helm templates; the chart renders Applications, not RBAC
        for d in yaml.safe_load_all(f.read_text(encoding="utf-8")):
            if not isinstance(d, dict):
                continue
            yield f, d
            # The Role variants the terminal applies (c5-scoped-role.yaml, c8-broad-role.yaml) live in ConfigMaps.
            if d.get("kind") == "ConfigMap":
                for v in (d.get("data") or {}).values():
                    if "kind: Role" in v or "kind: ClusterRole" in v:
                        for inner in yaml.safe_load_all(v):
                            if isinstance(inner, dict):
                                yield f, inner


for f, d in rbac_docs():
    if d.get("kind") in ("Role", "ClusterRole"):
        roles.setdefault((d["kind"], d["metadata"]["name"]), []).extend(d.get("rules") or [])
    elif d.get("kind") in ("RoleBinding", "ClusterRoleBinding"):
        bindings.append((str(f.relative_to(REPO)), d))


def writes_leases(rule: dict) -> bool:
    return (bool({"coordination.k8s.io", "*"} & set(rule.get("apiGroups") or []))
            and bool({"leases", "*"} & set(rule.get("resources") or []))
            and bool(WRITE & set(rule.get("verbs") or [])))


check("the grant reader sees a wildcard rule and a lease rule as writes, and a read-only lease rule as none",
      writes_leases({"apiGroups": ["*"], "resources": ["*"], "verbs": ["*"]})
      and writes_leases({"apiGroups": ["coordination.k8s.io"], "resources": ["leases"], "verbs": ["update"]})
      and not writes_leases({"apiGroups": ["coordination.k8s.io"], "resources": ["leases"], "verbs": ["get", "list"]}))


agent_bound = []
for f, b in bindings:
    for sub in b.get("subjects") or []:
        if sub.get("kind") != "ServiceAccount" or (sub.get("namespace") or b["metadata"].get("namespace")
                                                    or "agent") != "agent":
            continue
        ref = (b["roleRef"]["kind"], b["roleRef"]["name"])
        agent_bound.append((f, sub["name"], ref))
        check(f"{sub['name']}'s {ref[0]} {ref[1]} ({f}) is defined in the repo, so its grant can be read",
              ref in roles, f"no {ref[0]} {ref[1]} in gitops/")
        bad = [r for r in roles.get(ref, []) if writes_leases(r)]
        check(f"{sub['name']}'s {ref[0]} {ref[1]} writes no Lease", not bad, json.dumps(bad))
check("the scan found the agent's own bindings (agent-sa and workshop-mcp to the workshop-agent Role)",
      {("agent-sa", ("Role", "workshop-agent")), ("workshop-mcp", ("Role", "workshop-agent"))}
      <= {(s, ref) for _, s, ref in agent_bound}, str(agent_bound))
check("the workshop-agent Role's variants the terminal applies were read with it",
      len(roles.get(("Role", "workshop-agent"), [])) > 4, str(roles.get(("Role", "workshop-agent"))))

print()
if failures:
    print(f"{len(failures)} FAILED:\n  " + "\n  ".join(failures))
    sys.exit(1)
print("All guard lock checks passed.")
