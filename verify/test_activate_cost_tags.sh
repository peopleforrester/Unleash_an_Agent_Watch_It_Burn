#!/usr/bin/env bash
# ABOUTME: Behavioural tests for teardown/activate-cost-tags.sh (#392): refuses without a profile or from a linked
# ABOUTME: account, changes nothing on a dry run, and activates project+event and backfills under WIB_APPLY=1. Uses shims.
#
# Usage: verify/test_activate_cost_tags.sh      (no cloud access; aws is a shim)
# shellcheck disable=SC2016,SC2034  # check() evals its single-quoted condition; rc, from and help are read there
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${HERE}/../teardown/activate-cost-tags.sh"
REPORT="${HERE}/../teardown/cost-report.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"; CALLS="${T}/calls"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# ---- shim: records argv and answers from env the test controls ----
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $* [AWS_PROFILE=${AWS_PROFILE:-}]" >>"${CALLS}"
case "$*" in
  *"sts get-caller-identity"*) echo "${CALLER:-111111111111}" ;;
  *"organizations describe-organization"*) echo "${PAYER:-111111111111}" ;;
  *"list-cost-allocation-tags"*) printf '%b' "${TAGS-project\tUserDefined\tInactive\nevent\tUserDefined\tInactive\n}" ;;
  *"update-cost-allocation-tags-status"*) [[ -n "${UPDATE_ERR:-}" ]] && printf '%b\n' "${UPDATE_ERR}" ;;
  *"start-cost-allocation-tag-backfill"*) echo "2026-06-01T00:00:00Z PROCESSING" ;;
esac
exit 0
S
chmod +x "${SHIM}/aws"

# run <VAR=value...>: runs the script with the shim first on PATH and none of the caller's AWS_PROFILE or
# WIB_APPLY leaking in; output in ${T}/out, exit code in rc.
run() { : >"${CALLS}"; rc=0; env -u AWS_PROFILE -u WIB_APPLY PATH="${SHIM}:${PATH}" CALLS="${CALLS}" "$@" bash "${SCRIPT}" "${ARGS[@]}" >"${T}/out" 2>&1 || rc=$?; }
ARGS=()

echo "== no AWS_PROFILE: refuses before calling aws =="
run
check "exits non-zero" '[[ ${rc} -ne 0 ]]'
check "says the payer profile is required" 'grep -q "AWS_PROFILE is required" "${T}/out"'
check "made no aws call" '[[ ! -s "${CALLS}" ]]'

echo "== linked account: refuses, changes nothing =="
run AWS_PROFILE=accen-dev CALLER=222222222222 PAYER=111111111111
check "exits 4" '[[ ${rc} -eq 4 ]]'
check "names it a linked account" 'grep -q "LINKED account" "${T}/out"'
check "no activation call" '! grep -q "update-cost-allocation-tags-status" "${CALLS}"'

echo "== dry run on the payer: reads status, changes nothing =="
run AWS_PROFILE=payer
check "exits 0" '[[ ${rc} -eq 0 ]]'
check "lists both tag keys" 'grep -q "list-cost-allocation-tags --region us-east-1 --tag-keys project event" "${CALLS}"'
check "says DRY-RUN" 'grep -q "DRY-RUN: would activate project event" "${T}/out"'
check "no activation call" '! grep -q "update-cost-allocation-tags-status" "${CALLS}"'
check "no backfill call" '! grep -q "start-cost-allocation-tag-backfill" "${CALLS}"'
check "every aws call carries the given profile" '! grep -v "AWS_PROFILE=payer\]" "${CALLS}" | grep -q .'

echo "== a key billing has not seen yet is called out =="
run AWS_PROFILE=payer TAGS='project\tUserDefined\tInactive\n'
check "notes event is unknown" 'grep -q "'"'"'event'"'"' is not yet known" "${T}/out"'
check "does not note project" '! grep -q "'"'"'project'"'"' is not yet known" "${T}/out"'

echo "== WIB_APPLY=1: activates project and event, then backfills =="
ARGS=(--backfill-from 2026-06-01)
run AWS_PROFILE=payer WIB_APPLY=1
check "exits 0" '[[ ${rc} -eq 0 ]]'
check "activates both keys" 'grep -q "update-cost-allocation-tags-status --region us-east-1 --cost-allocation-tags-status TagKey=project,Status=Active TagKey=event,Status=Active" "${CALLS}"'
check "backfills from the first of the month, as a timestamp" 'grep -q "start-cost-allocation-tag-backfill --region us-east-1 --backfill-from 2026-06-01T00:00:00Z" "${CALLS}"'

echo "== WIB_APPLY=1 --no-backfill: activates only =="
ARGS=(--no-backfill)
run AWS_PROFILE=payer WIB_APPLY=1
check "exits 0" '[[ ${rc} -eq 0 ]]'
check "activates" 'grep -q "update-cost-allocation-tags-status" "${CALLS}"'
check "no backfill call" '! grep -q "start-cost-allocation-tag-backfill" "${CALLS}"'

echo "== activation errors fail the run =="
ARGS=()
run AWS_PROFILE=payer WIB_APPLY=1 UPDATE_ERR='event\tTagKeyNotFound\tTag key not found'
check "exits 5" '[[ ${rc} -eq 5 ]]'
check "prints the failing key" 'grep -q "event.*TagKeyNotFound" "${T}/out"'
check "no backfill after a failed activation" '! grep -q "start-cost-allocation-tag-backfill" "${CALLS}"'

echo "== default backfill start is a first-of-month inside the past twelve months =="
run AWS_PROFILE=payer
from="$(grep -o 'backfill tag status from [0-9-]*' "${T}/out" | awk '{print $NF}')"
check "is YYYY-MM-01" '[[ "${from}" =~ ^[0-9]{4}-[0-9]{2}-01$ ]]'
check "is no more than eleven months before this month" '[[ "${from}" == "$(date -u -d "$(date -u +%Y-%m-01) -11 months" +%Y-%m-01)" ]]'

echo "== a backfill start that is not the first of a month is refused =="
ARGS=(--backfill-from 2026-06-15)
run AWS_PROFILE=payer WIB_APPLY=1
check "exits 2" '[[ ${rc} -eq 2 ]]'
check "made no aws call" '[[ ! -s "${CALLS}" ]]'

echo "== cost-report.sh help names the real default tag and the activation script =="
help="$(bash "${REPORT}" --help)"
check "default key is project" 'grep -q "default: project" <<<"${help}"'
check "points at activate-cost-tags.sh" 'grep -q "activate-cost-tags.sh" <<<"${help}"'

echo
echo "${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
