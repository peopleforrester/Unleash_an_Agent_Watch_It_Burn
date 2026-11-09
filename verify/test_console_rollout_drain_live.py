# ABOUTME: Live half of #1258: a console rollout under a steady loop of POST /chat through the public host returns
# ABOUTME: no 502 and no dropped connection, the old pod drains past its preStop, and the new pod waits on the NLB.
# SUITE: e2e
"""Needs kubectl, the aws CLI, CONTEXT naming a KubeCon cluster (or any cluster running the console with a recorded
public host), AWS_PROFILE and AWS_REGION for the account the cluster's NLB is in (in a hecaton run,
`. "$HECATON_CLUSTER_ENV"` exports both), and the public internet. Every missing prerequisite is a failure, never a
skip.

verify/test_console_rollout_drain.py holds the settings in git. This holds the cluster to them and then watches one
console rollout from outside, the way the room sees it:

  1. the agent namespace carries the readiness-gate label, the console's nginx sleeps in preStop, its grace period
     covers the sleep plus the longest /chat turn, each of the console Service's target groups has a
     deregistration delay shorter than the sleep, read from the NLB itself, and the console.conf the pod mounts sets
     a keepalive_time that, added to that delay, is still under the sleep;
  2. one POST /chat a second goes to https://<public host>/chat for the whole rollout, from before it starts until
     the old pod is gone, and every one of them must come back as guard-proxy's own answer: no 502, no 504, no
     dropped connection;
  3. the old pod outlives its deletion by the preStop sleep, and the new pod carries the load balancer
     controller's target-health readiness gate, True.

The rollout. ROLLOUT=restart, the default, runs `kubectl rollout restart deploy/console`. The block-argocd-drift
policy refuses that to every principal but Argo CD's controller and the admin groups, so a hecaton run's identity
cannot start one: run it as a cluster admin. ROLLOUT=admin runs the same restart as the run's own
user in the system:masters group, which that policy exempts as an admin group; a hecaton run's role may impersonate
it, and run 19661 rolled the console on watch-it-burn-private that way. ROLLOUT=watch starts nothing; it sends the loop and waits up to WAIT
seconds (default 1800) for the next rollout an Argo CD sync makes, which is how a run checks it: start it, then let
the promotion of a change that rolls the console land. In restart mode, a cluster that does not hold the settings
is not rolled; in watch mode the loop runs anyway, so a rollout before the fix reaches the cluster shows its 502s.

What it spends. Each turn sends an EMPTY prompt in a fresh conversation: nginx counts it, and guard-proxy answers it
with a 400 before any guard, the prompt feed or the model, so it costs nothing and appears nowhere. One a second is
60 of guard-proxy's 150 a minute for the cluster, so do not run it while the room is chatting.

Usage: CONTEXT=<kube-context> [ROLLOUT=restart|admin|watch] [WAIT=<seconds>] python3 verify/test_console_rollout_drain_live.py
"""
from __future__ import annotations

import collections
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

CONTEXT = os.environ.get("CONTEXT", "")
ROLLOUT = os.environ.get("ROLLOUT", "restart")
WAIT = int(os.environ.get("WAIT", "1800"))
NS = "agent"
GATE_LABEL = "elbv2.k8s.aws/pod-readiness-gate-inject"
GATE_PREFIX = "target-health.elbv2.k8s.aws/"
CHAT_TIMEOUT = 285  # console.conf's /chat proxy_read_timeout; verify/test_console_rollout_drain.py reads it from git
INTERVAL = 1.0
WARMUP = 20
SETTLE = 30

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""), flush=True)
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("A console rollout under a loop of POST /chat dropped no turn.")
    sys.exit(0)


def kubectl(*args: str, timeout: str = "30s") -> subprocess.CompletedProcess:
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    return subprocess.run(["kubectl", "--context", CONTEXT, f"--request-timeout={timeout}", *args],
                          capture_output=True, text=True)


def kjson(*args: str) -> dict:
    r = kubectl(*args, "-o", "json")
    return json.loads(r.stdout) if r.returncode == 0 else {}


def console_pods() -> dict[str, dict]:
    return {p["metadata"]["name"]: p for p in kjson("-n", NS, "get", "pods", "-l", "app.kubernetes.io/name=console")
            .get("items", [])}


def chat(host: str) -> tuple[int, str]:
    session = f"wib-verify-1258-{uuid.uuid4().hex}"
    headers = {"Content-Type": "application/json", "User-Agent": "wib-verify/1258", "X-BurritoBot-Session": session}
    req = urllib.request.Request(f"https://{host}/chat", data=json.dumps({"prompt": "", "session": session}).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        return 0, f"{type(e).__name__}: {e}"
    return status, raw[:160].decode(errors="replace")


def answered(status: int, body: str) -> bool:
    # An empty prompt that went through the NLB, nginx and guard-proxy: guard-proxy's own 400, in the /chat shape.
    try:
        return status == 400 and "reply" in json.loads(body)
    except ValueError:
        return False


class Loop:
    """One POST /chat every INTERVAL seconds, each in its own thread, so a slow answer never delays the next."""

    def __init__(self, host: str):
        self.host, self.t0 = host, time.monotonic()
        self.results: list[tuple[float, int, str]] = []
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=40)
        self.thread = threading.Thread(target=self.run, daemon=True)

    def now(self) -> float:
        return time.monotonic() - self.t0

    def one(self) -> None:
        sent = self.now()
        status, body = chat(self.host)
        with self.lock:
            self.results.append((sent, status, body))

    def run(self) -> None:
        while not self.stop.is_set():
            self.pool.submit(self.one)
            self.stop.wait(INTERVAL)

    def start(self) -> "Loop":
        self.thread.start()
        return self

    def end(self) -> list[tuple[float, int, str]]:
        self.stop.set()
        self.thread.join()
        self.pool.shutdown(wait=True)
        return sorted(self.results)


print("== prerequisites ==")
missing = [m for m, bad in (
    ("kubectl is not on PATH", not shutil.which("kubectl")),
    ("the aws CLI is not on PATH", not shutil.which("aws")),
    ("CONTEXT is not set: name the kube-context of the KubeCon cluster to roll", not CONTEXT),
    ("AWS_PROFILE is not set: the NLB's target groups are read with it", not os.environ.get("AWS_PROFILE")),
    ("AWS_REGION is not set", not os.environ.get("AWS_REGION")),
    (f"ROLLOUT is {ROLLOUT!r}: it is restart, admin or watch", ROLLOUT not in ("restart", "admin", "watch")),
) if bad]
for m in missing:
    check(m, False)
if missing:
    finish()
r = kubectl("-n", NS, "get", "configmap", "cluster-identity", "-o", "jsonpath={.data.public-host}")
host = r.stdout.strip()
check("the cluster records its public host (cluster-identity public-host)", bool(host),
      r.stderr.strip() or "empty: infra/datadog-cluster-identity.sh writes it at bootstrap")
if not host:
    finish()

print(f"== {CONTEXT} holds the drain and the readiness gate ==")
ns = kjson("get", "namespace", NS)
check(f"the {NS} namespace carries {GATE_LABEL}=enabled",
      (ns.get("metadata", {}).get("labels") or {}).get(GATE_LABEL) == "enabled",
      f"labels: {(ns.get('metadata', {}).get('labels') or {})}")
dep = kjson("-n", NS, "get", "deploy", "console")
pod_spec = dep.get("spec", {}).get("template", {}).get("spec", {})
nginx = next((c for c in pod_spec.get("containers", []) if c.get("name") == "nginx"), {})
sleep = (((nginx.get("lifecycle") or {}).get("preStop") or {}).get("sleep") or {}).get("seconds")
grace = pod_spec.get("terminationGracePeriodSeconds", 30)
check(f"the console's nginx sleeps in preStop (got {sleep})", isinstance(sleep, int) and sleep > 0,
      f"lifecycle: {nginx.get('lifecycle')}")
sleep = sleep if isinstance(sleep, int) else 0
check(f"its grace period {grace}s covers the sleep plus the {CHAT_TIMEOUT}s /chat turn", grace >= sleep + CHAT_TIMEOUT)
tgbs = [t for t in kjson("-n", NS, "get", "targetgroupbindings").get("items", [])
        if t.get("spec", {}).get("serviceRef", {}).get("name") == "console"]
check(f"the console Service has its NLB target groups bound (got {len(tgbs)})", bool(tgbs))
delays = []
for t in tgbs:
    arn = t["spec"]["targetGroupARN"]
    a = subprocess.run(["aws", "--region", os.environ["AWS_REGION"], "elbv2", "describe-target-group-attributes",
                        "--target-group-arn", arn, "--output", "json"], capture_output=True, text=True)
    attrs = {x["Key"]: x["Value"] for x in json.loads(a.stdout).get("Attributes", [])} if a.returncode == 0 else {}
    delay = int(attrs.get("deregistration_delay.timeout_seconds", "0") or 0)
    delays.append(delay)
    check(f"{t['metadata']['name']} (port {t['spec']['serviceRef']['port']}) deregisters in {delay}s, under the "
          f"{sleep}s preStop sleep", a.returncode == 0 and 0 < delay < sleep, a.stderr.strip()[:200])
# The apex router reuses its connections, and the NLB keeps a flow on the pod it began on through the whole drain,
# so nginx must close them itself, on a response, before the sleep ends (run 19661's rollout).
conf_cm = next((v["configMap"]["name"] for v in pod_spec.get("volumes", [])
                if (v.get("configMap") or {}).get("name", "").startswith("console-conf")), "")
conf_text = kjson("-n", NS, "get", "configmap", conf_cm).get("data", {}).get("default.conf", "") if conf_cm else ""
m = re.search(r"^keepalive_time (\d+)s;", conf_text, re.M)
keepalive = int(m.group(1)) if m else None
check(f"the console's nginx config ({conf_cm or 'no console-conf volume'}) sets keepalive_time (got {'none' if keepalive is None else f'{keepalive}s'}), "
      f"and it plus the {max(delays, default=0)}s deregistration delay is under the {sleep}s sleep",
      keepalive is not None and bool(delays) and max(delays) + keepalive < sleep)
if failures and ROLLOUT in ("restart", "admin"):
    print("  the cluster does not hold the settings, so it is not rolled: sync the change, then run this again")
    finish()

print(f"== a loop of POST /chat through https://{host}, {WARMUP}s before the rollout ==")
before = console_pods()
loop = Loop(host).start()
time.sleep(WARMUP)
with loop.lock:
    warm = list(loop.results)
check(f"the loop is answered before the rollout ({sum(answered(s, b) for _, s, b in warm)} of {len(warm)})",
      bool(warm) and all(answered(s, b) for _, s, b in warm), f"{[(s, b) for _, s, b in warm if not answered(s, b)][:3]}")

print(f"== the rollout ({ROLLOUT}) ==")
rolled_at = None
if ROLLOUT in ("restart", "admin"):
    as_admin: list[str] = []
    if ROLLOUT == "admin":
        me = kubectl("auth", "whoami", "-o", "jsonpath={.status.userInfo.username}").stdout.strip()
        as_admin = [f"--as={me}", "--as-group=system:masters", "--as-group=system:authenticated"]
    r = kubectl(*as_admin, "-n", NS, "rollout", "restart", "deploy/console")
    check("kubectl rollout restart deploy/console is admitted", r.returncode == 0,
          (r.stderr.strip()[:300] + "\n        the block-argocd-drift policy admits only Argo CD's controller and "
           "the admin groups: run this as a cluster admin, with ROLLOUT=admin, or with ROLLOUT=watch during an Argo CD "
           "sync"))
    rolled_at = loop.now() if r.returncode == 0 else None
else:
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        # A rollout is a new console pod beside the old one (maxSurge 1), not just a new generation: a sync that
        # changes no pod template bumps the generation and rolls nothing.
        if set(console_pods()) - set(before):
            rolled_at = loop.now()
            break
        time.sleep(5)
    check(f"an Argo CD sync rolled the console within {WAIT}s", rolled_at is not None)
if rolled_at is None:
    loop.end()
    finish()
print(f"  the rollout began {rolled_at:.0f}s into the loop")
r = kubectl("-n", NS, "rollout", "status", "deploy/console", "--timeout=600s", timeout="620s")
check("the rollout completes", r.returncode == 0, (r.stderr or r.stdout).strip()[-300:])

# The old pods: when each was marked for deletion and when it was gone, by polling, so to a few seconds.
deleted_at: dict[str, float] = {}
gone_at: dict[str, float] = {}
deadline = time.monotonic() + grace + 120
while time.monotonic() < deadline and len(gone_at) < len(before):
    live = console_pods()
    for name in before:
        if name in gone_at:
            continue
        if name not in live:
            gone_at[name] = loop.now()
            deleted_at.setdefault(name, gone_at[name])
        elif live[name]["metadata"].get("deletionTimestamp"):
            deleted_at.setdefault(name, loop.now())
    time.sleep(2)
check(f"every old console pod is gone ({len(gone_at)} of {len(before)})", len(gone_at) == len(before))
time.sleep(SETTLE)
results = loop.end()

print(f"== what the loop got, {len(results)} turns over {results[-1][0] - results[0][0]:.0f}s ==" if results else
      "== what the loop got: nothing ==")
by_status = collections.Counter(s for _, s, _ in results)
print(f"  by status: {dict(sorted(by_status.items()))}")
for name in before:
    if name in deleted_at:
        print(f"  {name}: marked for deletion at {deleted_at[name]:.0f}s, gone at {gone_at.get(name, -1):.0f}s")
bad = [(t, s, b) for t, s, b in results if not answered(s, b)]
for t, s, b in bad[:12]:
    one_line = re.sub(r"\s+", " ", b)[:100]
    print(f"    {t:6.1f}s  HTTP {s}  {one_line}")
check("no turn came back 502", by_status.get(502, 0) == 0, f"{by_status.get(502, 0)} did")
check("no turn lost its connection", by_status.get(0, 0) == 0, f"{by_status.get(0, 0)} did")
check(f"every turn was answered by guard-proxy ({len(results) - len(bad)} of {len(results)})", bool(results) and not bad)

print("== the old pod drained, the new pod waited on the NLB ==")
for name in before:
    if name in deleted_at and name in gone_at:
        lived = gone_at[name] - deleted_at[name]
        check(f"{name} served on for {lived:.0f}s after deletion, past the {sleep}s preStop sleep", lived >= sleep - 3)
after = {n: p for n, p in console_pods().items() if n not in before}
check(f"the rollout made a new console pod (got {sorted(after)})", bool(after))
for name, p in after.items():
    gates = [g["conditionType"] for g in p["spec"].get("readinessGates", [])
             if g.get("conditionType", "").startswith(GATE_PREFIX)]
    conds = {c["type"]: c["status"] for c in p.get("status", {}).get("conditions", [])}
    check(f"{name} carries the load balancer controller's target-health readiness gates (got {len(gates)})",
          len(gates) == len(tgbs) and len(gates) > 0, f"readinessGates: {p['spec'].get('readinessGates')}")
    check(f"{name}'s target-health gates are True", bool(gates) and all(conds.get(g) == "True" for g in gates),
          f"{ {g: conds.get(g) for g in gates} }")
finish()
