#!/usr/bin/env bash
# ABOUTME: Finds workshop resources in one AWS account that carry no project tag, and optionally repairs
# ABOUTME: them, so a tag-driven teardown sweep cannot walk past them and leave them billing.
#
# Terraform default_tags do not reach every resource. Anything created by a controller inside the
# cluster (the AWS Load Balancer Controller), or by EKS on the cluster's behalf, is tagged by that
# component's own rules and not by terraform's. On one 50-cluster account of the sister Packt fleet,
# 451 resources carried no workshop tag at all. Every sweep that selects by tag therefore skipped them.
#
# The second half of the problem is ownership rather than tagging. Once a cluster's terraform state is
# gone, nothing owns the IAM roles, the customer-managed policies, or the CloudWatch log groups it
# created, and they are invisible to `terraform destroy`. Confirmed on 2026-08-24: two torn-down
# clusters left 8 IAM roles and 6 policies behind. Those do not bill, but they accumulate and they
# carry whatever grants were attached to them, which is the part that matters.
#
# Usage:
#   tag-audit.sh <profile> [--fix] [--region us-west-2]
#
# Read-only by default: it reports and exits non-zero if anything is untagged or orphaned. --fix adds
# the missing tags. --fix NEVER deletes anything; deletion stays with sweep-account.sh, where it is
# visible and deliberate.
set -uo pipefail

PROFILE="${1:-}"; shift || true
[[ -n "${PROFILE}" ]] || { echo "usage: ${0##*/} <profile> [--fix] [--region <r>]" >&2; exit 2; }

REGION="us-west-2"
FIX=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fix) FIX=1; shift ;;
    --region) REGION="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

readonly TAG_KEY="${WIB_TAG_KEY:-project}"
readonly TAG_VALUE="${WIB_TAG_VALUE:-watch-it-burn}"
# Overridable so the detection path can be exercised against a populated account without waiting for a
# fleet to exist. A run that reports "none" everywhere proves the filter matched nothing, not that the
# audit works, and those are very different things.
readonly NAME_MATCH="${WIB_NAME_MATCH:-watch-it-burn}"

AWS="aws --profile ${PROFILE} --region ${REGION}"
log() { printf '%s [%s] %s\n' "$(date +%H:%M:%S)" "${PROFILE}" "$*" >&2; }

untagged=0
orphaned=0

# --- EC2-family resources ------------------------------------------------------------------------
# One call covers instances, volumes, ENIs, security groups, subnets and the rest: describe-tags is
# the only EC2 API that answers "which of these has no tag" without a per-type describe. We invert it:
# list everything named for the workshop, then subtract what already carries the project tag.
audit_ec2() {
  local tagged_ids named_ids id
  named_ids="$(${AWS} ec2 describe-tags \
      --filters "Name=key,Values=Name" \
      --query "Tags[?contains(Value, \`${NAME_MATCH}\`)].ResourceId" \
      --output text 2>/dev/null | tr '\t' '\n' | sed '/^$/d' | sort -u)"
  [[ -n "${named_ids}" ]] || { log "ec2: no workshop-named resources"; return; }

  tagged_ids="$(${AWS} ec2 describe-tags \
      --filters "Name=key,Values=${TAG_KEY}" "Name=value,Values=${TAG_VALUE}" \
      --query 'Tags[].ResourceId' --output text 2>/dev/null | tr '\t' '\n' | sed '/^$/d' | sort -u)"

  local missing; missing="$(comm -23 <(printf '%s\n' "${named_ids}") <(printf '%s\n' "${tagged_ids}"))"
  local n; n="$(printf '%s' "${missing}" | grep -c . || true)"
  [[ "${n}" -gt 0 ]] || { log "ec2: all $(printf '%s' "${named_ids}" | grep -c .) workshop resources tagged"; return; }

  untagged=$(( untagged + n ))
  log "ec2: ${n} workshop-named resource(s) MISSING ${TAG_KEY}=${TAG_VALUE}"
  if [[ -n "${FIX}" ]]; then
    # create-tags takes up to 1000 resources per call; batch so a large account is one or two calls.
    printf '%s\n' "${missing}" | xargs -r -n 200 ${AWS} ec2 create-tags \
        --tags "Key=${TAG_KEY},Value=${TAG_VALUE}" --resources \
      && log "ec2: tagged ${n} resource(s)"
  else
    printf '%s\n' "${missing}" | sed 's/^/    /' >&2
  fi
}

# --- Load balancers ------------------------------------------------------------------------------
# Created by the LB Controller, not terraform, so these are the classic miss.
audit_elbv2() {
  local arns arn tags n=0 missing=()
  mapfile -t arns < <(${AWS} elbv2 describe-load-balancers \
      --query 'LoadBalancers[].LoadBalancerArn' --output text 2>/dev/null | tr '\t' '\n' | sed '/^$/d')
  [[ "${#arns[@]}" -gt 0 ]] || { log "elbv2: none"; return; }
  for arn in "${arns[@]}"; do
    tags="$(${AWS} elbv2 describe-tags --resource-arns "${arn}" \
        --query "TagDescriptions[0].Tags[?Key=='${TAG_KEY}'].Value" --output text 2>/dev/null)"
    [[ -n "${tags}" && "${tags}" != "None" ]] && continue
    missing+=("${arn}"); n=$(( n + 1 ))
  done
  [[ "${n}" -gt 0 ]] || { log "elbv2: all ${#arns[@]} tagged"; return; }
  untagged=$(( untagged + n ))
  log "elbv2: ${n} load balancer(s) MISSING ${TAG_KEY}=${TAG_VALUE}"
  for arn in "${missing[@]}"; do
    if [[ -n "${FIX}" ]]; then
      ${AWS} elbv2 add-tags --resource-arns "${arn}" --tags "Key=${TAG_KEY},Value=${TAG_VALUE}" >/dev/null 2>&1 \
        && log "    tagged $(basename "${arn}")"
    else
      printf '    %s\n' "${arn}" >&2
    fi
  done
}

# --- IAM roles and customer-managed policies ------------------------------------------------------
# These do not bill, so they are easy to leave behind, and they outlive the terraform state that made
# them. They also carry live grants, which is why they are worth naming rather than ignoring.
audit_iam() {
  local roles r policies pol n=0
  mapfile -t roles < <(${AWS} iam list-roles \
      --query "Roles[?contains(RoleName, \`${NAME_MATCH}\`)].RoleName" --output text 2>/dev/null \
      | tr '\t' '\n' | sed '/^$/d')
  if [[ "${#roles[@]}" -gt 0 ]]; then
    for r in "${roles[@]}"; do
      local has
      has="$(${AWS} iam list-role-tags --role-name "${r}" \
          --query "Tags[?Key=='${TAG_KEY}'].Value" --output text 2>/dev/null)"
      if [[ -z "${has}" || "${has}" == "None" ]]; then
        n=$(( n + 1 ))
        if [[ -n "${FIX}" ]]; then
          ${AWS} iam tag-role --role-name "${r}" --tags "Key=${TAG_KEY},Value=${TAG_VALUE}" >/dev/null 2>&1 \
            && log "    tagged role ${r}"
        else
          printf '    role %s\n' "${r}" >&2
        fi
      fi
    done
    untagged=$(( untagged + n ))
    log "iam: ${#roles[@]} workshop role(s), ${n} missing the tag"
  else
    log "iam: no workshop-named roles"
  fi

  mapfile -t policies < <(${AWS} iam list-policies --scope Local \
      --query "Policies[?contains(PolicyName, \`${NAME_MATCH}\`)].PolicyName" --output text 2>/dev/null \
      | tr '\t' '\n' | sed '/^$/d')
  if [[ "${#policies[@]}" -gt 0 ]]; then
    orphaned=$(( orphaned + ${#policies[@]} ))
    log "iam: ${#policies[@]} customer-managed policy/policies named for the workshop:"
    printf '    %s\n' "${policies[@]}" >&2
    log "iam: these are NOT auto-removed. Confirm each cluster is gone, then delete via sweep-account.sh."
  fi
}

# --- CloudWatch log groups ------------------------------------------------------------------------
# EKS control-plane logging creates these, and nothing removes them when the cluster goes. They bill
# for retained data.
audit_logs() {
  local groups g n=0
  mapfile -t groups < <(${AWS} logs describe-log-groups \
      --query "logGroups[?contains(logGroupName, \`${NAME_MATCH}\`)].logGroupName" --output text 2>/dev/null \
      | tr '\t' '\n' | sed '/^$/d')
  [[ "${#groups[@]}" -gt 0 ]] || { log "logs: no workshop log groups"; return; }
  for g in "${groups[@]}"; do
    local has
    has="$(${AWS} logs list-tags-for-resource \
        --resource-arn "arn:aws:logs:${REGION}:$(${AWS} sts get-caller-identity --query Account --output text):log-group:${g}" \
        --query "tags.${TAG_KEY}" --output text 2>/dev/null)"
    if [[ -z "${has}" || "${has}" == "None" ]]; then
      n=$(( n + 1 ))
      printf '    %s\n' "${g}" >&2
    fi
  done
  orphaned=$(( orphaned + ${#groups[@]} ))
  log "logs: ${#groups[@]} workshop log group(s), ${n} untagged. Retained data bills; delete after teardown."
}

log "tag audit: region ${REGION}${FIX:+ (--fix: will add missing tags)}"
audit_ec2
audit_elbv2
audit_iam
audit_logs

if [[ "${untagged}" -eq 0 && "${orphaned}" -eq 0 ]]; then
  log "CLEAN: everything workshop-named is tagged, and nothing is stranded."
  exit 0
fi
log "RESULT: ${untagged} untagged resource(s), ${orphaned} stranded resource(s)."
[[ -n "${FIX}" ]] && log "Re-run without --fix to confirm the tags landed."
exit 1
