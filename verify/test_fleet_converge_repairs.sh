#!/usr/bin/env bash
# ABOUTME: Behavioural tests for the converge repairs (#254): Datadog key resolution per cluster class,
# ABOUTME: identity and key-drift repair, stuck sync and pod handling, empty-state pruning, verifier ledger.
#
# Usage: verify/test_fleet_converge_repairs.sh      (offline; aws, kubectl and the scripts are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .fleet-repairs-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/states"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# ---- canned Datadog secrets, as Secrets Manager would answer ----
ADMIN='{"api-key":"ADMIN_API","app-key":"ADMIN_APP","org":"devops-days-portland-090826-001","role":"admin-instructor"}'
ADMATT='{"api-key":"PRES_API","app-key":"PRES_APP","org":"devops-days-portland-090826-002","role":"admin-attendee"}'
POOL='[{"api-key":"ADMIN_API","app-key":"ADMIN_APP","role":"admin-instructor"},{"api-key":"PRES_API","app-key":"PRES_APP","role":"admin-attendee"},{"api-key":"ROW1_API","app-key":"ROW1_APP","org":"devops-days-portland-090826-003"},{"api-key":"ROW2_API","app-key":"ROW2_APP","org":"devops-days-portland-090826-004"}]'
cat >"${SHIM}/aws" <<S
#!/usr/bin/env bash
echo "aws \$*" >>"\${CALLS}"
case "\$*" in
  *"--secret-id watch-it-burn/datadog-pool "*) printf '%s' '${POOL}' ;;
  *"--secret-id watch-it-burn/datadog-pool-2 "*) printf '%s' '[]' ;;
  *"--secret-id watch-it-burn/datadog-admin-attendee "*) printf '%s' '${ADMATT}' ;;
  *"--secret-id watch-it-burn/datadog "*) printf '%s' '${ADMIN}' ;;
  *"eks update-kubeconfig"*) exit 0 ;;
esac
exit 0
S
# kubectl answers from files the test controls; every mutation is recorded.
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $*" >>"${CALLS}"
case "$*" in
  *"config current-context"*) echo "ctx-test" ;;
  *"get applications.argoproj.io -n argocd -o json"*) cat "${T}/apps.json" 2>/dev/null || echo '{"items":[]}' ;;
  *"get pods -A -o json"*) cat "${T}/pods.json" 2>/dev/null || echo '{"items":[]}' ;;
  *"get configmap cluster-identity"*) cat "${T}/identity" 2>/dev/null ;;
  *"get secret datadog-secret -o jsonpath={.data.api-key}"*) printf '%s' "$(cat "${T}/live_key" 2>/dev/null)" | base64 ;;
  *"get secret datadog-admin-secret"*) [[ -f "${T}/admin_present" ]] && exit 0; exit 1 ;;
  *"create namespace"*|*"create secret generic"*) echo "kind: Placeholder" ;;
esac
exit 0
S
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"
src() { # $1: snippet run after sourcing; the three external actions are replaced by recorders
  ( cd "$(dirname "${FLEET}")" && WIB_STATE_DIR="${T}/states" \
      bash -c "source '${FLEET}' >/dev/null 2>&1
        run_identity_script() { echo \"identity-script CLUSTER_NAME=\${CLUSTER_NAME} admin=\${WITB_DD_ADMIN_API_KEY}\" >>'${CALLS}'; }
        reload_datadog_consumers() { echo \"reload \$1 \$2\" >>'${CALLS}'; }
        run_datadog_orgs_verify() { echo \"verify \$1 \$2\" >>'${CALLS}'; return \${VERIFY_RC:-0}; }
        $1" 2>>"${T}/stderr" )
}

echo "== datadog_keys_for: one truth for every cluster class =="
check "attendee-002 gets pool row 2 plus the instructor org second" \
  '[[ "$(src "datadog_keys_for watch-it-burn-attendee-002")" == "ROW2_API ROW2_APP ADMIN_API ADMIN_APP" ]]'
check "pres-michael gets the admin-attendee org plus the instructor org second" \
  '[[ "$(src "datadog_keys_for watch-it-burn-pres-michael")" == "PRES_API PRES_APP ADMIN_API ADMIN_APP" ]]'
check "an instructor cluster gets the instructor org and nothing second" \
  '[[ "$(src "datadog_keys_for watch-it-burn-r2-1")" == "ADMIN_API ADMIN_APP  " ]]'
check "a slot beyond the pool resolves nothing and returns 1" \
  '! src "datadog_keys_for watch-it-burn-attendee-099" >/dev/null'

echo "== repair_datadog =="
: >"${CALLS}"; printf 'watch-it-burn-attendee-002' >"${T}/identity"; printf 'ROW2_API' >"${T}/live_key"; touch "${T}/admin_present"
src 'repair_datadog watch-it-burn-attendee-002 /dev/null acct'
check "a cluster that matches the repo is left alone (no identity script, no reload)" '! grep -q "identity-script\|reload" "${CALLS}"'
: >"${CALLS}"; rm -f "${T}/identity"
src 'repair_datadog watch-it-burn-attendee-002 /dev/null acct'
check "missing identity: identity script runs with the cluster name and admin key, consumers reloaded" \
  'grep -q "identity-script CLUSTER_NAME=watch-it-burn-attendee-002 admin=ADMIN_API" "${CALLS}" && grep -q "^reload ctx-test acct" "${CALLS}"'
: >"${CALLS}"; printf 'watch-it-burn-attendee-002' >"${T}/identity"; printf 'STALE_JUNE_KEY' >"${T}/live_key"
src 'repair_datadog watch-it-burn-attendee-002 /dev/null acct'
check "key drift: datadog-secret rewritten in all three namespaces and consumers reloaded" \
  '[[ "$(grep -c "create secret generic datadog-secret --from-literal=api-key=ROW2_API" "${CALLS}")" -eq 3 ]] && grep -q "^reload" "${CALLS}"'
: >"${CALLS}"; printf 'ROW2_API' >"${T}/live_key"; rm -f "${T}/admin_present"
src 'repair_datadog watch-it-burn-attendee-002 /dev/null acct'
check "attendee without the admin secret: repaired (dual shipping restored)" 'grep -q "identity-script" "${CALLS}"'
: >"${CALLS}"; printf 'watch-it-burn-r2-1' >"${T}/identity"; printf 'ADMIN_API' >"${T}/live_key"; touch "${T}/admin_present"
src 'repair_datadog watch-it-burn-r2-1 /dev/null acct'
check "instructor WITH an admin secret: repaired (the stale secret goes)" 'grep -q "identity-script CLUSTER_NAME=watch-it-burn-r2-1 admin=$" "${CALLS}"'
rm -f "${T}/admin_present"

echo "== repair_stuck_syncs =="
old="$(date -u -d '40 minutes ago' +%FT%TZ)"; new="$(date -u -d '2 minutes ago' +%FT%TZ)"
printf '{"items":[{"metadata":{"name":"prometheus"},"status":{"operationState":{"phase":"Running","startedAt":"%s"}}},{"metadata":{"name":"kagent"},"status":{"operationState":{"phase":"Running","startedAt":"%s"}}},{"metadata":{"name":"ai-layer"},"status":{"operationState":{"phase":"Succeeded","startedAt":"%s"}}}]}' "$old" "$new" "$old" >"${T}/apps.json"
: >"${CALLS}"; src 'repair_stuck_syncs c /dev/null'
check "only the operation Running past the threshold is terminated" \
  'grep -q "patch application prometheus --type json" "${CALLS}" && ! grep -q "patch application kagent\|patch application ai-layer" "${CALLS}"'

echo "== repair_failed_syncs =="
printf '{"items":[{"metadata":{"name":"otel-operator"},"status":{"sync":{"status":"OutOfSync"},"operationState":{"phase":"Failed"}}},{"metadata":{"name":"ai-layer-otel"},"status":{"sync":{"status":"OutOfSync"},"operationState":{"phase":"Error"}}},{"metadata":{"name":"busy"},"operation":{"sync":{}},"status":{"sync":{"status":"OutOfSync"},"operationState":{"phase":"Failed"}}},{"metadata":{"name":"fine"},"status":{"sync":{"status":"Synced"},"operationState":{"phase":"Failed"}}}]}' >"${T}/apps.json"
: >"${CALLS}"; src 'repair_failed_syncs c /dev/null'
check "OutOfSync apps whose last operation failed get a sync operation; a Synced one and one already running do not" \
  'grep -q "patch application otel-operator --type merge" "${CALLS}" && grep -q "patch application ai-layer-otel --type merge" "${CALLS}" && ! grep -q "patch application busy\|patch application fine" "${CALLS}"'

echo "== repair_stuck_pods =="
printf '{"items":[{"metadata":{"namespace":"datadog","name":"datadog-agent-old","deletionTimestamp":"%s"}},{"metadata":{"namespace":"agent","name":"console-new","deletionTimestamp":"%s"}},{"metadata":{"namespace":"agent","name":"console-live"}}]}' "$old" "$new" >"${T}/pods.json"
: >"${CALLS}"; src 'repair_stuck_pods c /dev/null'
check "only the pod Terminating past the threshold is force-deleted" \
  'grep -q "\-n datadog delete pod datadog-agent-old --force --grace-period=0" "${CALLS}" && ! grep -q "delete pod console" "${CALLS}"'

echo "== prune_empty_states =="
echo '{"resources":[]}' >"${T}/states/watch-it-burn-attendee-105.tfstate"; echo '{"resources":[{"type":"x"}]}' >"${T}/states/watch-it-burn-attendee-001.tfstate"
src 'prune_empty_states'
check "an empty state is removed and a real one kept" '[[ ! -e "${T}/states/watch-it-burn-attendee-105.tfstate" && -e "${T}/states/watch-it-burn-attendee-001.tfstate" ]]'

echo "== verify_one =="
: >"${CALLS}"; VERIFY_RC=1 src 'verify_one watch-it-burn-attendee-002 /dev/null acct; cat "${FAIL_FILE}"; rm -f "${FAIL_FILE}"' >"${T}/out"
check "a failing datadog-orgs verifier is recorded as <name>:datadog-orgs" 'grep -qx "watch-it-burn-attendee-002:datadog-orgs" "${T}/out" && grep -q "^verify ctx-test acct" "${CALLS}"'

echo "== wiring =="
check "converge_one runs repair_one" 'grep -q "^    repair_one \"\${name}\" \"\${kcfg}\" \"\${acct_profile}\"" "${FLEET}"'
check "repair_one includes repair_failed_syncs" 'grep -q "^    repair_failed_syncs \"\${name}\" \"\${kcfg}\"" "${FLEET}"'
check "converge instructors skips roster slots with no state" 'grep -q "not provisioned, skipping" "${FLEET}"'
check "up ends with a converge pass over what it built" 'grep -q "repair-and-verify pass over" "${FLEET}"'
check "the post-up wait and verify iterate the PROVISION_SPEC names, never the register arguments" \
  'grep -q "wait_for_console_lbs \"\${built\[@\]}\"" "${FLEET}" && grep -q "for _n in \"\${built\[@\]}\"" "${FLEET}" && ! grep -q "wait_for_console_lbs \"\$@\"" "${FLEET}"'
: >"${CALLS}"; rm -f "${T}/k_polls"
src 'wait_for_console_lbs ""; echo rc=$?' >"${T}/out"
check "an empty name is not waited for" 'grep -qx "rc=0" "${T}/out" && [[ ! -f "${T}/k_polls" ]]'
check "bootstrap_one resolves keys through datadog_keys_for" 'grep -q "< <(datadog_keys_for \"\${name}\")" "${FLEET}"'
check "status, routes and converge prune empty states" '[[ "$(grep -c "^    prune_empty_states$" "${FLEET}")" -eq 3 ]]'

echo; echo "  ${pass} passed, ${fail} failed"
[[ -s "${T}/stderr" ]] && { echo "  (stderr, last lines)"; tail -4 "${T}/stderr" | sed 's/^/    /'; }
exit $(( fail > 0 ))
