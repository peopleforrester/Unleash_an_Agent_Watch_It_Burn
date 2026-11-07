# ABOUTME: Offline checks for the cluster guard lock (#1024): the Lease is taken, waited on, taken over when expired,
# ABOUTME: renewed and released; and the probes and every verify script that flips guards hold it while they do.
"""Holds verify/guard_lease.py and its callers to #1024 without a cluster.

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
      all(c[:3] == ["kubectl", "--context", "ctx-private"] for c in api.calls), str(api.calls))
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
rc, _, err = api2.handle(["kubectl", "--context", "c", "replace", "-f", "-"],
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


def fake_hold(lost=None, busy=False):
    @contextlib.contextmanager
    def hold(context, kubeconfig=None, profile=None, what="", wait=gl.WAIT_S, **kw):
        seen.update(context=context, kubeconfig=kubeconfig, profile=profile, what=what, wait=wait, inside=False)
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


real = (kp.guard_lease.hold, kp.Probe.run, kp.KubeconCluster.get_json)
kp.Probe.run, kp.KubeconCluster.get_json = fake_run, lambda self, path: None
try:
    kp.guard_lease.hold = fake_hold()
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = kp.main(["admin", "burritobot-private.burritobot.co", "--context", "watch-it-burn-private",
                      "--kubeconfig", "/tmp/k", "--profile", "accen-dev"])
    check("kubecon_probe admin runs its beats inside the lock, guards-off included",
          rc == 0 and seen.get("ran_inside") is True and seen["final"] is kp.GUARDS_OFF_BEAT and not seen["inside"],
          str(seen))
    check("it takes the lock on --context with the probe's kubeconfig and profile",
          (seen["context"], seen["kubeconfig"], seen["profile"]) == ("watch-it-burn-private", "/tmp/k", "accen-dev")
          and seen["what"] == "kubecon_probe.py admin burritobot-private.burritobot.co"
          and seen["wait"] == gl.WAIT_S, str(seen))
    seen.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        kp.main(["community", "attackme.burritobot.co", "--context", "watch-it-burn-community", "--lock-wait", "5"])
    check("kubecon_probe community holds it too, with --lock-wait", seen.get("ran_inside") is True
          and seen["context"] == "watch-it-burn-community" and seen["wait"] == 5.0, str(seen))
    seen.clear()
    kp.guard_lease.hold = fake_hold(busy=True)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = kp.main(["admin", "burritobot-private.burritobot.co", "--context", "watch-it-burn-private"])
    check("a busy lock: the probe exits BUSY_EXIT, runs no beat, and says KUBECON PROBE NOT RUN",
          rc == gl.BUSY_EXIT and "ran_inside" not in seen and "KUBECON PROBE NOT RUN" in out.getvalue(),
          f"{rc} {seen} {out.getvalue()}")
    seen.clear()
    kp.guard_lease.hold = fake_hold(lost="the lock was lost: held by 'someone'")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = kp.main(["admin", "burritobot-private.burritobot.co", "--context", "watch-it-burn-private"])
    check("a lock lost mid-run turns the probe RED on a guard-lock beat",
          rc == 1 and "The guard lock was held for the whole run" in out.getvalue() and "KUBECON PROBE RED" in out.getvalue(), out.getvalue())
finally:
    kp.guard_lease.hold, kp.Probe.run, kp.KubeconCluster.get_json = real

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

print()
if failures:
    print(f"{len(failures)} FAILED:\n  " + "\n  ".join(failures))
    sys.exit(1)
print("All guard lock checks passed.")
