#!/usr/bin/env bash
# ABOUTME: Idempotent teardown for Watch It Burn: deletes the independent per-attendee EKS clusters
# ABOUTME: (and any watch-it-burn-* clusters) by name prefix. No hub. Leaves the shared VPC for last.
#
# Architecture: independent per-attendee EKS clusters (no hub-and-spoke). Each cluster is standalone,
# so teardown is just "delete every cluster whose name starts with our prefix." The prefix scoping is
# the safety boundary: this account is SHARED with the Packt project, whose clusters are NOT named
# watch-it-burn-*, so this can only ever delete OUR clusters. It NEVER touches the local filesystem;
# it operates only via eksctl / aws. Safe to re-run: missing clusters are treated as success.
#
# Observability note: there is no central trace store to wipe. Each cluster's telemetry goes to Datadog
# (account-side, managed by Whitney) and its own in-cluster Prometheus/Tempo, which die with the cluster.
#
# Shared VPC note: clusters reference an existing shared VPC, so `eksctl delete cluster` does NOT delete
# the VPC (eksctl only removes what it created). Tear the shared VPC down separately, LAST, after every
# cluster is gone (see infra/shared-vpc/README.md).

set -euo pipefail

# --- defaults (override via flags / env) ---
REGION="${AWS_REGION:-us-west-2}"                          # verify-at-build
CLUSTER_PREFIX="${CLUSTER_PREFIX:-watch-it-burn-}"         # delete all clusters with this name prefix
ATTENDEES=()                                               # explicit ids (else discover by prefix)
ATTENDEE_PREFIX="${ATTENDEE_PREFIX:-watch-it-burn-attendee}" # used when --attendee ids are given
ASSUME_YES=false

usage() {
  cat <<'EOF'
Usage: teardown.sh [options]

Deletes Watch It Burn EKS clusters by name prefix (independent per-attendee clusters; no hub).

Options:
  --region <aws-region>        AWS region (default: $AWS_REGION or us-west-2)
  --prefix <prefix>            Delete all clusters whose name starts with this (default: watch-it-burn-)
  --attendee <id>              Tear down a specific attendee (repeatable): watch-it-burn-attendee-<id>.
                               If omitted, all clusters matching --prefix are discovered and deleted.
  --yes                        Do not prompt for confirmation.
  -h, --help                   Show this help.

Behavior:
  * Idempotent: already-deleted clusters are treated as success.
  * Deletes EKS clusters via `eksctl delete cluster --wait`.
  * Prefix-scoped: only watch-it-burn-* clusters, never the co-tenant Packt project's clusters.
  * Does NOT delete the shared VPC (eksctl leaves an existing VPC alone); remove it separately, last.
  * NEVER deletes local files; operates only via eksctl / aws.
EOF
}

# --- parse args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)   REGION="$2"; shift 2 ;;
    --prefix)   CLUSTER_PREFIX="$2"; shift 2 ;;
    --attendee) ATTENDEES+=("$2"); shift 2 ;;
    --yes)      ASSUME_YES=true; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

# --- preflight: required tooling ---
for bin in eksctl aws; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "ERROR: required tool not found on PATH: $bin" >&2
    exit 3
  fi
done

# --- safety: refuse a prefix that is not ours (cannot target the co-tenant Packt project) ---
if [[ "$CLUSTER_PREFIX" != watch-it-burn* ]]; then
  echo "ERROR: refusing prefix '$CLUSTER_PREFIX' - must start with 'watch-it-burn' (co-tenant safety)." >&2
  exit 4
fi

echo ">> Teardown starting (region=$REGION, prefix=$CLUSTER_PREFIX)"

# --- build the cluster list ---
CLUSTERS=()
if [[ ${#ATTENDEES[@]} -gt 0 ]]; then
  for a in "${ATTENDEES[@]}"; do CLUSTERS+=("${ATTENDEE_PREFIX}-${a}"); done
else
  echo ">> Discovering clusters matching prefix '$CLUSTER_PREFIX' in $REGION ..."
  while IFS= read -r name; do
    [[ -n "$name" ]] && CLUSTERS+=("$name")
  done < <(eksctl get cluster --region "$REGION" -o json 2>/dev/null \
            | grep -oE "\"${CLUSTER_PREFIX}[A-Za-z0-9._-]*\"" | tr -d '"' | sort -u || true)
fi

if [[ ${#CLUSTERS[@]} -eq 0 ]]; then
  echo ">> No matching clusters found to delete."
  echo ">> Teardown complete."
  exit 0
fi

echo ">> Clusters slated for deletion (${#CLUSTERS[@]}):"
printf '   - %s\n' "${CLUSTERS[@]}"

# --- confirmation gate ---
if [[ "$ASSUME_YES" != true ]]; then
  echo
  read -r -p ">> This will DELETE the above clusters. Type 'yes' to proceed: " reply
  if [[ "$reply" != "yes" ]]; then
    echo ">> Aborted by user."
    exit 0
  fi
fi

# --- delete each EKS cluster (idempotent) ---
total=${#CLUSTERS[@]}
i=0
for cluster in "${CLUSTERS[@]}"; do
  i=$((i + 1))
  echo ">> [${i}/${total}] Deleting EKS cluster: $cluster"
  if eksctl get cluster --name "$cluster" --region "$REGION" >/dev/null 2>&1; then
    eksctl delete cluster --name "$cluster" --region "$REGION" --wait
    echo ">> [${i}/${total}] Deleted: $cluster"
  else
    echo ">> [${i}/${total}] Already gone (idempotent): $cluster"
  fi
done

echo ">> All matching clusters deleted. The shared VPC was left intact; remove it separately if done."
echo ">> Teardown complete."
