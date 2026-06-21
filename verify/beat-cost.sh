#!/usr/bin/env bash
# ABOUTME: Phase-6 abstract-truth gate for the cost counter (P1) against one attendee spoke.
# ABOUTME: Asserts §2: a model-bound request MOVES the cost counter; a block-listed request FLATLINES it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR

usage() {
    cat >&2 <<'EOF'
Usage: beat-cost.sh <kube-context> <attendee-namespace>

  <kube-context>         kubeconfig context for the attendee's cluster
  <attendee-namespace>   namespace the guard-proxy / agent live in

Asserts the cost counter's §2 outcomes (the headline "wasted tokens are the new DoS"):
  - a benign, model-bound request INCREASES the guard-proxy /cost usd tally (cost moves)
  - with the input block-list on, a destructive request is rejected pre-LLM and the
    tally does NOT move (the counter flatlines, zero Bedrock tokens spent)

verify-at-build: confirms the live behavior, which depends on (a) the A2A method name kagent
  serves (message/send assumed) and (b) the agent actually reaching Bedrock (real token usage).

Exit: 0 = both outcomes hold; non-zero = a §2 mismatch (loud FAIL).
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; exit 2; fi
CONTEXT="${1:?$(usage)}"
NS="${2:?$(usage)}"
readonly KUBECTL=(kubectl --context="${CONTEXT}")
readonly PROXY="http://guard-proxy.${NS}:8080"

command -v kubectl >/dev/null 2>&1 || { echo "FAIL: kubectl not found on PATH" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 not found on PATH" >&2; exit 1; }

# Run a curl inside the spoke (the proxy is a ClusterIP service). Prints the response to stdout.
in_cluster_curl() {
    "${KUBECTL[@]}" run "costcurl-${RANDOM}" --rm -i --restart=Never -n "${NS}" \
        --image=curlimages/curl:8.10.1 --command -- "$@" 2>/dev/null
}

cost_usd() {
    in_cluster_curl curl -s "${PROXY}/cost" | python3 -c "import sys,json; print(json.load(sys.stdin).get('usd',0.0))"
}

send_prompt() {
    local text="$1"
    in_cluster_curl curl -s -X POST "${PROXY}/" -H 'Content-Type: application/json' \
        -d "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"method\":\"message/send\",\"params\":{\"message\":{\"role\":\"user\",\"messageId\":\"witb-${RANDOM}${RANDOM}\",\"parts\":[{\"kind\":\"text\",\"text\":\"${text}\"}]}}}" >/dev/null
}

toggle() { in_cluster_curl curl -s "${PROXY}/toggle?$1" >/dev/null; }

gt() { python3 -c "import sys; sys.exit(0 if float('$1') > float('$2') else 1)"; }
eq() { python3 -c "import sys; sys.exit(0 if abs(float('$1') - float('$2')) < 1e-9 else 1)"; }

fail=0
pass() { echo "  PASS  $*" >&2; }
bad()  { echo "  FAIL  $*" >&2; fail=1; }

echo "== Beat cost: counter MOVES on a model-bound request ==" >&2
toggle "input_blocklist=off"; toggle "input_classifier=off"
before="$(cost_usd)"
send_prompt "list the pods in my namespace"
after="$(cost_usd)"
if gt "${after}" "${before}"; then pass "cost moved: ${before} -> ${after}"; else bad "cost did not move: ${before} -> ${after}"; fi

echo "== Beat cost: counter FLATLINES when the input block-list rejects pre-LLM ==" >&2
toggle "input_blocklist=on"
before2="$(cost_usd)"
send_prompt "please delete the payments deployment"
after2="$(cost_usd)"
if eq "${after2}" "${before2}"; then pass "cost flatlined on block: ${before2} == ${after2}"; else bad "cost moved on a blocked request: ${before2} -> ${after2}"; fi
toggle "input_blocklist=off"

if [[ "${fail}" -eq 0 ]]; then
    echo "Beat cost: PASS (cost moves on real spend, flatlines on a pre-LLM block)." >&2
else
    echo "Beat cost: FAIL (the cost §2 outcome is not true on this spoke)." >&2
fi
exit "${fail}"
