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

log "[2] ArgoCD (chart 9.6.0 / app v3.4.4)"
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update >/dev/null
# NOTE: do NOT use --wait here. On EKS the helm install with --wait repeatedly hangs in
# pending-install (zero pods, no events, >15min) and times out; installing without --wait completes
# immediately and the pods come up normally. Wait on the core components explicitly afterwards.
# argocd-values.yaml carries dex.enabled=false + the Datadog Agent Autodiscovery annotation on
# argocd-server (PRD #26 M2). Folded in here because ArgoCD is bootstrap-installed, not Application-managed.
helm upgrade --install argocd argo/argo-cd --version 9.6.0 \
  -n argocd --create-namespace --values "${SCRIPT_DIR}/argocd-values.yaml"
log "    waiting for ArgoCD core components..."
kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=180s
kubectl -n argocd rollout status deploy/argocd-repo-server --timeout=180s
kubectl -n argocd rollout status deploy/argocd-server --timeout=180s

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

if [[ "${PROFILE}" == "full" ]]; then
  log "[3.5] AWS Load Balancer Controller (NLB for the console Service, ALB for the party Ingresses)"
  # IAM is an EKS Pod Identity association created by Terraform for kube-system/aws-load-balancer-controller
  # (infra/terraform/cluster/main.tf); Pod Identity supplies the AWS creds (no IMDS needed for auth).
  # clusterName/region/vpcId are passed EXPLICITLY: the controller otherwise auto-discovers vpcId from
  # IMDS, which the pod cannot reach on these nodes (IMDS hop limit), so it CrashLoops with "failed to
  # fetch VPC ID from instance metadata" (found live 2026-06-26). Deriving them via the EKS API avoids
  # IMDS entirely. chart 1.14.0 = controller v2.14.x (the Service+Ingress line; v3.x is Gateway API).
  REGION="${REGION:-us-west-2}"
  CLUSTER_NAME="${CLUSTER_NAME:-$(kubectl config current-context | sed -E 's#^.*cluster/##')}"
  [[ "${CLUSTER_NAME}" == watch-it-burn-* ]] || { echo "could not derive cluster name from context (got '${CLUSTER_NAME}'); set CLUSTER_NAME=" >&2; exit 1; }
  VPC_ID="$(aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${REGION}" --query 'cluster.resourcesVpcConfig.vpcId' --output text)"
  [[ "${VPC_ID}" == vpc-* ]] || { echo "could not derive vpcId for ${CLUSTER_NAME} (got '${VPC_ID}')" >&2; exit 1; }
  helm repo add eks https://aws.github.io/eks-charts >/dev/null 2>&1 || true
  helm repo update >/dev/null
  helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller --version 1.14.0 \
    -n kube-system \
    --set clusterName="${CLUSTER_NAME}" \
    --set region="${REGION}" \
    --set vpcId="${VPC_ID}" \
    --set serviceAccount.create=true \
    --set serviceAccount.name=aws-load-balancer-controller
  # Non-fatal: the controller reconciles Ingresses whenever it is ready; it must NOT gate the app-of-apps.
  kubectl -n kube-system rollout status deploy/aws-load-balancer-controller --timeout=180s \
    || log "WARN: LB controller not ready yet; continuing. Ingresses reconcile once it is up."
fi

log "[4] apply the ${PROFILE} app-of-apps (${ROOT_APP}, targetRevision: staging), ArgoCD deploys the components"
kubectl apply -f "${REPO}/${ROOT_APP}"

log "Deploy issued. Watch sync with: kubectl get applications -n argocd"
log "NOTE: agent Bedrock access is provisioned by Terraform (infra/terraform/cluster) as an EKS Pod"
log "  Identity association for agent:agent-sa, no SA annotation or kubectl step needed. The"
log "  eks-pod-identity-agent addon injects creds via the AWS SDK chain kagent already uses."
