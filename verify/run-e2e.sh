#!/usr/bin/env bash
# ABOUTME: Heavy suite: the live beat harness (run-all.sh) on a cluster, every `# SUITE: e2e` check in
# ABOUTME: verify/ (kubectl/helm renders, node, live Datadog), doc-link fetches, and Backstage Playwright.
#
# Usage: CONTEXT=<kube-context> IAM_PIPELINE_PROFILE=<aws-profile> IAM_PIPELINE_REGION=<region> \
#            [NAMESPACE=agent] bash verify/run-e2e.sh
#
# The target cluster is never guessed. CONTEXT is required and is passed explicitly to every kubectl call;
# the current-context is never read (see AGENTS.md, Kube-context safety). KUBECONFIG may be set for this
# one command to point at an isolated kubeconfig.
#
# Nothing here skips. A missing tool, context, cluster or credential is a FAILURE with the reason printed:
# this suite exists to prove the things the offline suite cannot, and a run that proved none of them must
# not exit 0. Every prerequisite is checked before anything runs, so one run lists everything that is missing.
#
# kyverno, conftest, terraform, kubectl, helm and otelcol-contrib are not taken from the host (#585, #654). The
# prerequisite check runs verify/fetch-e2e-tools.sh, which puts the pinned, checksum-verified binaries of
# e2e-tools.lock in the gitignored verify/.tools/bin, and that directory goes first on PATH for everything after it,
# so a cluster build runs the same binaries as the gate's E2E command (run-e2e-tools.sh). A failed fetch is one of
# the missing prerequisites.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKSTAGE_DIR="${SCRIPT_DIR}/../images/watch-it-burn-backstage"
TOOLS_BIN="${SCRIPT_DIR}/.tools/bin"
NAMESPACE="${NAMESPACE:-agent}"

missing=()
# jq: test_kyverno_cel_live.py runs the lab's own policyreport jq filter. curl, tar, unzip and sha256sum fetch
# and verify the pinned tools.
for tool in python3 node corepack jq curl tar unzip sha256sum; do
    command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool} is not on PATH")
done
# Backstage runs on Node 24 (packages/backend/Dockerfile is node:24). Yarn comes from corepack, which
# runs the yarn 4 the Backstage package.json pins (packageManager, .yarnrc.yml yarnPath), so no global
# yarn is needed. A yarn on PATH is not used.
if command -v node >/dev/null 2>&1 && [[ "$(node -p 'process.versions.node.split(".")[0]')" != "24" ]]; then
    missing+=("node $(node --version) is on PATH; the Backstage suite needs Node 24")
fi
# The pinned tools: the kyverno CLI test_kyverno_cel_policies.py evaluates the policies with, the conftest and
# terraform the IAM policy pipeline (#207) renders and checks the roots with, the kubectl and helm every render and
# live check runs, and the otelcol-contrib the collector tests run (test_lab_pipeline_collector.py, the chart's
# version). The fetch needs the four tools above, so it is only tried once they are there.
tools_ready=0
if command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1 \
    && command -v sha256sum >/dev/null 2>&1; then
    if bash "${SCRIPT_DIR}/fetch-e2e-tools.sh"; then
        tools_ready=1
    else
        missing+=("the pinned kyverno, conftest, terraform, kubectl, helm and otelcol-contrib could not be fetched (fetch-e2e-tools.sh, reasons above)")
    fi
else
    missing+=("the pinned kyverno, conftest, terraform, kubectl, helm and otelcol-contrib were not fetched: fetch-e2e-tools.sh needs curl, tar, unzip and sha256sum")
fi
if [[ "${tools_ready}" -eq 1 ]]; then
    # The four tests that take a path get the fetched one, so a tool already on the host is never what runs.
    export PATH="${TOOLS_BIN}:${PATH}"
    export KYVERNO_CLI="${TOOLS_BIN}/kyverno" CONFTEST="${TOOLS_BIN}/conftest" TERRAFORM="${TOOLS_BIN}/terraform" \
        OTELCOL_CONTRIB="${TOOLS_BIN}/otelcol-contrib"
fi
# test_iam_policy_aws.py sends the IAM documents to Access Analyzer and the policy simulator as a named profile.
command -v aws >/dev/null 2>&1 || missing+=("the aws CLI is not on PATH")
[[ -n "${IAM_PIPELINE_PROFILE:-}" && -n "${IAM_PIPELINE_REGION:-}" ]] \
    || missing+=("IAM_PIPELINE_PROFILE and IAM_PIPELINE_REGION must name the AWS profile and region the policy pipeline's AWS checks run as")
if [[ -z "${CONTEXT:-}" ]]; then
    missing+=("CONTEXT is not set: name the kube-context of the test attendee cluster to run against")
elif [[ "${tools_ready}" -eq 1 ]] \
    && ! kubectl --context "${CONTEXT}" --request-timeout=15s get --raw /readyz >/dev/null 2>&1; then
    missing+=("cluster for context '${CONTEXT}' is not reachable (kubectl --context ${CONTEXT} get --raw /readyz failed)")
fi
if [[ "${#missing[@]}" -gt 0 ]]; then
    printf 'E2E SUITE CANNOT RUN; this is a failure, not a skip:\n' >&2
    printf '  - %s\n' "${missing[@]}" >&2
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
    # Exit 2 is how a live check reports a missing credential; here that is a failure like any other.
    [[ "${rc}" -eq 0 ]] || { fail=1; failed_names+=("${label} (exit ${rc})"); }
}

# The beats first: they drive traffic through the AI layer, which the live Datadog check then looks for.
run_one "run-all.sh ${CONTEXT} ${NAMESPACE}" bash "${SCRIPT_DIR}/run-all.sh" "${CONTEXT}" "${NAMESPACE}"

for t in "${SCRIPT_DIR}"/test_*.py "${SCRIPT_DIR}"/test_*.sh; do
    [[ -e "${t}" ]] && grep -q '^# SUITE: e2e' "${t}" || continue
    case "${t}" in
        *.py) run_one "$(basename "${t}")" python3 "${t}" ;;
        *)    run_one "$(basename "${t}")" bash "${t}" ;;
    esac
done
# The half of the doc-link check the offline suite leaves out on purpose: fetching every documentation root.
run_one "test_doc_links.py (WIB_CHECK_LINKS=1, network)" env WIB_CHECK_LINKS=1 python3 "${SCRIPT_DIR}/test_doc_links.py"

# CI is unset on purpose: with CI set, playwright.config.ts starts no web servers and expects one to be
# running already on :7007. Chained with && because set -e does not apply inside a `|| rc=$?` call.
backstage_e2e() {
    ( cd "${BACKSTAGE_DIR}" && unset CI \
        && corepack yarn install --immutable \
        && corepack yarn playwright install chromium \
        && corepack yarn test:e2e )
}
run_one "backstage playwright (corepack yarn test:e2e)" backstage_e2e

printf '\n%d E2E checks ran\n' "${ran}"
if [[ "${fail}" -eq 0 ]]; then
    printf '\nALL E2E CHECKS GREEN\n'
else
    printf '\nSOME E2E CHECKS FAILED:\n' >&2
    printf '  %s\n' "${failed_names[@]}" >&2
    exit 1
fi
