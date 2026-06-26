#!/usr/bin/env bash
# ABOUTME: Recreate every OTel-auto-instrumented app pod that was admitted WITHOUT the OpenTelemetry
# ABOUTME: Operator's SDK injection, so it gets instrumented and actually exports spans/metrics.
#
# Why this exists: the OTel Operator injects the Python SDK + OTEL_EXPORTER_OTLP_ENDPOINT into pods that
# carry `instrumentation.opentelemetry.io/inject-python`, via a MUTATING WEBHOOK that fires at pod-create.
# If an app pod is created before that webhook is ready (a cold cluster bootstrap races the Operator),
# the pod is admitted with NO init container and NO OTLP endpoint, so it emits ZERO telemetry, silently.
# On 2026-06-26 every whitney cluster's guard-proxy + workshop-agent were in this state, which is why
# Datadog showed no spans/metrics. Recreating the pods once the webhook is ready fixes it; this script
# does exactly that, idempotently (it only touches pods annotated-but-not-injected).
#
# Kube-context safety: context is REQUIRED and explicit; AWS_PROFILE is per command; pod-DELETE (not a
# spec mutation) so the `block-argocd-drift` Kyverno guardrail does not reject it.
#
# Usage:
#   infra/reinstrument-app-pods.sh <kube-context> [aws-profile] [namespace]
set -euo pipefail

CONTEXT="${1:?usage: reinstrument-app-pods.sh <kube-context> [aws-profile] [namespace]}"
PROFILE="${2:-accen-dev}"
NS="${3:-agent}"
kc(){ AWS_PROFILE="$PROFILE" kubectl --context "$CONTEXT" "$@"; }

kc version --request-timeout=10s >/dev/null 2>&1 || { echo "ERROR: context '$CONTEXT' unreachable; refusing to proceed" >&2; exit 2; }

mapfile -t PODS < <(kc -n "$NS" get pods -o json 2>/dev/null | python3 -c "
import sys, json
for p in json.load(sys.stdin).get('items', []):
    ann = p['metadata'].get('annotations', {}) or {}
    init = [c['name'] for c in p['spec'].get('initContainers', []) or []]
    annotated = any(k.startswith('instrumentation.opentelemetry.io/inject') for k in ann)
    injected  = any('auto-instrumentation' in n for n in init)
    if annotated and not injected:
        print(p['metadata']['name'])
")

if [ "${#PODS[@]}" -eq 0 ]; then
  echo "[reinstrument] $CONTEXT ns/$NS: all OTel-annotated app pods are already injected; nothing to do"
  exit 0
fi

echo "[reinstrument] $CONTEXT ns/$NS: recreating un-instrumented pods: ${PODS[*]}"
kc -n "$NS" delete pod "${PODS[@]}"
echo "[reinstrument] done; the controllers recreate them WITH the OTel SDK injected (webhook is ready now)"
