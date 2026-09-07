#!/usr/bin/env bash
# ABOUTME: A presenter's cluster must start a challenge in the same state as a student's, so the C1 and C3
# ABOUTME: controls ship UNARMED on every profile that runs the lab. Offline: reads the bootstrap manifests.
#
# Why (#281). network-policies and kubearmor-policies are the Challenge 1 and Challenge 3 controls. The
# attendee profile has always excluded them, which is why a student's attack lands and their fix arms it.
# The full profile shipped them, so on rounds 2 and 3 the first attack was pre-blocked, and both apps run
# selfHeal with no ignoreDifferences: deleting the policies to stage the attack restored them in about a
# second (measured on r3-3). The presenter was left with a dead demo and no visible cause, on the first
# challenge, in front of the room.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${HERE}/.."
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# The set of apps that arm a challenge control. Adding one here without excluding it is the bug.
CHALLENGE_APPS=(network-policies kubearmor-policies)

selection() { # selection <profile> -> "exclude:<glob>" or "include:<glob>"
    python3 - "$1" <<'PY'
import sys, yaml, pathlib, glob
prof = sys.argv[1]
for f in sorted(glob.glob(f"gitops/bootstrap/{prof}/*.yaml")):
    for d in yaml.safe_load_all(pathlib.Path(f).read_text()):
        if not d or d.get("kind") != "Application": continue
        sp = d["spec"]
        for s in ([sp["source"]] if "source" in sp else sp.get("sources", [])):
            if s.get("path") == "gitops/apps" and s.get("directory"):
                dd = s["directory"]
                if dd.get("exclude"): print("exclude:" + dd["exclude"]); raise SystemExit
                if dd.get("include"): print("include:" + dd["include"]); raise SystemExit
print("none:")
PY
}

cd "${REPO}" || exit 1

echo "== every profile that runs the lab ships the challenge controls unarmed =="
for prof in full attendee; do
    sel="$(selection "${prof}")"
    for app in "${CHALLENGE_APPS[@]}"; do
        check "${prof}: ${app} is not deployed at bootstrap" '[[ "$sel" == exclude:* && "$sel" == *"${app}"* ]]'
    done
done

echo "== burn ships them too (it uses an include list, so absence is what matters) =="
sel_burn="$(selection burn)"
check "burn uses an include list" '[[ "$sel_burn" == include:* ]]'
for app in "${CHALLENGE_APPS[@]}"; do
    check "burn: ${app} is not in the include list" '[[ "$sel_burn" != *"${app}"* ]]'
done

echo "== the two lab profiles agree with each other =="
# They differ only by which collector overlay each takes, never by a challenge control.
f_sel="$(selection full)"; a_sel="$(selection attendee)"
# Reduce each side to a word first: bash cannot compare two conditional expressions directly.
named() { case "$1" in *"$2"*) echo yes ;; *) echo no ;; esac; }
for app in "${CHALLENGE_APPS[@]}"; do
    check "full and attendee treat ${app} the same" \
        '[[ "$(named "$f_sel" "$app")" == "$(named "$a_sel" "$app")" ]]'
done

echo "== admin is the ONE profile that arms them, on purpose =="
# The presenters demonstrate a control already working rather than staging an attack, so selfHeal is not
# a hazard there and the armed state is the point (#294). This is an exception with a reason, which is why
# it is asserted explicitly rather than the checks above being loosened.
sel_admin="$(selection admin)"
check "an admin root exists" '[[ "$sel_admin" != none:* ]]'
for app in "${CHALLENGE_APPS[@]}"; do
    check "admin: ${app} IS deployed (armed by design)" '[[ "$sel_admin" != *"${app}"* ]]'
done
check "admin takes the non-dual collector (it ships to the shared org directly)" \
    '[[ "$sel_admin" == *"otel-collector-attendee"* ]]'

echo "== the community cluster can be WATCHED, even though nothing defends it =="
# Observability is not a guardrail. attackme ships no enforcement at all and must still emit telemetry,
# or the Community phase ends with the room unable to see what it just did (#283, #296, #303).
for app in otel-collector otel-operator ai-layer-otel datadog-operator datadog-agent-cr external-secrets; do
    check "burn ships ${app}" '[[ "$sel_burn" == *"${app}"* ]]'
done
for app in kyverno falco network-policies kubearmor-policies; do
    check "burn still ships NO ${app}" '[[ "$sel_burn" != *"${app}"* ]]'
done

echo "== the controls still EXIST to be applied as the fix =="
# Excluding them from bootstrap must not mean deleting them: the student and the presenter both apply
# them by hand, from the staged manifests, as the fix step.
check "the C1 NetworkPolicies are still in the repo" \
    '[[ -f policies/network-policies/per-namespace/agent-egress-allowlist.yaml ]]'
check "the C3 KubeArmor policy is still in the repo" \
    '[[ -f policies/kubearmor/block-recipe-snoop.yaml ]]'
check "the C1 fix manifest is still staged for the terminal" \
    'grep -q "c1-network-policy.yaml" gitops/ai-layer/resources.yaml'
check "the C3 fix manifest is still staged for the terminal" \
    'grep -q "c3-kubearmor-policy.yaml" gitops/ai-layer/resources.yaml'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
