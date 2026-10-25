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
# that started to need a cluster or AWS fails here instead of reaching one.
#
# Nothing here skips. A missing prerequisite or a failed fetch exits 1 before any test runs, with every reason.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_BIN="${SCRIPT_DIR}/.tools/bin"

missing=()
# curl, tar, unzip and sha256sum fetch and verify the tools; uv brings the Python pins; openssl mints the Kyverno
# test's wrong key; jq runs test_ai_layer_rollout.py's filters; node runs the harnesses.
for tool in python3 git curl tar unzip sha256sum uv node jq openssl; do
    command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool} is not on PATH")
done
# The same Node major as run-e2e.sh and the Backstage image (#440).
if command -v node >/dev/null 2>&1 && [[ "$(node -p 'process.versions.node.split(".")[0]')" != "24" ]]; then
    missing+=("node $(node --version) is on PATH; the node harnesses run on Node 24")
fi
if [[ "${#missing[@]}" -gt 0 ]]; then
    printf 'E2E TOOLS TIER CANNOT RUN; this is a failure, not a skip:\n' >&2
    printf '  - %s\n' "${missing[@]}" >&2
    exit 1
fi
if ! bash "${SCRIPT_DIR}/fetch-e2e-tools.sh"; then
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

# The pinned tools come first on PATH, and the three tests that take a path get it, so a tool already on the
# host is never what a check runs.
tier_env=(env -u CONTEXT -u IAM_PIPELINE_PROFILE -u IAM_PIPELINE_REGION -u AWS_PROFILE
    -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN
    KUBECONFIG=/dev/null PATH="${TOOLS_BIN}:${PATH}"
    KYVERNO_CLI="${TOOLS_BIN}/kyverno" CONFTEST="${TOOLS_BIN}/conftest" TERRAFORM="${TOOLS_BIN}/terraform")
tier=0
for t in "${SCRIPT_DIR}"/test_*.py "${SCRIPT_DIR}"/test_*.sh; do
    [[ -e "${t}" ]] && grep -q '^# E2E TIER: tools' "${t}" || continue
    tier=$((tier + 1))
    case "${t}" in
        *.py) run_one "$(basename "${t}")" "${tier_env[@]}" python3 "${t}" ;;
        *)    run_one "$(basename "${t}")" "${tier_env[@]}" bash "${t}" ;;
    esac
done
# A tier that matched nothing would pass having proved nothing.
if [[ "${tier}" -eq 0 ]]; then
    printf 'NO `# E2E TIER: tools` TESTS FOUND in %s; the tier is not running\n' "${SCRIPT_DIR}" >&2
    exit 1
fi

printf '\n%d checks ran (the offline suite and %d tier tests)\n' "${ran}" "${tier}"
if [[ "${fail}" -eq 0 ]]; then
    printf '\nALL E2E TOOLS TIER CHECKS GREEN\n'
else
    printf '\nSOME E2E TOOLS TIER CHECKS FAILED:\n' >&2
    printf '  %s\n' "${failed_names[@]}" >&2
    exit 1
fi
