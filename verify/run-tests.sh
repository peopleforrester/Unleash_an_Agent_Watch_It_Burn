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
# Scratch goes under TMPDIR, else the checkout's ignored tmp/, never the system's temp directory, which on netcup
# is a tmpfs, so what a test leaves there is RAM (#1261). Every mktemp and Python tempfile below inherits it.
if [[ -z "${TMPDIR:-}" ]]; then
    TMPDIR="$(cd "${SCRIPT_DIR}/.." && pwd)/tmp"  # tmp-ok: the checkout's own tmp/, not the system one
    mkdir -p "${TMPDIR}"
fi
export TMPDIR

bash "${SCRIPT_DIR}/ensure-submodules.sh"

# No offline test reaches a cluster or an AWS account (#857): each runs with aws, kubectl, eksctl, helm and terraform
# stubbed first on PATH, and one that calls a stub fails, naming the call. See no-cloud.sh for why.
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${SCRIPT_DIR}/no-cloud.sh"
NO_CLOUD_DIR="$(mktemp -d)"
trap 'rm -rf "${NO_CLOUD_DIR}"' EXIT
no_cloud_setup "${NO_CLOUD_DIR}"

# Scoped to the change (#1018). With HECATON_BASE_SHA set, as hecaton's gate and CI set it, scope_tests.py reads
# the change against that base and verify/scope-map.yaml, the committed map of each test to the repo paths it reads,
# and names the tests the change can affect, each with why, or says to run them all: a change to a runner, the map
# or a shared helper, or to a path no entry covers. Without it, a person running this by hand, every test runs.
#
# Hecaton names the files itself (#1319, hecaton#623). AGENTS.md declares the suite's `Test files:` globs and the
# `Test map:` (verify/test-map.yaml, which scope_tests.py writes from the scope map), so the tests gate works out which
# of them read the change and passes them in HECATON_TEST_FILES, one repo path per line. When that is set and not
# empty, this runs exactly those files and does not ask scope_tests.py: the gate's `ran N of M test files` is then
# what ran. A listed file must be a verify/test_*.py or verify/test_*.sh that exists: a wrong name fails, never
# skips. A listed `# SUITE: e2e` file is set aside, as the glob sets it aside, and a list of only those runs nothing.
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
listed=()
declare -A seen_listed=()
if [[ -n "${HECATON_TEST_FILES:-}" ]]; then
    mapfile -t raw_listed <<<"${HECATON_TEST_FILES}"
    for t in "${raw_listed[@]}"; do
        t="${t#"${t%%[![:space:]]*}"}"
        t="${t%"${t##*[![:space:]]}"}"
        [[ -n "${t}" && -z "${seen_listed[${t}]:-}" ]] || continue
        seen_listed["${t}"]=1
        listed+=("${t}")
    done
fi
bad_listed=()
for t in "${listed[@]}"; do
    [[ "${t}" =~ ^verify/test_[^/]+\.(py|sh)$ && -f "${REPO_DIR}/${t}" ]] || bad_listed+=("${t}")
done
if [[ "${#bad_listed[@]}" -gt 0 ]]; then
    printf 'HECATON_TEST_FILES names %d paths that are not test files of this suite (verify/test_*.py or verify/test_*.sh, present in %s):\n' \
        "${#bad_listed[@]}" "${REPO_DIR}" >&2
    printf '  %q\n' "${bad_listed[@]}" >&2
    exit 1
fi

scoped=0
declare -A selected=()
if [[ "${#listed[@]}" -gt 0 ]]; then
    : # the listed files are the run; scope_tests.py is not asked
elif [[ -n "${HECATON_BASE_SHA:-}" ]]; then
    plan="$(python3 "${SCRIPT_DIR}/scope_tests.py" select offline)" \
        || { printf 'SCOPE FAILED: scope_tests.py could not read the change against HECATON_BASE_SHA=%s\n' \
                 "${HECATON_BASE_SHA}" >&2; exit 1; }
    mapfile -t plan_lines <<<"${plan}"
    case "${plan_lines[0]}" in
        FULL) ;;
        SCOPED)
            scoped=1
            for t in "${plan_lines[@]:1}"; do
                [[ -n "${t}" ]] && selected["${t}"]=1
            done
            ;;
        *) printf 'SCOPE FAILED: scope_tests.py printed %q, neither FULL nor SCOPED\n' "${plan_lines[0]}" >&2; exit 1 ;;
    esac
fi
# The tests get no HECATON_BASE_SHA: one that drives a runner in a fixture means that runner to run whole.
# Nor HECATON_TEST_FILES, for the same reason.
scope_base="${HECATON_BASE_SHA:-}"
unset HECATON_BASE_SHA HECATON_TEST_FILES

fail=0
ran=0
found=0
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
    local started="${SECONDS}"
    no_cloud_run "${interp[@]}" "$1" || rc=$?
    # Any non-zero exit fails, 2 included: bash exits 2 on a syntax or usage error, and that is not a pass.
    [[ "${rc}" -eq 0 ]] || { fail=1; failed_names+=("${name} (exit ${rc})"); }
    # Each test's seconds, so the E2E command's hour can be read test by test (#1005).
    printf -- '-- %s took %ds\n' "${name}" "$((SECONDS - started))"
}

# Both suffixes: the shell checks (fleet naming, exit codes, teardown hooks) are as offline as the Python
# ones and were never in the old list at all.
if [[ "${#listed[@]}" -gt 0 ]]; then
    candidates=()
    for t in "${listed[@]}"; do candidates+=("${REPO_DIR}/${t}"); done
else
    candidates=("${SCRIPT_DIR}"/test_*.py "${SCRIPT_DIR}"/test_*.sh)
fi
for t in "${candidates[@]}"; do
    [[ -e "${t}" ]] || continue
    if grep -q '^# SUITE: e2e' "${t}"; then
        e2e_names+=("$(basename "${t}")")
        continue
    fi
    found=$((found + 1))
    [[ "${scoped}" -eq 0 || -n "${selected[$(basename "${t}")]:-}" ]] || continue
    run_one "${t}"
done

printf '\n%d tests ran\n' "${ran}"
if [[ "${#listed[@]}" -gt 0 ]]; then
    printf '  the files HECATON_TEST_FILES names (#1319): %d listed, %d of them offline tests, all of which ran\n' \
        "${#listed[@]}" "${found}"
fi
if [[ "${scoped}" -eq 1 ]]; then
    printf '  scoped to the change since HECATON_BASE_SHA=%s: %d of the %d offline tests; the other %d read nothing it touched\n' \
        "${scope_base}" "${ran}" "${found}" "$((found - ran))"
fi
if [[ "${#e2e_names[@]}" -gt 0 ]]; then
    printf '  in the E2E suite instead (bash verify/run-e2e.sh): %s\n' "${e2e_names[*]}"
fi
# A glob that matches nothing is the failure mode this replaces: a runner that exits 0 having done nothing
# looks exactly like a passing build.
# With HECATON_TEST_FILES set, the gate chose the files, and a list of e2e files alone rightly runs none.
if [[ "${found}" -eq 0 && "${#listed[@]}" -eq 0 ]]; then
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
