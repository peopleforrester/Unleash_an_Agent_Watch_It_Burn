#!/usr/bin/env bash
# Clear orphan k8s-* security groups from a lab VPC, then terraform-destroy the VPC.
# These SGs are created by EKS load balancers and survive force-deleted clusters;
# they cross-reference each other so DeleteVpc fails until they are removed.
# Usage: clean-sgs-and-destroy.sh <profile> <lab_vpc_state_path|DEFAULT>
set -u
PROFILE="$1"
STATE_ARG="$2"
REGION="us-west-2"
TFDIR="/home/michael/repos/events/Unleash_an_Agent_Watch_It_Burn/infra/terraform/aws/network"
AWS="aws --profile $PROFILE --region $REGION"
log() { echo "$(date +%H:%M:%S) [$PROFILE] $*"; }

VPC=$($AWS ec2 describe-vpcs --filters 'Name=tag:Name,Values=watch-it-burn-lab-vpc' \
      --query 'Vpcs[0].VpcId' --output text 2>/dev/null)
if [[ -z "$VPC" || "$VPC" == "None" ]]; then
  log "no lab VPC; nothing to do."; exit 0
fi
log "lab VPC=$VPC"

# Gather non-default SGs in the VPC
mapfile -t SGS < <($AWS ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" \
  --query "SecurityGroups[?GroupName!='default'].GroupId" --output text 2>/dev/null | tr '\t' '\n' | sed '/^$/d')
log "non-default SGs: ${#SGS[@]}"

# Phase 1: revoke ALL ingress + egress rules to break cross-references
for sg in "${SGS[@]}"; do
  ing=$($AWS ec2 describe-security-groups --group-ids "$sg" --query 'SecurityGroups[0].IpPermissions' --output json 2>/dev/null)
  if [[ -n "$ing" && "$ing" != "[]" && "$ing" != "null" ]]; then
    $AWS ec2 revoke-security-group-ingress --group-id "$sg" --ip-permissions "$ing" >/dev/null 2>&1
  fi
  eg=$($AWS ec2 describe-security-groups --group-ids "$sg" --query 'SecurityGroups[0].IpPermissionsEgress' --output json 2>/dev/null)
  if [[ -n "$eg" && "$eg" != "[]" && "$eg" != "null" ]]; then
    $AWS ec2 revoke-security-group-egress --group-id "$sg" --ip-permissions "$eg" >/dev/null 2>&1
  fi
done
log "revoked rules on ${#SGS[@]} SGs"

# Phase 2: delete SGs in a retry loop (handles any residual ordering)
remaining=("${SGS[@]}")
for round in 1 2 3 4 5; do
  (( ${#remaining[@]} == 0 )) && break
  next=()
  for sg in "${remaining[@]}"; do
    if ! $AWS ec2 delete-security-group --group-id "$sg" >/dev/null 2>&1; then
      next+=("$sg")
    fi
  done
  remaining=("${next[@]}")
  log "round $round: ${#remaining[@]} SGs still undeletable"
done
log "SGs left after delete loop: ${#remaining[@]}"

# Phase 3: terraform destroy the lab VPC
log "terraform destroy lab VPC..."
if [[ "$STATE_ARG" == "DEFAULT" ]]; then
  terraform -chdir="$TFDIR" destroy -auto-approve \
    -var "profile=$PROFILE" -var "region=$REGION" 2>&1 | tail -6
else
  terraform -chdir="$TFDIR" destroy -auto-approve -state="$STATE_ARG" \
    -var "profile=$PROFILE" -var "region=$REGION" 2>&1 | tail -6
fi
log "terraform destroy exit: ${PIPESTATUS[0]}"

v=$($AWS ec2 describe-vpcs --filters 'Name=tag:Name,Values=watch-it-burn-lab-vpc' --query 'length(Vpcs)' --output text 2>/dev/null)
log "POST: lab VPC count=$v"
