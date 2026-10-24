#!/usr/bin/env bash
# ABOUTME: Activates the `project` and `event` cost-allocation tags on the PAYER account and backfills them,
# ABOUTME: so teardown/cost-report.sh returns a real tag-filtered figure. Run with payer credentials; DRY-RUN by default.
#
# Why this exists (#392): every resource carries project=watch-it-burn and event=<delivery> from the
# terraform default_tags, but Cost Explorer cannot filter on a tag until it is activated, and only the
# management (payer) account of the Organization can activate one. A linked account like accen-dev gets
#   AccessDeniedException: Linked account doesn't have access to cost allocation tags
# so cost-report.sh run from there comes back 0.00 USD. Nothing in this repo can fix that from a linked
# account; this script is the one action, scripted, for whoever holds the payer credentials.
#
# Activation alone only counts spend from the activation date forward. Cost Explorer also takes a backfill
# request (StartCostAllocationTagBackfill) that applies the current activation status to billing data as
# far back as the previous twelve months, starting on the first of a month. Backfilling recovers the AI
# Engineer World's Fair (2026-06-29) and Portland (2026-09-08) windows, which the tags already covered on
# the resources but which were never activated.
#
# Usage:
#   AWS_PROFILE=<payer-profile> teardown/activate-cost-tags.sh                  # dry run: show status, change nothing
#   AWS_PROFILE=<payer-profile> WIB_APPLY=1 teardown/activate-cost-tags.sh      # activate + backfill
#   ... --backfill-from 2026-06-01                                              # backfill start, first of a month
#   ... --no-backfill                                                           # activate only
#
# Then, from any account with Cost Explorer access, over a window with fleet activity:
#   teardown/cost-report.sh --start 2026-09-06 --end 2026-09-12
# AWS says activated tags can take up to 24 hours to show in Cost Explorer, and a backfill runs
# asynchronously: check it with `aws ce list-cost-allocation-tag-backfill-history --region us-east-1`.

set -euo pipefail

TAG_KEYS=(project event)   # the keys default_tags stamps in both terraform roots (infra/terraform/aws/*/main.tf)
CE_REGION="us-east-1"      # Cost Explorer has one endpoint, in us-east-1
BACKFILL=true
# The earliest start AWS accepts is the previous twelve months, and the docs do not say whether that counts
# from today or from the first of this month, so the default is eleven months back from the first of this
# month: earlier than every delivery so far (June 2026), and inside the window whichever way it is counted.
BACKFILL_FROM="$(date -u -d "$(date -u +%Y-%m-01) -11 months" +%Y-%m-01)"

usage() { sed -n '/^# Usage:/,/^# asynchronously/p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backfill-from) BACKFILL_FROM="$2"; shift 2 ;;
    --no-backfill)   BACKFILL=false; shift ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if ! [[ "${BACKFILL_FROM}" =~ ^[0-9]{4}-[0-9]{2}-01$ ]]; then
  echo "ERROR: --backfill-from must be the first of a month, YYYY-MM-01 (got '${BACKFILL_FROM}')." >&2
  exit 2
fi

# The profile is required and explicit (CLAUDE.md rule 6): a shared default profile is exactly how this would
# run against the linked account, fail, and leave nobody sure which account was asked.
if [[ -z "${AWS_PROFILE:-}" ]]; then
  echo "ERROR: AWS_PROFILE is required and must name the PAYER (management) account's profile." >&2
  exit 2
fi
if ! command -v aws >/dev/null 2>&1; then
  echo "ERROR: required tool not found on PATH: aws" >&2
  exit 3
fi

caller="$(aws sts get-caller-identity --query Account --output text)"
payer="$(aws organizations describe-organization --query Organization.MasterAccountId --output text 2>/dev/null || true)"
echo ">> profile ${AWS_PROFILE}: account ${caller}, organization payer ${payer:-unknown}"
if [[ -z "${payer}" || "${payer}" == "None" ]]; then
  echo "ERROR: could not read the Organization's management account from profile ${AWS_PROFILE}." >&2
  echo "       This must run with the PAYER account's credentials; a linked account cannot activate tags." >&2
  exit 4
fi
if [[ "${caller}" != "${payer}" ]]; then
  echo "ERROR: account ${caller} is a LINKED account; the payer is ${payer}." >&2
  echo "       Only the payer account can activate cost-allocation tags. Re-run with its profile." >&2
  exit 4
fi

echo ">> Current status of ${TAG_KEYS[*]}:"
status="$(aws ce list-cost-allocation-tags --region "${CE_REGION}" --tag-keys "${TAG_KEYS[@]}" \
            --query 'CostAllocationTags[].[TagKey,Type,Status]' --output text)"
printf '%s\n' "${status:-   (none listed)}" | sed 's/^/   /'
for k in "${TAG_KEYS[@]}"; do
  # A user-defined key only appears here once billing has seen it on a resource. If it is absent, activation
  # will fail for it; the fix is a fleet up, then a day for the key to arrive, not anything in this script.
  if ! printf '%s\n' "${status}" | awk -v k="${k}" '$1 == k { f = 1 } END { exit !f }'; then
    echo "   NOTE: '${k}' is not yet known to billing on this payer account; activation will report an error for it."
  fi
done

entries=()
for k in "${TAG_KEYS[@]}"; do entries+=("TagKey=${k},Status=Active"); done

if [[ -z "${WIB_APPLY:-}" ]]; then
  echo ">> DRY-RUN: would activate ${TAG_KEYS[*]}"
  [[ "${BACKFILL}" == true ]] && echo ">> DRY-RUN: would backfill tag status from ${BACKFILL_FROM}"
  echo "   Set WIB_APPLY=1 to make the change."
  exit 0
fi

echo ">> Activating ${TAG_KEYS[*]} ..."
errors="$(aws ce update-cost-allocation-tags-status --region "${CE_REGION}" \
            --cost-allocation-tags-status "${entries[@]}" \
            --query 'Errors[].[TagKey,Code,Message]' --output text)"
if [[ -n "${errors}" && "${errors}" != "None" ]]; then
  echo "ERROR: activation failed for:" >&2
  printf '%s\n' "${errors}" | sed 's/^/   /' >&2
  exit 5
fi
echo "   activated (idempotent: an already-active key is left as it is)"

if [[ "${BACKFILL}" == true ]]; then
  echo ">> Requesting backfill from ${BACKFILL_FROM} (once per 24h; runs asynchronously) ..."
  aws ce start-cost-allocation-tag-backfill --region "${CE_REGION}" \
      --backfill-from "${BACKFILL_FROM}T00:00:00Z" \
      --query 'BackfillRequest.[BackfillFrom,BackfillStatus]' --output text | sed 's/^/   /'
fi

echo ">> Done. Allow up to 24 hours, then: teardown/cost-report.sh --start <YYYY-MM-DD> --end <YYYY-MM-DD>"
