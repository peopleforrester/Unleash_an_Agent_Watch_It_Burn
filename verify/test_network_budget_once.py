# ABOUTME: The fleet budget is account-wide, so only one lab VPC state per account may create it: the network root
# ABOUTME: makes it behind create_budget, and the run-of-show's second-region applies turn it off.
"""On 2026-10-31 the run-of-show's us-east-2 and us-east-1 lab VPC applies (#643) both failed on
'DuplicateRecordException: A budget or resource with the same name but a different internalId already exists':
aws_budgets_budget.fleet is one per account, and us-west-2's state already holds it. The VPCs themselves applied."""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
TF = (REPO / "infra/terraform/aws/network/main.tf").read_text(encoding="utf-8")
ROS = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


var = re.search(r'^variable "create_budget" \{(.*?)^\}', TF, re.S | re.M)
check("the network root has a create_budget variable", var is not None)
check("it defaults on, so the home region's state keeps the budget it already holds",
      var is not None and re.search(r"^\s*default\s*=\s*true\s*$", var.group(1), re.M) is not None)
budget = re.search(r'^resource "aws_budgets_budget" "fleet" \{(.*?)^\}', TF, re.S | re.M)
check("the budget is created only when create_budget is set",
      budget is not None and re.search(r"^\s*count\s*=\s*var\.create_budget \? 1 : 0\s*$", budget.group(1), re.M) is not None)
check("a moved block keeps the home region's existing budget in place (no destroy and create)",
      re.search(r"moved \{\s*from = aws_budgets_budget\.fleet\s*to\s*= aws_budgets_budget\.fleet\[0\]\s*\}", TF) is not None)
applies = [ln for ln in ROS.splitlines() if "chdir=infra/terraform/aws/network apply" in ln]
check("the run-of-show's new-region applies exist", len(applies) >= 2, str(applies))
check("every one of them turns the budget off", all("-var create_budget=false" in ln for ln in applies), str(applies))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The fleet budget is created once per account.")
