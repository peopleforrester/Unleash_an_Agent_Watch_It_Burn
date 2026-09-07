#!/usr/bin/env bash
# ABOUTME: Behavioural tests for what a provisioning verb RETURNS: a build whose acceptance pass passed
# ABOUTME: must exit 0, and one whose acceptance failed must not. Offline; every worker is stubbed out.
#
# Why. On 2026-09-07 the 03:30 scheduled run aborted before its attendee clusters because
# `instructors up both` exited 1, thirty-eight minutes after building nine clusters its own verify then
# reported as "9 healthy, 0 with problems". The cause was the last line of cmd_instructors:
#
#     [[ -n "${WIB_NO_BOOTSTRAP:-}" ]] && print_bootstrap_hints "${round_filter}"
#
# With bootstrapping on, which is every normal run, that test is false, it is the last command in the
# function, and under `set -e` the script exits with its status. The verb could never return 0. The
# mirror image sat in _provision_spec_fleet, whose final `cmd_verify ... || log ...` swallowed the
# acceptance result, so `up <names>` returned 0 no matter what verify found.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# Run one expression against a sourced fleet.sh with the workers stubbed out. Nothing here touches AWS,
# kubectl, terraform or the router: the point is the exit code, not the work.
src() {
    ( cd "$(dirname "${FLEET}")" && bash -c '
        source "'"${FLEET}"'" >/dev/null 2>&1
        # Workers, stubbed. VERIFY_RC is what the acceptance pass decides.
        run_pool() { :; }
        up_one() { :; }
        wait_for_console_lbs() { :; }
        cmd_routes() { :; }
        register_with_provisioning() { :; }
        converge_one() { :; }
        report_failures() { :; }
        read_vpc_for() { VPC_ID=vpc-test; SUBNETS_JSON="[]"; }
        prune_empty_states() { :; }
        require_tools() { :; }
        print_bootstrap_hints() { echo "hints printed"; }
        cmd_verify() { echo "verify ran on: $*"; return "${VERIFY_RC:-0}"; }
        '"$1"'
        echo "rc=$?"
    ' 2>&1 )
}

echo "== a build whose acceptance passed returns success =="
out="$(VERIFY_RC=0 src 'cmd_instructors up both')"
check "instructors up exits 0 when verify passes" 'grep -q "rc=0" <<<"$out"'
# The names come out of an associative array, so their order is hash order, not roster order.
# The roster is three clusters now, not nine: one community and one admin per presenter (#291).
check "the acceptance pass actually ran over all three built clusters" \
    '[[ "$(grep -cE "watch-it-burn-(community|[a-z]+-admin)" <<<"$(grep "verify ran on:" <<<"$out" | tr " " "\n")")" -eq 3 ]]'

echo "== a build whose acceptance FAILED does not report success =="
out="$(VERIFY_RC=1 src 'cmd_instructors up both')"
check "instructors up exits non-zero when verify fails" 'grep -qv "rc=0" <<<"$out" && ! grep -q "rc=0" <<<"$out"'
check "and says so rather than failing silently" 'grep -q "NOT ready" <<<"$out"'

echo "== the same contract for the attendee path =="
out="$(VERIFY_RC=0 src 'cmd_up watch-it-burn-attendee-001')"
check "up <name> exits 0 when verify passes" 'grep -q "rc=0" <<<"$out"'
out="$(VERIFY_RC=1 src 'cmd_up watch-it-burn-attendee-001')"
check "up <name> exits non-zero when verify fails (it used to swallow the result)" '! grep -q "rc=0" <<<"$out"'

echo "== the bootstrap hints must not decide the exit code =="
out="$(VERIFY_RC=0 WIB_NO_BOOTSTRAP=1 src 'cmd_instructors up both')"
check "hints are printed when bootstrapping is off" 'grep -q "hints printed" <<<"$out"'
check "and printing them still exits 0" 'grep -q "rc=0" <<<"$out"'
out="$(VERIFY_RC=0 src 'cmd_instructors up both')"
check "no hints when bootstrapping is on, and still exit 0" '! grep -q "hints printed" <<<"$out" && grep -q "rc=0" <<<"$out"'

echo "== a verb that builds nothing is not a failure =="
out="$(VERIFY_RC=0 src 'cmd_instructors up nobody-by-that-name')"
check "an empty selection exits 0 with a message" 'grep -q "rc=0" <<<"$out" && grep -q "no roster clusters" <<<"$out"'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
