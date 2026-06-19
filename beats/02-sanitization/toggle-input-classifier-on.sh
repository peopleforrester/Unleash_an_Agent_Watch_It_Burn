#!/usr/bin/env bash
# ABOUTME: Beat-2 INPUT guard STAGE 2 (model-based prompt-injection classifier) toggle via guard-proxy.
# ABOUTME: Argo CD-safe runtime flip (no spec change, no restart, counter survives). Enabled progressively
# ABOUTME: AFTER stage 1 (block-list). NOT deterministic; never call the combined guard deterministic. --off disables.
set -euo pipefail

NS="${NS:-agent}"
STATE="on"
case "${1:-}" in
    "")        STATE="on" ;;
    --off)     STATE="off" ;;
    -h|--help) echo "usage: toggle-input-classifier-on.sh [--off]   (NS env overrides namespace, default 'agent')" >&2; exit 0 ;;
    *)         echo "unknown argument: ${1}" >&2; exit 2 ;;
esac

command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found" >&2; exit 1; }

echo "==> input classifier (stage 2) -> ${STATE} (runtime, via guard-proxy.${NS}:8080/toggle)" >&2
kubectl run "guardtoggle-incls-${RANDOM}" --rm -i --restart=Never -n "${NS}" \
  --image=curlimages/curl:8.10.1 --command -- \
  curl -s "http://guard-proxy.${NS}:8080/toggle?input_classifier=${STATE}"
