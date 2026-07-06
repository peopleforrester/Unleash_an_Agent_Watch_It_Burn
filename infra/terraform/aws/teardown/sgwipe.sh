#!/usr/bin/env bash
# Parallelized: clear orphan k8s-* security groups from a lab VPC, then terraform-destroy the VPC.
# Usage: sgwipe.sh <profile> <lab_vpc_state_path|DEFAULT>
set -u
PROFILE="$1"; STATE_ARG="$2"; REGION="us-west-2"
TFDIR="/home/michael/repos/events/Unleash_an_Agent_Watch_It_Burn/infra/terraform/aws/network"
AWS="aws --profile $PROFILE --region $REGION"
log() { echo "$(date +%H:%M:%S) [$PROFILE] $*"; }

VPC=$($AWS ec2 describe-vpcs --filters 'Name=tag:Name,Values=watch-it-burn-lab-vpc' \
      --query 'Vpcs[0].VpcId' --output text 2>/dev/null)
if [[ -z "$VPC" || "$VPC" == "None" ]]; then log "no lab VPC; nothing to do."; exit 0; fi
log "lab VPC=$VPC"

revoke_one() {
  local sg="$1" P="$2" R="$3"
  local A="aws --profile $P --region $R"
  local ing eg
  ing=$($A ec2 describe-security-groups --group-ids "$sg" --query 'SecurityGroups[0].IpPermissions' --output json 2>/dev/null)
  [[ -n "$ing" && "$ing" != "[]" && "$ing" != "null" ]] && $A ec2 revoke-security-group-ingress --group-id "$sg" --ip-permissions "$ing" >/dev/null 2>&1
  eg=$($A ec2 describe-security-groups --group-ids "$sg" --query 'SecurityGroups[0].IpPermissionsEgress' --output json 2>/dev/null)
  [[ -n "$eg" && "$eg" != "[]" && "$eg" != "null" ]] && $A ec2 revoke-security-group-egress --group-id "$sg" --ip-permissions "$eg" >/dev/null 2>&1
}
export -f revoke_one

mapfile -t SGS < <($AWS ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" \
  --query "SecurityGroups[?GroupName!='default'].GroupId" --output text 2>/dev/null | tr '\t' '\n' | sed '/^$/d')
log "non-default SGs: ${#SGS[@]}"

# Phase 1: revoke ALL rules in parallel (breaks cross-references)
printf '%s\n' "${SGS[@]}" | xargs -P 24 -I{} bash -c 'revoke_one "$@"' _ {} "$PROFILE" "$REGION"
log "revoke phase done"

# Phase 2: delete SGs in parallel, retry rounds
remaining=("${SGS[@]}")
for round in 1 2 3 4 5 6; do
  (( ${#remaining[@]} == 0 )) && break
  printf '%s\n' "${remaining[@]}" | xargs -P 24 -I{} bash -c "$AWS ec2 delete-security-group --group-id {} >/dev/null 2>&1 || true"
  mapfile -t remaining < <($AWS ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" \
    --query "SecurityGroups[?GroupName!='default'].GroupId" --output text 2>/dev/null | tr '\t' '\n' | sed '/^$/d')
  log "round $round: ${#remaining[@]} SGs remain"
done

# Phase 3: terraform destroy
log "terraform destroy lab VPC..."
if [[ "$STATE_ARG" == "DEFAULT" ]]; then
  terraform -chdir="$TFDIR" destroy -auto-approve -var "profile=$PROFILE" -var "region=$REGION" 2>&1 | tail -6
else
  terraform -chdir="$TFDIR" destroy -auto-approve -state="$STATE_ARG" -var "profile=$PROFILE" -var "region=$REGION" 2>&1 | tail -6
fi
log "terraform destroy exit: ${PIPESTATUS[0]}"
v=$($AWS ec2 describe-vpcs --filters 'Name=tag:Name,Values=watch-it-burn-lab-vpc' --query 'length(Vpcs)' --output text 2>/dev/null)
log "POST: lab VPC count=$v"
