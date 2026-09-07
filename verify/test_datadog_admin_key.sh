#!/usr/bin/env bash
# ABOUTME: Tests for #272: the instructor org's APP key is never written to a cluster, and the verifier
# ABOUTME: recognises a presenter cluster by fleet.sh's own naming rule rather than a stale glob. Offline.
#
# Why. The admin app key is a READ credential for the org that aggregates every cluster's telemetry,
# including LLM Observability spans carrying each attendee's prompts. It was written into the agent,
# datadog and monitoring namespaces of all 50 student clusters, where the terminal has cluster-wide read
# and where C1-C3 teach prompt-injecting the agent into running shell commands. Nothing consumed it.
#
# The second half: verify/datadog-orgs.sh decided "is this a cluster that must dual-ship?" with the glob
# *-pres-*, which the #208/#258 rename to <owner>-student killed. watch-it-burn-michael-student matched
# nothing and was reported "instructor cluster, single org by design" — a false pass on a presenter's own
# demo cluster.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IDENT="${HERE}/../infra/datadog-cluster-identity.sh"
ORGS="${HERE}/../verify/datadog-orgs.sh"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# Strip comments before asserting: both files EXPLAIN the old behaviour in prose, and a check that cannot
# tell a comment from code would fail on its own documentation.
code() { grep -vE "^[[:space:]]*#" "$1"; }
IDENT_SRC="$(code "${IDENT}")"; ORGS_SRC="$(code "${ORGS}")"

echo "== the admin app key never reaches a cluster =="
check "the identity script does not write an app-key literal" \
    '! grep -q -- "--from-literal=app-key=" <<<"$IDENT_SRC"'
check "it still writes the admin api-key, which dual shipping actually needs" \
    'grep -q -- "--from-literal=api-key=" <<<"$IDENT_SRC"'
check "all four dual-ship endpoint blobs are still built" \
    '[[ "$(grep -c -- "-additional-endpoints=" <<<"$IDENT_SRC")" -ge 3 ]]'
check "the reason is recorded in the script, not just in the commit" \
    'grep -qi "read credential" "${IDENT}"'

echo "== the verifier takes the app key from the operator, not from a student cluster =="
check "it reads WITB_DD_ADMIN_APP_KEY from the environment" \
    'grep -q "ADMIN_APP_KEY=\"\${WITB_DD_ADMIN_APP_KEY:-}\"" <<<"$ORGS_SRC"'
# Only the ADMIN secret is forbidden. The cluster's OWN datadog-secret legitimately carries an app key:
# that is the student's own org, the Datadog Agent CR needs it, and resolving the cluster's own org name
# requires it. The thing that must never be on a cluster is the key to everyone ELSE's org.
check "it no longer decodes an app-key out of the ADMIN secret" \
    '! grep -A3 "get secret datadog-admin-secret -o json" <<<"$ORGS_SRC" | grep -q "app-key"'
check "it still reads the cluster's own app key from datadog-secret" \
    'grep -A2 "get secret datadog-secret" <<<"$ORGS_SRC" | grep -q "app-key"'
check "a missing app key SKIPs loudly instead of passing quietly" \
    'grep -q "SKIP  \$ctx dual-ships" <<<"$ORGS_SRC"'
check "an admin secret with no api-key is still a failure" \
    'grep -q "has no api-key" <<<"$ORGS_SRC"'

echo "== presenter clusters are recognised by fleet.sh's rule, not a glob =="
check "the dead *-pres-* glob is gone" '! grep -q -- "\*-pres-\*" <<<"$ORGS_SRC"'
check "it calls is_presenter_name" 'grep -q "is_presenter_name" <<<"$ORGS_SRC"'
check "and it sources fleet.sh to get it" 'grep -q "source .*fleet.sh" <<<"$ORGS_SRC"'

# The regression itself: the renamed presenter clusters must be classified as needing dual shipping.
echo "== the rule actually matches today's presenter names =="
match() { ( source "${FLEET}" >/dev/null 2>&1; is_presenter_name "$1" && echo yes || echo no ) 2>/dev/null | tail -1; }
check "watch-it-burn-michael-student is a presenter cluster"  '[[ "$(match watch-it-burn-michael-student)" == yes ]]'
check "watch-it-burn-whitney-student is a presenter cluster"  '[[ "$(match watch-it-burn-whitney-student)" == yes ]]'
check "an instructor round cluster is NOT"                    '[[ "$(match watch-it-burn-r3-1)" == no ]]'
check "an attendee cluster is NOT (it matches by its own glob)" '[[ "$(match watch-it-burn-attendee-007)" == no ]]'
check "the old pres- form no longer matches, so nothing silently depends on it" \
    '[[ "$(match watch-it-burn-pres-michael)" == no ]]'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
