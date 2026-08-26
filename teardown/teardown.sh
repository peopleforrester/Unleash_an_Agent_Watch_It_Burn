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
readonly TAG_AUDIT="${TF_DIR}/aws/teardown/tag-audit.sh"
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
# WIB_APPLY=1 is explicit because `fleet.sh down` is now dry-run by default. This script exists to
# destroy, and the user already said so by running it, so the confirmation belongs at THIS boundary
# rather than being demanded twice. Run `fleet.sh down all` directly for a preview.
WIB_APPLY=1 "${FLEET}" down all

# The tag audit runs BEFORE the sweep, while the resources still exist to be tagged. Anything the
# teardown identifies by tag is invisible to it if untagged, and untagged resources keep billing after
# the event: an audit of one 50-cluster account on the sister fleet found 451 of them. --fix only ever
# ADDS tags, never deletes, so it is safe to run unattended here.
if [[ -x "${TAG_AUDIT}" ]]; then
  log "==> tag audit (repairing untagged resources so the sweep can see them)"
  "${TAG_AUDIT}" all --fix || log "  (tag audit reported findings or failed; continuing to teardown)"
else
  log "  (tag-audit.sh not executable; skipping — untagged resources may survive this teardown)"
fi

log "==> sweeping orphaned EKS control-plane log groups (ours only)"
[[ -x "${CLEANUP_LOGS}" ]] && "${CLEANUP_LOGS}" --delete || log "  (cleanup-log-groups.sh not executable; skipping)"

if [[ "${DESTROY_VPC}" == "true" ]]; then
  log "==> destroying the shared lab VPC (last)"
  # profile/region are passed explicitly: the network root no longer defaults `profile`, because an
  # implicit account is how a destroy can point at the wrong one. Override with WIB_DEFAULT_ACCOUNT.
  terraform -chdir="${TF_DIR}/aws/network" destroy -auto-approve \
    -var "profile=${WIB_DEFAULT_ACCOUNT:-accen-dev}" -var "region=${WIB_REGION:-us-west-2}"
else
  log "==> shared lab VPC left intact; re-run with --vpc to remove it when the event is over."
fi

log "Teardown complete."
