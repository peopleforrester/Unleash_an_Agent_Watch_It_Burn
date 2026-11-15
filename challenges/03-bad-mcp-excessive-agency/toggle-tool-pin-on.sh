#!/usr/bin/env bash
# ABOUTME: C7 rug-pull's pin (#1469): repoints evil-mcp's RemoteMCPServer spec.url at agentgateway :3004, where the
# ABOUTME: tool-pin processor strips any tool whose definition changed since approval; --off puts it back on :3003.
set -euo pipefail

# Kube-context safety (see CLAUDE.md): target an explicit context; never the global current-context.
CONTEXT="${CONTEXT:?set CONTEXT to the target kube-context}"
NS="${NS:-agent}"
KCTL=(kubectl --context "${CONTEXT}" -n "${NS}")

# The two binds evil-mcp can dial. :3003 is the committed url (gitops/ai-layer/resources.yaml), served by the
# agentgateway-c7 container with no pin. :3004 is the pinned bind in agentgateway-config (gitops/ai-layer/agentgateway.yaml),
# evil-mcp behind the tool-pin processor (gitops/ai-layer/tool-pin.yaml) in strip mode.
readonly UNPINNED_URL="http://agentgateway.agent:3003/mcp"
readonly PINNED_URL="http://agentgateway.agent:3004/mcp"

# WHY this is the student's whole action:
#   The allow-list (toggle-mcp-authz-on.sh) keys on the tool NAME, and the rug pull (toggle-rugpull-mutation-on.sh)
#   keeps the name and changes only get_weather's description. The pin keys on the definition: tool-pin hashes each
#   tool's {name, description, inputSchema} and drops one whose hash is not in tool-pin-baseline, which pins get_weather
#   from its approved, benign description. The bind, the processor and the baseline all stay in GitOps; the student
#   changes this one url field, and gitops/bootstrap/apps/ai-layer.yaml ignores only that field, so selfHeal keeps it.
#   kagent rolls workshop-agent by itself when the url changes (measured on watch-it-burn-community, 2026-11-05), so
#   no restart is needed here.
#
#   failClosed: while evil-mcp dials :3004, a tool-pin that is down refuses evil-mcp's tools/list, and on kagent 0.10.1
#   that fails the whole chat answer. So --on waits for tool-pin to be Ready before it repoints, and --off is the way
#   back from an outage.

STATE="on"
case "${1:-}" in
  --off) STATE="off" ;;
  --on|"") STATE="on" ;;
  -h|--help)
    echo "Usage: ${0##*/} [--on|--off]   (CONTEXT=<kube-context> required; NS=agent)"
    echo "  --on  (default): pin evil-mcp: its url becomes ${PINNED_URL} (tool-pin, strip mode)"
    echo "  --off          : unpin: its url goes back to ${UNPINNED_URL}, the committed value"
    exit 0 ;;
  *) echo "Unknown argument: $1" >&2; echo "Usage: ${0##*/} [--on|--off]" >&2; exit 2 ;;
esac

if [[ "${STATE}" == "on" ]]; then
  URL="${PINNED_URL}"
  # A url on :3004 with tool-pin not Ready is a chat outage (failClosed), so check what the pin needs first.
  "${KCTL[@]}" get service agentgateway -o jsonpath='{.spec.ports[*].port}' | grep -qw 3004 \
    || { echo "agentgateway on ${CONTEXT} has no :3004 port; this cluster predates #1469, not pinning" >&2; exit 1; }
  "${KCTL[@]}" get configmap tool-pin-baseline >/dev/null \
    || { echo "no tool-pin-baseline ConfigMap on ${CONTEXT}; not pinning" >&2; exit 1; }
  echo "==> Waiting for tool-pin to be Ready"
  "${KCTL[@]}" rollout status deployment/tool-pin --timeout=120s
else
  URL="${UNPINNED_URL}"
fi

echo "==> Setting C7 tool pin: ${STATE} (evil-mcp url = ${URL})"
"${KCTL[@]}" patch remotemcpserver evil-mcp --type merge -p "{\"spec\":{\"url\":\"${URL}\"}}"

echo "==> Done. evil-mcp now dials ${URL}; kagent re-lists its tools within 60 s and rolls workshop-agent itself."
if [[ "${STATE}" == "on" ]]; then
  echo "    A get_weather whose description changed since approval is stripped from the list (tool-pin logs \"changed\")."
fi
