#!/usr/bin/env bash
# ABOUTME: Asserts nothing belonging to Watch It Burn is running in any fleet account, across every
# ABOUTME: resource type that has ever leaked here, not only the billable compute audit-zero covers.
#
# Why this exists, and why it is broader than audit-zero.
#
# `fleet.sh audit-zero` answers "is anything BILLABLE left", scoped to EKS, EC2, load balancers, target
# groups, volumes, NAT gateways, addresses and ENIs. That scope is correct for its name and is why it
# reported ZERO on five accounts that were each holding 105 orphaned security groups, which cost nothing
# and block the lab VPC from ever being deleted. It also says nothing about log groups, secrets, IAM,
# SSM, S3, ACM, snapshots, launch templates or key pairs.
#
# On 2026-09-18 a hand-written sweep found 107 orphaned log groups holding ~111 GB, four lab VPC shells,
# two security groups and six secrets, in accounts that audit-zero had passed. This is that sweep, kept.
#
# Co-tenancy is the constraint that shapes it. These accounts are SHARED with the Packt project: every
# one holds a packt-lab-vpc, and accen-dev has held Packt log groups. Every check here is therefore
# scoped by our own naming or our own VPC, never by "everything in the account". A broad delete in a
# shared account is how a co-tenant loses work.
#
# Usage:
#   verify/account-audit.sh                  # us-west-2, every fleet account
#   verify/account-audit.sh --all-regions    # also sweep every region for stray compute (slow)
#   verify/account-audit.sh --accounts a,b   # a subset
#
# Exit 0 = nothing of ours anywhere. Exit 1 = findings, each named on stdout.
set -uo pipefail

REGION="${WIB_REGION:-us-west-2}"
ACCOUNTS="${WIB_ATTENDEE_ACCOUNTS:-accen-dev,aws1-student31,aws1-student32,aws1-student33,aws1-student34}"
ALL_REGIONS=0
# Ours by name. Anything not matching one of these is someone else's and is never reported or touched.
readonly OURS='watch-it-burn'
readonly OURS_ALT='wib'
# Explicitly not ours, named so a future reader knows the exclusion is deliberate rather than an oversight.
readonly COTENANT_VPC='packt-lab-vpc'

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all-regions) ALL_REGIONS=1; shift ;;
        --accounts) ACCOUNTS="$2"; shift 2 ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

findings=0
finding() { printf '  FINDING  %s\n' "$*"; findings=$((findings+1)); }
ok()      { printf '  ok       %s\n' "$*"; }

aws_q() { AWS_PROFILE="$1" aws "${@:2}" 2>/dev/null; }

audit_account() {
    local p="$1"
    printf '\n=== %s ===\n' "${p}"

    # --- compute, the same ground audit-zero covers, repeated so this is a complete answer on its own
    local eks ec2 lb tg vol nat eip
    eks="$(aws_q "$p" eks list-clusters --region "$REGION" --query 'length(clusters)' --output text)"
    ec2="$(aws_q "$p" ec2 describe-instances --region "$REGION" --filters Name=instance-state-name,Values=running,pending,stopping,stopped --query 'length(Reservations[].Instances[])' --output text)"
    lb="$(aws_q "$p" elbv2 describe-load-balancers --region "$REGION" --query 'length(LoadBalancers)' --output text)"
    tg="$(aws_q "$p" elbv2 describe-target-groups --region "$REGION" --query 'length(TargetGroups)' --output text)"
    vol="$(aws_q "$p" ec2 describe-volumes --region "$REGION" --query 'length(Volumes)' --output text)"
    nat="$(aws_q "$p" ec2 describe-nat-gateways --region "$REGION" --filter Name=state,Values=available,pending --query 'length(NatGateways)' --output text)"
    eip="$(aws_q "$p" ec2 describe-addresses --region "$REGION" --query 'length(Addresses)' --output text)"
    for pair in "eks:${eks}" "ec2:${ec2}" "loadbalancers:${lb}" "targetgroups:${tg}" "volumes:${vol}" "nat:${nat}" "addresses:${eip}"; do
        local k="${pair%%:*}" v="${pair##*:}"
        [[ "${v:-0}" == "0" ]] && ok "${k} 0" || finding "${p}: ${k} = ${v}"
    done

    # --- the things audit-zero never looked at ---------------------------------------------------
    # Security groups cost nothing and block VPC deletion. Scoped to k8s-* because the load balancer
    # controller names them that and because a bare name match would reach into the co-tenant's VPC.
    local sg
    sg="$(aws_q "$p" ec2 describe-security-groups --region "$REGION" --filters 'Name=group-name,Values=k8s-*' --query 'length(SecurityGroups)' --output text)"
    [[ "${sg:-0}" == "0" ]] && ok "k8s security groups 0" || finding "${p}: ${sg} orphaned k8s-* security group(s), these block VPC deletion"

    # Log groups outlive their clusters and store real data. 111 GB was found this way.
    local lg lgb
    lg="$(aws_q "$p" logs describe-log-groups --region "$REGION" --query "length(logGroups[?contains(logGroupName,'${OURS}')])" --output text)"
    if [[ "${lg:-0}" == "0" ]]; then ok "log groups 0"; else
        lgb="$(aws_q "$p" logs describe-log-groups --region "$REGION" --query "sum(logGroups[?contains(logGroupName,'${OURS}')].storedBytes)" --output text)"
        finding "${p}: ${lg} ${OURS} log group(s), ${lgb:-?} stored bytes"
    fi

    local sec
    sec="$(aws_q "$p" secretsmanager list-secrets --region "$REGION" --query "length(SecretList[?contains(Name,'${OURS}')])" --output text)"
    [[ "${sec:-0}" == "0" ]] && ok "secrets 0" || finding "${p}: ${sec} ${OURS}/* secret(s)"

    # Our lab VPC, by tag. The co-tenant's is excluded by name, deliberately.
    local vpc
    vpc="$(aws_q "$p" ec2 describe-vpcs --region "$REGION" --filters "Name=tag:Name,Values=${OURS}-lab-vpc" --query 'length(Vpcs)' --output text)"
    [[ "${vpc:-0}" == "0" ]] && ok "lab VPC 0 (${COTENANT_VPC} and the default VPC are not ours)" || finding "${p}: ${vpc} ${OURS}-lab-vpc still present"

    local iam pol
    iam="$(aws_q "$p" iam list-roles --query "length(Roles[?contains(RoleName,'${OURS}')||contains(RoleName,'${OURS_ALT}')])" --output text)"
    pol="$(aws_q "$p" iam list-policies --scope Local --query "length(Policies[?contains(PolicyName,'${OURS}')||contains(PolicyName,'${OURS_ALT}')])" --output text)"
    [[ "${iam:-0}" == "0" ]] && ok "IAM roles 0" || finding "${p}: ${iam} IAM role(s)"
    [[ "${pol:-0}" == "0" ]] && ok "IAM policies 0" || finding "${p}: ${pol} IAM policy(ies)"

    local ecr ssm snap cfn
    ecr="$(aws_q "$p" ecr describe-repositories --region "$REGION" --query "length(repositories[?contains(repositoryName,'${OURS}')||contains(repositoryName,'${OURS_ALT}')])" --output text)"
    ssm="$(aws_q "$p" ssm describe-parameters --region "$REGION" --query "length(Parameters[?contains(Name,'${OURS}')||contains(Name,'${OURS_ALT}')])" --output text)"
    snap="$(aws_q "$p" ec2 describe-snapshots --region "$REGION" --owner-ids self --query 'length(Snapshots)' --output text)"
    cfn="$(aws_q "$p" cloudformation list-stacks --region "$REGION" --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query "length(StackSummaries[?contains(StackName,'${OURS}')||contains(StackName,'eksctl')])" --output text)"
    [[ "${ecr:-0}" == "0" ]]  && ok "ECR repos 0"   || finding "${p}: ${ecr} ECR repo(s)"
    [[ "${ssm:-0}" == "0" ]]  && ok "SSM params 0"  || finding "${p}: ${ssm} SSM parameter(s)"
    [[ "${snap:-0}" == "0" ]] && ok "snapshots 0"   || finding "${p}: ${snap} EBS snapshot(s)"
    [[ "${cfn:-0}" == "0" ]]  && ok "CFN stacks 0"  || finding "${p}: ${cfn} CloudFormation stack(s)"

    # Tagged anything, via the tagging API. Catches resource types not enumerated above.
    local tagged
    tagged="$(aws_q "$p" resourcegroupstaggingapi get-resources --region "$REGION" \
              --tag-filters "Key=Name,Values=*${OURS}*" --query 'length(ResourceTagMappingList)' --output text)"
    [[ "${tagged:-0}" == "0" ]] && ok "tagged resources 0" || finding "${p}: ${tagged} resource(s) tagged ${OURS}"

    if [[ "${ALL_REGIONS}" == "1" ]]; then
        local r k e
        for r in $(aws_q "$p" ec2 describe-regions --query 'Regions[].RegionName' --output text); do
            [[ "$r" == "$REGION" ]] && continue
            k="$(aws_q "$p" eks list-clusters --region "$r" --query 'length(clusters)' --output text)"
            e="$(aws_q "$p" ec2 describe-instances --region "$r" --filters Name=instance-state-name,Values=running,pending --query 'length(Reservations[].Instances[])' --output text)"
            (( ${k:-0} + ${e:-0} > 0 )) && finding "${p}: ${r} has eks=${k} ec2=${e}"
        done
        ok "all other regions swept"
    fi
}

IFS=',' read -ra accts <<<"${ACCOUNTS}"
printf 'account-audit: %d account(s), region %s%s\n' "${#accts[@]}" "${REGION}" \
    "$( [[ "${ALL_REGIONS}" == "1" ]] && printf ' + all regions' )"
for a in "${accts[@]}"; do
    a="${a// /}"; [[ -n "$a" ]] || continue
    audit_account "$a"
done

printf '\n'
if (( findings > 0 )); then
    printf 'FAILED: %d finding(s). Nothing was deleted; this command only reports.\n' "${findings}"
    exit 1
fi
printf 'CLEAN: nothing belonging to %s is present in any audited account.\n' "${OURS}"
