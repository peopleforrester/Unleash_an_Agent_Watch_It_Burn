#!/usr/bin/env bash
# ABOUTME: A provisioning verb whose terraform apply failed must exit non-zero, whether or not the routes
# ABOUTME: and verify tail runs (#527). Offline: terraform, aws and jq are shims; no cluster, no AWS.
#
# Why. At the KubeCon bring-up on 2026-10-24, `WIB_PER_ROLE=1 WIB_NO_INGEST=1 ./fleet.sh instructors up
# all` failed terraform apply on both clusters, printed "2 cluster(s) FAILED:", and exited 0. The failure
# ledger was read with `report_failures || true`, so the exit code was left to the verify pass, and the
# walkthrough, finding no state file for either cluster, reported "0 with problems, out of 0". Unattended
# callers (scheduled-up.sh, a Night Before script, a dispatcher) read that 0 as a fleet that came up.
#
# Unlike test_fleet_exit_codes.sh, nothing in the build itself is stubbed here: run_pool, up_one and the
# failure ledger are fleet.sh's own, and only the terraform binary underneath them fails.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -t fleet-apply-fail.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# terraform: init and the lab-VPC outputs succeed; apply fails for every cluster whose name matches
# TF_APPLY_FAIL (an ERE; empty fails nothing). Every apply is recorded, so the test can tell an apply that
# failed from one that never ran.
cat >"${SHIM}/terraform" <<'S'
#!/usr/bin/env bash
case " $* " in
  *" apply "*)
    name="$(printf '%s\n' "$@" | sed -n 's/^-state=.*\/\(.*\)\.tfstate$/\1/p')"
    echo "${name}" >>"${T}/applies"
    if [[ -n "${TF_APPLY_FAIL:-}" && "${name}" =~ ${TF_APPLY_FAIL} ]]; then
        echo "Error: creating EKS Cluster (${name}): shim apply failure" >&2; exit 1
    fi
    echo "{}" >"$(printf '%s\n' "$@" | sed -n 's/^-state=//p')"; exit 0 ;;
  *" output "*"vpc_id"*) printf 'vpc-test' ;;
  *" output "*"private_subnet_ids"*) printf '["subnet-a"]' ;;
esac
exit 0
S
# aws: an account with no attendee IAM user in it, so the pre-apply adoption (#549) has nothing to do.
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
case "$*" in
  *"iam list-user-tags"*) echo "An error occurred (NoSuchEntity) when calling the ListUserTags operation" >&2; exit 254 ;;
esac
exit 0
S
printf '#!/usr/bin/env bash\nexit 0\n' >"${SHIM}/jq"
chmod +x "${SHIM}"/*
export T PATH="${SHIM}:${PATH}"

# Fresh state and log dirs per run, so one run's state files never make the next one skip its apply.
fresh() { rm -rf "${T}/states" "${T}/logs" "${T}/applies"; mkdir -p "${T}/states" "${T}/logs"; }
env_common=(WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" WIB_DOCKERHUB_ENV=/nonexistent
            WIB_PER_ROLE=1 WIB_NO_INGEST=1)

# The real process, exactly as the bring-up ran it. WIB_NO_BOOTSTRAP turns off the routes and verify tail,
# so what decides the exit code here is the build alone.
run_process() { # $1: the ERE of clusters whose apply fails
    fresh
    ( cd "$(dirname "${FLEET}")" && env "${env_common[@]}" WIB_NO_BOOTSTRAP=1 TF_APPLY_FAIL="$1" \
        bash "${FLEET}" instructors up all ) >"${T}/out" 2>&1
    echo "rc=$?" >>"${T}/out"; cat "${T}/out"
}

# The same build with the tail running: bootstrap, the console-LB wait, routes and the acceptance pass are
# stubbed to succeed, as the walkthrough did when it found nothing to walk. The build and its terraform
# failures are still the real ones.
run_with_tail() { # $1: the ERE of clusters whose apply fails
    fresh
    ( cd "$(dirname "${FLEET}")" && env "${env_common[@]}" TF_APPLY_FAIL="$1" bash -c '
        source "'"${FLEET}"'" >/dev/null 2>&1
        bootstrap_one() { :; }
        wait_for_console_lbs() { :; }
        cmd_routes() { echo "routes ran"; }
        converge_one() { :; }
        cmd_verify() { echo "verify ran"; return 0; }
        cmd_instructors up all
    ' ) >"${T}/out" 2>&1
    # Taken outside: fleet.sh runs under set -e, so a non-zero return ends the shell before any echo.
    echo "rc=$?" >>"${T}/out"; cat "${T}/out"
}

applies() { [[ -f "${T}/applies" ]] && wc -l <"${T}/applies" || echo 0; }

echo "== the control: every apply succeeds, so the shims are not what fails the run =="
out="$(run_process '')"
check "instructors up exits 0 when every apply succeeds" 'grep -qx "rc=0" <<<"$out"'
check "and both roster clusters were applied" '[[ "$(applies)" -eq 2 ]]'

echo "== every selected cluster's apply fails, no tail (the 2026-10-24 bring-up) =="
out="$(run_process '.*')"
check "terraform apply ran, and failed, for both selected clusters" \
    '[[ "$(applies)" -eq 2 ]] && [[ "$(grep -c "FAILED: watch-it-burn-" <<<"$out")" -eq 2 ]]'
check "the run reports the failures" 'grep -q "2 cluster(s) FAILED:" <<<"$out"'
check "instructors up exits non-zero" 'grep -q "^rc=" <<<"$out" && ! grep -qx "rc=0" <<<"$out"'
check "and says the fleet is not up" 'grep -q "the fleet is NOT up" <<<"$out"'

echo "== every apply fails, with a routes and verify tail that passes =="
out="$(run_with_tail '.*')"
check "the tail still ran" 'grep -q "routes ran" <<<"$out" && grep -q "verify ran" <<<"$out"'
check "and a passing verify does not turn the failed applies into success" \
    'grep -q "^rc=" <<<"$out" && ! grep -qx "rc=0" <<<"$out"'

echo "== one cluster's apply fails and the other builds =="
out="$(run_process 'community')"
check "the one failure is reported" \
    'grep -q "FAILED: watch-it-burn-community" <<<"$out" && grep -q "1 cluster(s) FAILED:" <<<"$out"'
check "instructors up exits non-zero" 'grep -q "^rc=" <<<"$out" && ! grep -qx "rc=0" <<<"$out"'
out="$(run_with_tail 'community')"
check "and still does with the tail running" 'grep -q "verify ran" <<<"$out" && ! grep -qx "rc=0" <<<"$out"'

echo "== the attendee path shares the build, and the contract =="
fresh
out="$( ( cd "$(dirname "${FLEET}")" && env "${env_common[@]}" WIB_NO_BOOTSTRAP=1 TF_APPLY_FAIL='.*' \
    bash "${FLEET}" up watch-it-burn-attendee-001 ) 2>&1; echo "rc=$?")"
check "up <name> exits non-zero when its apply fails" \
    'grep -q "FAILED: watch-it-burn-attendee-001" <<<"$out" && ! grep -qx "rc=0" <<<"$out"'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
