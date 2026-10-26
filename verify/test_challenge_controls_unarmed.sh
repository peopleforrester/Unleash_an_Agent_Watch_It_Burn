#!/usr/bin/env bash
# ABOUTME: A presenter's cluster must start a challenge in the same state as a student's, so the C1 and C3
# ABOUTME: controls ship UNARMED on every profile that runs the lab. Offline: reads the bootstrap values files.
#
# Why (#281). network-policies and kubearmor-policies are the Challenge 1 and Challenge 3 controls. The
# attendee profile has always left them out, which is why a student's attack lands and their fix arms it.
# The full profile shipped them, so on the guarded instructor clusters the first attack was pre-blocked,
# and both apps run selfHeal with no ignoreDifferences: deleting the policies to stage the attack restored
# them in about a second (measured on r3-3). The presenter was left with a dead demo and no visible cause,
# on the first challenge, in front of the room.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${HERE}/.."
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# The set of apps that arm a challenge control. Adding one here without leaving it out of a profile is the bug.
CHALLENGE_APPS=(network-policies kubearmor-policies)

# selection <profile> -> ",app1,app2,...," : the apps gitops/bootstrap/values-<profile>.yaml lists (#609),
# comma-fenced so a name matches only itself (otel-collector is not otel-collector-burn); "none" if no file.
selection() {
    python3 -c '
import sys, yaml, pathlib
f = pathlib.Path(f"gitops/bootstrap/values-{sys.argv[1]}.yaml")
print("," + ",".join(yaml.safe_load(f.read_text())["apps"]) + "," if f.is_file() else "none")
' "$1"
}
has() { [[ "$1" == *",$2,"* ]]; }

cd "${REPO}" || exit 1

echo "== every profile that runs the lab ships the challenge controls unarmed =="
for prof in full attendee; do
    sel="$(selection "${prof}")"
    check "${prof}: a values file lists its apps" '[[ "$sel" != none ]]'
    for app in "${CHALLENGE_APPS[@]}"; do
        check "${prof}: ${app} is not deployed at bootstrap" '! has "$sel" "${app}"'
    done
done

echo "== burn ships them too =="
sel_burn="$(selection burn)"
check "burn: a values file lists its apps" '[[ "$sel_burn" != none ]]'
for app in "${CHALLENGE_APPS[@]}"; do
    check "burn: ${app} is not in the list" '! has "$sel_burn" "${app}"'
done

echo "== the two lab profiles agree with each other =="
# They differ in which collector each takes and in attendee's #475 omissions, never by a challenge control.
f_sel="$(selection full)"; a_sel="$(selection attendee)"
# Reduce each side to a word first: bash cannot compare two conditional expressions directly.
named() { if has "$1" "$2"; then echo yes; else echo no; fi; }
for app in "${CHALLENGE_APPS[@]}"; do
    check "full and attendee treat ${app} the same" \
        '[[ "$(named "$f_sel" "$app")" == "$(named "$a_sel" "$app")" ]]'
done

echo "== admin is the ONE profile that arms them, on purpose =="
# The presenters demonstrate a control already working rather than staging an attack, so selfHeal is not
# a hazard there and the armed state is the point (#294). This is an exception with a reason, which is why
# it is asserted explicitly rather than the checks above being loosened.
sel_admin="$(selection admin)"
check "an admin profile exists" '[[ "$sel_admin" != none ]]'
for app in "${CHALLENGE_APPS[@]}"; do
    check "admin: ${app} IS deployed (armed by design)" 'has "$sel_admin" "${app}"'
done
check "admin takes the non-dual collector (it ships to the shared org directly)" \
    'has "$sel_admin" otel-collector && ! has "$sel_admin" otel-collector-attendee'

echo "== the community cluster can be WATCHED, even though nothing defends it =="
# Observability is not a guardrail. attackme ships no enforcement at all and must still emit telemetry,
# or the Community phase ends with the room unable to see what it just did (#283, #296, #303).
for app in otel-collector-burn otel-operator ai-layer-otel datadog-operator datadog-agent-cr external-secrets; do
    check "burn ships ${app}" 'has "$sel_burn" "${app}"'
done
for app in kyverno kyverno-policies minimal-floor falco network-policies kubearmor-policies; do
    check "burn still ships NO ${app}" '! has "$sel_burn" "${app}"'
done

echo "== the controls still EXIST to be applied as the fix =="
# Leaving them out of bootstrap must not mean deleting them: the student and the presenter both apply
# them by hand, from the staged manifests, as the fix step.
check "the C1 NetworkPolicies are still in the repo" \
    '[[ -f policies/network-policies/per-namespace/agent-egress-allowlist.yaml ]]'
check "the C3 KubeArmor policy is still in the repo" \
    '[[ -f policies/kubearmor/block-recipe-snoop.yaml ]]'
check "the C1 fix manifest is still staged for the terminal" \
    'grep -q "c1-network-policy.yaml" gitops/ai-layer/resources.yaml'
check "the C3 fix manifest is still staged for the terminal" \
    'grep -q "c3-kubearmor-policy.yaml" gitops/ai-layer/resources.yaml'

echo "== a rehearsal must not leave a challenge pre-solved =="
# The probe's attacks BUILD things, and only its toggles were being restored (#285).
PROBE="${REPO}/verify/agent_probe.py"; WALK="${REPO}/verify/fleet-walkthrough.sh"
check "the probe removes the Deployment its C6 beat creates" 'grep -q "remove_c6_artifact" "${PROBE}"'
check "it does so in the same restore path as the guards" 'grep -q "c6 artifact:" "${PROBE}"'
check "the acceptance pass fails a cluster that still has one" 'grep -q "c6-artifact-present" "${WALK}"'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
