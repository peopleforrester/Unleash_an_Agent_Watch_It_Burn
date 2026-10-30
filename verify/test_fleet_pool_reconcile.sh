#!/usr/bin/env bash
# ABOUTME: Behavioural tests for fleet.sh reconcile-pool (#391): a pool row whose cluster is not in any fleet
# ABOUTME: account's eks list-clusters is named, and deregistered only under WIB_APPLY=1. Uses shims.
# ABOUTME: The pool is read with `labctl pool` and deregistered with `labctl deregister`, both lab-platform's
# ABOUTME: handout pool (#656, #624), not the provisioning app's /admin/roster and /admin/delete.
#
# Usage: verify/test_fleet_pool_reconcile.sh      (no cloud access; aws, curl and labctl are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .fleet-pool-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# The pool as `labctl pool --customer <c> --event <e>` writes it (lab-platform#302, store.WritePoolCSV): Go's
# encoding/csv under the header cluster_name,state,region,reserved_for,claimed_by. Every row carries a
# claimed_by address with a comma in it, which Go quotes, so a parse that split on commas would count six fields.
pool_csv() { # remaining: "state|name" rows
  printf 'cluster_name,state,region,reserved_for,claimed_by\n'
  local r
  for r in "$@"; do printf '%s,%s,us-west-2,,"a,b@example.com"\n' "${r#*|}" "${r%%|*}"; done
}

# ---- shims: aws answers list-clusters per profile from files; curl answers a status code ----
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws AWS_PROFILE=${AWS_PROFILE:-} $*" >>"${CALLS}"
case "$*" in
  *"eks list-clusters"*)
    [[ "${AWS_PROFILE:-}" == "${LIST_FAIL_PROFILE:-none}" ]] && { echo "ExpiredToken" >&2; exit 255; }
    f="${T}/live.${AWS_PROFILE:-}"; [[ -f "${f}" ]] && cat "${f}"; exit 0 ;;
esac
exit 0
S
cat >"${SHIM}/curl" <<'S'
#!/usr/bin/env bash
echo "curl $*" >>"${CALLS}"
printf '%s' "${CURL_CODE:-200}"
S
# labctl: logs its arguments, and whether it saw USER. `pool` writes ${T}/pool.csv, or fails as an unknown event
# does when POOL_RC is set. Any other verb refuses with LABCTL_RC when that is set. Nothing may read /admin/roster
# or POST to /admin/delete any more.
cat >"${SHIM}/labctl" <<'S'
#!/usr/bin/env bash
echo "labctl $* [USER=${USER:-}]" >>"${CALLS}"
if [[ "${1:-}" == pool ]]; then
  [[ -z "${POOL_RC:-}" ]] || { echo "labctl: no event agenticburn/test-event (test)" >&2; exit "${POOL_RC}"; }
  cat "${T}/pool.csv"; exit 0
fi
[[ "${LABCTL_RC:-0}" -eq 0 ]] || { echo "labctl: ${!#} is claimed (test)" >&2; exit "${LABCTL_RC}"; }
S
for c in terraform railway; do printf '#!/usr/bin/env bash\necho "%s $*" >>"${CALLS}"\nexit 0\n' "$c" >"${SHIM}/$c"; done
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"
src() { # $1: bash snippet to run after sourcing fleet.sh (its source guard keeps main() from running)
  ( cd "$(dirname "${FLEET}")" && WIB_ADMIN_TOKEN=test-token WIB_PROVISIONING_URL=https://prov.test \
      DATABASE_URL=postgresql://lab@db.test/lab USER=tester WIB_EVENT=test-event \
      WIB_ATTENDEE_ACCOUNTS=acct-a,acct-b WIB_DEFAULT_ACCOUNT=acct-a WIB_REGION=us-west-2 \
      bash -c "source '${FLEET}' >/dev/null 2>&1; $1" 2>>"${SRC_ERR:-${T}/stderr}" )
}
# The verdict, the failure ledger and the log of one reconcile_pool run.
# Called as every caller in fleet.sh calls it (`reconcile_pool || ...`), so errexit is off inside it there too.
_RUN='mkdir -p "${LOG_DIR}"; rc=0; reconcile_pool || rc=$?; echo "rc=${rc}"; echo "--ledger"; cat "${FAIL_FILE}" 2>/dev/null; rm -f "${FAIL_FILE}"'
run() { : >"${T}/log"; SRC_ERR="${T}/log" src "${_RUN}" >"${T}/out"; }
run_without() { : >"${T}/log"; SRC_ERR="${T}/log" src "unset $1; ${_RUN}" >"${T}/out"; } # $1: a variable to unset
reset() { : >"${CALLS}"; rm -f "${T}"/live.*; }

# The state from the issue: one real attendee cluster, one roster row from the retired round naming.
pool_csv "claimable|watch-it-burn-attendee-001" "instructor|watch-it-burn-r2-2" >"${T}/pool.csv"
dereg() { grep "^labctl deregister" "${CALLS}"; }

echo "== a ghost is named, and only named, in a dry run =="
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
run
check "the dead roster row is named a ghost" 'grep -q "GHOST  instructor  watch-it-burn-r2-2" "${T}/log"'
check "the live cluster is not" '! grep -q "GHOST.*attendee-001" "${T}/log"'
check "the verdict is non-zero while a ghost remains" 'grep -qx "rc=1" "${T}/out"'
check "the ghost is in the failure ledger as pool-ghost:<name>" 'grep -qx "pool-ghost:watch-it-burn-r2-2" "${T}/out"'
check "nothing is deregistered without WIB_APPLY=1" '[[ -z "$(dereg)" ]]'
check "the pool is read from lab-platform through labctl pool, for the fleet's event" \
  'grep -qxF "labctl pool --customer agenticburn --event test-event [USER=tester]" "${CALLS}"'
check "and not from the provisioning app's /admin/roster" '! grep -q "admin/roster" "${CALLS}"'
check "a quoted address with a comma in it is one field, so its row fits the header" \
  '! grep -q "does not fit its header" "${T}/log" && ! grep -q "example.com" "${T}/log"'
check "both accounts were asked, each with its own profile and the region" \
  'grep -q "AWS_PROFILE=acct-a eks list-clusters --region us-west-2" "${CALLS}" && grep -q "AWS_PROFILE=acct-b eks list-clusters --region us-west-2" "${CALLS}"'
check "the default account is not listed twice when it is also an attendee account" \
  '[[ "$(grep -c "AWS_PROFILE=acct-a eks list-clusters" "${CALLS}")" -eq 1 ]]'

echo "== WIB_APPLY=1 deregisters exactly the ghost =="
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
WIB_APPLY=1 run
check "deregisters the ghost through labctl" 'grep -qxF "labctl deregister --customer agenticburn --event test-event watch-it-burn-r2-2 [USER=tester]" "${CALLS}"'
check "and nothing else" '[[ "$(grep -c "^labctl deregister" "${CALLS}")" -eq 1 ]] && ! grep -q "admin/delete" "${CALLS}"'
check "a clean deregister is a zero verdict" 'grep -qx "rc=0" "${T}/out"'
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
WIB_APPLY=1 LABCTL_RC=1 run
check "a refused deregister is a non-zero verdict, recorded as deregister:<name>" \
  'grep -qx "rc=1" "${T}/out" && grep -qx "deregister:watch-it-burn-r2-2" "${T}/out"'

echo "== a cluster in any fleet account keeps its row =="
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"; printf 'watch-it-burn-r2-2\twatch-it-burn-other\n' >"${T}/live.acct-b"
WIB_APPLY=1 run
check "a pool that matches the live fleet is clean" 'grep -qx "rc=0" "${T}/out" && grep -q "all 2 row(s) name a live cluster" "${T}/log"'
check "and nothing is deregistered" '[[ -z "$(dereg)" ]]'

echo "== it judges nothing it cannot see =="
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
WIB_APPLY=1 LIST_FAIL_PROFILE=acct-b run
check "one account that cannot be listed stops the verdict, deregistering nothing" \
  'grep -qx "rc=1" "${T}/out" && grep -qx "pool:list-clusters-failed:acct-b" "${T}/out" && [[ -z "$(dereg)" ]]'
reset
WIB_APPLY=1 run
check "every account empty while the pool holds rows is refused without the override" \
  'grep -qx "rc=1" "${T}/out" && grep -qx "pool:zero-live-clusters" "${T}/out" && [[ -z "$(dereg)" ]]'
reset
WIB_APPLY=1 WIB_RECONCILE_EMPTY_FLEET=1 run
check "with the override (teardown's case) every row goes" '[[ "$(grep -c "^labctl deregister" "${CALLS}")" -eq 2 ]]'
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
WIB_APPLY=1 POOL_RC=1 run
check "an event labctl does not know is a failure, not a clean pool" \
  'grep -qx "rc=1" "${T}/out" && grep -qx "pool:unreadable" "${T}/out" && grep -q "no event agenticburn/test-event" "${T}/log" && [[ -z "$(dereg)" ]]'
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
WIB_APPLY=1 run_without DATABASE_URL
check "no DATABASE_URL is a failure, and labctl is not run" \
  'grep -qx "rc=1" "${T}/out" && grep -qx "pool:unreadable" "${T}/out" && grep -q "DATABASE_URL is not set" "${T}/log" && ! grep -q "^labctl" "${CALLS}"'
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
run_without USER
check "reading the pool needs no USER, so a dry run still names the ghost" \
  'grep -qxF "labctl pool --customer agenticburn --event test-event [USER=]" "${CALLS}" && grep -q "GHOST  instructor  watch-it-burn-r2-2" "${T}/log"'
printf 'name,status\nwatch-it-burn-attendee-001,ready\n' >"${T}/pool.csv"
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
WIB_APPLY=1 run
check "output without the cluster_name,state header is refused" \
  'grep -qx "rc=1" "${T}/out" && grep -q "wrote no cluster_name,state header" "${T}/log" && [[ -z "$(dereg)" ]]'
: >"${T}/pool.csv"
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
WIB_APPLY=1 run
check "empty output, not even the header, is refused" \
  'grep -qx "rc=1" "${T}/out" && grep -q "wrote no cluster_name,state header" "${T}/log" && [[ -z "$(dereg)" ]]'
printf 'cluster_name,state,region,reserved_for,claimed_by\nwatch-it-burn-attendee-001,claimable\n' >"${T}/pool.csv"
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
WIB_APPLY=1 run
check "a row that does not fit the header is refused" \
  'grep -qx "rc=1" "${T}/out" && grep -q "does not fit its header" "${T}/log" && [[ -z "$(dereg)" ]]'
pool_csv >"${T}/pool.csv"
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
run
check "an empty pool (the header alone) is clean" 'grep -qx "rc=0" "${T}/out" && grep -q "all 0 row(s)" "${T}/log"'
pool_csv "claimable|watch-it-burn-attendee-001" "instructor|watch-it-burn-r2-2" >"${T}/pool.csv"
reset
WIB_NO_INGEST=1 WIB_APPLY=1 run
check "WIB_NO_INGEST=1 opts out (no request made)" 'grep -qx "rc=0" "${T}/out" && ! grep -qE "^(curl|labctl)" "${CALLS}"'

echo "== wiring =="
check "reconcile-pool is a subcommand" 'grep -q "reconcile-pool) cmd_reconcile_pool" "${FLEET}"'
_down="$(sed -n '/^cmd_down() {/,/^}/p' "${FLEET}")"
_downfleet="$(sed -n '/^cmd_down_fleet() {/,/^}/p' "${FLEET}")"
check "down all reconciles the pool" 'grep -q "WIB_RECONCILE_EMPTY_FLEET=1 reconcile_pool" <<<"${_down}"'
check "down-fleet reconciles the pool" 'grep -q "WIB_RECONCILE_EMPTY_FLEET=1 reconcile_pool" <<<"${_downfleet}"'
check "the hygiene gate surveys the pool, dry-run" \
  'grep -q "env -u WIB_APPLY .*fleet.sh\" reconcile-pool" "${HERE}/fleet-hygiene.sh"'

echo; echo "  ${pass} passed, ${fail} failed"
[[ -s "${T}/stderr" ]] && { echo "  (stderr from sourced runs, last lines)"; tail -5 "${T}/stderr" | sed 's/^/    /'; }
exit $(( fail > 0 ))
