#!/usr/bin/env bash
# ABOUTME: Behavioural test for roll-console.sh's ai-layer sync (#583): the operation it patches carries ai-layer's
# ABOUTME: own sync options, so RespectIgnoreDifferences keeps agentgateway's Bedrock pin; no options, no sync.
#
# Why (#583). Argo CD v3.5.2's controller reads RespectIgnoreDifferences from the sync operation alone; auto-sync and
# the API server copy .spec.syncPolicy.syncOptions in, a patched operation has only what the patch gives it. The bare
# {"operation":{"sync":{"revision":"staging"}}} this script wrote ran ai-layer without the option, which applies git's
# system id over agentgateway's BEDROCK_NOVA_MODEL ARN (verify/test_agent_tools_sync.py runs that through the port).
#
# Usage: verify/test_roll_console.sh      (offline; aws and kubectl are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLL="${HERE}/../infra/terraform/fleet/roll-console.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"; CALLS="${T}/calls"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
case "$*" in
  *"eks list-clusters"*) printf 'watch-it-burn-community\n' ;;
esac
exit 0
S
cat >"${SHIM}/kubectl" <<S
#!/usr/bin/env bash
echo "kubectl \$*" >>"${CALLS}"
case "\$*" in
  *"config current-context"*) echo "arn:aws:eks:us-west-2:515966504359:cluster/watch-it-burn-community" ;;
  *"-n argocd get app ai-layer -o json"*) cat "${T}/app.json" 2>/dev/null || exit 1 ;;
  *"get cm console-conf console-src -o json"*) echo '{"data":{"x":"ROLL MARKER"}}' ;;
esac
exit 0
S
chmod +x "${SHIM}/aws" "${SHIM}/kubectl"
run() { : >"${CALLS}"; PATH="${SHIM}:${PATH}" bash "${ROLL}" "ROLL MARKER" >"${T}/out" 2>&1; echo $?; }

echo "== roll-console.sh syncs ai-layer with ai-layer's own sync options =="
printf '%s' '{"metadata":{"name":"ai-layer"},"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true},"syncOptions":["CreateNamespace=true","ServerSideApply=true","Force=true","RespectIgnoreDifferences=true"]}}}' >"${T}/app.json"
rc="$(run)"
check "it rolls the cluster" '[[ "${rc}" -eq 0 ]] && grep -q "watch-it-burn-community: synced + console cycled" "${T}/out"'
check "the operation carries ai-layer's syncOptions, RespectIgnoreDifferences among them" \
  'grep -qF "patch app ai-layer --type merge -p {\"operation\":{\"sync\":{\"revision\":\"staging\",\"syncOptions\":[\"CreateNamespace=true\",\"ServerSideApply=true\",\"Force=true\",\"RespectIgnoreDifferences=true\"]}}}" "${CALLS}"'
check "and never a bare operation without them" '! grep -qF "{\"operation\":{\"sync\":{\"revision\":\"staging\"}}}" "${CALLS}"'

echo "== with ai-layer's sync options unreadable it does not sync =="
rm -f "${T}/app.json"; rc="$(run)"
check "no sync operation is patched" '! grep -q "patch app ai-layer" "${CALLS}"'
check "the console is not cycled" '! grep -q "delete pod" "${CALLS}"'
check "the cluster is named and the roll fails" \
  '[[ "${rc}" -ne 0 ]] && grep -q "could not read ai-layer.s sync options, NOT syncing" "${T}/out"'

echo
echo "${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
