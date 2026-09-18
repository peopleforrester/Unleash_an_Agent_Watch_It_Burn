#!/usr/bin/env bash
# ABOUTME: One entry point for the post-event harvest: runs the five passes in order and writes the
# ABOUTME: result under .harvest/<event>/, which stays gitignored because it holds attendee-typed text.
#
# Why the split between this directory and .harvest/ matters (issue #399).
#
# The CODE belongs in git and the DATA does not. The data is attendee prompts and terminal history from
# a live workshop; it is not ours to commit. The code is where everything learned about finding that
# data lives, and none of it was obvious:
#
#   * prompts are in the span attribute custom.gen_ai.input.messages, as JSON STRINGS. They are not in
#     the gen_ai.content.* events, which is where two earlier attempts looked.
#   * Falco runs in namespace `security`; falco-talon runs in namespace `falco`. Looking in the obvious
#     namespace returns zero events from a perfectly healthy cluster.
#   * every cluster ships to its OWN Datadog org, resolved from the datadog-secret ON that cluster. The
#     admin dual-ship org is a DIFFERENT org again, and querying the wrong one returns zero metrics for
#     a healthy fleet, which reads as an outage and is not one. That mistake was made twice.
#   * terminal history is ~/.bash_history inside the web-terminal pod.
#   * Kyverno PolicyReports record the villain being CAUGHT and survive the pod being deleted, so they
#     are the only durable evidence of a Challenge 2 attempt after a student applies the fix.
#
# Rediscovering that costs hours. Losing it costs the next event's data entirely.
#
# Usage:
#   scripts/harvest/run.sh <event-name>          e.g. devopsdays-portland
#   WIB_EVENT=<name> scripts/harvest/run.sh      same thing
#
# Run it while the clusters are still UP. Everything except the Datadog passes reads live cluster state,
# and none of it is recoverable after teardown.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVENT="${1:-${WIB_EVENT:-}}"
if [[ -z "${EVENT}" ]]; then
    echo "usage: $0 <event-name>   (e.g. devopsdays-portland)" >&2
    exit 2
fi
export WIB_EVENT="${EVENT}"
export WIB_SCRATCH="${WIB_SCRATCH:-/tmp/wib-harvest}"
mkdir -p "${WIB_SCRATCH}"
OUT="$(cd "${HERE}/../.." && pwd)/.harvest/${EVENT}"
mkdir -p "${OUT}"/{per-cluster,prompts,terminal,raw}

log() { printf '%s  %s\n' "$(date -u +%H:%M:%S)" "$*"; }
run() {
    local n="$1" f="$2"
    log "pass ${n}: ${f}"
    if python3 "${HERE}/${f}" >>"${OUT}/raw/harvest.log" 2>&1; then
        log "  ok"
    else
        # A failed pass must not stop the others: they read different sources and a Datadog outage
        # should not cost the cluster-state capture, which is the half that cannot be re-read later.
        log "  FAILED (see ${OUT}/raw/harvest.log); continuing"
    fi
}
log "harvesting '${EVENT}' into ${OUT}"
run 1 01-clusters.py        # usage, controls, challenge completion, terminal history, prompts
run 2 02-forensics.py       # Kyverno PolicyReports, KubeArmor, k8s events, pod health
run 3 03-falco.py           # Falco (ns security) and Talon (ns falco)
run 4 04-argo-datadog.py    # ArgoCD application history, per-org Datadog metrics
run 5 05-analyze.py         # behavioural report -> SUMMARY.md
log "done. Report: ${OUT}/SUMMARY.md"
ls -la "${OUT}" 2>/dev/null | awk 'NR>3{printf "  %s\n",$NF}'
