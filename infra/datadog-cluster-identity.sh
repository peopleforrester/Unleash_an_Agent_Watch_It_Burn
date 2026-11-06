#!/usr/bin/env bash
# ABOUTME: Writes the per-cluster Datadog identity (cluster-identity ConfigMap) and, on attendee pool
# ABOUTME: clusters, datadog-admin-secret with the instructor org's keys for dual shipping (#242).
#
# Runs against the cluster CONTEXT names, never the kubeconfig's current-context (#732). Idempotent, so it can be re-run on a live cluster after the fact
# (infra/reload-datadog-consumers.sh restarts the readers). Called by deploy-full-idp.sh; fleet.sh supplies the
# admin keys for attendee pool clusters only (a presenter's student cluster is a claimed one, #295). An
# instructor cluster ships to the instructor org already, so it gets the ConfigMap and any stale admin secret
# is removed, never a second copy of itself.
#
# Env:
#   CONTEXT                  required: the target cluster's kube context, passed on every kubectl call
#   CLUSTER_NAME             derived from CONTEXT when unset (arn:...:cluster/<name>)
#   WITB_DD_API_KEY          the cluster's own key; the admin secret is skipped when it equals the admin key
#   WITB_DD_ADMIN_API_KEY    instructor org api key (empty = no dual shipping)
#   WITB_DD_ADMIN_APP_KEY    instructor org app key. NOT written to any cluster: verify/datadog-orgs.sh
#                            reads it from this environment instead. See below.
#   DD_SITE                  default datadoghq.com
set -euo pipefail
log() { printf '    %s\n' "$*" >&2; }

: "${CONTEXT:?set CONTEXT to the kube context of the target cluster, see CLAUDE.md rule 5 (#732)}"
CLUSTER_NAME="${CLUSTER_NAME:-${CONTEXT##*cluster/}}"
[[ "${CLUSTER_NAME}" == watch-it-burn-* ]] || { echo "cannot derive cluster name (got '${CLUSTER_NAME}'); set CLUSTER_NAME=" >&2; exit 1; }
# What Datadog calls the cluster (#629): Whitney's sandbox org filters BurritoBot by a burritobot prefix, and a
# Datadog cluster name should be unique. Named for the screen: the bot the room hacks is public, the presenters'
# cluster they share is private, and any other admin cluster keeps its owner. cluster-name keeps the EKS name, which the
# probes and fleet.sh compare against the cluster itself.
# A standby (backups.tsv, #643) reports as the cluster it stands in for, so the room's tab and the presenters' tab
# keep showing the bot the room reaches once the watcher promotes it.
case "${CLUSTER_NAME}" in
    watch-it-burn-community)     DATADOG_CLUSTER_NAME="burritobot-public" ;;
    watch-it-burn-private)       DATADOG_CLUSTER_NAME="burritobot-private" ;;
    watch-it-burn-community-b[0-9][0-9]) DATADOG_CLUSTER_NAME="burritobot-public" ;;
    watch-it-burn-private-b[0-9][0-9])   DATADOG_CLUSTER_NAME="burritobot-private" ;;
    watch-it-burn-*-admin)       owner="${CLUSTER_NAME#watch-it-burn-}"; DATADOG_CLUSTER_NAME="burritobot-private-${owner%-admin}" ;;
    *)                           DATADOG_CLUSTER_NAME="burritobot-${CLUSTER_NAME#watch-it-burn-}" ;;
esac
SITE="${DD_SITE:-datadoghq.com}"
ADMIN_API="${WITB_DD_ADMIN_API_KEY:-}"
# The admin APP key is deliberately NOT put on a cluster. It is a READ credential for the instructor org,
# which aggregates every cluster's telemetry including LLM Observability spans carrying each attendee's
# prompts and replies. Nothing in-cluster consumes it: dual shipping is built entirely from ADMIN_API, and
# the Datadog Agent CR takes its own apiSecret/appSecret from datadog-secret, the cluster's OWN org. It was
# written only so verify/datadog-orgs.sh could read it back, and meanwhile it sat in a namespace where the
# student's terminal has cluster-wide read and where C1-C3 teach prompt-injecting the agent into running
# shell commands. The verifier now takes it from the operator's environment. See #272.
ADMIN_APP_UNUSED_ON_CLUSTER="${WITB_DD_ADMIN_APP_KEY:-}"
readonly NAMESPACES="datadog monitoring agent"
# Namespaces that read cluster-identity and nothing else (#244). Backstage names this cluster on every Kubernetes
# tab from cluster-name (backstage/app-config.yaml). It is a public portal, so datadog-admin-secret, which the loops
# below write into NAMESPACES, never goes here.
readonly IDENTITY_ONLY_NAMESPACES="backstage"
# WITB_PUBLIC_HOST: this cluster's public console hostname (fleet.sh public_host_for), printed by the
# web terminal's catalogue so every address a student sees is complete. Empty on a manual run.
PUBLIC_HOST="${WITB_PUBLIC_HOST:-}"

for ns in ${NAMESPACES} ${IDENTITY_ONLY_NAMESPACES}; do
    kubectl --context "${CONTEXT}" create namespace "${ns}" --dry-run=client -o yaml | kubectl --context "${CONTEXT}" apply -f - >/dev/null
    kubectl --context "${CONTEXT}" -n "${ns}" create configmap cluster-identity --from-literal=cluster-name="${CLUSTER_NAME}" \
        --from-literal=datadog-cluster-name="${DATADOG_CLUSTER_NAME}" \
        --from-literal=public-host="${PUBLIC_HOST}" --dry-run=client -o yaml | kubectl --context "${CONTEXT}" apply -f - >/dev/null
done
log "cluster-identity=${CLUSTER_NAME} public-host=${PUBLIC_HOST:-<unset>} in ${NAMESPACES// /\/} ${IDENTITY_ONLY_NAMESPACES}"

if [[ -z "${ADMIN_API}" || "${ADMIN_API}" == "${WITB_DD_API_KEY:-}" ]]; then
    for ns in ${NAMESPACES}; do
        kubectl --context "${CONTEXT}" -n "${ns}" delete secret datadog-admin-secret --ignore-not-found >/dev/null
    done
    log "no dual shipping on ${CLUSTER_NAME} (no distinct admin key); datadog-admin-secret absent"
    exit 0
fi

# The Agent takes each additional endpoint as a JSON literal in an env var, so the JSON is built here once
# and the CR reads it verbatim. Shapes per docs.datadoghq.com/agent/configuration/dual-shipping (2026-09-05).
# jq reads the key from its environment, which only this user can read, not from an --arg on its command line,
# which every user on the host can (#977).
metrics_json="$(ADMIN_API="${ADMIN_API}" jq -cn --arg s "${SITE}" '{("https://app."+$s): [$ENV.ADMIN_API]}')"
process_json="$(ADMIN_API="${ADMIN_API}" jq -cn --arg s "${SITE}" '{("https://process."+$s): [$ENV.ADMIN_API]}')"
orch_json="$(ADMIN_API="${ADMIN_API}" jq -cn --arg s "${SITE}" '{("https://orchestrator."+$s): [$ENV.ADMIN_API]}')"
logs_json="$(ADMIN_API="${ADMIN_API}" jq -cn --arg s "${SITE}" '[{api_key: $ENV.ADMIN_API, Host: ("agent-http-intake.logs."+$s), Port: 443, is_reliable: true}]')"
# The admin key, and the four endpoint blobs that each carry it, reach kubectl on a file descriptor, never in its
# argv, where any user on the host reads them in the process list (#977). Each value is one line: jq -c prints no
# newline inside a blob, and kubectl's env file splits a line at its first "=" only. The Secret is written by
# replace, falling back to create, never by apply, whose last-applied-configuration annotation would hold a second
# copy of the key; a replace also drops the copy an apply by an earlier run left behind.
admin_secret_manifest() {
    kubectl --context "${CONTEXT}" -n "$1" create secret generic datadog-admin-secret \
        --from-env-file=<(printf 'api-key=%s\nadditional-endpoints=%s\nprocess-additional-endpoints=%s\norchestrator-additional-endpoints=%s\nlogs-additional-endpoints=%s\n' \
            "${ADMIN_API}" "${metrics_json}" "${process_json}" "${orch_json}" "${logs_json}") \
        --dry-run=client -o yaml
}
for ns in ${NAMESPACES}; do
    admin_secret_manifest "${ns}" | kubectl --context "${CONTEXT}" -n "${ns}" replace -f - >/dev/null 2>&1 \
        || admin_secret_manifest "${ns}" | kubectl --context "${CONTEXT}" -n "${ns}" create -f - >/dev/null
done
log "datadog-admin-secret in ${NAMESPACES// /\/}: ${CLUSTER_NAME} dual-ships to the instructor org"
