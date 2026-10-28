#!/usr/bin/env bash
# ABOUTME: Behavioural tests for fleet.sh reconcile-pool (#391): a provisioning row whose cluster is not in
# ABOUTME: any fleet account's eks list-clusters is named, and deregistered only under WIB_APPLY=1. Uses shims.
# ABOUTME: The deregister is `labctl deregister` against lab-platform's pool, not POST /admin/delete (#624).
#
# Usage: verify/test_fleet_pool_reconcile.sh      (no cloud access; aws, curl and labctl are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .fleet-pool-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# The pool as the provisioning app's /admin/roster renders it (templates/admin_roster.html): the state
# cell, the name cell, then claimed-by, claimed-at, console and Datadog org. The org cell deliberately
# carries a watch-it-burn-* string, so a parse that grabbed every name-shaped cell would count it as a row.
roster_page() { # $1: the row count the page claims; remaining: "state|name" rows
  local said="$1"; shift
  printf '<div class="rsum"><span class="pill free">1 free</span></div>\n'
  printf '<p style="font-size:13px;">\n  All %s rows, unclaimed first. Use your browser'"'"'s find.</p>\n' "${said}"
  printf '<table class="rt">\n  <tr><th>State</th><th>Cluster</th><th>Claimed by</th><th>Claimed at (UTC)</th><th>Console</th><th>Datadog org</th></tr>\n'
  local r st nm
  for r in "$@"; do
    st="${r%%|*}"; nm="${r#*|}"
    printf '  <tr class="%s">\n    <td><span class="st %s">%s</span></td>\n    <td class="cn">%s</td>\n' "${st}" "${st}" "${st}" "${nm}"
    printf '    <td class="who">&mdash;</td>\n    <td class="cn">&mdash;</td>\n'
    printf '    <td class="cn"><a href="https://x.agenticburn.com" target="_blank" rel="noopener">https://x.agenticburn.com</a></td>\n'
    printf '    <td class="cn">watch-it-burn-instructor-org</td>\n  </tr>\n'
  done
  printf '</table>\n'
}

# ---- shims: aws answers list-clusters per profile from files; curl serves the roster or a status code ----
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
case "$*" in
  *"/admin/roster"*)
    [[ -n "${ROSTER_DOWN:-}" ]] && exit 22
    out=""; prev=""; for a in "$@"; do [[ "${prev}" == "-o" ]] && out="${a}"; prev="${a}"; done
    cat "${T}/roster.html" >"${out}"; exit 0 ;;
esac
printf '%s' "${CURL_CODE:-200}"
S
# labctl: logs its arguments; LABCTL_RC makes it refuse with that code. Nothing may POST to /admin/delete any more.
cat >"${SHIM}/labctl" <<'S'
#!/usr/bin/env bash
echo "labctl $*" >>"${CALLS}"
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
run() { : >"${T}/log"; SRC_ERR="${T}/log" src 'mkdir -p "${LOG_DIR}"; rc=0; reconcile_pool || rc=$?; echo "rc=${rc}"; echo "--ledger"; cat "${FAIL_FILE}" 2>/dev/null; rm -f "${FAIL_FILE}"' >"${T}/out"; }
reset() { : >"${CALLS}"; rm -f "${T}"/live.*; }

# The state from the issue: one real attendee cluster, one roster row from the retired round naming.
roster_page 2 "free|watch-it-burn-attendee-001" "instructor|watch-it-burn-r2-2" >"${T}/roster.html"

echo "== a ghost is named, and only named, in a dry run =="
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
run
check "the dead roster row is named a ghost" 'grep -q "GHOST  instructor  watch-it-burn-r2-2" "${T}/log"'
check "the live cluster is not" '! grep -q "GHOST.*attendee-001" "${T}/log"'
check "the verdict is non-zero while a ghost remains" 'grep -qx "rc=1" "${T}/out"'
check "the ghost is in the failure ledger as pool-ghost:<name>" 'grep -qx "pool-ghost:watch-it-burn-r2-2" "${T}/out"'
check "nothing is deregistered without WIB_APPLY=1" '! grep -q "^labctl" "${CALLS}"'
check "the Datadog org cell is not read as a row" '! grep -q "instructor-org" "${T}/log"'
check "both accounts were asked, each with its own profile and the region" \
  'grep -q "AWS_PROFILE=acct-a eks list-clusters --region us-west-2" "${CALLS}" && grep -q "AWS_PROFILE=acct-b eks list-clusters --region us-west-2" "${CALLS}"'
check "the default account is not listed twice when it is also an attendee account" \
  '[[ "$(grep -c "AWS_PROFILE=acct-a eks list-clusters" "${CALLS}")" -eq 1 ]]'

echo "== WIB_APPLY=1 deregisters exactly the ghost =="
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
WIB_APPLY=1 run
check "deregisters the ghost through labctl" 'grep -qxF "labctl deregister --customer agenticburn --event test-event watch-it-burn-r2-2" "${CALLS}"'
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
check "and nothing is deregistered" '! grep -q "^labctl" "${CALLS}"'

echo "== it judges nothing it cannot see =="
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
WIB_APPLY=1 LIST_FAIL_PROFILE=acct-b run
check "one account that cannot be listed stops the verdict, deregistering nothing" \
  'grep -qx "rc=1" "${T}/out" && grep -qx "pool:list-clusters-failed:acct-b" "${T}/out" && ! grep -q "^labctl" "${CALLS}"'
reset
WIB_APPLY=1 run
check "every account empty while the pool holds rows is refused without the override" \
  'grep -qx "rc=1" "${T}/out" && grep -qx "pool:zero-live-clusters" "${T}/out" && ! grep -q "^labctl" "${CALLS}"'
reset
WIB_APPLY=1 WIB_RECONCILE_EMPTY_FLEET=1 run
check "with the override (teardown's case) every row goes" '[[ "$(grep -c "^labctl deregister" "${CALLS}")" -eq 2 ]]'
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
WIB_APPLY=1 ROSTER_DOWN=1 run
check "an unreachable roster page is a failure, not a clean pool" \
  'grep -qx "rc=1" "${T}/out" && grep -qx "pool:unreadable" "${T}/out" && ! grep -q "^labctl" "${CALLS}"'
roster_page 3 "free|watch-it-burn-attendee-001" "instructor|watch-it-burn-r2-2" >"${T}/roster.html"
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
WIB_APPLY=1 run
check "a page whose row count disagrees with the parse is refused" \
  'grep -qx "rc=1" "${T}/out" && grep -q "says 3 rows but 2 parsed" "${T}/log" && ! grep -q "^labctl" "${CALLS}"'
printf '<html><body>Admin</body></html>\n' >"${T}/roster.html"
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
run
check "a page that is not the roster is refused" 'grep -qx "rc=1" "${T}/out" && grep -q "printed no row count" "${T}/log"'
roster_page 0 >"${T}/roster.html"
reset; printf 'watch-it-burn-attendee-001\n' >"${T}/live.acct-a"
run
check "an empty pool is clean" 'grep -qx "rc=0" "${T}/out"'
roster_page 2 "free|watch-it-burn-attendee-001" "instructor|watch-it-burn-r2-2" >"${T}/roster.html"
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
