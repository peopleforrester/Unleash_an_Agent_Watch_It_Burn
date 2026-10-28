#!/usr/bin/env bash
# ABOUTME: Behavioural tests for #445: fleet.sh takes every terminal login through provisioning-agenticburn's
# ABOUTME: harvest_terminal_credential.sh (user:password, never a bare password) and `ingest pool` re-ingests. Shims.
# ABOUTME: Each row goes to lab-platform through `labctl import` as pool.csv on stdin, a roster row as role=instructor (#600).
#
# Usage: verify/test_fleet_terminal_harvest.sh      (no cloud access; aws, kubectl, curl, labctl and the harvester are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; PROV="${T}/prov"; POOL="${T}/pool"
mkdir -p "${SHIM}" "${PROV}/scripts" "${POOL}" "${T}/states" "${T}/imports"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# ctrue <file> <python expression over d>: <file> is a pool.csv header and exactly one row, and that row, read as a
# dict d, satisfies the expression.
ctrue() { python3 -c 'import csv, sys
rows = list(csv.DictReader(open(sys.argv[1], newline="")))
sys.exit(0 if len(rows) == 1 and eval(sys.argv[2], {"d": rows[0]}) else 1)' "$1" "$2" 2>/dev/null; }

# ---- the harvester, as provisioning-agenticburn#16 specifies it: <cluster> [region] [out-dir]; 0 written,
# 3 Secret absent, 1 unreachable/unreadable/malformed. On a non-zero exit this shim LEAVES a stale file, so the
# tests prove fleet.sh itself never lets one survive, whatever the harvester does.
cat >"${PROV}/scripts/harvest_terminal_credential.sh" <<'S'
#!/usr/bin/env bash
echo "harvest $* [AWS_PROFILE=${AWS_PROFILE:-}]" >>"${CALLS}"
out="${3:?out-dir}/$1.terminal"
rc="${HARVEST_RC:-0}"
if [[ "${rc}" -eq 0 ]]; then printf '%s\n' "${HARVEST_CRED:-agentic:agentic}" >"${out}"; else echo stale >"${out}"; fi
exit "${rc}"
S
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $* [AWS_PROFILE=${AWS_PROFILE:-}]" >>"${CALLS}"; exit 0
S
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $* [AWS_PROFILE=${AWS_PROFILE:-}]" >>"${CALLS}"
case "$*" in
  *"get svc console"*) printf 'k8s-agent-console-abc.elb.us-west-2.amazonaws.com' ;;
  *"get secret terminal-auth"*) [[ -n "${LIVE_CRED:-}" ]] && printf '%s' "${LIVE_CRED}" | base64 ;;
esac
exit 0
S
# labctl: every `import` keeps its stdin, numbered, for the assertions, and logs its arguments and whether it saw
# DATABASE_URL and USER. LABCTL_RC makes every import fail with that exit code.
cat >"${SHIM}/labctl" <<'S'
#!/usr/bin/env bash
echo "labctl $* [DATABASE_URL=${DATABASE_URL:-} USER=${USER:-}]" >>"${CALLS}"
[[ "${LABCTL_RC:-0}" -eq 0 ]] || { echo "labctl: import refused (test)" >&2; exit "${LABCTL_RC}"; }
n="$(ls "${T}/imports" | wc -l)"; cat >"${T}/imports/$((n + 1)).csv"
S
# curl: /admin/roster serves ${T}/roster.html. Nothing may POST to /admin/import any more.
cat >"${SHIM}/curl" <<'S'
#!/usr/bin/env bash
echo "curl $*" >>"${CALLS}"
data=""; out=""; url=""; prev=""
for a in "$@"; do
  [[ "${prev}" == "--data" ]] && data="${a}"; [[ "${prev}" == "-o" ]] && out="${a}"
  [[ "${a}" == http* ]] && url="${a}"; prev="${a}"
done
case "${url}" in
  */admin/roster) [[ -n "${ROSTER_DOWN:-}" ]] && exit 22; cat "${T}/roster.html" >"${out}"; exit 0 ;;
  *) printf 404 ;;
esac
S
printf '#!/usr/bin/env bash\necho "terraform $*" >>"${CALLS}"\nexit 0\n' >"${SHIM}/terraform"
chmod +x "${SHIM}"/* "${PROV}/scripts/harvest_terminal_credential.sh"
export T CALLS PATH="${SHIM}:${PATH}"

A=watch-it-burn-attendee-007; B=watch-it-burn-attendee-008; ADMIN=watch-it-burn-whitney-admin
COMMUNITY=watch-it-burn-community
for n in "${A}" "${B}" "${ADMIN}" "${COMMUNITY}"; do
  touch "${T}/states/${n}.tfstate"
  printf 'user,cluster,access_key,secret_key\nu,%s,AKIAREAL%s,secret%s\n' "${n}" "${n##*-}" "${n##*-}" >"${POOL}/${n}.csv"
done
echo accen-qa >"${T}/states/${A}.account"
# Sourcing fleet.sh: the source guard keeps main() from running; WIB_* settings point every path at ${T}.
src() { # $1: bash snippet to run after sourcing
  ( cd "$(dirname "${FLEET}")" && WIB_ADMIN_TOKEN=test-token WIB_PROVISIONING_URL=https://prov.test \
      DATABASE_URL="${TEST_DATABASE_URL-postgresql://lab@db.test/lab}" USER="${TEST_USER-tester}" WIB_EVENT=test-event \
      WIB_PROVISION_DIR="${PROVISION_DIR_OVERRIDE:-${PROV}}" WIB_DEFAULT_ACCOUNT=acct-default WIB_REGION=us-west-2 \
      WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" WIB_AWS_POOL_DIR="${POOL}" WIB_INGEST_LB_WAIT=10 \
      bash -c "source '${FLEET}' >/dev/null 2>&1; POOL1='[]'; POOL2='[]'; sleep() { :; }; $1" 2>>"${T}/stderr" )
}
reset() { : >"${CALLS}"; : >"${T}/stderr"; rm -f "${T}"/imports/* "${POOL}"/*.terminal "${T}"/logs/.failures.*; }
ledger() { cat "${T}"/logs/.failures.* 2>/dev/null; }

echo "== harvest_terminal_login runs the harvester from WIB_PROVISION_DIR =="
reset
src "harvest_terminal_login ${A} accen-qa"; rc=$?
check "exit 0 when the harvester wrote the login" '[[ "${rc}" -eq 0 ]]'
check "calls <cluster> <region> <out-dir> in the cluster's account" \
  'grep -qxF "harvest ${A} us-west-2 ${POOL} [AWS_PROFILE=accen-qa]" "${CALLS}"'
check "the file holds the whole user:password value" '[[ "$(cat "${POOL}/${A}.terminal")" == agentic:agentic ]]'
for code in 3 1; do
  reset; echo "agentic" >"${POOL}/${A}.terminal"
  HARVEST_RC="${code}" src "harvest_terminal_login ${A} accen-qa"; rc=$?
  check "harvester exit ${code} is passed through" '[[ "${rc}" -eq "${code}" ]]'
  check "harvester exit ${code} leaves no stale .terminal file" '[[ ! -e "${POOL}/${A}.terminal" ]]'
done
check "a Secret-absent exit says the terminal is open" 'HARVEST_RC=3 src "harvest_terminal_login ${A} accen-qa"; grep -q "terminal is OPEN" "${T}/stderr"'
reset; echo "agentic" >"${POOL}/${A}.terminal"
PROVISION_DIR_OVERRIDE="${T}/nowhere" src "harvest_terminal_login ${A} accen-qa"; rc=$?
check "a missing harvester is exit 1, named, and removes the stale file" \
  '[[ "${rc}" -eq 1 ]] && grep -q "terminal harvester missing: ${T}/nowhere/scripts/harvest_terminal_credential.sh" "${T}/stderr" && [[ ! -e "${POOL}/${A}.terminal" ]]'
reset
src "harvest_terminal_login ${A} ''"; rc=$?
check "no account is a failure, never the default profile" '[[ "${rc}" -eq 1 ]] && ! grep -q "^harvest" "${CALLS}"'

echo "== bootstrap_terminal_auth harvests instead of writing a bare password =="
reset
LIVE_CRED=agentic:agentic src "mkdir -p \"\${LOG_DIR}\"; bootstrap_terminal_auth ${A} accen-qa ${T}/kcfg"
check "an existing Secret is harvested" 'grep -qxF "harvest ${A} us-west-2 ${POOL} [AWS_PROFILE=accen-qa]" "${CALLS}"'
check "and the file is user:password" '[[ "$(cat "${POOL}/${A}.terminal")" == agentic:agentic ]]'
check "and no Secret is created over it" '! grep -q "create secret" "${CALLS}"'
reset
src "mkdir -p \"\${LOG_DIR}\"; bootstrap_terminal_auth ${A} accen-qa ${T}/kcfg"
check "a new Secret gets the student login" 'grep -q "create secret generic terminal-auth -n agent --from-literal=TTYD_CREDENTIAL=agentic:agentic" "${CALLS}"'
check "then is read back through the harvester" 'grep -n "create secret\|^harvest" "${CALLS}" | tail -1 | grep -q harvest'
reset
HARVEST_RC=1 src "mkdir -p \"\${LOG_DIR}\"; bootstrap_terminal_auth ${A} accen-qa ${T}/kcfg"
check "a failed harvest is recorded by name and leaves no file" \
  'ledger | grep -qx "${A}:terminal-harvest" && [[ ! -e "${POOL}/${A}.terminal" ]]'

echo "== ingest sends terminal_user and terminal_password exactly as the Secret holds them =="
reset
HARVEST_CRED='agentic:pa:ss' src "mkdir -p \"\${LOG_DIR}\"; ingest_one ${A} accen-qa"
check "one import is sent to labctl" '[[ "$(ls "${T}/imports" | wc -l)" -eq 1 ]]'
check "the user and password are the harvested value, split on the first colon" \
  'ctrue "${T}/imports/1.csv" "d[\"terminal_user\"] == \"agentic\" and d[\"terminal_password\"] == \"pa:ss\""'
check "the harvest ran in the cluster's account" 'grep -qxF "harvest ${A} us-west-2 ${POOL} [AWS_PROFILE=accen-qa]" "${CALLS}"'
check "ingest does not read the Secret itself" '! grep -q "get secret terminal-auth" "${CALLS}"'
reset
HARVEST_CRED='sprouts:sprouts' src "mkdir -p \"\${LOG_DIR}\"; ingest_one ${ADMIN} acct-default"
check "an admin cluster sends what its Secret holds" \
  'ctrue "${T}/imports/1.csv" "d[\"terminal_user\"] == \"sprouts\" and d[\"terminal_password\"] == \"sprouts\""'
reset; echo "sprouts" >"${POOL}/${A}.terminal"
HARVEST_RC=1 src "mkdir -p \"\${LOG_DIR}\"; ingest_one ${A} accen-qa"
check "an unreadable cluster is not registered" '[[ "$(ls "${T}/imports" | wc -l)" -eq 0 ]]'
check "and is a retryable ingest failure" 'ledger | grep -qx "ingest:${A}"'
check "and the stale cached password is not used" '[[ ! -e "${POOL}/${A}.terminal" ]] && ! grep -q "cached password" "${T}/stderr"'
reset
HARVEST_RC=3 src "mkdir -p \"\${LOG_DIR}\"; ingest_one ${A} accen-qa"
check "an open terminal is registered with no login" \
  'ctrue "${T}/imports/1.csv" "d[\"terminal_user\"] == \"\" and d[\"terminal_password\"] == \"\""'
check "and fails the run by name" 'ledger | grep -qx "terminal-open:${A}"'
reset
HARVEST_CRED='agentic' src "mkdir -p \"\${LOG_DIR}\"; ingest_one ${A} accen-qa"
check "a bare password file is refused, not completed with a guess" \
  '[[ "$(ls "${T}/imports" | wc -l)" -eq 0 ]] && ledger | grep -qx "ingest:${A}"'

echo "== ingest registers through labctl import, a roster cluster as role=instructor (#600) =="
reset
src "mkdir -p \"\${LOG_DIR}\"; ingest_one ${A} accen-qa"
check "labctl runs import --customer agenticburn --event <the fleet's event> -, with DATABASE_URL and USER" \
  'grep -qxF "labctl import --customer agenticburn --event test-event - [DATABASE_URL=postgresql://lab@db.test/lab USER=tester]" "${CALLS}"'
check "nothing is POSTed to /admin/import" '! grep -q "admin/import" "${CALLS}"'
check "stdin is a pool.csv header and one row, keyed by the cluster name" 'ctrue "${T}/imports/1.csv" "d[\"name\"] == \"${A}\""'
check "the header carries the row's own columns, role last" \
  '[[ "$(head -1 "${T}/imports/1.csv")" == \"name\",\"region\",\"access_key\",\"secret_key\",\"console_url\",*,\"datadog_dashboard_url\",\"role\" ]]'
check "an attendee row has an empty role, so it is claimable" 'ctrue "${T}/imports/1.csv" "d[\"role\"] == \"\""'
for n in "${ADMIN}" "${COMMUNITY}"; do
  reset
  src "mkdir -p \"\${LOG_DIR}\"; ingest_one ${n} acct-default"
  check "roster cluster ${n} goes in as role=instructor" 'ctrue "${T}/imports/1.csv" "d[\"name\"] == \"${n}\" and d[\"role\"] == \"instructor\""'
done
reset
LABCTL_RC=1 src "mkdir -p \"\${LOG_DIR}\"; ingest_one ${A} accen-qa"
check "a failed import is retried three times" '[[ "$(grep -c "^labctl import" "${CALLS}")" -eq 3 ]]'
check "then recorded as an ingest failure by name, with labctl's own message" \
  'ledger | grep -qx "ingest:${A}" && grep -q "labctl import failed: ${A} after 3 attempts: labctl: import refused (test)" "${T}/stderr"'
for v in DATABASE_URL USER; do
  reset
  if [[ "${v}" == DATABASE_URL ]]; then TEST_DATABASE_URL="" src "rc=0; cmd_ingest ${A} || rc=\$?; echo rc=\${rc}" >"${T}/out"
  else TEST_USER="" src "rc=0; cmd_ingest ${A} || rc=\$?; echo rc=\${rc}" >"${T}/out"; fi
  check "ingest without ${v} exits non-zero, names it, and imports nothing" \
    '! grep -qx "rc=0" "${T}/out" && grep -q "missing: ${v}" "${T}/stderr" && ! grep -q "^labctl" "${CALLS}"'
done
reset
TEST_DATABASE_URL="" src "_ingest_attendee_names() { echo INGEST-RAN >&2; }; WIB_DRY_RUN=''; mkdir -p \"\${LOG_DIR}\"; register_with_provisioning 'the test fleet' _ingest_attendee_names ${A}"
check "provisioning without DATABASE_URL says the clusters were NOT registered" 'grep -q "the test fleet was NOT registered" "${T}/stderr"'
check "and fails the run, without trying the ingest" 'ledger | grep -qx "ingest:no-labctl" && ! grep -q INGEST-RAN "${T}/stderr"'
reset
src "_ingest_attendee_names() { echo INGEST-RAN \"\$@\" >&2; }; WIB_DRY_RUN=''; mkdir -p \"\${LOG_DIR}\"; register_with_provisioning 'the test fleet' _ingest_attendee_names ${A}"
check "with labctl ready, provisioning runs the ingest" 'grep -q "INGEST-RAN ${A}" "${T}/stderr" && [[ -z "$(ledger)" ]]'

echo "== terminal-password reads the login back through the harvester =="
reset
AWS_PROFILE=accen-qa src "restart_pods() { :; }; terminal_password_one ${A} ${T}/kcfg ctx-a"; rc=$?
check "exits 0" '[[ "${rc}" -eq 0 ]]'
check "the file is the whole login" '[[ "$(cat "${POOL}/${A}.terminal")" == agentic:agentic ]]'
reset
HARVEST_RC=1 AWS_PROFILE=accen-qa src "restart_pods() { :; }; terminal_password_one ${A} ${T}/kcfg ctx-a"; rc=$?
check "a failed harvest fails the verb" '[[ "${rc}" -ne 0 ]]'

echo "== ingest pool re-ingests every live row, claimed ones included =="
cat >"${T}/roster.html" <<H
<p>All 3 rows, unclaimed first.</p>
<table class="rt">
  <tr><th>State</th><th>Cluster</th><th>Claimed by</th></tr>
  <tr class="claimed"><td>claimed</td><td class="cn">${A}</td><td>someone@example.com</td></tr>
  <tr class="free"><td>free</td><td class="cn">${B}</td><td>&mdash;</td></tr>
  <tr class="admin"><td>admin</td><td class="cn">${ADMIN}</td><td>&mdash;</td></tr>
</table>
H
reset
src "rc=0; cmd_ingest pool || rc=\$?; echo rc=\${rc}" >"${T}/out"
check "exits 0 when every row re-ingested" 'grep -qx "rc=0" "${T}/out"'
check "reads the live pool from /admin/roster" 'grep -q "https://prov.test/admin/roster" "${CALLS}"'
check "imports one row per pool row" '[[ "$(ls "${T}/imports" | wc -l)" -eq 3 ]]'
check "the claimed row is re-sent with agentic/agentic" \
  '(for f in "${T}"/imports/*.csv; do ctrue "${f}" "d[\"name\"] == \"${A}\" and d[\"terminal_user\"] == \"agentic\" and d[\"terminal_password\"] == \"agentic\"" && exit 0; done; exit 1)'
check "each row is harvested in its own account" \
  'grep -qxF "harvest ${A} us-west-2 ${POOL} [AWS_PROFILE=accen-qa]" "${CALLS}" && grep -qxF "harvest ${B} us-west-2 ${POOL} [AWS_PROFILE=acct-default]" "${CALLS}"'
reset
ROSTER_DOWN=1 src "rc=0; cmd_ingest pool || rc=\$?; echo rc=\${rc}" >"${T}/out"
check "an unreadable pool is a failure, with nothing posted" \
  '! grep -qx "rc=0" "${T}/out" && [[ "$(ls "${T}/imports" | wc -l)" -eq 0 ]] && grep -q "cannot read the live pool" "${T}/stderr"'

echo "== nothing in fleet.sh writes a .terminal file but the harvester =="
check "no printf into a .terminal file" '! grep -nE "printf .*>\"?\\\$\{(pwfile|AWS_POOL_DIR\}/\\\$\{name\}\.terminal)" "${FLEET}"'
check "no pwfile variable is left" '! grep -q "pwfile" "${FLEET}"'
usage_txt="$(sed -n '/^usage() {/,/^}/p' "${FLEET}")"
check "usage documents ingest pool" 'grep -q "ingest pool" <<<"${usage_txt}"'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
