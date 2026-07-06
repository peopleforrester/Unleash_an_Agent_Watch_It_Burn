#!/usr/bin/env bash
# Sweep one AWS account clean of witb orphans, then destroy its lab VPC.
# Usage: sweep-account.sh <profile> <lab_vpc_state_path|DEFAULT>
# - Deletes orphan k8s-* NLBs in the lab VPC
# - Releases EIPs that are NOT the NAT gateway's (protected)
# - Deletes 'available' EBS volumes tagged watch-it-burn
# - terraform destroys the lab VPC (NAT, subnets, endpoints)
set -u
PROFILE="$1"
STATE_ARG="$2"
REGION="us-west-2"
TFDIR="/home/michael/repos/events/Unleash_an_Agent_Watch_It_Burn/infra/terraform/aws/network"
AWS="aws --profile $PROFILE --region $REGION"

log() { echo "$(date +%H:%M:%S) [$PROFILE] $*"; }

# Resolve lab VPC id
VPC=$($AWS ec2 describe-vpcs --filters 'Name=tag:Name,Values=watch-it-burn-lab-vpc' \
      --query 'Vpcs[0].VpcId' --output text 2>/dev/null)
if [[ -z "$VPC" || "$VPC" == "None" ]]; then
  log "no lab VPC found; nothing to sweep. Skipping to verify."
else
  log "lab VPC=$VPC"

  # 1. Protect NAT gateway EIP allocation ids
  NAT_ALLOCS=$($AWS ec2 describe-nat-gateways \
    --filter "Name=vpc-id,Values=$VPC" "Name=state,Values=available,pending,deleting" \
    --query 'NatGateways[].NatGatewayAddresses[].AllocationId' --output text 2>/dev/null)
  log "protected NAT allocations: ${NAT_ALLOCS:-none}"

  # 2. Delete all NLBs/ALBs in the lab VPC
  mapfile -t LBARNS < <($AWS elbv2 describe-load-balancers \
    --query "LoadBalancers[?VpcId=='$VPC'].LoadBalancerArn" --output text 2>/dev/null | tr '\t' '\n' | sed '/^$/d')
  log "load balancers in lab VPC: ${#LBARNS[@]}"
  for arn in "${LBARNS[@]}"; do
    $AWS elbv2 delete-load-balancer --load-balancer-arn "$arn" 2>/dev/null \
      && log "deleted LB $(basename "$arn")" || log "FAILED delete LB $arn"
  done

  # 3. Wait for LB ENIs to clear (so EIPs disassociate and subnets free up)
  if (( ${#LBARNS[@]} > 0 )); then
    log "waiting for ELB ENIs to drain..."
    for i in $(seq 1 30); do
      eni=$($AWS ec2 describe-network-interfaces \
        --filters "Name=vpc-id,Values=$VPC" "Name=description,Values=ELB*" \
        --query 'length(NetworkInterfaces)' --output text 2>/dev/null)
      [[ "$eni" =~ ^[0-9]+$ ]] || eni="?"
      log "  ELB ENIs remaining: $eni (poll $i/30)"
      [[ "$eni" == "0" ]] && break
      sleep 20
    done
  fi

  # 4. Release EIPs not belonging to the NAT gateway
  PROTECT=" $NAT_ALLOCS "
  mapfile -t EIPS < <($AWS ec2 describe-addresses \
    --query 'Addresses[].[AllocationId,AssociationId]' --output text 2>/dev/null)
  rel=0; skip=0
  for row in "${EIPS[@]}"; do
    alloc=$(echo "$row" | awk '{print $1}')
    assoc=$(echo "$row" | awk '{print $2}')
    [[ -z "$alloc" || "$alloc" == "None" ]] && continue
    if [[ "$PROTECT" == *" $alloc "* ]]; then skip=$((skip+1)); continue; fi
    # disassociate if still associated, then release
    if [[ -n "$assoc" && "$assoc" != "None" ]]; then
      $AWS ec2 disassociate-address --association-id "$assoc" 2>/dev/null
    fi
    $AWS ec2 release-address --allocation-id "$alloc" 2>/dev/null \
      && rel=$((rel+1)) || log "  could not release $alloc (maybe NAT/in-use)"
  done
  log "EIPs released=$rel protected/skipped=$skip"

  # 5. Delete available EBS volumes tagged watch-it-burn
  mapfile -t VOLS < <($AWS ec2 describe-volumes \
    --filters 'Name=status,Values=available' 'Name=tag:KubernetesCluster,Values=watch-it-burn-attendee-*' \
    --query 'Volumes[].VolumeId' --output text 2>/dev/null | tr '\t' '\n' | sed '/^$/d')
  # fallback: any available volume if the tag filter found none but volumes exist
  if (( ${#VOLS[@]} == 0 )); then
    mapfile -t VOLS < <($AWS ec2 describe-volumes --filters 'Name=status,Values=available' \
      --query 'Volumes[].VolumeId' --output text 2>/dev/null | tr '\t' '\n' | sed '/^$/d')
  fi
  log "available volumes to delete: ${#VOLS[@]}"
  vd=0
  for v in "${VOLS[@]}"; do
    $AWS ec2 delete-volume --volume-id "$v" 2>/dev/null && vd=$((vd+1))
  done
  log "volumes deleted=$vd"
fi

# 6. terraform destroy the lab VPC
log "terraform destroy lab VPC..."
if [[ "$STATE_ARG" == "DEFAULT" ]]; then
  terraform -chdir="$TFDIR" destroy -auto-approve \
    -var "profile=$PROFILE" -var "region=$REGION" 2>&1 | tail -5
else
  terraform -chdir="$TFDIR" destroy -auto-approve -state="$STATE_ARG" \
    -var "profile=$PROFILE" -var "region=$REGION" 2>&1 | tail -5
fi
log "terraform destroy exit: ${PIPESTATUS[0]}"

# 7. Verify
v=$($AWS ec2 describe-vpcs --filters 'Name=tag:Name,Values=watch-it-burn-lab-vpc' --query 'length(Vpcs)' --output text 2>/dev/null)
lb=$($AWS elbv2 describe-load-balancers --query 'length(LoadBalancers)' --output text 2>/dev/null)
nat=$($AWS ec2 describe-nat-gateways --filter 'Name=state,Values=available,pending' --query 'length(NatGateways)' --output text 2>/dev/null)
eip=$($AWS ec2 describe-addresses --query 'length(Addresses)' --output text 2>/dev/null)
vol=$($AWS ec2 describe-volumes --query 'length(Volumes)' --output text 2>/dev/null)
log "POST-SWEEP: VPC=$v LB=$lb NAT=$nat EIP=$eip Vol=$vol"
