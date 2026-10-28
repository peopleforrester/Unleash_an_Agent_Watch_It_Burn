#!/usr/bin/env bash
# ABOUTME: Behavioural tests for the fleet.sh teardown and routes hooks (#251): per-process failure ledger,
# ABOUTME: deregister on teardown, target-group retry, console-LB wait, and router reload retry. Uses shims.
# ABOUTME: deregister and release go to lab-platform through labctl, not /admin/delete or /admin/release (#624).
#
# Usage: verify/test_fleet_teardown_hooks.sh      (no cloud access; every external command is a shim)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .fleet-hooks-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# ---- shims: every external command records its argv and answers from files the test controls ----
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $*" >>"${CALLS}"
case "$*" in
  *"eks update-kubeconfig"*) exit 0 ;;
  *"describe-load-balancers"*) n=$(cat "${T}/lb_polls" 2>/dev/null || echo 0); echo $((n+1)) >"${T}/lb_polls"
        [[ "$n" -lt "${LB_GONE_AFTER:-0}" ]] && echo "arn:lb/one"; exit 0 ;;
  *"describe-tags"*) echo "${TAG_NAME:-}"; exit 0 ;;
  *"delete-load-balancer"*) exit 0 ;;
  *"describe-target-groups"*) echo "arn:tg/one"; exit 0 ;;
  *"delete-target-group"*) n=$(cat "${T}/tg_tries" 2>/dev/null || echo 0); echo $((n+1)) >"${T}/tg_tries"
        [[ "$n" -ge "${TG_OK_AFTER:-0}" ]] && exit 0; exit 254 ;;
  *"describe-volumes"*) echo "${VOL_ID:-}"; exit 0 ;;
  *"delete-volume"*) exit "${VOL_DELETE_RC:-0}" ;;
esac
exit 0
S
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $*" >>"${CALLS}"
n=$(cat "${T}/k_polls" 2>/dev/null || echo 0); echo $((n+1)) >"${T}/k_polls"
[[ "$n" -ge "${LB_READY_AFTER:-0}" ]] && echo "lb-${n}.elb.amazonaws.com"
exit 0
S
cat >"${SHIM}/curl" <<'S'
#!/usr/bin/env bash
echo "curl $*" >>"${CALLS}"; printf '%s' "${CURL_CODE:-200}"
S
# labctl: logs its arguments and whether it saw DATABASE_URL and USER; LABCTL_RC makes it refuse with that code.
cat >"${SHIM}/labctl" <<'S'
#!/usr/bin/env bash
echo "labctl $* [DATABASE_URL=${DATABASE_URL:-} USER=${USER:-}]" >>"${CALLS}"
[[ "${LABCTL_RC:-0}" -eq 0 ]] || { echo "labctl: ${!#} is claimed (test)" >&2; exit "${LABCTL_RC}"; }
S
for c in terraform railway; do printf '#!/usr/bin/env bash\necho "%s $*" >>"${CALLS}"\nexit 0\n' "$c" >"${SHIM}/$c"; done
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"
# Sourcing fleet.sh: the source guard keeps main() from running; WIB_* settings make every wait instant.
src() { # $1: bash snippet to run after sourcing
  ( cd "$(dirname "${FLEET}")" && WIB_ADMIN_TOKEN=test-token WIB_PROVISIONING_URL=https://prov.test \
      DATABASE_URL="${TEST_DATABASE_URL-postgresql://lab@db.test/lab}" USER="${TEST_USER-tester}" WIB_EVENT=test-event \
      WIB_TG_BACKOFF=0 WIB_LB_GONE_INTERVAL=0 WIB_LB_WAIT_INTERVAL=0 WIB_RELOAD_BACKOFF=0 \
      bash -c "source '${FLEET}' >/dev/null 2>&1; $1" 2>>"${T}/stderr" )
}

echo "== per-process failure ledger =="
a="$(src 'record_fail one; echo "${FAIL_FILE}"')"; b="$(src 'echo "${FAIL_FILE}"')"
check "two runs write different ledgers" '[[ -n "$a" && "$a" != "$b" ]]'
check "ledger is under logs/ and carries the pid" '[[ "$a" == */logs/.failures.[0-9]* ]]'
rm -f "$a" "$b"

echo "== deregister on teardown, through labctl deregister (#624) =="
: >"${CALLS}"; : >"${T}/stderr"
src 'deregister_one watch-it-burn-attendee-009; cat "${FAIL_FILE}" 2>/dev/null; rm -f "${FAIL_FILE}"' >"${T}/out"
check "runs labctl deregister --customer agenticburn --event <the fleet's event> <name>, with DATABASE_URL and USER" \
  'grep -qxF "labctl deregister --customer agenticburn --event test-event watch-it-burn-attendee-009 [DATABASE_URL=postgresql://lab@db.test/lab USER=tester]" "${CALLS}"'
check "nothing is POSTed to /admin/delete" '! grep -q "admin/delete" "${CALLS}"'
check "a zero exit records no failure" '[[ ! -s "${T}/out" ]]'
: >"${CALLS}"; : >"${T}/stderr"
LABCTL_RC=1 src 'deregister_one watch-it-burn-attendee-009; echo rc=$?; cat "${FAIL_FILE}"; rm -f "${FAIL_FILE}"' >"${T}/out"
check "a refusal (still claimed, or unknown) is recorded as deregister:<name>, not fatal" \
  'grep -qx "rc=0" "${T}/out" && grep -qx "deregister:watch-it-burn-attendee-009" "${T}/out"'
check "and says to tell the attendee, then rerun with --release-claimed, carrying labctl's message" \
  'grep -q "labctl: watch-it-burn-attendee-009 is claimed (test)" "${T}/stderr" && grep -q "Tell the attendee" "${T}/stderr" && grep -q "fleet.sh deregister --release-claimed watch-it-burn-attendee-009" "${T}/stderr"'
: >"${CALLS}"; : >"${T}/stderr"
TEST_DATABASE_URL="" src 'deregister_one watch-it-burn-attendee-009; echo rc=$?; cat "${FAIL_FILE}"; rm -f "${FAIL_FILE}"' >"${T}/out"
check "without DATABASE_URL it names what is missing, runs nothing, and records the failure" \
  'grep -qx "rc=0" "${T}/out" && grep -qx "deregister:watch-it-burn-attendee-009" "${T}/out" && grep -q "missing: DATABASE_URL" "${T}/stderr" && ! grep -q "^labctl" "${CALLS}"'
: >"${CALLS}"
WIB_NO_INGEST=1 src 'deregister_one watch-it-burn-attendee-009'
check "WIB_NO_INGEST=1 opts out (labctl not run)" '! grep -q "^labctl" "${CALLS}"'

echo "== fleet.sh deregister and release by hand (#624) =="
N1=watch-it-burn-attendee-009; N2=watch-it-burn-attendee-010
: >"${CALLS}"
src "rc=0; cmd_deregister ${N1} ${N2} || rc=\$?; echo rc=\${rc}" >"${T}/out"
check "deregister sends every name in one labctl call" \
  'grep -qxF "labctl deregister --customer agenticburn --event test-event ${N1} ${N2} [DATABASE_URL=postgresql://lab@db.test/lab USER=tester]" "${CALLS}" && [[ "$(grep -c "^labctl" "${CALLS}")" -eq 1 ]] && grep -qx "rc=0" "${T}/out"'
: >"${CALLS}"
src "rc=0; cmd_deregister --release-claimed ${N1} || rc=\$?; echo rc=\${rc}" >"${T}/out"
check "--release-claimed is passed on to labctl" \
  'grep -qxF "labctl deregister --customer agenticburn --event test-event --release-claimed ${N1} [DATABASE_URL=postgresql://lab@db.test/lab USER=tester]" "${CALLS}" && grep -qx "rc=0" "${T}/out"'
: >"${CALLS}"; : >"${T}/stderr"
LABCTL_RC=1 src "rc=0; cmd_deregister ${N1} ${N2} || rc=\$?; echo rc=\${rc}" >"${T}/out"
check "a refused deregister exits non-zero and names every cluster in the call" \
  '! grep -qx "rc=0" "${T}/out" && grep -qx "    - deregister:${N1}" "${T}/stderr" && grep -qx "    - deregister:${N2}" "${T}/stderr"'
: >"${CALLS}"; : >"${T}/stderr"
TEST_USER="" src "rc=0; cmd_deregister ${N1} || rc=\$?; echo rc=\${rc}" >"${T}/out"
check "deregister without USER exits 1 before running labctl" \
  '! grep -qx "rc=0" "${T}/out" && grep -q "missing: USER" "${T}/stderr" && ! grep -q "^labctl" "${CALLS}"'
: >"${CALLS}"
WIB_NO_INGEST=1 src "cmd_deregister ${N1}" >/dev/null
check "WIB_NO_INGEST does not silence a deregister asked for by hand" 'grep -q "^labctl deregister" "${CALLS}"'
: >"${CALLS}"
src "rc=0; cmd_release a@example.test b@example.test || rc=\$?; echo rc=\${rc}" >"${T}/out"
check "release runs labctl release --customer agenticburn --event <event> <email>, once per email" \
  'grep -qxF "labctl release --customer agenticburn --event test-event a@example.test [DATABASE_URL=postgresql://lab@db.test/lab USER=tester]" "${CALLS}" && grep -qxF "labctl release --customer agenticburn --event test-event b@example.test [DATABASE_URL=postgresql://lab@db.test/lab USER=tester]" "${CALLS}" && grep -qx "rc=0" "${T}/out"'
check "nothing is POSTed to /admin/release" '! grep -q "admin/release" "${CALLS}"'
: >"${CALLS}"; : >"${T}/stderr"
LABCTL_RC=1 src "rc=0; cmd_release a@example.test || rc=\$?; echo rc=\${rc}" >"${T}/out"
check "a refused release exits non-zero, recorded as release:<email>" '! grep -qx "rc=0" "${T}/out" && grep -qx "    - release:a@example.test" "${T}/stderr"'
: >"${CALLS}"; : >"${T}/stderr"
TEST_DATABASE_URL="" src "rc=0; cmd_release a@example.test || rc=\$?; echo rc=\${rc}" >"${T}/out"
check "release without DATABASE_URL exits 1 before running labctl" \
  '! grep -qx "rc=0" "${T}/out" && grep -q "missing: DATABASE_URL" "${T}/stderr" && ! grep -q "^labctl" "${CALLS}"'

echo "== target-group sweep waits for the LB and retries =="
rm -f "${T}/lb_polls" "${T}/tg_tries"; : >"${CALLS}"
TAG_NAME=watch-it-burn-attendee-009 LB_GONE_AFTER=3 TG_OK_AFTER=2 \
  src 'sweep_orphan_lbs watch-it-burn-attendee-009 acct; cat "${FAIL_FILE}" 2>/dev/null; rm -f "${FAIL_FILE}"' >"${T}/out"
check "polls describe-load-balancers until the LB is gone (>=3 polls)" '[[ "$(cat "${T}/lb_polls")" -ge 3 ]]'
check "retries delete-target-group until it succeeds (3 attempts)" '[[ "$(cat "${T}/tg_tries")" -eq 3 ]]'
# #269: a load balancer the sweep deleted and that then disappeared was CLEANED. The backstop doing its job
# is not a failure, so neither lb-leak nor tg-leak is recorded on a swept-clean run.
check "swept clean records no lb-leak and no tg-leak" '! grep -q "lb-leak" "${T}/out" && ! grep -q "tg-leak" "${T}/out"'
rm -f "${T}/lb_polls" "${T}/tg_tries"
# A load balancer that never disappears after deletion IS a real leak: record lb-leak. Timeout 0 so the
# gone-wait polls once and gives up immediately with the survivor still present.
TAG_NAME=watch-it-burn-attendee-009 LB_GONE_AFTER=99 TG_OK_AFTER=0 WIB_LB_GONE_TIMEOUT=0 \
  src 'sweep_orphan_lbs watch-it-burn-attendee-009 acct; cat "${FAIL_FILE}" 2>/dev/null; rm -f "${FAIL_FILE}"' >"${T}/out"
check "a load balancer that survives the sweep records lb-leak" 'grep -qx "lb-leak:watch-it-burn-attendee-009" "${T}/out"'
rm -f "${T}/lb_polls" "${T}/tg_tries"
TAG_NAME=watch-it-burn-attendee-009 LB_GONE_AFTER=0 TG_OK_AFTER=99 WIB_TG_RETRIES=4 \
  src 'sweep_orphan_lbs watch-it-burn-attendee-009 acct; cat "${FAIL_FILE}" 2>/dev/null; rm -f "${FAIL_FILE}"' >"${T}/out"
check "with NO leaked load balancer the target groups are still swept, and one that never deletes is tg-leak" \
  '[[ "$(cat "${T}/tg_tries")" -eq 4 ]] && grep -qx "tg-leak:watch-it-burn-attendee-009" "${T}/out" && ! grep -q "lb-leak" "${T}/out"'

echo "== volume sweep records vol-leak only on survival (#269) =="
VOL_ID=vol-abc VOL_DELETE_RC=0 \
  src 'sweep_orphan_volumes watch-it-burn-attendee-009 acct; cat "${FAIL_FILE}" 2>/dev/null; rm -f "${FAIL_FILE}"' >"${T}/out"
check "a volume the sweep deletes is not a failure" '! grep -q "vol-leak" "${T}/out"'
VOL_ID=vol-abc VOL_DELETE_RC=254 \
  src 'sweep_orphan_volumes watch-it-burn-attendee-009 acct; cat "${FAIL_FILE}" 2>/dev/null; rm -f "${FAIL_FILE}"' >"${T}/out"
check "a volume that survives deletion records vol-leak" 'grep -qx "vol-leak:watch-it-burn-attendee-009" "${T}/out"'

echo "== routes waits for the consoles =="
rm -f "${T}/k_polls"; : >"${CALLS}"
LB_READY_AFTER=2 src 'wait_for_console_lbs watch-it-burn-attendee-009; echo rc=$?' >"${T}/out"
check "returns 0 once the console has a hostname (3 kubectl polls)" 'grep -qx "rc=0" "${T}/out" && [[ "$(cat "${T}/k_polls")" -eq 3 ]]'
rm -f "${T}/k_polls"
LB_READY_AFTER=99 WIB_LB_WAIT_TIMEOUT=1 src 'if wait_for_console_lbs watch-it-burn-attendee-009; then echo rc=0; else echo rc=$?; fi; cat "${FAIL_FILE}"; rm -f "${FAIL_FILE}"' >"${T}/out"
check "gives up at the deadline, returns 1, records routes:lb-wait-timeout" 'grep -qx "rc=1" "${T}/out" && grep -qx "routes:lb-wait-timeout" "${T}/out"'
rm -f "${T}/k_polls"
src 'echo watch-it-burn-attendee-009 >"${FAIL_FILE}"; wait_for_console_lbs watch-it-burn-attendee-009; echo rc=$?; rm -f "${FAIL_FILE}"' >"${T}/out"
check "a cluster that failed provisioning is not waited for" 'grep -qx "rc=0" "${T}/out" && [[ ! -f "${T}/k_polls" ]]'

echo "== router reload retries =="
mkdir -p "${T}/apex/scripts"; printf '#!/usr/bin/env bash\nn=$(cat "%s/r_tries" 2>/dev/null || echo 0); echo $((n+1)) >"%s/r_tries"; [[ "$n" -ge "${RELOAD_OK_AFTER:-0}" ]]\n' "${T}" "${T}" >"${T}/apex/scripts/reload-routes.sh"; chmod +x "${T}/apex/scripts/reload-routes.sh"
rm -f "${T}/r_tries"
RELOAD_OK_AFTER=2 WIB_APEX_DIR="${T}/apex" src 'apply_routes_table /dev/null; echo rc=$?' >"${T}/out"
check "reload succeeds on the third attempt, returns 0" 'grep -qx "rc=0" "${T}/out" && [[ "$(cat "${T}/r_tries")" -eq 3 ]]'
rm -f "${T}/r_tries"
RELOAD_OK_AFTER=99 WIB_APEX_DIR="${T}/apex" src 'if apply_routes_table /dev/null; then echo rc=0; else echo rc=$?; fi; cat "${FAIL_FILE}"; rm -f "${FAIL_FILE}"' >"${T}/out"
check "three failures: returns 1 and records routes:reload-failed" 'grep -qx "rc=1" "${T}/out" && grep -qx "routes:reload-failed" "${T}/out" && [[ "$(cat "${T}/r_tries")" -eq 3 ]]'

echo "== wiring =="
check "down_one calls deregister_one" 'grep -q "^    deregister_one \"\${name}\"" "${FLEET}"'
check "up waits for console LBs before routes" 'grep -q "wait_for_console_lbs \"\${built\[@\]}\" || true" "${FLEET}"'
check "down republishes routes with the shrink allowed" 'grep -q "WIB_ROUTES_ALLOW_SHRINK=1 cmd_routes" "${FLEET}"'
check "deregister is a subcommand" 'grep -q "deregister) cmd_deregister" "${FLEET}"'
check "release is a subcommand" 'grep -q "release) cmd_release" "${FLEET}"'
check "no shared .failures path remains" '! grep -q "LOG_DIR}/.failures\"" "${FLEET}"'
check "drain waits for the cluster load balancers to be gone before destroy (#269)" \
  'grep -q "cluster_lb_count \"\${name}\" \"\${acct}\"" "${FLEET}"'

echo; echo "  ${pass} passed, ${fail} failed"
[[ -s "${T}/stderr" ]] && { echo "  (stderr from sourced runs, last lines)"; tail -5 "${T}/stderr" | sed 's/^/    /'; }
exit $(( fail > 0 ))
