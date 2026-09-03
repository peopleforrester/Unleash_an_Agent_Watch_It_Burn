#!/usr/bin/env bash
# ABOUTME: Queries AWS Cost Explorer for the real workshop spend across the workshop EKS clusters
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
# The tag our resources ACTUALLY carry is project=watch-it-burn, stamped by the provider default_tags in
# both terraform roots. The default here was `workshop`, which nothing sets, so every run of this script
# returned "TOTAL: 0.00 USD" and read as a free workshop rather than as a filter that matched nothing.
# Measured 2026-09-03 against the AI Engineer World's Fair window.
TAG_KEY="${COST_TAG_KEY:-project}"            # cost-allocation tag key on hub+spoke resources
TAG_VALUE="${COST_TAG_VALUE:-watch-it-burn}"  # tag value identifying this workshop run

# WHY A TAG-FILTERED NUMBER MAY STILL COME BACK ZERO, AND IT IS NOT THIS SCRIPT.
# accen-dev is a LINKED account in an AWS Organization. Cost-allocation tags are activated on the PAYER
# account only, and a linked account cannot even list them:
#   AccessDeniedException: Linked account doesn't have access to cost allocation tags
# Until `project` is activated by whoever owns the payer account, Cost Explorer cannot group or filter by
# it and a tag-filtered query is structurally empty. The unfiltered fallback below is the honest answer
# available from here: it is the WHOLE account, so on a co-tenant account it is an upper bound that
# includes the other project, never a workshop-only figure.
GRANULARITY="DAILY"                        # DAILY | MONTHLY
GROUP_BY_SERVICE=false                     # --by-service to break the total down per AWS service

usage() {
  cat <<'EOF'
Usage: cost-report.sh --start YYYY-MM-DD --end YYYY-MM-DD [options]

Prints the REAL AWS cost (from Cost Explorer) for the workshop run window, summed across the
workshop EKS clusters identified by a cost-allocation tag. The number is queried live, never
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

# A zero here is almost always the linked-account limitation above, not a free workshop. Say so, and show
# the unfiltered account total for the same window so the run has a number rather than a silence.
if [[ -z "${TOTAL_SUM:-}" ]] || awk -v v="${TOTAL_SUM:-0}" 'BEGIN{exit !(v+0==0)}'; then
  echo
  echo ">> Tag-filtered total is 0.00, which on this account almost certainly means the"
  echo "   '${TAG_KEY}' cost-allocation tag is not activated on the PAYER account rather than"
  echo "   that nothing was spent. A linked account cannot activate it."
  echo ">> Unfiltered total for the same window (WHOLE ACCOUNT, includes any co-tenant project):"
  aws ce get-cost-and-usage --region us-east-1 \
      --time-period "Start=${START},End=${END}" --granularity MONTHLY --metrics UnblendedCost \
      --query 'ResultsByTime[].Total.UnblendedCost.[Amount,Unit]' --output text 2>/dev/null \
    | awk '{printf "     %.2f %s\n", $1, $2}'
  echo "   Treat that as an upper bound, never as the workshop's cost."
fi
