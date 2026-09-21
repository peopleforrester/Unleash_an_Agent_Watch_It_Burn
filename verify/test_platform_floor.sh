#!/usr/bin/env bash
# ABOUTME: Behavioural test for the platform floor: health and converge must refuse to give a verdict
# ABOUTME: about a cluster that has no platform on it, however cheerful its node and its DNS look.
#
# Why this exists (#404). `converge watch-it-burn-attendee-001` printed "CONVERGED: 1/1 clusters healthy
# with a resolvable console endpoint" about a cluster holding four namespaces and zero Argo CD
# Applications. Nothing was installed. The old guard fired only on ZERO applications, so a bootstrap that
# died after applying the root app-of-apps left a cluster that passed. "Converged" is the word this fleet
# uses to mean "a student can be handed this", and it has to be able to tell a platform from a bare EKS
# cluster. This pins the floor, the three ways "no applications" happens, and the thing that matters
# most: that converge STOPS rather than going on to repair and endpoint-check an empty cluster.
#
# Usage: verify/test_platform_floor.sh      (offline; kubectl is a shim)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .platform-floor-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"; CALLS="${T}/calls"; MODE="${T}/mode"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# One shim, driven by a mode file, so each scenario is a one-line switch rather than a new fixture.
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $*" >>"${CALLS}"
mode="$(cat "${MODE}")"
apps() { # $1 = how many, all Synced+Healthy
    python3 -c 'import json,sys
n=int(sys.argv[1])
print(json.dumps({"items":[{"metadata":{"name":f"app-{i}"},"status":{"sync":{"status":"Synced"},"health":{"status":"Healthy"}}} for i in range(n)]}))' "$1"
}
case "$*" in
  *"get applications.argoproj.io"*)
      case "${mode}" in
        nocrd)   echo 'error: the server doesn'"'"'t have a resource type "applications"' >&2; exit 1 ;;
        apidown) echo 'Unable to connect to the server: dial tcp: i/o timeout' >&2; exit 1 ;;
        empty)   apps 0 ;;
        partial) apps 3 ;;
        *)       apps 20 ;;
      esac ;;
  *"get namespace agent"*)  [[ "${mode}" == "nons" ]] && exit 1; exit 0 ;;
  *"get namespace argocd"*) exit 0 ;;
  *"get pods"*) : ;;
  *) : ;;
esac
S
chmod +x "${SHIM}/kubectl"
export CALLS MODE PATH="${SHIM}:${PATH}"

WIB_STATE_DIR="${T}/states" source "${FLEET}" >/dev/null 2>&1 || true
for fn in platform_floor read_argo_apps converge_one health_one; do
    declare -F "${fn}" >/dev/null || { echo "  FAIL  ${fn} is not defined in fleet.sh"; exit 1; }
done

LOGS="${T}/logs"
log() { echo "$*" >>"${LOGS}"; }
record_fail() { echo "RECORD_FAIL $1" >>"${CALLS}"; }
provider_write_kubeconfig() { : >"$2"; return 0; }
# Everything converge does AFTER the floor. If any of these is called on an empty cluster, converge
# went on to repair and endpoint-check a cluster with nothing installed, which is the defect.
repair_one() { echo "REPAIR_CALLED" >>"${CALLS}"; }
converge_endpoint() { echo "ENDPOINT_CALLED" >>"${CALLS}"; echo "some-lb.example"; return 0; }

run() { # run <mode> <fn>; fresh ledgers each time
    echo "$1" >"${MODE}"; : >"${CALLS}"; : >"${LOGS}"
    "$2" watch-it-burn-attendee-001 >/dev/null 2>&1
}

echo "== an empty cluster is not converged =="
run empty converge_one
check "converge records a failure"                   "grep -q 'RECORD_FAIL' '${CALLS}'"
check "the failure names the missing platform"       "grep -q 'RECORD_FAIL watch-it-burn-attendee-001:no-platform apps=0' '${CALLS}'"
check "it does NOT say CONVERGED"                    "! grep -q 'CONVERGED' '${LOGS}'"
check "it does not go on to repair the cluster"      "! grep -q 'REPAIR_CALLED' '${CALLS}'"
check "it does not go on to check the endpoint"      "! grep -q 'ENDPOINT_CALLED' '${CALLS}'"
check "the log says a bootstrap is what is needed"   "grep -qi 'NO PLATFORM' '${LOGS}'"

echo "== a bootstrap that died partway through is not converged either =="
run partial converge_one
check "three applications is below the floor"        "grep -q 'RECORD_FAIL watch-it-burn-attendee-001:no-platform apps=3' '${CALLS}'"
check "the floor is named in the failure"            "grep -q 'min-10' '${CALLS}'"

echo "== the three ways 'no applications' happens are told apart =="
run nocrd converge_one
check "absent CRDs read as no-argocd-crds"           "grep -q 'RECORD_FAIL watch-it-burn-attendee-001:no-argocd-crds' '${CALLS}'"
run apidown converge_one
check "an unreachable API reads as unreadable"       "grep -q 'RECORD_FAIL watch-it-burn-attendee-001:argocd-unreadable' '${CALLS}'"

echo "== applications alone are not a platform: the namespaces have to be there =="
run nons converge_one
check "a missing agent namespace fails the floor"    "grep -q 'RECORD_FAIL watch-it-burn-attendee-001:missing-namespaces=\[agent\]' '${CALLS}'"
check "and converge stops before repairing"          "! grep -q 'REPAIR_CALLED' '${CALLS}'"

echo "== a real platform still passes =="
run full converge_one
check "twenty healthy apps reach the repair step"    "grep -q 'REPAIR_CALLED' '${CALLS}'"
check "and the endpoint check"                       "grep -q 'ENDPOINT_CALLED' '${CALLS}'"
check "and the cluster converges"                    "grep -q 'CONVERGED' '${LOGS}'"
check "with no failure recorded"                     "! grep -q 'RECORD_FAIL' '${CALLS}'"

echo "== health is gated the same way, since it answers the same question =="
run empty health_one
check "health refuses an empty cluster"              "grep -q 'RECORD_FAIL watch-it-burn-attendee-001:no-platform' '${CALLS}'"
check "health does not call it HEALTHY"              "! grep -q 'HEALTHY' '${LOGS}'"
run full health_one
check "health still passes a real platform"          "grep -q 'HEALTHY' '${LOGS}'"

echo
echo "platform-floor checks: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
