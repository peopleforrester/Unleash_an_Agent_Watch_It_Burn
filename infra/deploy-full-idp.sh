#!/usr/bin/env bash
# ABOUTME: Deploy the full Watch It Burn IDP onto a fresh cluster via the ArgoCD app-of-apps.
# ABOUTME: Installs ArgoCD, registers the (private) repo + ghcr OCI, applies app-of-apps; ArgoCD syncs the rest.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_URL="https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn.git"
# Profile selects which root app-of-apps to apply: "full" (Cluster 2/3) or "burn" (Cluster 1).
PROFILE="${1:-full}"
case "${PROFILE}" in
    full) ROOT_APP="gitops/bootstrap/app-of-apps.yaml" ;;
    burn) ROOT_APP="gitops/bootstrap/app-of-apps-burn.yaml" ;;
    *)    echo "usage: deploy-full-idp.sh [full|burn]" >&2; exit 2 ;;
esac
log() { printf '\n==> %s\n' "$*" >&2; }

log "[1] default gp3 StorageClass"
kubectl apply -f "${REPO}/infra/gp3-storageclass.yaml"

log "[2] ArgoCD (pinned chart 9.5.21 / app v3.4.3)"
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update >/dev/null
helm upgrade --install argocd argo/argo-cd --version 9.6.0 \
  -n argocd --create-namespace --set dex.enabled=false --wait --timeout 10m

log "[3] register the private repo (token from gh) + ghcr OCI helm for kagent"
GH_TOKEN="$(gh auth token)"
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: witb-repo
  namespace: argocd
  labels: { argocd.argoproj.io/secret-type: repository }
stringData:
  type: git
  url: ${REPO_URL}
  username: peopleforrester
  password: ${GH_TOKEN}
---
apiVersion: v1
kind: Secret
metadata:
  name: ghcr-kagent-oci
  namespace: argocd
  labels: { argocd.argoproj.io/secret-type: repository }
stringData:
  type: helm
  name: kagent-oci
  url: ghcr.io/kagent-dev/kagent/helm
  enableOCI: "true"
EOF

log "[4] apply the ${PROFILE} app-of-apps (${ROOT_APP}, targetRevision: staging), ArgoCD deploys the components"
kubectl apply -f "${REPO}/${ROOT_APP}"

log "Deploy issued. Watch sync with: kubectl get applications -n argocd"
log "NOTE: agent Bedrock access is provisioned by Terraform (infra/terraform/cluster) as an EKS Pod"
log "  Identity association for agent:agent-sa, no SA annotation or kubectl step needed. The"
log "  eks-pod-identity-agent addon injects creds via the AWS SDK chain kagent already uses."
