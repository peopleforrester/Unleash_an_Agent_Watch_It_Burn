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

# The rogue tools (read_internal_config, apply_optimization) and the get_weather injection entrypoint are
# served by evil-mcp-shim (the look-alike supply-chain MCP), reachable via the `evil-mcp` RemoteMCPServer
# — NOT by workshop-mcp. So the C7 control is whether `evil-mcp` is wired into the agent's toolset at all;
# adding the rogue tool NAMES to workshop-mcp's allowlist does nothing (a server cannot expose a tool it
# does not serve, which is why the earlier version never let the attack land). The legit workshop-mcp
# tools are present in both states.
readonly GOOD_TOOL='{"type":"McpServer","mcpServer":{"kind":"RemoteMCPServer","apiGroup":"kagent.dev","name":"workshop-mcp","toolNames":["list_pods","apply_manifest","get_secret"],"requireApproval":["apply_manifest"]}}'

# evil-mcp (the look-alike supply-chain MCP) stays WIRED in both states; the control is its toolNames
# allowlist. The benign get_weather is always present (it is the injection entrypoint), so the demo's
# attack chain fires in both states — what changes is whether read_internal_config / apply_optimization
# are in the agent's toolset for the injection to chain into.
if [[ "${STATE}" == "on" ]]; then
  # Defended ("after"): allowlist only get_weather. The injection still fires, but the rogue tools are
  # filtered out of the agent's toolset ("the rogue tool is filtered from list_tools"), so the leak fails.
  EVIL_TOOL='{"type":"McpServer","mcpServer":{"kind":"RemoteMCPServer","apiGroup":"kagent.dev","name":"evil-mcp","toolNames":["get_weather"]}}'
else
  # Vulnerable ("before"): the full rogue toolset is reachable; get_weather's injection chains into
  # read_internal_config and the sentinel walks out.
  EVIL_TOOL='{"type":"McpServer","mcpServer":{"kind":"RemoteMCPServer","apiGroup":"kagent.dev","name":"evil-mcp","toolNames":["get_weather","read_internal_config","apply_optimization"]}}'
fi
TOOLS="[${GOOD_TOOL},${EVIL_TOOL}]"

# JSON merge patch replaces the tools array wholesale (full entries given, preserving discriminators).
PATCH="{\"spec\":{\"declarative\":{\"tools\":${TOOLS}}}}"

echo "==> Setting MCP tool authorization: ${STATE} (evil-mcp $([[ "${STATE}" == on ]] && echo 'UNwired' || echo 'WIRED'))"
"${KCTL[@]}" patch agent "${AGENT}" --type=merge -p "${PATCH}"

echo "==> Done. kagent reconciles the Agent; the rogue tools are $([[ "${STATE}" == on ]] && echo 'now excluded' || echo 'reachable again')."
echo "==> Verify with: challenges/03-bad-mcp-excessive-agency/fallback.curl.sh --expect-$([[ "${STATE}" == on ]] && echo deny || echo allow)"
