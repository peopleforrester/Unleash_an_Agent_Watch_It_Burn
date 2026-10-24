#!/usr/bin/env bash
# ABOUTME: Behavioural tests for #526: preflight checks each account's permissions boundary and names the lab-VPC
# ABOUTME: state fleet.sh actually uses (terraform.tfstate for WIB_DEFAULT_ACCOUNT). Offline: aws and terraform are shims.
#
# Why this exists. At the KubeCon bring-up on 2026-10-24 both roster clusters in accen-dev failed at plan with
# "no matching IAM Policy found": infra/org/boundary had never been applied there, and preflight never looked.
# In the same step, preflight's lab-VPC hint for accen-dev said -state=states/accen-dev.tfstate while fleet.sh's
# lab_vpc_state_for (and so down-infra) uses the default terraform.tfstate; following it builds a VPC state that
# teardown never destroys.
#
# preflight.sh runs from a copy of the tree under a temp dir, so no real state file on this machine can make a
# case pass or fail.
#
# Usage: verify/test_preflight_boundary.sh      (no cloud access)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${HERE}/../infra/terraform/fleet"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
FLEET_DIR="${T}/infra/terraform/fleet"; NET="${T}/infra/terraform/aws/network"; BOUNDARY="${T}/infra/org/boundary"
SHIM="${T}/bin"; CALLS="${T}/calls"
mkdir -p "${FLEET_DIR}" "${NET}/states" "${BOUNDARY}" "${SHIM}"
cp "${SRC}/preflight.sh" "${SRC}/event.sh" "${FLEET_DIR}/"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# aws: each profile resolves to its pinned id; quotas are ample; the VPC is live. iam get-policy answers per
# BOUNDARY_<profile with - as _>: unset is present, "missing" is NoSuchEntity, "denied" is AccessDenied.
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $* [AWS_PROFILE=${AWS_PROFILE:-}]" >>"${CALLS}"
case "$1 $2" in
  "sts get-caller-identity")
    case "${AWS_PROFILE}" in accen-dev) echo 515966504359 ;; aws1-student31) echo 948731545609 ;; *) exit 255 ;; esac ;;
  "service-quotas get-service-quota") echo 1000.0 ;;
  "iam get-policy")
    var="BOUNDARY_${AWS_PROFILE//-/_}"
    case "${!var:-}" in
      missing) echo "An error occurred (NoSuchEntity) when calling the GetPolicy operation: Policy not found." >&2; exit 254 ;;
      denied)  echo "An error occurred (AccessDenied) when calling the GetPolicy operation: not authorized." >&2; exit 254 ;;
      *) echo watch-it-burn-permissions-boundary ;;
    esac ;;
  "ec2 describe-vpcs") echo vpc-0abc ;;
esac
exit 0
S
# terraform output: a state file holding "vpc" yields vpc-0abc; an empty one yields nothing, as a destroyed state does.
cat >"${SHIM}/terraform" <<'S'
#!/usr/bin/env bash
echo "terraform $*" >>"${CALLS}"
state=""; for a in "$@"; do [[ "${a}" == -state=* ]] && state="${a#-state=}"; done
[[ "$*" == *"output"* ]] && grep -q vpc "${state}" 2>/dev/null && printf 'vpc-0abc'
exit 0
S
for t in kubectl jq curl helm; do printf '#!/usr/bin/env bash\nexit 0\n' >"${SHIM}/${t}"; done
chmod +x "${SHIM}"/*
export CALLS PATH="${SHIM}:${PATH}"

OUT="${T}/out"
# run <accounts> [VAR=value ...]: preflight for 1 cluster per account; stdout+stderr in ${OUT}, exit in ${rc}.
run() {
  local accts="$1"; shift
  : >"${CALLS}"
  env -u WIB_DEFAULT_ACCOUNT -u WIB_EVENT WIB_ATTENDEE_ACCOUNTS="${accts}" WIB_REGION=us-west-2 "$@" \
    bash "${FLEET_DIR}/preflight.sh" 1 >"${OUT}" 2>&1
  rc=$?
}
has() { grep -qF -- "$1" "${OUT}"; }
fail_line() { grep -F 'FAIL' "${OUT}" | grep -F -- "$1"; }
reset_states() { rm -f "${NET}/terraform.tfstate" "${NET}"/states/*; }

BAPPLY_DEV="terraform -chdir=${FLEET_DIR}/../../org/boundary init && terraform -chdir=${FLEET_DIR}/../../org/boundary apply -state=states/accen-dev.tfstate -var profile=accen-dev -var region=us-west-2"

echo "== everything in place: GREEN, and the boundary is checked by ARN in the account =="
reset_states; echo vpc >"${NET}/terraform.tfstate"
run accen-dev
check "exit 0"                                 '[[ "${rc}" -eq 0 ]]'
check "PREFLIGHT GREEN"                        'has "PREFLIGHT GREEN"'
check "PASS line for the boundary"             'grep -F PASS "${OUT}" | grep -qF "permissions boundary watch-it-burn-permissions-boundary present"'
check "get-policy asks for the boundary ARN in the resolved account, as that profile" \
      'grep -qF "aws iam get-policy --policy-arn arn:aws:iam::515966504359:policy/watch-it-burn-permissions-boundary" "${CALLS}" && grep -F "iam get-policy" "${CALLS}" | grep -qF "[AWS_PROFILE=accen-dev]"'

echo "== a missing boundary is a FAIL that prints the infra/org/boundary apply line for that account =="
reset_states; echo vpc >"${NET}/terraform.tfstate"
run accen-dev BOUNDARY_accen_dev=missing
check "exit 1"                                 '[[ "${rc}" -eq 1 ]]'
check "PREFLIGHT FAILED"                       'has "PREFLIGHT FAILED"'
check "FAIL names the boundary as MISSING"     'fail_line "watch-it-burn-permissions-boundary MISSING in accen-dev" >/dev/null'
check "and carries the apply line, with the account's own boundary state" \
      'fail_line "${BAPPLY_DEV}" >/dev/null'

echo "== per account: only the account without the boundary fails, and its line names that account =="
reset_states; echo vpc >"${NET}/terraform.tfstate"; echo vpc >"${NET}/states/aws1-student31.tfstate"
run accen-dev,aws1-student31 BOUNDARY_aws1_student31=missing
check "exit 1"                                 '[[ "${rc}" -eq 1 ]]'
check "accen-dev's boundary passes"            'grep -F PASS "${OUT}" | grep -qF "permissions boundary"'
check "aws1-student31's apply line names its profile and state" \
      'fail_line "apply -state=states/aws1-student31.tfstate -var profile=aws1-student31 -var region=us-west-2" | grep -qF "org/boundary"'
check "get-policy ran in both accounts"        '[[ "$(grep -c "iam get-policy" "${CALLS}")" -eq 2 ]]'

echo "== a boundary that cannot be read is a FAIL too, not a pass =="
reset_states; echo vpc >"${NET}/terraform.tfstate"
run accen-dev BOUNDARY_accen_dev=denied
check "exit 1"                                 '[[ "${rc}" -eq 1 ]]'
check "FAIL says it could not be read, with the reason" 'fail_line "could not be read in accen-dev" | grep -qF "AccessDenied"'
check "and still prints the apply line"        'fail_line "${BAPPLY_DEV}" >/dev/null'

echo "== the default account's lab-VPC line names terraform.tfstate, the state lab_vpc_state_for uses =="
reset_states
run accen-dev
check "exit 1 with no lab VPC state"           '[[ "${rc}" -eq 1 ]]'
check "FAIL line names -state=terraform.tfstate" \
      'fail_line "no lab VPC state" | grep -qF "terraform -chdir=${FLEET_DIR}/../aws/network apply -state=terraform.tfstate -var profile=accen-dev -var region=us-west-2 -var event=kubecon-na-2026"'
check "and not states/accen-dev.tfstate"       '! fail_line "no lab VPC state" | grep -qF "states/accen-dev.tfstate"'
reset_states; : >"${NET}/terraform.tfstate"
run accen-dev
check "an EMPTY default state's line names terraform.tfstate" \
      'fail_line "lab VPC state is EMPTY" | grep -qF "apply -state=terraform.tfstate -var profile=accen-dev"'
check "and the output was read from terraform.tfstate" 'grep -qF "output -state=${FLEET_DIR}/../aws/network/terraform.tfstate -raw vpc_id" "${CALLS}"'

echo "== WIB_DEFAULT_ACCOUNT moves the default state with it =="
reset_states
run aws1-student31 WIB_DEFAULT_ACCOUNT=aws1-student31
check "the overridden default account's line names terraform.tfstate" \
      'fail_line "no lab VPC state" | grep -qF "apply -state=terraform.tfstate -var profile=aws1-student31"'

echo "== every other account keeps its own states/<acct>.tfstate =="
reset_states; echo vpc >"${NET}/terraform.tfstate"
run accen-dev,aws1-student31
check "aws1-student31's line names states/aws1-student31.tfstate" \
      'fail_line "no lab VPC state" | grep -qF "apply -state=states/aws1-student31.tfstate -var profile=aws1-student31"'
check "accen-dev's VPC passes from the default state" 'grep -F PASS "${OUT}" | grep -qF "lab VPC vpc-0abc present and live"'

echo "== a stray states/<default>.tfstate is called out (down-infra never destroys it) =="
reset_states; echo vpc >"${NET}/terraform.tfstate"; echo vpc >"${NET}/states/accen-dev.tfstate"
run accen-dev
check "note names the stray state"             'grep -F note "${OUT}" | grep -qF "stray ${FLEET_DIR}/../aws/network/states/accen-dev.tfstate"'

echo "== the Night Before list applies the boundary before the platform comes up =="
ROS="${HERE}/../facilitation/kubecon-na-2026-run-of-show.md"
night="$(awk '/^## Night Before/{on=1; next} /^## /{on=0} on' "${ROS}")"
b_line="$(grep -n 'org/boundary apply' <<<"${night}" | head -1 | cut -d: -f1)"
up_line="$(grep -n 'Platform up on AWS' <<<"${night}" | head -1 | cut -d: -f1)"
check "the Night Before list has the infra/org/boundary apply" '[[ -n "${b_line}" ]]'
check "before \"Platform up on AWS\""                          '[[ -n "${b_line}" && -n "${up_line}" && "${b_line}" -lt "${up_line}" ]]'

echo
if [ "${fail}" -gt 0 ]; then echo "FAILED: ${fail} check(s), ${pass} passed"; exit 1; fi
echo "All preflight boundary checks passed (${pass})."
