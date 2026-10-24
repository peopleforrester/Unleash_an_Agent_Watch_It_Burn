#!/usr/bin/env bash
# ABOUTME: Daily, unattended run of the plan-only drift report: supplies the environment cron does not, refuses
# ABOUTME: to run without its tools, keeps a dated copy, and posts the result to the "Fleet drift report" issue.
#
# Install once on the machine that holds the fleet's state files (the states are local, see docs/floor.md):
#
#   ( crontab -l 2>/dev/null; echo '17 6 * * * <repo>/infra/terraform/drift/scheduled-drift.sh # wib-drift' ) | crontab -
#
# Exit codes are drift-report.py's: 0 clean, 2 findings, 1 incomplete. Cron mails whatever is printed, so a
# failure is never silent even when the GitHub post is what failed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly REPORT_BIN="${WIB_DRIFT_BIN:-${SCRIPT_DIR}/drift-report.py}"
readonly LOG_DIR="${WIB_DRIFT_LOG_DIR:-${SCRIPT_DIR}/logs}"

log() { printf '%s  %s\n' "$(date -u +%FT%TZ)" "$*"; }

# Cron's PATH is /usr/bin:/bin and terraform, aws and gh live in linuxbrew. APPENDED, as scheduled-up.sh does,
# so a caller's PATH (an interactive run, a test with shims) still wins.
export PATH="${PATH:-/usr/bin:/bin}:/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:${HOME:-/home/michael}/.local/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="${HOME:-/home/michael}"

missing=()
for b in terraform aws gh python3; do
    command -v "${b}" >/dev/null 2>&1 || missing+=("${b}")
done
python3 -c 'import yaml' 2>/dev/null || missing+=("PyYAML for python3")
[[ -f "${REPORT_BIN}" ]] || missing+=("the report at ${REPORT_BIN}")
if [[ "${#missing[@]}" -gt 0 ]]; then
    log "DRIFT REPORT NOT RUN: missing ${missing[*]}"
    exit 1
fi

mkdir -p "${LOG_DIR}"
out="${LOG_DIR}/drift-$(date -u +%Y%m%dT%H%MZ).md"
log "drift report starting; copy at ${out}"
rc=0
python3 "${REPORT_BIN}" --post --out "${out}" "$@" || rc=$?
case "${rc}" in
    0) log "drift report: clean" ;;
    2) log "drift report: FINDINGS, posted to the 'Fleet drift report' issue" ;;
    *) log "drift report: INCOMPLETE (exit ${rc}); read ${out} and the output above" ;;
esac
exit "${rc}"
