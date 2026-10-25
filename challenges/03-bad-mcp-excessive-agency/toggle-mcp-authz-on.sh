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
#   This is a workshop cluster's C7 control: the kagent toolNames allowlist on the Agent CRD, which kagent
#   enforces when it renders the agent's tool set. The rogue tools are served by evil-mcp, and the `evil-mcp`
#   RemoteMCPServer goes through agentgateway on its own bind, :3003 (gitops/ai-layer/resources.yaml, #514),
#   but on a workshop cluster that bind's mcpAuthorization rule stays 'true', so this patch is what stops them.
#
#   An admin cluster (the KubeCon breakout) uses the gateway rule instead (#496): the web terminal's
#   guard-mcp-on rewrites that bind's CEL rule, the line marked `# c7-rule`, to get_weather and leaves this
#   list full. Running this script there would hide the rogue tools before the gateway saw a call, which is
#   not what the stage shows. The pre-gitops
#   agent/gateway/mcp-authz-* overlays that once held a gateway allowlist were deleted in #479.
#
# Rogue tools (induced by the poisoned MCP description; read_internal_config leaks
# FAKE-MCP-EXFIL-sentinel-4c1d): read_internal_config, apply_optimization.
# Legit tools the good agent needs: the eleven workshop-mcp tools in GOOD_TOOL below.

STATE="on"
case "${1:-}" in
  --off) STATE="off" ;;
  --on|"") STATE="on" ;;
  -h|--help) echo "Usage: ${0##*/} [--on|--off]   (CONTEXT=<kube-context> required; NS=agent AGENT=workshop-agent)"; exit 0 ;;
  *) echo "Unknown argument: $1" >&2; echo "Usage: ${0##*/} [--on|--off]" >&2; exit 2 ;;
esac

# The rogue tools (read_internal_config, apply_optimization) and the get_weather injection entrypoint are
# served by evil-mcp-shim (the look-alike supply-chain MCP), reachable via the `evil-mcp` RemoteMCPServer
# — NOT by workshop-mcp. So this script's control is which evil-mcp tools the agent is given (on an admin
# cluster C7's control is the gateway rule instead, see WHY above); adding the rogue tool NAMES to workshop-mcp's allowlist does nothing (a server cannot expose a tool it
# does not serve, which is why the earlier version never let the attack land). The legit workshop-mcp
# tools are present in both states.
#
# The merge patch REPLACES the tools array, so GOOD_TOOL is the whole committed workshop-mcp entry from
# gitops/ai-layer/resources.yaml, headersFrom included: dropping X-Agent-Identity would turn every later
# tool call into an `unattributed` audit line (#190). verify/test_tool_audit.py keeps the two identical.
readonly GOOD_TOOL='{"type":"McpServer","mcpServer":{"kind":"RemoteMCPServer","apiGroup":"kagent.dev","name":"workshop-mcp","toolNames":["lookup_customer_records","check_inventory","reorder_supply","get_order_history","get_marketing_intel","search_web","post_marketing","get_vault_entry","list_services","deploy_app","run_shell"]},"headersFrom":[{"name":"X-Agent-Identity","value":"workshop-agent"}]}'

# evil-mcp (the look-alike supply-chain MCP) stays WIRED in both states; this script's control is its toolNames
# allowlist, C7's control on a workshop cluster (an admin cluster's is the gateway rule, see WHY). The benign get_weather is always present (it is the injection entrypoint), so the demo's
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
echo "==> Verify by re-asking the weather question once deploy/${AGENT} has rolled out. fallback.curl.sh asks it both ways and puts the list back."
