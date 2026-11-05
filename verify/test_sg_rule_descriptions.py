# ABOUTME: Offline gate for #957: every security group and rule description the fleet roots write is one AWS accepts,
# ABOUTME: so a plan or an apply never fails on a description's characters, as plan-policy did on staging 2cb0484d.
"""Why. #906 added the cluster root's lab-VPC rule with the description "... the KubeCon guardrails switch's peer
link". The AWS provider checks an EC2 security group rule description against ^[0-9A-Za-z_ .:/()#,@\\[\\]+=&;{}!$*-]*$
and at most 255 characters, and the apostrophe is not in that set, so `terraform plan` of aws/cluster failed in the
plan-policy workflow on staging at 2cb0484d (issue #957), and an apply would have failed the same way. The offline
tests read the rule's ports and source, not its characters.

What this proves: each description in module "eks"'s node and cluster security group rule blocks, and each
description inside an aws_security_group resource in the network and cluster roots, matches that pattern and length.

What it does not prove, and where that is: that the plan as a whole succeeds is the plan-policy workflow
(.github/workflows/plan-policy.yml, infra/policy/plan/plan-fleet.py), which needs terraform and a local AWS mock.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import node_sg_rules as nsr  # noqa: E402

REPO = nsr.REPO
NETWORK_TF = REPO / "infra/terraform/aws/network/main.tf"
# The AWS provider's validation of an EC2 security group (and rule) description, as it printed it in the failing run.
AWS_SG_DESCRIPTION = re.compile(r"^[0-9A-Za-z_ .:/()#,@\[\]+=&;{}!$*-]*$")
MAX_LEN = 255
SG_RESOURCE = re.compile(r'^resource "aws_security_group" "([A-Za-z0-9_]+)" \{', re.MULTILINE)
DESCRIPTION_LINE = re.compile(r'^\s*description\s*=\s*"(.*)"\s*$', re.MULTILINE)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def accepted(desc: str) -> bool:
    return len(desc) <= MAX_LEN and AWS_SG_DESCRIPTION.match(desc) is not None


def block_after(text: str, start: int) -> str:
    """The body from the `{` that ends at `start` to its matching `}`."""
    depth, i = 1, start
    while i < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    if depth:
        raise nsr.AnchorMissing(f"a block opened at offset {start} never closes")
    return text[start:i - 1]


def sg_resource_descriptions(text: str) -> dict[str, list[str]]:
    """aws_security_group name -> every description in its body (its own, then its ingress and egress rules')."""
    return {m.group(1): DESCRIPTION_LINE.findall(block_after(text, m.end())) for m in SG_RESOURCE.finditer(text)}


try:
    cluster_text = nsr.CLUSTER_TF.read_text(encoding="utf-8")
    eks_blocks = {
        "node_security_group_additional_rules": nsr.rules(cluster_text),
        "security_group_additional_rules": nsr.rules(cluster_text, nsr.CLUSTER_RULES_ANCHOR),
    }
    network_text = NETWORK_TF.read_text(encoding="utf-8")
    sg_resources = {
        str(p.relative_to(REPO)): sg_resource_descriptions(t)
        for p, t in ((NETWORK_TF, network_text), (nsr.CLUSTER_TF, cluster_text))
    }
except nsr.AnchorMissing as e:
    print(f"FAIL: anchor missing: {e}", file=sys.stderr)
    sys.exit(1)

print('== module "eks" rule descriptions are ones AWS accepts ==')
for block, rules in eks_blocks.items():
    check(f"{block}: the block has rules to read", len(rules) > 0, f"rules: {rules}")
    for name, rule in rules.items():
        desc = rule.get("description")
        check(f"{block}.{name}: has a description", isinstance(desc, str) and desc != "", f"rule: {rule}")
        if isinstance(desc, str):
            check(f"{block}.{name}: its description is one AWS accepts", accepted(desc),
                  f"{desc!r} ({len(desc)} chars) is not in {AWS_SG_DESCRIPTION.pattern} or is over {MAX_LEN}")

print("== aws_security_group resource descriptions are ones AWS accepts ==")
check("the network root's bedrock_vpce security group is read",
      "bedrock_vpce" in sg_resources[str(NETWORK_TF.relative_to(REPO))], f"read: {sg_resources}")
for path, groups in sg_resources.items():
    for group, descs in groups.items():
        check(f"{path} aws_security_group.{group}: has a description", len(descs) > 0)
        for desc in descs:
            check(f"{path} aws_security_group.{group}: {desc!r} is one AWS accepts", accepted(desc),
                  f"not in {AWS_SG_DESCRIPTION.pattern} or over {MAX_LEN} chars")

print("== the check reads the description that failed plan-policy as refused ==")
# Owns its inputs: the description #906 wrote, which the AWS provider refused on staging at 2cb0484d.
check("the apostrophe in \"switch's\" is refused",
      not accepted("Lab VPC to the cluster API on 443/tcp (the KubeCon guardrails switch's peer link)"))
check("a description over 255 characters is refused", not accepted("a" * 256))
check("the reworded description is accepted",
      accepted("Lab VPC to the cluster API on 443/tcp (the peer link of the KubeCon guardrails switch)"))
SYN = 'resource "aws_security_group" "x" {\n  description = "ok"\n  ingress {\n    description = "it\'s"\n  }\n}\n'
check("an ingress block's description inside an aws_security_group is read",
      sg_resource_descriptions(SYN) == {"x": ["ok", "it's"]}, f"read: {sg_resource_descriptions(SYN)}")

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nALL SECURITY GROUP DESCRIPTION CHECKS GREEN")
