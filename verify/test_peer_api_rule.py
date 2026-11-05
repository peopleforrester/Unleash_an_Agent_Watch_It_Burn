# ABOUTME: Offline gate for #906: the cluster root admits the lab VPC to the cluster API on 443, so the KubeCon
# ABOUTME: guardrails switch's peer calls, which resolve to the other cluster's private endpoint, connect.
"""Why. Both roster clusters sit in the lab VPC with private endpoint access on, so inside the VPC a cluster's API
name resolves to its private endpoint ENIs, which carry the EKS module's cluster security group. The module admits
only that cluster's own nodes there. guardrails-on in one cluster's terminal calls the other cluster's API through
the guardrails-peer kubeconfig, and every peer call timed out (watch-it-burn-private's terminal to
watch-it-burn-community, 2026-11-05: "dial tcp 10.0.50.254:443: i/o timeout"), while `fleet.sh guardrails-link`,
run from outside the VPC over the public endpoint, passed.

What this proves: module "eks" carries an ingress rule on the cluster security group for TCP 443 from the lab VPC's
CIDR, read from the VPC the root is given, on every cluster the root builds, and the public endpoint stays on.

What it does not prove, and where that is: that the pinned module reads these attribute names is
verify/test_control_plane_app_ports_module.py (E2E tools tier). That a cluster built from this root switches its
peer is the KubeCon probe's guardrails-on beat, run on the pair (decisions.md, #906).
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
    text = nsr.CLUSTER_TF.read_text(encoding="utf-8")
    module = nsr.eks_module_body(text)
    rules = nsr.rules(text, nsr.CLUSTER_RULES_ANCHOR)
    raw = nsr.rules_body(text, nsr.CLUSTER_RULES_ANCHOR)
except nsr.AnchorMissing as e:
    print(f"FAIL: anchor missing: {e}", file=sys.stderr)
    sys.exit(1)

print("== the cluster API admits the lab VPC on 443 ==")
api = [n for n, r in rules.items() if r.get("type") == "ingress" and r.get("protocol") == "tcp"
       and r.get("from_port") == 443 and r.get("to_port") == 443]
check("one ingress rule on the cluster security group opens TCP 443, and only 443", len(api) == 1, f"rules: {rules}")
for n in api:
    r = rules[n]
    check(f"{n}: its source is the lab VPC's CIDR, read from the VPC the root is given",
          r.get("cidr_blocks") == "[data.aws_vpc.lab.cidr_block]", f"rule: {r}")
    check(f"{n}: it has no other source (no 0.0.0.0/0, no hand-written group id)",
          not any(k in r for k in ("ipv6_cidr_blocks", "prefix_list_ids", "source_security_group_id", "self",
                                   "source_node_security_group")), f"rule: {r}")
    check(f"{n}: its description names 443 and the guardrails switch",
          "443" in str(r.get("description", "")) and "guardrails" in str(r.get("description", "")))
check("the cluster security group gets no other additional rule", set(rules) == set(api), f"rules: {sorted(rules)}")
check('data "aws_vpc" "lab" reads the VPC by var.vpc_id',
      re.search(r'data "aws_vpc" "lab" \{\s*id\s*=\s*var\.vpc_id\s*\}', text) is not None)

print("== on every cluster the root builds ==")
check("the rules block holds no conditional expression and no variable (no gate on a role)",
      "?" not in raw and "var." not in raw)
check("the module's cluster security group is not switched off (the rule attaches to it)",
      re.search(r"^\s*create_security_group\s*=\s*false", module, re.MULTILINE) is None)
check("the public endpoint stays on (the rule opens nothing the public endpoint does not already serve)",
      re.search(r"^\s*endpoint_public_access\s*=\s*true", module, re.MULTILINE) is not None)
check("no public access CIDR list narrows the public endpoint, which is what makes the VPC rule add no exposure",
      re.search(r"^\s*endpoint_public_access_cidrs\s*=", module, re.MULTILINE) is None)

print("== the anchors read the two blocks apart ==")
# Owns its inputs: the cluster anchor must not match inside the node rules' name, of which it is the tail.
SYN = '''module "eks" {
  node_security_group_additional_rules = {
    n = {
      from_port = 8080
      to_port   = 8080
    }
  }
}
'''
try:
    nsr.rules(SYN, nsr.CLUSTER_RULES_ANCHOR)
    check("a module with only node rules has no cluster rules block", False)
except nsr.AnchorMissing as e:
    check("a module with only node rules has no cluster rules block (AnchorMissing names the literal)",
          "security_group_additional_rules" in str(e))
check("the node rules' anchor still reads the node block", set(nsr.rules(SYN)) == {"n"})

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nALL PEER API RULE CHECKS GREEN")
