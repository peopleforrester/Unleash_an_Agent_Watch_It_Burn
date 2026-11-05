# ABOUTME: Offline gate for #869: the cluster root lets the EKS control plane reach the workshop apps' pod ports
# ABOUTME: (8080, 3000) on the nodes, on every cluster it builds, so Service-proxy probes answer instead of hanging.
"""Why. lab-platform's attendee check, and an attendee's `kubectl get --raw /api/v1/namespaces/<ns>/services/
http:<svc>:<port>/proxy/<path>`, reach each workshop app through the API server's Service proxy, which dials the
app's pod from the control-plane ENIs. Those ENIs carry the EKS module's cluster security group. The module's
recommended node rules admit that group only on 443, 4443, 6443, 8443, 9443, 10250 and 10251, so a probe to an
app on 8080 or 3000 was accepted and then timed out (watch-it-burn-private, 2026-11-05: "dial tcp
10.0.97.64:8080: connect: connection timed out" after 133 s).

What this proves: module "eks" in infra/terraform/aws/cluster carries an ingress rule from the cluster security
group for each app port, unconditionally (no role or count gate), and the module's recommended rules, which hold
the API's own ports, stay on.

What it does not prove, and where that is: that the pinned module (21.29.x) reads these attribute names and maps
source_cluster_security_group to the group the control plane carries is verify/test_control_plane_app_ports_module.py
(E2E tools tier). That a cluster built from this root answers the probes is lab-platform's
TestTheLearnerAppsGroupReachesEveryWorkshopAppLive, run on a cluster once the change is applied (decisions.md, #869).
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import node_sg_rules as nsr  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


try:
    module = nsr.eks_module_body()
    rules = nsr.rules()
    raw_rules = nsr.rules_body()
except nsr.AnchorMissing as e:
    print(f"FAIL: anchor missing: {e}", file=sys.stderr)
    sys.exit(1)

print("== each workshop app port is open to the control plane ==")
for port, apps in nsr.APP_PORTS.items():
    names = nsr.rule_for_port(rules, port)
    check(f"TCP {port} ({apps}) is admitted from the cluster security group", bool(names), f"rules: {rules}")
    for n in names:
        r = rules[n]
        check(f"{n}: its source is the cluster security group, not a CIDR or a hand-written group id",
              not any(k in r for k in ("cidr_blocks", "ipv6_cidr_blocks", "prefix_list_ids", "source_security_group_id",
                                       "self")))
        check(f"{n}: it carries a description naming the port", str(port) in str(r.get("description", "")))

print("== the rules are narrow: one app port each, nothing wider ==")
for n, r in rules.items():
    span = (r.get("to_port", 0) - r.get("from_port", 0)) if all(isinstance(r.get(k), int) for k in ("from_port", "to_port")) else None
    check(f"{n}: from_port and to_port are literal numbers", span is not None, f"rule: {r}")
    check(f"{n}: it opens a single port", span == 0, f"rule: {r}")
    check(f"{n}: it is an app port this test names", r.get("from_port") in nsr.APP_PORTS,
          "add the port and its apps to node_sg_rules.APP_PORTS with the measurement that needs it")

print("== on every cluster the root builds ==")
check("the rules block holds no conditional expression (no `? :` on a role or variable)",
      "?" not in raw_rules and "var." not in raw_rules)
check('module "eks" has no count or for_each, so every apply of the root builds the rules',
      re.search(r"^\s*(count|for_each)\s*=", module, re.MULTILINE) is None)
check("the module's own node security group is not switched off (the rules attach to it)",
      re.search(r"^\s*create_node_security_group\s*=\s*false", module, re.MULTILINE) is None)
check("the module's recommended node rules (443, 10250 and the webhook ports) stay on",
      re.search(r"^\s*node_security_group_enable_recommended_rules\s*=\s*false", module, re.MULTILINE) is None)
check("the module's cluster security group is not switched off (it is the rules' source)",
      re.search(r"^\s*create_security_group\s*=\s*false", module, re.MULTILINE) is None)

print("== the parser reads a broken block as broken ==")
# Owns its inputs: a synthetic root, so the check of the checker does not hang on main.tf's wording.
SYN = '''module "eks" {
  node_security_group_additional_rules = {
    a = {
      from_port                     = 8080
      to_port                       = 8080
      source_cluster_security_group = false
    }
    b = {
      from_port   = 3000
      to_port     = 3000
      cidr_blocks = ["0.0.0.0/0"]
    }
  }
}
'''
syn = nsr.rules(SYN)
check("the synthetic block parses to its two rules", set(syn) == {"a", "b"}, f"parsed: {syn}")
check("a rule with source_cluster_security_group = false does not count for 8080", nsr.rule_for_port(syn, 8080) == [])
check("a CIDR rule does not count for 3000", nsr.rule_for_port(syn, 3000) == [])
try:
    nsr.rules('module "other" {\n}\n')
    check("a root without module \"eks\" raises AnchorMissing", False)
except nsr.AnchorMissing as e:
    check("a root without module \"eks\" raises AnchorMissing naming the literal", 'module "eks" {' in str(e))

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nALL CONTROL-PLANE APP-PORT CHECKS GREEN")
