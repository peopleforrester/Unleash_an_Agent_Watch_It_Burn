#!/usr/bin/env bash
# ABOUTME: Installs the per-cluster IDP stack on the single test EKS cluster.
# ABOUTME: Idempotent (helm upgrade --install); test-friendly values (ephemeral storage).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat >&2 <<'EOF'
Usage: bootstrap-test.sh
Installs ArgoCD, Kyverno, Falco, and kube-prometheus-stack onto the cluster in the
current kubectl context. Prints the resolved chart/app versions for VERSIONS.lock.
EOF
    exit 2
}
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage

log() { printf '==> %s\n' "$*" >&2; }

require() { command -v "$1" >/dev/null 2>&1 || { echo "missing tool: $1" >&2; exit 1; }; }
require helm
require kubectl

log "Target context: $(kubectl config current-context)"

log "Adding/refreshing helm repos"
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null
helm repo add kyverno https://kyverno.github.io/kyverno >/dev/null
helm repo add falcosecurity https://falcosecurity.github.io/charts >/dev/null
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo update >/dev/null

# verify-at-build: charts install repo-latest here; the resolved versions are printed
# at the end and must be pinned back into VERSIONS.lock.

log "Installing ArgoCD (namespace argocd)"
helm upgrade --install argocd argo/argo-cd \
    --namespace argocd --create-namespace \
    --set dex.enabled=false \
    --wait --timeout 10m

log "Installing Kyverno (namespace kyverno)"
helm upgrade --install kyverno kyverno/kyverno \
    --namespace kyverno --create-namespace \
    --wait --timeout 10m

log "Installing Falco (namespace falco; modern eBPF)"
helm upgrade --install falco falcosecurity/falco \
    --namespace falco --create-namespace \
    --set driver.kind=modern_ebpf \
    --wait --timeout 10m

log "Installing kube-prometheus-stack (namespace monitoring; ephemeral storage)"
helm upgrade --install kps prometheus-community/kube-prometheus-stack \
    --namespace monitoring --create-namespace \
    --set grafana.persistence.enabled=false \
    --set prometheus.prometheusSpec.retention=2h \
    --wait --timeout 15m

log "Resolved versions (pin these into VERSIONS.lock):"
helm list -A -o json | python3 -c '
import json,sys
for r in json.load(sys.stdin):
    print(f"  {r[\"name\"]:10} chart={r[\"chart\"]:30} app={r.get(\"app_version\",\"?\")}")
' >&2

log "Bootstrap complete."
