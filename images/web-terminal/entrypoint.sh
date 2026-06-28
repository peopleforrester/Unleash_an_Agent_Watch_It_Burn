#!/bin/bash
# ABOUTME: Builds a kubeconfig from the pod's in-cluster ServiceAccount so kubectl "just works" in the
# ABOUTME: browser terminal, then launches ttyd. The shell opens already scoped to the attendee's cluster.
set -euo pipefail

SA=/var/run/secrets/kubernetes.io/serviceaccount
export HOME=/home/term
mkdir -p "$HOME/.kube"

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

# Round-3 self-serve guardrail toggles (B5/B11): one command to flip the AI guards on the attendee's own
# cluster. They hit the guard-proxy /toggle via exec (no new pod, ArgoCD-safe, the cost counter survives).
cat > "$HOME/guards-on" <<'EOS'
#!/bin/bash
kubectl -n agent exec deploy/guard-proxy -- python3 -c \
  "import urllib.request;print(urllib.request.urlopen('http://localhost:8080/toggle?input=on&output=on',timeout=10).read().decode())"
EOS
cat > "$HOME/guards-off" <<'EOS'
#!/bin/bash
kubectl -n agent exec deploy/guard-proxy -- python3 -c \
  "import urllib.request;print(urllib.request.urlopen('http://localhost:8080/toggle?input=off&output=off',timeout=10).read().decode())"
EOS
chmod +x "$HOME/guards-on" "$HOME/guards-off"

cat > "$HOME/.bashrc" <<'BRC'
cat ~/.motd 2>/dev/null
echo "Welcome to your Watch It Burn cluster shell. Try: kubectl get pods -A"
echo "Round 3: flip your AI guardrails with  guards-on  and  guards-off"
export PATH="$HOME:$PATH"
export PS1='\[\e[38;5;208m\]watch-it-burn\[\e[0m\]:\w$ '
BRC

# -W writable (interactive); -b serves under /terminal so the console frontend can proxy it on a subpath.
# Auth/exposure are handled upstream by the per-attendee router; this is the attendee's own cluster.
exec ttyd -p 7681 -W -b /terminal -t fontSize=14 -t 'theme={"background":"#0f1117"}' bash --rcfile "$HOME/.bashrc"
