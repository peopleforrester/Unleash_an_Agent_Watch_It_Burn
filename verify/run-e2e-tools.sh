#!/usr/bin/env bash
# ABOUTME: The gate's E2E command (#572): the offline suite and every `# E2E TIER: tools` check, run with pinned,
# ABOUTME: checksum-verified binaries fetched into verify/.tools. Needs network; never a cluster, CONTEXT or AWS.
#
# Usage: bash verify/run-e2e-tools.sh
#
# Hecaton's promotion gate runs the declared `E2E command:` instead of the `Test command:`, on a host with no
# attendee cluster, no AWS profile and none of the cluster tools (#543). This is the part of the E2E suite that
# host can run: Kyverno CLI policy evaluation, conftest on the IAM plans, terraform init against the locks,
# kustomize and Helm renders, the node harnesses, Playwright renders and the llm-guard scanner. What a test
# needs beyond the binaries in e2e-tools.lock comes pinned through uv (playwright, llm-guard, segno).
#
# A test joins the tier with a `# E2E TIER: tools` line next to its `# SUITE: e2e` line, so run-tests.sh still
# leaves it out and run-e2e.sh still runs it on a cluster build. verify/test_e2e_tools_tier.py holds that no
# tier test reads CONTEXT or IAM_PIPELINE_*. Each one runs with those unset and KUBECONFIG=/dev/null, so a test
# that started to need a cluster or AWS fails here instead of reaching one. aws and eksctl, which the tier pins no
# copy of, are stubbed first on PATH by no-cloud.sh (#865): on a dispatched run the aws on PATH is hecaton's wrapper,
# which exports the run's live session whatever the environment holds, so unsetting AWS_PROFILE alone would not stop a
# call reaching the two live clusters. A tier test that calls either one fails, naming the call.
#
# Checks run E2E_TOOLS_JOBS at a time (default 4), the offline suite as one of them, each with its output in a log of
# its own that is printed whole when it ends; one after another they took more than the gate's hour (#1005). The tests
# marked `# E2E SERIAL: terraform` share the provider cache and run one at a time. Each check's seconds are printed
# after it and the ten slowest at the end. Stopped by a signal, the runner names each check still running, with its
# last lines, and stops it.
#
# Nothing here skips. A missing prerequisite or a failed fetch exits 1 before any test runs, with every reason.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_BIN="${SCRIPT_DIR}/.tools/bin"

# Scoped to the change (#1018), as run-tests.sh is: with HECATON_BASE_SHA set, a tier test runs only when the change
# touches what it reads (verify/scope-map.yaml), and when none does, the tools are neither checked for nor fetched.
# Without it every tier test runs. The offline suite below inherits the variable and scopes itself the same way.
scoped=0
declare -A selected=()
if [[ -n "${HECATON_BASE_SHA:-}" ]]; then
    command -v python3 >/dev/null 2>&1 || { printf 'SCOPE FAILED: python3 is not on PATH\n' >&2; exit 1; }
    plan="$(python3 "${SCRIPT_DIR}/scope_tests.py" select tools)" \
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
need_tools=1
if [[ "${scoped}" -eq 1 && "${#selected[@]}" -eq 0 ]]; then
    need_tools=0
    printf 'scope: no tier test reads what the change touched, so the tools are neither checked for nor fetched\n'
fi

missing=()
# curl, tar, python3 (zipfile, #1047) and sha256sum fetch and verify the tools, and xz unpacks weaver's archive; uv brings the Python
# pins; openssl mints the Kyverno test's wrong key; jq runs test_ai_layer_rollout.py's filters; node runs the harnesses.
# flock holds the shared Terraform provider cache for one terraform test at a time (#1114).
tools=(python3 git)
[[ "${need_tools}" -eq 0 ]] || tools+=(curl tar sha256sum xz uv node jq openssl flock)
for tool in "${tools[@]}"; do
    if command -v "${tool}" >/dev/null 2>&1; then
        continue
    elif [[ "${tool}" == node ]]; then
        missing+=("node is not on PATH; install the current Node.js release (nodejs.org) for the node harnesses")
    else
        missing+=("${tool} is not on PATH")
    fi
done
# The node harnesses run on the Node on PATH (#1200). Node 24 is the oldest they have been run on (#572) and 26 the
# newest, so only a major below 24 is refused; CI installs the current one.
if [[ "${need_tools}" -eq 1 ]] && command -v node >/dev/null 2>&1; then
    node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)"
    if ! [[ "${node_major}" =~ ^[0-9]+$ ]] || (( node_major < 24 )); then
        missing+=("node $(node --version 2>/dev/null) is on PATH; the node harnesses run on Node 24 or later")
    fi
fi
# The Playwright tests' browsers, checked once (#658). `playwright install` locks the browsers directory even when
# nothing is missing, and where that directory is not writable it retries for about 8 minutes per test before it fails.
if [[ "${need_tools}" -eq 1 ]] && command -v uv >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
    if ! pw="$(python3 "${SCRIPT_DIR}/playwright_browsers.py" 2>&1)"; then
        while IFS= read -r line; do
            [[ -n "${line}" ]] && missing+=("${line}")
        done <<<"${pw}"
        [[ -n "${pw}" ]] || missing+=("verify/playwright_browsers.py failed without saying why")
    fi
fi
# How many checks run at once (#1005), and the bash that can wait on whichever ends first (`wait -n -p`, bash 5.1).
JOBS="${E2E_TOOLS_JOBS:-4}"
[[ "${JOBS}" =~ ^[1-9][0-9]*$ ]] || missing+=("E2E_TOOLS_JOBS is '${JOBS}', not a whole number of 1 or more")
(( BASH_VERSINFO[0] > 5 || (BASH_VERSINFO[0] == 5 && BASH_VERSINFO[1] >= 1) )) \
    || missing+=("bash ${BASH_VERSION} runs this; the tier needs bash 5.1 or later")
if [[ "${#missing[@]}" -gt 0 ]]; then
    printf 'E2E TOOLS TIER CANNOT RUN; this is a failure, not a skip:\n' >&2
    printf '  - %s\n' "${missing[@]}" >&2
    exit 1
fi
if [[ "${need_tools}" -eq 1 ]] && ! bash "${SCRIPT_DIR}/fetch-e2e-tools.sh"; then
    printf 'E2E TOOLS TIER CANNOT RUN; this is a failure, not a skip: the pinned tools could not be fetched\n' >&2
    exit 1
fi

bash "${SCRIPT_DIR}/ensure-submodules.sh"

fail=0
ran=0
failed_names=()
timings=()

# The pinned tools come first on PATH, and the six tests that take a path get it, so a tool already on the
# host is never what a check runs. Ahead of them stand only the aws and eksctl stubs (#865), which shadow no pinned tool.
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${SCRIPT_DIR}/no-cloud.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT
# Terraform's providers come from the host artifact cache, outside every worktree (#1114, #1119). Each terraform test
# gets them through tf_plugin_cache.terraform_env: a filesystem mirror filled through artifact_cache.get() by each
# lock's zh: SHA-256, which terraform installs from and never downloads past, and the plugin cache beside it in the
# same root, <root>/terraform-plugin-cache, which tf_plugin_cache.py names here and fails on when it is unusable. In
# verify/.tools it started cold in every new checkout, and the lock-init test spent 326 s downloading the same
# providers again. Terraform does not promise a cache is safe to write from two processes at once, so the tests marked
# `# E2E SERIAL: terraform` run one at a time here (#572, #1005), and each holds TF_CACHE_LOCK while it runs, so a run
# in another checkout that shares the cache waits its turn. A wait past TF_CACHE_LOCK_WAIT seconds fails the check,
# naming the lock.
TF_CACHE="$(python3 "${SCRIPT_DIR}/tf_plugin_cache.py")" || {
    printf 'E2E TOOLS TIER CANNOT RUN; this is a failure, not a skip: no usable Terraform provider cache\n' >&2
    exit 1
}
TF_CACHE_LOCK="${TF_CACHE}.lock"
TF_CACHE_LOCK_WAIT="${TF_CACHE_LOCK_WAIT:-1800}"
printf 'Terraform provider cache: %s\n' "${TF_CACHE}"

check_job() { # $1: the check's own directory, $2: "offline" or a tier test
    local dir="$1" t="$2"
    if [[ "${t}" == offline ]]; then
        bash "${SCRIPT_DIR}/run-tests.sh"
        return
    fi
    # Each check gets aws and eksctl stubs and a call log of its own, so a cloud call is named under the check that
    # made it while others run beside it (#865).
    no_cloud_setup "${dir}/no-cloud" aws eksctl
    # Helm reads its repository list, index cache and plugins from the user's home unless told otherwise, and a
    # `helm pull --repo` or `helm template --repo` loads every repository listed there. In run 17641 that home listed a
    # `cilium` repository whose cached index was gone, and every chart fetch in six tier tests failed on it. Each check
    # gets an empty Helm home of its own, so no two write one index cache, removed when the runner exits.
    local helm="${dir}/helm"
    mkdir -p "${helm}/config" "${helm}/cache" "${helm}/data"
    # PYTHONUNBUFFERED: a Python test writes each line as it prints it, so a check stopped part way shows how far it got.
    # Into the gate's pipe its output was block-buffered, and when the gate's hour ran out in test_trace_shape_e2e.py its
    # tail held the test's heading and nothing after (#1005).
    local -a tier_env=(env -u HECATON_BASE_SHA -u TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE -u CONTEXT -u IAM_PIPELINE_PROFILE -u IAM_PIPELINE_REGION -u AWS_PROFILE
        -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN
        KUBECONFIG=/dev/null PATH="${NO_CLOUD_BIN}:${TOOLS_BIN}:${PATH}" TF_PLUGIN_CACHE_DIR="${TF_CACHE}" PYTHONUNBUFFERED=1
        KYVERNO_CLI="${TOOLS_BIN}/kyverno" CONFTEST="${TOOLS_BIN}/conftest" TERRAFORM="${TOOLS_BIN}/terraform"
        OTELCOL_CONTRIB="${TOOLS_BIN}/otelcol-contrib" TTYD="${TOOLS_BIN}/ttyd" CRANE="${TOOLS_BIN}/crane"
        AGENTGATEWAY="${TOOLS_BIN}/agentgateway" HELM_CONFIG_HOME="${helm}/config"
        HELM_CACHE_HOME="${helm}/cache" HELM_DATA_HOME="${helm}/data")
    local -a run=(python3)
    [[ "${t}" == *.py ]] || run=(bash)
    if ! grep -q '^# E2E SERIAL: terraform' "${t}"; then
        no_cloud_run "${tier_env[@]}" "${run[@]}" "${t}"
        return
    fi
    # check_job runs in a subshell of its own, so the lock is this check's and goes when the subshell ends.
    local lock_fd
    exec {lock_fd}>>"${TF_CACHE_LOCK}"
    if ! flock -w "${TF_CACHE_LOCK_WAIT}" "${lock_fd}"; then
        printf 'FAIL: %s was held by another run for %ss, so the shared provider cache was never free\n' \
            "${TF_CACHE_LOCK}" "${TF_CACHE_LOCK_WAIT}"
        return 1
    fi
    no_cloud_run "${tier_env[@]}" "${run[@]}" "${t}"
}

# The gate runs this in place of the Test command, so main stays gated on the offline suite as well. It goes first in
# the queue, then the terraform tests, which run one at a time, then the rest of the tier.
queue=(offline)
serial=("")
labels=("run-tests.sh (the offline suite)")
tier=0
tier_found=0
later=()
for t in "${SCRIPT_DIR}"/test_*.py "${SCRIPT_DIR}"/test_*.sh; do
    [[ -e "${t}" ]] && grep -q '^# E2E TIER: tools' "${t}" || continue
    tier_found=$((tier_found + 1))
    [[ "${scoped}" -eq 0 || -n "${selected[$(basename "${t}")]:-}" ]] || continue
    tier=$((tier + 1))
    if grep -q '^# E2E SERIAL: terraform' "${t}"; then
        queue+=("${t}"); serial+=(terraform); labels+=("$(basename "${t}")")
    else
        later+=("${t}")
    fi
done
for t in "${later[@]}"; do
    queue+=("${t}"); serial+=(""); labels+=("$(basename "${t}")")
done
# A tier that matched nothing would pass having proved nothing.
if [[ "${tier_found}" -eq 0 ]]; then
    printf 'NO `# E2E TIER: tools` TESTS FOUND in %s; the tier is not running\n' "${SCRIPT_DIR}" >&2
    exit 1
fi

# Run one after another, the offline suite and the tier took more than the gate's hour on staging 629c53ea (#1005).
# E2E_TOOLS_JOBS checks run at once, each with its output in a log of its own, printed whole when it ends, so no two
# checks' lines are mixed.
declare -A job_index=() job_start=()
terraform_busy=""

start_job() { # $1: the check's place in the queue
    local i="$1" dir="${WORK_DIR}/$1"
    mkdir -p "${dir}"
    check_job "${dir}" "${queue[$i]}" >"${dir}/log" 2>&1 &
    job_index[$!]="${i}"
    job_start[$!]="${SECONDS}"
    [[ -z "${serial[$i]}" ]] || terraform_busy="$!"
}

finish_job() { # $1: the check's pid, $2: its exit code
    local pid="$1" rc="$2" i="${job_index[$1]}" took=$((SECONDS - job_start[$1]))
    local label="${labels[$i]}"
    printf '\n== %s ==\n' "${label}"
    cat "${WORK_DIR}/${i}/log"
    ran=$((ran + 1))
    [[ "${rc}" -eq 0 ]] || { fail=1; failed_names+=("${label} (exit ${rc})"); }
    # Each check's seconds, so a gate that runs out of time shows in its tail where the time went (#1005).
    printf -- '-- %s took %ds\n' "${label}" "${took}"
    timings+=("${took} ${label}")
    [[ "${terraform_busy}" != "${pid}" ]] || terraform_busy=""
    unset 'job_index[$pid]' 'job_start[$pid]'
    rm -rf "${WORK_DIR:?}/${i}"
}

slowest() {
    [[ "${#timings[@]}" -gt 0 ]] || return 0
    printf '%s\n' "${timings[@]}" | sort -rn | head -n 10 | awk '{ t = $1; $1 = ""; printf "  %4ds %s\n", t, substr($0, 2) }'
}

descendants() { # every process under $1, deepest first
    local child
    for child in $(ps -o pid= --ppid "$1" 2>/dev/null); do
        descendants "${child}"
        printf '%s\n' "${child}"
    done
}

# Stopped by a signal (the gate's timeout interrupts, then terminates): name each check still running, how long it
# had run and the last lines it wrote, then stop it and what it started.
stopped() {
    trap - INT TERM
    local pid i
    printf '\nThe slowest checks that ended:\n'
    slowest
    printf '\nSTOPPED by a signal after %dm%02ds, %d of %d checks ended, these still running:\n' \
        "$((SECONDS / 60))" "$((SECONDS % 60))" "${ran}" "${#queue[@]}"
    for pid in "${!job_index[@]}"; do
        i="${job_index[${pid}]}"
        printf '  %s, for %ds; its last lines:\n' "${labels[$i]}" "$((SECONDS - job_start[${pid}]))"
        tail -n 5 "${WORK_DIR}/${i}/log" 2>/dev/null | sed 's/^/      /'
        kill $(descendants "${pid}") "${pid}" 2>/dev/null || true
    done
    [[ "${#failed_names[@]}" -eq 0 ]] || printf 'Failed before the stop:\n%s\n' "$(printf '  %s\n' "${failed_names[@]}")"
    exit 1
}
trap stopped INT TERM

pending=("${!queue[@]}")
while [[ "${#pending[@]}" -gt 0 || "${#job_index[@]}" -gt 0 ]]; do
    rest=()
    for i in "${pending[@]}"; do
        if [[ "${#job_index[@]}" -lt "${JOBS}" ]] && [[ -z "${serial[$i]}" || -z "${terraform_busy}" ]]; then
            start_job "${i}"
        else
            rest+=("${i}")
        fi
    done
    pending=("${rest[@]}")
    rc=0
    wait -n -p done_pid "${!job_index[@]}" || rc=$?
    finish_job "${done_pid}" "${rc}"
done

# The time taken, since a run waits on this in the background and sets its limit from it (#796).
printf '\nThe slowest checks:\n'
slowest
# The line keeps the shape the suite records in decisions.md quote and test_952_suite_record.py reads; the job count
# follows it.
printf '\n%d checks ran (the offline suite and %d tier tests) in %dm%02ds, %d at a time\n' "${ran}" "${tier}" \
    "$((SECONDS / 60))" "$((SECONDS % 60))" "${JOBS}"
if [[ "${scoped}" -eq 1 ]]; then
    printf '  scoped to the change since HECATON_BASE_SHA=%s: %d of the %d tier tests; the other %d read nothing it touched\n' \
        "${HECATON_BASE_SHA}" "${tier}" "${tier_found}" "$((tier_found - tier))"
fi
if [[ "${fail}" -eq 0 ]]; then
    printf '\nALL E2E TOOLS TIER CHECKS GREEN\n'
else
    printf '\nSOME E2E TOOLS TIER CHECKS FAILED:\n' >&2
    printf '  %s\n' "${failed_names[@]}" >&2
    exit 1
fi
