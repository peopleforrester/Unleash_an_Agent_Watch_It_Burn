#!/usr/bin/env bash
# ABOUTME: Asserts every cluster ships to a Datadog org from the CURRENT event pool, not a stale one, and that
# ABOUTME: the pool's orgs have not expired. Key validity is NOT the check: expired trial orgs still validate keys.
#
# Why this exists. On 2026-09-05 every cluster in the fleet, the provisioning admin bundle, and both pool
# secrets were still on the June 26 World's Fair orgs (ai-eng-wf-062626-*). Every existing check passed,
# because /api/v1/validate returns {"valid":true} for an expired trial org and the agents kept shipping data.
# What died was the web UI login the lab page hands a student. Whitney hit "Your trial account has expired"
# on every walkthrough, and nothing automated could have told us. See issue #237.
#
# Usage:
#   verify/datadog-orgs.sh <kube-context> [aws-profile]           # one cluster
#   verify/datadog-orgs.sh --pool [aws-profile]                   # the pool secret only
#
# Env: WIB_DD_POOL_PREFIX (default devops-days-portland-090826) is the org-name prefix every cluster must be on.
#      WIB_DD_MIN_DAYS (default 3) is the minimum days of pool validity left before this fails.
#      WITB_DD_ADMIN_APP_KEY is the instructor org APP key, read from THIS environment. It used to be read
#      off the cluster out of datadog-admin-secret, which meant a read credential for the org holding every
#      attendee's prompts sat on all 50 student clusters, where the terminal has cluster-wide read (#272).
#      Without it the dual-shipping destination cannot be named, so that one assertion degrades to a SKIP
#      rather than silently passing.
set -euo pipefail

# fleet.sh owns what a cluster is NAMED; this file must not restate it. The glob here used to be
# "*-pres-*", which the #208/#258 rename to <owner>-student made dead: watch-it-burn-michael-student matched
# neither that nor *-attendee-*, so a presenter cluster with dual shipping MISSING was reported as
# "instructor cluster, single org by design". A false pass on Michael's and Whitney's own demo clusters.
_HERE_DDO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1090
source "${_HERE_DDO}/../infra/terraform/fleet/fleet.sh" >/dev/null 2>&1 || true

PREFIX="${WIB_DD_POOL_PREFIX:-devops-days-portland-090826}"
ADMIN_APP_KEY="${WITB_DD_ADMIN_APP_KEY:-}"
MIN_DAYS="${WIB_DD_MIN_DAYS:-3}"
REGION="${WIB_REGION:-us-west-2}"
fail=0

check_pool() {
    local profile="$1"
    local pool
    pool="$(AWS_PROFILE="$profile" aws secretsmanager get-secret-value --region "$REGION" \
        --secret-id watch-it-burn/datadog-pool --query SecretString --output text)"
    python3 - "$pool" "$PREFIX" "$MIN_DAYS" <<'PY'
import sys, json, time
pool, prefix, min_days = json.loads(sys.argv[1]), sys.argv[2], int(sys.argv[3])
bad = [r["org"] for r in pool if not str(r.get("org", "")).startswith(prefix)]
exps = [int(r["expirationDate"]) for r in pool if str(r.get("expirationDate", "")).isdigit()]
print(f"  pool: {len(pool)} orgs, {len(pool) - len(bad)} on prefix {prefix}")
rc = 0
if bad:
    print(f"  FAIL: {len(bad)} org(s) not from the current pool, e.g. {bad[:3]}"); rc = 1
if not exps:
    print("  FAIL: pool rows carry no expirationDate; cannot prove they are alive"); rc = 1
else:
    days = (min(exps) - time.time()) / 86400
    print(f"  earliest expiry in {days:.1f} days")
    if days < min_days:
        print(f"  FAIL: pool expires in under {min_days} days"); rc = 1
sys.exit(rc)
PY
}

check_cluster() {
    local ctx="$1" profile="$2"
    local api app org
    read -r api app < <(AWS_PROFILE="$profile" kubectl --context "$ctx" -n datadog get secret datadog-secret -o json \
        | python3 -c 'import sys,json,base64;d=json.load(sys.stdin)["data"];print(base64.b64decode(d["api-key"]).decode(),base64.b64decode(d["app-key"]).decode())')
    org="$(curl -s --max-time 20 -H "DD-API-KEY: $api" -H "DD-APPLICATION-KEY: $app" https://api.datadoghq.com/api/v1/org \
        | python3 -c 'import sys,json;print(json.load(sys.stdin)["orgs"][0]["name"])' 2>/dev/null || echo "?")"
    local rc=0
    if [[ "$org" == "$PREFIX"* ]]; then
        echo "  OK    $ctx -> $org"
    else
        echo "  FAIL  $ctx -> $org (expected prefix $PREFIX)"; rc=1
    fi
    # Per-cluster identity (#242): without it every cluster reports kube_cluster_name=watch-it-burn.
    local ident want
    want="${ctx##*/}"
    ident="$(AWS_PROFILE="$profile" kubectl --context "$ctx" -n datadog get configmap cluster-identity \
        -o jsonpath='{.data.cluster-name}' 2>/dev/null || true)"
    if [[ "$ident" == "$want" ]]; then
        echo "  OK    $ctx identity: $ident"
    else
        echo "  FAIL  $ctx identity: '${ident:-<none>}' (want $want); run infra/datadog-cluster-identity.sh"; rc=1
    fi
    # Dual shipping (#242): attendee and presenter clusters carry the instructor org as a second
    # destination. The admin APP key is NOT on the cluster any more (#272); it comes from the operator's
    # environment, so this can name the destination org without shipping a read credential to 50 students.
    local aapi aorg
    if AWS_PROFILE="$profile" kubectl --context "$ctx" -n datadog get secret datadog-admin-secret >/dev/null 2>&1; then
        aapi="$(AWS_PROFILE="$profile" kubectl --context "$ctx" -n datadog get secret datadog-admin-secret -o json 2>/dev/null \
            | python3 -c 'import sys,json,base64;print(base64.b64decode(json.load(sys.stdin)["data"]["api-key"]).decode())' 2>/dev/null || true)"
        if [[ -z "$aapi" ]]; then
            echo "  FAIL  $ctx: datadog-admin-secret has no api-key (dual shipping cannot work)"; rc=1
        elif [[ -z "$ADMIN_APP_KEY" ]]; then
            # Naming the org needs an app key, and we deliberately no longer have one on the cluster. Say so
            # rather than passing quietly: a silent OK here is what let the June orgs survive (#237).
            echo "  SKIP  $ctx dual-ships (admin api-key present); set WITB_DD_ADMIN_APP_KEY to name the org"
        else
            aorg="$(curl -s --max-time 20 -H "DD-API-KEY: $aapi" -H "DD-APPLICATION-KEY: $ADMIN_APP_KEY" https://api.datadoghq.com/api/v1/org \
                | python3 -c 'import sys,json;print(json.load(sys.stdin)["orgs"][0]["name"])' 2>/dev/null || echo "?")"
            if [[ "$aorg" == "$PREFIX"* && "$aorg" != "$org" ]]; then
                echo "  OK    $ctx dual-ships to $aorg"
            else
                echo "  FAIL  $ctx admin org: $aorg (want prefix $PREFIX and not the cluster's own org $org)"; rc=1
            fi
        fi
    else
        # is_presenter_name comes from fleet.sh so the rename cannot orphan this check again.
        if [[ "$want" == *-attendee-* ]] || is_presenter_name "$want"; then
            echo "  FAIL  $ctx: attendee/presenter cluster without datadog-admin-secret (no dual shipping)"; rc=1
        else
            echo "  OK    $ctx: instructor cluster, single org by design"
        fi
    fi
    return $rc
}

if [[ "${1:-}" == "--pool" ]]; then
    check_pool "${2:-accen-dev}" || fail=1
elif [[ -n "${1:-}" ]]; then
    check_cluster "$1" "${2:-accen-dev}" || fail=1
else
    echo "usage: $0 <kube-context> [aws-profile] | --pool [aws-profile]" >&2; exit 2
fi
exit $fail
