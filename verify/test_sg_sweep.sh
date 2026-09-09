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

echo "== it is wired into the teardown, not just defined =="
check "down_one calls sweep_orphan_sgs" \
      "grep -q 'sweep_orphan_sgs \"\${name}\"' '${FLEET}'"
check "audit-zero reports leftover k8s groups" \
      "grep -q 'zero:\${acct}:sg' '${FLEET}'"

echo
if [ "${fail}" -gt 0 ]; then echo "FAILED: ${fail} check(s), ${pass} passed"; exit 1; fi
echo "All security-group sweep checks passed (${pass})."
