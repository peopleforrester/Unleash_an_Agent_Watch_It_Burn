#!/usr/bin/env bash
# ABOUTME: Bootstraps the platform onto the current-context cluster (independent; no hub): ArgoCD + observability.
# ABOUTME: Idempotent (helm upgrade --install + kubectl apply); safe to re-run. Run after `eksctl create`.
set -euo pipefail

# verify-at-build: re-confirm each pin against the project's current stable release and record in
# VERSIONS.lock before the event (research/06-cncf-stack.md §6). Do NOT trust these from memory.
readonly ARGOCD_VERSION="v3.4.3"          # app version; chart resolved via the argo helm repo
readonly KPS_CHART_VERSION="86.2.3"       # kube-prometheus-stack (Grafana + Prometheus)
readonly TEMPO_RELEASE="tempo"            # grafana/tempo single-binary chart for the workshop scale

readonly ARGOCD_NS="argocd"
readonly MONITORING_NS="monitoring"
readonly TEMPO_NS="tempo"

usage() {
    cat >&2 <<'EOF'
Usage: infra/bootstrap.sh

Bootstraps the platform onto the cluster in the current kubectl context (independent cluster, no hub):
  - ArgoCD               (in-cluster GitOps; reconciles THIS cluster from Git)
  - kube-prometheus-stack (Grafana + Prometheus)
  - Grafana Tempo        (in-cluster trace fallback; Datadog is the primary sink)

Idempotent. Re-running upgrades in place. Requires: kubectl, helm, a reachable cluster (current context).
EOF
}

require_tool() {
    local tool="$1"
    command -v "${tool}" >/dev/null 2>&1 || {
        printf 'ERROR: required tool not found: %s\n' "${tool}" >&2
        exit 1
    }
}

add_helm_repos() {
    printf '==> [1/5] Adding/updating Helm repos\n' >&2
    helm repo add argo https://argoproj.github.io/argo-helm >/dev/null
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
    helm repo add grafana https://grafana.github.io/helm-charts >/dev/null
    helm repo update >/dev/null
}

install_argocd() {
    printf '==> [2/5] Installing ArgoCD %s into ns/%s\n' "${ARGOCD_VERSION}" "${ARGOCD_NS}" >&2
    # verify-at-build: pin the chart version that ships app ${ARGOCD_VERSION}; record both in VERSIONS.lock.
    helm upgrade --install argocd argo/argo-cd \
        --namespace "${ARGOCD_NS}" --create-namespace \
        --set "global.image.tag=${ARGOCD_VERSION}" \
        --wait --timeout 10m
}

install_monitoring() {
    printf '==> [3/5] Installing kube-prometheus-stack chart %s into ns/%s\n' \
        "${KPS_CHART_VERSION}" "${MONITORING_NS}" >&2
    helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
        --version "${KPS_CHART_VERSION}" \
        --namespace "${MONITORING_NS}" --create-namespace \
        --wait --timeout 15m
}

install_tempo() {
    printf '==> [4/5] Installing Grafana Tempo (%s) into ns/%s\n' "${TEMPO_RELEASE}" "${TEMPO_NS}" >&2
    # Single-binary Tempo is sufficient for workshop trace volume; receives OTLP from the in-cluster collector.
    helm upgrade --install "${TEMPO_RELEASE}" grafana/tempo \
        --namespace "${TEMPO_NS}" --create-namespace \
        --set "tempo.receivers.otlp.protocols.grpc.endpoint=0.0.0.0:4317" \
        --set "tempo.receivers.otlp.protocols.http.endpoint=0.0.0.0:4318" \
        --wait --timeout 10m
}

report() {
    printf '==> [5/5] Platform ready on this cluster. Endpoints:\n' >&2
    printf '    ArgoCD server (port-forward): kubectl -n %s port-forward svc/argocd-server 8080:443\n' \
        "${ARGOCD_NS}" >&2
    printf '    Grafana       (port-forward): kubectl -n %s port-forward svc/kube-prometheus-stack-grafana 3000:80\n' \
        "${MONITORING_NS}" >&2
    printf '    Tempo OTLP in-cluster:        tempo.%s.svc:4317 (grpc) / :4318 (http)\n' "${TEMPO_NS}" >&2
    printf '\n    Next: kubectl apply -f platform/argocd/appproject-workshop.yaml\n' >&2
    printf '          kubectl apply -f platform/argocd/appset-attendee.yaml\n' >&2
    printf '          then the cluster self-reconciles via its own ArgoCD (see infra/attendee-cluster/README.md).\n' >&2
}

main() {
    if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
        usage
        exit 2
    fi

    require_tool kubectl
    require_tool helm

    printf '==> Verifying the current-context cluster is reachable\n' >&2
    kubectl get nodes >/dev/null || {
        printf 'ERROR: kubectl cannot reach a cluster. Create one first (infra/attendee-cluster/ or infra/test-cluster/).\n' >&2
        exit 1
    }

    add_helm_repos
    install_argocd
    install_monitoring
    install_tempo
    report

    printf '==> Cluster bootstrap complete.\n' >&2
}

main "$@"
