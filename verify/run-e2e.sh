#!/usr/bin/env bash
# ABOUTME: Heavy suite: the live beat harness (run-all.sh) on a cluster, every `# SUITE: e2e` check in
# ABOUTME: verify/ (kubectl/helm renders, node, live Datadog), doc-link fetches, Backstage's footprint and Playwright.
#
# Usage: CONTEXT=<kube-context> IAM_PIPELINE_PROFILE=<aws-profile> IAM_PIPELINE_REGION=<region> \
#            DRIFT_PROFILE=<aws-profile> ATTENDEE_CLUSTER=<cluster> COMMUNITY_CONTEXT=<kube-context> \
#            PRIVATE_CONTEXT=<kube-context> [NAMESPACE=agent] bash verify/run-e2e.sh
#
# The KubeCon probe's Challenge 3 beat (test_kubecon_c3_live.py, #807) runs on the live public bot, not the attendee
# cluster, so it needs COMMUNITY_CONTEXT, the kube-context of the community cluster (attackme). It spends one model
# call there and removes the Joker it lands.
#
# The Agent Observability read-back (test_agent_obs_flow_live.py, #813) sends one fresh chat to each KubeCon bot over
# the public internet and reads its spans back from Datadog with the read pair in watch-it-burn/datadog, as
# WIB_DEFAULT_ACCOUNT (default accen-dev) in WIB_REGION (default us-west-2). It spends two model calls and can wait
# up to ten minutes per bot.
#
# #647's trace scrub (test_collector_pii_scrub_live.py) also runs on COMMUNITY_CONTEXT: it sends one span with PII into
# attackme's collector over a port-forward, reads it back from Datadog APM and Agent Observability scrubbed, and scans
# the stored burritobot-public spans for raw PII. No model call; the span goes with the post-talk purge. Its storefront
# half (test_public_datadog_button_live.py) loads the public and private bots in headless Chromium and needs no context.
#
# The tier swap (test_tier_swap_live.py, #793) runs on CONTEXT: it patches workshop-agent from bedrock-nova to
# bedrock-haiku, holds guard-proxy's /cost to the new tier within 5 seconds and one /chat turn to Haiku rates, and
# patches it back. It spends one Haiku call and restarts the agent pod twice.
#
# #783's trace-id fix (test_otel_trace_id_fix_live.py, #812) is checked on staging and on both KubeCon clusters, so it
# also needs PRIVATE_CONTEXT, the kube-context of the private admin cluster (watch-it-burn-private). It only reads.
#
# #954's recipe block (test_recipe_block_live.py) runs on PRIVATE_CONTEXT too: the terminal's guardrails-on, the card
# BurritoBot's prompt names read back Permission denied with KubeArmor's Block alert, one marked model call asking for
# it, then guardrails-off. The switch reaches the community cluster as well, for the minute or two it runs.
#
# #954's 2-hour flow (test_two_hour_flow_live.py, #970) runs on PRIVATE_CONTEXT as well: lab.html's own chat asks for
# Challenges 1, 2, 3, 5, 6 and 7, each in a fresh marked conversation, judged on what the lab tells the student to look
# for, with the deployed systemMessage held equal to git's. 35 model calls; it puts the AI guards back off and
# deletes promo-mascot and maintenance-shell. Its guardrails stay off, so run it apart from the recipe block above.
#
# The prompt wall's "+N more" count (test_wall_more_count_live.py, #935) needs no context: it downloads the wall the
# room reads, WALL_URL (default https://prompts.agenticburn.com/), and runs the page's own script on a fake clock in
# node, with verify/wall_more_count.py's checks, which the tools tier runs on the pinned copy. It sends nothing to the
# wall. The wall is prompts-agenticburn's, deployed to Railway with `railway up`.
#
# The AWS-plane drift check (test_drift_aws_live.py, #205) needs DRIFT_PROFILE, an operator profile in
# WIB_ATTENDEE_ACCOUNTS whose account has infra/terraform/aws/audit applied, and ATTENDEE_CLUSTER, a cluster in that
# account whose attendee key is in infra/terraform/fleet/aws-pool/. They are prerequisites like the rest.
#
# The target cluster is never guessed. CONTEXT is required and is passed explicitly to every kubectl call;
# the current-context is never read (see AGENTS.md, Kube-context safety). KUBECONFIG may be set for this
# one command to point at an isolated kubeconfig.
#
# Nothing here skips. A missing tool, context, cluster or credential is a FAILURE with the reason printed:
# this suite exists to prove the things the offline suite cannot, and a run that proved none of them must
# not exit 0. Every prerequisite is checked before anything runs, so one run lists everything that is missing.
#
# kyverno, conftest, terraform, kubectl, helm, otelcol-contrib, ttyd, crane, weaver and agentgateway are not taken from the host
# (#585, #654, #770, #775, #782). The prerequisite check runs verify/fetch-e2e-tools.sh, which puts the pinned,
# checksum-verified binaries of e2e-tools.lock in the gitignored verify/.tools/bin, and that directory goes first on
# PATH for everything after it, so a cluster build runs the same binaries as the gate's E2E command
# (run-e2e-tools.sh). A failed fetch is one of the missing prerequisites.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKSTAGE_DIR="${SCRIPT_DIR}/../images/watch-it-burn-backstage"
TOOLS_BIN="${SCRIPT_DIR}/.tools/bin"
NAMESPACE="${NAMESPACE:-agent}"

missing=()
# jq: test_kyverno_cel_live.py runs the lab's own policyreport jq filter. curl, tar, unzip and sha256sum fetch
# and verify the pinned tools, and xz unpacks weaver's archive. uv brings the Python pins the checks run on
# (playwright, llm-guard, segno, mcp), as in run-e2e-tools.sh, so nothing is installed globally (#441).
for tool in python3 node corepack jq curl tar unzip sha256sum xz uv; do
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
# live check runs, the otelcol-contrib the collector tests run (test_lab_pipeline_collector.py, the chart's
# version), the ttyd the terminal image ships (test_ttyd_ws_auth.py, #770), and the weaver
# test_weaver_registry_check.py checks weaver/registry with (#782), and the agentgateway release binary of the deployed
# gateway version test_agentgateway_tracing_e2e.py runs the gateway ConfigMaps on (#864). The fetch needs the four
# tools above, so it is only tried once they are there.
tools_ready=0
if command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1 \
    && command -v sha256sum >/dev/null 2>&1; then
    if bash "${SCRIPT_DIR}/fetch-e2e-tools.sh"; then
        tools_ready=1
    else
        missing+=("the pinned kyverno, conftest, terraform, kubectl, helm, otelcol-contrib, ttyd, crane, weaver and agentgateway could not be fetched (fetch-e2e-tools.sh, reasons above)")
    fi
else
    missing+=("the pinned kyverno, conftest, terraform, kubectl, helm, otelcol-contrib, ttyd, crane, weaver and agentgateway were not fetched: fetch-e2e-tools.sh needs curl, tar, unzip and sha256sum")
fi
if [[ "${tools_ready}" -eq 1 ]]; then
    # The six tests that take a path get the fetched one, so a tool already on the host is never what runs.
    export PATH="${TOOLS_BIN}:${PATH}"
    export KYVERNO_CLI="${TOOLS_BIN}/kyverno" CONFTEST="${TOOLS_BIN}/conftest" TERRAFORM="${TOOLS_BIN}/terraform" \
        OTELCOL_CONTRIB="${TOOLS_BIN}/otelcol-contrib" TTYD="${TOOLS_BIN}/ttyd" CRANE="${TOOLS_BIN}/crane" \
        AGENTGATEWAY="${TOOLS_BIN}/agentgateway"
fi
# test_iam_policy_aws.py sends the IAM documents to Access Analyzer and the policy simulator as a named profile.
command -v aws >/dev/null 2>&1 || missing+=("the aws CLI is not on PATH")
[[ -n "${IAM_PIPELINE_PROFILE:-}" && -n "${IAM_PIPELINE_REGION:-}" ]] \
    || missing+=("IAM_PIPELINE_PROFILE and IAM_PIPELINE_REGION must name the AWS profile and region the policy pipeline's AWS checks run as")
[[ -n "${DRIFT_PROFILE:-}" && -n "${ATTENDEE_CLUSTER:-}" ]] \
    || missing+=("DRIFT_PROFILE and ATTENDEE_CLUSTER must name the fleet account (audit root applied) and the attendee cluster whose key the AWS-plane drift check uses (test_drift_aws_live.py)")
if [[ -z "${CONTEXT:-}" ]]; then
    missing+=("CONTEXT is not set: name the kube-context of the test attendee cluster to run against")
elif [[ "${tools_ready}" -eq 1 ]] \
    && ! kubectl --context "${CONTEXT}" --request-timeout=15s get --raw /readyz >/dev/null 2>&1; then
    missing+=("cluster for context '${CONTEXT}' is not reachable (kubectl --context ${CONTEXT} get --raw /readyz failed)")
fi
if [[ -z "${COMMUNITY_CONTEXT:-}" ]]; then
    missing+=("COMMUNITY_CONTEXT is not set: name the kube-context of the community cluster (attackme) the KubeCon probe's Challenge 3 beat runs on (test_kubecon_c3_live.py)")
elif [[ "${tools_ready}" -eq 1 ]] \
    && ! kubectl --context "${COMMUNITY_CONTEXT}" --request-timeout=15s get --raw /readyz >/dev/null 2>&1; then
    missing+=("community cluster for context '${COMMUNITY_CONTEXT}' is not reachable (kubectl --context ${COMMUNITY_CONTEXT} get --raw /readyz failed)")
fi
if [[ -z "${PRIVATE_CONTEXT:-}" ]]; then
    missing+=("PRIVATE_CONTEXT is not set: name the kube-context of the private admin cluster (watch-it-burn-private) #783's trace-id fix is checked on (test_otel_trace_id_fix_live.py)")
elif [[ "${tools_ready}" -eq 1 ]] \
    && ! kubectl --context "${PRIVATE_CONTEXT}" --request-timeout=15s get --raw /readyz >/dev/null 2>&1; then
    missing+=("private cluster for context '${PRIVATE_CONTEXT}' is not reachable (kubectl --context ${PRIVATE_CONTEXT} get --raw /readyz failed)")
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

# The attendee profile deploys Backstage (#244), so its live check runs here (#548): both pods Ready, a usage reading
# for every container, and the Kubernetes tab listing pods for unicorn-party and workshop-agent. One sample keeps the
# suite fast; the script's default of six readings ten seconds apart sleeps for 50 seconds. Run it alone for a peak.
run_one "backstage-footprint.sh (SAMPLES=1)" \
    env CONTEXT="${CONTEXT}" SAMPLES=1 bash "${SCRIPT_DIR}/backstage-footprint.sh"

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
