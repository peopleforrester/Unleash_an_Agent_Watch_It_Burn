# ABOUTME: Tools-tier gate for #869: the pinned terraform-aws-eks module reads the root's node rules the way the
# ABOUTME: root means them, so 8080 and 3000 open from the security group the control-plane ENIs carry.
# SUITE: e2e (needs terraform on PATH, or TERRAFORM, and network to registry.terraform.io)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
# E2E SERIAL: terraform (run-e2e-tools.sh runs one such test at a time: they share the provider cache, #1005)
"""Why this is not the offline test. Terraform converts a module input to its declared object type and drops any
attribute the type does not name, without an error, so a misspelt `source_cluster_security_group` would plan a
rule with no source at all and `terraform validate` would still pass. This test fetches the module the root pins
(a fresh `terraform init` of a copy, as test_terraform_lock_init.py does), validates the root against it, and then
reads the module's own source: every attribute the root's rules set is in the variable's type, the rule resource
maps source_cluster_security_group to the module's cluster security group, and that group is the one the EKS
cluster's vpc_config attaches to the control-plane ENIs (live: sg-0ca9886f5a9d4f6d3 on watch-it-burn-private,
the group the issue's hand-added rules named).

What it does not prove: that a built cluster answers the probes. That is lab-platform's
TestTheLearnerAppsGroupReachesEveryWorkshopAppLive on a cluster once the change is applied (decisions.md, #869)."""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import node_sg_rules as nsr  # noqa: E402

INIT_TIMEOUT = 600
PINNED_MINOR = "21.29."

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


exe = os.environ.get("TERRAFORM") or shutil.which("terraform")
if not exe:
    print("FAIL: terraform is not on PATH (or set TERRAFORM); VERSIONS.lock pins v1.15.6", file=sys.stderr)
    sys.exit(1)

try:
    root_rules = nsr.rules()
    cluster_rules = nsr.rules(anchor=nsr.CLUSTER_RULES_ANCHOR)
except nsr.AnchorMissing as e:
    print(f"FAIL: anchor missing: {e}", file=sys.stderr)
    sys.exit(1)

env = {**os.environ, "TF_IN_AUTOMATION": "1", "CHECKPOINT_DISABLE": "1"}
env.pop("TF_DATA_DIR", None)
src = nsr.CLUSTER_TF.parent

with tempfile.TemporaryDirectory(prefix="tf-node-rules-") as tmp:
    work = pathlib.Path(tmp)
    for f in list(src.glob("*.tf")) + [src / ".terraform.lock.hcl"]:
        shutil.copy2(f, work / f.name)

    print("== the root initialises and validates against the pinned module ==")
    try:
        r = subprocess.run([exe, "init", "-lockfile=readonly", "-backend=false", "-input=false", "-no-color"],
                           cwd=work, env=env, capture_output=True, text=True, timeout=INIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"FAIL: terraform init did not finish within {INIT_TIMEOUT}s (a download stalled)", file=sys.stderr)
        sys.exit(1)
    check("terraform init of a copy of the cluster root succeeds", r.returncode == 0, (r.stdout + r.stderr)[-2000:])
    if r.returncode != 0:
        print(f"\n{len(failures)} FAILED", file=sys.stderr)
        sys.exit(1)
    v = subprocess.run([exe, "validate", "-no-color"], cwd=work, env=env, capture_output=True, text=True,
                       timeout=INIT_TIMEOUT)
    check("terraform validate accepts the root (each rule has the module's required attributes)",
          v.returncode == 0, (v.stdout + v.stderr)[-2000:])

    mods = json.loads((work / ".terraform/modules/modules.json").read_text(encoding="utf-8"))["Modules"]
    eks = next((m for m in mods if m["Key"] == "eks"), None)
    check("module eks resolved", eks is not None, f"modules: {[m['Key'] for m in mods]}")
    if eks is None:
        print(f"\n{len(failures)} FAILED", file=sys.stderr)
        sys.exit(1)
    check(f"module eks is the pinned {PINNED_MINOR}x", str(eks.get("Version", "")).startswith(PINNED_MINOR),
          f"resolved {eks.get('Version')}")
    mdir = work / eks["Dir"]
    variables = (mdir / "variables.tf").read_text(encoding="utf-8")
    node_groups = (mdir / "node_groups.tf").read_text(encoding="utf-8")
    main = (mdir / "main.tf").read_text(encoding="utf-8")

    print("== the module's variable type names every attribute the root's rules set ==")
    m = re.search(r'variable "node_security_group_additional_rules"\s*\{.*?type\s*=\s*map\(object\(\{(.*?)\}\)\)',
                  variables, re.DOTALL)
    check('variables.tf declares node_security_group_additional_rules as map(object({...}))', m is not None)
    declared = set(re.findall(r"^\s*([a-z_]+)\s*=", m.group(1), re.MULTILINE)) if m else set()
    for name, attrs in root_rules.items():
        unknown = sorted(set(attrs) - declared)
        check(f"{name}: every attribute it sets is in the module's type (none silently dropped)", not unknown,
              f"not in the type: {unknown}; the type has {sorted(declared)}")

    print("== the cluster group's rules (#906, the lab VPC to the API on 443) are read as the root means them ==")
    cm = re.search(r'variable "security_group_additional_rules"\s*\{.*?type\s*=\s*map\(object\(\{(.*?)\}\)\)',
                   variables, re.DOTALL)
    check('variables.tf declares security_group_additional_rules as map(object({...}))', cm is not None)
    cdeclared = set(re.findall(r"^\s*([a-z_]+)\s*=", cm.group(1), re.MULTILINE)) if cm else set()
    for name, attrs in cluster_rules.items():
        unknown = sorted(set(attrs) - cdeclared)
        check(f"{name}: every attribute it sets is in the module's type (none silently dropped)", not unknown,
              f"not in the type: {unknown}; the type has {sorted(cdeclared)}")
    cres = re.search(r'resource "aws_security_group_rule" "cluster"\s*\{(.*?)\n\}', main, re.DOTALL)
    check('main.tf has resource "aws_security_group_rule" "cluster"', cres is not None)
    cbody = cres.group(1) if cres else ""
    check("its for_each reads var.security_group_additional_rules", "var.security_group_additional_rules" in cbody)
    check("it attaches each rule to the module's cluster security group (the one on the control-plane ENIs)",
          re.search(r"security_group_id\s*=\s*aws_security_group\.cluster\[0\]\.id", cbody) is not None)
    check("it passes each rule's cidr_blocks through to the rule",
          re.search(r"^\s*cidr_blocks\s*=\s*try\(each\.value\.cidr_blocks,\s*null\)", cbody, re.MULTILINE) is not None,
          cbody[:1500])

    print("== source_cluster_security_group resolves to the group on the control-plane ENIs ==")
    res = re.search(r'resource "aws_security_group_rule" "node"\s*\{(.*?)\n\}', node_groups, re.DOTALL)
    check('node_groups.tf has resource "aws_security_group_rule" "node"', res is not None)
    body = res.group(1) if res else ""
    check("its for_each merges var.node_security_group_additional_rules", "var.node_security_group_additional_rules" in body)
    check("it attaches each rule to the module's node security group",
          re.search(r"security_group_id\s*=\s*aws_security_group\.node\[0\]\.id", body) is not None)
    check("source_cluster_security_group = true sets the source to local.security_group_id",
          re.search(r"source_security_group_id\s*=\s*try\(each\.value\.source_cluster_security_group,\s*false\)\s*\?"
                    r"\s*local\.security_group_id", body) is not None)
    check("local.security_group_id is the module's cluster security group",
          re.search(r"security_group_id\s*=\s*local\.create_security_group\s*\?\s*aws_security_group\.cluster\[0\]\.id",
                    main) is not None)
    check("the EKS cluster's vpc_config attaches that group to the control plane",
          re.search(r"vpc_config\s*\{[^}]*security_group_ids\s*=\s*compact\(distinct\(concat\(var\.additional_security_group_ids,"
                    r"\s*\[local\.security_group_id\]", main, re.DOTALL) is not None)

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nALL CONTROL-PLANE APP-PORT MODULE CHECKS GREEN")
