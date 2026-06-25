#!/usr/bin/env bash
# ABOUTME: Beat-2 INPUT guard STAGE 1 (deterministic block-list) toggle — runtime flip via the guard-proxy /toggle endpoint.
# ABOUTME: Argo CD-safe: changes no managed spec and does not restart the pod, so the cost counter
# ABOUTME: survives and self-heal will not revert it. Pass --off to disable.
set -euo pipefail

NS="${NS:-agent}"
STATE="on"
case "${1:-}" in
    "")        STATE="on" ;;
    --off)     STATE="off" ;;
    -h|--help) echo "usage: toggle-input-guard-on.sh [--off]   (NS env overrides namespace, default 'agent')" >&2; exit 0 ;;
    *)         echo "unknown argument: ${1}" >&2; exit 2 ;;
esac

command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found" >&2; exit 1; }
# Kube-context safety (see CLAUDE.md): target an explicit context; never the global current-context.
CONTEXT="${CONTEXT:?set CONTEXT to the target kube-context}"
KCTL=(kubectl --context "${CONTEXT}")

echo "==> input guard -> ${STATE} (runtime, via guard-proxy.${NS}:8080/toggle)" >&2
"${KCTL[@]}" run "guardtoggle-in-${RANDOM}" --rm -i --restart=Never -n "${NS}" \
  --image=curlimages/curl:8.10.1 --command -- \
  curl -s "http://guard-proxy.${NS}:8080/toggle?input_blocklist=${STATE}"
