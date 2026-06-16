#!/usr/bin/env bash
# ABOUTME: Idempotent teardown for the Watch-It-Burn workshop — deletes each attendee SPOKE EKS cluster
# ABOUTME: and the hub trace data (Tempo re-leak sink), with a flag to leave the hub stack intact.
#
# Architecture (BUILD-SPEC rev3): N attendee SPOKE EKS clusters + 1 HUB EKS cluster. This script
# deletes the SPOKE clusters via `eksctl delete cluster` and wipes hub trace data via kubectl/helm.
# It NEVER touches the local filesystem with rm -rf — it operates exclusively through
# eksctl / kubectl / helm / aws against cloud + k8s resources. Safe to re-run: missing clusters and
# already-deleted resources are treated as success.

set -euo pipefail

# --- defaults (override via flags / env) ---
REGION="${AWS_REGION:-us-east-1}"                 # verify-at-build
SPOKE_PREFIX="${SPOKE_PREFIX:-watch-it-burn-spoke}"   # spoke cluster name prefix  # verify-at-build
HUB_CLUSTER="${HUB_CLUSTER:-watch-it-burn-hub}"       # hub EKS cluster name        # verify-at-build
HUB_KUBE_CONTEXT="${HUB_KUBE_CONTEXT:-}"             # kube context for the hub; empty = current
TEMPO_NAMESPACE="${TEMPO_NAMESPACE:-observability}"  # hub Tempo namespace
TEMPO_RELEASE="${TEMPO_RELEASE:-tempo-hub}"          # hub Tempo helm release
KEEP_HUB=false                                       # --keep-hub leaves hub trace data + hub cluster
ATTENDEES=()                                         # explicit attendee ids (else discover by prefix)
ASSUME_YES=false

usage() {
  cat <<'EOF'
Usage: teardown.sh [options]

Deletes the workshop's attendee SPOKE EKS clusters and the HUB trace data.

Options:
  --region <aws-region>        AWS region (default: $AWS_REGION or us-east-1)
  --spoke-prefix <prefix>      Spoke cluster name prefix (default: watch-it-burn-spoke)
  --hub-cluster <name>         Hub EKS cluster name (default: watch-it-burn-hub)
  --hub-context <ctx>          kube context for the hub cluster (default: current context)
  --attendee <id>              Tear down a specific attendee (repeatable). If omitted, all
                               clusters matching --spoke-prefix are discovered and deleted.
  --keep-hub                   Leave the hub cluster AND its trace data intact (spokes only).
  --yes                        Do not prompt for confirmation.
  -h, --help                   Show this help.

Behavior:
  * Idempotent: already-deleted clusters / missing resources are treated as success.
  * Deletes SPOKE EKS clusters via `eksctl delete cluster`.
  * Wipes HUB trace data (Tempo) so no span store retains even the FAKE sentinel post-run.
  * NEVER deletes local files; operates only via eksctl / kubectl / helm / aws.
EOF
}

# --- parse args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)       REGION="$2"; shift 2 ;;
    --spoke-prefix) SPOKE_PREFIX="$2"; shift 2 ;;
    --hub-cluster)  HUB_CLUSTER="$2"; shift 2 ;;
    --hub-context)  HUB_KUBE_CONTEXT="$2"; shift 2 ;;
    --attendee)     ATTENDEES+=("$2"); shift 2 ;;
    --keep-hub)     KEEP_HUB=true; shift ;;
    --yes)          ASSUME_YES=true; shift ;;
    -h|--help)      usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

# --- preflight: required tooling ---
for bin in eksctl kubectl helm aws; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "ERROR: required tool not found on PATH: $bin" >&2
    exit 3
  fi
done

echo ">> Teardown starting (region=$REGION, spoke-prefix=$SPOKE_PREFIX, hub=$HUB_CLUSTER, keep-hub=$KEEP_HUB)"

# --- helper: build the kubectl context flag for the hub ---
hub_kctx() {
  if [[ -n "$HUB_KUBE_CONTEXT" ]]; then echo "--context=$HUB_KUBE_CONTEXT"; fi
}

# --- discover spoke clusters if no explicit attendees given ---
SPOKE_CLUSTERS=()
if [[ ${#ATTENDEES[@]} -gt 0 ]]; then
  for a in "${ATTENDEES[@]}"; do SPOKE_CLUSTERS+=("${SPOKE_PREFIX}-${a}"); done
else
  echo ">> Discovering spoke clusters matching prefix '$SPOKE_PREFIX' in $REGION ..."
  # `eksctl get cluster` lists all EKS clusters in the region; filter by prefix.
  while IFS= read -r name; do
    [[ -n "$name" ]] && SPOKE_CLUSTERS+=("$name")
  done < <(eksctl get cluster --region "$REGION" -o json 2>/dev/null \
            | grep -oE "\"${SPOKE_PREFIX}[A-Za-z0-9._-]*\"" | tr -d '"' | sort -u || true)
fi

if [[ ${#SPOKE_CLUSTERS[@]} -eq 0 ]]; then
  echo ">> No spoke clusters found to delete."
else
  echo ">> Spoke clusters slated for deletion (${#SPOKE_CLUSTERS[@]}):"
  printf '   - %s\n' "${SPOKE_CLUSTERS[@]}"
fi

# --- confirmation gate ---
if [[ "$ASSUME_YES" != true ]]; then
  echo
  read -r -p ">> This will DELETE the above SPOKE clusters and (unless --keep-hub) hub trace data. Type 'yes' to proceed: " reply
  if [[ "$reply" != "yes" ]]; then
    echo ">> Aborted by user."
    exit 0
  fi
fi

# --- delete each spoke EKS cluster (idempotent) ---
total=${#SPOKE_CLUSTERS[@]}
i=0
for cluster in "${SPOKE_CLUSTERS[@]}"; do
  i=$((i + 1))
  echo ">> [${i}/${total}] Deleting spoke EKS cluster: $cluster"
  if eksctl get cluster --name "$cluster" --region "$REGION" >/dev/null 2>&1; then
    # --wait so the script does not return before the CloudFormation stacks are gone.
    eksctl delete cluster --name "$cluster" --region "$REGION" --wait
    echo ">> [${i}/${total}] Deleted: $cluster"
  else
    echo ">> [${i}/${total}] Already gone (idempotent): $cluster"
  fi
done

# --- hub trace data wipe (the re-leak sink) ---
if [[ "$KEEP_HUB" == true ]]; then
  echo ">> --keep-hub set: leaving hub cluster '$HUB_CLUSTER' and its trace data intact."
else
  echo ">> Wiping HUB trace data (Tempo) in namespace '$TEMPO_NAMESPACE' on hub '$HUB_CLUSTER' ..."
  if kubectl $(hub_kctx) get namespace "$TEMPO_NAMESPACE" >/dev/null 2>&1; then
    # Delete Tempo's persistent storage so no span store retains even the FAKE sentinel.
    # PVCs back Tempo's trace blocks; removing them drops all stored traces.
    echo ">> Deleting Tempo PVCs (trace storage) ..."
    kubectl $(hub_kctx) -n "$TEMPO_NAMESPACE" delete pvc \
      -l "app.kubernetes.io/name=tempo" --ignore-not-found=true   # verify-at-build: confirm label
    # Restart Tempo so it comes back with empty storage (idempotent; no error if absent).
    echo ">> Restarting Tempo to reinitialize empty trace storage ..."
    kubectl $(hub_kctx) -n "$TEMPO_NAMESPACE" rollout restart statefulset \
      -l "app.kubernetes.io/name=tempo" 2>/dev/null || true
    echo ">> Hub trace data wiped."
  else
    echo ">> Tempo namespace '$TEMPO_NAMESPACE' not found on hub (idempotent): nothing to wipe."
  fi
fi

echo ">> Teardown complete."
