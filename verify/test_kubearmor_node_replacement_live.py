# ABOUTME: Live check of #1235's criterion (#1262) on watch-it-burn-private: with require-resource-limits at Deny, every
# ABOUTME: node has one Ready KubeArmor enforcer and kubearmor.io/* labels the snitch wrote, none put there by hand.
# SUITE: e2e
"""Needs kubectl and PRIVATE_CONTEXT naming the kube-context of watch-it-burn-private. Every missing prerequisite is a
failure, never a skip.

Why. On 2026-11-08 a node group replacement on watch-it-burn-private (run 18849, #1136) left the new node with no
KubeArmor enforcer. The KubeArmor operator runs a snitch Job on each new node, and the snitch writes the node's
`kubearmor.io/*` labels, which the enforcer DaemonSet selects on. require-resource-limits, at Deny on that cluster at
all times, refused the snitch Job, so the node got no labels and no enforcer, and the labels were put on by hand with
`kubectl label` (manager `kubectl-label`). #1235 and then #1236 let the snitch through: the policy's matchCondition
skips KubeArmor's workload objects in the kubearmor namespace. The criterion this test holds is #1235's: "On
watch-it-burn-private, with require-resource-limits at Deny, a node replacement ends with the KubeArmor enforcer
DaemonSet at one Ready pod per node and no hand-put node labels."

A run cannot replace a node group, so this test does not cause one. It reads the state any replacement must end in,
and it fails when the criterion stops holding, in each of these ways:

- the kube-context is not watch-it-burn-private;
- require-resource-limits is not at Deny, so the cluster is not in the state the criterion is about, or it no longer
  carries the matchCondition that admits the snitch Job, git's `kubearmor-workloads-judged-at-their-pods`;
- there is no Ready node to hold the criterion on;
- a Ready node carries none of the `kubearmor.io/*` labels the enforcer DaemonSet selects on (the snitch never ran);
- a `kubearmor.io/*` label on a node is owned, in the node's managedFields, by any field manager but `snitch`
  (`kubectl-label`, `kubectl-edit`, `kubectl-patch`, `kubectl-client-side-apply` and the rest), alone or beside it:
  that label was put there by hand;
- a Ready node has no Ready enforcer pod (`kubearmor-app=kubearmor`), or more than one;
- an enforcer DaemonSet has fewer Ready pods than it schedules.

After a real node replacement, run this and it holds the new node to the same state. Until one, it holds the node
run 19566 stripped and had the snitch relabel (decisions.md, 2026-11-09, #1235, run 19566).

verify/test_kubearmor_node_replacement_checks.py runs `run` offline against a fake healthy cluster and one fake per
way above, and holds that each way fails here. This spends nothing and changes nothing: read-only kubectl gets.

Usage: PRIVATE_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] python3 verify/test_kubearmor_node_replacement_live.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

CLUSTER = "watch-it-burn-private"
POLICY = "require-resource-limits"
CONDITION_NAME = "kubearmor-workloads-judged-at-their-pods"
# git's policies/kyverno/require-resource-limits.yaml; the offline checks hold this equal to the file.
CONDITION = "!(request.namespace == 'kubearmor' && request.kind.kind != 'Pod')"
LABEL_PREFIX = "kubearmor.io/"
SNITCH = "snitch"
ENFORCER_LABEL = "kubearmor-app=kubearmor"


class Cluster:
    """Read-only kubectl gets on one cluster, every call naming its context. The offline checks fake each method."""

    def __init__(self, context: str) -> None:
        self.context = context

    def _kubectl(self, *args: str) -> str:
        r = subprocess.run(["kubectl", "--context", self.context, "--request-timeout=30s", *args],
                           capture_output=True, text=True, timeout=90)
        if r.returncode != 0:
            raise RuntimeError(f"kubectl --context {self.context} {' '.join(args)}: {r.stderr.strip()}")
        return r.stdout

    def cluster_name(self) -> str:
        return self._kubectl("config", "view", "--minify", "-o", "jsonpath={.contexts[0].context.cluster}").strip()

    def policy(self) -> dict | None:
        try:
            return json.loads(self._kubectl("get", "validatingpolicy", POLICY, "-o", "json"))
        except RuntimeError as e:
            if "NotFound" in str(e) or "not found" in str(e):
                return None
            raise

    def nodes(self) -> dict:
        return json.loads(self._kubectl("get", "nodes", "--show-managed-fields", "-o", "json"))

    def enforcer_pods(self) -> dict:
        return json.loads(self._kubectl("-n", "kubearmor", "get", "pods", "-l", ENFORCER_LABEL, "-o", "json"))

    def enforcer_daemonsets(self) -> dict:
        return json.loads(self._kubectl("-n", "kubearmor", "get", "daemonsets", "-l", ENFORCER_LABEL, "-o", "json"))


def _ready(obj: dict) -> bool:
    return any(c.get("type") == "Ready" and c.get("status") == "True"
               for c in (obj.get("status") or {}).get("conditions") or [])


def kubearmor_labels(node: dict) -> dict[str, str]:
    return {k: v for k, v in ((node.get("metadata") or {}).get("labels") or {}).items() if k.startswith(LABEL_PREFIX)}


def label_owners(node: dict) -> dict[str, list[str]]:
    """Each kubearmor.io/* label on the node, with every field manager that owns it, as `manager (operation time)`."""
    owners: dict[str, list[str]] = {}
    for mf in (node.get("metadata") or {}).get("managedFields") or []:
        labels = ((mf.get("fieldsV1") or {}).get("f:metadata") or {}).get("f:labels") or {}
        for key in labels:
            name = key[2:] if key.startswith("f:") else key
            if name.startswith(LABEL_PREFIX):
                owners.setdefault(name, []).append(
                    f"{mf.get('manager')} ({mf.get('operation')} {mf.get('time')})")
    return owners


def hand_put(node: dict) -> list[str]:
    """The node's kubearmor.io/* labels some manager other than the snitch owns, or no manager owns at all."""
    owners = label_owners(node)
    bad = []
    for name in sorted(kubearmor_labels(node)):
        others = [o for o in owners.get(name, []) if o.split(" ", 1)[0] != SNITCH]
        if others:
            bad.append(f"{name} owned by {', '.join(others)}")
        elif not owners.get(name):
            bad.append(f"{name} owned by no field manager (managedFields unread?)")
    return bad


def policy_checks(policy: dict | None) -> list[tuple[str, bool, str]]:
    if policy is None:
        return [(f"{POLICY} is installed", False, "validatingpolicy not found")]
    spec = policy.get("spec") or {}
    actions = spec.get("validationActions") or []
    conds = {c.get("name"): " ".join((c.get("expression") or "").split()) for c in spec.get("matchConditions") or []}
    return [
        (f"{POLICY} is at Deny, the state the criterion is about", "Deny" in actions, f"validationActions: {actions!r}"),
        (f"{POLICY} carries git's {CONDITION_NAME}, so the snitch Job a new node runs is admitted",
         conds.get(CONDITION_NAME) == CONDITION, f"matchConditions: {conds!r}"),
    ]


def node_checks(nodes: dict, pods: dict, daemonsets: dict) -> list[tuple[str, bool, str]]:
    ready_nodes = [n for n in nodes.get("items") or [] if _ready(n)]
    results = [("the cluster has a Ready node", bool(ready_nodes), f"{len(nodes.get('items') or [])} nodes, none Ready")]
    on_node: dict[str, list[dict]] = {}
    for p in pods.get("items") or []:
        on_node.setdefault((p.get("spec") or {}).get("nodeName") or "", []).append(p)
    for n in ready_nodes:
        name = n["metadata"]["name"]
        labels = kubearmor_labels(n)
        results.append((f"{name}: carries the snitch's kubearmor.io/* labels", bool(labels),
                        "no kubearmor.io/* label: the snitch never ran on this node"))
        bad = hand_put(n)
        results.append((f"{name}: no kubearmor.io/* label put there by hand (each owned by `{SNITCH}` alone)",
                        not bad, "; ".join(bad)))
        mine = on_node.get(name, [])
        ready = [p["metadata"]["name"] for p in mine if _ready(p)]
        results.append((f"{name}: one Ready KubeArmor enforcer pod", len(ready) == 1,
                        f"{len(ready)} Ready of {len(mine)} enforcer pods: "
                        f"{[p['metadata']['name'] for p in mine]!r}"))
    for ds in daemonsets.get("items") or []:
        st = ds.get("status") or {}
        want, ready = st.get("desiredNumberScheduled", 0), st.get("numberReady", 0)
        results.append((f"enforcer DaemonSet {ds['metadata']['name']}: every pod it schedules is Ready ({ready}/{want})",
                        ready == want, f"desired {want}, ready {ready}"))
    return results


def report(results: list[tuple[str, bool, str]]) -> list[str]:
    failed = []
    for label, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))
        if not ok:
            failed.append(label)
    return failed


def run(cluster: Cluster) -> list[str]:
    """Every check; the failed labels."""
    try:
        name = cluster.cluster_name()
        print(f"== {cluster.context}: the cluster ==")
        failed = report([(f"the kube-context is {CLUSTER}", name == CLUSTER or name.endswith(f"/{CLUSTER}"),
                          f"context {cluster.context} names cluster {name!r}")])
        if failed:
            return failed
        print(f"== {POLICY} ==")
        failed += report(policy_checks(cluster.policy()))
        print("== each node: its KubeArmor enforcer and who wrote its kubearmor.io/* labels ==")
        failed += report(node_checks(cluster.nodes(), cluster.enforcer_pods(), cluster.enforcer_daemonsets()))
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        failed = report([(f"{CLUSTER} can be read", False, str(e))])
    return failed


def main() -> int:
    missing = ["kubectl is not on PATH"] if shutil.which("kubectl") is None else []
    context = os.environ.get("PRIVATE_CONTEXT", "")
    if not context:
        missing.append(f"PRIVATE_CONTEXT is not set: name the kube-context of {CLUSTER}")
    if missing:
        print("FAIL: test_kubearmor_node_replacement_live.py cannot run; this is a failure, not a skip:",
              file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1
    failed = run(Cluster(context))
    if failed:
        print(f"\nFAILED: {len(failed)}: a node on {CLUSTER} would not come through a replacement with its enforcer "
              "and snitch-written labels", file=sys.stderr)
        return 1
    print(f"\nOn {CLUSTER}, at Deny, every node has one Ready KubeArmor enforcer and kubearmor.io/* labels the snitch "
          "wrote, none by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
