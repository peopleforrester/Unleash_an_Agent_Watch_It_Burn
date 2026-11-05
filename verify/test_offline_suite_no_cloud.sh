#!/usr/bin/env bash
# ABOUTME: The offline suite's no-cloud guard (#857): a test that calls aws, kubectl, eksctl, helm or terraform fails,
# ABOUTME: naming the call, and fleet.sh's unstubbed guardrails link (#616's stall) fails in seconds without reaching a cluster.
#
# Why. In run 16967 (#616) two offline tests ran `cmd_instructors up all` on event.sh's kubecon profile without
# stubbing cmd_guardrails_link. The `aws` on a dispatched run's PATH carries the run's live session, so the suite
# wrote real kubeconfigs for both KubeCon clusters and polled each for its guardrails-switch token for five minutes a
# call. verify/no-cloud.sh is the guard run-tests.sh puts round every test; this checks it holds, on the same
# no_cloud_run the runner calls, and that the runner calls it.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -t offline-no-cloud.XXXX)"; trap 'rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# A second layer of fakes behind the guard's stubs, so a guard that let a call through would land here and be
# reported, never on the real aws (#857's own hazard).
mkdir -p "${T}/backstop"
for t in aws kubectl eksctl helm terraform; do
    printf '#!/bin/sh\necho "%s $*" >>"%s/backstop-calls"\nexit 1\n' "${t}" "${T}" >"${T}/backstop/${t}"
    chmod +x "${T}/backstop/${t}"
done
export PATH="${T}/backstop:${PATH}"

# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${HERE}/no-cloud.sh"
no_cloud_setup "${T}/guard"
# Run one command through the guard; $out holds its output and $rc its exit code.
run() { rc=0; out="$(no_cloud_run "$@" 2>&1)" || rc=$?; }

echo "== the runner puts every offline test through the guard =="
RT="${HERE}/run-tests.sh"
check "run-tests.sh sources no-cloud.sh and sets the guard up before any test" \
  'grep -qF ". \"\${SCRIPT_DIR}/no-cloud.sh\"" "${RT}" && grep -qF "no_cloud_setup \"\${NO_CLOUD_DIR}\"" "${RT}"'
check "and run_one runs each test through no_cloud_run" \
  '[[ "$(sed -n "/^run_one() {/,/^}/p" "${RT}" | grep -c "no_cloud_run \"\${interp\[@\]}\" \"\$1\"")" -eq 1 ]]'
check "no_cloud_run refuses to run a test when the guard was never set up" \
  '! ( unset NO_CLOUD_BIN; no_cloud_run true ) 2>/dev/null'

echo "== a call to any cloud tool fails the test and names the call =="
for t in aws kubectl eksctl helm terraform; do
    run bash -c "${t} reach-the-cluster --name watch-it-burn-community"
    check "${t}: the test fails" '[[ "${rc}" -ne 0 ]]'
    check "${t}: and the call is named" 'grep -qF "${t} reach-the-cluster --name watch-it-burn-community" <<<"${out}"'
done
run bash -c 'aws sts get-caller-identity >/dev/null 2>&1 || true; exit 0'
check "a test that swallows the failed call and exits 0 still fails" '[[ "${rc}" -eq 1 ]] && grep -q "CALLED A CLOUD TOOL" <<<"${out}"'
run bash -c 'exit 3'
check "the log is emptied between tests, and a test's own exit code is kept" \
  '[[ "${rc}" -eq 3 ]] && ! grep -q "CALLED A CLOUD TOOL" <<<"${out}"'

echo "== a test that rebuilds its environment still reaches the stub =="
# PATH is read inside the test, where the guard has put its stubs first, as a test's own env -i would read it.
run bash -c 'env -i PATH="${PATH}" sh -c "kubectl get ns >/dev/null 2>&1; exit 0"'
check "env -i with PATH kept" '[[ "${rc}" -eq 1 ]] && grep -qF "kubectl get ns" <<<"${out}"'
run python3 -c 'import os, subprocess; subprocess.run(["aws", "eks", "list-clusters"], env={"PATH": os.environ["PATH"]}, capture_output=True)'
check "python subprocess with env= of PATH alone" '[[ "${rc}" -eq 1 ]] && grep -qF "aws eks list-clusters" <<<"${out}"'

echo "== a test with its own fake ahead of the stub is not flagged =="
mkdir -p "${T}/fake"
printf '#!/bin/sh\necho fake-aws "$@"\n' >"${T}/fake/aws"; chmod +x "${T}/fake/aws"
run bash -c "PATH='${T}/fake':\"\${PATH}\" aws eks update-kubeconfig"
check "a fake aws first on PATH answers and nothing is logged" \
  '[[ "${rc}" -eq 0 ]] && grep -q "^fake-aws eks update-kubeconfig" <<<"${out}" && ! grep -q "CALLED A CLOUD TOOL" <<<"${out}"'
run bash -c 'echo offline; exit 0'
check "a test that calls nothing passes" '[[ "${rc}" -eq 0 && "${out}" == offline ]]'

echo "== #616's shape: an unstubbed guardrails link under instructors up all =="
# What test_presenter_student_retired.sh and test_fleet_apply_failure_exit.sh ran before #616: the build stubbed,
# cmd_guardrails_link not, on the kubecon profile. Under the guard the link's first aws call fails, so it never
# reaches the token poll.
mkdir -p "${T}/states" "${T}/logs"
link616() { # $1: extra stubs
    ( cd "$(dirname "${FLEET}")" && WIB_ROSTER_PROFILES=kubecon WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" \
        timeout 120 bash -c "source '${FLEET}' >/dev/null 2>&1
            _provision_spec_fleet() { :; }; print_bootstrap_hints() { :; }; require_tools() { :; }; $1
            cmd_instructors up all" )
}
start="${SECONDS}"
run link616 ""
took=$((SECONDS - start))
check "it ends in seconds, not on the five-minute token poll (took ${took}s)" '[[ "${rc}" -ne 124 && "${took}" -lt 60 ]]'
check "the test fails" '[[ "${rc}" -ne 0 ]]'
check "and names the kubeconfig the link tried to write for the live community cluster" \
  'grep -E "^    aws eks update-kubeconfig .*--name watch-it-burn-community" <<<"${out}" >/dev/null'
run link616 "cmd_guardrails_link() { :; }"
check "with the link stubbed, as #616 left both tests, it passes" '[[ "${rc}" -eq 0 ]] && ! grep -q "CALLED A CLOUD TOOL" <<<"${out}"'

echo "== the tools tier stubs only the tools it pins no copy of (#865) =="
# run-e2e-tools.sh stubs aws and eksctl alone and puts them ahead of its pinned kubectl, helm and terraform, as
# tier_env's PATH does here with a fake pinned kubectl; a guard set up with named tools shadows none of the others.
mkdir -p "${T}/pinned"
printf '#!/bin/sh\necho "pinned kubectl $*" >>"%s/pinned-calls"\n' "${T}" >"${T}/pinned/kubectl"
chmod +x "${T}/pinned/kubectl"
no_cloud_setup "${T}/tier" aws eksctl
check "no_cloud_setup <dir> aws eksctl writes exactly those two stubs" \
  '[[ "$(ls "${NO_CLOUD_BIN}" | tr "\n" " ")" == "aws eksctl " ]]'
run env PATH="${NO_CLOUD_BIN}:${T}/pinned:${PATH}" bash -c "eksctl get cluster; kubectl version --client; exit 0"
check "a tier test's eksctl call fails it and is named" '[[ "${rc}" -eq 1 ]] && grep -qF "    eksctl get cluster" <<<"${out}"'
check "and its kubectl call reaches the pinned kubectl, unstubbed" \
  'grep -qxF "pinned kubectl version --client" "${T}/pinned-calls" && ! grep -qF "    kubectl" <<<"${out}"'

echo "== offline means offline =="
check "nothing got past the guard's stubs to the backstop behind them" \
  '[[ ! -s "${T}/backstop-calls" ]] || { sed "s/^/        /" "${T}/backstop-calls"; false; }'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
