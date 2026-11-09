# ABOUTME: Offline checks for verify/test_kubearmor_node_replacement_live.py (#1262): a fake watch-it-burn-private whose
# ABOUTME: replaced node the snitch relabelled passes, and each way #1235's criterion can stop holding fails.
"""test_kubearmor_node_replacement_live.py is the live test for #1235's criterion "On watch-it-burn-private, with
require-resource-limits at Deny, a node replacement ends with the KubeArmor enforcer DaemonSet at one Ready pod per
node and no hand-put node labels". It needs the cluster. This runs its `run` against fake clusters: the healthy one,
shaped on what run 19566 read after the snitch relabelled ip-10-0-90-97, passes, and each way the criterion can stop
holding fails it by name. The hand-put fakes are shaped on what run 19479 read before: the node's nine labels owned
by manager `kubectl-label` at 2026-11-08T23:53:21Z. The DESIRED 0 fake is run 18849's: the snitch refused, so the
node has no labels and the DaemonSet never scheduled there. The policy's matchCondition is held equal to git's
policies/kyverno/require-resource-limits.yaml, so the live check reads for the condition git ships.

Nothing here touches the network or a cluster.
"""
from __future__ import annotations

import contextlib
import copy
import io
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import test_kubearmor_node_replacement_live as live  # noqa: E402

POLICY_FILE = REPO / "policies/kyverno/require-resource-limits.yaml"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


NODE_A = "ip-10-0-90-97.us-west-2.compute.internal"
NODE_B = "ip-10-0-90-162.us-west-2.compute.internal"
LABELS = {"apparmorfs": "no", "btf": "yes", "enforcer": "bpf", "nri-socket": "var_run_nri_nri.sock",
          "oci-hooks": "no", "rand": "fwzj", "runtime": "containerd", "seccomp": "yes", "securityfs": "yes",
          "socket": "run_containerd_containerd.sock"}


def _labels_field(names) -> dict:
    return {"f:metadata": {"f:labels": {f"f:kubearmor.io/{k}": {} for k in names}}}


def node(name: str, manager: str = "snitch", time: str = "2026-11-09T14:33:46Z", ready: bool = True,
         labels: dict | None = None) -> dict:
    labels = LABELS if labels is None else labels
    return {
        "metadata": {
            "name": name,
            "labels": {"kubernetes.io/os": "linux", **{f"kubearmor.io/{k}": v for k, v in labels.items()}},
            "managedFields": [
                {"manager": "kubelet", "operation": "Update", "time": "2026-11-08T23:32:12Z",
                 "fieldsV1": {"f:metadata": {"f:labels": {"f:kubernetes.io/os": {}}}}},
                *([{"manager": manager, "operation": "Update", "time": time, "fieldsV1": _labels_field(labels)}]
                  if labels else []),
            ],
        },
        "status": {"conditions": [{"type": "Ready", "status": "True" if ready else "False"}]},
    }


def pod(name: str, on: str, ready: bool = True) -> dict:
    return {"metadata": {"name": name}, "spec": {"nodeName": on},
            "status": {"conditions": [{"type": "Ready", "status": "True" if ready else "False"}]}}


def daemonset(name: str, desired: int, ready: int) -> dict:
    return {"metadata": {"name": name}, "status": {"desiredNumberScheduled": desired, "numberReady": ready}}


def git_policy() -> dict:
    return yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))


def armed_policy() -> dict:
    """git's policy as the admin profile's armed root patches it: validationActions Deny, nothing else changed."""
    pol = git_policy()
    pol["spec"]["validationActions"] = ["Deny"]
    return pol


class FakeCluster(live.Cluster):
    def __init__(self, name: str = "watch-it-burn-private", policy: dict | None = None, nodes: list | None = None,
                 pods: list | None = None, daemonsets: list | None = None, policy_missing: bool = False,
                 unreadable: str = "") -> None:
        super().__init__("watch-it-burn-private")
        self.name = name
        self._policy = None if policy_missing else (armed_policy() if policy is None else policy)
        self._nodes = [node(NODE_A)] if nodes is None else nodes
        self._pods = [pod("kubearmor-bpf-containerd-98c2c-dtzgv", NODE_A)] if pods is None else pods
        self._ds = [daemonset("kubearmor-bpf-containerd-98c2c", 1, 1),
                    daemonset("kubearmor---cf83e", 0, 0)] if daemonsets is None else daemonsets
        self.unreadable = unreadable

    def _kubectl(self, *args: str) -> str:
        raise AssertionError(f"the offline checks ran kubectl {args!r}")

    def cluster_name(self) -> str:
        return self.name

    def policy(self) -> dict | None:
        return self._policy

    def nodes(self) -> dict:
        if self.unreadable:
            raise RuntimeError(self.unreadable)
        return {"items": self._nodes}

    def enforcer_pods(self) -> dict:
        return {"items": self._pods}

    def enforcer_daemonsets(self) -> dict:
        return {"items": self._ds}


def failed(cluster: FakeCluster) -> list[str]:
    with contextlib.redirect_stdout(io.StringIO()):
        return live.run(cluster)


def fails_on(case: str, cluster: FakeCluster, needle: str) -> None:
    got = failed(cluster)
    check(f"{case}: fails, naming {needle!r}", any(needle in f for f in got), f"failed: {got!r}")


print("== the live check reads for the policy git ships ==")
pol = git_policy()
conds = {c.get("name"): " ".join((c.get("expression") or "").split())
         for c in (pol.get("spec") or {}).get("matchConditions") or []}
check(f"git's {live.POLICY} carries {live.CONDITION_NAME} as the live check's CONDITION",
      conds.get(live.CONDITION_NAME) == live.CONDITION, f"git: {conds!r}, live: {live.CONDITION!r}")

print("== a healthy cluster passes ==")
got = failed(FakeCluster())
check("one node, labels owned by the snitch alone, one Ready enforcer, Deny with the condition: nothing fails",
      got == [], repr(got))
two = FakeCluster(nodes=[node(NODE_A), node(NODE_B, time="2026-11-08T23:24:58Z")],
                  pods=[pod("e-a", NODE_A), pod("e-b", NODE_B)], daemonsets=[daemonset("kubearmor-bpf", 2, 2)])
check("two nodes, each with its own enforcer and snitch labels: nothing fails", failed(two) == [], repr(failed(two)))
check("an ARN-form cluster name in the kubeconfig is the same cluster",
      failed(FakeCluster(name="arn:aws:eks:us-west-2:515966504359:cluster/watch-it-burn-private")) == [])
notready = FakeCluster(nodes=[node(NODE_A), node(NODE_B, manager="kubectl-label", ready=False)])
check("a NotReady node, as one draining in a replacement, is not held to an enforcer", failed(notready) == [],
      repr(failed(notready)))

print("== each way the criterion stops holding fails ==")
fails_on("the context is the community cluster", FakeCluster(name="watch-it-burn-community"),
         "the kube-context is watch-it-burn-private")
audit = armed_policy()
audit["spec"]["validationActions"] = ["Audit"]
fails_on("require-resource-limits at Audit", FakeCluster(policy=audit), "is at Deny")
nocond = armed_policy()
nocond["spec"].pop("matchConditions", None)
fails_on("require-resource-limits without the snitch's matchCondition", FakeCluster(policy=nocond),
         live.CONDITION_NAME)
fails_on("require-resource-limits not installed", FakeCluster(policy_missing=True), "is installed")
fails_on("no Ready node", FakeCluster(nodes=[node(NODE_A, ready=False)], pods=[]), "has a Ready node")
fails_on("the labels hand-put with kubectl label (run 19479's read)",
         FakeCluster(nodes=[node(NODE_A, manager="kubectl-label", time="2026-11-08T23:53:21Z")]),
         f"{NODE_A}: no kubearmor.io/* label put there by hand")
both = node(NODE_A)
both["metadata"]["managedFields"].append({"manager": "kubectl-edit", "operation": "Update",
                                          "time": "2026-11-09T15:00:00Z", "fieldsV1": _labels_field(["enforcer"])})
fails_on("one label co-owned by the snitch and a hand edit", FakeCluster(nodes=[both]), "put there by hand")
unowned = node(NODE_A)
unowned["metadata"]["managedFields"] = unowned["metadata"]["managedFields"][:1]
fails_on("labels with no managedFields entry (read without --show-managed-fields)", FakeCluster(nodes=[unowned]),
         "put there by hand")
fails_on("the snitch refused, DESIRED 0 (run 18849): no labels, no enforcer",
         FakeCluster(nodes=[node(NODE_A, labels={})], pods=[], daemonsets=[daemonset("kubearmor-bpf", 0, 0)]),
         f"{NODE_A}: carries the snitch's kubearmor.io/* labels")
fails_on("the snitch refused, DESIRED 0 (run 18849): the enforcer half",
         FakeCluster(nodes=[node(NODE_A, labels={})], pods=[], daemonsets=[daemonset("kubearmor-bpf", 0, 0)]),
         f"{NODE_A}: one Ready KubeArmor enforcer pod")
fails_on("a replaced node with labels but no enforcer pod",
         FakeCluster(nodes=[node(NODE_A), node(NODE_B)], pods=[pod("e-a", NODE_A)]),
         f"{NODE_B}: one Ready KubeArmor enforcer pod")
fails_on("the enforcer pod not Ready", FakeCluster(pods=[pod("e-a", NODE_A, ready=False)]),
         f"{NODE_A}: one Ready KubeArmor enforcer pod")
fails_on("two Ready enforcer pods on one node", FakeCluster(pods=[pod("e-a", NODE_A), pod("e-a2", NODE_A)]),
         f"{NODE_A}: one Ready KubeArmor enforcer pod")
fails_on("an enforcer DaemonSet short of Ready pods", FakeCluster(daemonsets=[daemonset("kubearmor-bpf", 2, 1)]),
         "every pod it schedules is Ready (1/2)")
fails_on("the cluster cannot be read", FakeCluster(unreadable="connection refused"),
         "watch-it-burn-private can be read")
hand_b = FakeCluster(nodes=[node(NODE_A), node(NODE_B, manager="kubectl-label")],
                     pods=[pod("e-a", NODE_A), pod("e-b", NODE_B)])
got = failed(hand_b)
check("a second node hand-labelled beside a healthy one fails on that node alone",
      got == [f"{NODE_B}: no kubearmor.io/* label put there by hand (each owned by `snitch` alone)"], repr(got))

print("== the live test's own guards ==")
src = (HERE / "test_kubearmor_node_replacement_live.py").read_text(encoding="utf-8")
check("it reads nodes with --show-managed-fields, without which kubectl drops the owners it judges",
      '"get", "nodes", "--show-managed-fields"' in src)
check("its one kubectl call names its context",
      '"kubectl", "--context", self.context' in src and src.count("subprocess.run(") == 1)
check("it is in the live suite, not the offline one", "\n# SUITE: e2e\n" in src)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All KubeArmor node replacement checks passed.")
