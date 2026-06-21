#!/usr/bin/env bash
# ABOUTME: Creates the target S3 "hoop" bucket attendees try to land the trophy in. Scoring reads it.
# ABOUTME: verify-at-build: grant each attendee agent IRSA s3:PutObject scoped to THIS bucket only.
set -euo pipefail
REGION="${AWS_REGION:-us-west-2}"
BUCKET="${1:-watch-it-burn-exfil-hoop}"
echo "==> creating hoop bucket s3://${BUCKET} in ${REGION}" >&2
if aws s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
    echo "==> bucket already exists" >&2
elif [[ "${REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" >/dev/null
else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
        --create-bucket-configuration LocationConstraint="${REGION}" >/dev/null
fi
aws s3api put-public-access-block --bucket "${BUCKET}" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true >/dev/null
# Collision-avoidance: tag the bucket project=watch-it-burn so it is unambiguously ours in a shared
# account (the Packt project also uses this account). Cost allocation + Resource Groups key on this tag.
aws s3api put-bucket-tagging --bucket "${BUCKET}" --tagging \
    'TagSet=[{Key=project,Value=watch-it-burn},{Key=event,Value=ai-engineer-worldsfair-2026},{Key=component,Value=exfil-game-hoop}]' >/dev/null
echo "==> hoop ready: s3://${BUCKET}" >&2
