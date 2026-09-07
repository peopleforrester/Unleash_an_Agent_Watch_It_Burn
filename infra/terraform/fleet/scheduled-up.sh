#!/usr/bin/env bash
# ABOUTME: Unattended bring-up for a scheduled run: the instructor roster plus N attendee clusters, each
# ABOUTME: stage ending in its own acceptance pass. Supplies the env cron does not, and logs every stage.
#
# Why this exists. A bring-up that has to happen while nobody is watching cannot depend on a chat session
# being alive, and cron gives a script almost none of an interactive shell's environment: no PATH to
# linuxbrew (terraform, aws, kubectl, helm, railway all live there), no HOME for the railway and aws
# credential files, no AWS_PROFILE. Every one of those failures is silent and looks like "the fleet did
# not come up". This script sets them, asserts each dependency BEFORE it starts building, and refuses to
# run rather than half-build.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly FLEET_BIN="${WIB_FLEET_BIN:-${SCRIPT_DIR}/fleet.sh}"
readonly LOG_DIR="${WIB_SCHED_LOG_DIR:-${SCRIPT_DIR}/logs}"
readonly LOCK_FILE="${WIB_SCHED_LOCK:-${LOG_DIR}/.scheduled-up.lock}"
readonly CRON_TAG="wib-scheduled-up"

usage() {
    cat >&2 <<EOF
Usage: ${0##*/} [attendee-count]

Brings up the nine instructor clusters (both owners, all rounds) and <attendee-count> attendee clusters
(default 2), then runs the acceptance pass over everything. Each stage already ends in its own verify, so
a stage that reports success has been checked, not assumed.

  WIB_SCHED_ATTENDEES    attendee count when no argument is given (default 2)
  WIB_SCHED_INSTRUCTORS  instructor selector (default 'both'; 'none' skips the roster entirely)
  AWS_PROFILE            account for the attendee pool (default accen-dev)
  WIB_CRON_SELF_REMOVE   1 = remove the one-shot ${CRON_TAG} line from the crontab after a clean run
  WIB_SCHED_LOG_DIR      where the run log is written (default fleet/logs)
EOF
    exit 2
}

log() { printf '%s  %s\n' "$(date -u +%FT%TZ)" "$*"; }

# Cron's PATH is /usr/bin:/bin. Every tool the fleet driver shells out to is in linuxbrew, so a bare
# inherited PATH fails at the first terraform call, after the script has already reported it started.
# The known directories are APPENDED, never prepended: under cron the inherited PATH has nothing in it to
# shadow them, and in any other context (an interactive run, a test with shims) the caller's PATH is the
# one that should win.
setup_env() {
    export PATH="${PATH:-/usr/bin:/bin}:/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:${HOME:-/home/michael}/.local/bin:/usr/local/bin:/usr/bin:/bin"
    export HOME="${HOME:-/home/michael}"
    export AWS_PROFILE="${AWS_PROFILE:-accen-dev}"
    export WIB_APPLY="${WIB_APPLY:-1}"
}

# Assert every dependency and credential up front. A missing railway login only surfaces at the ingest
# step, an hour into a build, and leaves clusters that exist but are not claimable.
preflight_env() {
    local missing=() b
    for b in terraform aws kubectl helm python3 jq curl dig railway; do
        command -v "${b}" >/dev/null 2>&1 || missing+=("${b}")
    done
    [[ -x "${FLEET_BIN}" ]] || missing+=("fleet.sh at ${FLEET_BIN}")
    if [[ "${#missing[@]}" -gt 0 ]]; then
        log "PREFLIGHT FAILED: not on PATH: ${missing[*]}"; return 1
    fi
    if ! aws sts get-caller-identity --query Account --output text >/dev/null 2>&1; then
        log "PREFLIGHT FAILED: AWS_PROFILE='${AWS_PROFILE}' does not authenticate"; return 1
    fi
    if ! railway whoami >/dev/null 2>&1; then
        log "PREFLIGHT FAILED: railway is not logged in, so the provisioning admin token cannot be"
        log "                  resolved and the clusters would build without being claimable."
        return 1
    fi
    log "preflight ok: tools, AWS_PROFILE=${AWS_PROFILE}, railway login"
}

# Run one fleet verb, timed, and stop the run on the first failure. Nothing is retried here on purpose:
# each verb already retries internally, so a failure that reaches this level is one a human must read.
run_stage() {
    local name="$1"; shift
    local start; start="$(date +%s)"
    log "STAGE ${name}: ${FLEET_BIN##*/} $*"
    if "${FLEET_BIN}" "$@"; then
        log "STAGE ${name}: OK in $(( ($(date +%s) - start) / 60 ))m"
    else
        local rc=$?
        log "STAGE ${name}: FAILED (exit ${rc}) after $(( ($(date +%s) - start) / 60 ))m"
        return "${rc}"
    fi
}

# A one-shot schedule that leaves its line behind fires again next year on the same date. Removing it on
# a clean run makes the schedule genuinely one-shot without needing anyone to remember.
remove_cron_line() {
    [[ "${WIB_CRON_SELF_REMOVE:-}" == "1" ]] || return 0
    local current
    current="$(crontab -l 2>/dev/null || true)"
    grep -q "${CRON_TAG}" <<<"${current}" || return 0
    printf '%s\n' "${current}" > "${LOG_DIR}/crontab.before-self-remove.$(date -u +%Y%m%dT%H%M%SZ)"
    grep -v "${CRON_TAG}" <<<"${current}" | crontab -
    log "removed the one-shot ${CRON_TAG} line from the crontab"
}

main() {
    [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage
    local attendees="${1:-${WIB_SCHED_ATTENDEES:-2}}"
    [[ "${attendees}" =~ ^[0-9]+$ ]] || usage
    local instructors="${WIB_SCHED_INSTRUCTORS:-both}"

    setup_env
    mkdir -p "${LOG_DIR}"
    # The same lock is taken by an unattended teardown, so a teardown that overruns its window delays this
    # bring-up instead of interleaving with it. Bounded: a long wait is survivable, an unbounded one is a
    # scheduled job that silently never returns.
    exec 9>"${LOCK_FILE}"
    local wait_s="${WIB_SCHED_LOCK_WAIT:-1800}"
    if ! flock -w "${wait_s}" 9; then
        log "another fleet run still holds ${LOCK_FILE} after ${wait_s}s; exiting rather than building on top of it"
        exit 1
    fi

    log "scheduled bring-up starting: instructors='${instructors}', attendees=${attendees}"
    preflight_env || exit 1

    [[ "${instructors}" == "none" ]] || run_stage "instructors" instructors up "${instructors}"
    run_stage "attendees" scale "${attendees}"
    run_stage "verify" verify all

    log "scheduled bring-up COMPLETE: instructor roster + ${attendees} attendee cluster(s), verified"
    remove_cron_line
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
