# ABOUTME: Offline: the self-heal drill reads Argo CD's operationState the way v3.5 writes it, and docs/floor.md
# ABOUTME: names ai-layer's gate Jobs, which are no longer PreSync hooks a full-sync heal waits on (#795, #898).
"""Offline: python3, PyYAML and the repo.

The two operationStates below are trimmed from the syncs that put agent/platform-console-egress back on
2026-11-05 at 10:35Z, read with `kubectl get application ai-layer -o json`. On watch-it-burn-community the app had
already synced staging's head, so self-heal synced the one missing resource (back in 1.2 s). On
watch-it-burn-private it had not, so the delete started a full sync to the new revision, which ran both PreSync
gates first (back in 27.2 s). The third case is from private at 10:41Z, where a full sync followed a selective heal.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


spec = importlib.util.spec_from_file_location("drill", REPO / "verify/test_drift_selfheal_live.py")
drill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drill)
DRILL = (REPO / "verify/test_drift_selfheal_live.py").read_text(encoding="utf-8")

SELECTIVE = {  # watch-it-burn-community, 2026-11-05T10:35:34Z
    "operation": {"initiatedBy": {"automated": True}, "sync": {
        "autoHealAttemptsCount": 1, "prune": True,
        "resources": [{"group": "networking.k8s.io", "kind": "NetworkPolicy", "name": "platform-console-egress"},
                      {"kind": "ConfigMap", "name": "kubearmor-gate-script"}]}},
    "phase": "Succeeded", "startedAt": "2026-11-05T10:35:34Z", "finishedAt": "2026-11-05T10:35:34Z",
    "syncResult": {"resources": [{"kind": "NetworkPolicy", "name": "platform-console-egress", "syncPhase": "Sync"}]},
}
FULL = {  # watch-it-burn-private, 2026-11-05T10:35:35Z
    "operation": {"initiatedBy": {"automated": True}, "sync": {
        "prune": True, "revision": "fc8a8556367ae91100d61fe7ff8a796b6ef755f5"}},
    "phase": "Succeeded", "startedAt": "2026-11-05T10:35:35Z", "finishedAt": "2026-11-05T10:36:05Z",
    "syncResult": {"resources": [
        {"kind": "ServiceAccount", "name": "otel-gate", "hookType": "PreSync", "syncPhase": "PreSync"},
        {"kind": "Job", "name": "otel-gate", "hookType": "PreSync", "syncPhase": "PreSync"},
        {"kind": "Job", "name": "kubearmor-gate", "hookType": "PreSync", "syncPhase": "PreSync"},
        {"kind": "NetworkPolicy", "name": "platform-console-egress", "syncPhase": "Sync"}]},
}

print("== the drill reads the heal count Argo CD v3.5 writes ==")
check("autoHealAttemptsCount is read (1 on the community heal)", drill.heal_count(SELECTIVE) == 1)
check("a sync without the field reads 0", drill.heal_count(FULL) == 0)
check("the old name selfHealAttemptsCount is not what the drill reads",
      drill.heal_count({"operation": {"sync": {"selfHealAttemptsCount": 4}}}) == 0)
check("an empty operationState reads 0", drill.heal_count({}) == 0)

print("== the drill names which path healed the policy ==")
sel = drill.heal_kind(SELECTIVE, "2026-11-05T10:35:35Z")
check(f"the community heal reads as selective ({sel})", sel.startswith("a selective self-heal of 2 resource(s)"))
full = drill.heal_kind(FULL, "2026-11-05T10:35:59Z")
check(f"the private heal reads as a full sync with both gates ({full})",
      full == "a full sync to revision fc8a8556, PreSync Jobs run first: kubearmor-gate, otel-gate")
check("a full sync with no hooks says none",
      drill.heal_kind({"startedAt": "2026-11-05T10:00:00Z", "operation": {"sync": {}}},
                      "2026-11-05T10:00:01Z").endswith("first: none"))
# watch-it-burn-private, 10:41Z: a selective heal at fc8a8556 put the policy back at 10:41:11, and a full sync to
# dd250dd9, which had just landed on staging, started at 10:41:13. Reading that one must not call it the healer.
LATER = {"startedAt": "2026-11-05T10:41:13Z", "phase": "Running",
         "operation": {"sync": {"revision": "dd250dd96b94ef1a6615ab625a1bbab7cb35888c"}}}
later = drill.heal_kind(LATER, "2026-11-05T10:41:11Z")
check(f"a sync that started after the policy was re-created is not named as the healer ({later})",
      later.startswith("a sync that cannot be named") and "full sync" not in later)
check("an operationState with no start time is not named either", drill.heal_kind({}, "2026-11-05T10:41:11Z")
      .startswith("a sync that cannot be named"))
ANCHORS = ("healed by {heal_kind(", "SYNC_WAIT_S:\n")
missing = [a for a in ANCHORS if a not in DRILL]
check(f"verify/test_drift_selfheal_live.py has the lines this check orders ({missing or 'both'} missing)" if missing
      else "verify/test_drift_selfheal_live.py has the lines this check orders", not missing)
if not missing:
    check("the drill reads the operationState as soon as the policy is back, before it waits for the sync to end",
          DRILL.index(ANCHORS[0]) < DRILL.index(ANCHORS[1]))

print("== ai-layer runs no hook Job, and docs/floor.md names its wave -1 gate Jobs ==")
# #898: the gates were PreSync hooks, and every full sync deleted, re-created and ran them before it applied the
# drill's policy. They are now plain Jobs at sync-wave -1, which a full sync re-applies as a no-op. A hook Job added
# back to ai-layer would bring the slow path back, so it fails here, and floor.md has to name each gate.
FLOOR = (REPO / "docs/floor.md").read_text(encoding="utf-8")
kust = yaml.safe_load((REPO / "gitops/ai-layer/kustomization.yaml").read_text(encoding="utf-8"))
hooks, gates = [], []
for res in kust.get("resources") or []:
    path = REPO / "gitops/ai-layer" / res
    if not path.is_file():
        continue
    for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        ann = ((doc or {}).get("metadata") or {}).get("annotations") or {}
        if (doc or {}).get("kind") != "Job":
            continue
        if "argocd.argoproj.io/hook" in ann:
            hooks.append(doc["metadata"]["name"])
        elif ann.get("argocd.argoproj.io/sync-wave") == "-1":
            gates.append(((doc["metadata"].get("labels") or {}).get("app.kubernetes.io/name")) or doc["metadata"]["name"])
check(f"ai-layer has no hook Job, so a full-sync heal waits on none ({', '.join(sorted(hooks)) or 'none'})", not hooks)
check(f"ai-layer has its wave -1 gate Jobs to name ({', '.join(sorted(gates))})", sorted(gates) == ["kubearmor-gate", "otel-gate"])
for job in sorted(gates):
    check(f"floor.md names the gate Job `{job}`", f"`{job}`" in FLOOR)
check("floor.md says a full sync no longer runs the gates (#898)", "full sync" in FLOOR and "#898" in FLOOR)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("Self-heal operation checks passed.")
