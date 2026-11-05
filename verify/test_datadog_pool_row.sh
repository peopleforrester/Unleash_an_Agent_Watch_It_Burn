#!/usr/bin/env bash
# ABOUTME: Behavioural tests for infra/terraform/fleet/datadog-pool-row.sh (#832): load puts question 926's one row in
# ABOUTME: front of the pool so fleet.sh's own datadog_keys_for resolves attendee-001, and remove restores the pools.
#
# Usage: verify/test_datadog_pool_row.sh      (offline; aws is a shim backed by one file per secret)
# shellcheck disable=SC2016,SC2034  # check() evals its single-quoted condition; P1, P2 and FLEET_SEL are read there
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROW="${HERE}/../infra/terraform/fleet/datadog-pool-row.sh"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .pool-row-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; SM="${T}/sm"; mkdir -p "${SHIM}" "${SM}"; CALLS="${T}/calls"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# Offline means offline (#859): aws, kubectl, eksctl, terraform and helm are stubs that log the call and fail,
# even when the test is run by hand (verify/no-cloud.sh). The last check reads the log.
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${HERE}/no-cloud.sh"; no_cloud_guard "${T}/no-cloud"
[[ -f "${ROW}" ]] || { echo "FAIL: ${ROW} is missing"; exit 1; }

# Secrets Manager, one file per secret id ("/" -> "__"), plus <file>.desc for a created secret's description.
# A secret whose file is absent answers ResourceNotFoundException; ${T}/deny makes every read AccessDenied.
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $*" >>"${CALLS}"
[[ "$1" == "secretsmanager" ]] || exit 0
verb="$2"; shift 2; id="" str="" desc="" query=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --secret-id|--name) id="$2"; shift ;;
    --secret-string) str="$2"; shift ;;
    --description) desc="$2"; shift ;;
    --query) query="$2"; shift ;;
  esac; shift
done
f="${SM}/${id//\//__}"
if [[ -n "${str}" && "${str}" != file://* ]]; then echo "secret on the command line" >&2; exit 9; fi
case "${verb}" in
  get-secret-value)
    [[ -f "${T}/deny" ]] && { echo "An error occurred (AccessDeniedException)" >&2; exit 254; }
    [[ -f "${f}" ]] || { echo "An error occurred (ResourceNotFoundException) when calling the GetSecretValue operation" >&2; exit 254; }
    cat "${f}"; echo ;;
  put-secret-value)
    [[ -f "${f}" ]] || { echo "ResourceNotFoundException" >&2; exit 254; }
    cat "${str#file://}" >"${f}" ;;
  create-secret)
    [[ -f "${f}" ]] && { echo "ResourceExistsException" >&2; exit 254; }
    cat "${str#file://}" >"${f}"; printf '%s' "${desc}" >"${f}.desc" ;;
  describe-secret)
    [[ -f "${f}" ]] || exit 254
    [[ "${query}" == "Description" ]] && { if [[ -f "${f}.desc" ]]; then cat "${f}.desc"; echo; else echo None; fi; } ;;
  delete-secret) rm -f "${f}" "${f}.desc" ;;
esac
exit 0
S
REAL_JQ="$(command -v jq)"
cat >"${SHIM}/jq" <<S
#!/usr/bin/env bash
echo "jq \$*" >>"\${CALLS}"
exec "${REAL_JQ}" "\$@"
S
chmod +x "${SHIM}"/*
export T SM CALLS PATH="${SHIM}:${PATH}"

ADMIN='{"api-key":"INSTRUCTOR_API_9f3c","app-key":"INSTRUCTOR_APP_77aa","org":"sandbox","role":"admin-instructor"}'
P1='/watch-it-burn__datadog-pool'; P2='/watch-it-burn__datadog-pool-2'
put()   { printf '%s' "$2" >"${SM}/$1"; }
reset() { rm -f "${SM}"/* "${T}/deny"; : >"${CALLS}"; put watch-it-burn__datadog "${ADMIN}"; }
row()   { bash "${ROW}" "$@" >"${T}/out" 2>&1; }
norm()  { "${REAL_JQ}" -S -c . "$1"; }
keys()  { ( cd "$(dirname "${FLEET}")" && bash -c "source '${FLEET}' >/dev/null 2>&1; datadog_keys_for $1" 2>/dev/null ); }

echo "== empty pools: the gate #832 names, then load opens it =="
reset; put watch-it-burn__datadog-pool '[]'; put watch-it-burn__datadog-pool-2 '[]'
check "before load, fleet.sh's datadog_keys_for refuses attendee-001" '! keys watch-it-burn-attendee-001 >/dev/null'
check "show says fleet.sh up refuses it" 'row show && grep -q "fleet.sh up refuses it" "${T}/out"'
check "load exits 0" 'row load'
check "after load, fleet.sh resolves attendee-001 to the instructor key on both destinations (one org, #587)" \
  '[[ "$(keys watch-it-burn-attendee-001)" == "INSTRUCTOR_API_9f3c INSTRUCTOR_APP_77aa INSTRUCTOR_API_9f3c INSTRUCTOR_APP_77aa" ]]'
check "the row is non-admin, marked, and carries no Datadog login (#647)" \
  '"${REAL_JQ}" -e ".[0] | .role == \"attendee\" and .\"loaded-by\" == \"datadog-pool-row.sh\" and .org == \"\" and .email == \"\" and .password == \"\" and .site == \"datadoghq.com\"" "${SM}${P1}" >/dev/null'
check "a roster cluster still takes the instructor org alone" \
  '[[ "$(keys watch-it-burn-private)" == "INSTRUCTOR_API_9f3c INSTRUCTOR_APP_77aa  " ]]'
check "attendee-002 still has no org" '! keys watch-it-burn-attendee-002 >/dev/null'
check "show says question 926's one org, naming the key by its last four only" \
  'row show && grep -q "resolves to watch-it-burn/datadog.s key (...9f3c)" "${T}/out" && ! grep -q INSTRUCTOR_ "${T}/out"'
: >"${CALLS}"   # from here, only this script's own calls (fleet.sh's datadog_keys_for passes rows to jq itself)
check "load printed no key" 'row load && ! grep -q INSTRUCTOR_ "${T}/out"'
check "a second load leaves one row, not two" '[[ "$("${REAL_JQ}" length "${SM}${P1}")" == 1 ]]'
check "remove exits 0" 'row remove'
check "no key reached a command line in load, show or remove (aws or jq)" \
  'row show && grep -q "^jq " "${CALLS}" && ! grep -q INSTRUCTOR_ "${CALLS}"'
check "after remove, both pools are empty again" '[[ "$(norm "${SM}${P1}")" == "[]" && "$(norm "${SM}${P2}")" == "[]" ]]'
check "after remove, fleet.sh refuses attendee-001 again" '! keys watch-it-burn-attendee-001 >/dev/null'
check "a second remove changes nothing and says so" 'row remove && grep -q "nothing to remove" "${T}/out" && [[ "$(norm "${SM}${P1}")" == "[]" ]]'

echo "== a pool that already holds rows (Portland's, admin and attendee) =="
reset
OLD1='[{"api-key":"ADMIN_ROW","app-key":"A","role":"admin-instructor"},{"api-key":"OLD1_API","app-key":"OLD1_APP","org":"devops-days-portland-090826-003"}]'
OLD2='[{"api-key":"OLD2_API","app-key":"OLD2_APP","org":"devops-days-portland-090826-150"}]'
put watch-it-burn__datadog-pool "${OLD1}"; put watch-it-burn__datadog-pool-2 "${OLD2}"
check "before load, attendee-001 takes a stale Portland row" '[[ "$(keys watch-it-burn-attendee-001)" == "OLD1_API OLD1_APP INSTRUCTOR_API_9f3c INSTRUCTOR_APP_77aa" ]]'
check "show says attendee-001 is on a pool row's own key" 'row show && grep -q "a pool row.s own key" "${T}/out"'
check "load exits 0 and notes the other rows shift" 'row load && grep -q "2 other non-admin row" "${T}/out"'
check "attendee-001 now resolves to the instructor key, not the stale row" \
  '[[ "$(keys watch-it-burn-attendee-001)" == "INSTRUCTOR_API_9f3c INSTRUCTOR_APP_77aa INSTRUCTOR_API_9f3c INSTRUCTOR_APP_77aa" ]]'
check "the old rows are kept, in order, behind it" \
  '[[ "$("${REAL_JQ}" -c ".[1:]" "${SM}${P1}")" == "$(printf "%s" "${OLD1}" | "${REAL_JQ}" -c .)" ]]'
check "pool-2 is not written by a load that found no row there" '! grep -q "put-secret-value --secret-id watch-it-burn/datadog-pool-2" "${CALLS}"'
check "remove restores both pools exactly" \
  'row remove && [[ "$(norm "${SM}${P1}")" == "$(printf "%s" "${OLD1}" | "${REAL_JQ}" -S -c .)" && "$(norm "${SM}${P2}")" == "$(printf "%s" "${OLD2}" | "${REAL_JQ}" -S -c .)" ]]'

echo "== a marked row left in pool-2 is moved, not doubled =="
reset
put watch-it-burn__datadog-pool '[]'
put watch-it-burn__datadog-pool-2 '[{"role":"attendee","loaded-by":"datadog-pool-row.sh","api-key":"STALE","app-key":"STALE"},{"api-key":"KEEP","app-key":"KEEP"}]'
check "load exits 0" 'row load'
check "pool-2 keeps only its own row" '[[ "$("${REAL_JQ}" -c "map(.\"api-key\")" "${SM}${P2}")" == "[\"KEEP\"]" ]]'
check "pool-1 holds the fresh row" '[[ "$("${REAL_JQ}" -r ".[0].\"api-key\"" "${SM}${P1}")" == "INSTRUCTOR_API_9f3c" ]]'

echo "== missing pool secrets: load creates, remove deletes only what load created =="
reset
check "load exits 0 with neither pool secret present" 'row load && grep -q "created watch-it-burn/datadog-pool" "${T}/out"'
check "fleet.sh resolves attendee-001 from the created secret" \
  '[[ "$(keys watch-it-burn-attendee-001)" == "INSTRUCTOR_API_9f3c INSTRUCTOR_APP_77aa INSTRUCTOR_API_9f3c INSTRUCTOR_APP_77aa" ]]'
check "pool-2 is not created" '[[ ! -f "${SM}${P2}" ]]'
check "remove deletes the secret load created" 'row remove && [[ ! -f "${SM}${P1}" ]] && grep -q "deleted watch-it-burn/datadog-pool" "${T}/out"'
reset; put watch-it-burn__datadog-pool '[]'
check "remove on a pre-existing secret writes [] and keeps it" \
  'row load && row remove && [[ -f "${SM}${P1}" && "$(norm "${SM}${P1}")" == "[]" ]] && ! grep -q delete-secret "${CALLS}"'

echo "== refusals: nothing is written =="
reset; put watch-it-burn__datadog-pool "${OLD1}"; rm -f "${SM}/watch-it-burn__datadog"
check "no instructor secret: load fails and names it" '! row load && grep -q "watch-it-burn/datadog does not exist" "${T}/out"'
check "  and writes nothing" '! grep -q "put-secret-value\|create-secret" "${CALLS}"'
reset; put watch-it-burn__datadog '{"api-key":"","app-key":"x"}'; put watch-it-burn__datadog-pool '[]'
check "an instructor secret without keys: load fails" '! row load && grep -q "has no api-key and app-key" "${T}/out" && ! grep -q put-secret-value "${CALLS}"'
reset; put watch-it-burn__datadog-pool "${OLD1}"; : >"${T}/deny"
check "a pool that cannot be read (access denied) is not taken for empty: load fails" \
  '! row load && grep -q "cannot read" "${T}/out" && ! grep -q "put-secret-value\|create-secret" "${CALLS}"'
check "  and remove fails too" '! row remove && ! grep -q "put-secret-value\|delete-secret" "${CALLS}"'
reset; put watch-it-burn__datadog-pool '{"not":"an array"}'
check "a pool that is not a JSON array is left alone" '! row load && grep -q "not a JSON array" "${T}/out" && ! grep -q put-secret-value "${CALLS}"'
reset
check "no verb prints the usage and exits 2" 'bash "${ROW}" >"${T}/out" 2>&1; [[ $? -eq 2 ]] && grep -q "load" "${T}/out"'

echo "== it reads and writes what fleet.sh reads =="
# The selection must stay fleet.sh's: if datadog_keys_for's expression changes, this script must change with it.
FLEET_SEL='map(select((.role // "") | startswith("admin") | not))'
check "datadog_keys_for still selects non-admin rows with the expression this script copies" \
  'grep -qF "${FLEET_SEL}" "${FLEET}" && grep -qF "${FLEET_SEL}" "${ROW}"'
check "the same profile and region defaults as fleet.sh" \
  'grep -q "WIB_DEFAULT_ACCOUNT:-accen-dev" "${ROW}" && grep -q "WIB_SECRETS_REGION:-\${WIB_HOME_REGION" "${ROW}" && grep -q "WIB_HOME_REGION:-us-west-2" "${FLEET}"'

echo
echo "== offline means offline =="
check "no check above called aws, kubectl, eksctl, terraform or helm" 'no_cloud_clean'

echo "${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
