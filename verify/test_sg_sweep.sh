#!/usr/bin/env bash
# ABOUTME: Behavioural test for sweep_orphan_sgs: the orphaned load-balancer-controller security groups that
# ABOUTME: cost nothing, carry no tags, and silently block the lab VPC from ever being deleted.
#
# Why this exists. After the Portland teardown every account passed audit-zero while holding 105 non-default
# security groups in its lab VPC, and the lab VPC then refused to delete. The groups are created by the AWS
# Load Balancer Controller, so terraform never owned them, and unlike the leaked load balancers and volumes
# they carry NO TAGS AT ALL (verified against the live leftovers, 105 of 105). A sweep copied from the
# tag-filtered volume sweep would therefore match nothing and report a clean run. This test pins the two
# things that make it actually work: the name derivation, and the revoke-before-delete ordering.
#
# Usage: verify/test_sg_sweep.sh      (offline; aws is a shim)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .sg-sweep-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $*" >>"${CALLS}"
case "$*" in
  *describe-security-groups*group-name*) echo -e "sg-aaa\tsg-bbb" ;;
  *describe-security-groups*IpPermissionsEgress*) echo '[{"IpProtocol":"-1"}]' ;;
  *describe-security-groups*IpPermissions*)      echo '[{"IpProtocol":"tcp"}]' ;;
  *delete-security-group*) exit 0 ;;
  *) : ;;
esac
S
chmod +x "${SHIM}/aws"
export CALLS PATH="${SHIM}:${PATH}"

# Source fleet.sh without running it.
WIB_SOURCE_ONLY=1 source "${FLEET}" >/dev/null 2>&1 || true
if ! declare -F sweep_orphan_sgs >/dev/null; then
    echo "  FAIL  sweep_orphan_sgs is not defined in fleet.sh"; exit 1
fi
log() { :; }; record_fail() { echo "RECORD_FAIL $*" >>"${CALLS}"; }
WIB_REGION="${WIB_REGION:-us-west-2}"

sweep_orphan_sgs "watch-it-burn-attendee-010" "acct-x" >/dev/null 2>&1

echo "== the name filter matches what the controller actually creates =="
# The live groups were named k8s-traffic-watchitburnattendee010-7ad7b645a: dashes stripped, no tags.
check "the cluster name is squashed (dashes removed) into the filter" \
      "grep -q 'k8s-traffic-watchitburnattendee010-\*' '${CALLS}'"
check "it does NOT filter on a kubernetes.io/cluster tag (the groups carry none)" \
      "! grep -q 'tag:kubernetes.io/cluster' '${CALLS}'"
check "it excludes the VPC's own default group" \
      "grep -q 'GroupName!=\`default\`' '${CALLS}'"

echo "== rules are revoked before deletion, or referenced groups refuse to go =="
rev_i=$(grep -n 'revoke-security-group-ingress' "${CALLS}" | head -1 | cut -d: -f1)
rev_e=$(grep -n 'revoke-security-group-egress'  "${CALLS}" | head -1 | cut -d: -f1)
del=$(grep -n 'delete-security-group' "${CALLS}" | head -1 | cut -d: -f1)
check "ingress rules are revoked"            "[ -n '${rev_i}' ]"
check "egress rules are revoked"             "[ -n '${rev_e}' ]"
check "revoke happens BEFORE the first delete" "[ -n '${del}' ] && [ '${rev_i}' -lt '${del}' ] && [ '${rev_e}' -lt '${del}' ]"
check "every discovered group is deleted"    "[ \$(grep -c 'delete-security-group' '${CALLS}') -ge 2 ]"

echo "== the filter covers service- and ingress-named groups, not just per-cluster ones =="
# The first version filtered on k8s-traffic-<squashed cluster>-* only. k8s-agent-console-43c584a1f2 and
# k8s-watchitburningres-11bfcbd899 do not carry the cluster name, survived that sweep, and then blocked
# the lab VPC from deleting. Scoping by vpc-id is what makes the wide k8s-* filter safe: this account
# also holds a packt-lab-vpc that is not ours.
check "the sweep scopes by vpc-id" \
      "grep -q 'Name=vpc-id,Values=' '${FLEET}'"
check "and matches every k8s-* group in that VPC" \
      "grep -q 'Name=group-name,Values=k8s-\*' '${FLEET}'"
check "the lab VPC id is resolved from state" \
      "grep -q '^read_vpc_id_for()' '${FLEET}'"

echo "== it is wired into the teardown, not just defined =="
check "down_one calls sweep_orphan_sgs" \
      "grep -q 'sweep_orphan_sgs \"\${name}\"' '${FLEET}'"
check "audit-zero reports leftover k8s groups" \
      "grep -q 'zero:\${acct}:sg' '${FLEET}'"

echo "== a parallel teardown's leak reports are re-checked once every destroy is done =="
# 2026-10-31, the #643 standbys: five us-east-2 clusters in one lab VPC were destroyed at once. Each sweep is
# VPC-wide, so each one met its siblings' groups while those clusters were still going, failed to delete them, and
# recorded sg-leak; afterwards the VPC held nothing but its own Bedrock endpoint group.
check "fleet.sh defines recheck_sg_leaks" "declare -F recheck_sg_leaks >/dev/null"
mkdir -p "$(dirname "${FAIL_FILE}")"   # fleet.sh's own, read-only path
printf 'sg-leak:watch-it-burn-community-b01\nsg-leak:watch-it-burn-private-b01\nother-cluster\n' >"${FAIL_FILE}"
record_fail() { echo "${1}" >>"${FAIL_FILE}"; }
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $*" >>"${CALLS}"
case "$*" in *describe-security-groups*group-name*) echo "None" ;; *) : ;; esac
S
read_vpc_id_for() { echo vpc-123; }
recheck_sg_leaks >/dev/null 2>&1
check "with the groups gone, both sg-leak reports are dropped" "! grep -q '^sg-leak:' '${FAIL_FILE}'"
check "and every other failure is kept" "grep -qx 'other-cluster' '${FAIL_FILE}'"
printf 'sg-leak:watch-it-burn-community-b01\n' >"${FAIL_FILE}"
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $*" >>"${CALLS}"
case "$*" in
  *describe-security-groups*group-name*) echo "sg-stuck" ;;
  *describe-security-groups*) echo '[]' ;;
  *delete-security-group*) exit 1 ;;
  *) : ;;
esac
S
recheck_sg_leaks >/dev/null 2>&1
check "a group that still will not delete keeps its sg-leak report" "grep -qx 'sg-leak:watch-it-burn-community-b01' '${FAIL_FILE}'"
rm -f "${FAIL_FILE}"
check "_instructors_down and the cluster down both re-check before reporting" \
      "[ \$(grep -c 'recheck_sg_leaks$' '${FLEET}') -ge 2 ]"

echo
if [ "${fail}" -gt 0 ]; then echo "FAILED: ${fail} check(s), ${pass} passed"; exit 1; fi
echo "All security-group sweep checks passed (${pass})."
