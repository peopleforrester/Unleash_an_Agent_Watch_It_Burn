#!/usr/bin/env bash
# ABOUTME: Force-sync the datadog-secret ExternalSecret and restart every workload that consumes it, so a
# ABOUTME: rotated Datadog API key in AWS Secrets Manager actually takes effect on a running cluster.
#
# Why this exists: the Datadog API key reaches each cluster as `datadog-secret` (ESO syncs it from
# Secrets Manager). The OTel Collector (the PRIMARY trace/metric sink), the Datadog Agent, and
# falcosidekick all read it as an ENV VAR, which is fixed at pod start. When the key rotates, ESO updates
# the in-cluster secret but the running pods keep the OLD key and silently stop exporting (the Collector
# ran ~6h on an expired key on 2026-06-26, dropping all telemetry, until restarted). There is no
# in-cluster auto-reloader, so this restart MUST happen as part of every key rotation. Run this after any
# `watch-it-burn/datadog*` rotation, for each affected cluster.
#
# Kube-context safety (per repo CLAUDE.md): the target context is REQUIRED and explicit; AWS_PROFILE is
# passed per command; nothing relies on the ambient current-context.
#
# Usage:
#   infra/reload-datadog-consumers.sh <kube-context> [aws-profile]
set -euo pipefail

CONTEXT="${1:?usage: reload-datadog-consumers.sh <kube-context> [aws-profile]}"
PROFILE="${2:-accen-dev}"

kc() { AWS_PROFILE="$PROFILE" kubectl --context "$CONTEXT" "$@"; }

# Fail loudly if the context is not reachable, rather than acting on the wrong/ambient cluster.
kc version --request-timeout=10s >/dev/null 2>&1 || { echo "ERROR: context '$CONTEXT' unreachable; refusing to proceed" >&2; exit 2; }

TS="$(date +%s)"
echo "[reload-datadog-consumers] context=$CONTEXT profile=$PROFILE"

# 1. Force ESO to re-pull the rotated key immediately (otherwise it waits for refreshInterval).
for ns in datadog monitoring security; do
  kc -n "$ns" annotate externalsecret datadog-secret "force-sync=$TS" --overwrite >/dev/null 2>&1 \
    && echo "  force-synced datadog-secret in $ns" || echo "  (no datadog-secret ExternalSecret in $ns)"
done
sleep 5

# 2. Restart every consumer so it re-reads the env var from the freshly-synced secret.
#
# We DELETE PODS rather than `rollout restart`. Restart patches the workload spec, which the workshop's
# own `block-argocd-drift` Kyverno policy rejects ("managed by ArgoCD; change it in Git, not the cluster").
# Deleting a pod is not a mutation of the ArgoCD-tracked Deployment/DaemonSet, so the controller simply
# recreates the pod (reading the fresh secret) and the guardrail does not fire. Works for all consumers.
kc -n datadog    delete pod -l agent.datadoghq.com/component=agent          --ignore-not-found 2>&1 | sed 's/^/  datadog-agent: /'   || true
kc -n datadog    delete pod -l agent.datadoghq.com/component=cluster-agent  --ignore-not-found 2>&1 | sed 's/^/  cluster-agent: /'   || true
kc -n monitoring delete pod -l app.kubernetes.io/name=opentelemetry-collector --ignore-not-found 2>&1 | sed 's/^/  collector: /'      || true
kc -n security   delete pod -l app.kubernetes.io/name=falcosidekick         --ignore-not-found 2>&1 | sed 's/^/  falcosidekick: /'   || true

echo "[reload-datadog-consumers] done for $CONTEXT"
