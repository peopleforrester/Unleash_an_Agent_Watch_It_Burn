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
check "a presenter student cluster has no role" '[[ -z "$(q "role_of_instructor_name watch-it-burn-whitney-student")" ]]'

echo "== a roster cluster is recognised as one =="
check "community counts as a roster cluster" 'q "is_instructor_name watch-it-burn-community"'
check "admin counts as a roster cluster"     'q "is_instructor_name watch-it-burn-whitney-admin"'
check "an attendee does not"                 '! q "is_instructor_name watch-it-burn-attendee-042"'
check "a presenter student cluster does not" '! q "is_instructor_name watch-it-burn-michael-student"'

echo "== the hostname a human is given =="
check "the community cluster answers on attackme" \
  '[[ "$(q "public_host_for watch-it-burn-community")" == attackme.agenticburn.com ]]'
check "an admin cluster is named for its owner" \
  '[[ "$(q "public_host_for watch-it-burn-michael-admin")" == michael-admin.agenticburn.com ]]'
check "the other presenter too" \
  '[[ "$(q "public_host_for watch-it-burn-whitney-admin")" == whitney-admin.agenticburn.com ]]'
check "a presenter student cluster is unchanged" \
  '[[ "$(q "public_host_for watch-it-burn-whitney-student")" == whitney-student.agenticburn.com ]]'
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

echo "== Datadog: one shared org for the presenters, dual shipping for students (#296) =="
# datadog_keys_for prints "api app admin_api admin_app". A roster cluster takes the shared org as its
# PRIMARY and has no second destination; an attendee takes a pool org and dual-ships to the shared one.
src="$(cat "${FLEET}")"
check "an attendee slot is what selects a pool org" \
  'grep -q "if \[\[ -n \"\${slot}\" \]\]; then" <<<"$src"'
check "roster and admin clusters fall through to the instructor org" \
  'grep -q "_dd=\"\${_admin}\"" <<<"$src"'
check "only slotted and presenter-student clusters get a dual-ship key" \
  'grep -q "if \[\[ -n \"\${slot}\" \]\] || is_presenter_name \"\${name}\"; then" <<<"$src"'
# An admin cluster must NOT match the presenter-student rule, or it would dual-ship to its own org.
check "an admin cluster is not a presenter student cluster" \
  '! q "is_presenter_name watch-it-burn-michael-admin"'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
