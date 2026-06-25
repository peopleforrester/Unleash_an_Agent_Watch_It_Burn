#!/usr/bin/env bash
# ABOUTME: Mint a ready-to-use kubeconfig for a collaborator (e.g. Whitney) to bang on a dev cluster.
# ABOUTME: Creates a ServiceAccount + ClusterRoleBinding + long-lived token; no AWS IAM, fully revocable.
#
# WHY a ServiceAccount token (not an IAM user): the collaborator needs to USE the cluster (run the agent,
# attack it, deploy), but the cluster lives in an isolated dev account. A k8s SA token kubeconfig needs
# nothing from AWS IAM, works against the EKS public API endpoint, is time-boxable, and is revoked in one
# command (delete the SA). The handed-out kubeconfig contains ONLY a scoped bearer token + the cluster CA.
#
# USAGE
#   infra/grant-collaborator-kubeconfig.sh <name> <kube-context> [role] [out-file]
#     <name>          collaborator handle, e.g. whitney  (becomes the SA name: collab-<name>)
#     <kube-context>  the cluster's kube-context (must already be in your KUBECONFIG)
#     [role]          cluster-admin (default; full bang-on access) | edit (no RBAC/secret-escalation)
#     [out-file]      where to write the kubeconfig (default: /tmp/<name>-<cluster>.kubeconfig)
#
# REVOKE
#   kubectl --context <ctx> -n collaborators delete sa collab-<name>
#   kubectl --context <ctx> delete clusterrolebinding collab-<name>
#
# The output kubeconfig is a SECRET (a working credential). Hand it to the collaborator over a secure
# channel (1Password). Do NOT commit it. This script never writes the token to the repo.
set -euo pipefail

err() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ $# -ge 2 ]] || err "usage: $0 <name> <kube-context> [role] [out-file]"
NAME="$1"
CTX="$2"
ROLE="${3:-cluster-admin}"
SA="collab-${NAME}"
NS="collaborators"
OUT="${4:-/tmp/${NAME}-$(echo "$CTX" | sed 's#.*/##')-collab.kubeconfig}"

case "$ROLE" in cluster-admin|edit) : ;; *) err "role must be cluster-admin or edit, got: $ROLE" ;; esac
command -v kubectl >/dev/null || err "kubectl not found"

K() { kubectl --context "$CTX" "$@"; }

# Safety: confirm the context resolves to a real cluster before mutating it.
K cluster-info >/dev/null 2>&1 || err "context '$CTX' is not reachable; is it in your KUBECONFIG?"
echo "==> context: $(K config current-context 2>/dev/null || echo "$CTX")" >&2

# 1. Namespace + ServiceAccount.
K create namespace "$NS" --dry-run=client -o yaml | K apply -f - >/dev/null
K -n "$NS" create serviceaccount "$SA" --dry-run=client -o yaml | K apply -f - >/dev/null

# 2. Bind the SA to the chosen ClusterRole.
K create clusterrolebinding "$SA" \
  --clusterrole="$ROLE" --serviceaccount="${NS}:${SA}" \
  --dry-run=client -o yaml | K apply -f - >/dev/null

# 3. Long-lived token Secret for the SA (non-expiring; revoked by deleting the SA/Secret). EKS public
#    endpoint validates this bearer token without any AWS credentials on the collaborator's side.
K -n "$NS" apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${SA}-token
  namespace: ${NS}
  annotations:
    kubernetes.io/service-account.name: ${SA}
type: kubernetes.io/service-account-token
EOF

# Wait for the token controller to populate the Secret.
for _ in $(seq 1 20); do
  TOKEN="$(K -n "$NS" get secret "${SA}-token" -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || true)"
  [[ -n "${TOKEN:-}" ]] && break
  sleep 1
done
[[ -n "${TOKEN:-}" ]] || err "token Secret was not populated in time"

# 4. Cluster server URL + CA (from the SA-token Secret's ca.crt).
SERVER="$(K config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
CA_B64="$(K -n "$NS" get secret "${SA}-token" -o jsonpath='{.data.ca\.crt}')"
CLUSTER_NAME="$(echo "$CTX" | sed 's#.*/##')"

# 5. Emit a self-contained kubeconfig (no exec plugins, no AWS) the collaborator can use directly.
cat > "$OUT" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: ${CLUSTER_NAME}
    cluster:
      server: ${SERVER}
      certificate-authority-data: ${CA_B64}
contexts:
  - name: ${CLUSTER_NAME}-${NAME}
    context:
      cluster: ${CLUSTER_NAME}
      namespace: agent
      user: ${SA}
current-context: ${CLUSTER_NAME}-${NAME}
users:
  - name: ${SA}
    user:
      token: ${TOKEN}
EOF
chmod 600 "$OUT"

echo "==> wrote kubeconfig: ${OUT}" >&2
echo "==> role: ${ROLE}  SA: ${NS}/${SA}  cluster: ${CLUSTER_NAME}" >&2
echo "==> hand it over securely (1Password). Revoke: kubectl --context '${CTX}' -n ${NS} delete sa ${SA} && kubectl --context '${CTX}' delete clusterrolebinding ${SA}" >&2
echo "$OUT"
