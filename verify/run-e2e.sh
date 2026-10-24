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
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKSTAGE_DIR="${SCRIPT_DIR}/../images/watch-it-burn-backstage"
NAMESPACE="${NAMESPACE:-agent}"

missing=()
for tool in kubectl helm python3 node yarn; do
    command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool} is not on PATH")
done
# test_kyverno_cel_policies.py evaluates the policies with the Kyverno CLI, pinned to the deployed v1.19.0.
command -v "${KYVERNO_CLI:-kyverno}" >/dev/null 2>&1 \
    || missing+=("the kyverno CLI v1.19.0 is not on PATH (or set KYVERNO_CLI): github.com/kyverno/kyverno/releases/tag/v1.19.0")
# The IAM policy pipeline (#207): test_iam_policy_structural.py renders the Terraform roots and runs conftest;
# test_iam_policy_aws.py sends the documents to Access Analyzer and the policy simulator as a named profile.
command -v "${CONFTEST:-conftest}" >/dev/null 2>&1 \
    || missing+=("conftest v0.71.1 is not on PATH (or set CONFTEST): github.com/open-policy-agent/conftest/releases/tag/v0.71.1")
command -v "${TERRAFORM:-terraform}" >/dev/null 2>&1 || missing+=("terraform is not on PATH (or set TERRAFORM); VERSIONS.lock pins v1.15.6")
command -v aws >/dev/null 2>&1 || missing+=("the aws CLI is not on PATH")
[[ -n "${IAM_PIPELINE_PROFILE:-}" && -n "${IAM_PIPELINE_REGION:-}" ]] \
    || missing+=("IAM_PIPELINE_PROFILE and IAM_PIPELINE_REGION must name the AWS profile and region the policy pipeline's AWS checks run as")
if [[ -z "${CONTEXT:-}" ]]; then
    missing+=("CONTEXT is not set: name the kube-context of the test attendee cluster to run against")
elif command -v kubectl >/dev/null 2>&1 \
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
        && yarn install --immutable \
        && yarn playwright install chromium \
        && yarn test:e2e )
}
run_one "backstage playwright (yarn test:e2e)" backstage_e2e

printf '\n%d E2E checks ran\n' "${ran}"
if [[ "${fail}" -eq 0 ]]; then
    printf '\nALL E2E CHECKS GREEN\n'
else
    printf '\nSOME E2E CHECKS FAILED:\n' >&2
    printf '  %s\n' "${failed_names[@]}" >&2
    exit 1
fi
