#!/usr/bin/env bash
# ABOUTME: Offline render-gate suite: runs every no-cluster check in verify/ for the build, through offline-suite.sh.
# ABOUTME: Green here is the buildable-without-a-cluster bar; checks needing kubectl, helm or a cluster are in run-e2e.sh.
#
# This is the command people, CI and the E2E command run. It scopes the suite to the change and hands the run to
# offline-suite.sh, which finds the tests, sets the `# SUITE: e2e` ones aside and runs each under no_cloud_run.
# offline-suite.sh is also hecaton's declared Test command, apart from this file because this one spells
# scope_tests.py, whose map names nearly every path in the repo: see the head of offline-suite.sh (#1319).
#
# Scoped to the change (#1018). With HECATON_BASE_SHA set, as CI and the E2E command set it, scope_tests.py reads the
# change against that base and verify/scope-map.yaml, the committed map of each test to the repo paths it reads, and
# names the tests the change can affect, each with why, or says to run them all: a change to a runner, the map or a
# shared helper, or to a path no entry covers. The names go to offline-suite.sh in OFFLINE_SUITE_SCOPE. Without the
# variable, a person running this by hand, every test runs.
#
# HECATON_TEST_FILES, the list hecaton's tests gate passes (hecaton#623), wins over the scoping: with it set and not
# blank, scope_tests.py is not asked and offline-suite.sh runs exactly the files listed.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Scratch goes under TMPDIR, else the checkout's ignored tmp/, never the system's temp directory, which on netcup
# is a tmpfs, so what a test leaves there is RAM (#1261). scope_tests.py and offline-suite.sh inherit it.
if [[ -z "${TMPDIR:-}" ]]; then
    TMPDIR="$(cd "${SCRIPT_DIR}/.." && pwd)/tmp"  # tmp-ok: the checkout's own tmp/, not the system one
    mkdir -p "${TMPDIR}"
fi
export TMPDIR

# OFFLINE_SUITE_SCOPE carries this file's scoping to offline-suite.sh, and only what is decided here sets it.
unset OFFLINE_SUITE_SCOPE
listed="${HECATON_TEST_FILES:-}"
if [[ -z "${listed//[[:space:]]/}" && -n "${HECATON_BASE_SHA:-}" ]]; then
    plan="$(python3 "${SCRIPT_DIR}/scope_tests.py" select offline)" \
        || { printf 'SCOPE FAILED: scope_tests.py could not read the change against HECATON_BASE_SHA=%s\n' \
                 "${HECATON_BASE_SHA}" >&2; exit 1; }
    mapfile -t plan_lines <<<"${plan}"
    case "${plan_lines[0]}" in
        FULL) ;;
        SCOPED)
            OFFLINE_SUITE_SCOPE=""
            for t in "${plan_lines[@]:1}"; do
                [[ -n "${t}" ]] && OFFLINE_SUITE_SCOPE+="${t}"$'\n'
            done
            export OFFLINE_SUITE_SCOPE
            ;;
        *) printf 'SCOPE FAILED: scope_tests.py printed %q, neither FULL nor SCOPED\n' "${plan_lines[0]}" >&2; exit 1 ;;
    esac
fi

exec bash "${SCRIPT_DIR}/offline-suite.sh"
