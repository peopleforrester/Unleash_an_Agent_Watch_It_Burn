#!/usr/bin/env bash
# ABOUTME: Writes the per-cluster Datadog identity (cluster-identity ConfigMap) and, on attendee and presenter
# ABOUTME: clusters, datadog-admin-secret with the instructor org's keys for dual shipping (#242).
#
# Runs against the cluster in KUBECONFIG. Idempotent, so it can be re-run on a live cluster after the fact
# (infra/reload-datadog-consumers.sh restarts the readers). Called by deploy-full-idp.sh; fleet.sh supplies the
# admin keys for attendee and presenter clusters only. An instructor cluster ships to the instructor org
# already, so it gets the ConfigMap and any stale admin secret is removed, never a second copy of itself.
#
# Env:
#   CLUSTER_NAME             derived from the kube context when unset (arn:...:cluster/<name>)
#   WITB_DD_API_KEY          the cluster's own key; the admin secret is skipped when it equals the admin key
#   WITB_DD_ADMIN_API_KEY    instructor org api key (empty = no dual shipping)
#   WITB_DD_ADMIN_APP_KEY    instructor org app key (lets verify/datadog-orgs.sh resolve the org name)
#   DD_SITE                  default datadoghq.com
set -euo pipefail
log() { printf '    %s\n' "$*" >&2; }

CLUSTER_NAME="${CLUSTER_NAME:-$(kubectl config current-context | sed -E 's#^.*cluster/##')}"
[[ "${CLUSTER_NAME}" == watch-it-burn-* ]] || { echo "cannot derive cluster name (got '${CLUSTER_NAME}'); set CLUSTER_NAME=" >&2; exit 1; }
SITE="${DD_SITE:-datadoghq.com}"
ADMIN_API="${WITB_DD_ADMIN_API_KEY:-}"
ADMIN_APP="${WITB_DD_ADMIN_APP_KEY:-}"
readonly NAMESPACES="datadog monitoring"

for ns in ${NAMESPACES}; do
    kubectl create namespace "${ns}" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    kubectl -n "${ns}" create configmap cluster-identity --from-literal=cluster-name="${CLUSTER_NAME}" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null
done
log "cluster-identity=${CLUSTER_NAME} in ${NAMESPACES// /\/}"

if [[ -z "${ADMIN_API}" || "${ADMIN_API}" == "${WITB_DD_API_KEY:-}" ]]; then
    for ns in ${NAMESPACES}; do
        kubectl -n "${ns}" delete secret datadog-admin-secret --ignore-not-found >/dev/null
    done
    log "no dual shipping on ${CLUSTER_NAME} (no distinct admin key); datadog-admin-secret absent"
    exit 0
fi

# The Agent takes each additional endpoint as a JSON literal in an env var, so the JSON is built here once
# and the CR reads it verbatim. Shapes per docs.datadoghq.com/agent/configuration/dual-shipping (2026-09-05).
metrics_json="$(jq -cn --arg k "${ADMIN_API}" --arg s "${SITE}" '{("https://app."+$s): [$k]}')"
process_json="$(jq -cn --arg k "${ADMIN_API}" --arg s "${SITE}" '{("https://process."+$s): [$k]}')"
orch_json="$(jq -cn --arg k "${ADMIN_API}" --arg s "${SITE}" '{("https://orchestrator."+$s): [$k]}')"
logs_json="$(jq -cn --arg k "${ADMIN_API}" --arg s "${SITE}" '[{api_key: $k, Host: ("agent-http-intake.logs."+$s), Port: 443, is_reliable: true}]')"
for ns in ${NAMESPACES}; do
    kubectl -n "${ns}" create secret generic datadog-admin-secret \
        --from-literal=api-key="${ADMIN_API}" \
        --from-literal=app-key="${ADMIN_APP}" \
        --from-literal=additional-endpoints="${metrics_json}" \
        --from-literal=process-additional-endpoints="${process_json}" \
        --from-literal=orchestrator-additional-endpoints="${orch_json}" \
        --from-literal=logs-additional-endpoints="${logs_json}" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null
done
log "datadog-admin-secret in ${NAMESPACES// /\/}: ${CLUSTER_NAME} dual-ships to the instructor org"
