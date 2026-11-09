#!/usr/bin/env bash
# ABOUTME: Behavioural test of fleet.sh pin_coc_guardrail (#1279): the cluster root's code-of-conduct guardrail id, version
# ABOUTME: and region reach agent/coc-guardrail, which guard-proxy reads as env; guard-proxy restarts only on a change.
#
# Why. The guardrail's id is Bedrock's pick and its version is published by the apply, so neither can be committed:
# they reach the cluster here, as pin_bedrock_profiles hands over the tagged profiles' ARNs (#513). guard-proxy reads
# BEDROCK_GUARDRAIL_ID, _VERSION and _REGION from this ConfigMap at start (gitops/ai-layer/resources.yaml), so a pin
# that wrote the map and left the pod running would leave the classifier unconfigured until some later restart.
#
# Usage: verify/test_pin_coc_guardrail.sh      (offline; terraform and kubectl are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
FLEET="${REPO}/infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${REPO}" .pin-coc-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/states" "${T}/logs" "${T}/live"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# Offline means offline (#859): aws, kubectl, eksctl, terraform and helm are stubs that log the call and fail,
# even when the test is run by hand (verify/no-cloud.sh). The last check reads the log.
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${HERE}/no-cloud.sh"; no_cloud_guard "${T}/no-cloud"

# The output as the cluster root writes it (output "coc_guardrail").
out() { printf '{"id":"%s","version":"%s","region":"%s"}\n' "$1" "$2" "$3" >"${T}/output.json"; }
cat >"${SHIM}/terraform" <<'S'
#!/usr/bin/env bash
echo "terraform $*" >>"${CALLS}"
[[ "$*" == *"output -state="*"-json coc_guardrail"* ]] || exit 1
cat "${T}/output.json" 2>/dev/null || { echo "No outputs found" >&2; exit 1; }
S
# kubectl answers `get configmap coc-guardrail` from ${T}/live/cm.json; apply stores what it reads; delete pod is logged.
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $*" >>"${CALLS}"
case "$*" in
  *" get configmap coc-guardrail "*)
    [[ -f "${T}/live/cm.json" ]] || { echo 'configmaps "coc-guardrail" not found' >&2; exit 1; }
    cat "${T}/live/cm.json" ;;
  *"apply -f -"*)
    body="$(cat)"
    [[ -f "${T}/cm_fails" ]] && exit 1
    printf '%s\n' "${body}" >"${T}/live/cm.json" ;;
  *" delete pod "*) [[ -f "${T}/restart_fails" ]] && exit 1 ;;
esac
exit 0
S
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"
run() { # $1: the cluster name. Prints the function's exit code; its log goes to ${T}/stderr.
  ( cd "${REPO}" && WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" bash -c "source '${FLEET}' >/dev/null 2>&1
        rc=0; pin_coc_guardrail '$1' /dev/null || rc=\$?; echo \$rc  # fleet.sh sets -e
        cat \"\${FAIL_FILE}\" >'${T}/ledger' 2>/dev/null || : >'${T}/ledger'" 2>"${T}/stderr" )
}
fresh() { rm -f "${T}/live/"* "${T}/cm_fails" "${T}/restart_fails"; : >"${CALLS}"; out gr-abc123 1 us-west-2; }
cm() { jq -r "$1" "${T}/live/cm.json" 2>/dev/null; }

echo "== a fresh cluster: the guardrail reaches agent/coc-guardrail and guard-proxy restarts to read it =="
fresh; rc="$(run watch-it-burn-attendee-001)"
check "it succeeds" '[[ "${rc}" == "0" ]]'
check "the output is read from this cluster's own state" \
  'grep -q "output -state=${T}/states/watch-it-burn-attendee-001.tfstate -json coc_guardrail" "${CALLS}"'
check "agent/coc-guardrail is written, in agent" \
  '[[ "$(cm .kind)" == ConfigMap && "$(cm .metadata.name)" == coc-guardrail && "$(cm .metadata.namespace)" == agent ]]'
check "with exactly the id, version and region keys" '[[ "$(cm ".data | keys | join(\" \")")" == "id region version" ]]'
check "naming the cluster's guardrail, its published version and its region" \
  '[[ "$(cm .data.id)" == gr-abc123 && "$(cm .data.version)" == 1 && "$(cm .data.region)" == us-west-2 ]]'
check "guard-proxy's pods are restarted, since they read their env only at start" \
  'grep -q "kubectl -n agent delete pod -l app.kubernetes.io/name=guard-proxy" "${CALLS}"'
check "and the log names what guard-proxy now calls" 'grep -q "names guardrail gr-abc123 version 1 in us-west-2" "${T}/stderr"'
check "nothing is recorded as failed" '[[ ! -s "${T}/ledger" ]]'

echo "== idempotent: a pinned cluster is left alone, so converge does not restart guard-proxy each pass =="
: >"${CALLS}"; rc="$(run watch-it-burn-attendee-001)"
check "it succeeds again" '[[ "${rc}" == "0" ]]'
check "and neither rewrites the map nor restarts guard-proxy" '! grep -q "apply -f -\|delete pod" "${CALLS}"'

echo "== a new published version (a settings change) moves guard-proxy to it =="
out gr-abc123 2 us-west-2; : >"${CALLS}"; rc="$(run watch-it-burn-attendee-001)"
check "it succeeds" '[[ "${rc}" == "0" ]]'
check "the map names version 2" '[[ "$(cm .data.version)" == 2 && "$(cm .data.id)" == gr-abc123 ]]'
check "and guard-proxy restarts once" '[[ "$(grep -c "delete pod" "${CALLS}")" == 1 ]]'

echo "== a standby in another region names its own =="
fresh; out gr-east01 1 us-east-2; rc="$(run watch-it-burn-community-b01)"
check "it succeeds, with the standby's region" '[[ "${rc}" == "0" && "$(cm .data.region)" == us-east-2 && "$(cm .data.id)" == gr-east01 ]]'

echo "== a cluster applied before #1279 has no output: a failure that says to re-apply =="
fresh; rm -f "${T}/output.json"; rc="$(run watch-it-burn-attendee-001)"
check "it returns non-zero" '[[ "${rc}" == "1" ]]'
check "the ledger names the cluster" 'grep -qx "watch-it-burn-attendee-001:coc-guardrail" "${T}/ledger"'
check "it says to re-apply" 'grep -q "re-apply the cluster" "${T}/stderr"'
check "it writes nothing and restarts nothing" '! grep -q "apply -f -\|delete pod" "${CALLS}"'

echo "== an output with no numbered version (DRAFT) is refused: DRAFT changes under a running guard-proxy =="
fresh; out gr-abc123 DRAFT us-west-2; rc="$(run watch-it-burn-attendee-001)"
check "it returns non-zero" '[[ "${rc}" == "1" ]]'
check "and writes no map" '[[ ! -f "${T}/live/cm.json" ]]'
fresh; out "" 1 us-west-2; rc="$(run watch-it-burn-attendee-001)"
check "an empty id is refused too" '[[ "${rc}" == "1" && ! -f "${T}/live/cm.json" ]]'

echo "== a map the cluster refuses fails the pin =="
fresh; touch "${T}/cm_fails"; rc="$(run watch-it-burn-attendee-001)"
check "it returns non-zero" '[[ "${rc}" == "1" ]]'
check "the ledger names the cluster" 'grep -qx "watch-it-burn-attendee-001:coc-guardrail" "${T}/ledger"'
check "it says what is missing" 'grep -q "could not write agent/coc-guardrail" "${T}/stderr"'
check "and restarts no guard-proxy for a map it did not write" '! grep -q "delete pod" "${CALLS}"'
fresh; touch "${T}/restart_fails"; rc="$(run watch-it-burn-attendee-001)"
check "a failed restart is logged, and the written map still counts" \
  '[[ "${rc}" == "0" && "$(cm .data.id)" == gr-abc123 ]] && grep -q "guard-proxy restart failed" "${T}/stderr"'

echo "== it runs where the cluster is set up and repaired =="
src="$(cat "${FLEET}")"
check "bootstrap_one pins after the IDP is installed" \
  'sed -n "/^bootstrap_one() {/,/^}/p" <<<"${src}" | grep "pin_coc_guardrail \"\${name}\" \"\${kcfg}\"" >/dev/null'
check "converge's repair_one pins too" \
  'sed -n "/^repair_one() {/,/^}/p" <<<"${src}" | grep "pin_coc_guardrail \"\${name}\" \"\${kcfg}\"" >/dev/null'

echo "== guard-proxy reads the keys the pin writes, and the root outputs what the pin reads =="
envs="$(python3 - "${REPO}/gitops/ai-layer/resources.yaml" <<'P'
import sys, yaml
for d in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")):
    if d and d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy":
        for c in d["spec"]["template"]["spec"]["containers"]:
            for e in c.get("env", []):
                ref = (e.get("valueFrom") or {}).get("configMapKeyRef")
                if ref and ref["name"] == "coc-guardrail":
                    print(e["name"], ref["key"], ref.get("optional"))
P
)"
check "BEDROCK_GUARDRAIL_ID, _VERSION and _REGION come from the id, version and region keys, each optional" \
  '[[ "${envs}" == $'"'"'BEDROCK_GUARDRAIL_ID id True\nBEDROCK_GUARDRAIL_VERSION version True\nBEDROCK_GUARDRAIL_REGION region True'"'"' ]]'
tf="$(sed -n '/^output "coc_guardrail" {/,/^}/p' "${REPO}/infra/terraform/aws/cluster/main.tf")"
check "the cluster root's coc_guardrail output carries the guardrail id, the published version and the region" \
  'grep -q "id      = aws_bedrock_guardrail.coc.guardrail_id" <<<"${tf}" &&
   grep -q "version = aws_bedrock_guardrail_version.coc.version" <<<"${tf}" && grep -q "region  = var.region" <<<"${tf}"'

echo "== offline means offline =="
check "no check above called aws, kubectl, eksctl, terraform or helm" 'no_cloud_clean'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
