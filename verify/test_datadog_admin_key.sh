#!/usr/bin/env bash
# ABOUTME: Tests for #272: the instructor org's APP key is never written to a cluster, and the verifier
# ABOUTME: recognises a dual-shipping cluster by fleet.sh's own naming rule rather than a stale glob. Offline.
#
# Why. The admin app key is a READ credential for the org that aggregates every cluster's telemetry,
# including LLM Observability spans carrying each attendee's prompts. It was written into the agent,
# datadog and monitoring namespaces of all 50 student clusters, where the terminal has cluster-wide read
# and where C1-C3 teach prompt-injecting the agent into running shell commands. Nothing consumed it.
#
# The second half: verify/datadog-orgs.sh decided "is this a cluster that must dual-ship?" with the glob
# *-pres-*, which the #208/#258 rename to <owner>-student killed. watch-it-burn-michael-student matched
# nothing and was reported "instructor cluster, single org by design" — a false pass on a presenter's own
# demo cluster. Those student clusters are retired (#295): a presenter claims a pool cluster by email, so the
# attendee pool is the only class that dual-ships, and the verifier asks fleet.sh's is_attendee_name.
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

echo "== dual-shipping clusters are recognised by fleet.sh's rule, not a glob =="
check "the dead *-pres-* glob is gone" '! grep -q -- "\*-pres-\*" <<<"$ORGS_SRC"'
check "the *-attendee-* glob is gone too" '! grep -q -- "\*-attendee-\*" <<<"$ORGS_SRC"'
check "it calls is_attendee_name" 'grep -q "is_attendee_name" <<<"$ORGS_SRC"'
check "and it sources fleet.sh to get it" 'grep -q "source .*fleet.sh" <<<"$ORGS_SRC"'
check "and refuses to run without it, rather than calling everything single-org" \
    'grep -q "declare -F is_attendee_name" <<<"$ORGS_SRC"'

# The regression itself: what must dual-ship is classified as such, and nothing else is.
echo "== the rule actually matches today's names =="
match() { ( source "${FLEET}" >/dev/null 2>&1; is_attendee_name "$1" && echo yes || echo no ) 2>/dev/null | tail -1; }
check "an attendee pool cluster dual-ships"                   '[[ "$(match watch-it-burn-attendee-007)" == yes ]]'
check "an admin cluster does NOT (it ships to the shared org)" '[[ "$(match watch-it-burn-private)" == no ]]'
check "the community cluster does NOT"                        '[[ "$(match watch-it-burn-community)" == no ]]'
check "a retired presenter student name is not a pool cluster" '[[ "$(match watch-it-burn-whitney-student)" == no ]]'
check "the old pres- form no longer matches, so nothing silently depends on it" \
    '[[ "$(match watch-it-burn-pres-michael)" == no ]]'

# One org (#587): an attendee cluster whose own key is the instructor org's (question 926's one-row pool) has no
# admin secret by design. The verifier runs against shims here: kubectl, curl and aws answer from the test.
echo "== an attendee on the instructor org itself is one org by design, an attendee on its own org still must dual-ship =="
SHIM="$(mktemp -d)"; trap 'rm -rf "${SHIM}"' EXIT
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
case "$*" in
  *"get secret datadog-secret -o json"*) printf '{"data":{"api-key":"%s","app-key":"%s"}}' "$(printf OWN_API | base64)" "$(printf OWN_APP | base64)" ;;
  *"get configmap cluster-identity"*) printf 'watch-it-burn-attendee-001' ;;
  *"get secret datadog-admin-secret"*) exit 1 ;;
esac
S
printf '#!/usr/bin/env bash\necho %s\n' "'{\"included\":[{\"type\":\"orgs\",\"attributes\":{\"name\":\"Datadog\"}}]}'" >"${SHIM}/curl"
printf '#!/usr/bin/env bash\nprintf %s "{\\"api-key\\":\\"${INSTRUCTOR_API}\\"}"\n' "'%s'" >"${SHIM}/aws"
chmod +x "${SHIM}"/*
orgs() { PATH="${SHIM}:${PATH}" INSTRUCTOR_API="$1" bash "${ORGS}" arn:aws:eks:us-west-2:1:cluster/watch-it-burn-attendee-001 p 2>&1; }
one="$(orgs OWN_API)"; one_rc=$?
check "the cluster's key is the instructor key: it passes, saying one org by design" \
    '[[ "${one_rc}" -eq 0 ]] && grep -q "one org by design" <<<"${one}"'
two="$(orgs OTHER_API)"; two_rc=$?
check "the instructor key is another org's: no admin secret is still a failure" \
    '[[ "${two_rc}" -ne 0 ]] && grep -q "attendee cluster without datadog-admin-secret" <<<"${two}"'
none="$(orgs "")"; none_rc=$?
check "the instructor key unreadable: no admin secret is still a failure" '[[ "${none_rc}" -ne 0 ]]'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
