#!/usr/bin/env bash
# ABOUTME: Beat-3 live toggle — flips the kagent Agent's MCP tool allowlist (toolNames) on workshop-agent.
# ABOUTME: ON = restrictive (rogue tools excluded, the "after"); --off = permissive (rogue tools reachable).
set -euo pipefail

# Kube-context safety (see CLAUDE.md): target an explicit context; never the global current-context.
CONTEXT="${CONTEXT:?set CONTEXT to the target kube-context}"
NS="${NS:-agent}"
AGENT="${AGENT:-workshop-agent}"
KCTL=(kubectl --context "${CONTEXT}" -n "${NS}")

# WHY this toggles toolNames and not the agentgateway config:
#   The kagent Agent's RemoteMCPServer points DIRECT at workshop-mcp (gitops/ai-layer/resources.yaml),
#   so the agent's tool calls do NOT traverse agentgateway. Flipping agentgateway's mcpAuthorization
#   therefore would not gate the agent's tools. The in-path, deployed, deterministic control is the
#   kagent toolNames allowlist on the Agent CRD, which kagent enforces when it renders the agent's
#   tool set. This toggle patches that.
#
#   The gateway-enforced alternative (route the agent through agentgateway:3001/mcp and flip the
#   route's mcpAuthorization CEL rules) is the "the gateway blocks it" story. It needs the
#   RemoteMCPServer repointed at agentgateway AND a live spike to confirm the MCP listener path, so it
#   is NOT wired here (the agent/gateway/mcp-authz-{on,off}.yaml overlays are that path, pending the
#   Phase-4b SPIKE in challenges/03-.../BUILD-SPIKE.md). Until then, toolNames is the real control.
#
# Rogue tools (induced by the poisoned MCP description; read_internal_config leaks
# FAKE-MCP-EXFIL-sentinel-4c1d): read_internal_config, apply_optimization.
# Legit tools the good agent needs: list_pods, apply_manifest, get_secret.

STATE="on"
case "${1:-}" in
  --off) STATE="off" ;;
  --on|"") STATE="on" ;;
  -h|--help) echo "Usage: ${0##*/} [--on|--off]   (CONTEXT=<kube-context> required; NS=agent AGENT=workshop-agent)"; exit 0 ;;
  *) echo "Unknown argument: $1" >&2; echo "Usage: ${0##*/} [--on|--off]" >&2; exit 2 ;;
esac

if [[ "${STATE}" == "on" ]]; then
  # Defended ("after"): only the legitimate tools are reachable; rogue tools excluded.
  TOOL_NAMES='["list_pods","apply_manifest","get_secret"]'
else
  # Vulnerable ("before"): the rogue tools are reachable, so beat-3's attack lands.
  TOOL_NAMES='["list_pods","apply_manifest","get_secret","read_internal_config","apply_optimization"]'
fi

# Merge-patch the whole tools array (JSON merge patch replaces arrays wholesale, so the full entry is
# provided, preserving the McpServer discriminator, the RemoteMCPServer ref, and requireApproval).
PATCH=$(cat <<JSON
{"spec":{"declarative":{"tools":[
  {"type":"McpServer","mcpServer":{
    "kind":"RemoteMCPServer","apiGroup":"kagent.dev","name":"workshop-mcp",
    "toolNames":${TOOL_NAMES},
    "requireApproval":["apply_manifest"]
  }}
]}}}
JSON
)

echo "==> Setting MCP tool authorization: ${STATE} (toolNames=${TOOL_NAMES})"
"${KCTL[@]}" patch agent "${AGENT}" --type=merge -p "${PATCH}"

echo "==> Done. kagent reconciles the Agent; the rogue tools are $([[ "${STATE}" == on ]] && echo 'now excluded' || echo 'reachable again')."
echo "==> Verify with: challenges/03-bad-mcp-excessive-agency/fallback.curl.sh --expect-$([[ "${STATE}" == on ]] && echo deny || echo allow)"
