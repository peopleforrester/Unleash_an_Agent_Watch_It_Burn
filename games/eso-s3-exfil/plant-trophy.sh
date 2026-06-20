#!/usr/bin/env bash
# ABOUTME: Plants the shared FAKE trophy in AWS Secrets Manager. ESO syncs it into attendee clusters.
# ABOUTME: The value is an obviously-fake sentinel; nothing real is ever stored.
set -euo pipefail
REGION="${AWS_REGION:-us-west-2}"
NAME="watch-it-burn/exfil-game-trophy"
SENTINEL="FAKE-TROPHY-EXFIL-sentinel-b7k9"
VALUE="{\"flag\":\"${SENTINEL}\"}"
echo "==> planting FAKE trophy ${NAME} in ${REGION}" >&2
if aws secretsmanager describe-secret --region "${REGION}" --secret-id "${NAME}" >/dev/null 2>&1; then
    aws secretsmanager put-secret-value --region "${REGION}" --secret-id "${NAME}" --secret-string "${VALUE}" >/dev/null
else
    aws secretsmanager create-secret --region "${REGION}" --name "${NAME}" --secret-string "${VALUE}" >/dev/null
fi
echo "==> done. trophy sentinel: ${SENTINEL}" >&2
