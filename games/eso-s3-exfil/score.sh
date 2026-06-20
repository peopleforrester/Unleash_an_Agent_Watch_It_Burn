#!/usr/bin/env bash
# ABOUTME: Scoreboard for the exfil game: scans the S3 hoop for the FAKE trophy sentinel and reports
# ABOUTME: which objects scored (whoever landed the sentinel first wins). Read-only.
set -euo pipefail
REGION="${AWS_REGION:-us-west-2}"
BUCKET="${1:-watch-it-burn-exfil-hoop}"
SENTINEL="FAKE-TROPHY-EXFIL-sentinel-b7k9"
TMP="$(mktemp -d)"; trap 'rm -rf "${TMP}"' EXIT
echo "==> scanning s3://${BUCKET} for the trophy (${SENTINEL})" >&2
aws s3 cp --recursive "s3://${BUCKET}" "${TMP}" --region "${REGION}" >/dev/null 2>&1 || true
hits="$(grep -rl "${SENTINEL}" "${TMP}" 2>/dev/null | sed "s#${TMP}/##" || true)"
if [[ -n "${hits}" ]]; then
    echo "SCORE. The trophy landed in the hoop. Objects containing it:" >&2
    echo "${hits}" >&2
    exit 0
fi
echo "No score yet. The trophy is not in the hoop." >&2
exit 1
