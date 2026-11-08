#!/usr/bin/env bash
# ABOUTME: Tests for #1082: fleet.sh's Datadog verification passes a cluster on Whitney's one sandbox org and fails a
# ABOUTME: cluster on any other org or on a retired pool (Portland), with kubectl and Datadog's answers stubbed. Offline.
#
# Why. Since #629 both KubeCon clusters ship to one org, Whitney's sandbox org, whose name is "Datadog" (read live
# 2026-11-08 on watch-it-burn-private and watch-it-burn-community). The check used to match a prefix, so an org that
# only started with "Datadog" passed, and its default had been the Portland pool's devops-days-portland-090826. Here
# fleet.sh's own run_datadog_orgs_verify runs verify/datadog-orgs.sh against shims: kubectl answers with an
# instructor cluster's secret and identity, curl answers /api/v2/current_user with the org the test names.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORGS="${HERE}/datadog-orgs.sh"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
NC="$(mktemp -d)"; SHIM="$(mktemp -d)"; trap 'rm -rf "${NC}" "${SHIM}"' EXIT
# Offline means offline (#859): aws, kubectl, eksctl, terraform and helm are stubs that log the call and fail; the
# shims below stand ahead of them, and the last check reads the log.
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${HERE}/no-cloud.sh"; no_cloud_guard "${NC}/no-cloud"

for f in "${ORGS}" "${FLEET}"; do
    [[ -f "$f" ]] || { echo "FATAL: $f is missing" >&2; exit 2; }
done
grep -q '^run_datadog_orgs_verify()' "${FLEET}" \
    || { echo "FATAL: run_datadog_orgs_verify() is not defined in ${FLEET}" >&2; exit 2; }

# An instructor cluster: its own datadog-secret and cluster-identity, no datadog-admin-secret (one org, #587).
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
case "$*" in
  *"get secret datadog-secret -o json"*) printf '{"data":{"api-key":"%s","app-key":"%s"}}' "$(printf OWN_API | base64)" "$(printf OWN_APP | base64)" ;;
  *"get configmap cluster-identity"*) printf '%s' "${SHIM_CLUSTER}" ;;
  *"get secret datadog-admin-secret"*) exit 1 ;;
  *) exit 1 ;;
esac
S
# Datadog's /api/v2/current_user, naming the org in SHIM_ORG; an empty SHIM_ORG is an answer with no org in it.
cat >"${SHIM}/curl" <<'S'
#!/usr/bin/env bash
echo "$*" >>"${SHIM_CURL_LOG}"
case "$*" in
  *"/api/v2/current_user"*)
    if [[ -n "${SHIM_ORG}" ]]; then
        printf '{"data":{"type":"users"},"included":[{"type":"orgs","attributes":{"name":"%s"}}]}' "${SHIM_ORG}"
    else
        printf '{"errors":["Forbidden"]}'
    fi ;;
  *) exit 7 ;;
esac
S
chmod +x "${SHIM}"/*
CURL_LOG="${SHIM}/curl.log"; : >"${CURL_LOG}"

# verify <cluster> <org> [VAR=value ...]: fleet.sh's own verification of that cluster, as `fleet.sh up` runs it.
verify() {
    local cluster="$1" org="$2"; shift 2
    env "$@" PATH="${SHIM}:${PATH}" SHIM_CLUSTER="${cluster}" SHIM_ORG="${org}" SHIM_CURL_LOG="${CURL_LOG}" \
        bash -c 'source "$1" >/dev/null 2>&1; run_datadog_orgs_verify "$2" accen-dev' _ "${FLEET}" "${cluster}" 2>&1
}

echo "== an instructor cluster on the one sandbox org passes =="
for c in watch-it-burn-private watch-it-burn-community; do
    out="$(verify "$c" Datadog)"; rc=$?
    check "$c on the sandbox org Datadog: exit 0" '[[ $rc -eq 0 ]]'
    check "$c: it names the org and the single-org instructor case" \
        'grep -q "OK    $c -> Datadog" <<<"$out" && grep -q "instructor cluster, single org by design" <<<"$out"'
done
check "the org is read from /api/v2/current_user, which the sandbox's read-only key may call" \
    'grep -q "https://api.datadoghq.com/api/v2/current_user" "${CURL_LOG}"'

echo "== a cluster on any other org fails =="
for org in "devops-days-portland-090826-003" "devops-days-portland-090826-150" "ai-eng-wf-062626-012" \
           "Datadog Demo Org" "Datadog-trial-7" "datadog" "Acme Pool 007" ""; do
    out="$(verify watch-it-burn-private "$org")"; rc=$?
    check "an org named '${org:-<none in the answer>}' fails, naming the cluster" \
        '[[ $rc -ne 0 ]] && grep -q "FAIL  watch-it-burn-private -> " <<<"$out"'
done
out="$(verify watch-it-burn-private devops-days-portland-090826-003)"
check "the Portland org fails as a retired pool's org" 'grep -q "retired pool.s org (devops-days-portland-090826)" <<<"$out"'
out="$(verify watch-it-burn-private "Datadog Demo Org")"
check "an org that only starts with Datadog fails as not the sandbox org" 'grep -q "expected the sandbox org Datadog" <<<"$out"'

echo "== the Portland pool prefix fails even when the environment names it =="
out="$(verify watch-it-burn-private devops-days-portland-090826-003 WIB_DD_POOL_PREFIX=devops-days-portland-090826)"; rc=$?
check "WIB_DD_POOL_PREFIX=devops-days-portland-090826 does not let a Portland org pass" \
    '[[ $rc -ne 0 ]] && grep -q "retired pool" <<<"$out"'
out="$(verify watch-it-burn-private Datadog WIB_DD_POOL_PREFIX=devops-days-portland-090826)"; rc=$?
check "and under that prefix the sandbox org is not on it either" '[[ $rc -ne 0 ]]'

echo "== a per-event pool still names its own prefix =="
out="$(verify watch-it-burn-private "Acme Pool 007" WIB_DD_POOL_PREFIX="Acme Pool")"; rc=$?
check "WIB_DD_POOL_PREFIX='Acme Pool' passes an org under it" '[[ $rc -eq 0 ]] && grep -q "OK    watch-it-burn-private -> Acme Pool 007" <<<"$out"'
out="$(verify watch-it-burn-private Datadog WIB_DD_ORG="Other Sandbox")"; rc=$?
check "WIB_DD_ORG names another single org, and Datadog then fails" '[[ $rc -ne 0 ]]'

echo "== the cluster's identity still has to be its own =="
out="$(env PATH="${SHIM}:${PATH}" SHIM_CLUSTER=watch-it-burn SHIM_ORG=Datadog SHIM_CURL_LOG="${CURL_LOG}" \
    bash -c 'source "$1" >/dev/null 2>&1; run_datadog_orgs_verify watch-it-burn-private accen-dev' _ "${FLEET}" 2>&1)"; rc=$?
check "the sandbox org with the bare watch-it-burn identity still fails" '[[ $rc -ne 0 ]] && grep -q "identity:" <<<"$out"'

echo "== offline means offline =="
check "no Datadog call left the shims: every curl was to /api/v2/current_user" \
    '! grep -v "/api/v2/current_user" "${CURL_LOG}" | grep -q .'
check "no check above called aws, kubectl, eksctl, terraform or helm" 'no_cloud_clean'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
