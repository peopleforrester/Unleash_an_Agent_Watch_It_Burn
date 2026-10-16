#!/usr/bin/env bash
# ABOUTME: Offline render-gate suite — runs every no-cluster check in verify/ for the build.
# ABOUTME: Green here is the buildable-without-a-cluster bar; checks needing kubectl, helm or a cluster are in run-e2e.sh.
#
# The test list is DISCOVERED, never written down. It used to be one long hand-maintained line of
# filenames, and on 2026-09-03 a commit that deleted test_origin_guard.py deleted that whole line with it.
# The suite stopped parsing, and stayed broken for four days without anybody noticing, because the only
# thing that reports the suite is broken is the suite. A hardcoded list also silently omitted every test
# added after it was written: eleven of them by the time this was found.
#
# The split is by need, decided in the test file and not at run time. A test that needs kubectl, helm, a
# credential or a cluster carries a `# SUITE: e2e` line and belongs to run-e2e.sh, which fails when what
# it needs is missing. Everything else runs here and must pass on any machine with python3, PyYAML, bash
# and git. There is no skip: a check that could quietly skip here went green on machines that never ran
# it, which is the same failure as a suite that runs nothing.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "${SCRIPT_DIR}/ensure-submodules.sh"

fail=0
ran=0
failed_names=()
e2e_names=()

run_one() {
    local name interp rc
    name="$(basename "$1")"
    case "${name}" in
        *.py) interp=(python3) ;;
        *)    interp=(bash) ;;
    esac
    printf '\n== %s ==\n' "${name}"
    ran=$((ran + 1))
    rc=0
    "${interp[@]}" "$1" || rc=$?
    # Any non-zero exit fails, 2 included: bash exits 2 on a syntax or usage error, and that is not a pass.
    [[ "${rc}" -eq 0 ]] || { fail=1; failed_names+=("${name} (exit ${rc})"); }
}

# Both suffixes: the shell checks (fleet naming, exit codes, teardown hooks) are as offline as the Python
# ones and were never in the old list at all.
for t in "${SCRIPT_DIR}"/test_*.py "${SCRIPT_DIR}"/test_*.sh; do
    [[ -e "${t}" ]] || continue
    if grep -q '^# SUITE: e2e' "${t}"; then
        e2e_names+=("$(basename "${t}")")
        continue
    fi
    run_one "${t}"
done

printf '\n%d tests ran\n' "${ran}"
if [[ "${#e2e_names[@]}" -gt 0 ]]; then
    printf '  in the E2E suite instead (bash verify/run-e2e.sh): %s\n' "${e2e_names[*]}"
fi
# A glob that matches nothing is the failure mode this replaces: a runner that exits 0 having done nothing
# looks exactly like a passing build.
if [[ "${ran}" -eq 0 ]]; then
    printf 'NO TESTS FOUND in %s — the suite is not running\n' "${SCRIPT_DIR}" >&2
    exit 1
fi
if [[ "${fail}" -eq 0 ]]; then
    printf '\nALL OFFLINE RENDER-GATE TESTS GREEN\n'
else
    printf '\nSOME TESTS FAILED:\n' >&2
    printf '  %s\n' "${failed_names[@]}" >&2
    exit 1
fi
