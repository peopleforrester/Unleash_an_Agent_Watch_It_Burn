#!/usr/bin/env bash
# ABOUTME: Queries AWS Cost Explorer for the real workshop spend across the hub + spoke EKS clusters
# ABOUTME: over the run window and prints the actual dollar number - never estimated or hardcoded.
#
# Reports the REAL AWS cost for the workshop run for Accenture expensing (BUILD-SPEC Phase 9).
# Uses `aws ce get-cost-and-usage`. Costs are attributed by cost-allocation tag (default key
# "workshop") so all watch-it-burn clusters tagged with that key are summed. No figure is estimated
# or baked into this script; it reports whatever Cost Explorer returns for the window.

set -euo pipefail

# --- defaults (override via flags) ---
START=""                                   # run-window start, YYYY-MM-DD (inclusive)
END=""                                     # run-window end,   YYYY-MM-DD (exclusive, CE convention)
TAG_KEY="${COST_TAG_KEY:-workshop}"        # cost-allocation tag key on hub+spoke resources  # verify-at-build
TAG_VALUE="${COST_TAG_VALUE:-watch-it-burn}"  # tag value identifying this workshop run     # verify-at-build
GRANULARITY="DAILY"                        # DAILY | MONTHLY
GROUP_BY_SERVICE=false                     # --by-service to break the total down per AWS service

usage() {
  cat <<'EOF'
Usage: cost-report.sh --start YYYY-MM-DD --end YYYY-MM-DD [options]

Prints the REAL AWS cost (from Cost Explorer) for the workshop run window, summed across the
hub + spoke EKS clusters identified by a cost-allocation tag. The number is queried live, never
estimated or hardcoded.

Required:
  --start YYYY-MM-DD     Run-window start date (inclusive).
  --end   YYYY-MM-DD     Run-window end date (exclusive - Cost Explorer convention; use the day
                         AFTER the last billed day to include the final day).

Options:
  --tag-key <key>        Cost-allocation tag key (default: workshop, or $COST_TAG_KEY).
  --tag-value <value>    Tag value for this run (default: watch-it-burn, or $COST_TAG_VALUE).
  --granularity <g>      DAILY or MONTHLY (default: DAILY).
  --by-service           Also print a per-AWS-service breakdown.
  -h, --help             Show this help.

Notes:
  * The cost-allocation tag MUST be activated in the Billing console before it can be queried,
    and tagged resources only show cost from the activation date forward.
  * Cost Explorer get-cost-and-usage incurs a small per-request charge.
EOF
}

# --- parse args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --start)       START="$2"; shift 2 ;;
    --end)         END="$2"; shift 2 ;;
    --tag-key)     TAG_KEY="$2"; shift 2 ;;
    --tag-value)   TAG_VALUE="$2"; shift 2 ;;
    --granularity) GRANULARITY="$2"; shift 2 ;;
    --by-service)  GROUP_BY_SERVICE=true; shift ;;
    -h|--help)     usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

# --- validate required args ---
if [[ -z "$START" || -z "$END" ]]; then
  echo "ERROR: --start and --end are required." >&2
  usage
  exit 2
fi
if ! [[ "$START" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ && "$END" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "ERROR: dates must be YYYY-MM-DD." >&2
  exit 2
fi

# --- preflight tooling ---
for bin in aws; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "ERROR: required tool not found on PATH: $bin" >&2
    exit 3
  fi
done

echo ">> Querying AWS Cost Explorer for workshop spend"
echo ">>   window:      $START (incl) .. $END (excl)"
echo ">>   filter tag:  ${TAG_KEY}=${TAG_VALUE}"
echo ">>   granularity: $GRANULARITY"

# Cost-allocation tag filter scopes the query to hub+spoke resources for THIS run only.
FILTER_JSON=$(cat <<JSON
{ "Tags": { "Key": "${TAG_KEY}", "Values": ["${TAG_VALUE}"] } }
JSON
)

# --- total cost (unblended) ---
echo ">> Fetching total unblended cost ..."
TOTAL=$(aws ce get-cost-and-usage \
  --time-period "Start=${START},End=${END}" \
  --granularity "$GRANULARITY" \
  --metrics "UnblendedCost" \
  --filter "$FILTER_JSON" \
  --query 'ResultsByTime[].Total.UnblendedCost.Amount' \
  --output text)

# Sum the per-period amounts into one number (awk, no hardcoding - operates on live API output).
TOTAL_SUM=$(printf '%s\n' "$TOTAL" | awk '{ s += $1 } END { printf "%.2f", s }')
CURRENCY=$(aws ce get-cost-and-usage \
  --time-period "Start=${START},End=${END}" \
  --granularity "$GRANULARITY" \
  --metrics "UnblendedCost" \
  --filter "$FILTER_JSON" \
  --query 'ResultsByTime[0].Total.UnblendedCost.Unit' \
  --output text 2>/dev/null || echo "USD")

# --- optional per-service breakdown ---
if [[ "$GROUP_BY_SERVICE" == true ]]; then
  echo ">> Fetching per-service breakdown ..."
  aws ce get-cost-and-usage \
    --time-period "Start=${START},End=${END}" \
    --granularity "$GRANULARITY" \
    --metrics "UnblendedCost" \
    --filter "$FILTER_JSON" \
    --group-by "Type=DIMENSION,Key=SERVICE" \
    --query 'ResultsByTime[].Groups[].[Keys[0], Metrics.UnblendedCost.Amount]' \
    --output text \
    | awk '{ svc[$1] += $2 } END { for (s in svc) printf "   %-40s %10.2f\n", s, svc[s] }' \
    | sort -k2 -nr
fi

echo
echo "==========================================================="
echo "  REAL workshop AWS cost (${TAG_KEY}=${TAG_VALUE})"
echo "  Window: ${START} .. ${END}"
echo "  TOTAL:  ${TOTAL_SUM} ${CURRENCY}"
echo "==========================================================="
