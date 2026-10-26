#!/usr/bin/env bash
# ABOUTME: Behavioural test of fleet.sh pin_bedrock_profiles (#513, #561): each live Bedrock ModelConfig and agentgateway's
# ABOUTME: bedrock model env point at the cluster's tagged application profile; a pin with no tagged profile fails.
#
# Why. A system-defined inference profile cannot carry tags, so a ModelConfig left on us.amazon.nova-pro-v1:0
# bills untagged and the denial-of-wallet numbers on stage cannot be checked against the bill. The ARN that fixes
# it is per cluster and known only after apply, so it reaches the cluster here, not through git. The gateway path
# (#561) is the same pin on a different field: agentgateway's bedrock backend reads its model from the
# BEDROCK_NOVA_MODEL env of the agentgateway container, which commits the system id.
#
# Usage: verify/test_pin_bedrock_profiles.sh      (offline; terraform and kubectl are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
FLEET="${REPO}/infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${REPO}" .pin-bedrock-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/states" "${T}/logs" "${T}/live"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

ACCT=111122223333
arn() { echo "arn:aws:bedrock:us-west-2:${ACCT}:application-inference-profile/$1"; }
# The output as the cluster root writes it: system profile id -> this cluster's application profile ARN.
cat >"${T}/output.json" <<J
{"us.amazon.nova-pro-v1:0":"$(arn nova0001)","us.anthropic.claude-haiku-4-5-20251001-v1:0":"$(arn haiku001)",
 "us.anthropic.claude-sonnet-4-6":"$(arn sonnet01)","us.anthropic.claude-opus-4-8":"$(arn opus0001)"}
J
cat >"${SHIM}/terraform" <<'S'
#!/usr/bin/env bash
echo "terraform $*" >>"${CALLS}"
[[ "$*" == *"output -state="*"-json bedrock_application_profiles"* ]] || exit 1
cat "${T}/output.json" 2>/dev/null || { echo "No outputs found" >&2; exit 1; }
S
# kubectl answers `get modelconfig <n>` from ${T}/live/<n>; a patch writes the new model there and is recorded.
# `get deployment agentgateway` answers the env var its jsonpath names from ${T}/live/gw-<VAR>; `set env` writes it.
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $*" >>"${CALLS}"
args=("$@")
for i in "${!args[@]}"; do
  if [[ "${args[$i]}" == "modelconfig" ]]; then cfg="${args[$((i+1))]}"; fi
done
case "$*" in
  *" get modelconfig "*) cat "${T}/live/${cfg}" 2>/dev/null ;;
  *" patch modelconfig "*)
    [[ -f "${T}/patch_fails" ]] && exit 1
    for i in "${!args[@]}"; do [[ "${args[$i]}" == "-p" ]] && body="${args[$((i+1))]}"; done
    jq -r '.spec.model' <<<"${body}" >"${T}/live/${cfg}" ;;
  *" get deployment agentgateway "*)
    var="$(grep -o '@.name=="[A-Z_]*"' <<<"$*" | tail -1 | cut -d'"' -f2)"
    cat "${T}/live/gw-${var}" 2>/dev/null ;;
  *" set env deployment/agentgateway -c agentgateway "*)
    [[ -f "${T}/patch_fails" ]] && exit 1
    kv="${args[$(( ${#args[@]} - 1 ))]}"
    printf '%s\n' "${kv#*=}" >"${T}/live/gw-${kv%%=*}" ;;
esac
exit 0
S
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"
run() { # $1: the cluster name. Prints the function's exit code; its log goes to ${T}/stderr.
  ( cd "${REPO}" && WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" WIB_MODELCONFIG_WAIT="${WAIT:-0}" \
      WIB_MODELCONFIG_POLL=1 bash -c "source '${FLEET}' >/dev/null 2>&1
        rc=0; pin_bedrock_profiles '$1' /dev/null || rc=\$?; echo \$rc  # fleet.sh sets -e
        cat \"\${FAIL_FILE}\" >'${T}/ledger' 2>/dev/null || : >'${T}/ledger'" 2>"${T}/stderr" )
}
fresh() { # the four Bedrock ModelConfigs and the gateway as Argo first creates them, on their committed system ids
  rm -f "${T}/live/"* "${T}/patch_fails"; : >"${CALLS}"
  echo "us.amazon.nova-pro-v1:0" >"${T}/live/bedrock-nova"
  echo "us.anthropic.claude-haiku-4-5-20251001-v1:0" >"${T}/live/bedrock-haiku"
  echo "us.anthropic.claude-sonnet-4-6" >"${T}/live/bedrock-sonnet"
  echo "us.anthropic.claude-opus-4-8" >"${T}/live/bedrock-opus"
  echo "us.amazon.nova-pro-v1:0" >"${T}/live/gw-BEDROCK_NOVA_MODEL"
}

echo "== the committed Bedrock ModelConfigs are what gets pinned =="
configs="$(cd "${REPO}" && bash -c "source '${FLEET}' >/dev/null 2>&1; bedrock_modelconfigs")"
check "all four Bedrock ModelConfigs are read from resources.yaml" '[[ "$(wc -l <<<"${configs}")" -eq 4 ]]'
check "the workshop default bedrock-nova is one of them, on its system id" \
  'grep -qx "bedrock-nova us.amazon.nova-pro-v1:0" <<<"${configs}"'
check "the gateway-* configs (OpenAI provider, agentgateway backend names) are not" \
  '! grep -q "^gateway-" <<<"${configs}"'

echo "== agentgateway's bedrock backend is pinned through its container env (#561) =="
gw="$(cd "${REPO}" && bash -c "source '${FLEET}' >/dev/null 2>&1; bedrock_gateway_models")"
check "its one bedrock backend reads BEDROCK_NOVA_MODEL, committed to the nova system id" \
  '[[ "${gw}" == "BEDROCK_NOVA_MODEL us.amazon.nova-pro-v1:0" ]]'

echo "== a fresh cluster: every Bedrock ModelConfig moves to its tagged profile =="
fresh; rc="$(run watch-it-burn-attendee-001)"
check "it succeeds" '[[ "${rc}" == "0" ]]'
check "bedrock-nova now calls the cluster's nova profile" '[[ "$(cat "${T}/live/bedrock-nova")" == "$(arn nova0001)" ]]'
check "bedrock-opus now calls the cluster's opus profile" '[[ "$(cat "${T}/live/bedrock-opus")" == "$(arn opus0001)" ]]'
check "agentgateway's BEDROCK_NOVA_MODEL now names the cluster's nova profile" \
  '[[ "$(cat "${T}/live/gw-BEDROCK_NOVA_MODEL")" == "$(arn nova0001)" ]]'
check "it is set on the agentgateway container, not the C7 one" \
  'grep -q "set env deployment/agentgateway -c agentgateway BEDROCK_NOVA_MODEL=$(arn nova0001)" "${CALLS}"'
check "the map is read from this cluster's own state" \
  'grep -q "output -state=${T}/states/watch-it-burn-attendee-001.tfstate -json bedrock_application_profiles" "${CALLS}"'
check "nothing is recorded as failed" '[[ ! -s "${T}/ledger" ]]'

echo "== idempotent: a pinned cluster is left alone =="
: >"${CALLS}"; rc="$(run watch-it-burn-attendee-001)"
check "it succeeds again" '[[ "${rc}" == "0" ]]'
check "and patches nothing" '! grep -q "patch modelconfig" "${CALLS}"'
check "and leaves the gateway alone, so it does not roll on every converge" '! grep -q "set env" "${CALLS}"'

echo "== a pin with no tagged profile fails, it does not leave the spend untagged quietly =="
fresh; jq 'del(."us.anthropic.claude-opus-4-8")' "${T}/output.json" >"${T}/o2" && cp "${T}/output.json" "${T}/output.full" && mv "${T}/o2" "${T}/output.json"
rc="$(run watch-it-burn-attendee-001)"
check "it returns non-zero" '[[ "${rc}" == "1" ]]'
check "the ledger names the cluster" 'grep -qx "watch-it-burn-attendee-001:bedrock-profiles" "${T}/ledger"'
check "it says which ModelConfig and which id" 'grep -q "bedrock-opus pins us.anthropic.claude-opus-4-8" "${T}/stderr"'
check "the others are still pinned" '[[ "$(cat "${T}/live/bedrock-nova")" == "$(arn nova0001)" ]]'
cp "${T}/output.full" "${T}/output.json"

echo "== a cluster applied before #513 has no output: a failure that says to re-apply =="
fresh; mv "${T}/output.json" "${T}/output.away"; rc="$(run watch-it-burn-attendee-001)"; mv "${T}/output.away" "${T}/output.json"
check "it returns non-zero" '[[ "${rc}" == "1" ]]'
check "the ledger names the cluster" 'grep -qx "watch-it-burn-attendee-001:bedrock-profiles" "${T}/ledger"'
check "it says to re-apply" 'grep -q "re-apply the cluster" "${T}/stderr"'
check "it patches nothing" '! grep -q "patch modelconfig\|set env" "${CALLS}"'

echo "== a ModelConfig Argo has not created fails after the wait, and a failed patch fails =="
fresh; rm -f "${T}/live/bedrock-sonnet"; rc="$(WAIT=1 run watch-it-burn-attendee-001)"
check "a missing ModelConfig returns non-zero" '[[ "${rc}" == "1" ]]'
check "and says it never appeared" 'grep -q "bedrock-sonnet never appeared" "${T}/stderr"'
fresh; touch "${T}/patch_fails"; rc="$(run watch-it-burn-attendee-001)"
check "a refused patch returns non-zero" '[[ "${rc}" == "1" ]]'
check "and is in the ledger" 'grep -qx "watch-it-burn-attendee-001:bedrock-profiles" "${T}/ledger"'
fresh; rm -f "${T}/live/gw-BEDROCK_NOVA_MODEL"; rc="$(WAIT=1 run watch-it-burn-attendee-001)"
check "a gateway without the env var fails after the wait" '[[ "${rc}" == "1" ]]'
check "and says so" 'grep -q "agentgateway.s BEDROCK_NOVA_MODEL never appeared" "${T}/stderr"'
check "the ModelConfigs are still pinned" '[[ "$(cat "${T}/live/bedrock-nova")" == "$(arn nova0001)" ]]'

echo "== a gateway config the pin cannot reach fails, it does not pass with the gateway path untagged =="
# The same function against a copy of the repo whose agentgateway.yaml is broken one way at a time. fleet.sh
# finds the repo from its own path (REPO_ROOT is readonly), so the copy carries fleet/ as well.
mkrepo() { rm -rf "${T}/repo"; mkdir -p "${T}/repo/gitops/ai-layer" "${T}/repo/infra/terraform/fleet"
  cp -r "${FLEET}" "${REPO}/infra/terraform/fleet/event.sh" "${REPO}/infra/terraform/fleet/providers" "${T}/repo/infra/terraform/fleet/"
  cp "${REPO}/gitops/ai-layer/resources.yaml" "${REPO}/gitops/ai-layer/agentgateway.yaml" "${T}/repo/gitops/ai-layer/"; }
run_in() { # $1: the repo copy. Prints the exit code, like run.
  ( cd "$1" && WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" WIB_MODELCONFIG_WAIT=0 \
      bash -c "source '$1/infra/terraform/fleet/fleet.sh' >/dev/null 2>&1
        rc=0; pin_bedrock_profiles watch-it-burn-attendee-001 /dev/null || rc=\$?; echo \$rc" 2>"${T}/stderr" )
}
fresh; mkrepo; sed -i 's/model: \${BEDROCK_NOVA_MODEL}/model: us.amazon.nova-pro-v1:0/' "${T}/repo/gitops/ai-layer/agentgateway.yaml"
rc="$(run_in "${T}/repo")"
check "a bedrock backend naming its model inline returns non-zero" '[[ "${rc}" == "1" ]]'
check "and says it cannot be pinned" 'grep -q "names us.amazon.nova-pro-v1:0 inline" "${T}/stderr"'
fresh; mkrepo; sed -i 's/- name: BEDROCK_NOVA_MODEL/- name: BEDROCK_NOVA_MODEL_UNUSED/' "${T}/repo/gitops/ai-layer/agentgateway.yaml"
rc="$(run_in "${T}/repo")"
check "a variable the container does not set returns non-zero" '[[ "${rc}" == "1" ]]'
check "and names it" 'grep -q "reads BEDROCK_NOVA_MODEL, which the agentgateway container does not set" "${T}/stderr"'

echo "== it runs where the cluster's ModelConfigs are set up and repaired =="
src="$(cat "${FLEET}")"
check "bootstrap_one pins after the IDP is installed" \
  'sed -n "/^bootstrap_one() {/,/^}/p" <<<"${src}" | grep -q "pin_bedrock_profiles \"\${name}\" \"\${kcfg}\""'
check "converge's repair_one pins too" \
  'sed -n "/^repair_one() {/,/^}/p" <<<"${src}" | grep -q "pin_bedrock_profiles \"\${name}\" \"\${kcfg}\""'
app="$(cat "${REPO}/gitops/bootstrap/apps/ai-layer.yaml")"
check "Argo ignores .spec.model on Bedrock ModelConfigs, so selfHeal keeps the ARN" \
  'grep -qF ".spec | select(.provider == \"Bedrock\") | .model" <<<"${app}"'
check "Argo ignores agentgateway's BEDROCK_NOVA_MODEL env entry by name, so selfHeal keeps the ARN" \
  'grep -qF "select(.name==\"agentgateway\") | .env[] | select(.name == \"BEDROCK_NOVA_MODEL\")" <<<"${app}"'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
