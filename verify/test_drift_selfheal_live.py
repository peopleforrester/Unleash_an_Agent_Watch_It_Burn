# ABOUTME: E2E drill for #205: delete a managed NetworkPolicy on a live cluster and time Argo CD putting it back,
# ABOUTME: against the window docs/floor.md documents. Needs kubectl and CONTEXT; anything missing is a failure.
# SUITE: e2e
"""Usage: CONTEXT=<kube-context> python3 verify/test_drift_selfheal_live.py

The target is the one managed NetworkPolicy every profile carries (TARGET below). The 30 s window holds only
when the owning app has not self-healed recently: at one git revision the controller backs each further
self-heal off (2 s, 6 s, 18 s, 54 s, 162 s, then 300 s), counted from the previous sync's finish. So the drill
first waits for QUIET_S of quiet on the app, and fails if it cannot get it in QUIET_WAIT_S, because an app that
self-heals that often is drift worth knowing about. Then it deletes the policy and times its return.

Every kubectl call carries --context "$CONTEXT" (CLAUDE.md, Kube-context safety). The current-context is never
read. If the policy does not come back, the drill asks Argo CD for a refresh before it exits, so a failed run
does not leave the console without egress.
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import time

TARGET = ("agent", "platform-console-egress", "ai-layer")  # namespace, NetworkPolicy, owning Application
WINDOW_S = 30          # docs/floor.md: back within this, given QUIET_S without a self-heal on the owning app
QUIET_S = 300          # the self-heal backoff cap; past it the next heal is immediate whatever the count
QUIET_WAIT_S = 600     # how long to wait for that quiet before calling the app itself the finding
GIVE_UP_S = 330        # past the window, keep watching this long so a miss reports the real time
SYNC_WAIT_S = 120      # after the policy is back, how long the sync that put it back may take to finish
TRACKING = "argocd.argoproj.io/tracking-id"

CONTEXT = os.environ.get("CONTEXT", "")
failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def kubectl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", CONTEXT, "--request-timeout=15s", *args],
                          capture_output=True, text=True)


def get_json(*args: str) -> dict | None:
    p = kubectl("get", *args, "-o", "json")
    if p.returncode != 0:
        if "NotFound" in p.stderr:
            return None
        raise RuntimeError(f"kubectl get {' '.join(args)}: {p.stderr.strip()}")
    return json.loads(p.stdout)


def since_last_sync(app: dict) -> float | None:
    fin = ((app.get("status") or {}).get("operationState") or {}).get("finishedAt")
    if not fin:
        return None
    t = datetime.datetime.fromisoformat(fin.replace("Z", "+00:00"))
    return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()


def new_operation(op: dict, prior: str | None) -> bool:
    """Whether `op` is a sync that started after the one recorded before the delete (`prior`, its startedAt).
    Compared with the server's own earlier timestamp, never this host's clock, so clock skew cannot pass it."""
    started = op.get("startedAt")
    return bool(started) and (prior is None or started > prior)


def heal_count(op: dict) -> int:
    """The self-heal count on an operationState. Argo CD v3.5 serialises it as `autoHealAttemptsCount` (the Go
    field is SelfHealAttemptsCount, which is the name its logs print); `selfHealAttemptsCount` is not in the CRD."""
    return ((op.get("operation") or {}).get("sync") or {}).get("autoHealAttemptsCount", 0)


def heal_kind(op: dict, created: str) -> str:
    """Which of Argo CD's two paths put the policy back, read from the operationState seen right after the policy
    returned. `created` is the new policy's creationTimestamp; a sync that started after it did not make it.

    A selective self-heal syncs only the resources that are out of sync: `operation.sync.resources` lists them and
    no hook runs, so the policy is back in about a second. A full sync applies every resource, wave by wave. Which
    one a delete gets is set by the first comparison that sees the policy missing (Argo CD v3.5.7,
    controller/appcontroller.go needRefreshAppStatus, autoSync and alreadyAttemptedSync, controller/state.go
    evaluateRevisionChanges). A refresh an object change asks for compares at the revision the app last compared,
    which with no manifest-generate-paths annotation reads as no new revision, so it heals selectively, at
    staging's head if the periodic resync has already compared it. Only a comparison against staging's head
    (the periodic one, or the delete's own once the last is over 120 s old) that sees the policy missing, while
    the app last synced an older commit, starts a full sync. So the first heal after a staging commit can take
    either path: full on 2026-11-05 (#795), selective at the new revision on 2026-11-06, in 2.7 s at 69b85238 and
    2.5 s at 8e00324d (#962). At 10:13:12Z that day the delete's own comparison was against staging's head but
    still read the policy as there, and the next refresh healed it selectively. While ai-layer's gates
    (kubearmor-gate, otel-gate) were PreSync hooks, a full sync ran them before the policy was applied: 20.1, 25.2
    and 27.2 s on 2026-11-05 against the 30 s window (#795). Since #898 they are plain wave -1 Jobs that a full sync re-applies without running, so a full
    sync names its PreSync Jobs as none, and one that lists a Job again means a hook is back. A selective
    heal can also be followed at once by a full sync to a revision that just landed (10:41Z that day on
    watch-it-burn-private), which is why the start time is compared and not assumed."""
    started = op.get("startedAt") or ""
    if not started or started > created:
        return (f"a sync that cannot be named: the one read when the policy was back started at {started or 'never'},"
                f" after the policy was re-created at {created}")
    sync = (op.get("operation") or {}).get("sync") or {}
    hooks = sorted({r["name"] for r in (op.get("syncResult") or {}).get("resources") or []
                    if r.get("hookType") and r.get("kind") == "Job"})
    if sync.get("resources"):
        return f"a selective self-heal of {len(sync['resources'])} resource(s), no hooks run"
    rev = (sync.get("revision") or "")[:8] or "unknown"
    return f"a full sync to revision {rev}, PreSync Jobs run first: {', '.join(hooks) or 'none'}"


def finish() -> int:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("Self-heal drill passed.")
    return 0


def main() -> int:
    ns, name, app_name = TARGET
    print("== prerequisites ==")
    check("kubectl is on PATH", shutil.which("kubectl") is not None)
    check("CONTEXT names the cluster to drill", bool(CONTEXT))
    if failures:
        return finish()
    app = get_json("-n", "argocd", "application", app_name)
    check(f"Application {app_name} exists on {CONTEXT}", app is not None)
    if app is None:
        return finish()
    auto = (app["spec"].get("syncPolicy") or {}).get("automated") or {}
    check(f"{app_name} self-heals and prunes", auto.get("selfHeal") is True and auto.get("prune") is True)
    before = get_json("-n", ns, "networkpolicy", name)
    check(f"{ns}/{name} exists before the drill", before is not None)
    if before is None:
        return finish()
    check(f"{ns}/{name} carries Argo CD's tracking annotation (it is managed)",
          TRACKING in (before["metadata"].get("annotations") or {}))
    if failures:
        return finish()

    print(f"== waiting for {QUIET_S}s without a sync on {app_name} (the self-heal backoff cap) ==")
    waited = 0.0
    while True:
        app = get_json("-n", "argocd", "application", app_name) or {}
        quiet = since_last_sync(app)
        if quiet is None or quiet >= QUIET_S:
            break
        if waited >= QUIET_WAIT_S:
            break
        step = min(QUIET_S - quiet, 15.0)
        time.sleep(step)
        waited += step
    count = heal_count(((app.get("status") or {}).get("operationState") or {}))
    print(f"  {app_name}: last sync {quiet if quiet is not None else 'never'}s ago, autoHealAttemptsCount {count}")
    check(f"{app_name} went {QUIET_S}s without syncing within {QUIET_WAIT_S}s of waiting "
          "(if not, it is healing something all the time: that is the finding)",
          quiet is None or quiet >= QUIET_S)
    if failures:
        return finish()

    print(f"== delete {ns}/{name} and time its return ==")
    old_uid = before["metadata"]["uid"]
    prior_start = ((app.get("status") or {}).get("operationState") or {}).get("startedAt")
    p = kubectl("-n", ns, "delete", "networkpolicy", name, "--wait=false")
    check(f"the delete is admitted ({p.stderr.strip() or 'ok'})", p.returncode == 0)
    if p.returncode != 0:
        return finish()
    t0 = time.monotonic()
    back, after = None, None
    while time.monotonic() - t0 < GIVE_UP_S:
        after = get_json("-n", ns, "networkpolicy", name)
        if after is not None and after["metadata"]["uid"] != old_uid:
            back = time.monotonic() - t0
            break
        time.sleep(1)
    if back is None:
        print(f"  not back after {GIVE_UP_S}s; requesting a refresh so the console keeps its egress")
        kubectl("-n", "argocd", "annotate", "application", app_name, "argocd.argoproj.io/refresh=normal", "--overwrite")
        check(f"{ns}/{name} came back at all within {GIVE_UP_S}s", False)
        return finish()
    print(f"  back after {back:.1f}s")
    healing = ((get_json("-n", "argocd", "application", app_name) or {}).get("status") or {}).get(
        "operationState") or {}
    print(f"  healed by {heal_kind(healing, after['metadata'].get('creationTimestamp') or '')}")
    check(f"{ns}/{name} came back within the documented {WINDOW_S}s (took {back:.1f}s)", back <= WINDOW_S)
    check("as a new object (a new uid), so it was re-created and not merely never deleted",
          after["metadata"]["uid"] != old_uid)
    check("carrying Argo CD's tracking annotation", TRACKING in (after["metadata"].get("annotations") or {}))
    check("with the spec git has", after.get("spec") == before.get("spec"))

    # The policy is back as soon as the sync applies it, which is before the sync ends: on watch-it-burn-private
    # on 2026-11-05 it was back at 25.2 s and the sync still Running, finishing 6 s later. So wait for the sync
    # that started after the delete to leave Running, then read how it ended.
    op: dict = {}
    t1 = time.monotonic()
    while time.monotonic() - t1 < SYNC_WAIT_S:
        app = get_json("-n", "argocd", "application", app_name) or {}
        op = (app.get("status") or {}).get("operationState") or {}
        if new_operation(op, prior_start) and op.get("phase") != "Running":
            break
        time.sleep(2)
    check(f"a sync started after the delete and ended within {SYNC_WAIT_S}s of the policy's return "
          f"(started {op.get('startedAt')}, phase {op.get('phase')})",
          new_operation(op, prior_start) and op.get("phase") != "Running")
    check(f"the sync that did it was automated and succeeded (phase {op.get('phase')})",
          op.get("phase") == "Succeeded" and (op.get("operation", {}).get("initiatedBy") or {}).get("automated") is True)
    return finish()


if __name__ == "__main__":
    sys.exit(main())
