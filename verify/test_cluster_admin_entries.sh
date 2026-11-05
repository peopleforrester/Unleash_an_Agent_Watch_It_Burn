#!/usr/bin/env bash
# ABOUTME: Offline test for #884: the cluster root names its cluster admins (nwuser, and the hecaton-run role in
# ABOUTME: accen-dev) instead of taking whoever runs terraform, and fleet.sh adopts the role's pre-made entry.
#
# Why this exists. The EKS module's enable_cluster_creator_admin_permissions made the caller of terraform a cluster
# admin and the cluster KMS key's administrator. Since hecaton#519 a run's accen-dev profile is the role hecaton-run,
# so a run's apply planned to replace the operator nwuser's entry with the role's. The root now names both, moves
# nwuser's entry from the module's old "cluster_creator" key so it is not re-created, and fleet.sh imports the role's
# entry that hecaton made by hand on the two roster clusters. These checks pin the root's text and fleet.sh's adoption.
# That the pinned module keys its resources the way the moved blocks and imports assume, and that the locals give
# these principals per account, is verify/test_cluster_admin_entries_module.py (E2E tools tier).
#
# Usage: verify/test_cluster_admin_entries.sh      (offline; aws and terraform are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
MAIN_TF="${HERE}/../infra/terraform/aws/cluster/main.tf"
T="$(mktemp -d -p "${HERE}/.." .cluster-admins-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/states" "${T}/logs" "${T}/pool"; CALLS="${T}/calls"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${HERE}/no-cloud.sh"; no_cloud_guard "${T}/no-cloud"

# Each anchor this test cuts main.tf on is checked first, so a reworded anchor reads as that.
for a in 'module "eks" {' '  account_id ' 'cluster_admin_entries = {' 'variable "operator_user" {'; do
    grep -qF -- "${a}" "${MAIN_TF}" || { echo "  FAIL  anchor missing: '${a}' is not in ${MAIN_TF}"; exit 1; }
done
# The text of a top-level block: from the line that opens it to the first line that is exactly "}".
block() { awk -v a="$1" 'index($0, a) == 1 { on = 1 } on { print } on && /^}$/ { exit }' "${MAIN_TF}"; }
EKS="$(block 'module "eks" {')"
ADMINS="$(awk '/^locals \{$/ { buf = ""; on = 1 } on { buf = buf $0 "\n" } on && /^}$/ { on = 0; if (buf ~ /\n  account_id /) printf "%s", buf }' "${MAIN_TF}")"
[[ -n "${ADMINS}" ]] || { echo "  FAIL  anchor missing: no locals block with account_id in ${MAIN_TF}"; exit 1; }

echo "== the root names its admins, not the caller =="
check "module eks no longer maps whoever runs terraform into a cluster-admin entry" \
    'grep -qE "^  enable_cluster_creator_admin_permissions += false$" <<<"${EKS}"'
check "its access entries are the named list" 'grep -qE "^  access_entries += local\.cluster_admin_entries$" <<<"${EKS}"'
check "the cluster KMS key's administrator is the operator, not the caller" \
    'grep -qE "^  kms_key_administrators += \[local\.operator_arn\]$" <<<"${EKS}"'
check "the operator is nwuser by default" \
    "awk '/^variable \"operator_user\" \\{/,/^}/' '${MAIN_TF}' | grep -qE '^  default += \"nwuser\"$'"
check "the operator is a user in the cluster's own account" \
    'grep -qF "operator_arn = \"arn:aws:iam::\${local.account_id}:user/\${var.operator_user}\"" <<<"${ADMINS}"'
check "the run role is named only in accen-dev (515966504359), where hecaton made it" \
    'grep -qE "^  run_role_accounts += \[\"515966504359\"\]$" <<<"${ADMINS}"'
check "and only when the plan's account is one of those" \
    'grep -qF "\"hecaton_run\" => \"arn:aws:iam::\${a}:role/\${local.run_role_name}\" if a == local.account_id" <<<"${ADMINS}"'
check "the operator's key is operator" 'grep -qF "{ operator = local.operator_arn }" <<<"${ADMINS}"'
check "each admin gets AmazonEKSClusterAdminPolicy" \
    'grep -qF "policy_arn   = \"arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy\"" <<<"${ADMINS}"'
check "at cluster scope" 'grep -qF "access_scope = { type = \"cluster\" }" <<<"${ADMINS}"'
check "under the policy key admin (the association address is <entry>_admin)" 'grep -qE "^      admin = \{$" <<<"${ADMINS}"'

echo "== nwuser's existing entry is moved, not replaced =="
moved_ok() {   # $1 from, $2 to
    awk '/^moved \{$/,/^}$/' "${MAIN_TF}" | tr -d ' ' | tr '\n' ' ' \
        | grep -qF "moved{ from=$1 to=$2 }"
}
check "the entry moves from cluster_creator to operator" \
    "moved_ok 'module.eks.aws_eks_access_entry.this[\"cluster_creator\"]' 'module.eks.aws_eks_access_entry.this[\"operator\"]'"
check "its admin association moves from cluster_creator_admin to operator_admin" \
    "moved_ok 'module.eks.aws_eks_access_policy_association.this[\"cluster_creator_admin\"]' 'module.eks.aws_eks_access_policy_association.this[\"operator_admin\"]'"

echo "== fleet.sh and the root name the same role =="
check "fleet.sh's RUN_ROLE_NAME is main.tf's run_role_name" \
    "[[ \"\$(sed -n 's/^readonly RUN_ROLE_NAME=\"\\([^\"]*\\)\".*/\\1/p' '${FLEET}')\" == \"\$(sed -n 's/^  run_role_name *= \"\\([^\"]*\\)\"$/\\1/p' '${MAIN_TF}')\" ]]"
check "and that name is hecaton-run" "grep -qE '^  run_role_name += \"hecaton-run\"$' '${MAIN_TF}'"

# The shims. aws: T/entries is what list-access-entries prints (no file: the cluster is gone; T/list-error: an expired
# session), T/assoc that the role holds the admin association. terraform: `state list` prints T/state-list, an
# import fails when T/import-fails exists.
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "[${AWS_PROFILE:-}] aws $*" >>"${CALLS}"
case "$*" in
  *"eks list-access-entries"*)
    [[ -f "${T}/list-error" ]] && { echo "An error occurred (ExpiredTokenException) when calling the ListAccessEntries operation" >&2; exit 254; }
    [[ -f "${T}/entries" ]] || { echo "An error occurred (ResourceNotFoundException) when calling the ListAccessEntries operation: No cluster found" >&2; exit 254; }
    cat "${T}/entries" ;;
  *"eks list-associated-access-policies"*) [[ -f "${T}/assoc" ]] && echo 1 || echo 0 ;;
esac
exit 0
S
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
for f in adopt_run_role_access_entry up_one; do
    declare -F "${f}" >/dev/null || { echo "  FAIL  ${f} is not defined in fleet.sh"; exit 1; }
done
WIB_REGION="${WIB_REGION:-us-west-2}"

C=watch-it-burn-private; ROLE="arn:aws:iam::515966504359:role/hecaton-run"
ADMIN="arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
ENTRY='module.eks.aws_eks_access_entry.this["hecaton_run"]'
ASSOC='module.eks.aws_eks_access_policy_association.this["hecaton_run_admin"]'
VARS=(-var "name=${C}" -var "event=e")
reset() {
    : >"${CALLS}"; : >"${T}/tf"
    rm -f "${T}"/states/* "${T}/state-list" "${T}/import-fails" "${T}/list-error" "${T}/entries" "${T}/assoc"
}
adopt() { adopt_run_role_access_entry "${C}" acct-x "${VARS[@]}" >/dev/null 2>&1; }
imports() { grep -c "terraform .* import " "${T}/tf"; }
live_role() {   # the cluster holds the role's entry; its state does not
    touch "${T}/states/${C}.tfstate"
    printf '%s\n' 'module.eks.aws_eks_access_entry.this["operator"]' >"${T}/state-list"
    echo "${ROLE}" >"${T}/entries"
}

echo "== the role's entry made by hecaton is adopted before the apply =="
reset; adopt; rc=$?
check "no state here (a fresh build): nothing is asked and the apply creates the entry" \
    '[[ "${rc}" -eq 0 ]] && [[ ! -s "${CALLS}" ]] && [[ "$(imports)" -eq 0 ]]'
reset; live_role; printf '%s\n%s\n' "${ENTRY}" "${ASSOC}" >"${T}/state-list"; adopt; rc=$?
check "a state that holds the entry needs nothing, and AWS is not asked" \
    '[[ "${rc}" -eq 0 ]] && [[ ! -s "${CALLS}" ]] && [[ "$(imports)" -eq 0 ]]'
reset; live_role; touch "${T}/assoc"; adopt; rc=$?
check "an entry on the cluster that the state lacks is imported by its principal" \
    "[[ \"\${rc}\" -eq 0 ]] && grep -qF -- '${ENTRY} ${C}:${ROLE}' '${T}/tf'"
check "with its admin association" "grep -qF -- '${ASSOC} ${C}#${ROLE}#${ADMIN}' '${T}/tf'"
check "each import into this cluster's state, with the apply's variables" \
    "[[ \"\$(grep -c -- 'import -no-color -input=false -state=${T}/states/${C}.tfstate -var name=${C} -var event=e ' '${T}/tf')\" -eq 2 ]]"
check "the entry is looked up by the role's name, in the cluster's account and region" \
    "grep -qF \"[acct-x] aws eks list-access-entries --cluster-name ${C} --region ${WIB_REGION} --query accessEntries[?ends_with(@, ':role/hecaton-run')] | [0] --output text\" '${CALLS}'"
check "nothing here creates or deletes an access entry" '! grep -qE "eks (create|delete)-access-entry|(associate|disassociate)-access-policy" "${CALLS}"'
reset; live_role; adopt
check "an entry with no admin association: only the entry is imported, the apply associates it" \
    '[[ "$(imports)" -eq 1 ]] && grep -qF -- "${ENTRY} " "${T}/tf"'
reset; live_role; printf '%s\n' "${ASSOC}" >>"${T}/state-list"; touch "${T}/assoc"; adopt
check "an association the state already holds is not imported again" '[[ "$(imports)" -eq 1 ]] && ! grep -qF -- "${ASSOC} " "${T}/tf"'
reset; live_role; echo None >"${T}/entries"; adopt; rc=$?
check "a cluster with no entry for the role (another account): nothing is imported" '[[ "${rc}" -eq 0 ]] && [[ "$(imports)" -eq 0 ]]'
reset; live_role; rm -f "${T}/entries"; adopt; rc=$?
check "a cluster that is gone: the apply builds it again, nothing is imported" '[[ "${rc}" -eq 0 ]] && [[ "$(imports)" -eq 0 ]]'
reset; live_role; touch "${T}/list-error"; adopt; rc=$?
check "entries that cannot be read stop the apply" '[[ "${rc}" -ne 0 ]] && [[ "$(imports)" -eq 0 ]]'
reset; live_role; touch "${T}/import-fails"; adopt; rc=$?
check "a failed import stops the apply" '[[ "${rc}" -ne 0 ]]'

echo "== the build path =="
body() { awk "/^$1\\(\\) \\{/,/^}/" "${FLEET}"; }
check "up_one adopts the role's entry before it applies" \
    "[[ \$(body up_one | grep -n 'adopt_run_role_access_entry' | head -1 | cut -d: -f1) -lt \$(body up_one | grep -n 'apply -auto-approve' | head -1 | cut -d: -f1) ]]"
check "and passes it the apply's variables" \
    'body up_one | grep -qF "adopt_run_role_access_entry \"\${name}\" \"\${TF_PROFILE:-\${WIB_DEFAULT_ACCOUNT}}\" -var \"event=\${WIB_EVENT}\" \"\${tfvars[@]}\""'

echo "== offline means offline =="
check "no check above called aws, kubectl, eksctl, terraform or helm" 'no_cloud_clean'

echo; echo "  ${pass} passed, ${fail} failed"; exit $(( fail > 0 ))
