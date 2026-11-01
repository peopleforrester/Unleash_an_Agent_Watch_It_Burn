#!/usr/bin/env bash
# ABOUTME: Behavioural test for sweep_orphan_sgs: the orphaned load-balancer-controller security groups that
# ABOUTME: cost nothing and block the lab VPC from being deleted, swept only when tagged for the torn-down cluster.
#
# Why this exists. After the Portland teardown every account passed audit-zero while holding 105 non-default
# security groups in its lab VPC, and the lab VPC then refused to delete. The groups are created by the AWS
# Load Balancer Controller, so terraform never owned them. The sweep then took every k8s-* group in the lab
# VPC, and the lab VPC is shared with the roster clusters: on 2026-11-01 `fleet.sh down
# watch-it-burn-attendee-441` stripped the community and private clusters' agent-console and traffic groups
# (#752). The sweep now selects by the cluster's own tags (#753). This test pins that selection, that a group
# under another cluster's tag or no tag is never touched, and the revoke-before-delete ordering.
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
  # The AWS side of the tag filters: k8s-agent-console-43c584a1f2 (sg-console) and k8s-watchitburningres-11bfcbd899
  # (sg-ingress) carry elbv2.k8s.aws/cluster=watch-it-burn-attendee-010, k8s-elb-a1b2 (sg-legacy) carries
  # kubernetes.io/cluster/watch-it-burn-attendee-010=owned and also the elbv2 tag, so both calls return it.
  # sg-sibling is a roster cluster's k8s-traffic group and sg-untagged a tagless leftover: any other filter
  # (a vpc-wide or name-only k8s-* one) would return them.
  *describe-security-groups*--filters*tag:elbv2.k8s.aws/cluster,Values=watch-it-burn-attendee-010*) echo -e "sg-console\tsg-ingress\tsg-legacy" ;;
  *describe-security-groups*--filters*tag:kubernetes.io/cluster/watch-it-burn-attendee-010,Values=owned*) echo "sg-legacy" ;;
  *describe-security-groups*--filters*tag:*) echo "None" ;;
  *describe-security-groups*--filters*) echo -e "sg-sibling\tsg-untagged" ;;
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

echo "== the sweep selects by the torn-down cluster's tags, not by a k8s-* name =="
read_vpc_id_for() { echo vpc-123; }
sweep_orphan_sgs "watch-it-burn-attendee-010" "acct-x" >/dev/null 2>&1
check "it filters on tag:elbv2.k8s.aws/cluster=<name>" \
      "grep -q 'describe-security-groups.*Name=tag:elbv2.k8s.aws/cluster,Values=watch-it-burn-attendee-010' '${CALLS}'"
check "it filters on tag:kubernetes.io/cluster/<name>=owned" \
      "grep -q 'describe-security-groups.*Name=tag:kubernetes.io/cluster/watch-it-burn-attendee-010,Values=owned' '${CALLS}'"
check "every selecting call is scoped to the lab VPC when the VPC id is known" \
      "[ \$(grep -c 'describe-security-groups.*--filters.*Name=tag:' '${CALLS}') -eq \$(grep -c 'describe-security-groups.*--filters Name=vpc-id,Values=vpc-123 Name=tag:' '${CALLS}') ]"
check "no selecting call filters on a k8s-* group name" \
      "! grep -q 'describe-security-groups.*Name=group-name' '${CALLS}'"
check "every describe-security-groups selection carries a tag filter" \
      "! grep 'describe-security-groups.*--filters' '${CALLS}' | grep -vq 'Name=tag:'"
check "it excludes the VPC's own default group" \
      "grep -q 'GroupName!=\`default\`' '${CALLS}'"
check "the agent-console group tagged for the cluster is deleted" \
      "grep -q 'delete-security-group.*sg-console' '${CALLS}'"
check "the ingress-named group tagged for the cluster is deleted" \
      "grep -q 'delete-security-group.*sg-ingress' '${CALLS}'"
check "a group both tag filters return is deleted once, not reported as a leak" \
      "[ \$(grep -c 'delete-security-group.*sg-legacy' '${CALLS}') -eq 1 ] && ! grep -q RECORD_FAIL '${CALLS}'"
check "a roster cluster's group in the same VPC is never touched" "! grep -q 'sg-sibling' '${CALLS}'"
check "an untagged leftover is not swept per cluster" "! grep -q 'sg-untagged' '${CALLS}'"
: >"${CALLS}"
read_vpc_id_for() { return 1; }
sweep_orphan_sgs "watch-it-burn-attendee-010" "acct-x" >/dev/null 2>&1
check "with no lab VPC id it uses the same tag selection, without vpc-id" \
      "grep -q 'describe-security-groups --region [^ ]* --filters Name=tag:elbv2.k8s.aws/cluster,Values=watch-it-burn-attendee-010' '${CALLS}' && ! grep -q 'Name=vpc-id' '${CALLS}' && ! grep -q 'Name=group-name' '${CALLS}'"
check "and still deletes the cluster's tagged groups" \
      "grep -q 'delete-security-group.*sg-console' '${CALLS}' && ! grep -q 'sg-sibling' '${CALLS}'"
: >"${CALLS}"
read_vpc_id_for() { echo vpc-123; }
sweep_orphan_sgs "watch-it-burn-attendee-010" "acct-x" >/dev/null 2>&1

echo "== rules are revoked before deletion, or referenced groups refuse to go =="
rev_i=$(grep -n 'revoke-security-group-ingress' "${CALLS}" | head -1 | cut -d: -f1)
rev_e=$(grep -n 'revoke-security-group-egress'  "${CALLS}" | head -1 | cut -d: -f1)
del=$(grep -n 'delete-security-group' "${CALLS}" | head -1 | cut -d: -f1)
check "ingress rules are revoked"            "[ -n '${rev_i}' ]"
check "egress rules are revoked"             "[ -n '${rev_e}' ]"
check "revoke happens BEFORE the first delete" "[ -n '${del}' ] && [ '${rev_i}' -lt '${del}' ] && [ '${rev_e}' -lt '${del}' ]"
check "every selected group is deleted"      "[ \$(grep -c 'delete-security-group' '${CALLS}') -eq 3 ]"

echo "== the selection in fleet.sh is the tag-scoped one =="
# The first version filtered on k8s-traffic-<squashed cluster>-* only and missed the service- and ingress-named
# groups; the second took every k8s-* group in the lab VPC and reached the roster clusters' groups (#752).
check "fleet.sh selects on the elbv2.k8s.aws/cluster tag" \
      "grep -q 'Name=tag:elbv2.k8s.aws/cluster,Values=\${name}' '${FLEET}'"
check "fleet.sh selects on the kubernetes.io/cluster/<name> tag" \
      "grep -q 'Name=tag:kubernetes.io/cluster/\${name},Values=owned' '${FLEET}'"
check "the sweep no longer filters on a k8s-* name" \
      "! sed -n '/^sweep_orphan_sgs()/,/^}/p' '${FLEET}' | grep -q 'Name=group-name'"
check "the lab VPC id is resolved from state" \
      "grep -q '^read_vpc_id_for()' '${FLEET}'"

echo "== it is wired into the teardown, not just defined =="
check "down_one calls sweep_orphan_sgs" \
      "grep -q 'sweep_orphan_sgs \"\${name}\"' '${FLEET}'"
check "audit-zero reports leftover k8s groups" \
      "grep -q 'zero:\${acct}:sg' '${FLEET}'"

echo "== a group a live load balancer uses is never touched =="
# 2026-10-31: the us-west-2 standby teardown was stopped before its sweep, because the lab VPC there also holds
# attackme's and burritobot-private's live NLB groups, and the sweep then revoked every k8s-* group's rules before it
# tried the delete. Revoking a live LB's ingress cuts the room off. The tag selection now keeps other clusters' groups
# out; a group on a network interface is in use and stays the second guard.
: >"${CALLS}"
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $*" >>"${CALLS}"
case "$*" in
  *describe-security-groups*--filters*tag:elbv2.k8s.aws/cluster,Values=watch-it-burn-community-b03*) echo -e "sg-live\tsg-orphan" ;;
  *describe-network-interfaces*sg-live*) echo "eni-0abc" ;;
  *describe-network-interfaces*) echo "" ;;
  *describe-security-groups*IpPermissionsEgress*) echo '[{"IpProtocol":"-1"}]' ;;
  *describe-security-groups*IpPermissions*)      echo '[{"IpProtocol":"tcp"}]' ;;
  *delete-security-group*) exit 0 ;;
  *) : ;;
esac
S
read_vpc_id_for() { echo vpc-123; }
sweep_orphan_sgs "watch-it-burn-community-b03" "acct-x" >/dev/null 2>&1
check "it asks which groups are on a network interface" "grep -q 'describe-network-interfaces.*sg-live' '${CALLS}'"
check "a group on an interface has no rule revoked" "! grep -E 'revoke-security-group-(ingress|egress).*sg-live' '${CALLS}' >/dev/null"
check "and is not deleted" "! grep -q 'delete-security-group.*sg-live' '${CALLS}'"
check "an unattached group is still revoked and deleted" \
      "grep -q 'revoke-security-group-ingress.*sg-orphan' '${CALLS}' && grep -q 'delete-security-group.*sg-orphan' '${CALLS}'"

echo "== a parallel teardown's leak reports are re-checked once every destroy is done =="
# 2026-10-31, the #643 standbys: five us-east-2 clusters in one lab VPC were destroyed at once. Each sweep then took
# every k8s-* group in the VPC, met its siblings' groups while those clusters were still going, failed to delete them,
# and recorded sg-leak; afterwards the VPC held nothing but its own Bedrock endpoint group. A cluster's own tagged
# group can still be held by a sibling's cross-reference, so the re-check stays.
check "fleet.sh defines recheck_sg_leaks" "declare -F recheck_sg_leaks >/dev/null"
mkdir -p "$(dirname "${FAIL_FILE}")"   # fleet.sh's own, read-only path
printf 'sg-leak:watch-it-burn-community-b01\nsg-leak:watch-it-burn-private-b01\nother-cluster\n' >"${FAIL_FILE}"
record_fail() { echo "${1}" >>"${FAIL_FILE}"; }
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $*" >>"${CALLS}"
case "$*" in *describe-security-groups*--filters*tag:*) echo "None" ;; *) : ;; esac
S
read_vpc_id_for() { echo vpc-123; }
# fleet.sh runs under set -euo pipefail, so a selection that finds nothing must not fail its own pipeline and end
# the teardown. Run in the background so errexit is not suspended by a conditional around it.
( set -e; sweep_orphan_sgs "watch-it-burn-community-b01" "acct-x"; : >"${T}/empty-ok" ) >/dev/null 2>&1 &
wait $! || true
check "a sweep that finds no tagged group returns cleanly under errexit" "[ -f '${T}/empty-ok' ]"
recheck_sg_leaks >/dev/null 2>&1
check "with the groups gone, both sg-leak reports are dropped" "! grep -q '^sg-leak:' '${FAIL_FILE}'"
check "and every other failure is kept" "grep -qx 'other-cluster' '${FAIL_FILE}'"
printf 'sg-leak:watch-it-burn-community-b01\n' >"${FAIL_FILE}"
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $*" >>"${CALLS}"
case "$*" in
  *describe-security-groups*--filters*tag:*) echo "sg-stuck" ;;
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
