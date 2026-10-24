#!/usr/bin/env bash
# ABOUTME: Behavioural test of fleet.sh pin_bedrock_profiles (#513): each live Bedrock ModelConfig is pointed at
# ABOUTME: the cluster's tagged application profile, and a pin with no tagged profile fails instead of passing.
#
# Why. A system-defined inference profile cannot carry tags, so a ModelConfig left on us.amazon.nova-pro-v1:0
# bills untagged and the denial-of-wallet numbers on stage cannot be checked against the bill. The ARN that fixes
# it is per cluster and known only after apply, so it reaches the cluster here, not through git.
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
fresh() { # the four Bedrock ModelConfigs as Argo first creates them, on their committed system ids
  rm -f "${T}/live/"* "${T}/patch_fails"; : >"${CALLS}"
  echo "us.amazon.nova-pro-v1:0" >"${T}/live/bedrock-nova"
  echo "us.anthropic.claude-haiku-4-5-20251001-v1:0" >"${T}/live/bedrock-haiku"
  echo "us.anthropic.claude-sonnet-4-6" >"${T}/live/bedrock-sonnet"
  echo "us.anthropic.claude-opus-4-8" >"${T}/live/bedrock-opus"
}

echo "== the committed Bedrock ModelConfigs are what gets pinned =="
configs="$(cd "${REPO}" && bash -c "source '${FLEET}' >/dev/null 2>&1; bedrock_modelconfigs")"
check "all four Bedrock ModelConfigs are read from resources.yaml" '[[ "$(wc -l <<<"${configs}")" -eq 4 ]]'
check "the workshop default bedrock-nova is one of them, on its system id" \
  'grep -qx "bedrock-nova us.amazon.nova-pro-v1:0" <<<"${configs}"'
check "the gateway-* configs (OpenAI provider, agentgateway backend names) are not" \
  '! grep -q "^gateway-" <<<"${configs}"'

echo "== a fresh cluster: every Bedrock ModelConfig moves to its tagged profile =="
fresh; rc="$(run watch-it-burn-attendee-001)"
check "it succeeds" '[[ "${rc}" == "0" ]]'
check "bedrock-nova now calls the cluster's nova profile" '[[ "$(cat "${T}/live/bedrock-nova")" == "$(arn nova0001)" ]]'
check "bedrock-opus now calls the cluster's opus profile" '[[ "$(cat "${T}/live/bedrock-opus")" == "$(arn opus0001)" ]]'
check "the map is read from this cluster's own state" \
  'grep -q "output -state=${T}/states/watch-it-burn-attendee-001.tfstate -json bedrock_application_profiles" "${CALLS}"'
check "nothing is recorded as failed" '[[ ! -s "${T}/ledger" ]]'

echo "== idempotent: a pinned cluster is left alone =="
: >"${CALLS}"; rc="$(run watch-it-burn-attendee-001)"
check "it succeeds again" '[[ "${rc}" == "0" ]]'
check "and patches nothing" '! grep -q "patch modelconfig" "${CALLS}"'

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
check "it patches nothing" '! grep -q "patch modelconfig" "${CALLS}"'

echo "== a ModelConfig Argo has not created fails after the wait, and a failed patch fails =="
fresh; rm -f "${T}/live/bedrock-sonnet"; rc="$(WAIT=1 run watch-it-burn-attendee-001)"
check "a missing ModelConfig returns non-zero" '[[ "${rc}" == "1" ]]'
check "and says it never appeared" 'grep -q "bedrock-sonnet never appeared" "${T}/stderr"'
fresh; touch "${T}/patch_fails"; rc="$(run watch-it-burn-attendee-001)"
check "a refused patch returns non-zero" '[[ "${rc}" == "1" ]]'
check "and is in the ledger" 'grep -qx "watch-it-burn-attendee-001:bedrock-profiles" "${T}/ledger"'

echo "== it runs where the cluster's ModelConfigs are set up and repaired =="
src="$(cat "${FLEET}")"
check "bootstrap_one pins after the IDP is installed" \
  'sed -n "/^bootstrap_one() {/,/^}/p" <<<"${src}" | grep -q "pin_bedrock_profiles \"\${name}\" \"\${kcfg}\""'
check "converge's repair_one pins too" \
  'sed -n "/^repair_one() {/,/^}/p" <<<"${src}" | grep -q "pin_bedrock_profiles \"\${name}\" \"\${kcfg}\""'
app="$(cat "${REPO}/gitops/apps/ai-layer.yaml")"
check "Argo ignores .spec.model on Bedrock ModelConfigs, so selfHeal keeps the ARN" \
  'grep -qF ".spec | select(.provider == \"Bedrock\") | .model" <<<"${app}"'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
