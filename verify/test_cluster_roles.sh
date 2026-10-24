#!/usr/bin/env bash
# ABOUTME: The fleet has three kinds of cluster and no rounds: community (attackme), admin (one per
# ABOUTME: presenter), and the numbered attendee pool. Naming, profile and Datadog org all follow the role.
#
# Why (#291, #296). Rounds 1/2/3 were a provisioning artefact that leaked into hostnames, accounts, the
# bootstrap profile and the run-of-show. They are replaced by a role the roster states outright. Three
# separate bugs this year came from two places disagreeing about what a cluster is called (#265, #272,
# #284), so the naming rules get a test rather than a convention.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
ROSTER="${HERE}/../infra/terraform/fleet/roster.tsv"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# Run one expression against a sourced fleet.sh. No cloud access: these are pure naming functions.
q() { ( cd "$(dirname "${FLEET}")" && bash -c "source '${FLEET}' >/dev/null 2>&1; load_roster; $1" 2>/dev/null ); }

echo "== the roster states a role, and there are no rounds =="
rows="$(grep -cvE '^#|^$' "${ROSTER}")"
check "the roster is three clusters" '[[ "$rows" == "3" ]]'
check "one of them is the community cluster" 'grep -q "^watch-it-burn-community|community|" "${ROSTER}"'
check "one admin cluster per presenter" '[[ "$(grep -c "|admin|" "${ROSTER}")" == "2" ]]'
check "no roster row mentions a round" '! grep -qE "^watch-it-burn-r[123]-" "${ROSTER}"'
check "every row carries all seven columns" \
  '[[ "$(grep -vE "^#|^$" "${ROSTER}" | awk -F"|" "NF!=7" | wc -l)" == "0" ]]'

echo "== the role is derived from the name, so nothing has to remember it =="
check "the community cluster is community"  '[[ "$(q "role_of_instructor_name watch-it-burn-community")" == community ]]'
check "an admin cluster is admin"           '[[ "$(q "role_of_instructor_name watch-it-burn-michael-admin")" == admin ]]'
check "an attendee cluster has no role"     '[[ -z "$(q "role_of_instructor_name watch-it-burn-attendee-007")" ]]'
check "a retired presenter student name has no role" '[[ -z "$(q "role_of_instructor_name watch-it-burn-whitney-student")" ]]'

echo "== a roster cluster is recognised as one =="
check "community counts as a roster cluster" 'q "is_instructor_name watch-it-burn-community"'
check "admin counts as a roster cluster"     'q "is_instructor_name watch-it-burn-whitney-admin"'
check "an attendee does not"                 '! q "is_instructor_name watch-it-burn-attendee-042"'
check "a retired presenter student name does not" '! q "is_instructor_name watch-it-burn-michael-student"'

echo "== the hostname a human is given =="
check "the community cluster answers on attackme" \
  '[[ "$(q "public_host_for watch-it-burn-community")" == attackme.agenticburn.com ]]'
check "an admin cluster is named for its owner" \
  '[[ "$(q "public_host_for watch-it-burn-michael-admin")" == michael-admin.agenticburn.com ]]'
check "the other presenter too" \
  '[[ "$(q "public_host_for watch-it-burn-whitney-admin")" == whitney-admin.agenticburn.com ]]'
check "nothing is named <owner>-student any more (#295)" \
  '[[ "$(q "public_host_for watch-it-burn-whitney-student")" != whitney-student.agenticburn.com ]]'
check "an attendee still gets its memorable name" \
  '[[ "$(q "public_host_for watch-it-burn-attendee-007")" == *-*.agenticburn.com ]]'
check "no hostname anywhere is a roundN name" \
  '[[ "$(q "public_host_for watch-it-burn-community; echo; public_host_for watch-it-burn-michael-admin")" != *round* ]]'

echo "== the profile follows the role =="
spec() { q "_provision_spec_fleet() { :; }; print_bootstrap_hints() { :; }; require_tools() { :; }
            cmd_instructors up $1 >/dev/null 2>&1
            for k in \"\${!PROVISION_SPEC[@]}\"; do echo \"\${k}=\$(cut -d'|' -f2 <<<\"\${PROVISION_SPEC[\$k]}\")\"; done | sort"; }
check "community bootstraps the unguarded profile" '[[ "$(spec community)" == "watch-it-burn-community=burn" ]]'
check "admin bootstraps the armed profile" \
  '[[ "$(spec admin)" == *"michael-admin=admin"* && "$(spec admin)" == *"whitney-admin=admin"* ]]'
check "an owner selects only that presenter's cluster" '[[ "$(spec whitney | wc -l)" == "1" ]]'
check "both selects all three" '[[ "$(spec both | wc -l)" == "3" ]]'

echo "== teardown takes the same selector as the build (#88) =="
# After rounds were retired, `instructors down` still looped rounds 1/2/3, matched no roster row and
# destroyed nothing. The workers are stubbed: run_pool prints the names it would hand to down_one.
down() { q "require_tools() { :; }; terraform() { :; }; report_failures() { :; }
            read_vpc_for() { VPC_ID=vpc-test; SUBNETS_JSON='[]'; }
            run_pool() { shift; printf '%s\n' \"\$@\"; }
            cmd_instructors down $1" | sort | tr '\n' ' '; }
check "down with no selector destroys the whole roster" \
  '[[ "$(down "")" == "watch-it-burn-community watch-it-burn-michael-admin watch-it-burn-whitney-admin " ]]'
check "down both destroys the whole roster" \
  '[[ "$(down both)" == "watch-it-burn-community watch-it-burn-michael-admin watch-it-burn-whitney-admin " ]]'
check "down <owner> destroys only that presenter's cluster" '[[ "$(down whitney)" == "watch-it-burn-whitney-admin " ]]'
check "and never the unowned community cluster" '[[ "$(down michael)" == "watch-it-burn-michael-admin " ]]'
check "down <role> destroys only that role" '[[ "$(down community)" == "watch-it-burn-community " ]]'
check "down and up select the same set for every selector" \
  '( for s in "" both community admin michael whitney; do
       [[ "$(down "$s")" == "$(spec "$s" | cut -d= -f1 | tr "\n" " ")" ]] || exit 1
   done )'
check "an unknown selector destroys nothing" '[[ -z "$(down nobody-by-that-name)" ]]'
check "and says so rather than exiting silently" \
  '( cd "$(dirname "${FLEET}")" && bash -c "source \"${FLEET}\" >/dev/null 2>&1; require_tools() { :; }
       run_pool() { :; }; cmd_instructors down nobody-by-that-name" 2>&1 ) | grep -q "no roster clusters"'

echo "== Datadog: one shared org for the presenters, dual shipping for students (#296) =="
# datadog_keys_for prints "api app admin_api admin_app". A roster cluster takes the shared org as its
# PRIMARY and has no second destination; an attendee takes a pool org and dual-ships to the shared one.
src="$(cat "${FLEET}")"
check "an attendee slot is what selects a pool org" \
  'grep -q "if \[\[ -n \"\${slot}\" \]\]; then" <<<"$src"'
check "roster and admin clusters fall through to the instructor org" \
  'grep -q "_dd=\"\${_admin}\"" <<<"$src"'
check "only slotted clusters get a dual-ship key" \
  '! grep -q "|| is_presenter_name \"\${name}\"; then" <<<"$src"'
# The presenter rule now names the admin clusters (#295), so it must not be what selects dual shipping, or
# an admin cluster would dual-ship to the org it already ships to.
check "an admin cluster is a presenter cluster, and that alone grants no second key" \
  'q "is_presenter_name watch-it-burn-michael-admin" && ! grep -q "is_presenter_name" <<<"$(sed -n "/^datadog_keys_for() {/,/^}/p" "${FLEET}")"'

# With no shared org loaded (#454) a roster cluster still bootstraps, without Datadog, and converge reports
# the gap rather than failing (#510). Only an attendee slot is refused, since falling back would mix
# students' telemetry into another org. The behaviour is shimmed in test_fleet_converge_repairs.sh.
boot_src="$(sed -n "/^bootstrap_one() {/,/^}/p" "${FLEET}")"
repair_src="$(sed -n "/^repair_datadog() {/,/^}/p" "${FLEET}")"
check "bootstrap refuses an unresolved org only for an attendee slot" \
  'grep -B1 "refusing to fall back to the shared org" <<<"$boot_src" | grep -q "if is_attendee_name \"\${name}\"; then"'
check "converge records unresolved keys as a failure only for an attendee slot" \
  'grep -B1 "datadog-keys-unresolved" <<<"$repair_src" | grep -q "is_attendee_name \"\${name}\" ||"'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
