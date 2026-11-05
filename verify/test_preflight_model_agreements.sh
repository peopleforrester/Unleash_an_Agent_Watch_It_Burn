#!/usr/bin/env bash
# ABOUTME: Behavioural tests for #882: preflight checks, in every account, that each Bedrock model the cluster root binds
# ABOUTME: (bedrock_tiers and the tutor_model default) reports agreementAvailability AVAILABLE. Offline: aws is a shim.
#
# Why this exists. On 2026-11-05 a pod running as the tutor's ServiceAccount passed IAM for its own tutor profile on
# both clusters, and Bedrock then refused nearly every call: "not authorized to perform the required AWS Marketplace
# actions". The tutor's model, anthropic.claude-sonnet-5, had no Marketplace agreement in accen-dev, and nothing
# before a bring-up looked. preflight.sh now asks get-foundation-model-availability for every bound model, per account,
# and fails any that is not AVAILABLE with the commands that accept it. It never runs them: accepting is a
# subscription on the account owner's behalf.
#
# preflight.sh runs from a copy of the tree under a temp dir, with a cluster root this test writes, so the model list
# is the test's own. One section reads the real cluster root, and checks its anchors first.
#
# Usage: verify/test_preflight_model_agreements.sh      (no cloud access)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${HERE}/../infra/terraform/fleet"
REAL_TF="${HERE}/../infra/terraform/aws/cluster/main.tf"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
FLEET_DIR="${T}/infra/terraform/fleet"; NET="${T}/infra/terraform/aws/network"; CLUSTER="${T}/infra/terraform/aws/cluster"
SHIM="${T}/bin"; CALLS="${T}/calls"
mkdir -p "${FLEET_DIR}" "${NET}/states" "${CLUSTER}" "${SHIM}"
cp "${SRC}/preflight.sh" "${SRC}/event.sh" "${FLEET_DIR}/"
echo vpc >"${NET}/terraform.tfstate"; echo vpc >"${NET}/states/aws1-student31.tfstate"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# A cluster root shaped like the real one: four tiers, and a tutor on a model of its own.
write_tf() {
  cat >"${CLUSTER}/main.tf" <<EOF
locals {
  bedrock_tiers = {
    nova   = "us.amazon.nova-pro-v1:0"
    haiku  = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    sonnet = "us.anthropic.claude-sonnet-4-6"
    opus   = "us.anthropic.claude-opus-4-8"
  }
  bedrock_profiles = values(local.bedrock_tiers)
}

variable "tutor_model" {
  description = "Bedrock inference profile the workshop tutor uses."
  type        = string
  default     = "${1}"
}
EOF
}

# aws: accounts resolve, quotas are ample, the boundary and VPC are there. get-foundation-model-availability answers
# per AGREE_<profile>_<model>, with every character outside [A-Za-z0-9] as _: unset is AVAILABLE, "denied" is an
# AccessDenied error, "empty" prints nothing, anything else is printed as the status.
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $* [AWS_PROFILE=${AWS_PROFILE:-}]" >>"${CALLS}"
case "$1 $2" in
  "sts get-caller-identity")
    case "${AWS_PROFILE}" in accen-dev) echo 515966504359 ;; aws1-student31) echo 948731545609 ;; *) exit 255 ;; esac ;;
  "service-quotas get-service-quota") echo 1000.0 ;;
  "iam get-policy") echo watch-it-burn-permissions-boundary ;;
  "ec2 describe-vpcs") echo vpc-0abc ;;
  "bedrock get-foundation-model-availability")
    model=""; prev=""; for a in "$@"; do [[ "${prev}" == "--model-id" ]] && model="${a}"; prev="${a}"; done
    var="AGREE_${AWS_PROFILE}_${model}"; var="${var//[^A-Za-z0-9]/_}"
    case "${!var:-AVAILABLE}" in
      empty) echo "" ;;
      denied) echo "An error occurred (AccessDeniedException) when calling the GetFoundationModelAvailability operation: no" >&2; exit 254 ;;
      *) echo "${!var:-AVAILABLE}" ;;
    esac ;;
esac
exit 0
S
cat >"${SHIM}/terraform" <<'S'
#!/usr/bin/env bash
state=""; for a in "$@"; do [[ "${a}" == -state=* ]] && state="${a#-state=}"; done
[[ "$*" == *"output"* ]] && grep -q vpc "${state}" 2>/dev/null && printf 'vpc-0abc'
exit 0
S
for t in kubectl jq curl helm; do printf '#!/usr/bin/env bash\nexit 0\n' >"${SHIM}/${t}"; done
chmod +x "${SHIM}"/*
export CALLS PATH="${SHIM}:${PATH}"

OUT="${T}/out"
run() {
  local accts="$1"; shift
  : >"${CALLS}"
  env -u WIB_DEFAULT_ACCOUNT -u WIB_EVENT WIB_ATTENDEE_ACCOUNTS="${accts}" WIB_REGION=us-west-2 "$@" \
    bash "${FLEET_DIR}/preflight.sh" 1 >"${OUT}" 2>&1
  rc=$?
}
has() { grep -qF -- "$1" "${OUT}"; }
pass_line() { grep -F 'PASS' "${OUT}" | grep -F -- "$1"; }
fail_line() { grep -F 'FAIL' "${OUT}" | grep -F -- "$1"; }
asked() { grep -F "bedrock get-foundation-model-availability" "${CALLS}"; }

echo "== every bound model AVAILABLE: GREEN, one read per model per account, as that account in WIB_REGION =="
write_tf "us.anthropic.claude-sonnet-5"
run accen-dev
check "exit 0"                                  '[[ "${rc}" -eq 0 ]]'
check "PREFLIGHT GREEN"                         'has "PREFLIGHT GREEN"'
for m in amazon.nova-pro-v1:0 anthropic.claude-haiku-4-5-20251001-v1:0 anthropic.claude-sonnet-4-6 \
         anthropic.claude-opus-4-8 anthropic.claude-sonnet-5; do
  check "asked about ${m}, without the us. prefix" 'asked | grep -qF -- "--model-id ${m} --region us-west-2"'
done
check "five models, five reads"                 '[[ "$(asked | wc -l)" -eq 5 ]]'
check "every read as accen-dev"                 '! asked | grep -vqF "[AWS_PROFILE=accen-dev]"'
check "the PASS line names the tier"            'pass_line "anthropic.claude-opus-4-8 (tier:opus): AVAILABLE" >/dev/null'
check "and the tutor"                           'pass_line "anthropic.claude-sonnet-5 (tutor): AVAILABLE" >/dev/null'

echo "== a tutor on a tier's model is one read, naming both =="
write_tf "us.anthropic.claude-sonnet-4-6"
run accen-dev
check "four reads"                              '[[ "$(asked | wc -l)" -eq 4 ]]'
check "the line names tier:sonnet and tutor"    'pass_line "anthropic.claude-sonnet-4-6 (tier:sonnet,tutor): AVAILABLE" >/dev/null'

echo "== NOT_AVAILABLE is a FAIL that prints the offers and accept commands and runs neither =="
write_tf "us.anthropic.claude-sonnet-5"
run accen-dev AGREE_accen_dev_anthropic_claude_sonnet_5=NOT_AVAILABLE
check "exit 1"                                  '[[ "${rc}" -eq 1 ]]'
check "PREFLIGHT FAILED"                        'has "PREFLIGHT FAILED"'
check "FAIL names the model, the tutor and the account" \
      'fail_line "anthropic.claude-sonnet-5 (tutor): NOT_AVAILABLE in accen-dev" >/dev/null'
check "and the offers command" \
      'fail_line "AWS_PROFILE=accen-dev aws bedrock list-foundation-model-agreement-offers --model-id anthropic.claude-sonnet-5 --region us-west-2" >/dev/null'
check "and the accept command" \
      'fail_line "AWS_PROFILE=accen-dev aws bedrock create-foundation-model-agreement --model-id anthropic.claude-sonnet-5 --offer-token" >/dev/null'
check "preflight called neither"                '! grep -qE "agreement-offers|create-foundation-model-agreement" "${CALLS}"'
check "the other four still PASS"               '[[ "$(grep -F PASS "${OUT}" | grep -cF "Bedrock agreement")" -eq 4 ]]'

echo "== PENDING is a FAIL too: accepted, not yet usable =="
run accen-dev AGREE_accen_dev_anthropic_claude_opus_4_8=PENDING
check "exit 1"                                  '[[ "${rc}" -eq 1 ]]'
check "FAIL says PENDING and to re-run"         'fail_line "anthropic.claude-opus-4-8 (tier:opus): PENDING" | grep -qF "re-run in 15 minutes"'

echo "== an unreadable answer is a FAIL, not a pass =="
run accen-dev AGREE_accen_dev_amazon_nova_pro_v1_0=denied
check "exit 1"                                  '[[ "${rc}" -eq 1 ]]'
check "FAIL says it could not be read, with the reason" \
      'fail_line "amazon.nova-pro-v1:0 (tier:nova) could not be read in accen-dev" | grep -qF "AccessDeniedException"'
run accen-dev AGREE_accen_dev_amazon_nova_pro_v1_0=empty
check "an empty answer is a FAIL too"           'fail_line "amazon.nova-pro-v1:0 (tier:nova) could not be read in accen-dev (empty answer)" >/dev/null'

echo "== per account: the agreement is the account's, so only the account without it fails =="
run accen-dev,aws1-student31 AGREE_aws1_student31_anthropic_claude_haiku_4_5_20251001_v1_0=NOT_AVAILABLE
check "exit 1"                                  '[[ "${rc}" -eq 1 ]]'
check "aws1-student31's haiku fails, naming that account" \
      'fail_line "anthropic.claude-haiku-4-5-20251001-v1:0 (tier:haiku): NOT_AVAILABLE in aws1-student31" | grep -qF "AWS_PROFILE=aws1-student31 aws bedrock list-foundation-model-agreement-offers"'
check "accen-dev's haiku passes"                'pass_line "anthropic.claude-haiku-4-5-20251001-v1:0 (tier:haiku): AVAILABLE" >/dev/null'
check "ten reads, five per account"             '[[ "$(asked | wc -l)" -eq 10 && "$(asked | grep -cF "[AWS_PROFILE=aws1-student31]")" -eq 5 ]]'

echo "== a cluster root it cannot read is a FAIL, never an empty pass =="
rm -f "${CLUSTER}/main.tf"
run accen-dev
check "exit 1"                                  '[[ "${rc}" -eq 1 ]]'
check "FAIL names the cluster root"             'fail_line "could not read bedrock_tiers and the tutor_model default" | grep -qF "aws/cluster/main.tf"'
check "and asks Bedrock nothing"                '[[ "$(asked | wc -l)" -eq 0 ]]'
printf 'locals {\n  bedrock_tiers = {\n    nova = "us.amazon.nova-pro-v1:0"\n  }\n}\n' >"${CLUSTER}/main.tf"
run accen-dev
check "a root with tiers and no tutor_model default fails too" \
      'fail_line "could not read bedrock_tiers and the tutor_model default" >/dev/null'

echo "== the real cluster root: preflight asks about exactly the models it binds =="
# Anchors this section reads the real file on; a reworded one names itself instead of failing further on.
for anchor in 'bedrock_tiers = {' 'variable "tutor_model"'; do
  if ! grep -qF -- "${anchor}" "${REAL_TF}"; then
    echo "  FAIL  anchor '${anchor}' is not in ${REAL_TF}: this test reads the model list on it"; exit 1
  fi
done
cp "${REAL_TF}" "${CLUSTER}/main.tf"
want="$(python3 - "${REAL_TF}" <<'P'
import re, sys
tf = open(sys.argv[1]).read()
ids = set(re.findall(r'"([^"]+)"', re.search(r"bedrock_tiers = \{(.*?)\}", tf, re.S).group(1)))
ids.add(re.search(r'variable "tutor_model".*?default\s*=\s*"([^"]+)"', tf, re.S).group(1))
print("\n".join(sorted(re.sub(r"^(us|eu|apac|global|jp|au|ca)\.", "", i) for i in ids)))
P
)"
run accen-dev
got="$(asked | sed -E 's/.*--model-id ([^ ]+) .*/\1/' | sort -u)"
check "the models asked are bedrock_tiers plus the tutor_model default (${want//$'\n'/, })" '[[ -n "${want}" && "${got}" == "${want}" ]]'
check "and all pass on the shim"                '[[ "${rc}" -eq 0 ]]'

echo
if [ "${fail}" -gt 0 ]; then echo "FAILED: ${fail} check(s), ${pass} passed"; exit 1; fi
echo "All preflight model agreement checks passed (${pass})."
