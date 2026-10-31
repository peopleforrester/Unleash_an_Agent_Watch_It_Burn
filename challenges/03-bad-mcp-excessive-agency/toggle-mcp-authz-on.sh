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
# Legit tools the good agent needs: workshop-mcp's, which this script never writes (its toolNames stay as the cluster has them).

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
# evil-mcp (the look-alike supply-chain MCP) stays WIRED in both states; this script's control is its toolNames
# allowlist, C7's control on a workshop cluster (an admin cluster's is the gateway rule, see WHY). The benign get_weather is always present (it is the injection entrypoint), so the demo's
# attack chain fires in both states — what changes is whether read_internal_config / apply_optimization
# are in the agent's toolset for the injection to chain into.
if [[ "${STATE}" == "on" ]]; then
  # Defended ("after"): allowlist only get_weather. The injection still fires, but the rogue tools are
  # filtered out of the agent's toolset ("the rogue tool is filtered from list_tools"), so the leak fails.
  EVIL_TOOLS='["get_weather"]'
else
  # Vulnerable ("before"): the full rogue toolset is reachable; get_weather's injection chains into
  # read_internal_config and the sentinel walks out.
  EVIL_TOOLS='["get_weather","read_internal_config","apply_optimization"]'
fi

# Only evil-mcp's toolNames is written, found by name on the live Agent and never by its place in the tools array
# (#708). The patch tests that entry's name before it replaces the list, so a reorder of the tools in
# gitops/workshop-agent/agent.yaml, or one between this read and the patch, fails the patch instead of narrowing
# workshop-mcp. workshop-mcp's entry, headersFrom included, is left exactly as the cluster holds it, so this
# script carries no copy of it to keep equal to git. PATCH_PY is the web terminal's .evilpatch.py, which
# verify/test_evil_tools_by_name.py holds identical.
read -r -d '' PATCH_PY <<'PY' || true
import json, sys
tools = json.load(sys.stdin)["spec"]["declarative"]["tools"]
hits = [i for i, t in enumerate(tools) if (t.get("mcpServer") or {}).get("name") == "evil-mcp"]
names = json.loads(sys.argv[1]) if len(sys.argv) == 2 else None
if len(hits) != 1 or not isinstance(names, list) or not all(isinstance(n, str) for n in names):
    sys.exit(1)
entry = "/spec/declarative/tools/%d/mcpServer" % hits[0]
print(json.dumps([
    {"op": "test", "path": entry + "/name", "value": "evil-mcp"},
    {"op": "replace", "path": entry + "/toolNames", "value": names},
]))
PY
command -v python3 >/dev/null 2>&1 || { echo "python3 not found on PATH" >&2; exit 1; }
PATCH="$("${KCTL[@]}" get agent "${AGENT}" -o json | python3 -c "${PATCH_PY}" "${EVIL_TOOLS}")" || {
  echo "ERROR: could not read ${AGENT}, or it has no single tools entry whose mcpServer.name is evil-mcp; nothing was patched" >&2
  exit 1; }

echo "==> Setting MCP tool authorization: ${STATE} (evil-mcp $([[ "${STATE}" == on ]] && echo 'UNwired' || echo 'WIRED'))"
"${KCTL[@]}" patch agent "${AGENT}" --type=json -p "${PATCH}"

echo "==> Done. kagent reconciles the Agent; the rogue tools are $([[ "${STATE}" == on ]] && echo 'now excluded' || echo 'reachable again')."
echo "==> Verify by re-asking the weather question once deploy/${AGENT} has rolled out. fallback.curl.sh asks it both ways and puts the list back."
