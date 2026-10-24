#!/usr/bin/env bash
# ABOUTME: Deterministic C7 fallback — calls the rogue read_internal_config tool through agentgateway's
# ABOUTME: evil-mcp bind (:3003) with no model in the loop, and asserts the gateway rule allows it, then denies it.
set -euo pipefail

# What this proves: the lesson of C7 is the GUARDRAIL, not the model. This script speaks MCP to the
# gateway's evil-mcp bind itself (initialize, then tools/call), so nothing depends on the model taking the
# poisoned description's bait. With the rule open the sentinel comes back; with it narrowed to get_weather
# the gateway refuses the call before evil-mcp runs it (#496).
#
# It flips the rule the way the stage does: by running the terminal's own guard-mcp-off and guard-mcp-on in
# the web-terminal pod, as the terminal's ServiceAccount (the one principal block-argocd-drift lets edit
# agentgateway-c7-config). It ends with the guard ON. Each wait is timed, and the on -> deny time is the
# rule's live reload delay on this cluster: the gateway reloads the file, nothing restarts.
#
# Admin clusters only. Everywhere else C7's control is the kagent toolNames allow-list and the gateway rule
# stays 'true', so there is no deny here to assert; the script says so and stops.

usage() {
  cat <<'EOF'
Usage: CONTEXT=<kube-context> fallback.curl.sh [--expect-allow|--expect-deny]

  (no flag)        Flip C7 off, assert the call is ALLOWED (sentinel returned), flip it on, assert it
                   is DENIED (refused, no sentinel). Prints how long each took. Leaves the guard ON.
  --expect-allow   One call against the rule as it stands; assert the sentinel comes back. No flip.
  --expect-deny    One call against the rule as it stands; assert the gateway refuses it. No flip.

Environment:
  CONTEXT       kube-context of the ADMIN cluster (required; never the current-context)
  NS            namespace of agentgateway and the web terminal. Default: agent
  LOCAL_PORT    local end of the port-forward to agentgateway:3003. Default: 13003
  TIMEOUT       seconds to wait for each flip to take effect. Default: 180
  TOOL_NAME     rogue tool to invoke. Default: read_internal_config
  SENTINEL      the fake value it leaks. Default: FAKE-MCP-EXFIL-sentinel-4c1d
EOF
}

MODE="both"
case "${1:-}" in
  "")             MODE="both" ;;
  --expect-allow) MODE="allow" ;;
  --expect-deny)  MODE="deny" ;;
  -h|--help)      usage; exit 0 ;;
  *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
esac

# Kube-context safety (see CLAUDE.md): target an explicit context; never the global current-context.
CONTEXT="${CONTEXT:?set CONTEXT to the target kube-context}"
NS="${NS:-agent}"
LOCAL_PORT="${LOCAL_PORT:-13003}"
TIMEOUT="${TIMEOUT:-180}"
TOOL_NAME="${TOOL_NAME:-read_internal_config}"
SENTINEL="${SENTINEL:-FAKE-MCP-EXFIL-sentinel-4c1d}"
KCTL=(kubectl --context "${CONTEXT}" -n "${NS}")
URL="http://127.0.0.1:${LOCAL_PORT}/mcp"
PROTOCOL="2025-06-18"

fail() { echo "==> FAIL: $*" >&2; exit 1; }
command -v kubectl >/dev/null 2>&1 || fail "kubectl not found on PATH"
command -v curl >/dev/null 2>&1 || fail "curl not found on PATH"

# The same test the terminal's _c7gw makes: an admin cluster is the one whose Argo CD root is
# app-of-apps-admin. --ignore-not-found separates "not an admin cluster" from "could not ask".
root="$(kubectl --context "${CONTEXT}" -n argocd get application app-of-apps-admin --ignore-not-found -o name)" \
  || fail "could not read the Argo CD root on ${CONTEXT}"
[[ -n "${root}" ]] || fail "${CONTEXT} is not an admin cluster (no app-of-apps-admin). C7's control there is the
    kagent toolNames allow-list (toggle-mcp-authz-on.sh) and the gateway rule stays 'true', so there is no
    gateway deny to assert."

WORK="$(mktemp -d)"
PF_PID=""
cleanup() { [[ -n "${PF_PID}" ]] && kill "${PF_PID}" 2>/dev/null; rm -rf "${WORK}"; }
trap cleanup EXIT

echo "==> C7 deterministic fallback on ${CONTEXT} (mode: ${MODE})"
echo "==> Port-forwarding agentgateway:3003 (the evil-mcp bind) to ${URL}"
"${KCTL[@]}" port-forward svc/agentgateway "${LOCAL_PORT}:3003" >"${WORK}/port-forward.log" 2>&1 &
PF_PID=$!
for _ in $(seq 1 40); do
  curl -s -o /dev/null --max-time 1 "${URL}" && break
  kill -0 "${PF_PID}" 2>/dev/null || fail "port-forward exited: $(cat "${WORK}/port-forward.log")"
  sleep 0.5
done

post() { # post <out-body> <json> [session-id] ; prints the HTTP status
  local sid_hdr=()
  [[ -n "${3:-}" ]] && sid_hdr=(-H "Mcp-Session-Id: $3" -H "MCP-Protocol-Version: ${PROTOCOL}")
  curl -sS --max-time 20 -D "${WORK}/headers" -o "$1" -w '%{http_code}' -X POST "${URL}" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    ${sid_hdr[@]+"${sid_hdr[@]}"} --data "$2" || true
}

# One MCP session and one tools/call. Prints allow (sentinel back), deny (refused, no sentinel) or unclear
# (neither: an empty reply, a dead session, a 404 for a lost session). Only allow and deny are evidence.
# Refused means a 401/403 or a JSON-RPC error in the reply; the exchange is printed either way, so the
# shape agentgateway answers with is on screen rather than assumed.
call_rogue() {
  local code sid
  code="$(post "${WORK}/init" "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"${PROTOCOL}\",\"capabilities\":{},\"clientInfo\":{\"name\":\"c7-fallback\",\"version\":\"1.0\"}}}")"
  sid="$(grep -i '^mcp-session-id:' "${WORK}/headers" | head -1 | cut -d: -f2- | tr -d ' \r')"
  if [[ "${code}" != 2* || -z "${sid}" ]]; then
    { echo "initialize: HTTP ${code}, no session id"; cat "${WORK}/init"; } > "${WORK}/last"
    echo unclear; return
  fi
  post /dev/null '{"jsonrpc":"2.0","method":"notifications/initialized"}' "${sid}" >/dev/null
  code="$(post "${WORK}/call" "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"${TOOL_NAME}\",\"arguments\":{}}}" "${sid}")"
  { echo "tools/call ${TOOL_NAME}: HTTP ${code}"; cat "${WORK}/call"; echo; } > "${WORK}/last"
  if grep -qF "${SENTINEL}" "${WORK}/call"; then
    echo allow
  elif [[ "${code}" == 401 || "${code}" == 403 ]] || grep -qE '"error"|"isError": *true' "${WORK}/call"; then
    echo deny
  else
    echo unclear
  fi
}

# wait_for <allow|deny> : call until the gateway answers that way, and print how many seconds it took.
wait_for() {
  local start now got
  start="$(date +%s)"
  while :; do
    got="$(call_rogue)"
    now="$(date +%s)"
    if [[ "${got}" == "$1" ]]; then echo "$((now - start))"; return 0; fi
    if (( now - start >= TIMEOUT )); then
      echo "==> still '${got}' after ${TIMEOUT}s, expected '$1'. Last exchange:" >&2
      cat "${WORK}/last" >&2
      return 1
    fi
    sleep 2
  done
}

# The stage's own toggles, run in the terminal pod as the terminal's ServiceAccount.
flip() {
  echo "==> guard-mcp-$1 (in the web terminal)"
  "${KCTL[@]}" exec deploy/web-terminal -c ttyd -- env HOME=/home/student "/home/student/guard-mcp-$1" \
    || fail "guard-mcp-$1 failed in the web terminal"
}

case "${MODE}" in
  allow|deny)
    got="$(call_rogue)"
    cat "${WORK}/last"
    [[ "${got}" == "${MODE}" ]] || fail "expected '${MODE}', the gateway answered '${got}'"
    echo "==> PASS: the gateway answered '${MODE}' for ${TOOL_NAME}" ;;
  both)
    flip off
    allow_s="$(wait_for allow)" || fail "the sentinel never came back with the rule open"
    cat "${WORK}/last"
    echo "==> PASS (open): ${TOOL_NAME} ran and returned the sentinel, ${allow_s}s after guard-mcp-off"
    flip on
    deny_s="$(wait_for deny)" || fail "the gateway never refused ${TOOL_NAME} with the rule narrowed"
    cat "${WORK}/last"
    echo "==> PASS (guarded): the gateway refused ${TOOL_NAME} and no sentinel leaked, ${deny_s}s after guard-mcp-on"
    echo "==> Reload delay on ${CONTEXT}: ${deny_s}s for guard-mcp-on (and ${allow_s}s for guard-mcp-off, which"
    echo "    is 0 when the rule was already open). The guard is left ON." ;;
esac
