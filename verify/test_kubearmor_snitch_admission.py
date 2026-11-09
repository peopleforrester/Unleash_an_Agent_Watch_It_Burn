# ABOUTME: Holds #1236's fix: require-resource-limits skips KubeArmor's workload objects in the kubearmor namespace and
# ABOUTME: judges their Pods, which that namespace's LimitRange fills, so the operator's snitch Job is admitted at Deny.
"""Offline: reads the policy, the kubearmor-config chart's LimitRange and two Application files. Renders nothing.

Why. On 2026-11-08 #1042's apply replaced watch-it-burn-private's node group, and the KubeArmor operator logged
`Cannot run snitch on node ip-10-0-90-97 ... Policy require-resource-limits failed`. The admin profile arms that policy
as Deny. The operator builds its per-node snitch Job with no limits, and KubeArmorConfig has no field to give it any.
#1081's LimitRange fills limits into Pods, but Kyverno's autogen rule judges the Job's pod template and refused the Job
before any Pod existed. The snitch is what writes the kubearmor.io/* labels the enforcer DaemonSet selects on, so the
new node got no enforcer, and the KubeCon admin probe's Challenge 2 beat leaked the recipe (decisions.md, 2026-11-08,
#1042, run 18828).

The fix is two halves that only work together: the policy's matchCondition skips non-Pod objects in kubearmor, and
the LimitRange gives every Pod there the limits the policy still asks of it. This test fails when either half goes,
when the condition widens past the kubearmor namespace or to Pods, and when arming stops leaving the condition in
place. verify/test_kyverno_cel_policies.py runs the policy through Kyverno's own engine on a snitch Job.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
POLICY = REPO / "policies/kyverno/require-resource-limits.yaml"
LIMITRANGE = REPO / "gitops/kubearmor-config/templates/limitrange.yaml"
KUBEARMOR_APP = REPO / "gitops/bootstrap/apps/kubearmor.yaml"
POLICIES_APP = REPO / "gitops/bootstrap/apps/kyverno-policies.yaml"
CONDITION = "!(request.namespace == 'kubearmor' && request.kind.kind != 'Pod')"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


print("== require-resource-limits ==")
pol = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
spec = pol.get("spec") or {}
conds = spec.get("matchConditions") or []
mine = [m for m in conds if m.get("name") == "kubearmor-workloads-judged-at-their-pods"]
check("it carries the matchCondition kubearmor-workloads-judged-at-their-pods", len(mine) == 1,
      f"matchConditions: {conds!r}")
expr = " ".join((mine[0].get("expression") or "").split()) if mine else ""
check("the condition skips non-Pod objects in the kubearmor namespace and nothing else", expr == CONDITION,
      f"expression: {expr!r}, want {CONDITION!r}")
check("it is the policy's only matchCondition, so no other skip rides in beside it", len(conds) == 1,
      f"matchConditions: {[m.get('name') for m in conds]!r}")
rules = (spec.get("matchConstraints") or {}).get("resourceRules") or []
check("the policy is still written against Pods, so a Pod in kubearmor is judged",
      any("pods" in (r.get("resources") or []) and "" in (r.get("apiGroups") or []) for r in rules), repr(rules))
check("no namespaceSelector takes the kubearmor namespace out whole",
      "namespaceSelector" not in (spec.get("matchConstraints") or {}))
autogen = (spec.get("autogen") or {}).get("podControllers") or {}
check("autogen is left on, so Beat 1 still fails at the Deployment outside kubearmor",
      autogen.get("controllers", None) != [], repr(autogen))

print("== the kubearmor namespace's LimitRange, the other half ==")
lr = yaml.safe_load(LIMITRANGE.read_text(encoding="utf-8"))
lim = next((x for x in (lr.get("spec") or {}).get("limits") or [] if x.get("type") == "Container"), {})
check("a LimitRange gives every container there default cpu and memory limits",
      lr.get("kind") == "LimitRange" and {"cpu", "memory"} <= set(lim.get("default") or {}), repr(lim))
app = yaml.safe_load(KUBEARMOR_APP.read_text(encoding="utf-8"))
dest = (app.get("spec") or {}).get("destination") or {}
check("the kubearmor Application, which renders that LimitRange, deploys into the namespace the condition names",
      dest.get("namespace") == "kubearmor", repr(dest))
sources = (app.get("spec") or {}).get("sources") or []
check("and renders gitops/kubearmor-config, the chart the LimitRange is in",
      any(s.get("path") == "gitops/kubearmor-config" for s in sources))

print("== arming keeps the condition ==")
papp = yaml.safe_load(POLICIES_APP.read_text(encoding="utf-8"))
patches = (((papp.get("spec") or {}).get("source") or {}).get("kustomize") or {}).get("patches") or []
mine_patch = [p for p in patches if (p.get("target") or {}).get("name") == "require-resource-limits"]
ops = [op for p in mine_patch for op in (yaml.safe_load(p.get("patch") or "[]") or [])]
check("the armed root patches require-resource-limits", len(mine_patch) == 1)
check("and patches only /spec/validationActions, so the condition stays at Deny",
      bool(ops) and all(op.get("path") == "/spec/validationActions" for op in ops), repr(ops))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All KubeArmor snitch admission checks passed.")
