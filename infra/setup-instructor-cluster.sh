#!/usr/bin/env bash
# ABOUTME: One-command instructor-cluster setup: bootstrap an already-provisioned cluster and set its
# ABOUTME: round toggle state. R1=burn (no guardrails), R2=full+infra enforcing, R3=full+infra on, AI off.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly SCRIPT_DIR REPO

usage() {
    cat >&2 <<EOF
Usage: ${0##*/} <cluster-name> <round 1|2|3> [aws-profile]

Bootstraps an ALREADY-PROVISIONED instructor cluster and sets its round's toggle state:
  Round 1  burn profile  — no production guardrails (the spectacle cluster).
  Round 2  full profile  — infra guardrails enforcing (Kyverno Enforce; NetworkPolicy/Falco/PID
                           come up enforcing from the full app-of-apps).
  Round 3  full profile  — infra on (same as R2); AI guards deployed but OFF for the attendee/instructor
                           to flip live (output -> input -> MCP).

Provision the cluster first:  infra/terraform/fleet/fleet.sh instructors up <round>
Profile defaults to accen-dev; region from REGION (default us-west-2).

Kube-context safety: uses an isolated kubeconfig and an explicit context; never the global current-context.
EOF
    exit 2
}

[[ $# -ge 2 ]] || usage
NAME="$1"; ROUND="$2"; PROFILE="${3:-accen-dev}"; REGION="${REGION:-us-west-2}"
case "${ROUND}" in 1) BOOT=burn ;; 2|3) BOOT=full ;; *) echo "round must be 1|2|3" >&2; usage ;; esac
[[ "${NAME}" == watch-it-burn-* ]] || { echo "refusing non-watch-it-burn name: ${NAME}" >&2; exit 1; }

KCFG="$(mktemp -t "${NAME}.kubeconfig.XXXX")"
trap 'rm -f "${KCFG}"' EXIT
log() { printf '\n==> %s\n' "$*" >&2; }

log "[1] isolated kubeconfig for ${NAME} (${PROFILE}/${REGION})"
AWS_PROFILE="${PROFILE}" aws eks update-kubeconfig --kubeconfig "${KCFG}" --name "${NAME}" --region "${REGION}" >/dev/null
CONTEXT="$(KUBECONFIG="${KCFG}" kubectl config current-context)"
log "    context: ${CONTEXT}"

log "[2] bootstrap IDP with the '${BOOT}' profile (Round ${ROUND})"
KUBECONFIG="${KCFG}" AWS_PROFILE="${PROFILE}" bash "${REPO}/infra/deploy-full-idp.sh" "${BOOT}"

if [[ "${ROUND}" == "1" ]]; then
    log "Round 1 ready: ${NAME} has NO production guardrails. Point the room at it and let it burn."
    exit 0
fi

# Round 2/3: wait for ArgoCD to materialize the controls, then flip Kyverno to Enforce. NetworkPolicy
# egress, Falco/Talon, and the PID limit come up enforcing from the full app-of-apps (no runtime toggle).
log "[3] wait for the Kyverno policy to sync, then set Enforce"
for i in $(seq 1 40); do
    if KUBECONFIG="${KCFG}" AWS_PROFILE="${PROFILE}" kubectl --context "${CONTEXT}" \
        get clusterpolicy require-resource-limits >/dev/null 2>&1; then break; fi
    [[ "${i}" -eq 40 ]] && { echo "timed out waiting for Kyverno policy sync" >&2; exit 1; }
    sleep 15
done
CONTEXT="${CONTEXT}" KUBECONFIG="${KCFG}" AWS_PROFILE="${PROFILE}" \
    bash "${REPO}/challenges/01-cncf-wall/toggle-kyverno-enforce.sh"

if [[ "${ROUND}" == "2" ]]; then
    log "Round 2 ready: ${NAME} has infra guardrails enforcing. Same attacks now get walled."
else
    # All clusters run the workshop-default model (Sonnet 4.6, set in gitops/ai-layer/resources.yaml).
    # The old per-cluster Bedrock model-tier pin (haiku/opus on the cost-race clusters) was dropped when
    # the fleet standardized on Sonnet; every R3 cluster is now the identical full build, no model patch.
    log "Round 3 ready: ${NAME} has infra on; AI guards are deployed but OFF. Flip them live with:"
    log "  CONTEXT=${CONTEXT} challenges/02-sanitization/toggle-output-guard-on.sh   (output first)"
    log "  CONTEXT=${CONTEXT} challenges/02-sanitization/toggle-input-guard-on.sh     (then input)"
    log "  CONTEXT=${CONTEXT} challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh  (then MCP)"
fi
