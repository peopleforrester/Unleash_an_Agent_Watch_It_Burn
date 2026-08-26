#!/usr/bin/env bash
# ABOUTME: Pre-provision gate. Proves each account is reachable, is the account we think it is, and has
# ABOUTME: quota headroom for the run about to start, BEFORE any money is committed. Read-only.
#
# Why this exists as a script rather than a checklist. The quota numbers and the account list already
# existed, as prose in docs/ and infra/SIZING.md, where a human ticks them off on the morning. Prose
# gets skimmed. The two failures it is meant to stop are both unrecoverable-ish and both silent at the
# moment they happen:
#
#   1. A profile pointing at the wrong account. accen-dev is SHARED with the co-tenant Packt project,
#      so a mis-resolved profile provisions into an account whose teardown will never look for those
#      clusters. Checking that the profile RESOLVES is not enough; it has to resolve to the expected
#      12-digit account id, which is why they are pinned below rather than discovered.
#
#   2. A quota rejection discovered mid-build. Quotas are per-account and per-region, and a run that
#      fits at 1 cluster is rejected at 50. Finding out 40 minutes in, after the control planes exist,
#      costs the build window and leaves a half fleet to reconcile.
#
# Everything here is a read: sts, service-quotas, and a file existence test. It never mutates.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly LAB_VPC_DIR="${SCRIPT_DIR}/../aws/network"
WIB_REGION="${WIB_REGION:-us-west-2}"
WIB_ATTENDEE_ACCOUNTS="${WIB_ATTENDEE_ACCOUNTS:-accen-dev,aws1-student31,aws1-student32,aws1-student33,aws1-student34}"
WIB_DEFAULT_ACCOUNT="${WIB_DEFAULT_ACCOUNT:-accen-dev}"

# The pinned profile -> account-id map. Verified 2026-08-26 against sts get-caller-identity.
# A profile that resolves to anything else is a hard failure, not a warning: it is the one condition
# where continuing does damage that teardown cannot find.
declare -A EXPECTED_ACCOUNT=(
    [accen-dev]=515966504359
    [aws1-student31]=948731545609
    [aws1-student32]=891472436879
    [aws1-student33]=250699659274
    [aws1-student34]=783241407859
)

# Per-cluster resource cost, used to scale the quota checks by the run size.
readonly VCPU_PER_CLUSTER=8       # one t3.2xlarge node
readonly NLB_PER_CLUSTER=1        # the console Service; party Ingresses share an ALB when present
readonly EKS_PER_CLUSTER=1

# Service Quotas codes. Names are not stable across regions; codes are.
readonly Q_VCPU="L-1216C47A"      # Running On-Demand Standard (A,C,D,H,I,M,R,T,Z) instances, in vCPUs
readonly Q_NLB="L-69A177A2"       # Network Load Balancers per Region
readonly Q_EKS="L-1194D53C"       # Clusters per Region
readonly Q_VPC="L-F678F1CE"       # VPCs per Region
readonly Q_EIP="L-0263D0A3"       # EC2-VPC Elastic IPs
readonly Q_CLB="L-E9E9831D"       # Classic Load Balancers per Region (reported, not fatal)

fail=0
log() { printf '%s\n' "$*" >&2; }
ok()   { printf '  PASS  %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; fail=1; }
note() { printf '  note  %s\n' "$*"; }

usage() {
    cat >&2 <<EOF
Usage: ${0##*/} <clusters-per-account>

Read-only preflight for a fleet run. Verifies, per account:
  * the profile resolves to the EXPECTED account id (hard failure on mismatch)
  * vCPU / NLB / EKS / VPC / EIP quota headroom for <clusters-per-account>
  * a lab VPC state exists (or is the default account's default state)
and, once, that the local tooling is present.

Exits non-zero if anything would block the run. Mutates nothing.
EOF
    exit 2
}

per_account="${1:-}"
[[ "${per_account}" =~ ^[0-9]+$ && "${per_account}" -gt 0 ]] || usage

# quota_at_least <profile> <code> <needed> <label>
# Reports the applied quota against what this run needs. A quota the API cannot report is called out
# rather than assumed: an unreadable quota is not a passing quota, and treating it as one is how a
# check passes for the wrong reason.
quota_at_least() {
    local profile="$1" code="$2" needed="$3" label="$4" value
    value="$(AWS_PROFILE="${profile}" aws service-quotas get-service-quota \
        --service-code "${5:-ec2}" --quota-code "${code}" --region "${WIB_REGION}" \
        --query 'Quota.Value' --output text 2>/dev/null || true)"
    if [[ -z "${value}" || "${value}" == "None" ]]; then
        # Fall back to the AWS default for the quota when no override has been requested.
        value="$(AWS_PROFILE="${profile}" aws service-quotas get-aws-default-service-quota \
            --service-code "${5:-ec2}" --quota-code "${code}" --region "${WIB_REGION}" \
            --query 'Quota.Value' --output text 2>/dev/null || true)"
    fi
    if [[ -z "${value}" || "${value}" == "None" ]]; then
        bad "${label}: quota ${code} could not be read (needs ${needed}) — verify by hand before running"
        return
    fi
    local have; have="${value%.*}"
    if (( have >= needed )); then
        ok "${label}: ${have} available, need ${needed}"
    else
        bad "${label}: ${have} available, need ${needed} — request an increase before this run"
    fi
}

echo "== tooling =="
for t in terraform kubectl aws jq curl helm; do
    if command -v "${t}" >/dev/null 2>&1; then ok "${t} present"; else bad "${t} NOT found"; fi
done

IFS=',' read -ra accounts <<<"${WIB_ATTENDEE_ACCOUNTS}"
for acct in "${accounts[@]}"; do
    acct="${acct// /}"; [[ -n "${acct}" ]] || continue
    echo
    echo "== ${acct} (${per_account} cluster(s)) =="

    actual="$(AWS_PROFILE="${acct}" aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
    expected="${EXPECTED_ACCOUNT[${acct}]:-}"
    if [[ -z "${actual}" ]]; then
        bad "identity: profile '${acct}' does not resolve (credentials missing or expired)"
        continue
    elif [[ -z "${expected}" ]]; then
        note "identity: resolves to ${actual}; no pinned id for '${acct}' — add one to EXPECTED_ACCOUNT"
    elif [[ "${actual}" != "${expected}" ]]; then
        bad "identity: '${acct}' resolves to ${actual}, EXPECTED ${expected} — REFUSING, this would provision into the wrong account"
        continue
    else
        ok "identity: ${actual}"
    fi

    quota_at_least "${acct}" "${Q_VCPU}" "$(( per_account * VCPU_PER_CLUSTER ))" "vCPU"
    quota_at_least "${acct}" "${Q_NLB}"  "$(( per_account * NLB_PER_CLUSTER ))"  "NLB per region" elasticloadbalancing
    quota_at_least "${acct}" "${Q_EKS}"  "$(( per_account * EKS_PER_CLUSTER ))"  "EKS clusters" eks
    # Service codes differ and are not guessable: VPCs are under 'vpc', Elastic IPs under 'ec2'.
    # Verified live 2026-08-26; querying either under the other returns empty, which this script
    # reports as unreadable rather than passing.
    quota_at_least "${acct}" "${Q_VPC}"  1                                       "VPCs" vpc
    quota_at_least "${acct}" "${Q_EIP}"  1                                       "Elastic IPs" ec2

    # Classic LB is informational: nothing should create one, but if the console Service annotations
    # ever regress to the in-tree provider it silently will, and the low Classic quota is then the
    # first symptom. Reporting it makes that legible instead of mysterious.
    clb="$(AWS_PROFILE="${acct}" aws service-quotas get-service-quota --service-code elasticloadbalancing \
        --quota-code "${Q_CLB}" --region "${WIB_REGION}" --query 'Quota.Value' --output text 2>/dev/null || true)"
    [[ -n "${clb}" && "${clb}" != "None" ]] && note "Classic LB quota ${clb%.*} (nothing should create one; a rise here means the NLB annotations regressed)"

    if [[ -f "${LAB_VPC_DIR}/states/${acct}.tfstate" ]]; then
        ok "lab VPC state present"
    elif [[ "${acct}" == "${WIB_DEFAULT_ACCOUNT}" && -f "${LAB_VPC_DIR}/terraform.tfstate" ]]; then
        ok "lab VPC state present (default state)"
    else
        bad "no lab VPC state — apply it first: terraform -chdir=${LAB_VPC_DIR} apply -state=states/${acct}.tfstate -var profile=${acct} -var region=${WIB_REGION}"
    fi
done

echo
if [[ "${fail}" -eq 0 ]]; then
    echo "PREFLIGHT GREEN: ${#accounts[@]} account(s) ready for ${per_account} cluster(s) each."
    exit 0
fi
echo "PREFLIGHT FAILED — resolve the items above before provisioning." >&2
exit 1
