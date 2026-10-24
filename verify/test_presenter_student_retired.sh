#!/usr/bin/env bash
# ABOUTME: The dedicated presenter student clusters are gone (#295): Michael and Whitney claim a pool cluster
# ABOUTME: by email like everyone else, and the one owner-named presenter cluster left is <owner>-admin. Offline.
#
# Why. watch-it-burn-michael-student and watch-it-burn-whitney-student were provisioned outside the pool,
# so the presenters never walked the claim flow the room walks. Every seam that broke on 2026-09-07 (40 of 50
# clusters without a route, registration skipping every cluster outside the default account, a dual-shipping
# check that false-passed on a stale glob, #272) was one a presenter claiming their own cluster would have
# hit first. With the student clusters gone, the owner-derived naming rule (is_presenter_name) is still the
# ONE place that names a presenter's cluster; it now names the admin cluster (#294) instead of a second class.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
ROSTER="${HERE}/../infra/terraform/fleet/roster.tsv"
T="$(mktemp -d -p "${HERE}/.." .presenter-retired-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
mkdir -p "${T}/states"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# Run one expression against a sourced fleet.sh, with state in a temp dir and no cloud access.
q() { ( cd "$(dirname "${FLEET}")" && WIB_STATE_DIR="${T}/states" \
        bash -c "source '${FLEET}' >/dev/null 2>&1; load_roster; $1" 2>/dev/null ); }
# Comments explain the retired class in prose; assertions about behaviour read the code only.
code() { grep -vE '^[[:space:]]*#' "$1"; }
FLEET_CODE="$(code "${FLEET}")"

echo "== no roster row, provisioning path or bootstrap profile produces a presenter student cluster =="
check "no roster row is a -student cluster" '! grep -vE "^#|^$" "${ROSTER}" | grep -q -- "-student|"'
check "the presenter naming rule no longer matches a -student name" \
  '! q "is_presenter_name watch-it-burn-michael-student"'
check "no bootstrap profile is named for a student or presenter cluster" \
  '[[ -z "$(ls "${HERE}/../gitops/bootstrap" | grep -iE "student|presenter")" ]]'
check "fleet.sh code never builds a <owner>-student name or host" \
  '! grep -qE "[a-z}]-student([^0-9]|$)" <<<"${FLEET_CODE}"'
# `up` takes explicit names, and before #295 that is how the presenter student clusters were built.
up() { q "_provision_spec_fleet() { shift 2; printf '%s\n' \"\$@\"; }; require_tools() { :; }; cmd_up $1"; }
check "up refuses a presenter student name" '[[ -z "$(up watch-it-burn-michael-student)" ]]'
check "and says why, pointing at the claim flow" \
  'grep -qi "claim" <<<"$( cd "$(dirname "${FLEET}")" && bash -c "source \"${FLEET}\" >/dev/null 2>&1
       _provision_spec_fleet() { :; }; cmd_up watch-it-burn-whitney-student" 2>&1 )"'
check "up refuses a roster name too: those are built by instructors up" '[[ -z "$(up watch-it-burn-michael-admin)" ]]'
check "up still provisions attendee pool clusters by count" \
  '[[ "$(up 2 | sort | tr "\n" " ")" == "watch-it-burn-attendee-001 watch-it-burn-attendee-002 " ]]'
check "and by name" '[[ "$(up watch-it-burn-attendee-007)" == watch-it-burn-attendee-007 ]]'
spec() { q "_provision_spec_fleet() { :; }; print_bootstrap_hints() { :; }; require_tools() { :; }
            cmd_instructors up $1 >/dev/null 2>&1; printf '%s\n' \"\${!PROVISION_SPEC[@]}\""; }
check "instructors up never builds a -student cluster, for any selector" \
  '( for s in "" both all community admin michael whitney; do spec "$s" | grep -q -- "-student$" && exit 1; done; exit 0 )'

echo "== a presenter's claimed cluster is an ordinary pool cluster =="
# What a presenter's email claims is an attendee-NNN row, so everything below is the attendee path. The point
# is that nothing in fleet.sh singles a presenter out any more: one class gets a pool org and dual shipping.
check "the only name class that dual-ships is the attendee pool" \
  'grep -q "if \[\[ -n \"\${slot}\" \]\]; then" <<<"${FLEET_CODE}" && ! grep -q "|| is_presenter_name \"\${name}\"; then" <<<"${FLEET_CODE}"'
check "no cluster resolves to the retired admin-attendee org" \
  '! grep -q "datadog-admin-attendee\|==\"admin-attendee\"" <<<"${FLEET_CODE}"'
check "a pool cluster gets its memorable hostname, not an owner name" \
  '[[ "$(q "public_host_for watch-it-burn-attendee-001")" != *michael* && "$(q "public_host_for watch-it-burn-attendee-001")" == *-*.agenticburn.com ]]'
check "attendee registration and routing are the same code for every claimed cluster" \
  'grep -q "_ingest_attendee_names" <<<"${FLEET_CODE}" && ! grep -q "watch-it-burn-\*-\${PRESENTER" <<<"${FLEET_CODE}"'
check "the dual-shipping verifier asks fleet.sh which clusters are attendees" \
  'grep -q "is_attendee_name \"\$want\"" "${HERE}/datadog-orgs.sh"'
check "is_attendee_name is the pool rule" \
  'q "is_attendee_name watch-it-burn-attendee-042" && ! q "is_attendee_name watch-it-burn-michael-admin" && ! q "is_attendee_name watch-it-burn-community"'

echo "== the owner-derived naming rule generalised to the admin clusters, in one place =="
check "an admin cluster is a presenter cluster" 'q "is_presenter_name watch-it-burn-whitney-admin"'
check "its owner comes from the name" '[[ "$(q "presenter_owner_of watch-it-burn-whitney-admin")" == whitney ]]'
check "and its host is <owner>-admin" '[[ "$(q "public_host_for watch-it-burn-michael-admin")" == michael-admin.agenticburn.com ]]'
check "is_instructor_name defers to it rather than restating the admin regex" \
  'grep -q "^is_instructor_name() .*is_presenter_name" <<<"${FLEET_CODE}"'
check "no other -admin name regex is left in fleet.sh" \
  '[[ "$(grep -cE "\-admin\\\$|\*-admin\)" <<<"${FLEET_CODE}")" == 0 ]]'
check "every admin roster row's owner column agrees with the name" \
  '( grep -vE "^#|^$" "${ROSTER}" | awk -F"|" "\$2==\"admin\"" | while IFS="|" read -r n _ _ _ _ _ o; do
       [[ "$(q "presenter_owner_of $n")" == "$o" ]] || exit 1; done )'
check "the community cluster is not a presenter cluster" '! q "is_presenter_name watch-it-burn-community"'
check "an attendee cluster is not a presenter cluster" '! q "is_presenter_name watch-it-burn-attendee-007"'

echo "== the sets that keep presenter clusters through a teardown no longer expect student clusters =="
# A stray state file from the old fleet must not be swept back into a presenter's set.
for n in watch-it-burn-community watch-it-burn-michael-admin watch-it-burn-whitney-admin \
         watch-it-burn-michael-student watch-it-burn-whitney-student watch-it-burn-attendee-001; do
    : >"${T}/states/${n}.tfstate"
done
sel() { q "resolve_all $*" | sort | tr '\n' ' '; }
check "an owner selects that presenter's admin cluster only" '[[ "$(sel michael)" == "watch-it-burn-michael-admin " ]]'
check "the other presenter too" '[[ "$(sel whitney)" == "watch-it-burn-whitney-admin " ]]'
check "presenters selects the admin clusters, not student clusters" \
  '[[ "$(sel presenters)" == "watch-it-burn-michael-admin watch-it-burn-whitney-admin " ]]'
check "instructors is the roster and nothing else" \
  '[[ "$(sel instructors)" == "watch-it-burn-community watch-it-burn-michael-admin watch-it-burn-whitney-admin " ]]'
check "the attendee teardown selector does not reach a presenter cluster" '[[ "$(sel attendees)" == "watch-it-burn-attendee-001 " ]]'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
