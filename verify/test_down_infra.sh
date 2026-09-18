#!/usr/bin/env bash
# ABOUTME: Pins that 'down all' destroys the lab VPC too, and that down-infra refuses while clusters live.
#
# Why this exists. `fleet.sh down` destroyed clusters and left each account's lab VPC running: a NAT
# gateway, an Elastic IP and the Bedrock endpoint, roughly $1.25/day/account. So "tear it down" left the
# only remaining billable thing in place, and audit-zero passed because it was written to treat that VPC
# as the expected floor. The cost was real and recurring, and the caller had to remember a second command
# that did not exist.
#
# Usage: verify/test_down_infra.sh      (offline; static checks against fleet.sh)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

echo "== the verb exists and is reachable =="
check "destroy_lab_vpc_for is defined"  "grep -q '^destroy_lab_vpc_for()' '${FLEET}'"
check "cmd_down_infra is defined"       "grep -q '^cmd_down_infra()' '${FLEET}'"
check "down-infra is in the dispatch"   "grep -qE '^\s+down-infra\) cmd_down_infra' '${FLEET}'"
check "down-infra is documented"        "grep -q 'down-infra \[accts\]' '${FLEET}'"

echo "== 'down all' destroys the VPC by default =="
check "down all calls cmd_down_infra"   "grep -q 'cmd_down_infra || true' '${FLEET}'"
check "and still runs audit_zero"       "grep -A6 'cmd_down_infra || true' '${FLEET}' | grep -q 'audit_zero'"
check "WIB_KEEP_VPC is the opt-OUT, not the opt-in" \
      "grep -q 'WIB_KEEP_VPC' '${FLEET}'"

echo "== it cannot strand a live cluster's networking =="
check "refuses while clusters are live" "grep -q 'REFUSING to destroy the lab VPC' '${FLEET}'"
check "and records that as a failure"   "grep -q 'vpc-in-use' '${FLEET}'"
check "a failed destroy is recorded"    "grep -q 'vpc-destroy:' '${FLEET}'"

echo "== the per-account state split is honoured =="
# accen-dev's lab VPC lives in the DEFAULT terraform.tfstate; the rest under states/<acct>.tfstate.
# Getting this wrong destroys the wrong account's networking, or silently no-ops.
check "lab_vpc_state_for is defined"    "grep -q '^lab_vpc_state_for()' '${FLEET}'"
check "default account uses terraform.tfstate" \
      "grep -A4 '^lab_vpc_state_for()' '${FLEET}' | grep -q 'WIB_DEFAULT_ACCOUNT'"
check "other accounts use states/<acct>.tfstate" \
      "grep -A8 '^lab_vpc_state_for()' '${FLEET}' | grep -q 'states/%s.tfstate'"

echo "== EKS log groups are cleaned up too =="
# /aws/eks/<cluster>/cluster OUTLIVES the cluster and nothing ever deleted one. 107 groups and about
# 111 GB were found orphaned on 2026-09-18, including clusters from the retired round naming. Small,
# permanent, and growing by one group per cluster per event, which is the worst shape for a leak.
check "sweep_orphan_log_group is defined"  "grep -q '^sweep_orphan_log_group()' '${FLEET}'"
check "down_one calls it"                  "grep -q 'sweep_orphan_log_group \"\${name}\"' '${FLEET}'"
check "it refuses while the cluster exists" \
      "grep -A6 '^sweep_orphan_log_group()' '${FLEET}' | grep -q 'describe-cluster'"
check "a failed delete is recorded"        "grep -q 'loggroup-leak:' '${FLEET}'"
check "audit-zero names leftover log groups" "grep -q 'zero:\${acct}:loggroups' '${FLEET}'"

echo "== secrets have a command, scoped and forceful =="
check "reap-secrets is defined"      "grep -q '^cmd_reap_secrets()' '${FLEET}'"
check "it is in the dispatch"        "grep -qE '^\s+reap-secrets\) cmd_reap_secrets' '${FLEET}'"
# A name-only filter in a SHARED account has already nearly reached a co-tenant's resources once.
check "scoped by the watch-it-burn/ prefix" \
      "grep -q \"starts_with(Name, 'watch-it-burn/')\" '${FLEET}'"
# A secret in the 30-day recovery window still bills, so the default delete looks like it worked and does not stop the cost.
check "force-deletes rather than scheduling" \
      "grep -q 'force-delete-without-recovery' '${FLEET}'"
check "NOT chained into down all"    "! grep -q 'cmd_reap_secrets || true' '${FLEET}'"

echo "== a clean teardown exits zero (#395) =="
# The router refuses an empty table, correctly. But when the last cluster is gone the table is empty
# because the fleet is gone, and the refusal made a successful 'down all' report failure.
check "ALLOW_EMPTY is passed to the reload" "grep -q 'ALLOW_EMPTY=\"\${allow_empty}\"' '${FLEET}'"
check "only when a shrink was asserted"     "grep -q 'WIB_ROUTES_ALLOW_SHRINK:-' '${FLEET}'"
check "and only when the table is truly empty" \
      "grep -q 'the table is empty and a shrink was asserted' '${FLEET}'"
# The first version of this counted with $(grep -c ... || echo 1). grep -c PRINTS 0 and EXITS 1 when
# nothing matches, so the substitution captured "0\n1" and never equalled "0": the branch could not fire
# and a clean teardown kept reporting failure. Caught only by running a real teardown and reading the
# exit, not by any check.
check "the empty-table count does not use the || echo fallback" \
      "! grep -q 'grep -cvE .* || echo 1' '${FLEET}'"
check "it captures the count separately from the exit status" \
      "grep -q 'route_lines=\"\$(grep -cvE' '${FLEET}'"
check "and compares numerically" "grep -q '\\${route_lines}. -eq 0' '${FLEET}'"

echo "== there is ONE teardown path, not two (#398) =="
TD="${HERE}/../teardown/teardown.sh"
# Two implementations of one verb guarantee that whichever is run, something is skipped, and both exit
# zero so the gap is invisible. That is how 107 orphaned log groups accumulated while a correct
# cleanup-log-groups.sh sat in the repo wired into the path nobody runs.
check "teardown.sh delegates to fleet.sh"  "grep -q 'exec env WIB_APPLY=1' '${TD}'"
check "and does no work of its own"        "! grep -qE '^\s*(terraform|aws) ' '${TD}'"
check "it no longer calls cleanup-log-groups directly" "! grep -q 'CLEANUP_LOGS' '${TD}'"
check "it no longer calls tag-audit directly"          "! grep -q 'TAG_AUDIT' '${TD}'"
check "tag-audit now runs inside down all" "grep -q 'aws/teardown/tag-audit.sh' '${FLEET}'"
check "tag audit runs before the sweeps"   \
      "[ \$(grep -n 'tag-audit.sh' '${FLEET}' | head -1 | cut -d: -f1) -lt \$(grep -n 'cmd_down_infra || true' '${FLEET}' | head -1 | cut -d: -f1) ]"

echo
if [ "${fail}" -gt 0 ]; then echo "FAILED: ${fail} check(s), ${pass} passed"; exit 1; fi
echo "All down-infra checks passed (${pass})."
