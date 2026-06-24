#!/usr/bin/env bash
# ABOUTME: Beat-3 live toggle — applies the agentgateway mcpAuthorization CEL deny rule (mcp-authz-on).
# ABOUTME: Idempotent (kubectl apply). Use --off to apply mcp-authz-off.yaml and remove the deny rule.
set -euo pipefail

# Kube-context safety (see CLAUDE.md): target an explicit context; never the global current-context.
CONTEXT="${CONTEXT:?set CONTEXT to the target kube-context}"
KCTL=(kubectl --context "${CONTEXT}")

# The gateway config files (mcp-authz-on.yaml / mcp-authz-off.yaml) live under agent/gateway/ and
# overlay the agentgateway-config ConfigMap. This toggle only applies them. ON = CEL Deny over
# mcp.tool.name for read_internal_config (+ targets allowlist); OFF = no tool-authz rule ("before").
#
# CANONICAL agentgateway is gitops/ai-layer/agentgateway.yaml (single fixed `agent` namespace). The
# overlay manifests are ATTENDEE_NAMESPACE templates and rewrite the WHOLE config.yaml, so they must
# (1) resolve ATTENDEE_NAMESPACE to the deployed namespace before apply and (2) carry the full
# canonical config (tracing + promptGuard) or they regress those. See the RECONCILIATION headers in
# the manifests; both reconciliations gate on the beat-3 mcpAuthorization-enforcement SPIKE.

STATE="on"
MANIFEST="agent/gateway/mcp-authz-on.yaml"
case "${1:-}" in
  --off) STATE="off"; MANIFEST="agent/gateway/mcp-authz-off.yaml" ;;
  --on|"") STATE="on"; MANIFEST="agent/gateway/mcp-authz-on.yaml" ;;
  -h|--help) echo "Usage: toggle-mcp-authz-on.sh [--on|--off]"; exit 0 ;;
  *) echo "Unknown argument: $1" >&2; echo "Usage: toggle-mcp-authz-on.sh [--on|--off]" >&2; exit 2 ;;
esac

# Resolve the manifest relative to the repo root regardless of where the script is invoked from.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST_PATH="${REPO_ROOT}/${MANIFEST}"

if [[ ! -f "${MANIFEST_PATH}" ]]; then
  echo "==> ERROR: gateway manifest not found: ${MANIFEST_PATH}" >&2
  echo "==> Expected the gateway author to provide it under agent/gateway/." >&2
  exit 1
fi

echo "==> Applying MCP tool authorization state: ${STATE}"
echo "==> Manifest: ${MANIFEST_PATH}"
"${KCTL[@]}" apply -f "${MANIFEST_PATH}"

echo "==> Done. MCP authorization is now '${STATE}'."
echo "==> Verify with: beats/03-bad-mcp-excessive-agency/fallback.curl.sh --expect-$([[ "${STATE}" == on ]] && echo deny || echo allow)"
