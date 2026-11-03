# ABOUTME: Render/wiring gate for #113: the community cluster leaks node IMDS creds on purpose, every other
# ABOUTME: cluster keeps it out of reach, and the facilitator beat steals them read-only and names the account.
"""The IMDS credential-theft challenge (#113), pinned where it is written down.

Michael chose "make a cluster genuinely vulnerable" (question 843, 2026-10-26). The vulnerability is a single
per-cluster knob: the node IMDSv2 PUT-response hop limit. At the default 1 a pod's packet to 169.254.169.254
dies one hop short of node IMDS, so a compromised pod cannot steal the node instance-role credentials. The
community (burn) cluster alone runs it at 2 and ships no agent-deny-imds ClusterNetworkPolicy, so there the
theft lands and the stolen key is proven to be a node role in a real AWS account (ASI03). This test proves
that wiring is coherent across the terraform, fleet.sh and the burn profile, and that the facilitator
demonstration is read-only and actually performs the theft it narrates. The pivot is shown by reading the
node instance-identity document, not by calling the aws CLI, which the minimal tool-pod image does not carry
(#748): an aws call would only print "aws: not found" on stage.

What it does NOT prove, and where that is proven: that a real community node answers IMDS at hop limit 2 and
a real attendee node does not is the live half named in challenges/imds-node-creds/FACILITATOR.md (owed on a
cluster build); that admin and attendee clusters keep the hop limit of 1 and the deny policy is also
verify/test_agent_cloud_credential.py; that the role functions map community->2 and everything else->1 is
verify/test_cluster_roles.sh.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
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
helper = re.search(r"imds_hop_limit_for_role\(\)\s*\{(.*?)\n\}", FLEET, re.DOTALL)
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
check("it proves the pivot by reading the node instance-identity document with the stolen token (#748)",
      "instance-identity/document" in STEAL and "accountId" in STEAL)
check("it names the AWS account the stolen node role lives in, so the cloud-account reach is on screen",
      "account ${ACCT}" in STEAL)
check("it reports BLOCKED when the node refuses, so it is safe to run on a guarded cluster too",
      "BLOCKED" in STEAL)
# Read-only, and no aws CLI: the tool-pod image has none, so any aws call would print "aws: not found"
# on stage (#748). IMDS is only ever GET/PUT-token (never a write), and the pivot is shown without aws.
# Scan only executable lines; comments naming `aws ...` as the thing we deliberately avoid do not count.
STEAL_CODE = "\n".join(ln for ln in STEAL.splitlines() if not ln.lstrip().startswith("#"))
aws_calls = set(re.findall(r"\baws\s+([a-z0-9-]+)\s+([a-z0-9-]+)", STEAL_CODE))
check("the steal script invokes no aws CLI at all (nothing to print 'aws: not found'; nothing changed)",
      aws_calls == set())
check("it does not steal or touch the Pod Identity endpoint 169.254.170.23", "169.254.170.23/" not in STEAL)

print("== the presenter narrative tells the pivot the script actually shows (#837) ==")
# #748 dropped `aws sts get-caller-identity` from the script; the stage copy that names the script must not
# still promise it. The runbook is exempt: it names the call only to say the script does not make it.
NARRATIVE = ("facilitation/kubecon-na-2026-run-of-show.md", "docs/RUN-OF-SHOW-2026-08.md",
             "gitops/ai-layer/web/kubecon.html", "gitops/ai-layer/web/brief.html")
for rel in NARRATIVE:
    text = (REPO / rel).read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", text)
    check(f"{rel} names the steal script (the anchor this check reads)", "steal-node-creds.sh" in text)
    check(f"{rel} names the instance-identity document pivot", "instance-identity document" in flat)
EXEMPT = {"challenges/imds-node-creds/FACILITATOR.md", "challenges/imds-node-creds/steal-node-creds.sh",
          "verify/test_imds_credential_theft.py", "decisions.md"}
tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True,
                         text=True).stdout.split("\0")
stale = []
for rel in tracked:
    if not rel or rel in EXEMPT:
        continue
    path = REPO / rel
    if not path.is_file():
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    if "steal-node-creds.sh" in text and "get-caller-identity" in text:
        stale.append(rel)
check(f"no file that names the steal script still says it runs get-caller-identity (found: {stale})",
      stale == [])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ALL IMDS CREDENTIAL-THEFT CHECKS PASSED")
