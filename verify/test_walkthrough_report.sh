#!/usr/bin/env bash
# ABOUTME: Behavioural test for the fleet-walkthrough JSON report the admin console shows (#268): console code,
# ABOUTME: Argo count, BurritoBot's pod Ready, and last trace seen, with an unknown trace column said out loud.
#
# Usage: verify/test_walkthrough_report.sh      (no cloud access; curl, aws and kubectl are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/states"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
jtrue() { python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); r = d["results"][0]; sys.exit(0 if eval(sys.argv[2]) else 1)' "$1" "$2" 2>/dev/null; }

# curl: the console answers 200, the lab page has Challenge 1, the terminal demands its password.
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
# aws: the kubeconfig is written; the instructor org's Datadog secret cannot be read, so last trace is unknown.
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
case "$*" in
  *"eks update-kubeconfig"*) exit 0 ;;
  *secretsmanager*) echo "AccessDenied: not in this test" >&2; exit 255 ;;
esac
exit 0
S
# kubectl: one of two Argo apps converged, no C6 artifact, and BurritoBot's Ready status from AGENT_READY.
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
case "$*" in
  "config current-context") echo "arn:aws:eks:us-west-2:111122223333:cluster/watch-it-burn-attendee-007" ;;
  *"get applications --no-headers"*) printf 'platform   Synced     Healthy\nai-layer   OutOfSync  Healthy\n' ;;
  *"get deploy maintenance-shell"*) exit 1 ;;
  *"app.kubernetes.io/name=workshop-agent"*) printf '%s\n' "${AGENT_READY}" ;;
esac
exit 0
S
chmod +x "${SHIM}"/*
touch "${T}/states/watch-it-burn-attendee-007.tfstate"
walk() { # $1 AGENT_READY value, $2 report path
  PATH="${SHIM}:${PATH}" AGENT_READY="$1" WIB_STATE_DIR="${T}/states" \
    bash "${HERE}/fleet-walkthrough.sh" --json "$2" >"${T}/out" 2>&1
}

echo "== a cluster with BurritoBot Ready =="
walk True "${T}/r1.json"
check "the report is written" '[[ -s "${T}/r1.json" ]]'
check "console HTTP code" 'jtrue "${T}/r1.json" "r[\"console_http\"] == 200"'
check "Argo Synced+Healthy count out of total" 'jtrue "${T}/r1.json" "r[\"argo\"] == {\"synced_healthy\": 1, \"total\": 2}"'
check "agent pod Ready" 'jtrue "${T}/r1.json" "r[\"agent_ready\"] is True and \"agent-not-ready\" not in r[\"issues\"]"'
check "the Argo shortfall is still an issue" 'jtrue "${T}/r1.json" "\"argo=1/2\" in r[\"issues\"] and r[\"status\"] == \"fail\""'
check "an unreadable trace source leaves last_trace null, not a time" 'jtrue "${T}/r1.json" "r[\"last_trace\"] is None"'
check "and the report says why the column is unknown" 'jtrue "${T}/r1.json" "\"cannot read watch-it-burn/datadog\" in (d[\"last_trace_error\"] or \"\")"'
check "the console output says so too" 'grep -q "last trace unknown" "${T}/out"'

echo "== a cluster whose BurritoBot pod is not Ready =="
walk False "${T}/r2.json"
check "agent_ready is false and named as an issue" 'jtrue "${T}/r2.json" "r[\"agent_ready\"] is False and \"agent-not-ready\" in r[\"issues\"]"'
walk "" "${T}/r3.json"
check "no agent pod at all is not Ready either" 'jtrue "${T}/r3.json" "r[\"agent_ready\"] is False"'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
