# ABOUTME: Render/wiring gate for #113: the community cluster leaks node IMDS creds on purpose, every other
# ABOUTME: cluster keeps it out of reach, and the facilitator beat steals them read-only via sts get-caller-identity.
"""The IMDS credential-theft challenge (#113), pinned where it is written down.

Michael chose "make a cluster genuinely vulnerable" (question 843, 2026-10-26). The vulnerability is a single
per-cluster knob: the node IMDSv2 PUT-response hop limit. At the default 1 a pod's packet to 169.254.169.254
dies one hop short of node IMDS, so a compromised pod cannot steal the node instance-role credentials. The
community (burn) cluster alone runs it at 2 and ships no agent-deny-imds ClusterNetworkPolicy, so there the
theft lands and `aws sts get-caller-identity` returns a node role (ASI03). This test proves that wiring is
coherent across the terraform, fleet.sh and the burn profile, and that the facilitator demonstration is
read-only and actually performs the theft it narrates.

What it does NOT prove, and where that is proven: that a real community node answers IMDS at hop limit 2 and
a real attendee node does not is the live half named in challenges/imds-node-creds/FACILITATOR.md (owed on a
cluster build); that admin and attendee clusters keep the hop limit of 1 and the deny policy is also
verify/test_agent_cloud_credential.py; that the role functions map community->2 and everything else->1 is
verify/test_cluster_roles.sh.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
TF = (REPO / "infra/terraform/aws/cluster/main.tf").read_text(encoding="utf-8")
FLEET = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
BURN = (REPO / "gitops/bootstrap/values-burn.yaml")
BEAT_DIR = REPO / "challenges/imds-node-creds"
FAC = (BEAT_DIR / "FACILITATOR.md").read_text(encoding="utf-8")
STEAL = (BEAT_DIR / "steal-node-creds.sh").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the node hop limit is a per-cluster variable, default 1 (the control) ==")
check("the node group reads var.imds_hop_limit, not a literal",
      re.search(r"http_put_response_hop_limit\s*=\s*var\.imds_hop_limit\b", TF) is not None)
m = re.search(r'variable "imds_hop_limit"\s*\{[^}]*type\s*=\s*number[^}]*default\s*=\s*(\d+)', TF)
check("var.imds_hop_limit is a number defaulting to 1", bool(m) and int(m.group(1)) == 1)

print("== fleet.sh raises it to 2 for the community cluster alone ==")
# The helper is the single source of truth; test_cluster_roles.sh exercises it against a sourced fleet.sh.
helper = re.search(r"imds_hop_limit_for_role\(\)\s*\{(.*?)\n\}", FLEET, re.S)
check("imds_hop_limit_for_role exists", helper is not None)
body = helper.group(1) if helper else ""
check("community gets 2", re.search(r"community\)\s*printf '2'", body) is not None)
check("every other role (admin, attendee) falls through to 1",
      re.search(r"\*\)\s*printf '1'", body) is not None and "admin)" not in body)
check("up_one passes -var imds_hop_limit to terraform",
      re.search(r'-var\s+"imds_hop_limit=\$\{hop\}"', FLEET) is not None
      and re.search(r'hop="\$\(imds_hop_limit_for_role', FLEET) is not None)
check("the dry-run plan shows the hop limit, so a plan reveals which clusters are vulnerable",
      "-var imds_hop_limit=${hop}" in FLEET)

print("== the burn profile leaves both IMDS controls off, and says so ==")
burn = yaml.safe_load(BURN.read_text(encoding="utf-8")) or {}
check("the burn profile ships no agent-deny-imds ClusterNetworkPolicy app",
      "cluster-network-policies" not in (burn.get("apps") or []))
btext = BURN.read_text(encoding="utf-8")
check("the burn values file names the deliberate hop-limit-2 leak (not the stale 'hop limit of 1' claim)",
      "imds_hop_limit=2" in btext and "hop limit of 1 still keeps pods off" not in btext)

print("== the facilitator demonstration: real theft, read-only, context-safe ==")
check("there is a FACILITATOR.md for the beat", bool(FAC.strip()))
check("it is pegged to ASI03", "ASI03" in FAC)
check("it names the community/attackme cluster as the only place it lands", "attackme" in FAC and "community" in FAC)
check("it is marked not-an-attendee-step (the student clusters block it)", "not" in FAC and "attendee step" in FAC)
check("it names the owed live check", "Not yet run on a cluster" in FAC)

check("the steal script requires CONTEXT with no current-context fallback",
      re.search(r': "\$\{CONTEXT:\?', STEAL) is not None)
check("every kubectl in the steal script carries --context \"$CONTEXT\"",
      bool(re.findall(r"kubectl ", STEAL)) and
      all('--context "$CONTEXT"' in ln for ln in STEAL.splitlines() if re.search(r"\bkubectl ", ln)))
check("it targets node IMDS at 169.254.169.254", "169.254.169.254" in STEAL)
check("it requests an IMDSv2 token (PUT), which the hop limit is what blocks",
      "-X PUT" in STEAL and "x-aws-ec2-metadata-token-ttl-seconds" in STEAL.lower())
check("it reads the node instance-role credentials path",
      "iam/security-credentials/" in STEAL)
check("it proves the pivot with sts get-caller-identity using the stolen creds",
      "sts get-caller-identity" in STEAL and "AWS_SESSION_TOKEN=" in STEAL)
check("it reports BLOCKED when the node refuses, so it is safe to run on a guarded cluster too",
      "BLOCKED" in STEAL)
# Read-only: the only AWS call is the identity lookup, and IMDS is only ever GET/PUT-token (never a write).
aws_calls = set(re.findall(r"\baws\s+([a-z0-9-]+)\s+([a-z0-9-]+)", STEAL))
check("no aws call other than sts get-caller-identity (nothing is created or changed)",
      aws_calls == {("sts", "get-caller-identity")})
check("it does not steal or touch the Pod Identity endpoint 169.254.170.23", "169.254.170.23/" not in STEAL)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ALL IMDS CREDENTIAL-THEFT CHECKS PASSED")
