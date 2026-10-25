#!/usr/bin/env bash
# ABOUTME: Behavioural test that fleet-walkthrough.sh --only fails a named cluster with no state file (#570),
# ABOUTME: so `fleet.sh verify <names>` cannot pass when nothing it was asked to check exists.
#
# Usage: verify/test_walkthrough_no_state.sh      (no cloud access; curl, aws and kubectl are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/states"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
jtrue() { python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); sys.exit(0 if eval(sys.argv[2]) else 1)' "$1" "$2" 2>/dev/null; }

# A healthy cluster on every check, so the only failure a run can show is the missing state.
cat >"${SHIM}/curl" <<'S'
#!/usr/bin/env bash
w=""; url=""
for a in "$@"; do [[ "$a" == "%{http_code}" ]] && w=1; [[ "$a" == http* ]] && url="$a"; done
case "${url}" in
  */terminal/) [[ -n "$w" ]] && printf 401 ;;
  */lab.html)  echo "<h2>Challenge 1</h2>" ;;
  *)           [[ -n "$w" ]] && printf 200 ;;
esac
exit 0
S
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
case "$*" in
  *"eks update-kubeconfig"*) exit 0 ;;
  *secretsmanager*) echo "AccessDenied: not in this test" >&2; exit 255 ;;
esac
exit 0
S
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
case "$*" in
  "config current-context") echo "arn:aws:eks:us-west-2:111122223333:cluster/watch-it-burn-attendee-007" ;;
  *"get applications --no-headers"*) printf 'platform   Synced     Healthy\n' ;;
  *"get deploy maintenance-shell"*) exit 1 ;;
  *"app.kubernetes.io/name=workshop-agent"*) echo True ;;
esac
exit 0
S
chmod +x "${SHIM}"/*
# datadog-orgs.sh would need a real org; a passing stand-in keeps the healthy cluster healthy.
mkdir -p "${T}/verify"; cp "${HERE}/fleet-walkthrough.sh" "${HERE}/last_trace.py" "${T}/verify/"
printf '#!/usr/bin/env bash\nexit 0\n' >"${T}/verify/datadog-orgs.sh"
mkdir -p "${T}/infra/terraform"; ln -s "${HERE}/../infra/terraform/fleet" "${T}/infra/terraform/fleet"
walk() { # $1 --only list, $2 report path; sets rc
  PATH="${SHIM}:${PATH}" WIB_STATE_DIR="${T}/states" \
    bash "${T}/verify/fleet-walkthrough.sh" --only "$1" --json "$2" >"${T}/out" 2>&1
  rc=$?
}

echo "== no named cluster has a state file =="
walk "watch-it-burn-attendee-001,watch-it-burn-attendee-002" "${T}/r1.json"
check "exits non-zero" '[[ "${rc}" -ne 0 ]]'
check "each missing cluster is a named failure" 'grep -q "FAIL watch-it-burn-attendee-001: no-state" "${T}/out" && grep -q "FAIL watch-it-burn-attendee-002: no-state" "${T}/out"'
check "the tally counts them" 'grep -q "0 healthy, 2 with problems, out of 2" "${T}/out"'
check "the report lists them as failed" 'jtrue "${T}/r1.json" "d[\"clusters\"] == 2 and d[\"failed\"] == 2 and all(r[\"issues\"] == [\"no-state\"] for r in d[\"results\"])"'

echo "== one named cluster has state, one does not =="
touch "${T}/states/watch-it-burn-attendee-007.tfstate"
walk "watch-it-burn-attendee-007,watch-it-burn-attendee-008" "${T}/r2.json"
check "exits non-zero" '[[ "${rc}" -ne 0 ]]'
check "the present cluster is walked and healthy" 'grep -qE "watch-it-burn-attendee-007 +OK" "${T}/out"'
check "the absent one fails as no-state" 'grep -q "FAIL watch-it-burn-attendee-008: no-state" "${T}/out"'
check "the tally is one of each" 'grep -q "1 healthy, 1 with problems, out of 2" "${T}/out"'

echo "== every named cluster has state =="
walk "watch-it-burn-attendee-007" "${T}/r3.json"
check "exits zero" '[[ "${rc}" -eq 0 ]]'
check "no no-state failure" '! grep -q "no-state" "${T}/out"'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
