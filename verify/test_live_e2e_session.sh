#!/usr/bin/env bash
# ABOUTME: Behavioural tests for live-e2e-session.sh (#461): the one-row pool from the sandbox key, the refusal to adopt a
# ABOUTME: cluster, teardown and pool restore on every exit, and the live Datadog check scoped to the cluster under test.
#
# Usage: verify/test_live_e2e_session.sh      (offline; aws, kubectl, fleet.sh and run-e2e.sh are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${HERE}/live-e2e-session.sh"
T="$(mktemp -d -p "${HERE}/.." .live-e2e-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

SANDBOX='{"api-key":"SANDBOX_API_KEY_x1","app-key":"SANDBOX_APP_KEY_y2","site":"datadoghq.com"}'
OLD_POOL='[{"api-key":"JUNE_API","app-key":"JUNE_APP","org":"Datadog-june-001","expirationDate":"1751328000"}]'
ARN="arn:aws:eks:us-west-2:111122223333:cluster/watch-it-burn-attendee-001"

# Secrets Manager and EKS answer from files under ${T}/state; every call is recorded.
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws AWS_PROFILE=${AWS_PROFILE:-} $*" >>"${T}/calls"
arg() { local want="$1"; shift; while [[ $# -gt 0 ]]; do [[ "$1" == "${want}" ]] && { printf '%s' "$2"; return; }; shift; done; }
id="$(arg --secret-id "$@")"; [[ -n "${id}" ]] || id="$(arg --name "$@")"
val="$(arg --secret-string "$@")"
case "$1 $2" in
  "eks describe-cluster") [[ -f "${T}/state/cluster" ]] && { echo "{}"; exit 0; }; exit 254 ;;
  "eks update-kubeconfig") printf 'current-context: %s\n' "${ARN}" >"$(arg --kubeconfig "$@")"; exit 0 ;;
  "secretsmanager get-secret-value")
    case "${id}" in
      watch-it-burn/datadog) [[ -f "${T}/no_sandbox" ]] && exit 254; printf '%s' "${SANDBOX}" ;;
      watch-it-burn/datadog-pool) [[ -f "${T}/state/pool" ]] || exit 254; cat "${T}/state/pool" ;;
    esac ;;
  "secretsmanager describe-secret") [[ "${id}" == watch-it-burn/datadog-pool && -f "${T}/state/pool" ]] || exit 254 ;;
  "secretsmanager put-secret-value"|"secretsmanager create-secret")
    [[ -f "${T}/fail_restore" && -f "${T}/state/seeded" ]] && exit 1
    cp "${val#file://}" "${T}/state/pool"; touch "${T}/state/seeded"; echo "$1 $2 ${id}" >>"${T}/writes" ;;
  "secretsmanager delete-secret") rm -f "${T}/state/pool"; echo "$1 $2 ${id}" >>"${T}/writes" ;;
esac
exit 0
S
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl KUBECONFIG=${KUBECONFIG:-} $*" >>"${T}/calls"
[[ "$*" == "config current-context" ]] && { sed -n 's/^current-context: //p' "${KUBECONFIG}"; exit 0; }
exit 0
S
# fleet.sh: up builds the cluster unless told to fail, down removes it unless it is stuck.
cat >"${T}/fleet.sh" <<'S'
#!/usr/bin/env bash
echo "fleet $* NO_INGEST=${WIB_NO_INGEST:-} APPLY=${WIB_APPLY:-} ACCT=${WIB_DEFAULT_ACCOUNT:-} REGION=${WIB_REGION:-} POOL_AT_UP=$(cat "${T}/state/pool" 2>/dev/null)" >>"${T}/fleet"
case "$1" in
  up) touch "${T}/state/cluster"; [[ -f "${T}/fail_up" ]] && exit 1; exit 0 ;;
  down) [[ -f "${T}/stuck" ]] || rm -f "${T}/state/cluster"; exit 0 ;;
esac
S
cat >"${T}/run-e2e.sh" <<'S'
#!/usr/bin/env bash
echo "e2e CONTEXT=${CONTEXT:-} KUBECONFIG=${KUBECONFIG:-} IAM=${IAM_PIPELINE_PROFILE:-}/${IAM_PIPELINE_REGION:-}" >>"${T}/e2e"
echo "e2e-dd ADMIN_API=${WITB_DD_ADMIN_API_KEY:-} ADMIN_APP=${WITB_DD_ADMIN_APP_KEY:-} ACCT=${WIB_DEFAULT_ACCOUNT:-} REGION=${WIB_REGION:-}" >>"${T}/e2e"
echo "run-e2e output"
exit "$(cat "${T}/e2e_rc" 2>/dev/null || echo 0)"
S
chmod +x "${SHIM}"/* "${T}/fleet.sh" "${T}/run-e2e.sh"
export T SANDBOX ARN

reset() { rm -rf "${T}/state" "${T}/calls" "${T}/fleet" "${T}/e2e" "${T}/writes" "${T}/e2e_rc" "${T}/fail_up" "${T}/stuck" \
          "${T}/no_sandbox" "${T}/fail_restore" "${T}/out"; mkdir -p "${T}/state"; }
session() { # runs the session with the shims; output in ${T}/out, exit code in ${T}/rc
  env PATH="${SHIM}:${PATH}" WIB_FLEET_SH="${T}/fleet.sh" WIB_RUN_E2E="${T}/run-e2e.sh" E2E_LOG="${T}/e2e.log" \
      E2E_PROFILE=accen-dev E2E_REGION=us-west-2 IAM_PIPELINE_PROFILE=pipe IAM_PIPELINE_REGION=us-east-1 "$@" \
      bash "${SESSION}" >"${T}/out" 2>&1
  echo "$?" >"${T}/rc"
}
rc() { cat "${T}/rc"; }

echo "== it will not start without an explicit profile and region =="
reset
env -u E2E_PROFILE -u E2E_REGION PATH="${SHIM}:${PATH}" WIB_FLEET_SH="${T}/fleet.sh" WIB_RUN_E2E="${T}/run-e2e.sh" \
    IAM_PIPELINE_PROFILE=pipe IAM_PIPELINE_REGION=us-east-1 bash "${SESSION}" >"${T}/out" 2>&1; echo "$?" >"${T}/rc"
check "no E2E_PROFILE or E2E_REGION: exits non-zero" '[[ "$(rc)" -ne 0 ]]'
check "  and says which" 'grep -q "E2E_PROFILE must name" "${T}/out" && grep -q "E2E_REGION must name" "${T}/out"'
check "  and touched nothing in AWS" '[[ ! -s "${T}/calls" && ! -e "${T}/fleet" ]]'

echo "== it never adopts a cluster it did not build =="
reset; touch "${T}/state/cluster"
session
check "watch-it-burn-attendee-001 already exists: exits non-zero" '[[ "$(rc)" -ne 0 ]] && grep -q REFUSING "${T}/out"'
check "  and neither seeds the pool nor runs fleet.sh (no down of someone else's cluster)" '[[ ! -e "${T}/writes" && ! -e "${T}/fleet" ]]'

echo "== no pool before: a one-row pool from the sandbox key, then no pool after =="
reset
session
check "exits 0 when run-e2e.sh passes" '[[ "$(rc)" -eq 0 ]]'
check "the pool fleet.sh up saw is one row with the sandbox keys, role attendee" \
  'grep "^fleet up" "${T}/fleet" | grep -q "POOL_AT_UP=\[{\"org\":\"burritobot-sandbox (live e2e, #461)\",\"api-key\":\"SANDBOX_API_KEY_x1\",\"app-key\":\"SANDBOX_APP_KEY_y2\",\"role\":\"attendee\"}\]"'
check "  created with the project, event and component tags" 'grep "create-secret" "${T}/calls" | grep -q "Key=project,Value=watch-it-burn Key=event,Value=kubecon-na-2026 Key=component,Value=datadog-pool"'
check "  written from a file, never with a key on the command line" '! grep -q SANDBOX_API_KEY_x1 "${T}/calls" && grep "create-secret" "${T}/calls" | grep -q "secret-string file://"'
check "up builds watch-it-burn-attendee-001 only, outside the handout pool, in the named account and region" \
  'grep -q "^fleet up watch-it-burn-attendee-001 NO_INGEST=1 APPLY= ACCT=accen-dev REGION=us-west-2" "${T}/fleet"'
check "run-e2e.sh gets the cluster's context and its isolated kubeconfig" \
  'grep -q "^e2e CONTEXT=${ARN} KUBECONFIG=.*live-e2e\..*/watch-it-burn-attendee-001.kubeconfig IAM=pipe/us-east-1" "${T}/e2e"'
check "  and the sandbox keys as the instructor org's, with the account and region the Datadog checks read (#587)" \
  'grep -q "^e2e-dd ADMIN_API=SANDBOX_API_KEY_x1 ADMIN_APP=SANDBOX_APP_KEY_y2 ACCT=accen-dev REGION=us-west-2$" "${T}/e2e"'
check "every AWS call names the profile and the region" \
  '! grep "^aws " "${T}/calls" | grep -v "AWS_PROFILE=accen-dev " | grep -q . && ! grep "^aws " "${T}/calls" | grep -v -- "--region us-west-2" | grep -q .'
check "down tears the cluster down with WIB_APPLY=1" 'grep -q "^fleet down watch-it-burn-attendee-001 NO_INGEST= APPLY=1" "${T}/fleet"'
check "the cluster is gone and the pool deleted, since there was none" '[[ ! -e "${T}/state/cluster" && ! -e "${T}/state/pool" ]] && tail -1 "${T}/writes" | grep -q "delete-secret watch-it-burn/datadog-pool"'
check "no key is printed" '! grep -q "SANDBOX_A[PI]*_KEY\|SANDBOX_APP_KEY" "${T}/out"'
check "run-e2e.sh's output is kept in E2E_LOG" 'grep -q "run-e2e output" "${T}/e2e.log"'

echo "== a pool before: put back byte for byte, even when run-e2e.sh fails =="
reset; printf '%s' "${OLD_POOL}" >"${T}/state/pool"; echo 1 >"${T}/e2e_rc"
session
check "exits with run-e2e.sh's failure" '[[ "$(rc)" -eq 1 ]]'
check "fleet.sh up saw the one-row pool, not the June one" 'grep "^fleet up" "${T}/fleet" | grep -q "SANDBOX_API_KEY_x1" && ! grep "^fleet up" "${T}/fleet" | grep -q JUNE_API'
check "the cluster was still torn down" 'grep -q "^fleet down watch-it-burn-attendee-001" "${T}/fleet" && [[ ! -e "${T}/state/cluster" ]]'
check "the saved pool is back exactly as it was" '[[ "$(cat "${T}/state/pool")" == "${OLD_POOL}" ]]'
check "  by put-secret-value, never deleted" '! grep -q delete-secret "${T}/calls"'
check "the work directory with the saved value is removed" '! ls -d "${TMPDIR:-/tmp}"/live-e2e.* >/dev/null 2>&1 || ! grep -rqs JUNE_API "${TMPDIR:-/tmp}"/live-e2e.*'

echo "== a failed build still tears down and restores =="
reset; touch "${T}/fail_up"
session
check "exits non-zero" '[[ "$(rc)" -ne 0 ]]'
check "run-e2e.sh never ran" '[[ ! -e "${T}/e2e" ]]'
check "down ran on what up left, and the pool is gone again" 'grep -q "^fleet down watch-it-burn-attendee-001" "${T}/fleet" && [[ ! -e "${T}/state/cluster" && ! -e "${T}/state/pool" ]]'

echo "== what is left behind is said, loudly =="
reset; touch "${T}/stuck"
session
check "a cluster EKS still lists after down: exits non-zero even though run-e2e.sh passed" '[[ "$(rc)" -ne 0 ]]'
check "  and names it with the command to run" 'grep -q "watch-it-burn-attendee-001 IS STILL UP. Run: WIB_APPLY=1" "${T}/out"'
reset; printf '%s' "${OLD_POOL}" >"${T}/state/pool"; touch "${T}/fail_restore"
session
check "a pool that could not be put back: exits non-zero" '[[ "$(rc)" -ne 0 ]] && grep -q "watch-it-burn/datadog-pool NOT RESTORED" "${T}/out"'
saved="$(sed -n 's/.*Its saved value is \([^:]*\): .*/\1/p' "${T}/out")"
check "  and keeps the saved value where it says, to put back by hand" '[[ -n "${saved}" && "$(cat "${saved}")" == "${OLD_POOL}" ]]'
rm -rf "$(dirname "${saved:-/nonexistent/x}")"
reset; touch "${T}/no_sandbox"
session
check "no sandbox key: exits non-zero before anything is built" '[[ "$(rc)" -ne 0 && ! -e "${T}/fleet" && ! -e "${T}/writes" ]]'

echo "== the live Datadog check looks at the cluster under test, not the org's other clusters =="
ENVF="${T}/dd.env"; printf 'DD_API_KEY=k\nDD_APP_KEY=a\n' >"${ENVF}"
out="$(env -u DD_KUBE_CLUSTER WITB_ENV_FILE="${ENVF}" python3 "${HERE}/test_datadog_service_map.py" 2>&1)"; smrc=$?
check "test_datadog_service_map.py without DD_KUBE_CLUSTER fails (exit 2, run-e2e.sh counts it) before any query" \
  '[[ "${smrc}" -eq 2 ]] && grep -q "DD_KUBE_CLUSTER is not set" <<<"${out}"'
SMAP="$(cat "${HERE}/test_datadog_service_map.py")"
check "  its UST series and its cluster check carry kube_cluster_name" \
  '[[ "$(grep -c "kube_cluster_name:{DD_KUBE_CLUSTER}" <<<"${SMAP}")" -ge 2 ]] && grep -q "^    test_cluster_ships()" <<<"${SMAP}"'
RUNE2E="$(cat "${HERE}/run-e2e.sh")"
check "run-e2e.sh reads the name from the cluster's datadog/cluster-identity and exports it" \
  'grep -q "\-n datadog get configmap cluster-identity" <<<"${RUNE2E}" && grep -q "{.data.datadog-cluster-name}" <<<"${RUNE2E}" && grep -q "export DD_KUBE_CLUSTER" <<<"${RUNE2E}"'

echo
echo "${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
