# ABOUTME: E2E drill for #205: delete a managed NetworkPolicy on a live cluster and time Argo CD putting it back,
# ABOUTME: against the window docs/floor.md documents. Needs kubectl and CONTEXT; anything missing is a failure.
# SUITE: e2e
"""Usage: CONTEXT=<kube-context> [HEAL_PATH=any|full] python3 verify/test_drift_selfheal_live.py

HEAL_PATH=full aims the delete at the full-sync path (#962): it fails unless staging has moved since the app last
synced, waits until the app's last comparison is older than argocd-cm's timeout.reconciliation, deletes then, and
fails unless a full sync put the policy back. The default, any, deletes as soon as the app is quiet and reports
whichever path healed. heal_kind's docstring says why the moment matters.

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
import re
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

EXPIRY_MARGIN_S = 2    # HEAL_PATH=full deletes this long after the comparison expires, for clock skew
EXPIRY_WAIT_S = 300    # how long HEAL_PATH=full waits for an expired comparison (the resync is 120 s + 60 s jitter)
HEAL_PATHS = ("any", "full")

CONTEXT = os.environ.get("CONTEXT", "")
HEAL_PATH = os.environ.get("HEAL_PATH", "any")
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

    The path is set by the comparison the delete's refresh runs (Argo CD v3.5.7, controller/appcontroller.go
    needRefreshAppStatus and alreadyAttemptedSync, controller/state.go evaluateRevisionChanges). A refresh that an
    object change asks for compares at the revision the app last compared (level 1, CompareWithRecent). With no
    manifest-generate-paths annotation that reads as no new revision, so self-heal syncs only the resources that
    are out of sync: `operation.sync.resources` lists them and no hook runs, so the policy is back in about a
    second. Once the app's last comparison is older than argocd-cm's timeout.reconciliation (120 s; the periodic
    resync comes 0 to 60 s after that), the same refresh compares with staging's head (level 2,
    CompareWithLatest), and if the app last synced an older commit, even one that leaves its manifests alone, it
    starts a full sync to the head. So the first heal after a staging commit is a full sync only when the delete
    lands in that window, which HEAL_PATH=full waits for. On 2026-11-06 on watch-it-burn-private a delete 63 s
    after the last comparison healed selectively, at the new revision 69b85238, in 2.7 s (#962). While ai-layer's
    gates (kubearmor-gate, otel-gate) were PreSync hooks, a full sync ran them before the policy was applied: 20.1,
    25.2 and 27.2 s on 2026-11-05 against the 30 s window (#795). Since #898 they are plain wave -1 Jobs that a full sync re-applies without running, so a full
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


def parse_seconds(value: str) -> int:
    """argocd-cm's timeout.reconciliation, a Go duration written as whole seconds or minutes (`120s`, `3m`)."""
    m = re.fullmatch(r"(\d+)(s|m)", value.strip())
    if not m:
        raise ValueError(f"timeout.reconciliation {value!r} is not whole seconds or minutes (120s, 3m)")
    return int(m.group(1)) * (60 if m.group(2) == "m" else 1)


def full_path_state(app: dict, expiry_s: int, now: datetime.datetime) -> tuple[str | None, float]:
    """For HEAL_PATH=full: why a delete now cannot start a full sync (None when it can), and how many seconds to
    wait first so the delete's refresh compares with staging's head (heal_kind's docstring has the mechanism).

    status.sync.revision is the revision of the app's last comparison, which the periodic resync moves to
    staging's head; operationState.syncResult.revision is the one it last synced. When they are equal, staging
    has not moved since the last sync and every heal is selective, so there is nothing to wait for."""
    status = app.get("status") or {}
    compared = (status.get("sync") or {}).get("revision") or ""
    synced = ((status.get("operationState") or {}).get("syncResult") or {}).get("revision") or ""
    if not compared or not synced:
        return (f"the app does not say both revisions (compared {compared or 'none'}, synced {synced or 'none'})", 0.0)
    if compared == synced:
        return (f"staging has not moved since the app last synced {synced[:8]}, so a heal can only be selective;"
                " run it again after the next staging commit reaches the app", 0.0)
    reconciled = status.get("reconciledAt")
    if not reconciled:
        return ("the app has no reconciledAt to time the delete against", 0.0)
    age = (now - datetime.datetime.fromisoformat(reconciled.replace("Z", "+00:00"))).total_seconds()
    return (None, max(0.0, expiry_s + EXPIRY_MARGIN_S - age))


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
    check(f"HEAL_PATH is one of {', '.join(HEAL_PATHS)} (it is {HEAL_PATH!r})", HEAL_PATH in HEAL_PATHS)
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

    if HEAL_PATH == "full":
        cm = get_json("-n", "argocd", "configmap", "argocd-cm") or {}
        raw = (cm.get("data") or {}).get("timeout.reconciliation")
        check(f"argocd-cm sets timeout.reconciliation, which HEAL_PATH=full times the delete by ({raw})", bool(raw))
        if failures:
            return finish()
        expiry = parse_seconds(raw)
        print(f"== HEAL_PATH=full: waiting for {app_name}'s last comparison to pass {expiry}s ==")
        t_exp = time.monotonic()
        while True:
            app = get_json("-n", "argocd", "application", app_name) or {}
            why, wait = full_path_state(app, expiry, datetime.datetime.now(datetime.timezone.utc))
            if why or wait <= 0 or time.monotonic() - t_exp >= EXPIRY_WAIT_S:
                break
            time.sleep(min(wait, 5.0))
        status = app.get("status") or {}
        print(f"  compared {((status.get('sync') or {}).get('revision') or '')[:8]}, last synced "
              f"{(((status.get('operationState') or {}).get('syncResult') or {}).get('revision') or '')[:8]}, "
              f"reconciledAt {status.get('reconciledAt')}")
        check(f"staging has moved since {app_name} last synced ({why or 'it has'})", why is None)
        if why is None:
            check(f"{app_name}'s last comparison passed {expiry}s within {EXPIRY_WAIT_S}s of waiting", wait <= 0)
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
    healed_by = heal_kind(healing, after["metadata"].get("creationTimestamp") or "")
    print(f"  healed by {healed_by}")
    if HEAL_PATH == "full":
        check(f"HEAL_PATH=full: a full sync put it back and ran no PreSync Job ({healed_by})",
              healed_by.startswith("a full sync to revision ") and healed_by.endswith("PreSync Jobs run first: none"))
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
