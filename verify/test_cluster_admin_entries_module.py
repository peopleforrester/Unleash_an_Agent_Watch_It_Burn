# ABOUTME: Tools-tier gate for #884: the pinned terraform-aws-eks module keys access entries the way the root's moved
# ABOUTME: blocks and fleet.sh's imports assume, and the root's locals name nwuser everywhere and hecaton-run in accen-dev.
# SUITE: e2e (needs terraform on PATH, or TERRAFORM, and network to registry.terraform.io)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Why this is not the offline test. verify/test_cluster_admin_entries.sh reads the root's text. Whether that text
does what it says hangs on two things it cannot see: how the module turns access_entries into state addresses (the
moved blocks name `this["cluster_creator"]` and `this["cluster_creator_admin"]`, fleet.sh imports
`this["hecaton_run"]` and `this["hecaton_run_admin"]`), and what the locals evaluate to for a given account. This
test fetches the module the root pins (a fresh `terraform init` of a copy), validates the root against it, reads the
module's source for the keying, and then plans the root's own locals block, cut from main.tf, against a local STS
endpoint (verify/iam_plan_render.py's) for an account outside the run-role list and for one inside it.

What it does not prove: that an apply on watch-it-burn-community or watch-it-burn-private moves nwuser's entry and
adopts the role's. That needs the operator machine, where the clusters' states are (decisions.md, #884)."""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import iam_plan_render as ipr  # noqa: E402

INIT_TIMEOUT = 600
PINNED_MINOR = "21.29."
ADMIN = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
CLUSTER_DIR = ipr.CLUSTER
LOCALS_ANCHOR = "locals {\n  account_id "
ACCOUNTS_LITERAL = 'run_role_accounts = ["515966504359"]'

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def done() -> None:
    if failures:
        print(f"\n{len(failures)} FAILED", file=sys.stderr)
        sys.exit(1)


def locals_block(text: str) -> str:
    """main.tf's admin locals block, from its `locals {` to the matching `}`; exits naming a missing anchor."""
    start = text.find(LOCALS_ANCHOR)
    if start < 0:
        print(f"FAIL: anchor missing: {LOCALS_ANCHOR!r} is not in {CLUSTER_DIR / 'main.tf'}", file=sys.stderr)
        sys.exit(1)
    depth, i = 0, text.index("{", start)
    while i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return text[start:i + 1]
        i += 1
    print(f"FAIL: the locals block at {LOCALS_ANCHOR!r} never closes", file=sys.stderr)
    sys.exit(1)


exe = os.environ.get("TERRAFORM") or shutil.which("terraform")
if not exe:
    print("FAIL: terraform is not on PATH (or set TERRAFORM); VERSIONS.lock pins v1.15.6", file=sys.stderr)
    sys.exit(1)

main_tf = (CLUSTER_DIR / "main.tf").read_text(encoding="utf-8")
admins = locals_block(main_tf)
if ACCOUNTS_LITERAL not in admins:
    print(f"FAIL: anchor missing: {ACCOUNTS_LITERAL!r} is not in the admin locals of {CLUSTER_DIR / 'main.tf'}",
          file=sys.stderr)
    sys.exit(1)

env = {**os.environ, "TF_IN_AUTOMATION": "1", "CHECKPOINT_DISABLE": "1"}
env.pop("TF_DATA_DIR", None)
env["TF_PLUGIN_CACHE_DIR"] = os.environ.get("TF_PLUGIN_CACHE_DIR") or ipr._plugin_cache()


def tf(work: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([exe, *args], cwd=work, env=env, capture_output=True, text=True, timeout=INIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"FAIL: terraform {args[0]} did not finish within {INIT_TIMEOUT}s (a download stalled)", file=sys.stderr)
        sys.exit(1)


with tempfile.TemporaryDirectory(prefix="tf-cluster-admins-") as tmp:
    work = pathlib.Path(tmp)
    for f in list(CLUSTER_DIR.glob("*.tf")) + [CLUSTER_DIR / ".terraform.lock.hcl"]:
        shutil.copy2(f, work / f.name)

    print("== the root initialises and validates against the pinned module, moved blocks included ==")
    r = tf(work, "init", "-lockfile=readonly", "-backend=false", "-input=false", "-no-color")
    check("terraform init of a copy of the cluster root succeeds", r.returncode == 0, (r.stdout + r.stderr)[-2000:])
    done()
    v = tf(work, "validate", "-no-color")
    check("terraform validate accepts the root", v.returncode == 0, (v.stdout + v.stderr)[-2000:])
    mods = json.loads((work / ".terraform/modules/modules.json").read_text(encoding="utf-8"))["Modules"]
    eks = next((m for m in mods if m["Key"] == "eks"), None)
    check("module eks resolved", eks is not None, f"modules: {[m['Key'] for m in mods]}")
    done()
    check(f"module eks is the pinned {PINNED_MINOR}x", str(eks.get("Version", "")).startswith(PINNED_MINOR),
          f"resolved {eks.get('Version')}")
    mod_main = (work / eks["Dir"] / "main.tf").read_text(encoding="utf-8")

    print("== the module keys access entries the way the moved blocks and fleet.sh's imports assume ==")
    boot = re.search(r"bootstrap_cluster_creator_admin_permissions = \{ for k, v in \{\s*cluster_creator = \{(.*?)"
                     r"\} : k => v if var\.enable_cluster_creator_admin_permissions \}", mod_main, re.DOTALL)
    check("the creator's entry was keyed cluster_creator, and only exists while the flag is on", boot is not None)
    check("its one policy association was keyed admin (state address cluster_creator_admin)",
          boot is not None and re.search(r"policy_associations = \{\s*admin = \{", boot.group(1)) is not None)
    check("the root's access_entries are merged in by their own keys",
          re.search(r"merged_access_entries = merge\(\s*local\.bootstrap_cluster_creator_admin_permissions,\s*"
                    r"var\.access_entries,\s*\)", mod_main) is not None)
    check('aws_eks_access_entry.this is keyed by the entry key',
          re.search(r'resource "aws_eks_access_entry" "this" \{\s*for_each = \{ for k, v in local\.merged_access_entries'
                    r" : k => v if local\.create \}", mod_main) is not None)
    check('aws_eks_access_policy_association.this is keyed "<entry>_<policy>"',
          re.search(r'resource "aws_eks_access_policy_association" "this" \{\s*for_each = \{ for k, v in '
                    r'local\.flattened_access_entries : "\$\{v\.entry_key\}_\$\{v\.pol_key\}" => v', mod_main) is not None)
    check("the KMS key's administrators are the root's list when it gives one, the caller only when it does not",
          re.search(r"key_administrators\s*=\s*coalescelist\(var\.kms_key_administrators,", mod_main) is not None)

print("== the root's locals name the admins per account ==")
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ipr._Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()


def render(block: str) -> dict:
    """Plan main.tf's admin locals on their own, as account ipr.ACCOUNT, and return the outputs."""
    scratch = ('provider "aws" {\n  region  = var.region\n  profile = var.profile\n}\n'
               'variable "region" {\n  default = "us-west-2"\n}\nvariable "profile" {\n  default = "render"\n}\n'
               'variable "operator_user" {\n  default = "nwuser"\n}\n'
               'data "aws_caller_identity" "current" {}\n'
               f"{block}\n"
               'output "entries" {\n  value = local.cluster_admin_entries\n}\n'
               'output "operator_arn" {\n  value = local.operator_arn\n}\n')
    with tempfile.TemporaryDirectory(prefix="tf-cluster-admins-locals-") as tmp:
        work = pathlib.Path(tmp)
        (work / "main.tf").write_text(ipr._point_at(scratch, server.server_address[1]), encoding="utf-8")
        r = tf(work, "init", "-input=false", "-no-color")
        if r.returncode:
            print(f"FAIL: terraform init of the locals scratch failed:\n{r.stderr or r.stdout}", file=sys.stderr)
            sys.exit(1)
        r = tf(work, "plan", "-input=false", "-no-color", "-refresh=false", "-out=p.tfplan")
        if r.returncode:
            print(f"FAIL: terraform plan of the locals scratch failed:\n{r.stderr or r.stdout}", file=sys.stderr)
            sys.exit(1)
        r = tf(work, "show", "-json", "p.tfplan")
        return {k: v["value"] for k, v in json.loads(r.stdout)["planned_values"]["outputs"].items()}


def is_admin(entry: dict, principal: str) -> bool:
    return (entry.get("principal_arn") == principal and entry.get("type") == "STANDARD"
            and entry.get("policy_associations") == {"admin": {"policy_arn": ADMIN, "access_scope": {"type": "cluster"}}})


try:
    acct = ipr.ACCOUNT
    nwuser = f"arn:aws:iam::{acct}:user/nwuser"
    role = f"arn:aws:iam::{acct}:role/hecaton-run"
    out = render(admins)
    check(f"an account outside the run-role list ({acct}) gets the operator's entry only",
          sorted(out["entries"]) == ["operator"], f"entries: {sorted(out['entries'])}")
    check("that entry is nwuser in the plan's own account, cluster admin at cluster scope",
          is_admin(out["entries"].get("operator", {}), nwuser), json.dumps(out["entries"]))
    check("the KMS key's administrator is the same user", out["operator_arn"] == nwuser, out["operator_arn"])
    out = render(admins.replace(ACCOUNTS_LITERAL, f'run_role_accounts = ["515966504359", "{acct}"]'))
    check("an account in the list gets the operator and the hecaton-run role",
          sorted(out["entries"]) == ["hecaton_run", "operator"], f"entries: {sorted(out['entries'])}")
    check("the role's entry is cluster admin at cluster scope, in that account",
          is_admin(out["entries"].get("hecaton_run", {}), role), json.dumps(out["entries"]))
    check("the operator's entry is unchanged by the role's", is_admin(out["entries"].get("operator", {}), nwuser))
finally:
    server.shutdown()

done()
print("\nALL CLUSTER ADMIN ENTRY MODULE CHECKS GREEN")
