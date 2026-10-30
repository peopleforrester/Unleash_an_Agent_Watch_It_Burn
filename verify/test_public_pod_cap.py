# ABOUTME: Render/wiring gate for #686: the community cluster's node takes 250 pods (VPC-CNI prefix delegation plus
# ABOUTME: kubelet maxPods 250) so the room's per-attendee Jokers fit, while admin and attendee nodes keep 110.
"""The public cluster's pod cap (#686), pinned where it is written down.

The attackme node (one t3.2xlarge, the community cluster) allocated 110 pods with about 53 running, so about 55
per-attendee Jokers (#685) fit at once. Raising the cap takes two things on AL2023: VPC-CNI prefix delegation,
so the node has pod IPs past its 58 secondary addresses, and an explicit kubelet maxPods in the nodeadm
NodeConfig, because nodeadm ignores prefix delegation when it computes max-pods. Prefix delegation is on for every
cluster already; this test holds the maxPods half: a per-cluster variable, 110 by default, raised to 250 by fleet.sh
for the community role alone, and bounded so a typo cannot ask kubelet for more than the node was sized for.

What it does NOT prove, and where that is proven: that a rebuilt community node reports allocatable pods 250 and
that verify/kubecon_probe.py is green on it is the live half, owed on a rebuild with AWS access (decisions.md,
#686); that max_pods_for_role maps community->250 and everything else->110 against a sourced fleet.sh is
verify/test_cluster_roles.sh.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
TF = (REPO / "infra/terraform/aws/cluster/main.tf").read_text(encoding="utf-8")
FLEET = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the node pod cap is a per-cluster variable, default 110 ==")
var = re.search(r'variable "max_pods"\s*\{(.*?)\n\}', TF, re.S)
check("variable max_pods exists", var is not None)
vbody = var.group(1) if var else ""
check("it is a number defaulting to 110", re.search(r"type\s*=\s*number", vbody) is not None
      and re.search(r"default\s*=\s*110\b", vbody) is not None)
check("it is validated to 110..250", "var.max_pods >= 110" in vbody and "var.max_pods <= 250" in vbody)
check("the nodeadm NodeConfig reads it, not a literal",
      "maxPods: ${var.max_pods}" in TF and re.search(r"maxPods:\s*\d", TF) is None)

print("== prefix delegation is on, so the cap is kubelet's and not the node's IPs ==")
cni = re.search(r"vpc-cni\s*=\s*\{(.*?)\n    \}", TF, re.S)
cbody = cni.group(1) if cni else ""
check("the vpc-cni addon sets ENABLE_PREFIX_DELEGATION = \"true\"",
      re.search(r'ENABLE_PREFIX_DELEGATION\s*=\s*"true"', cbody) is not None)
check("and installs before the node group, so the first node boots with it",
      re.search(r"before_compute\s*=\s*true", cbody) is not None)

print("== fleet.sh raises it to 250 for the community cluster alone ==")
helper = re.search(r"max_pods_for_role\(\)\s*\{(.*?)\n\}", FLEET, re.S)
check("max_pods_for_role exists", helper is not None)
body = helper.group(1) if helper else ""
check("community gets 250", re.search(r"community\)\s*printf '250'", body) is not None)
check("every other role (admin, attendee) falls through to 110",
      re.search(r"\*\)\s*printf '110'", body) is not None and "admin)" not in body)
check("up_one derives it from the role",
      re.search(r'maxpods="\$\(max_pods_for_role "\$\{role\}"\)"', FLEET) is not None)
check("up_one passes -var max_pods on every apply",
      re.search(r'-var\s+"max_pods=\$\{maxpods\}"', FLEET) is not None)
check("the dry-run plan shows it, so a plan reveals which node takes 250",
      "-var max_pods=${maxpods}" in FLEET)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ALL PUBLIC POD-CAP CHECKS PASSED")
