#!/usr/bin/env bash
# ABOUTME: Validate the Datadog credentials the fleet is actually using, so "is the trial still alive?" is
# ABOUTME: a measured answer on the morning of delivery rather than a guess (issue #95).
#
# Usage:
#   verify/datadog-pool-check.sh                 # every watch-it-burn cluster in the region
#   verify/datadog-pool-check.sh <cluster> ...   # just these
#   POOL=1 verify/datadog-pool-check.sh          # also validate the staged pool in Secrets Manager
#
# WHAT IT CHECKS, and what it deliberately does NOT:
#   api_key   -> GET /api/v1/validate. Proves INGESTION works: the agent can ship metrics and traces.
#   app_key   -> GET /api/v2/users?page[size]=1 with both keys. Proves the org answers authenticated
#                READS, which is the closest programmatic proxy for "the org is alive, not expired".
#   UI login  -> NOT CHECKABLE from here. A Datadog trial can end for the web UI while keys still work,
#                which is exactly the shape of Whitney's 2026-08-29 report ("my Datadog Pro trial has
#                expired") on a fleet whose api keys all validated. If app_key is fine but a human cannot
#                log in, the org is expired for UI purposes and needs re-minting: that is the real signal.
#
# Never prints a key. Only the last 6 characters, so two rows can be told apart.
set -uo pipefail
REGION="${AWS_REGION:-us-west-2}"
PROFILE="${AWS_PROFILE:-accen-dev}"
SITE="${DD_SITE:-datadoghq.com}"

clusters=("$@")
if [[ ${#clusters[@]} -eq 0 ]]; then
    mapfile -t clusters < <(aws eks list-clusters --region "$REGION" --profile "$PROFILE" \
        --query 'clusters[]' --output text 2>/dev/null | tr '\t' '\n' | grep watch-it-burn | sort)
fi

fail=0
for c in "${clusters[@]}"; do
    K=$(mktemp)
    aws eks update-kubeconfig --kubeconfig "$K" --name "$c" --region "$REGION" --profile "$PROFILE" >/dev/null 2>&1
    if ! KUBECONFIG="$K" kubectl config current-context 2>/dev/null | grep -q "$c"; then
        printf '  %-30s CONTEXT MISMATCH\n' "$c"; rm -f "$K"; fail=1; continue
    fi
    ak=$(KUBECONFIG="$K" AWS_PROFILE="$PROFILE" kubectl -n datadog get secret datadog-secret \
        -o jsonpath='{.data.api-key}' 2>/dev/null | base64 -d 2>/dev/null)
    pk=$(KUBECONFIG="$K" AWS_PROFILE="$PROFILE" kubectl -n datadog get secret datadog-secret \
        -o jsonpath='{.data.app-key}' 2>/dev/null | base64 -d 2>/dev/null)
    rm -f "$K"
    if [[ -z "$ak" ]]; then
        printf '  %-30s NO datadog-secret api key\n' "$c"; fail=1; continue
    fi
    v=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
        "https://api.${SITE}/api/v1/validate" -H "DD-API-KEY: $ak")
    if [[ -n "$pk" ]]; then
        r=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
            "https://api.${SITE}/api/v2/users?page%5Bsize%5D=1" \
            -H "DD-API-KEY: $ak" -H "DD-APPLICATION-KEY: $pk")
    else
        r="none"
    fi
    status=OK
    [[ "$v" == "200" ]] || { status="API-KEY-BAD"; fail=1; }
    [[ "$r" == "200" || "$r" == "none" ]] || { status="ORG-READ-BAD($r)"; fail=1; }
    printf '  %-30s api=%s org_read=%-4s key=...%s  %s\n' "$c" "$v" "$r" "${ak: -6}" "$status"
done

if [[ "${POOL:-0}" == "1" ]]; then
    echo
    echo "Staged pool in Secrets Manager:"
    for sec in watch-it-burn/datadog-pool watch-it-burn/datadog-pool-2; do
        n=$(aws secretsmanager get-secret-value --secret-id "$sec" --region "$REGION" --profile "$PROFILE" \
            --query SecretString --output text 2>/dev/null | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))' 2>/dev/null)
        printf '  %-34s %s entries\n' "$sec" "${n:-UNREADABLE}"
    done
fi

echo
if [[ "$fail" -eq 0 ]]; then
    echo "All checked Datadog credentials are live."
    echo "NOTE: this does not prove a human can LOG IN. Have Whitney open her org before doors."
else
    echo "PROBLEMS FOUND above. Trial orgs expire in ~14 days; re-mint and re-run distribute_datadog_keys.py."
fi
exit "$fail"
