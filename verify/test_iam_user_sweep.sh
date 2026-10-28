#!/usr/bin/env bash
# ABOUTME: Behavioural test for the attendee IAM user teardown (#458): a destroyed cluster's wib-* user and
# ABOUTME: its access keys are deleted, a live or unconfirmed cluster's user is not, and audit-zero names leftovers.
#
# Why this exists. Every cluster has one IAM user with a live access key (made by generate_attendee_aws.py
# until #549, by the cluster root since), and nothing ever deleted one. The fleet accounts are reused event after event, so every key handed to an
# attendee outlived their cluster, and a cluster rebuilt under the same name gives that user cluster admin
# again. audit-zero counted compute and passed. These checks pin what the deletion may and may not touch.
#
# Usage: verify/test_iam_user_sweep.sh      (offline; aws is a shim)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .iam-sweep-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/tags" "${T}/pool"; CALLS="${T}/calls"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# The shim's account: T/tags/<user>.<key> holds a user's tags (no file: no such user), T/live the live
# clusters, T/users the wib-* users, T/describe how describe-cluster answers (live|gone|error).
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
  *"eks list-clusters"*) [[ -f "${T}/list-fails" ]] && exit 254; cat "${T}/live" 2>/dev/null ;;
  *"iam list-users"*) cat "${T}/users" 2>/dev/null ;;
  *"iam list-user-tags"*)
    key=cluster; [[ "$*" == *"Key=='project'"* ]] && key=project
    [[ -f "${T}/tags/${user}.cluster" ]] || { echo "An error occurred (NoSuchEntity) when calling the ListUserTags operation" >&2; exit 254; }
    cat "${T}/tags/${user}.${key}" 2>/dev/null ;;
  *"iam list-access-keys"*) printf 'AKIAONE\tAKIATWO\n' ;;
  *"iam list-user-policies"*) echo "eks-own-cluster" ;;
  *"iam list-attached-user-policies"*) : ;;
  *"iam delete-login-profile"*) exit 254 ;;
  *"iam delete-user "*) [[ -f "${T}/delete-fails" ]] && exit 254; rm -f "${T}/tags/${user}".* ;;
  *) : ;;
esac
exit 0
S
chmod +x "${SHIM}/aws"
export T CALLS PATH="${SHIM}:${PATH}"

# shellcheck source=/dev/null
WIB_AWS_POOL_DIR="${T}/pool" source "${FLEET}" >/dev/null 2>&1 || true
set +e
for f in iam_user_for sweep_attendee_iam_user sweep_orphan_iam_users delete_attendee_iam_user; do
    declare -F "${f}" >/dev/null || { echo "  FAIL  ${f} is not defined in fleet.sh"; exit 1; }
done
log() { :; }; record_fail() { echo "RECORD_FAIL $*" >>"${CALLS}"; }
WIB_REGION="${WIB_REGION:-us-west-2}"

user_of() { mkdir -p "${T}/tags"; printf '%s' "$2" >"${T}/tags/$1.cluster"; printf '%s' "${3:-watch-it-burn}" >"${T}/tags/$1.project"; }
reset() { : >"${CALLS}"; rm -f "${T}"/tags/* "${T}/pool"/* "${T}/live" "${T}/users" "${T}/list-fails" "${T}/delete-fails"; echo gone >"${T}/describe"; }
deletes() { grep -c 'aws iam delete-\(user\|access-key\|user-policy\) ' "${CALLS}"; }

echo "== the user name is the cluster root's (and was the generator's) =="
check "attendee cluster -> wib-attendee-001" '[[ "$(iam_user_for watch-it-burn-attendee-001)" == "wib-attendee-001" ]]'
check "shared admin cluster -> wib-private" '[[ "$(iam_user_for watch-it-burn-private)" == "wib-private" ]]'
check "<owner>-admin cluster -> wib-alpha-admin" '[[ "$(iam_user_for watch-it-burn-alpha-admin)" == "wib-alpha-admin" ]]'

C=watch-it-burn-attendee-007
echo "== a destroyed cluster's user goes, keys first =="
reset; user_of wib-attendee-007 "${C}"; echo 'name,region,access_key,secret_key' >"${T}/pool/${C}.csv"
sweep_attendee_iam_user "${C}" acct-x
check "both access keys are deleted" 'grep -q "delete-access-key --user-name wib-attendee-007 --access-key-id AKIAONE" "${CALLS}" && grep -q "access-key-id AKIATWO" "${CALLS}"'
check "the inline policy is deleted" 'grep -q "delete-user-policy --user-name wib-attendee-007 --policy-name eks-own-cluster" "${CALLS}"'
# shellcheck disable=SC2034  # k and u are read inside the eval'd check below
{ k=$(grep -n 'delete-access-key' "${CALLS}" | head -1 | cut -d: -f1); u=$(grep -n 'iam delete-user ' "${CALLS}" | head -1 | cut -d: -f1); }
check "the user is deleted after its keys" '[[ -n "${u}" && -n "${k}" && "${k}" -lt "${u}" ]]'
check "all of it in the cluster's own account" '! grep "aws iam delete-" "${CALLS}" | grep -qv "^\[acct-x\] "'
check "the persisted copy of the dead key is removed" '[[ ! -f "${T}/pool/${C}.csv" ]]'
check "and nothing is recorded as a failure" '! grep -q RECORD_FAIL "${CALLS}"'

echo "== it never touches a user it cannot prove is orphaned =="
reset; user_of wib-attendee-007 "${C}"; echo live >"${T}/describe"; sweep_attendee_iam_user "${C}" acct-x
check "a live cluster keeps its user" '[[ "$(deletes)" -eq 0 ]]'
reset; user_of wib-attendee-007 "${C}"; echo error >"${T}/describe"; sweep_attendee_iam_user "${C}" acct-x
check "an unreadable cluster keeps its user, and that is recorded" '[[ "$(deletes)" -eq 0 ]] && grep -q "RECORD_FAIL iam-user-leak:${C}" "${CALLS}"'
reset; user_of wib-attendee-007 watch-it-burn-attendee-070; sweep_attendee_iam_user "${C}" acct-x
check "a user tagged for another cluster is left alone" '[[ "$(deletes)" -eq 0 ]] && ! grep -q RECORD_FAIL "${CALLS}"'
reset; sweep_attendee_iam_user "${C}" acct-x
check "no such user is a clean answer" '[[ "$(deletes)" -eq 0 ]] && ! grep -q RECORD_FAIL "${CALLS}"'
reset; user_of wib-attendee-007 "${C}"; touch "${T}/delete-fails"; echo x >"${T}/pool/${C}.csv"; sweep_attendee_iam_user "${C}" acct-x
check "a failed delete is recorded and the key file kept" 'grep -q "RECORD_FAIL iam-user-leak:${C}" "${CALLS}" && [[ -f "${T}/pool/${C}.csv" ]]'

echo "== the account-wide sweep takes only our orphans =="
orphans() {
    reset
    user_of wib-attendee-001 watch-it-burn-attendee-001
    user_of wib-attendee-002 watch-it-burn-attendee-002
    user_of wib-someone-else watch-it-burn-attendee-003 other-project
    printf 'wib-attendee-001\twib-attendee-002\twib-someone-else\twib-untagged\n' >"${T}/users"
    printf 'watch-it-burn-attendee-002\n' >"${T}/live"
}
orphans; WIB_APPLY='' sweep_orphan_iam_users acct-x
check "dry run deletes nothing" '[[ "$(deletes)" -eq 0 ]]'
orphans; WIB_APPLY=1 sweep_orphan_iam_users acct-x
check "the user of a gone cluster is deleted" 'grep -q "iam delete-user --user-name wib-attendee-001" "${CALLS}"'
check "a live cluster's user is kept" '! grep -q "delete-user --user-name wib-attendee-002" "${CALLS}"'
check "another project's and an untagged user are kept" '! grep -q "delete-user --user-name wib-someone-else" "${CALLS}" && ! grep -q "delete-user --user-name wib-untagged" "${CALLS}"'
orphans; touch "${T}/list-fails"; WIB_APPLY=1 sweep_orphan_iam_users acct-x
check "an unread live list deletes nothing and is recorded" '[[ "$(deletes)" -eq 0 ]] && grep -q "RECORD_FAIL iam-users:list-clusters-failed:acct-x" "${CALLS}"'

echo "== it is wired into the teardown and the audit =="
check "down_one deletes the destroyed cluster's user" "awk '/^down_one\\(\\)/,/^}/' '${FLEET}' | grep -q 'sweep_attendee_iam_user \"\${name}\"'"
check "down all sweeps orphans before its audit" "awk '/if \\[\\[ \"\\\$\\{1:-\\}\" == \"all\" \\]\\]; then/,/^    fi\$/' '${FLEET}' | grep -q 'sweep_orphan_iam_users'"
check "reap-iam-users is a subcommand" "grep -q 'reap-iam-users) cmd_reap_iam_users' '${FLEET}'"
check "audit-zero names leftover IAM users" "grep -q 'zero:\${acct}:iam-users' '${FLEET}'"

echo; echo "  ${pass} passed, ${fail} failed"; exit $(( fail > 0 ))
