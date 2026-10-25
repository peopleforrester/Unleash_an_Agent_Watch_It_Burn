#!/usr/bin/env bash
# ABOUTME: One-command roster-cluster setup: bootstrap an already-provisioned community or admin cluster
# ABOUTME: with the profile its role gets, and arm it. The role, profile and account come from fleet.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"
FLEET="${REPO}/infra/terraform/fleet/fleet.sh"
readonly SCRIPT_DIR REPO FLEET

usage() {
    cat >&2 <<EOF
Usage: ${0##*/} <roster-cluster-name> [aws-profile]

Bootstraps an ALREADY-PROVISIONED roster cluster (infra/terraform/fleet/roster.tsv) the way its role says:
  watch-it-burn-community        community role, burn profile: no guardrails at all (attackme, the
                                 cluster the whole room attacks).
  watch-it-burn-<owner>-admin    admin role, admin profile: the student build with every guardrail
                                 ARMED. Kyverno is flipped to Deny here; NetworkPolicy/Falco/PID come up
                                 enforcing from the admin app-of-apps. The AI guards stay OFF to flip live.

The role is read from the cluster's NAME by fleet.sh (role_of_instructor_name), and the profile and the
default account from the role (bootstrap_profile_for_role, account_for_role), so this script cannot
disagree with the fleet about what a cluster is. An attendee cluster is not set up here.

'fleet.sh instructors up [role|owner]' provisions, bootstraps and arms in one step and is the usual path.
This script is for a cluster provisioned bare (WIB_NO_BOOTSTRAP=1) or one whose bootstrap failed.
Region from REGION (default us-west-2).

Kube-context safety: uses an isolated kubeconfig and an explicit context; never the global current-context.
EOF
    exit 2
}

# Ask fleet.sh, in a subshell so its globals cannot collide with ours. Fails loudly if it cannot be
# loaded: a local copy of the naming rule is the drift this script exists to avoid.
fleet_q() {
    ( cd "$(dirname "${FLEET}")" && bash -c 'source "$1" >/dev/null 2>&1 || true; shift
        declare -F "$1" >/dev/null || { echo "FATAL: could not load $1 from fleet.sh" >&2; exit 3; }
        "$@"' _ "${FLEET}" "$@" )
}

[[ $# -ge 1 && $# -le 2 ]] || usage
NAME="$1"; REGION="${REGION:-us-west-2}"
[[ "${NAME}" == watch-it-burn-* ]] || { echo "refusing non-watch-it-burn name: ${NAME}" >&2; exit 1; }
ROLE="$(fleet_q role_of_instructor_name "${NAME}")"
[[ -n "${ROLE}" ]] || { echo "refusing ${NAME}: not a roster cluster (community or <owner>-admin)" >&2; usage; }
BOOT="$(fleet_q bootstrap_profile_for_role "${ROLE}")"
PROFILE="${2:-$(fleet_q account_for_role "${ROLE}")}"
# This script used to take a round number second. A bare number now would be read as the AWS profile, so
# say what changed instead of failing later inside aws with a profile named "2".
[[ ! "${PROFILE}" =~ ^[0-9]+$ ]] || {
    echo "refusing aws-profile '${PROFILE}': rounds are gone; the role comes from the cluster name (#560)" >&2; usage; }

KCFG="$(mktemp -t "${NAME}.kubeconfig.XXXX")"
trap 'rm -f "${KCFG}"' EXIT
log() { printf '\n==> %s\n' "$*" >&2; }

log "[1] isolated kubeconfig for ${NAME} (${PROFILE}/${REGION})"
AWS_PROFILE="${PROFILE}" aws eks update-kubeconfig --kubeconfig "${KCFG}" --name "${NAME}" --region "${REGION}" >/dev/null
CONTEXT="$(KUBECONFIG="${KCFG}" kubectl config current-context)"
log "    context: ${CONTEXT}"

log "[2] bootstrap IDP with the '${BOOT}' profile (${ROLE} cluster)"
KUBECONFIG="${KCFG}" AWS_PROFILE="${PROFILE}" bash "${REPO}/infra/deploy-full-idp.sh" "${BOOT}"

if [[ "${ROLE}" == "community" ]]; then
    log "Community cluster ready: ${NAME} has NO guardrails. Point the room at it and let it burn."
    exit 0
fi

# Admin: wait for ArgoCD to materialize the controls, then flip Kyverno to Deny. NetworkPolicy egress,
# Falco/Talon, and the PID limit come up enforcing from the admin app-of-apps (no runtime toggle).
log "[3] wait for the Kyverno policy to sync, then set Deny"
for i in $(seq 1 40); do
    if KUBECONFIG="${KCFG}" AWS_PROFILE="${PROFILE}" kubectl --context "${CONTEXT}" \
        get validatingpolicy require-resource-limits >/dev/null 2>&1; then break; fi
    [[ "${i}" -eq 40 ]] && { echo "timed out waiting for Kyverno policy sync" >&2; exit 1; }
    sleep 15
done
CONTEXT="${CONTEXT}" KUBECONFIG="${KCFG}" AWS_PROFILE="${PROFILE}" \
    bash "${REPO}/challenges/01-cncf-wall/toggle-kyverno-enforce.sh"

log "Admin cluster ready: ${NAME} has its infra guardrails armed; the AI guards are deployed but OFF. Flip them live with:"
log "  CONTEXT=${CONTEXT} challenges/02-sanitization/toggle-output-guard-on.sh   (output first)"
log "  CONTEXT=${CONTEXT} challenges/02-sanitization/toggle-input-guard-on.sh     (then input)"
log "  CONTEXT=${CONTEXT} challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh  (then MCP)"
