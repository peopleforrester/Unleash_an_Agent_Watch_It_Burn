#!/usr/bin/env bash
# ABOUTME: Deterministic Beat-3 fallback — invokes the rogue read_internal_config tool through
# ABOUTME: agentgateway directly via MCP JSON-RPC, proving the deny rule blocks it model-independently.
set -euo pipefail

# What this proves: the lesson of Beat 3 is the GUARDRAIL, not the model. This script calls the
# rogue MCP tool straight through the gateway's MCP endpoint, with no agent in the loop. With the
# deny rule OFF the sentinel comes back; with it ON the gateway rejects the call. Same before/after
# outcome the live beat shows, but deterministic.
#
# verify-at-build: confirm the exact gateway MCP path, the JSON-RPC method/shape agentgateway's OSS
#   v1.2.1 MCP front expects for a tool call, and how a policy denial is surfaced (HTTP status vs
#   JSON-RPC error). See BUILD-SPIKE.md / research/02-agentgateway.md. The endpoint and parsing below
#   are the documented shape and MUST be reconciled against the live gateway during the spike. [SPIKE]

usage() {
  cat <<'EOF'
Usage: fallback.curl.sh [--expect-allow|--expect-deny]

  --expect-allow   Assert the sentinel IS returned (deny rule OFF / "before" state). Default.
  --expect-deny    Assert the call is blocked and the sentinel is ABSENT (deny rule ON / "after").

Environment:
  GATEWAY_URL   Base URL of agentgateway's MCP endpoint.
                Default: http://localhost:8080/mcp   # verify-at-build
  TOOL_NAME     Rogue tool to invoke. Default: read_internal_config
  SENTINEL      Expected fake value. Default: FAKE-MCP-EXFIL-sentinel-4c1d
EOF
}

EXPECT="allow"
case "${1:-}" in
  --expect-allow|"") EXPECT="allow" ;;
  --expect-deny)     EXPECT="deny" ;;
  -h|--help)         usage; exit 0 ;;
  *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
esac

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8080/mcp}"   # verify-at-build
TOOL_NAME="${TOOL_NAME:-read_internal_config}"
SENTINEL="${SENTINEL:-FAKE-MCP-EXFIL-sentinel-4c1d}"

echo "==> Beat-3 deterministic fallback (mode: expect-${EXPECT})"
echo "==> Gateway MCP endpoint: ${GATEWAY_URL}"
echo "==> Invoking rogue tool '${TOOL_NAME}' directly through the gateway (no agent in the loop)"

# MCP JSON-RPC tools/call payload. Shape per the MCP spec tools/call method. [SPIKE: confirm live]
REQ=$(cat <<JSON
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"${TOOL_NAME}","arguments":{}}}
JSON
)

echo "==> Sending tools/call request..."
HTTP_BODY=$(mktemp)
HTTP_CODE=$(curl -sS -o "${HTTP_BODY}" -w '%{http_code}' \
  -X POST "${GATEWAY_URL}" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data "${REQ}" || true)

echo "==> Gateway responded with HTTP ${HTTP_CODE}"
echo "==> Response body:"
cat "${HTTP_BODY}"
echo

if grep -q "${SENTINEL}" "${HTTP_BODY}"; then
  SAW_SENTINEL="yes"
else
  SAW_SENTINEL="no"
fi
rm -f "${HTTP_BODY}"

echo "==> Sentinel present in response: ${SAW_SENTINEL}"

if [[ "${EXPECT}" == "allow" ]]; then
  if [[ "${SAW_SENTINEL}" == "yes" ]]; then
    echo "==> PASS (before/deny-off): rogue tool returned the sentinel as expected."
    exit 0
  fi
  echo "==> FAIL: expected the sentinel but it was absent. Is the deny rule already on?" >&2
  exit 1
else
  if [[ "${SAW_SENTINEL}" == "no" ]]; then
    echo "==> PASS (after/deny-on): gateway blocked the call; no sentinel leaked."
    exit 0
  fi
  echo "==> FAIL: sentinel leaked despite the deny rule. The control did NOT enforce." >&2
  exit 1
fi
