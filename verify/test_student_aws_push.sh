#!/usr/bin/env bash
# ABOUTME: Behavioural test for #584: fleet.sh pushes the attendee's key into student-creds, never agent, deletes
# ABOUTME: a copy an older bootstrap left in agent, and restarts the terminal in agent so it reads the key.
#
# Why this exists. The key holds EKS cluster-admin on its cluster (aws_eks_access_policy_association.attendee_admin
# in infra/terraform/aws/cluster/main.tf). In namespace agent, the agent's broad Role (the state Challenge 8 starts
# in) could read it, and run_shell could presign an EKS token from it and act as cluster-admin, an identity
# restrict-agent-spawned-workloads does not match. These checks pin the push to student-creds, the clean-up of the
# old copy, and the terminal restart, which the provisioning repo's push script cannot do once it is pointed at a
# namespace with no terminal in it.
#
# Usage: verify/test_student_aws_push.sh      (offline; kubectl and the push script are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .student-aws-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/prov/scripts" "${T}/pool" "${T}/states" "${T}/logs"; CALLS="${T}/calls"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# kubectl: every call recorded. `config current-context` answers from T/ctx (no file: no context).
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $*" >>"${CALLS}"
case "$*" in
  "config current-context") [[ -f "${T}/ctx" ]] && cat "${T}/ctx" || exit 1 ;;
esac
exit 0
S
# The provisioning repo's push_vtt_aws_creds.sh: records its arguments, fails when T/push-fails exists.
cat >"${T}/prov/scripts/push_vtt_aws_creds.sh" <<'S'
echo "push $*" >>"${CALLS}"
[[ -f "${T}/push-fails" ]] && exit 1
exit 0
S
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"

# shellcheck source=/dev/null
WIB_PROVISION_DIR="${T}/prov" WIB_AWS_POOL_DIR="${T}/pool" WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" \
    source "${FLEET}" >/dev/null 2>&1 || true
set +e
for f in push_student_aws bootstrap_student_aws; do
    declare -F "${f}" >/dev/null || { echo "  FAIL  ${f} is not defined in fleet.sh"; exit 1; }
done
WIB_REGION="${WIB_REGION:-us-west-2}"
C=watch-it-burn-attendee-007; CTX="arn:aws:eks:us-west-2:111122223333:cluster/${C}"
reset() { : >"${CALLS}"; rm -f "${T}/push-fails" "${T}/ctx"; echo "${CTX}" >"${T}/ctx"; }
push() { push_student_aws "${C}" acct-x "${T}/kcfg" AKIATEST SECRETTEST >/dev/null 2>&1; }

echo "== the key goes to student-creds, not agent =="
check "fleet.sh names student-creds as the key's namespace" '[[ "${STUDENT_AWS_NS}" == student-creds ]]'
reset; push; rc=$?
check "a push succeeds" '[[ "${rc}" -eq 0 ]]'
check "it waits for the student-creds namespace" "grep -qF 'kubectl --context ${CTX} get ns student-creds' '${CALLS}'"
check "the push script is told the student-creds namespace" \
    "grep -E '^push ' '${CALLS}' | grep -qF -- '--namespace student-creds'"
check "and the cluster's context, key and region" \
    "grep -E '^push ' '${CALLS}' | grep -qF -- '--context ${CTX} --access-key AKIATEST --secret-key SECRETTEST --region ${WIB_REGION}'"
check "nothing is pushed or created in agent" "! grep -E '^push ' '${CALLS}' | grep -qF -- '--namespace agent'"

echo "== the old copy in agent is removed, and the terminal re-reads the key =="
check "a student-aws-creds left in agent is deleted" \
    "grep -qF 'kubectl --context ${CTX} -n agent delete secret student-aws-creds --ignore-not-found' '${CALLS}'"
check "the delete comes before the push, so a failed push still leaves no key in agent" \
    '[[ "$(grep -n "delete secret" "${CALLS}" | cut -d: -f1)" -lt "$(grep -nE "^push " "${CALLS}" | cut -d: -f1)" ]]'
check "the terminal pod in agent is restarted by pod delete, not rollout" \
    "grep -qF 'kubectl --context ${CTX} -n agent delete pod -l app.kubernetes.io/name=web-terminal' '${CALLS}' && ! grep -q 'rollout' '${CALLS}'"
check "every kubectl call but the context lookup names the context" \
    "! grep -E '^kubectl ' '${CALLS}' | grep -v '^kubectl config current-context\$' | grep -vqF -- '--context ${CTX}'"

echo "== a failure is reported, not hidden =="
reset; touch "${T}/push-fails"; push; rc=$?
check "a failed push returns non-zero" '[[ "${rc}" -ne 0 ]]'
check "and restarts nothing" "! grep -q 'delete pod' '${CALLS}'"
check "but the copy in agent is still deleted" "grep -qF -- '-n agent delete secret student-aws-creds' '${CALLS}'"
reset; rm -f "${T}/ctx"; push; rc=$?
check "no context in the kubeconfig: non-zero, and nothing is pushed" '[[ "${rc}" -ne 0 ]] && ! grep -qE "^push " "${CALLS}"'

echo "== both bootstrap paths go through the helper =="
body() { declare -f "$1"; }
check "a fresh key and the pool-CSV re-push both call push_student_aws" \
    '[[ "$(body bootstrap_student_aws | grep -c push_student_aws)" -eq 2 ]]'
check "bootstrap no longer calls the push script itself" '! body bootstrap_student_aws | grep -q PUSH_VTT_SCRIPT'

echo
echo "  ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
