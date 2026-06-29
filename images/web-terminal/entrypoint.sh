#!/bin/bash
# ABOUTME: Wires the student VTT: kubectl from the in-cluster ServiceAccount, the AWS CLI from the
# ABOUTME: student's own keys (optional secret), guardrail toggles, then launches ttyd in /home/student.
set -euo pipefail

SA=/var/run/secrets/kubernetes.io/serviceaccount
export HOME=/home/student
mkdir -p "$HOME/.kube" "$HOME/.aws"

if [ -f "$SA/token" ]; then
  kubectl config set-cluster this \
    --server="https://kubernetes.default.svc" \
    --certificate-authority="$SA/ca.crt" --embed-certs=true >/dev/null
  kubectl config set-credentials me --token="$(cat "$SA/token")" >/dev/null
  kubectl config set-context this --cluster=this --user=me \
    --namespace="$(cat "$SA/namespace")" >/dev/null
  kubectl config use-context this >/dev/null
  echo "kubectl is configured for THIS cluster (namespace: $(cat "$SA/namespace"))." > "$HOME/.motd"
else
  echo "WARNING: no in-cluster ServiceAccount token found; kubectl is not auto-configured." > "$HOME/.motd"
fi

# Pre-configure the AWS CLI with the student's OWN keys (mounted as the optional `student-aws-creds`
# secret -> env). Written as the DEFAULT profile so `aws` works with no --profile inside the VTT. On a
# cluster without the secret, aws is installed but unconfigured; kubectl still works via the SA above.
if [[ -n "${AWS_ACCESS_KEY_ID:-}" && -n "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
  cat > "$HOME/.aws/credentials" <<CREDS
[default]
aws_access_key_id = ${AWS_ACCESS_KEY_ID}
aws_secret_access_key = ${AWS_SECRET_ACCESS_KEY}
CREDS
  cat > "$HOME/.aws/config" <<CFG
[default]
region = ${AWS_DEFAULT_REGION:-us-west-2}
output = json
CFG
  chmod 600 "$HOME/.aws/credentials"
  printf 'aws is configured with your keys (default profile, region %s).\n' "${AWS_DEFAULT_REGION:-us-west-2}" >> "$HOME/.motd"
fi

# Round-3 self-serve guardrail toggles (B5/B11). Each prints PLAIN-LANGUAGE confirmation of what changed
# (not raw JSON) so a student can see what the guard does. Output/input guards flip via the guard-proxy
# /toggle (no new pod, ArgoCD-safe, the cost counter survives). The MCP guard patches the kagent Agent's
# toolNames allow-list; the ai-layer app ignores drift on .spec.declarative.tools so the toggle persists.
#
# _px <query> : hit the guard-proxy /toggle endpoint, swallow the JSON, return its exit code.
cat > "$HOME/.guardlib" <<'EOS'
_px() { kubectl -n agent exec deploy/guard-proxy -- python3 -c \
  "import urllib.request;urllib.request.urlopen('http://localhost:8080/toggle?$1',timeout=10).read()" >/dev/null 2>&1; }
# _evil <json-array> : set ONLY the evil-mcp toolNames (index 1 of the tools array). workshop-mcp
# (index 0, the real BurritoBot tools) is never touched, so the recipe/customer/shell tools survive.
_evil() { kubectl -n agent patch agent workshop-agent --type=json \
  -p "[{\"op\":\"replace\",\"path\":\"/spec/declarative/tools/1/mcpServer/toolNames\",\"value\":$1}]" >/dev/null 2>&1; }
EOS

# Combined: flip EVERY AI guard at once (the "reset and explore" convenience).
cat > "$HOME/guards-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
_px "output=on" && _px "input_blocklist=on&input_classifier=on"
_evil '["get_weather"]'
echo "🛡️  ALL AI guards ON: output scrubbing (C5), input block-list + injection classifier (C6), and MCP"
echo "    tool restriction (C7) are active. Re-run any challenge prompt to watch it get blocked or redacted."
EOS
cat > "$HOME/guards-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
_px "output=off" && _px "input_blocklist=off&input_classifier=off"
_evil '["get_weather","read_internal_config","apply_optimization"]'
echo "🔓 ALL AI guards OFF: the agent is back to wide open. Re-run any challenge prompt to see the weakness."
EOS

# Challenge 5 — OUTPUT guard (scrubs the leaked Bat Spit Amazing Awesome Sauce from replies).
cat > "$HOME/guard-output-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _px "output=on"; then
  echo "🛡️  Challenge 5 — OUTPUT guard ON. The agent's replies are now scanned on the way out: the recipe"
  echo "    amounts, the ogre-toenails ingredient, and the signature are redacted before they reach you."
  echo "    Re-send the recipe prompt; the reply comes back scrubbed (and Datadog shows the guard fired)."
else
  echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guard-output-on' again."
fi
EOS
cat > "$HOME/guard-output-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _px "output=off"; then
  echo "🔓 Challenge 5 — OUTPUT guard OFF. Replies are no longer scrubbed. Re-send the recipe prompt and the"
  echo "    full secret recipe leaks straight through."
else
  echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guard-output-off' again."
fi
EOS

# Challenge 6 — INPUT guards (deterministic block-list + prompt-injection classifier), upstream of the model.
cat > "$HOME/guard-input-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _px "input_blocklist=on&input_classifier=on"; then
  echo "🛡️  Challenge 6 — INPUT guards ON (two stages): (1) a block-list rejects prompts containing"
  echo "    destructive commands or the secret-recipe phrases, and (2) a prompt-injection classifier catches"
  echo "    poisoned instructions. Both run BEFORE the model, so a blocked prompt spends ZERO tokens."
  echo "    Re-send the poisoned ticket; it's rejected upstream and the cost counter does not move."
else
  echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guard-input-on' again."
fi
EOS
cat > "$HOME/guard-input-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _px "input_blocklist=off&input_classifier=off"; then
  echo "🔓 Challenge 6 — INPUT guards OFF. Prompts go straight to the model. Re-send the poisoned ticket and"
  echo "    the injected instructions ride right in (and you pay tokens for it)."
else
  echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guard-input-off' again."
fi
EOS

# Challenge 7 — MCP tool authorization. Narrow the agent's allow-list to drop the rogue evil-mcp tools
# (read_internal_config, apply_optimization); only get_weather stays. workshop-mcp is left fully intact.
cat > "$HOME/guard-mcp-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _evil '["get_weather"]'; then
  echo "🛡️  Challenge 7 — MCP tool authorization ON. The rogue evil-mcp tools (read_internal_config,"
  echo "    apply_optimization) are removed from the agent's allow-list; only get_weather remains. Your real"
  echo "    BurritoBot tools are untouched. Re-ask the weather question: the poisoned description still tries,"
  echo "    but the rogue tool is gone, so the sentinel never appears."
else
  echo "⚠️  Could not patch the agent. Wait a moment and try 'guard-mcp-on' again."
fi
EOS
cat > "$HOME/guard-mcp-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _evil '["get_weather","read_internal_config","apply_optimization"]'; then
  echo "🔓 Challenge 7 — MCP tool authorization OFF. The rogue evil-mcp tools are back in the allow-list."
  echo "    Re-ask the weather question and the agent gets chained into read_internal_config, leaking the"
  echo "    sentinel."
else
  echo "⚠️  Could not patch the agent. Wait a moment and try 'guard-mcp-off' again."
fi
EOS
chmod +x "$HOME/guards-on" "$HOME/guards-off" \
  "$HOME"/guard-output-on "$HOME"/guard-output-off "$HOME"/guard-input-on "$HOME"/guard-input-off \
  "$HOME"/guard-mcp-on "$HOME"/guard-mcp-off

cat > "$HOME/.bashrc" <<'BRC'
cat ~/.motd 2>/dev/null
echo "Welcome to your Watch It Burn cluster shell."
echo "  kubectl is wired to your cluster   (try: kubectl get pods -A)"
echo "  aws is ready with your keys        (try: aws sts get-caller-identity)"
echo "  flip your AI guardrails with       guards-on   guards-off"
cd "$HOME"
export PATH="$HOME:$PATH"
export PS1='\[\e[38;5;208m\]watch-it-burn\[\e[0m\]:\w$ '
BRC

# -W writable (interactive); -b serves under /terminal so the console frontend can proxy it on a subpath.
# Auth/exposure are handled upstream by the per-attendee router; this is the attendee's own cluster.
exec ttyd -p 7681 -W -b /terminal -t fontSize=14 -t 'theme={"background":"#0f1117"}' bash --rcfile "$HOME/.bashrc"
