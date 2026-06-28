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
