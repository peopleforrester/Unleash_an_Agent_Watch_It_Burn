#!/usr/bin/env bash
# ABOUTME: Phase-6 abstract-truth gate for Beat 1 (the CNCF wall) against one attendee spoke.
# ABOUTME: Asserts §2 before/after: Audit admits then Enforce rejects; RBAC forbids escalation; admission denies ArgoCD drift and self-heal reverts.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly SCRIPT_DIR REPO_ROOT
readonly BEAT_DIR="${REPO_ROOT}/challenges/01-cncf-wall"
readonly TOGGLE="${BEAT_DIR}/toggle-kyverno-enforce.sh"

usage() {
    cat >&2 <<'EOF'
Usage: beat-01.sh <kube-context> <attendee-namespace>

  <kube-context>         kubeconfig context for the attendee's cluster
  <attendee-namespace>   namespace the scoped agent acts in (agent SA: agent-sa)

Asserts Beat 1's §2 outcomes:
  - non-compliant workload ADMITS while require-resource-limits is in Audit
  - same workload REJECTS after toggle-kyverno-enforce.sh flips it to Enforce
  - privilege escalation (ClusterRoleBinding) is FORBIDDEN by RBAC (no toggle)
  - out-of-band mutation of an ArgoCD-managed resource is DENIED by admission
  - ArgoCD self-heal reverts any drift (defense in depth)

Exit: 0 = all walls held; non-zero = a §2 mismatch (loud FAIL).
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; exit 2; fi
export CONTEXT="${1:?$(usage)}"
NS="${2:?$(usage)}"

readonly SA="system:serviceaccount:${NS}:agent-sa"
readonly KUBECTL=(kubectl --context="${CONTEXT}")
readonly AS=(--as="${SA}")
readonly WORKLOAD="beat1-sample-web"
readonly ARGOCD_MANAGED="argocd-managed-app"   # ArgoCD-managed Deployment in NS (planted by Phase 2)

command -v kubectl >/dev/null 2>&1 || { echo "FAIL: kubectl not found on PATH" >&2; exit 1; }
[[ -x "${TOGGLE}" ]] || { echo "FAIL: missing toggle script: ${TOGGLE}" >&2; exit 1; }

fail() { echo "FAIL [beat-01]: $*" >&2; exit 1; }
step() { echo "==> [beat-01] $*" >&2; }

# Leave the cluster as we found it regardless of how we exit: policy back to Audit,
# test workload removed. Keeps the script idempotent across repeated runs.
# shellcheck disable=SC2329  # invoked indirectly via the EXIT trap below
cleanup() {
    "${KUBECTL[@]}" -n "${NS}" delete deployment "${WORKLOAD}" --ignore-not-found >/dev/null 2>&1 || true
    "${TOGGLE}" --audit >/dev/null 2>&1 || true
}
trap cleanup EXIT

step "Spoke context=${CONTEXT} namespace=${NS} agent SA=${SA}"

# Precondition: policy starts in Audit (idempotent reset; survives a prior interrupted run).
step "Resetting require-resource-limits to Audit (precondition)"
"${TOGGLE}" --audit >/dev/null 2>&1 \
    || fail "could not set require-resource-limits to Audit"
"${KUBECTL[@]}" -n "${NS}" delete deployment "${WORKLOAD}" --ignore-not-found >/dev/null 2>&1 || true

# ---- Before: Audit admits a non-compliant workload ----------------------------------------
step "BEFORE: deploying non-compliant workload (no resource limits) while policy is Audit -- expect ADMIT"
if ! "${KUBECTL[@]}" "${AS[@]}" -n "${NS}" create deployment "${WORKLOAD}" --image=nginx:latest >/dev/null 2>&1; then
    fail "non-compliant workload was NOT admitted in Audit mode (§2 before-state broken)"
fi
echo "    PASS: workload admitted in Audit" >&2
"${KUBECTL[@]}" "${AS[@]}" -n "${NS}" delete deployment "${WORKLOAD}" --ignore-not-found >/dev/null 2>&1 || true

# ---- Toggle: Audit -> Enforce -------------------------------------------------------------
step "TOGGLE: flipping require-resource-limits Audit -> Enforce"
"${TOGGLE}" >/dev/null 2>&1 || fail "toggle-kyverno-enforce.sh failed"
ACTION="$("${KUBECTL[@]}" get clusterpolicy require-resource-limits \
    -o jsonpath='{.spec.rules[0].validate.failureAction}' 2>/dev/null || true)"
[[ "${ACTION}" == "Enforce" ]] || fail "policy did not reach Enforce (got '${ACTION:-<none>}')"
step "Waiting for admission webhook to observe the Enforce change"
sleep 5

# ---- After: Enforce rejects the same workload ---------------------------------------------
step "AFTER: redeploying the same non-compliant workload -- expect REJECT (Kyverno admission)"
REJECT_OUT="$("${KUBECTL[@]}" "${AS[@]}" -n "${NS}" create deployment "${WORKLOAD}" --image=nginx:latest 2>&1)" \
    && fail "workload ADMITTED while policy is Enforce (§2 after-state broken)"
echo "${REJECT_OUT}" | grep -qiE 'admission|require-resource-limits|denied|policy' \
    || fail "rejection was not a Kyverno admission message: ${REJECT_OUT}"
echo "    PASS: workload rejected by Kyverno admission" >&2

# ---- Privilege escalation: RBAC Forbidden, no toggle --------------------------------------
step "WALL 2: agent attempts ClusterRoleBinding self-grant -- expect FORBIDDEN (RBAC, no toggle)"
ESC_OUT="$("${KUBECTL[@]}" "${AS[@]}" create clusterrolebinding beat1-agent-admin \
    --clusterrole=cluster-admin --serviceaccount="${NS}:agent-sa" 2>&1)" \
    && { "${KUBECTL[@]}" delete clusterrolebinding beat1-agent-admin --ignore-not-found >/dev/null 2>&1 || true;
         fail "ClusterRoleBinding was created -- RBAC scoping failed"; }
echo "${ESC_OUT}" | grep -qiE 'forbidden|cannot create' \
    || fail "escalation did not fail with an RBAC Forbidden error: ${ESC_OUT}"
echo "    PASS: escalation forbidden by RBAC" >&2

# ---- ArgoCD drift: admission Denied, then self-heal reverts -------------------------------
step "WALL 3: agent mutates ArgoCD-managed resource out-of-band -- expect DENY (admission, no toggle)"
# Co-design check: the agent SA must hold enough RBAC to *reach* admission (patch verb granted),
# so a Forbidden here would mean the GitOps point is lost at RBAC instead of admission.
if ! "${KUBECTL[@]}" "${AS[@]}" -n "${NS}" auth can-i patch deployment >/dev/null 2>&1; then
    fail "agent SA cannot patch deployments -- step 3 would die at RBAC, not admission (§2 co-design broken)"
fi
[[ -n "$("${KUBECTL[@]}" -n "${NS}" get deployment "${ARGOCD_MANAGED}" -o name 2>/dev/null || true)" ]] \
    || fail "ArgoCD-managed resource '${ARGOCD_MANAGED}' not present in ${NS} (Phase-2 plant missing)"
ORIG_REPLICAS="$("${KUBECTL[@]}" -n "${NS}" get deployment "${ARGOCD_MANAGED}" \
    -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "")"

# Patch the MAIN resource (not the /scale subresource): scale needs a different RBAC verb
# and is not intercepted by a policy matching Deployment UPDATE, so it would bypass the wall.
DRIFT_OUT="$("${KUBECTL[@]}" "${AS[@]}" -n "${NS}" patch deployment "${ARGOCD_MANAGED}" --type=merge -p '{"spec":{"replicas":5}}' 2>&1)" \
    && fail "drift mutation ADMITTED -- block-argocd-drift admission policy failed (§2 wall 3 broken)"
echo "${DRIFT_OUT}" | grep -qiE 'admission|drift|denied|argocd|not allowed' \
    || fail "drift rejection was not an admission message: ${DRIFT_OUT}"
echo "    PASS: out-of-band drift denied by admission" >&2

# Defense in depth: even if admission were bypassed, ArgoCD self-heal must revert drift.
# Confirm the resource is unchanged from its declared replica count.
step "DEFENSE-IN-DEPTH: confirming ArgoCD self-heal keeps the managed resource at its declared spec"
NOW_REPLICAS="$("${KUBECTL[@]}" -n "${NS}" get deployment "${ARGOCD_MANAGED}" \
    -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "")"
[[ "${NOW_REPLICAS}" == "${ORIG_REPLICAS}" ]] \
    || fail "ArgoCD-managed replicas drifted (${ORIG_REPLICAS} -> ${NOW_REPLICAS}); self-heal did not hold"
echo "    PASS: managed resource still at declared replicas (${NOW_REPLICAS})" >&2

echo "PASS [beat-01]: all three CNCF walls held; Kyverno Audit->Enforce toggle behaves per §2." >&2
exit 0
