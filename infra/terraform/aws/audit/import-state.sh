#!/usr/bin/env bash
# ABOUTME: Rebuilds an account's audit-root state (states/<profile>.tfstate) from what stands in AWS, by importing each
# ABOUTME: of the root's resources, then settles it and plans: the way back when the state file is lost (#955).
#
# Why this exists. The states are local files, gitignored under states/ (docs/floor.md), so a state lives only on the
# machine that applied it. Run 17588 (#795) applied this root in accen-dev from a hecaton run's worktree, and that
# worktree was retired with the state in it. Every resource here has a fixed name built from the account id and the
# region, so the state can be rebuilt from AWS alone, on whichever machine is to keep it:
#
#   terraform -chdir=infra/terraform/aws/audit init
#   infra/terraform/aws/audit/import-state.sh <profile>
#
# It refuses a state that already manages anything, so it never overwrites a live state, and it changes nothing in
# AWS: imports only read, the refresh-only apply writes only the state, and the last step is a plan. The plan shows one
# change and only one, `force_destroy` on the bucket, which is a Terraform-only setting AWS cannot read back; the
# targeted apply after it writes that into the state and makes no AWS call that changes anything. It exits 0 when the
# plan after that says no changes, and 1 otherwise, printing the plan.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR

die() { printf 'import-state: %s\n' "$*" >&2; exit 1; }

[[ $# -eq 1 && -n "$1" ]] || die "usage: import-state.sh <profile>   (the fleet account's AWS profile, passed explicitly)"
readonly PROFILE="$1"
readonly REGION="${WIB_AUDIT_REGION:-us-west-2}"
# The event tag, from the same file every root's caller sources (it sets WIB_EVENT without exporting it).
# shellcheck source=SCRIPTDIR/../../fleet/event.sh
. "${SCRIPT_DIR}/../../fleet/event.sh"
[[ -n "${WIB_EVENT:-}" ]] || die "WIB_EVENT is empty after sourcing infra/terraform/fleet/event.sh"
readonly STATE="states/${PROFILE}.tfstate"

tf() { terraform -chdir="${SCRIPT_DIR}" "$@"; }
readonly VARS=(-var "profile=${PROFILE}" -var "event=${WIB_EVENT}" -var "region=${REGION}")

[[ -d "${SCRIPT_DIR}/.terraform" ]] || die "not initialised: run 'terraform -chdir=infra/terraform/aws/audit init' first"
mkdir -p "${SCRIPT_DIR}/states"
if [[ -s "${SCRIPT_DIR}/${STATE}" ]]; then
    listed="$(tf state list -state="${STATE}")" || die "cannot read ${STATE}"
    # Data sources are re-read on every plan and own nothing; a managed resource is what must never be overwritten.
    held="$(grep -v '^data\.' <<<"${listed}" || true)"
    [[ -z "${held}" ]] || die "${STATE} already manages resources; refusing to import over it:
${held}"
fi

account="$(aws sts get-caller-identity --profile "${PROFILE}" --query Account --output text)" ||
    die "cannot read the account of profile ${PROFILE}"
[[ "${account}" =~ ^[0-9]{12}$ ]] || die "profile ${PROFILE} gave account '${account}', not a 12-digit id"

# Names as main.tf builds them: local.name, local.bucket and the role's "${local.name}-config-recorder".
readonly NAME="watch-it-burn"
readonly BUCKET="${NAME}-audit-${account}-${REGION}"
readonly ROLE="${NAME}-config-recorder"

# One line per resource in main.tf, address then import id; verify/test_audit_import_state.py holds this list to
# main.tf's resources one for one.
IMPORTS=(
    "aws_s3_bucket.audit|${BUCKET}"
    "aws_s3_bucket_public_access_block.audit|${BUCKET}"
    "aws_s3_bucket_ownership_controls.audit|${BUCKET}"
    "aws_s3_bucket_server_side_encryption_configuration.audit|${BUCKET}"
    "aws_s3_bucket_lifecycle_configuration.audit|${BUCKET}"
    "aws_s3_bucket_policy.audit|${BUCKET}"
    "aws_iam_role.config|${ROLE}"
    "aws_iam_role_policy_attachment.config|${ROLE}/arn:aws:iam::aws:policy/service-role/AWS_ConfigRole"
    "aws_iam_role_policy.config_delivery|${ROLE}:config-delivery"
    "aws_config_configuration_recorder.fleet|${NAME}"
    "aws_config_delivery_channel.fleet|${NAME}"
    "aws_config_configuration_recorder_status.fleet|${NAME}"
    "aws_cloudtrail.fleet|arn:aws:cloudtrail:${REGION}:${account}:trail/${NAME}"
)

printf 'import-state: rebuilding %s for account %s in %s (%d resources)\n' "${STATE}" "${account}" "${REGION}" "${#IMPORTS[@]}"
for entry in "${IMPORTS[@]}"; do
    addr="${entry%%|*}"
    id="${entry#*|}"
    printf 'import-state: %s <- %s\n' "${addr}" "${id}"
    tf import -input=false -state="${STATE}" "${VARS[@]}" "${addr}" "${id}" >/dev/null ||
        die "import of ${addr} (${id}) failed; ${STATE} holds the imports before it"
done

# The settle step docs/floor.md gives after an apply: it writes what AWS reads back and changes nothing in AWS.
tf apply -input=false -refresh-only -auto-approve -state="${STATE}" "${VARS[@]}" >/dev/null
# force_destroy is Terraform's own flag, never read from AWS, so an import leaves it false. A targeted apply of the
# bucket sets it in the state; S3 has no such setting, so nothing in AWS changes.
tf apply -input=false -auto-approve -target=aws_s3_bucket.audit -state="${STATE}" "${VARS[@]}" >/dev/null

rc=0
plan="$(tf plan -input=false -detailed-exitcode -state="${STATE}" "${VARS[@]}" 2>&1)" || rc=$?
case "${rc}" in
    0) printf 'import-state: %s rebuilt; plan: no changes\n' "${STATE}" ;;
    *) printf '%s\n' "${plan}"; die "${STATE} rebuilt but the plan is not clean (exit ${rc}): read the plan above" ;;
esac
