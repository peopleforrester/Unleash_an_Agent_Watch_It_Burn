#!/usr/bin/env bash
# ABOUTME: One live E2E session (#461): builds a test attendee cluster for the run only, gives it a one-row Datadog pool
# ABOUTME: from the sandbox key, runs run-e2e.sh on it, then always tears the cluster down and puts the pool back.
#
# Usage: E2E_PROFILE=accen-dev E2E_REGION=us-west-2 IAM_PIPELINE_PROFILE=<aws-profile> IAM_PIPELINE_REGION=<region> \
#            [E2E_LOG=<file>] bash verify/live-e2e-session.sh
#
# Why a pool row (question 926, decisions.md): there is no per-attendee Datadog org pool since Datadog stopped issuing
# per-student orgs, and fleet.sh refuses to bootstrap an attendee cluster whose pool row does not resolve, so a real
# workshop never mixes students' telemetry. The session writes watch-it-burn/datadog-pool as one row carrying the
# keys in watch-it-burn/datadog (Whitney's sandbox org, #629). The cluster reports as burritobot-attendee-001
# (infra/datadog-cluster-identity.sh), and with the same key as the instructor org it does not dual-ship.
#
# In order:
#   1. Refuses if watch-it-burn-attendee-001 already exists: this session tears down only what it built.
#   2. Saves watch-it-burn/datadog-pool's value, if there is one, to a mode-700 work directory, then writes the row.
#   3. `fleet.sh up watch-it-burn-attendee-001` with WIB_NO_INGEST=1, so the cluster never enters lab-platform's
#      handout pool where an attendee could claim it. The module default size, 1 x t3.2xlarge, in the lab VPC.
#   4. Pulls an isolated kubeconfig, checks its context is that cluster, and runs run-e2e.sh against it.
#   5. On every exit, a failure or Ctrl-C included: `WIB_APPLY=1 fleet.sh down` the cluster, checks EKS no longer
#      lists it, and puts the pool back (the saved value, or no secret if there was none).
# Exits with run-e2e.sh's status, or non-zero when any step or the teardown failed. A cluster still up or a pool not
# restored is printed last, with what to run.
#
# The profile and region are never taken from the environment's defaults (CLAUDE.md, Kube-context safety, rule 6).
# test_datadog_sandbox_live.py, one of the `# SUITE: e2e` checks, reads the two KubeCon clusters, not this one: drive
# one /chat on each within the hour before the run, as its docstring says, or its failure says nothing about this one.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# WIB_FLEET_SH and WIB_RUN_E2E: the shim test's seams (verify/test_live_e2e_session.sh).
FLEET="${WIB_FLEET_SH:-${HERE}/../infra/terraform/fleet/fleet.sh}"
RUN_E2E="${WIB_RUN_E2E:-${HERE}/run-e2e.sh}"
# shellcheck source=../infra/terraform/fleet/event.sh
. "${HERE}/../infra/terraform/fleet/event.sh"

log() { printf '[live-e2e] %s\n' "$*" >&2; }

missing=()
[[ -n "${E2E_PROFILE:-}" ]] || missing+=("E2E_PROFILE must name the AWS profile of the fleet's default account (accen-dev)")
[[ -n "${E2E_REGION:-}" ]] || missing+=("E2E_REGION must name the fleet's region (us-west-2)")
[[ -n "${IAM_PIPELINE_PROFILE:-}" && -n "${IAM_PIPELINE_REGION:-}" ]] \
    || missing+=("IAM_PIPELINE_PROFILE and IAM_PIPELINE_REGION are run-e2e.sh's; set them here so the cluster is not built for a run that cannot start")
for tool in aws jq kubectl; do
    command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool} is not on PATH")
done
if [[ "${#missing[@]}" -gt 0 ]]; then
    printf 'LIVE E2E SESSION CANNOT START; nothing was built:\n' >&2
    printf '  - %s\n' "${missing[@]}" >&2
    exit 1
fi

readonly PROFILE="${E2E_PROFILE}" REGION="${E2E_REGION}"
# Pool row 1 is the only row, and fleet.sh's datadog_keys_for maps attendee slot 1 to it.
readonly NAME="watch-it-burn-attendee-001"
readonly POOL_ID="watch-it-burn/datadog-pool" SANDBOX_ID="watch-it-burn/datadog"
E2E_LOG="${E2E_LOG:-/tmp/live-e2e-$(date -u +%Y%m%dT%H%M%SZ).log}"
WORK="$(mktemp -d -t live-e2e.XXXX)"; chmod 700 "${WORK}"
KCFG="${WORK}/${NAME}.kubeconfig"
SAVED="${WORK}/datadog-pool.saved"
ROW="${WORK}/datadog-pool.row"

sm()    { AWS_PROFILE="${PROFILE}" aws secretsmanager "$@" --region "${REGION}"; }
fleet() { WIB_DEFAULT_ACCOUNT="${PROFILE}" WIB_ATTENDEE_ACCOUNTS="${PROFILE}" WIB_REGION="${REGION}" bash "${FLEET}" "$@"; }
cluster_listed() { AWS_PROFILE="${PROFILE}" aws eks describe-cluster --name "${NAME}" --region "${REGION}" >/dev/null 2>&1; }

pool_seeded=0 pool_existed=0 cluster_started=0

# The row is written from a file, never on the command line, and no key is printed.
seed_pool() {
    local sandbox
    sandbox="$(sm get-secret-value --secret-id "${SANDBOX_ID}" --query SecretString --output text)" \
        || { log "cannot read ${SANDBOX_ID}; nothing was built"; return 1; }
    ( umask 077; jq -ce 'select((."api-key" // "") != "" and (."app-key" // "") != "")
        | [{org: "burritobot-sandbox (live e2e, #461)", "api-key": ."api-key", "app-key": ."app-key", role: "attendee"}]' \
        <<<"${sandbox}" >"${ROW}" 2>/dev/null ) \
        || { log "${SANDBOX_ID} has no api-key and app-key; nothing was built"; return 1; }
    if sm describe-secret --secret-id "${POOL_ID}" >/dev/null 2>&1; then
        ( umask 077; sm get-secret-value --secret-id "${POOL_ID}" --query SecretString --output text >"${SAVED}" ) \
            || { log "${POOL_ID} exists but its value could not be saved; not overwriting it, nothing was built"; return 1; }
        pool_existed=1
        log "saved ${POOL_ID}'s current value ($(jq 'length' "${SAVED}" 2>/dev/null || echo '?') rows) to put back after"
        sm put-secret-value --secret-id "${POOL_ID}" --secret-string "file://${ROW}" >/dev/null \
            || { log "could not write the one-row pool into ${POOL_ID}"; return 1; }
    else
        sm create-secret --name "${POOL_ID}" --secret-string "file://${ROW}" \
            --tags 'Key=project,Value=watch-it-burn' "Key=event,Value=${WIB_EVENT}" 'Key=component,Value=datadog-pool' >/dev/null \
            || { log "could not create ${POOL_ID}"; return 1; }
    fi
    pool_seeded=1
    log "${POOL_ID} is one row from ${SANDBOX_ID} (Whitney's sandbox org) for this session"
}

restore_pool() {
    [[ "${pool_seeded}" -eq 1 ]] || return 0
    if [[ "${pool_existed}" -eq 1 ]]; then
        sm put-secret-value --secret-id "${POOL_ID}" --secret-string "file://${SAVED}" >/dev/null || return 1
        log "${POOL_ID} put back to its saved value"
    else
        sm delete-secret --secret-id "${POOL_ID}" --force-delete-without-recovery >/dev/null || return 1
        log "${POOL_ID} deleted: it did not exist before this session"
    fi
}

finish() {
    local rc=$? problems=() restore_failed=0
    trap - EXIT INT TERM
    if [[ "${cluster_started}" -eq 1 ]]; then
        log "tearing down ${NAME}"
        WIB_APPLY=1 fleet down "${NAME}" || log "fleet.sh down ${NAME} exited non-zero"
        if cluster_listed; then
            problems+=("${NAME} IS STILL UP. Run: WIB_APPLY=1 WIB_DEFAULT_ACCOUNT=${PROFILE} WIB_REGION=${REGION} infra/terraform/fleet/fleet.sh down ${NAME}")
        else
            log "${NAME} is gone (EKS no longer lists it)"
        fi
    fi
    if ! restore_pool; then
        restore_failed=1
        if [[ "${pool_existed}" -eq 1 ]]; then
            problems+=("${POOL_ID} NOT RESTORED. Its saved value is ${SAVED}: AWS_PROFILE=${PROFILE} aws secretsmanager put-secret-value --region ${REGION} --secret-id ${POOL_ID} --secret-string file://${SAVED}, then delete ${WORK}")
        else
            problems+=("${POOL_ID} NOT DELETED. Run: AWS_PROFILE=${PROFILE} aws secretsmanager delete-secret --region ${REGION} --secret-id ${POOL_ID} --force-delete-without-recovery")
        fi
    fi
    if [[ "${#problems[@]}" -gt 0 ]]; then
        printf '\nLIVE E2E SESSION LEFT THINGS BEHIND:\n' >&2
        printf '  - %s\n' "${problems[@]}" >&2
        [[ "${rc}" -ne 0 ]] || rc=1
    fi
    # The saved pool value is the one copy left when its restore failed, so the work directory stays then.
    [[ "${pool_existed}" -eq 1 && "${restore_failed}" -eq 1 ]] || rm -rf "${WORK}"
    exit "${rc}"
}
trap finish EXIT
trap 'exit 130' INT TERM

if cluster_listed; then
    log "REFUSING: ${NAME} already exists in ${PROFILE}/${REGION}. This session builds its own cluster and tears down"
    log "          only that; it never adopts one it did not build. Find out whose it is before anything else."
    exit 1
fi
seed_pool || exit 1

cluster_started=1
log "building ${NAME} (fleet.sh up, attendee bootstrap, not registered in the handout pool)"
WIB_NO_INGEST=1 fleet up "${NAME}" || { log "fleet.sh up ${NAME} failed; see infra/terraform/fleet/logs/${NAME}.*.log"; exit 1; }

AWS_PROFILE="${PROFILE}" aws eks update-kubeconfig --kubeconfig "${KCFG}" --name "${NAME}" --region "${REGION}" >/dev/null \
    || { log "could not write a kubeconfig for ${NAME}"; exit 1; }
CONTEXT="$(KUBECONFIG="${KCFG}" kubectl config current-context 2>/dev/null || true)"
[[ "${CONTEXT}" == *":cluster/${NAME}" ]] \
    || { log "STOP: the isolated kubeconfig's context is '${CONTEXT:-none}', not ${NAME}; not running anything against it"; exit 1; }

log "running run-e2e.sh against ${CONTEXT}; log at ${E2E_LOG}"
KUBECONFIG="${KCFG}" AWS_PROFILE="${PROFILE}" CONTEXT="${CONTEXT}" \
    IAM_PIPELINE_PROFILE="${IAM_PIPELINE_PROFILE}" IAM_PIPELINE_REGION="${IAM_PIPELINE_REGION}" \
    bash "${RUN_E2E}" 2>&1 | tee "${E2E_LOG}"
e2e_rc="${PIPESTATUS[0]}"
log "run-e2e.sh exited ${e2e_rc}; record the result in decisions.md under #461 (log: ${E2E_LOG})"
exit "${e2e_rc}"
