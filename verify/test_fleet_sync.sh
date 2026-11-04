#!/usr/bin/env bash
# ABOUTME: Behavioural test for `fleet.sh sync <application> <name...>` (#583): the by-hand sync writes the app's own
# ABOUTME: sync options, prune and retry, refuses an app with an operation pending, and waits for the result.
#
# Why (#583). On 2026-11-01 a by-hand sync of ai-layer on both KubeCon clusters wrote an operation without
# RespectIgnoreDifferences. Argo CD v3.5.2 reads that option from the operation alone, so the sync put git's Bedrock
# system id back over agentgateway's BEDROCK_NOVA_MODEL and every Bedrock ModelConfig's ARN.
#
# Usage: verify/test_fleet_sync.sh      (offline; kubectl is a shim, the per-cluster function runs on a sourced fleet.sh)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"; CALLS="${T}/calls"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# The Application before the sync, and after it: the shim answers with after.json once a patch has been made.
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $*" >>"${CALLS}"
case "$*" in
  *"-n argocd get application ai-layer -o json"*)
    if [[ -f "${T}/patched" ]]; then cat "${T}/after.json"; else cat "${T}/before.json"; fi ;;
  *"-n argocd get application"*) exit 1 ;;
  *"-n argocd patch application ai-layer --type merge"*) touch "${T}/patched" ;;
esac
exit 0
S
chmod +x "${SHIM}/kubectl"
export T CALLS PATH="${SHIM}:${PATH}"
POLICY='"syncPolicy":{"automated":{"prune":true,"selfHeal":true},"syncOptions":["CreateNamespace=true","ServerSideApply=true","Force=true","RespectIgnoreDifferences=true"],"retry":{"limit":5}}'
OLD_STATE='"operationState":{"phase":"Succeeded","startedAt":"2026-11-01T16:36:40Z"}'
app() { printf '{"metadata":{"name":"ai-layer"},"spec":{%s}%s,"status":{%s}}' "${POLICY}" "$1" "$2"; }
run() { # $1 application; prints the exit code, logs to ${T}/stderr
  rm -f "${T}/patched"; : >"${CALLS}"; : >"${T}/stderr"
  ( cd "$(dirname "${FLEET}")" && WIB_SYNC_POLL=0 WIB_SYNC_WAIT=3 bash -c "source '${FLEET}' >/dev/null 2>&1
      SYNC_APP='$1' sync_app_one watch-it-burn-community /dev/null watch-it-burn-community" 2>>"${T}/stderr" )
  echo $?
}

echo "== fleet.sh sync writes the app's own operation and waits for it =="
app "" "${OLD_STATE}" >"${T}/before.json"
app "" '"operationState":{"phase":"Succeeded","startedAt":"2026-11-04T21:00:00Z","message":"successfully synced"}' >"${T}/after.json"
rc="$(run ai-layer)"
check "it succeeds once the new operation reads Succeeded" '[[ "${rc}" -eq 0 ]] && grep -q "ai-layer sync Succeeded" "${T}/stderr"'
check "the operation carries ai-layer's syncOptions, RespectIgnoreDifferences among them, with its prune and retry" \
  'grep -qF "patch application ai-layer --type merge -p {\"operation\":{\"initiatedBy\":{\"username\":\"fleet-sync\"},\"sync\":{\"prune\":true,\"syncOptions\":[\"CreateNamespace=true\",\"ServerSideApply=true\",\"Force=true\",\"RespectIgnoreDifferences=true\"]},\"retry\":{\"limit\":5}}}" "${CALLS}"'
check "every call names the cluster's context" '! grep -v -- "--context watch-it-burn-community" "${CALLS}" | grep -q .'

echo "== it fails on a sync that fails, and on one that never finishes =="
app "" '"operationState":{"phase":"Failed","startedAt":"2026-11-04T21:00:00Z","message":"one or more objects failed to apply"}' >"${T}/after.json"
rc="$(run ai-layer)"
check "a Failed sync fails the verb and says so" '[[ "${rc}" -ne 0 ]] && grep -q "ai-layer sync Failed one or more objects failed to apply" "${T}/stderr"'
cp "${T}/before.json" "${T}/after.json"
rc="$(run ai-layer)"
check "an operation that never starts (the old state still shown) times out" \
  '[[ "${rc}" -ne 0 ]] && grep -q "ai-layer.s sync did not finish in 3s" "${T}/stderr"'

echo "== it refuses an app with an operation pending, and an app that is not there =="
app ',"operation":{"sync":{"resources":[{"kind":"Deployment","name":"guard-proxy"}]}}' "${OLD_STATE}" >"${T}/before.json"
rc="$(run ai-layer)"
check "a pending operation is not merged into (the #679 trap)" \
  '[[ "${rc}" -ne 0 ]] && ! grep -q "patch application" "${CALLS}" && grep -q "already has an operation pending" "${T}/stderr"'
rc="$(run no-such-app)"
check "a missing Application fails, naming it" '[[ "${rc}" -ne 0 ]] && grep -q "no Application no-such-app" "${T}/stderr"'

echo "== the verb is wired =="
check "main dispatches sync to cmd_sync" 'grep -qE "^        sync\) cmd_sync \"\\\$@\" ;;" "${FLEET}"'
check "usage names it" 'grep -q "^    sync <application> <name...>" "${FLEET}"'
check "with too few arguments it prints usage and exits 2" \
  '( cd "$(dirname "${FLEET}")" && bash "${FLEET}" sync ai-layer >/dev/null 2>"${T}/usage" ); [[ $? -eq 2 ]] && grep -q "usage: sync <application> <name...>" "${T}/usage"'

echo
echo "${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
