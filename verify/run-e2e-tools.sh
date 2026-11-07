#!/usr/bin/env bash
# ABOUTME: The gate's E2E command (#572): the offline suite, then every `# E2E TIER: tools` check, run with pinned,
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
# curl, tar, unzip and sha256sum fetch and verify the tools, and xz unpacks weaver's archive; uv brings the Python
# pins; openssl mints the Kyverno test's wrong key; jq runs test_ai_layer_rollout.py's filters; node runs the harnesses.
tools=(python3 git)
[[ "${need_tools}" -eq 0 ]] || tools+=(curl tar unzip sha256sum xz uv node jq openssl)
for tool in "${tools[@]}"; do
    command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool} is not on PATH")
done
# The same Node major as run-e2e.sh and the Backstage image (#440).
if [[ "${need_tools}" -eq 1 ]] && command -v node >/dev/null 2>&1 && [[ "$(node -p 'process.versions.node.split(".")[0]')" != "24" ]]; then
    missing+=("node $(node --version) is on PATH; the node harnesses run on Node 24")
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

run_one() { # $1: label, rest: command
    local label="$1" rc=0
    shift
    printf '\n== %s ==\n' "${label}"
    ran=$((ran + 1))
    "$@" || rc=$?
    [[ "${rc}" -eq 0 ]] || { fail=1; failed_names+=("${label} (exit ${rc})"); }
}

# The gate runs this in place of the Test command, so main stays gated on the offline suite as well.
run_one "run-tests.sh (the offline suite)" bash "${SCRIPT_DIR}/run-tests.sh"

# The pinned tools come first on PATH, and the six tests that take a path get it, so a tool already on the
# host is never what a check runs. Ahead of them stand only the aws and eksctl stubs (#865), which shadow no pinned tool.
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${SCRIPT_DIR}/no-cloud.sh"
NO_CLOUD_DIR="$(mktemp -d)"
trap 'rm -rf "${NO_CLOUD_DIR}"' EXIT
no_cloud_setup "${NO_CLOUD_DIR}" aws eksctl
# Helm reads its repository list, index cache and plugins from the user's home unless told otherwise, and a
# `helm pull --repo` or `helm template --repo` loads every repository listed there. In run 17641 that home listed a
# `cilium` repository whose cached index was gone, and every chart fetch in six tier tests failed on it. Each run
# gets an empty Helm home of its own, removed with the stubs.
HELM_HOME="${NO_CLOUD_DIR}/helm"
mkdir -p "${HELM_HOME}/config" "${HELM_HOME}/cache" "${HELM_HOME}/data"
# The Terraform provider cache outlives each test, so the ~800 MB aws provider downloads once per checkout, not once
# per test process; the tests run one after another, so nothing writes to it concurrently (#572).
TF_CACHE="${SCRIPT_DIR}/.tools/plugin-cache"
mkdir -p "${TF_CACHE}"
tier_env=(env -u HECATON_BASE_SHA -u CONTEXT -u IAM_PIPELINE_PROFILE -u IAM_PIPELINE_REGION -u AWS_PROFILE
    -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN
    KUBECONFIG=/dev/null PATH="${NO_CLOUD_BIN}:${TOOLS_BIN}:${PATH}" TF_PLUGIN_CACHE_DIR="${TF_CACHE}"
    KYVERNO_CLI="${TOOLS_BIN}/kyverno" CONFTEST="${TOOLS_BIN}/conftest" TERRAFORM="${TOOLS_BIN}/terraform"
    OTELCOL_CONTRIB="${TOOLS_BIN}/otelcol-contrib" TTYD="${TOOLS_BIN}/ttyd" CRANE="${TOOLS_BIN}/crane"
    AGENTGATEWAY="${TOOLS_BIN}/agentgateway" HELM_CONFIG_HOME="${HELM_HOME}/config"
    HELM_CACHE_HOME="${HELM_HOME}/cache" HELM_DATA_HOME="${HELM_HOME}/data")
tier=0
tier_found=0
for t in "${SCRIPT_DIR}"/test_*.py "${SCRIPT_DIR}"/test_*.sh; do
    [[ -e "${t}" ]] && grep -q '^# E2E TIER: tools' "${t}" || continue
    tier_found=$((tier_found + 1))
    [[ "${scoped}" -eq 0 || -n "${selected[$(basename "${t}")]:-}" ]] || continue
    tier=$((tier + 1))
    case "${t}" in
        *.py) run_one "$(basename "${t}")" no_cloud_run "${tier_env[@]}" python3 "${t}" ;;
        *)    run_one "$(basename "${t}")" no_cloud_run "${tier_env[@]}" bash "${t}" ;;
    esac
done
# A tier that matched nothing would pass having proved nothing.
if [[ "${tier_found}" -eq 0 ]]; then
    printf 'NO `# E2E TIER: tools` TESTS FOUND in %s; the tier is not running\n' "${SCRIPT_DIR}" >&2
    exit 1
fi

# The time taken, since a run waits on this in the background and sets its limit from it (#796).
printf '\n%d checks ran (the offline suite and %d tier tests) in %dm%02ds\n' "${ran}" "${tier}" \
    "$((SECONDS / 60))" "$((SECONDS % 60))"
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
