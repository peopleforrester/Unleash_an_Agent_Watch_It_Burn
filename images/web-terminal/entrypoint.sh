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
  # tokenFile, NOT a baked --token value. EKS mounts a PROJECTED ServiceAccount token: it is short-lived
  # (~1h) and the kubelet rotates the file in place. Copying the token VALUE into the kubeconfig freezes a
  # snapshot that expires ~1h after pod start, after which every kubectl in this terminal fails with
  # "You must be logged in to the server (the server has asked for the client to provide credentials)" and
  # the guard toggles (which shell out to `kubectl exec deploy/guard-proxy`) all report "Could not reach
  # the guard-proxy". A 3-day-old cluster was hours past expiry; a fresh cluster would break ~1h into the
  # workshop. Pointing at tokenFile makes client-go re-read the rotated token on every call, so it never
  # expires while the pod runs. Regression-guarded by verify/test_terminal_kubeconfig.py.
  kubectl config set-credentials me >/dev/null
  kubectl config set "users.me.tokenFile" "$SA/token" >/dev/null
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

# The platform catalogue, with LIVE values (Michael asked for this three times before it existed).
# Prints every service, where it is, and its actual password read from the cluster, so nobody has to dump
# a ConfigMap or grep a Service list to find their own Grafana. Mirrors gitops/ai-layer/web/platform.html.
cat > "$HOME/platform" <<'EOS'
#!/bin/bash
# ABOUTME: print every installed service, how to reach it, and its live credentials.
b(){ printf '\n\033[1;35m%s\033[0m\n' "$1"; }
row(){ printf '  \033[1m%-22s\033[0m %s\n' "$1" "$2"; }
sec(){ kubectl -n "$1" get secret "$2" -o jsonpath="{.data.$3}" 2>/dev/null | base64 -d 2>/dev/null; }

# The in-pod context is literally named "this" (set by this entrypoint), so derive the real cluster name
# from the kubeconfig cluster entry instead of the context name.
_cn="$(kubectl config view -o jsonpath='{.clusters[0].name}' 2>/dev/null | sed 's|.*/||')"
echo "Everything installed on ${_cn:-your cluster}."
echo "Only the console is published; the rest are ClusterIP, so each one shows its port-forward."

b "OPEN IN YOUR BROWSER NOW"
row "BurritoBot"  "this cluster's /  (the app under attack)"
row "Your terminal" "/lab   login: ${TTYD_CREDENTIAL%%:*} / ${TTYD_CREDENTIAL#*:}"
row "Platform page" "/platform  (this list, in the browser)"

b "OBSERVABILITY (port-forward, then open localhost)"
gp="$(sec monitoring prometheus-grafana admin-password)"
row "Grafana" "kubectl -n monitoring port-forward svc/prometheus-grafana 3000:80  -> http://localhost:3000"
row ""        "login: admin / ${gp:-<could not read secret>}"
row "Prometheus" "kubectl -n monitoring port-forward svc/prometheus-kube-prometheus-prometheus 9090:9090"
row "Loki"       "kubectl -n monitoring port-forward svc/loki 3100:3100   (no login)"
row "Tempo"      "kubectl -n monitoring port-forward svc/tempo 3200:3200  (no login)"

b "DELIVERY"
ap="$(sec argocd argocd-initial-admin-secret password)"
row "Argo CD" "kubectl -n argocd port-forward svc/argocd-server 8081:80  -> http://localhost:8081"
row ""        "login: admin / ${ap:-<could not read secret>}"
row "Kyverno" "no UI:  kubectl get clusterpolicy"

b "RUNTIME SECURITY"
row "KubeArmor" "kubectl -n agent get kubearmorpolicy -o yaml     (inline block)"
row "Falco/Talon" "kubectl -n falco logs -l app.kubernetes.io/name=falco --tail=40"
row "NetworkPolicy" "kubectl -n agent get networkpolicy"

b "THE AI LAYER"
row "kagent"      "kubectl -n agent get agent workshop-agent -o yaml"
row "guard-proxy" "guards-status        (your AI guardrails + spend cap)"
row "LLM Guard"   "in-cluster: llm-guard:8000"
row "MCP servers" "kubectl -n agent get pods -l app=workshop-mcp"
echo
echo "Full list with descriptions: open /platform in your browser."
EOS

# Read-only: which AI guards are currently on. The platform tour on the lab page points at this, and a
# student who has flipped several toggles needs a way to see where they actually are without guessing.
cat > "$HOME/guards-status" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
raw="$(kubectl -n agent exec deploy/guard-proxy -- python3 -c \
  "import urllib.request;print(urllib.request.urlopen('http://localhost:8080/guards',timeout=10).read().decode())" 2>/dev/null | tail -1)"
if [ -z "$raw" ]; then
  echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guards-status' again."
  exit 1
fi
echo "Your AI guardrails right now:"
printf '%s' "$raw" | python3 -c '
import json,sys
g=json.load(sys.stdin)
label={"output":"C5 output guard (scrubs secrets on the way out)",
       "input_blocklist":"C6 input block-list (cheap, pre-model)",
       "input_classifier":"C6 injection classifier (model-based)",
       "budget":"C4 spend budget (freezes cost at the cap)"}
for k in ("output","input_blocklist","input_classifier","budget"):
    on=g.get(k)
    print(("  ON   " if on else "  off  ")+label.get(k,k))
'
echo
echo "Flip them with: guard-output-on  guard-input-on  guard-mcp-on  guard-budget-on  (or guards-on / guards-off)"
EOS

# Combined: flip EVERY AI guard at once (the "reset and explore" convenience).
cat > "$HOME/guards-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
_px "output=on" && _px "input_blocklist=on&input_classifier=on" && _px "budget=on"
_evil '["get_weather"]'
echo "🛡️  ALL AI guards ON: output scrubbing (C5), input block-list + injection classifier (C6), MCP tool"
echo "    restriction (C7), and the spend budget (C4). Re-run any challenge to watch it get blocked, redacted,"
echo "    or frozen on cost."
EOS
cat > "$HOME/guards-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
_px "output=off" && _px "input_blocklist=off&input_classifier=off" && _px "budget=off"
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
# Challenge 4 — DENIAL-OF-WALLET. The agent does not have to crash your cluster to hurt you; it can just
# run up the bill. On Round 1 there is no cap and the cost counter on BurritoBot climbs with no ceiling.
# The control is a per-agent budget at the gateway: once this cluster's spend crosses its cap, further
# requests are refused BEFORE the model is called, so a blocked request costs nothing.
cat > "$HOME/guard-budget-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _px "budget=on"; then
  echo "🛡️  Challenge 4 — BUDGET guard ON. This cluster now has a spend cap at the gateway. Keep chatting;"
  echo "    once the tab crosses the cap, BurritoBot refuses further requests BEFORE calling the model, so"
  echo "    the cost counter stops dead and a blocked request costs \$0. The agent is not down; the bill is"
  echo "    capped. That is denial-of-wallet stopped at the platform, not in the app."
else
  echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guard-budget-on' again."
fi
EOS
cat > "$HOME/guard-budget-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _px "budget=off"; then
  echo "🔓 Challenge 4 — BUDGET guard OFF. No spend ceiling. Hammer BurritoBot and watch the cost counter"
  echo "    climb with nothing to stop it. That is the denial-of-wallet: your service is fine, your bill is not."
else
  echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guard-budget-off' again."
fi
EOS
chmod +x "$HOME/platform" "$HOME/guards-status" "$HOME/guards-on" "$HOME/guards-off" \
  "$HOME"/guard-output-on "$HOME"/guard-output-off "$HOME"/guard-input-on "$HOME"/guard-input-off \
  "$HOME"/guard-mcp-on "$HOME"/guard-mcp-off "$HOME"/guard-budget-on "$HOME"/guard-budget-off

cat > "$HOME/.bashrc" <<'BRC'
cat ~/.motd 2>/dev/null
echo "Welcome to your Watch It Burn cluster shell."
echo "  kubectl is wired to your cluster   (try: kubectl get pods -A)"
echo "  aws is ready with your keys        (try: aws sts get-caller-identity)"
echo "  flip your AI guardrails with       guards-on   guards-off"
echo "  see which guards are on           guards-status"
echo "  every service, URL and password    platform"
# Named, not launched. A student who wants an AI CLI types one; a student who does not never sees it.
# The "+" tab opens another terminal if they want one running beside their work.
echo ""
echo "  AI coding CLIs are installed:      claude   gemini   codex   opencode   aider"
echo "  (each needs its own auth/API key; the workshop does not sign you in)"
cd "$HOME"
export PATH="$HOME:$PATH"
export PS1='\[\e[38;5;208m\]watch-it-burn\[\e[0m\]:\w$ '
BRC

# --- Browser IDE and notebook -------------------------------------------------------------------
#
# Both run as background processes beside ttyd, sharing /home/student, so a file written in any surface
# appears in the others immediately. Each gets a restart loop: a crashed IDE must not cost the attendee
# their shell, and a silently dead tab is worse than a restarting one because it reads as a broken lab.
run_service() {
  local name="$1"; shift
  (
    while true; do
      "$@" >>"$HOME/.session/${name}.log" 2>&1
      echo "[$(date -Is)] ${name} exited ($?), restarting in 3s" >>"$HOME/.session/${name}.log"
      sleep 3
    done
  ) &
}
mkdir -p "$HOME/.session" "$HOME/work"

# The console nginx runs in a SEPARATE pod here (it proxies to web-terminal:7681), unlike the sister
# repo where it was a sidecar sharing loopback. So these two have to bind 0.0.0.0 and are reachable
# from anywhere on the pod network, which means "bind to loopback, only nginx can reach it" is NOT
# available as an argument and neither surface may run unauthenticated.
#
# That matters more here than almost anywhere: this cluster deliberately runs hostile workloads. The
# whole exercise is an over-permissioned agent with shell and apply, plus villain images. An IDE with
# --auth none on that pod network is a root shell handed to the thing the workshop is about. So both
# reuse the terminal credential rather than inventing a second one; a credential that has to be
# distributed twice drifts, and one the attendee has already been handed costs nothing extra.
# The `:-` is load-bearing. This script runs under `set -u`, where ${VAR#pattern} on an UNSET variable
# is a hard error, not an empty expansion. Without the default, a cluster whose terminal-auth Secret is
# missing died right here with "TTYD_CREDENTIAL: unbound variable", which crash-looped the pod and made
# every no-credential branch below unreachable, including the warnings written for exactly that case.
# The Secret is declared optional in gitops/ai-layer/resources.yaml, so that path is reachable in
# practice: bootstrap_terminal_auth can fail and log "terminal-auth NOT created".
TTYD_CREDENTIAL="${TTYD_CREDENTIAL:-}"
CRED_PASS="${TTYD_CREDENTIAL#*:}"

if [[ -n "${CRED_PASS}" ]]; then
  PASSWORD="${CRED_PASS}" run_service ide /opt/code-server/bin/code-server \
    --bind-addr 0.0.0.0:8443 \
    --auth password \
    --disable-telemetry \
    --disable-update-check \
    "$HOME/work"
else
  echo "WARNING: no TTYD_CREDENTIAL; starting code-server with auth DISABLED on the pod network." >&2
  run_service ide /opt/code-server/bin/code-server \
    --bind-addr 0.0.0.0:8443 --auth none \
    --disable-telemetry --disable-update-check "$HOME/work"
fi

# JupyterLab. base_url matches the nginx location EXACTLY, because the prefix is KEPT on that route
# (see console.conf); getting it backwards yields a blank tab that still returns HTTP 200. The token is
# the same shared credential. disable_check_xsrf is required because the lab page frames this on a
# different path, and allow_origin is scoped to the console rather than left open.
run_service jupyter /opt/jupyter/bin/jupyter lab \
  --no-browser \
  --ip=0.0.0.0 --port=8888 \
  --ServerApp.base_url=/jupyter \
  --ServerApp.token="${CRED_PASS:-}" \
  --ServerApp.password= \
  --ServerApp.disable_check_xsrf=True \
  --ServerApp.allow_remote_access=True \
  --ServerApp.tornado_settings="{'headers': {'Content-Security-Policy': \"frame-ancestors 'self'\"}}" \
  --ServerApp.root_dir="$HOME/work"

# --- No workshop tutor, deliberately -----------------------------------------------------------
#
# A second ttyd on 7682 used to run the Claude Code CLI as an in-workbench tutor, with a nudge watcher
# and a small HTTP server on 7683 feeding a banner on the lab page.
#
# It is gone because clicking it showed an attendee Claude Code's "Trust this folder?" prompt. The
# suppression it relied on is undocumented per-project config internal to that CLI, so even when
# corrected a future release can bring the prompt back, and it would appear live in front of the room.
# No attendee-facing surface may run a coding-agent CLI or show its UI.
#
# The problem it addressed is real and unsolved: one instructor cannot hand-diagnose a room working at
# its own pace. A replacement must be purpose-built, taking a question and rendering a server-side
# answer, with no terminal and nothing that can raise a dialog. See issue #89.

# -W writable (interactive); -b serves under /terminal so the console frontend can proxy it on a subpath.
#
# The shell is NO LONGER wrapped in script(1). That transcript existed solely so the tutor could read
# what the attendee had typed; with the tutor gone (issue #89) nothing consumes it, and it was recording
# every keystroke of every session, including anything pasted into the shell, to a file on the pod.
# Keeping a verbatim record of what people type, for no reader, is a liability rather than a feature.
#
# AUTHENTICATION. This used to read "auth/exposure are handled upstream by the per-attendee router".
# That was wrong, and it was measured wrong on the sister Packt fleet on 2026-07-25: the cluster NLB
# answers on its BARE IP with no Host header, so anything the router enforces is bypassed by dialling
# the load balancer directly. A router in front of a publicly-reachable upstream is not a control, and
# a non-guessable hostname is not a credential. On 2026-07-23 an attendee reached the instructor's
# cluster through its terminal URL because of exactly this gap.
#
# So the credential is enforced HERE, at ttyd, which is the only place upstream reachability cannot
# route around. TTYD_CREDENTIAL ("user:password") arrives from the optional `terminal-auth` Secret,
# created per-cluster by the provisioning bootstrap with a random password.
if [[ -n "${TTYD_CREDENTIAL:-}" ]]; then
  printf 'This terminal requires the username and password from your cluster hand-out.\n' >> "$HOME/.motd"
  exec ttyd -p 7681 -W -b /terminal -c "${TTYD_CREDENTIAL}" \
    -t fontSize=14 -t 'theme={"background":"#0f1117"}' \
    bash --rcfile "$HOME/.bashrc"
fi

# No credential supplied. Run open so an existing cluster does not break on rollout, but say so loudly
# in the pod log: an unauthenticated terminal on an internet-facing NLB is a shell anyone can open.
echo "WARNING: no TTYD_CREDENTIAL set. This terminal is UNAUTHENTICATED and reachable by anyone who" >&2
echo "WARNING: can reach the load balancer. Create the 'terminal-auth' Secret to close it." >&2
exec ttyd -p 7681 -W -b /terminal -t fontSize=14 -t 'theme={"background":"#0f1117"}' \
  bash --rcfile "$HOME/.bashrc"
