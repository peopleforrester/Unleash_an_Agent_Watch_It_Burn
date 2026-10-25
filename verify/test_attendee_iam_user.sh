#!/usr/bin/env bash
# ABOUTME: Behavioural test for the attendee IAM user after #549: the cluster root makes the user and its policy,
# ABOUTME: fleet.sh only mints the key, adopts a user made before #549 at the next apply, and never writes a grant.
#
# Why this exists. The per-cluster user's inline policy used to be written by put_user_policy from
# provisioning-agenticburn's generate_attendee_aws.py, which fleet.sh ran on every build, so no check of the IAM
# policy pipeline ever saw it and the user carried no permissions boundary. The user, the policy and the EKS access
# entry are now in the cluster Terraform root. These checks pin what is left to fleet.sh: the key and nothing more,
# the hand-over of users the old generator made, and an aws-keys verb that mints for built clusters only.
#
# Usage: verify/test_attendee_iam_user.sh      (offline; aws and terraform are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
MAIN_TF="${HERE}/../infra/terraform/aws/cluster/main.tf"
T="$(mktemp -d -p "${HERE}/.." .attendee-user-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/tags" "${T}/keys" "${T}/pool" "${T}/states" "${T}/logs"; CALLS="${T}/calls"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# The shim's account. T/tags/<user>.cluster holds a user's cluster tag (no file: no such user), T/keys/<user> that
# the user holds a key, T/describe how describe-cluster answers (live|gone|error), T/policy, T/entry and T/assoc that
# the user's inline policy, access entry and admin association exist.
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "[${AWS_PROFILE:-}] aws $*" >>"${CALLS}"
user=""; prev=""; for a in "$@"; do [[ "${prev}" == "--user-name" ]] && user="${a}"; prev="${a}"; done
case "$*" in
  *"eks describe-cluster"*)
    case "$(cat "${T}/describe")" in
      live) exit 0 ;;
      error) echo "An error occurred (ExpiredTokenException) when calling the DescribeCluster operation" >&2; exit 254 ;;
      *) echo "An error occurred (ResourceNotFoundException) when calling the DescribeCluster operation" >&2; exit 254 ;;
    esac ;;
  *"eks describe-access-entry"*) [[ -f "${T}/entry" ]] || exit 254 ;;
  *"eks list-associated-access-policies"*) [[ -f "${T}/assoc" ]] && echo 1 || echo 0 ;;
  *"iam list-user-tags"*)
    [[ -f "${T}/tags/${user}.cluster" ]] || { echo "An error occurred (NoSuchEntity) when calling the ListUserTags operation" >&2; exit 254; }
    cat "${T}/tags/${user}.cluster" ;;
  *"iam get-user-policy"*) [[ -f "${T}/policy" ]] || exit 254 ;;
  *"iam get-user "*) echo "arn:aws:iam::111122223333:user/${user}" ;;
  *"iam list-access-keys"*"length("*) [[ -f "${T}/keys-fail" ]] && exit 254; [[ -f "${T}/keys/${user}" ]] && echo 1 || echo 0 ;;
  *"iam list-access-keys"*) [[ -f "${T}/keys/${user}" ]] && echo AKIAOLD ;;
  *"iam create-access-key"*) touch "${T}/keys/${user}"; printf 'AKIANEW%s\tSECRET-%s\n' "${user##*-}" "${user}" ;;
  *"iam list-user-policies"*) echo "eks-own-cluster" ;;
  *"iam delete-user "*) rm -f "${T}/tags/${user}".* ;;
  *) : ;;
esac
exit 0
S
# terraform: every call recorded; `state list` answers from T/state-list; an import fails when T/import-fails exists.
cat >"${SHIM}/terraform" <<'S'
#!/usr/bin/env bash
echo "terraform $*" >>"${T}/tf"
case " $* " in
  *" state list "*) cat "${T}/state-list" 2>/dev/null ;;
  *" import "*) [[ -f "${T}/import-fails" ]] && exit 1 ;;
esac
exit 0
S
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"

# shellcheck source=/dev/null
WIB_AWS_POOL_DIR="${T}/pool" WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" source "${FLEET}" >/dev/null 2>&1 || true
set +e
for f in iam_user_for mint_attendee_key adopt_attendee_iam_user bootstrap_student_aws cmd_aws_keys up_one; do
    declare -F "${f}" >/dev/null || { echo "  FAIL  ${f} is not defined in fleet.sh"; exit 1; }
done
record_fail() { echo "RECORD_FAIL $*" >>"${CALLS}"; }
report_failures() { :; }
WIB_REGION="${WIB_REGION:-us-west-2}"

user_of() { printf '%s' "$2" >"${T}/tags/$1.cluster"; }
reset() {
    : >"${CALLS}"; : >"${T}/tf"
    rm -f "${T}"/tags/* "${T}"/keys/* "${T}"/pool/* "${T}"/states/* "${T}/state-list" "${T}/import-fails" \
          "${T}/keys-fail" "${T}/policy" "${T}/entry" "${T}/assoc"
    echo gone >"${T}/describe"
}
C=watch-it-burn-attendee-007; U=wib-attendee-007

echo "== the user's name is the cluster root's =="
check "main.tf names the user by the same rule as iam_user_for" \
    "grep -qF 'attendee_user = substr(\"wib-\${trimprefix(var.name, \"watch-it-burn-\")}\", 0, 64)' '${MAIN_TF}'"
check "attendee cluster -> wib-attendee-007" '[[ "$(iam_user_for "${C}")" == "${U}" ]]'

echo "== mint_attendee_key makes the key and nothing else =="
reset; mint_attendee_key "${C}" acct-x "${T}/one.csv" >"${T}/out" 2>&1; rc=$?
check "a user with no key gets one" '[[ "${rc}" -eq 0 ]] && grep -q "\[acct-x\] aws iam create-access-key --user-name ${U}" "${CALLS}"'
check "the CSV is the header and one row, the pool's shape" \
    '[[ "$(cat "${T}/one.csv")" == "$(printf "name,region,access_key,secret_key\n%s,us-west-2,AKIANEW007,SECRET-%s" "${C}" "${U}")" ]]'
check "the CSV is readable by its owner only" '[[ "$(stat -c %a "${T}/one.csv")" == 600 ]]'
check "the secret is in the file alone, not the output" '! grep -q "SECRET-" "${T}/out"'
check "it writes no policy and makes no user" '! grep -qE "iam (put-user-policy|create-user|attach-user-policy)" "${CALLS}"'
rm -f "${T}/one.csv"; : >"${CALLS}"; mint_attendee_key "${C}" acct-x "${T}/one.csv" >/dev/null 2>&1; rc=$?
check "a user that holds a key gets no second one, and that is not a failure" \
    '[[ "${rc}" -eq 0 ]] && ! grep -q create-access-key "${CALLS}" && [[ ! -s "${T}/one.csv" ]]'
reset; touch "${T}/keys-fail"; mint_attendee_key "${C}" acct-x "${T}/one.csv" >/dev/null 2>&1; rc=$?
check "keys that cannot be read are a failure, not a mint" '[[ "${rc}" -ne 0 ]] && ! grep -q create-access-key "${CALLS}"'

echo "== a user the old generator made is adopted or removed before the apply =="
VARS=(-var "name=${C}" -var "event=e")
adopt() { adopt_attendee_iam_user "${C}" acct-x "${VARS[@]}" >/dev/null 2>&1; }
imports() { grep -c "terraform .* import " "${T}/tf"; }
reset; touch "${T}/states/${C}.tfstate"; echo aws_iam_user.attendee >"${T}/state-list"; adopt; rc=$?
check "a user the state already holds needs nothing" '[[ "${rc}" -eq 0 ]] && [[ ! -s "${CALLS}" ]] && [[ "$(imports)" -eq 0 ]]'
reset; adopt; rc=$?
check "no such user: the apply creates it" '[[ "${rc}" -eq 0 ]] && [[ "$(imports)" -eq 0 ]] && ! grep -q "delete-user " "${CALLS}"'
reset; user_of "${U}" watch-it-burn-attendee-070; adopt; rc=$?
check "a user of that name tagged for another cluster stops the apply" '[[ "${rc}" -ne 0 ]] && ! grep -q "delete-user " "${CALLS}"'
reset; user_of "${U}" "${C}"; adopt; rc=$?
check "a leftover from a cluster that is gone is deleted, not handed on (#458)" \
    '[[ "${rc}" -eq 0 ]] && grep -q "aws iam delete-user --user-name ${U}" "${CALLS}" && [[ "$(imports)" -eq 0 ]]'
reset; user_of "${U}" "${C}"; echo error >"${T}/describe"; adopt; rc=$?
check "a cluster that cannot be read keeps its user and stops the apply" '[[ "${rc}" -ne 0 ]] && ! grep -q "delete-user " "${CALLS}"'
reset; user_of "${U}" "${C}"; echo live >"${T}/describe"; adopt; rc=$?
check "a live cluster with no state here cannot adopt, and stops" '[[ "${rc}" -ne 0 ]] && [[ "$(imports)" -eq 0 ]]'
reset; user_of "${U}" "${C}"; echo live >"${T}/describe"; touch "${T}/states/${C}.tfstate" "${T}/policy" "${T}/entry" "${T}/assoc"; adopt; rc=$?
ARN="arn:aws:iam::111122223333:user/${U}"
check "a live cluster's user is imported, so its student keeps the key" \
    "[[ \"\${rc}\" -eq 0 ]] && grep -q 'import .* aws_iam_user.attendee ${U}\$' '${T}/tf'"
check "with its inline policy" "grep -q 'import .* aws_iam_user_policy.attendee_eks ${U}:eks-own-cluster\$' '${T}/tf'"
check "its access entry" "grep -qF 'aws_eks_access_entry.attendee ${C}:${ARN}' '${T}/tf'"
check "and its admin association" \
    "grep -qF 'aws_eks_access_policy_association.attendee_admin ${C}#${ARN}#arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy' '${T}/tf'"
check "each import into this cluster's state, with the apply's variables" \
    "[[ \"\$(grep -c -- '-state=${T}/states/${C}.tfstate -var name=${C} -var event=e ' '${T}/tf')\" -eq 4 ]]"
check "the user is not deleted" '! grep -q "delete-user " "${CALLS}"'
reset; user_of "${U}" "${C}"; echo live >"${T}/describe"; touch "${T}/states/${C}.tfstate"; adopt
check "only what exists is imported" '[[ "$(imports)" -eq 1 ]]'
reset; user_of "${U}" "${C}"; echo live >"${T}/describe"; touch "${T}/states/${C}.tfstate" "${T}/import-fails"; adopt; rc=$?
check "a failed import stops the apply" '[[ "${rc}" -ne 0 ]]'

echo "== aws-keys mints for built clusters and creates nothing =="
keys() {   # $1: WIB_APPLY value
    WIB_APPLY="$1" WIB_ATTENDEE_ACCOUNTS=acct-x WIB_NAME_OFFSET=0 cmd_aws_keys 3 >/dev/null 2>&1
}
reset; user_of wib-attendee-001 watch-it-burn-attendee-001; user_of wib-attendee-003 watch-it-burn-attendee-003; keys ''
check "dry run mints nothing" '! grep -q create-access-key "${CALLS}" && [[ ! -e "${T}/pool/acct-x.csv" ]]'
keys 1
check "the built clusters' users get keys" \
    'grep -q "create-access-key --user-name wib-attendee-001" "${CALLS}" && grep -q "create-access-key --user-name wib-attendee-003" "${CALLS}"'
check "a name with no user is skipped, not given one" '! grep -q "wib-attendee-002" <(grep -E "create-|put-" "${CALLS}")'
check "nothing here creates a user or writes a policy" '! grep -qE "iam (create-user|put-user-policy|attach-user-policy)|eks create-access-entry" "${CALLS}"'
check "the account CSV is one header and a row per key" \
    '[[ "$(grep -c "^name,region" "${T}/pool/acct-x.csv")" -eq 1 && "$(grep -c "^watch-it-burn-attendee-00[13]," "${T}/pool/acct-x.csv")" -eq 2 ]]'
check "each key is also kept per cluster, where bootstrap and ingest look" '[[ -s "${T}/pool/watch-it-burn-attendee-001.csv" ]]'
user_of wib-attendee-002 watch-it-burn-attendee-002; keys 1
check "a later run appends its new key and keeps the earlier ones" \
    '[[ "$(grep -c "^name,region" "${T}/pool/acct-x.csv")" -eq 1 && "$(grep -c "^watch-it-burn-attendee-" "${T}/pool/acct-x.csv")" -eq 3 ]]'

echo "== the build path =="
body() { awk "/^$1\\(\\) \\{/,/^}/" "${FLEET}"; }
check "bootstrap mints through mint_attendee_key" 'body bootstrap_student_aws | grep -q "mint_attendee_key \"\${name}\""'
check "up_one adopts before it applies" \
    "[[ \$(body up_one | grep -n 'adopt_attendee_iam_user' | head -1 | cut -d: -f1) -lt \$(body up_one | grep -n 'apply -auto-approve' | head -1 | cut -d: -f1) ]]"
check "fleet.sh no longer runs the generator" '! grep -v "^[[:space:]]*#" "${FLEET}" | grep -q "generate_attendee_aws"'

echo; echo "  ${pass} passed, ${fail} failed"; exit $(( fail > 0 ))
