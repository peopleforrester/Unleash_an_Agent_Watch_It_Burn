#!/usr/bin/env bash
# ABOUTME: Tears down the exfil game: empties + deletes the hoop bucket and deletes the FAKE trophy.
set -euo pipefail
REGION="${AWS_REGION:-us-west-2}"
BUCKET="${1:-watch-it-burn-exfil-hoop}"
echo "==> emptying + deleting s3://${BUCKET}" >&2
aws s3 rm "s3://${BUCKET}" --recursive --region "${REGION}" >/dev/null 2>&1 || true
aws s3api delete-bucket --bucket "${BUCKET}" --region "${REGION}" >/dev/null 2>&1 || true
echo "==> deleting FAKE trophy from Secrets Manager" >&2
aws secretsmanager delete-secret --region "${REGION}" --secret-id "watch-it-burn/exfil-game-trophy" \
    --force-delete-without-recovery >/dev/null 2>&1 || true
echo "==> teardown complete" >&2
