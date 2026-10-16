#!/usr/bin/env bash
# ABOUTME: Offline render-gate suite — runs every no-cluster check in verify/ for the build.
# ABOUTME: Green here is the buildable-without-a-cluster bar; live cluster assertions are in run-all.sh.
#
# The test list is DISCOVERED, never written down. It used to be one long hand-maintained line of
# filenames, and on 2026-09-03 a commit that deleted test_origin_guard.py deleted that whole line with it.
# The suite stopped parsing, and stayed broken for four days without anybody noticing, because the only
# thing that reports the suite is broken is the suite. A hardcoded list also silently omitted every test
# added after it was written: eleven of them by the time this was found.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# A dozen checks read gitops/ai-layer/guard-proxy/proxy.py, which lives in a submodule. A fresh clone
# has the submodule directories empty, and every one of those checks then dies on a missing file. Check
# them out here, not in the caller, so `bash verify/run-tests.sh` is the whole command: the hecaton gate
# runs it without a shell, so a `git submodule update --init && ...` prefix never worked there.
if [[ -d "${REPO_DIR}/.git" || -f "${REPO_DIR}/.git" ]] \
    && git -C "${REPO_DIR}" submodule status | grep -q '^-'; then
    printf 'initialising submodules\n'
    git -C "${REPO_DIR}" submodule update --init \
        || { printf 'FAILED to initialise submodules; the guard-proxy checks cannot run\n' >&2; exit 1; }
fi

fail=0
ran=0
failed_names=()

skipped=0
skipped_names=()

# Exit 2 is SKIP, per the repo's shell convention: a check that needs a credential, a cluster or a tool
# (kubectl, helm) this machine does not have is not a failing check. It is still reported, so a suite that skips everything
# cannot be mistaken for a suite that passed everything.
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
    case "${rc}" in
        0) ;;
        2) skipped=$((skipped + 1)); skipped_names+=("${name}") ;;
        *) fail=1; failed_names+=("${name}") ;;
    esac
}

# Both suffixes: the shell checks (fleet naming, exit codes, teardown hooks) are as offline as the Python
# ones and were never in the old list at all.
for t in "${SCRIPT_DIR}"/test_*.py "${SCRIPT_DIR}"/test_*.sh; do
    [[ -e "${t}" ]] || continue
    run_one "${t}"
done

printf '\n%d tests ran, %d skipped\n' "${ran}" "${skipped}"
if [[ "${skipped}" -gt 0 ]]; then
    printf '  skipped (needs a credential, a cluster or a tool): %s\n' "${skipped_names[*]}"
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
