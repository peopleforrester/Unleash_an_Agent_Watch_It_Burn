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
# Kube-context safety (see CLAUDE.md): target an explicit context; never the global current-context.
CONTEXT="${CONTEXT:?set CONTEXT to the target kube-context}"
KCTL=(kubectl --context "${CONTEXT}")

echo "==> input classifier (stage 2) -> ${STATE} (runtime, via guard-proxy.${NS}:8080/toggle)" >&2
# exec the guard-proxy to hit its OWN /toggle (localhost): spawns no new pod, so Kyverno
# require-resource-limits (Enforce in R2/R3) cannot reject it. python3 ships in the image.
"${KCTL[@]}" -n "${NS}" exec deploy/guard-proxy -- python3 -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8080/toggle?input_classifier=${STATE}', timeout=10).read().decode())"
