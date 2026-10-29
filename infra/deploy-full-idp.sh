#!/usr/bin/env bash
# ABOUTME: Deploy the full Watch It Burn IDP onto a fresh cluster through the lab-bootstrap root Application.
# ABOUTME: Installs ArgoCD, applies lab-bootstrap (gitops/bootstrap at staging, the profile's values); ArgoCD syncs the rest.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_URL="https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn.git"
# Profile selects which values file of the gitops/bootstrap chart the root reads (#609); lab-platform.yaml lists
# the first four; local-inference is built only from here (#394). Each file's header says what its profile is for.
PROFILE="${1:-full}"
case "${PROFILE}" in
    # full: Cluster 2/3, the guarded instructor clusters.
    full)     VALUES="values-full.yaml" ;;
    # burn: Cluster 1, the community cluster with no guardrails.
    burn)     VALUES="values-burn.yaml" ;;
    # attendee: full platform minus the C1-C3 challenge controls, so the student installs each one
    # themselves (RUN-OF-SHOW-2026-08, #160).
    attendee) VALUES="values-attendee.yaml" ;;
    # admin: the presenters' own cluster. The student build with every guardrail ARMED, so a control can be
    # shown already working rather than staged (#294).
    admin)    VALUES="values-admin.yaml" ;;
    # local-inference: full plus a CPU vLLM behind agentgateway's /local route, for one instructor or demo
    # cluster, never the fleet (#394, question 657).
    local-inference) VALUES="values-local-inference.yaml" ;;
    *)        echo "usage: deploy-full-idp.sh [full|burn|attendee|admin|local-inference]" >&2; exit 2 ;;
esac
[[ -f "${REPO}/gitops/bootstrap/${VALUES}" ]] || { echo "gitops/bootstrap/${VALUES} is missing" >&2; exit 1; }
log() { printf '\n==> %s\n' "$*" >&2; }

log "[1] default gp3 StorageClass"
kubectl apply -f "${REPO}/infra/gp3-storageclass.yaml"

log "[2] ArgoCD (chart 10.8.4 / app v3.5.2)"
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update >/dev/null
# NOTE: do NOT use --wait here. On EKS the helm install with --wait repeatedly hangs in
# pending-install (zero pods, no events, >15min) and times out; installing without --wait completes
# immediately and the pods come up normally. Wait on the core components explicitly afterwards.
# argocd-values.yaml carries dex.enabled=false + the Datadog Agent Autodiscovery annotation on
# argocd-server (PRD #26 M2). Folded in here because ArgoCD is bootstrap-installed, not Application-managed.
helm upgrade --install argocd argo/argo-cd --version 10.8.4 \
  -n argocd --create-namespace --values "${SCRIPT_DIR}/argocd-values.yaml"
log "    waiting for ArgoCD core components..."
kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=180s
kubectl -n argocd rollout status deploy/argocd-repo-server --timeout=180s
kubectl -n argocd rollout status deploy/argocd-server --timeout=180s

# [3] No repository Secret (#609). The repo is public and Argo CD reads it anonymously, as labctl does, so no
# credential is written here; this step used to write the operator's own `gh auth token` into witb-repo on every
# cluster, attendee clusters included. A cluster built before that change still holds it, so it is removed. The
# credential-free ghcr-kagent-oci repository Secret kagent needs is now a template of the gitops/bootstrap chart.
log "[3] no repository credential: remove any witb-repo Secret an earlier build wrote"
kubectl -n argocd delete secret witb-repo --ignore-not-found

log "[3.6] per-cluster secrets, created DIRECTLY in the cluster (no ESO / no Secrets Manager from the"
log "      cluster, no cross-account). The secret exists BEFORE lab-bootstrap, so consumers never"
log "      crash-loop waiting on it. Datadog keys are passed in by the caller (fleet reads the pool on the"
log "      provisioning box); a manual run falls back to the local Secrets Manager if this account can read it."
DD_API_KEY="${WITB_DD_API_KEY:-}"
DD_APP_KEY="${WITB_DD_APP_KEY:-}"
if [[ -z "${DD_API_KEY}" || -z "${DD_APP_KEY}" ]]; then
  _dd="$(aws secretsmanager get-secret-value --secret-id watch-it-burn/datadog \
    --region "${REGION:-us-west-2}" --query SecretString --output text 2>/dev/null || true)"
  if [[ -n "${_dd}" ]]; then
    DD_API_KEY="$(jq -r '."api-key" // empty' <<<"${_dd}")"
    DD_APP_KEY="$(jq -r '."app-key" // empty' <<<"${_dd}")"
  fi
fi
if [[ -n "${DD_API_KEY}" && -n "${DD_APP_KEY}" ]]; then
  for ns in datadog monitoring security; do
    kubectl create namespace "${ns}" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    kubectl -n "${ns}" create secret generic datadog-secret \
      --from-literal=api-key="${DD_API_KEY}" --from-literal=app-key="${DD_APP_KEY}" \
      --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  done
  log "    datadog-secret created in datadog/monitoring/security (datadog agent + falcosidekick read it)"
else
  # A known gap, not a failure (#454, #500): every profile comes up without Datadog. Nothing below reads
  # datadog-secret with a non-optional reference except the Datadog Agent, whose pods wait for it.
  log "    WARN: no Datadog keys (WITB_DD_API_KEY/_APP_KEY unset, no readable local pool secret) — datadog-secret NOT created"
  log "    KNOWN GAP until a Datadog key is loaded: the OTel Collector sends traces to Tempo and metrics to"
  log "      Prometheus only (its datadog-gate init container logs which), falcosidekick runs without its"
  log "      Datadog output (Talon and Prometheus unaffected), and the Datadog Agent does not start."
  log "      To add Datadog later, on this same profile: write datadog-secret (fleet.sh converge, or re-run this"
  log "      with WITB_DD_API_KEY/_APP_KEY) and restart the readers: infra/reload-datadog-consumers.sh <context>."
fi
# Per-cluster identity for Datadog plus, on attendee clusters, the instructor org's keys for
# dual shipping (#242). fleet.sh passes WITB_DD_ADMIN_*; a manual run without them gets identity only.
WITB_DD_API_KEY="${DD_API_KEY}" bash "${SCRIPT_DIR}/datadog-cluster-identity.sh"

# Installed on BOTH profiles, burn included. A load balancer controller is plumbing, not a guardrail:
# The community cluster's premise is that nothing STOPS the agent, not that the cluster has no way to expose a
# Service. While this was gated on "full", the burn console Service sat in <pending> forever, because
# the in-tree service-controller picked it up instead and cannot associate the public subnets on this
# shared, untagged-per-cluster VPC (the same root cause documented on the console Service in
# gitops/ai-layer/resources.yaml). The visible effect was that round1.agenticburn.com never had an
# upstream to route to, so the burn cluster had no reachable console, BurritoBot or terminal at all.
# Observed on watch-it-burn-r1-1, 2026-08-26: `EnsuringLoadBalancer` from service-controller and no
# hostname after 11 minutes, against seconds on the full-profile clusters.
# The IAM side already supported this: the Pod Identity association for
# kube-system/aws-load-balancer-controller is created by Terraform for EVERY cluster
# (infra/terraform/aws/cluster/main.tf), so only the Helm install was missing.
log "[3.5] AWS Load Balancer Controller (NLB for the console Service)"
# Pod Identity supplies the AWS creds (no IMDS needed for auth).
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
  -n kube-system --values "${SCRIPT_DIR}/aws-load-balancer-controller-values.yaml" \
  --set clusterName="${CLUSTER_NAME}" \
  --set region="${REGION}" \
  --set vpcId="${VPC_ID}" \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller
# Non-fatal: the controller reconciles the console Service whenever it is ready; it must NOT gate lab-bootstrap.
kubectl -n kube-system rollout status deploy/aws-load-balancer-controller --timeout=180s \
  || log "WARN: LB controller not ready yet; continuing. The console Service reconciles once it is up."

# [4] One root on every profile, named and shaped like the one labctl creates (lab-platform docs/talk-config.md
# section 5): the gitops/bootstrap chart with this profile's values file and revision=staging, so every child
# follows staging as before. It is not self-managed: nothing the chart renders sources gitops/bootstrap.
# A cluster built before #609 has one of the four old roots instead. Applying lab-bootstrap over it would be the
# two-roots failure of 2026-09-06, two roots over the same children, so the old root is deleted first WITHOUT
# cascading: its resources-finalizer is what makes Argo CD delete the children, so it is stripped before the
# delete, and the children stay for lab-bootstrap to adopt.
log "[4] apply lab-bootstrap (gitops/bootstrap, ${VALUES}, revision staging), ArgoCD deploys the components"
for old in app-of-apps app-of-apps-attendee app-of-apps-burn app-of-apps-admin; do
  if [[ -n "$(kubectl -n argocd get application "${old}" --ignore-not-found -o name)" ]]; then
    log "    replacing the old root ${old}: finalizer removed, deleted without its children"
    kubectl -n argocd patch application "${old}" --type merge -p '{"metadata":{"finalizers":null}}'
    kubectl -n argocd delete application "${old}" --wait=true
  fi
done
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: lab-bootstrap
  namespace: argocd
  labels:
    lab-platform/profile: ${PROFILE}
spec:
  project: default
  source:
    repoURL: ${REPO_URL}
    targetRevision: staging
    path: gitops/bootstrap
    helm:
      valueFiles:
        - ${VALUES}
      parameters:
        - name: revision
          value: staging
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  # Charts such as Kyverno's add finalizers to the Applications the root renders, which git can never match,
  # so the root would report OutOfSync for ever (#265). Ignored, and RespectIgnoreDifferences so a sync does
  # not try to strip them either.
  ignoreDifferences:
    - group: argoproj.io
      kind: Application
      jsonPointers:
        - /metadata/finalizers
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - RespectIgnoreDifferences=true
EOF

log "Deploy issued. Watch sync with: kubectl get applications -n argocd"
log "NOTE: agent Bedrock access is provisioned by Terraform (infra/terraform/aws/cluster) as an EKS Pod"
log "  Identity association for agent:agent-sa, no SA annotation or kubectl step needed. The"
log "  eks-pod-identity-agent addon injects creds via the AWS SDK chain kagent already uses."
