#!/usr/bin/env bash
# ABOUTME: Beat-2 live toggle — switches the output exfil guard ON via the LLM Guard sidecar.
# ABOUTME: Idempotent (kubectl apply); reverse with the --off flag to restore the open state.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
# Gateway state manifests are authored under agent/gateway/ (separate workstream).
readonly REPO_ROOT="${SCRIPT_DIR}/../.."
readonly ON_MANIFEST="${REPO_ROOT}/agent/gateway/output-guard-on.yaml"
readonly OFF_MANIFEST="${REPO_ROOT}/agent/gateway/output-guard-off.yaml"

usage() {
    cat >&2 <<USAGE
usage: toggle-output-guard-on.sh [--off]

  (no args)  Apply ${ON_MANIFEST#"${REPO_ROOT}/"} — output exfil guard ON
             (LLM Guard sidecar with the output Regex scanner on the response path).
  --off      Apply ${OFF_MANIFEST#"${REPO_ROOT}/"} — output guard OFF (workshop default).

Idempotent: re-running applies the same desired state. Exit 0 success, 1 failure, 2 usage.
USAGE
}

command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found" >&2; exit 1; }

STATE="on"
case "${1:-}" in
    "")        STATE="on" ;;
    --off)     STATE="off" ;;
    -h|--help) usage; exit 0 ;;
    *)         echo "unknown argument: ${1}" >&2; usage; exit 2 ;;
esac

if [[ "${STATE}" == "on" ]]; then
    MANIFEST="${ON_MANIFEST}"
else
    MANIFEST="${OFF_MANIFEST}"
fi

[[ -f "${MANIFEST}" ]] || { echo "manifest not found: ${MANIFEST}" >&2; exit 1; }

echo "==> Setting output exfil guard ${STATE^^}" >&2
echo "    applying: ${MANIFEST}" >&2
kubectl apply -f "${MANIFEST}"
echo "==> Done. Output guard is now ${STATE^^}." >&2
