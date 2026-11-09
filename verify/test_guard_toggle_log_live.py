# ABOUTME: Live half of #1068 (#1046's #1052 check): a verify toggle on watch-it-burn-private writes one guard_toggle
# ABOUTME: line per guard it changes in guard-proxy's log, none for a read, each naming the guard, values, peer, caller.
# SUITE: e2e
"""Needs kubectl and PRIVATE_CONTEXT naming the kube-context of the private admin cluster (watch-it-burn-private).
Every missing prerequisite is a failure, never a skip.

guard-proxy-agenticburn#67 (0e7f15b) has guard-proxy log a guard_toggle line for every /toggle that changes a guard,
so a guard found in the wrong state can be traced to the request that put it there (#1024). This runs the verify
toggle run 18491 ran by hand for #1046 and reads the log back:

- first: the context is the private cluster (its cluster-identity names burritobot-private), and guard-proxy's pod
  template carries git's checksum/proxy-py with its one replica rolled out, so the pod runs the pinned proxy.py;
- then, holding the private cluster's guard lock (verify/guard_lease.py) so no other run flips a guard meanwhile,
  five /toggle requests through `kubectl exec` into the proxy container, each with the lock's holder as X-WIB-Caller:
  a read, the output guard flipped, a read, the output guard flipped back, a read. The last read must equal the
  first, so the cluster is left as found; a failure mid-way still flips the guard back;
- then `kubectl logs deploy/guard-proxy -c proxy --since-time=<start>` must hold exactly two guard_toggle lines, one
  per change and none for the three reads, each naming `output`, the value it took and the one it had, a peer, and
  the holder (verify/guard_toggle_log.py's judge).

It prints one `guard_toggle read:` line, the line decisions.md records and verify/test_guard_toggle_record.py holds.
It makes no model call and changes no spec.

Usage: PRIVATE_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] python3 verify/test_guard_toggle_log_live.py
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guard_lease  # noqa: E402
import guard_toggle_log as gt  # noqa: E402
import kubecon_probe as kp  # noqa: E402
from test_kubecon_c3_live import git_proxy_checksum, proxy_rolled_out  # noqa: E402

PRIVATE = "burritobot-private.agenticburn.com"
# How long the log is read for the two lines before the verdict: kubectl logs is near instant, so this is slack.
LOG_WAIT_S = 30


def since_time(t: float) -> str:
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_log(cluster: kp.KubeconCluster, since: str, want: int) -> list[dict]:
    """guard-proxy's guard_toggle lines since `since`, read until `want` are there or LOG_WAIT_S passes, then once
    more after a pause, so a late extra line is seen too."""
    deadline = time.monotonic() + LOG_WAIT_S
    while True:
        lines = gt.parse(cluster._kubectl("-n", "agent", "logs", "deploy/guard-proxy", "-c", "proxy",
                                          f"--since-time={since}"))
        if len(lines) >= want or time.monotonic() > deadline:
            break
        time.sleep(3)
    time.sleep(3)
    return gt.parse(cluster._kubectl("-n", "agent", "logs", "deploy/guard-proxy", "-c", "proxy",
                                     f"--since-time={since}"))


def run_checks(cluster: kp.KubeconCluster, context: str, check) -> None:
    host = cluster.identity_host()
    check("the context is the private admin cluster", kp.identity_name(host) == PRIVATE,
          f"its cluster-identity public-host is {host!r}, not {PRIVATE!r}: STOP")
    if kp.identity_name(host) != PRIVATE:
        return
    dep = json.loads(cluster._kubectl("-n", "agent", "get", "deployment", "guard-proxy", "-o", "json"))
    want = git_proxy_checksum()
    ok, note = proxy_rolled_out(dep, want)
    check(f"guard-proxy runs git's proxy.py (checksum/proxy-py {want})", ok, note)
    replicas = dep["spec"].get("replicas", 1)
    check("guard-proxy has one replica, so the exec and the log read reach the same pod", replicas == 1,
          f"{replicas} replicas")
    if not ok or replicas != 1:
        return

    caller = guard_lease.caller(context)
    check("the guard lock's holder is known, for X-WIB-Caller", bool(caller), "WIB_GUARD_LEASE names no holder")
    start = since_time(time.time() - 2)
    first = cluster.toggle("")
    was = bool(first[gt.GUARD])
    flip = "off" if was else "on"
    back = "on" if was else "off"
    changes = [(gt.GUARD, not was, was), (gt.GUARD, was, not was)]
    flipped = False
    try:
        r = cluster.toggle(f"{gt.GUARD}={flip}")
        flipped = True
        check(f"/toggle?{gt.GUARD}={flip} answers {gt.GUARD}={not was}", r.get(gt.GUARD) is (not was), f"answered {r}")
        middle = cluster.toggle("")
        check("a read between the flips changes nothing", middle == r, f"{middle} after {r}")
    finally:
        if flipped:
            r = cluster.toggle(f"{gt.GUARD}={back}")
            check(f"/toggle?{gt.GUARD}={back} answers {gt.GUARD}={was}", r.get(gt.GUARD) is was, f"answered {r}")
    last = cluster.toggle("")
    check("left as found: the last /toggle read equals the first", last == first, f"first {first}, last {last}")

    lines = read_log(cluster, start, len(changes))
    for line in lines:
        print(f"  INFO  {json.dumps({k: line.get(k) for k in ('timestamp', 'event', *gt.FIELDS)})}")
    problems = gt.judge(lines, changes, caller)
    check("guard-proxy's log holds one guard_toggle line per change and none for the three reads",
          len(lines) == len(changes), "; ".join(problems))
    check("each line names the guard, the value it took and had, a peer and the X-WIB-Caller holder",
          not problems, "; ".join(problems))
    print("  " + gt.record_line(context, want, gt.GUARD, len(changes), 3, len(lines),
                                gt.matched(lines, changes, caller)))


def main() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
        if not cond:
            failures.append(name)

    context = os.environ.get("PRIVATE_CONTEXT", "")
    missing = []
    if not context:
        missing.append("PRIVATE_CONTEXT is not set: name the kube-context of the private admin cluster "
                       "(watch-it-burn-private)")
    if shutil.which("kubectl") is None:
        missing.append("kubectl is not on PATH")
    if not missing:
        env = {k: v for k, v in os.environ.items() if k != "KUBECONFIG"}
        if os.environ.get("KUBECONFIG"):
            env["KUBECONFIG"] = os.environ["KUBECONFIG"]
        r = subprocess.run(["kubectl", "--context", context, "--request-timeout=15s", "get", "--raw", "/readyz"],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            missing.append(f"cluster for context {context!r} is not reachable: {(r.stderr or r.stdout).strip()[:200]}")
    if missing:
        print("FAILED: the live guard_toggle check cannot run; this is a failure, not a skip:")
        for m in missing:
            print(f"  - {m}")
        return 1

    print(f"== a verify toggle on {context} and guard-proxy's guard_toggle lines ==")
    kubeconfig = os.environ.get("KUBECONFIG") or None
    cluster = kp.KubeconCluster("", context, None, kubeconfig, timeout=60.0)
    if not guard_lease.run_held(context, lambda: run_checks(cluster, context, check), check,
                                "verify/test_guard_toggle_log_live.py", kubeconfig=kubeconfig):
        return guard_lease.BUSY_EXIT

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All live guard_toggle checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
