#!/usr/bin/env bash
# ABOUTME: Idempotent teardown for Watch It Burn. Destroys the independent per-attendee EKS clusters
# ABOUTME: via the Terraform fleet (each its own state), then sweeps orphaned EKS log groups.
#
# Provisioning is Terraform (infra/terraform/), not eksctl. Teardown delegates to the fleet driver,
# which destroys each cluster from its own state file. The safety boundary is the cluster-name prefix:
# this account is SHARED with the Packt project, whose clusters are NOT named watch-it-burn-*, and the
# fleet driver refuses any name that is not watch-it-burn-* (assert_ours). So this can only ever delete
# OUR clusters. The shared lab VPC is left for last and only removed with --vpc (see infra/terraform/).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
TF_DIR="$(cd "${SCRIPT_DIR}/../infra/terraform" && pwd)"
readonly TF_DIR
readonly FLEET="${TF_DIR}/fleet/fleet.sh"
readonly CLEANUP_LOGS="${TF_DIR}/fleet/cleanup-log-groups.sh"
# Name-prefix safety boundary: we only ever operate on watch-it-burn-* (never the co-tenant Packt).
readonly CLUSTER_PREFIX="watch-it-burn-"
DESTROY_VPC=false

log() { printf '%s\n' "$*" >&2; }

usage() {
  cat >&2 <<EOF
Usage: ${0##*/} [--vpc]

Destroys all Watch It Burn attendee clusters (Terraform fleet, per-attendee state), then sweeps
orphaned EKS log groups. Scoped to the ${CLUSTER_PREFIX} cluster-name prefix; it cannot touch the
co-tenant Packt clusters (the fleet refuses any non-watch-it-burn name).

  --vpc    Also destroy the shared lab VPC after every cluster is gone (infra/terraform/aws/network).
  -h       Show this help.
EOF
  exit 2
}

case "${1:-}" in
  --vpc) DESTROY_VPC=true ;;
  -h|--help) usage ;;
  "") ;;
  *) log "refusing prefix outside ${CLUSTER_PREFIX}; unknown arg: ${1}"; usage ;;
esac

command -v terraform >/dev/null 2>&1 || { log "terraform not found"; exit 1; }
[[ -x "${FLEET}" ]] || { log "fleet driver not found at ${FLEET}"; exit 1; }

log "==> destroying all attendee clusters via the Terraform fleet (prefix ${CLUSTER_PREFIX})"
"${FLEET}" down all

log "==> sweeping orphaned EKS control-plane log groups (ours only)"
[[ -x "${CLEANUP_LOGS}" ]] && "${CLEANUP_LOGS}" --delete || log "  (cleanup-log-groups.sh not executable; skipping)"

if [[ "${DESTROY_VPC}" == "true" ]]; then
  log "==> destroying the shared lab VPC (last)"
  terraform -chdir="${TF_DIR}/aws/network" destroy -auto-approve
else
  log "==> shared lab VPC left intact; re-run with --vpc to remove it when the event is over."
fi

log "Teardown complete."
