#!/usr/bin/env bash
# ABOUTME: Deletes orphaned EKS control-plane log groups left by create_cloudwatch_log_group=false
# ABOUTME: after a cluster is destroyed. Only ever touches our (watch-it-burn) clusters.
set -euo pipefail

REGION="${REGION:-us-west-2}"
PROFILE="${AWS_PROFILE:-accen-dev}"
# Only clusters whose name matches this are ours. Never touch the co-tenant Packt log groups.
readonly OURS_REGEX='^watch-it-burn-'
DELETE=0

log() { printf '%s\n' "$*" >&2; }

usage() {
    cat >&2 <<EOF
Usage: [AWS_PROFILE=accen-dev REGION=us-west-2] ${0##*/} [--delete]

Lists /aws/eks/<name>/cluster log groups whose cluster name matches ${OURS_REGEX} and whose EKS
cluster no longer exists, i.e. orphans from create_cloudwatch_log_group=false. Dry-run by default;
pass --delete to remove them.
EOF
    exit 2
}

main() {
    [[ "${1:-}" == "--delete" ]] && DELETE=1
    [[ "${1:-}" =~ ^(|--delete)$ ]] || usage
    command -v aws >/dev/null 2>&1 || { log "aws not found"; exit 1; }

    local groups grp name orphans=0
    mapfile -t groups < <(AWS_PROFILE="${PROFILE}" aws logs describe-log-groups \
        --region "${REGION}" --log-group-name-prefix /aws/eks/ \
        --query 'logGroups[].logGroupName' --output text 2>/dev/null | tr '\t' '\n')

    for grp in "${groups[@]}"; do
        [[ -n "${grp}" ]] || continue
        # /aws/eks/<name>/cluster -> <name>
        name="${grp#/aws/eks/}"; name="${name%/cluster}"
        [[ "${name}" =~ ${OURS_REGEX} ]] || { log "skip (not ours): ${grp}"; continue; }
        if AWS_PROFILE="${PROFILE}" aws eks describe-cluster --name "${name}" \
            --region "${REGION}" >/dev/null 2>&1; then
            log "live cluster, keep: ${grp}"
            continue
        fi
        orphans=$((orphans + 1))
        if [[ "${DELETE}" -eq 1 ]]; then
            AWS_PROFILE="${PROFILE}" aws logs delete-log-group \
                --region "${REGION}" --log-group-name "${grp}" 2>&1 \
                && log "deleted orphan: ${grp}"
        else
            log "ORPHAN (dry-run): ${grp}"
        fi
    done

    log "done: ${orphans} orphan(s) $([[ "${DELETE}" -eq 1 ]] && echo deleted || echo found)"
}

main "$@"
