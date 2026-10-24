#!/usr/bin/env bash
# ABOUTME: Behavioural tests for the admin console's runner (#268): the restart-agent, restart-console and
# ABOUTME: terminal-password verbs, and serve-actions claiming, running and reporting queued actions. Uses shims.
#
# Usage: verify/test_admin_actions.sh      (no cloud access; kubectl, aws and curl are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/states" "${T}/pool"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# jtrue <file> <python expression over d>: the JSON in <file> satisfies the expression.
jtrue() { python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); sys.exit(0 if eval(sys.argv[2]) else 1)' "$1" "$2" 2>/dev/null; }

# ---- shims: every external command records its argv and answers from env the test controls ----
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $*" >>"${CALLS}"; exit 0
S
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $* [AWS_PROFILE=${AWS_PROFILE:-}]" >>"${CALLS}"
case "$*" in
  "config current-context") echo "${KCTX}" ;;
  *"get pods"*"-o jsonpath"*) echo "${OLD_PODS-old-pod-1}" ;;
  *"get pods"*"-o json"*)
      if [[ "${READY:-1}" == 1 ]]; then
          echo '{"items":[{"metadata":{"name":"old-pod-1","deletionTimestamp":"x"},"status":{"conditions":[{"type":"Ready","status":"True"}]}},
                          {"metadata":{"name":"new-pod-1"},"status":{"conditions":[{"type":"Ready","status":"True"}]}}]}'
      else
          echo '{"items":[{"metadata":{"name":"old-pod-1"},"status":{"conditions":[{"type":"Ready","status":"True"}]}},
                          {"metadata":{"name":"new-pod-1"},"status":{"conditions":[{"type":"Ready","status":"False"}]}}]}'
      fi ;;
  *"delete pod"*) exit "${DELETE_RC:-0}" ;;
  *"create secret"*) echo "kind: Secret" ;;
  *"apply -f -"*) cat >"${T}/applied" ;;
esac
exit 0
S
# curl: answers the provisioning app's admin routes. The queue body comes from ${T}/queue.json, a claim is
# refused for any id listed in REFUSE_CLAIM, and every POSTed body is kept for the assertions.
cat >"${SHIM}/curl" <<'S'
#!/usr/bin/env bash
out=""; url=""; method=GET; data=""; tok=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out="$2"; shift ;;
    -X) method="$2"; shift ;;
    -H) [[ "$2" == X-Admin-Token:* ]] && tok="${2#X-Admin-Token: }"; shift ;;
    --data-binary) data="${2#@}"; shift ;;
    -w|--max-time) shift ;;
    http*) url="$1" ;;
  esac
  shift
done
echo "curl ${method} ${url} token=${tok}" >>"${CALLS}"
path="${url#https://prov.test}"; code=200; : >"${out:-/dev/null}"
case "${method} ${path}" in
  "GET /admin/actions?status=pending") cat "${T}/queue.json" >"${out}" ;;
  POST\ /admin/actions/*/claim) id="${path#/admin/actions/}"; id="${id%/claim}"
        [[ " ${REFUSE_CLAIM:-} " == *" ${id} "* ]] && code=409 ;;
  POST\ /admin/actions/*/result) id="${path#/admin/actions/}"; id="${id%/result}"; cp "${data}" "${T}/result.${id}" ;;
  "POST /admin/health") cp "${data}" "${T}/health.json"; code="${HEALTH_CODE:-200}" ;;
  *) code=404 ;;
esac
printf '%s' "${code}"
S
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"
A=watch-it-burn-attendee-007; ADMIN=watch-it-burn-whitney-admin
touch "${T}/states/${A}.tfstate" "${T}/states/${ADMIN}.tfstate"
echo accen-qa >"${T}/states/${A}.account"
ctx_of() { printf 'arn:aws:eks:us-west-2:111122223333:cluster/%s' "$1"; }
# Sourcing fleet.sh: the source guard keeps main() from running; WIB_* settings make every wait instant.
src() { # $1: bash snippet to run after sourcing
  ( cd "$(dirname "${FLEET}")" && WIB_ADMIN_TOKEN=test-token WIB_PROVISIONING_URL=https://prov.test \
      WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" WIB_AWS_POOL_DIR="${T}/pool" WIB_RESTART_WAIT=2 WIB_RESTART_INTERVAL=1 \
      bash -c "source '${FLEET}' >/dev/null 2>&1; $1" 2>>"${T}/stderr" )
}

echo "== restart-agent deletes BurritoBot's pod and waits for a Ready replacement =="
: >"${CALLS}"
KCTX="$(ctx_of "${A}")" src "cmd_restart_agent ${A}"; rc=$?
check "exits 0 once a new pod is Ready" '[[ "${rc}" -eq 0 ]]'
check "deletes the agent pod by the workshop-agent selector, in ns agent, with an explicit context" \
  'grep -q "kubectl --context $(ctx_of "${A}") -n agent delete pod old-pod-1 --wait=false" "${CALLS}" && grep -q -- "-n agent get pods -l app.kubernetes.io/name=workshop-agent" "${CALLS}"'
check "runs in the account the cluster was built in" 'grep "delete pod" "${CALLS}" | grep -q "AWS_PROFILE=accen-qa"'
check "a pod delete, never a rollout restart (the drift policy refuses one)" '! grep -q "rollout" "${CALLS}"'
: >"${CALLS}"
READY=0 KCTX="$(ctx_of "${A}")" src "cmd_restart_agent ${A}"; rc=$?
check "no Ready replacement inside the wait is a failure" '[[ "${rc}" -ne 0 ]]'
check "the old pod still being Ready does not count as the replacement" 'grep -q "no Ready replacement" "${T}/stderr"'
: >"${CALLS}"
OLD_PODS="" KCTX="$(ctx_of "${A}")" src "cmd_restart_agent ${A}"; rc=$?
check "no pod to delete is a failure, not a silent success" '[[ "${rc}" -ne 0 ]] && ! grep -q "delete pod" "${CALLS}"'

echo "== the target is confirmed before any mutation =="
: >"${CALLS}"
KCTX="$(ctx_of watch-it-burn-attendee-008)" src "cmd_restart_agent ${A}"; rc=$?
check "a kubeconfig pointing at another cluster is refused" '[[ "${rc}" -ne 0 ]] && ! grep -q "delete" "${CALLS}"'
: >"${CALLS}"
KCTX="$(ctx_of packt-cluster-1)" src "cmd_restart_agent packt-cluster-1"; rc=$?
check "a non-watch-it-burn name is refused before kubectl runs" '[[ "${rc}" -ne 0 ]] && ! grep -q "kubectl" "${CALLS}"'

echo "== restart-console =="
: >"${CALLS}"
KCTX="$(ctx_of "${A}")" src "cmd_restart_console ${A}"; rc=$?
check "deletes the console pod by its selector" \
  '[[ "${rc}" -eq 0 ]] && grep -q -- "-n agent get pods -l app.kubernetes.io/name=console" "${CALLS}" && grep -q "delete pod old-pod-1" "${CALLS}"'

echo "== terminal-password re-issues the role's credential =="
: >"${CALLS}"; rm -f "${T}/applied"
KCTX="$(ctx_of "${A}")" src "cmd_terminal_password ${A}"; rc=$?
check "exits 0" '[[ "${rc}" -eq 0 ]]'
check "an attendee cluster gets the student login" 'grep -q "create secret generic terminal-auth --from-literal=TTYD_CREDENTIAL=agentic:agentic --dry-run=client" "${CALLS}"'
check "the secret is applied, so an existing one is overwritten" '[[ -s "${T}/applied" ]]'
check "the local copy ingest publishes matches" '[[ "$(cat "${T}/pool/${A}.terminal")" == agentic ]]'
check "the terminal pod is restarted so ttyd reads it" 'grep -q -- "-n agent get pods -l app.kubernetes.io/name=web-terminal" "${CALLS}"'
: >"${CALLS}"
KCTX="$(ctx_of "${ADMIN}")" src "cmd_terminal_password ${ADMIN}"
check "an admin cluster gets the presenter login" 'grep -q "TTYD_CREDENTIAL=sprouts:sprouts" "${CALLS}"'

echo "== serve-actions claims, runs and reports each queued action =="
cat >"${T}/queue.json" <<J
{"actions": [
  {"id": "a1", "action": "restart-agent", "cluster": "${A}", "requested_by": "whitney@example.com", "requested_at": "2026-10-24T10:00:00Z"},
  {"id": "a2", "action": "rm -rf", "cluster": "${A}", "requested_by": "whitney@example.com"},
  {"id": "a3", "action": "restart-console", "cluster": "packt-cluster-1", "requested_by": "michael@example.com"},
  {"id": "a4", "action": "converge", "cluster": "watch-it-burn-attendee-099", "requested_by": "michael@example.com"},
  {"id": "a5", "action": "restart-agent", "cluster": "${A}", "requested_by": "michael@example.com"}
]}
J
: >"${CALLS}"; rm -f "${T}"/result.* "${T}/health_called"
REFUSE_CLAIM=a5 KCTX="$(ctx_of "${A}")" src "post_fleet_health() { touch '${T}/health_called'; }; cmd_serve_actions --once"; rc=$?
check "one pass exits 0" '[[ "${rc}" -eq 0 ]]'
check "polls the pending queue with the admin token" 'grep -q "curl GET https://prov.test/admin/actions?status=pending token=test-token" "${CALLS}"'
check "posts a health report on the pass" '[[ -e "${T}/health_called" ]]'
check "claims before running" 'grep -n "a1/claim\|delete pod" "${CALLS}" | head -1 | grep -q claim'
check "runs the queued verb against the cluster" 'grep -q "kubectl --context $(ctx_of "${A}") -n agent delete pod old-pod-1" "${CALLS}"'
check "reports done with exit 0 and the verb's output" \
  'jtrue "${T}/result.a1" "d[\"status\"] == \"done\" and d[\"exit_code\"] == 0 and \"replacement Ready\" in d[\"output\"] and d[\"runner\"] and d[\"finished_at\"]"'
check "an action outside the allow-list is refused and answered, not run" \
  'jtrue "${T}/result.a2" "d[\"status\"] == \"failed\" and d[\"exit_code\"] == 2 and \"unknown action\" in d[\"output\"]"'
check "a foreign cluster name is refused" 'jtrue "${T}/result.a3" "d[\"status\"] == \"failed\" and \"not a watch-it-burn cluster\" in d[\"output\"]"'
check "a cluster with no state on this runner is refused" 'jtrue "${T}/result.a4" "d[\"status\"] == \"failed\" and \"no state\" in d[\"output\"]"'
check "an action another runner claimed is left alone" '[[ ! -e "${T}/result.a5" ]]'
check "only the allowed action reached a cluster (one delete)" '[[ "$(grep -c "delete pod" "${CALLS}")" -eq 1 ]]'
audit="${T}/logs/admin-actions.tsv"
check "each action gets a local audit line: when, id, who, what, where, exit code" \
  'grep -qP "^\d{4}-\d\d-\d\dT[\d:]+Z\ta1\twhitney@example.com\trestart-agent\t${A}\t0$" "${audit}"'

echo "== serve-actions says so when the queue does not answer =="
echo 'not json' >"${T}/queue.json"
: >"${CALLS}"
KCTX="$(ctx_of "${A}")" src "post_fleet_health() { :; }; cmd_serve_actions --once"; rc=$?
check "an unreadable queue fails the pass" '[[ "${rc}" -ne 0 ]] && grep -q "did not answer with an action list" "${T}/stderr"'

echo "== the health report goes to /admin/health =="
rm -f "${T}/health.json"
src "cmd_verify() { printf '{\"clusters\": 1, \"results\": [{\"cluster\": \"${A}\", \"agent_ready\": true}]}' >\"\${WIB_VERIFY_REPORT}\"; return 1; }; post_fleet_health"; rc=$?
check "a walkthrough that found a broken cluster is still posted" '[[ "${rc}" -eq 0 ]] && jtrue "${T}/health.json" "d[\"results\"][0][\"agent_ready\"] is True"'
src "cmd_verify() { return 1; }; post_fleet_health"; rc=$?
check "a walkthrough that wrote no report is a failure" '[[ "${rc}" -ne 0 ]]'
HEALTH_CODE=500 src "cmd_verify() { echo '{}' >\"\${WIB_VERIFY_REPORT}\"; }; post_fleet_health"; rc=$?
check "a report the app refused is a failure" '[[ "${rc}" -ne 0 ]]'

echo "== wired into the driver =="
src_txt="$(cat "${FLEET}")"; usage_txt="$(sed -n '/^usage() {/,/^}/p' "${FLEET}")"
for v in restart-agent restart-console terminal-password serve-actions; do
  check "main dispatches ${v}" 'grep -qE "^        ${v}\) cmd_" <<<"${src_txt}"'
  check "usage documents ${v}" 'grep -q "^    ${v}" <<<"${usage_txt}"'
done
check "the queue's action names are exactly the four verbs" \
  'grep -q "^readonly ADMIN_ACTIONS=\"restart-agent restart-console converge terminal-password\"" <<<"${src_txt}"'
echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
