#!/usr/bin/env bash
# ABOUTME: Phase-6 verification harness — runs beat-01/02/03 against one fresh test attendee spoke.
# ABOUTME: The abstract-truth gate: asserts every §2 before/after outcome, idempotent, exits non-zero on any failure.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly BEAT_01="${SCRIPT_DIR}/beat-01.sh"
readonly BEAT_02="${SCRIPT_DIR}/beat-02.sh"
readonly BEAT_03="${SCRIPT_DIR}/beat-03.sh"

usage() {
    cat >&2 <<'EOF'
Usage: run-all.sh <kube-context> <attendee-namespace>

  <kube-context>         kubeconfig context for a FRESH test attendee SPOKE cluster
  <attendee-namespace>   namespace the scoped agent / gateway live in

Runs the Beat 1, 2, and 3 assertions in order and prints a pass/fail summary.
Each beat asserts its §2 before/after states (see the individual scripts).
Every beat is idempotent: running this harness twice in a row must pass both
times (no leftover state). Beat 3 follows its spike gate automatically.

Exit: 0 = every beat PASS; non-zero = at least one beat FAILED.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; exit 2; fi
CONTEXT="${1:?$(usage)}"
NS="${2:?$(usage)}"

for s in "${BEAT_01}" "${BEAT_02}" "${BEAT_03}"; do
    [[ -x "${s}" ]] || { echo "FAIL: beat script not executable: ${s}" >&2; exit 1; }
done

declare -A RESULT
ORDER=(beat-01 beat-02 beat-03)
declare -A SCRIPT=([beat-01]="${BEAT_01}" [beat-02]="${BEAT_02}" [beat-03]="${BEAT_03}")

echo "================================================================" >&2
echo " Phase-6 harness  context=${CONTEXT}  namespace=${NS}" >&2
echo "================================================================" >&2

OVERALL=0
for beat in "${ORDER[@]}"; do
    echo "" >&2
    echo "---------------- running ${beat} ----------------" >&2
    if "${SCRIPT[${beat}]}" "${CONTEXT}" "${NS}"; then
        RESULT[${beat}]="PASS"
    else
        RESULT[${beat}]="FAIL"
        OVERALL=1
    fi
done

echo "" >&2
echo "================================================================" >&2
echo " SUMMARY" >&2
echo "----------------------------------------------------------------" >&2
for beat in "${ORDER[@]}"; do
    printf "  %-10s %s\n" "${beat}" "${RESULT[${beat}]}" >&2
done
echo "================================================================" >&2

if [[ "${OVERALL}" -eq 0 ]]; then
    echo "ALL BEATS PASS — the §2 abstract is true on this attendee spoke." >&2
else
    echo "FAILURE — at least one beat does not match §2. The talk's claims are NOT yet true." >&2
fi
exit "${OVERALL}"
