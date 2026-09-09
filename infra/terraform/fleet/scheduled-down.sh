#!/usr/bin/env bash
# ABOUTME: One-shot scheduled teardown of the whole fleet, the counterpart to scheduled-up.sh: cron fires
# ABOUTME: this after the event window closes and it destroys every cluster with state, ending in audit-zero.
#
# Why this exists. The clusters are promised to attendees until 17:10 PDT on the event day and cost real
# money after it. A teardown queued inside a Claude Code session dies silently when the session ends (that
# failure has already cost one rebuild), so the schedule has to live in cron and the run has to detach from
# whatever started it.
#
# Usage: scheduled-down.sh
#   WIB_APPLY             forced to 1; `down` is a no-op without it
#   WIB_DOWN_TARGET       what to destroy (default 'all': every cluster that has state)
#   WIB_CRON_SELF_REMOVE  1 = drop the wib-scheduled-down line from the crontab after a clean run
#   WIB_SCHED_LOG_DIR     where the run log goes (default fleet/logs)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly FLEET_BIN="${WIB_FLEET_BIN:-${SCRIPT_DIR}/fleet.sh}"
readonly LOG_DIR="${WIB_SCHED_LOG_DIR:-${SCRIPT_DIR}/logs}"
readonly LOCK_FILE="${LOG_DIR}/.scheduled-down.lock"
readonly CRON_TAG="wib-scheduled-down"
readonly TARGET="${WIB_DOWN_TARGET:-all}"

log() { printf '%s  %s\n' "$(date -u +%FT%TZ)" "$*"; }

setup_env() {
    # cron gets a stripped PATH and none of the interactive shell's exports.
    export PATH="${PATH:-/usr/bin:/bin}:/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:${HOME:-/home/michael}/.local/bin:/usr/local/bin:/usr/bin:/bin"
    export HOME="${HOME:-/home/michael}"
    export AWS_PROFILE="${AWS_PROFILE:-accen-dev}"
    export WIB_APPLY=1
}

self_remove() {
    [[ "${WIB_CRON_SELF_REMOVE:-0}" == "1" ]] || return 0
    crontab -l 2>/dev/null | grep -v "# ${CRON_TAG}\$" | crontab - && log "removed the one-shot ${CRON_TAG} cron line"
}

main() {
    mkdir -p "${LOG_DIR}"
    setup_env
    exec 9>"${LOCK_FILE}"
    flock -n 9 || { log "another scheduled-down holds the lock; exiting"; exit 0; }

    log "TEARDOWN START  target=${TARGET}  (17:10 PDT window closed)"
    for b in aws kubectl terraform; do
        command -v "$b" >/dev/null || { log "FATAL: ${b} not on PATH"; exit 1; }
    done

    local rc=0
    "${FLEET_BIN}" down "${TARGET}" || rc=$?
    if (( rc == 0 )); then
        log "teardown reported success; audit-zero ran as part of 'down ${TARGET}'"
        self_remove
    else
        log "TEARDOWN FAILED rc=${rc}; leaving the cron line in place and NOT self-removing"
    fi
    log "TEARDOWN END rc=${rc}"
    return "${rc}"
}
main "$@"
