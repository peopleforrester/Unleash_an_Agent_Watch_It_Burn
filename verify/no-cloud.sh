#!/usr/bin/env bash
# ABOUTME: The no-cloud guard (#857, #865): each test runs with its cloud tools replaced by stubs that log the call and
# ABOUTME: fail, and a test that called one fails, naming the calls. The offline suite stubs five, the tools tier two.
#
# Why. On a dispatched run the `aws` on PATH is hecaton's wrapper, which exports the run's live session for the two
# KubeCon clusters whatever the caller's environment holds, and KUBECONFIG names both. In run 16967 (#616) two
# offline tests ran fleet.sh's `cmd_instructors up all` on event.sh's kubecon profile without stubbing
# cmd_guardrails_link. That wrote real kubeconfigs for watch-it-burn-community and watch-it-burn-private and polled
# each for its guardrails-switch token for five minutes a call, which stalled the suite, and once that app syncs it
# would have written guardrails-peer Secrets on both clusters. #616 stubbed the link in those two tests and #421 put
# stubs like these in one of them. This is the same backstop for every offline test, the next one included.
#
# A stub stands first on PATH and has its log path written into it, so a test that rebuilds its environment
# (python's subprocess env=, `env -u`, `env -i` with PATH kept) still reaches the stub and still logs. A test that
# needs a cloud tool to answer puts its own fake ahead of these on PATH, as test_guardrails_switch.py does: a fake
# never reaches the stub, so it logs nothing.
#
# The tools tier (run-e2e-tools.sh) runs its real pinned kubectl, helm and terraform from verify/.tools/bin with
# KUBECONFIG=/dev/null and the AWS variables unset, but hecaton's aws wrapper exports the run's session whatever the
# caller's environment holds, and the tier pins no aws or eksctl. So it stubs just those two, ahead of its pinned
# tools on PATH (#865).
#
# Sourced, not run: each runner calls no_cloud_setup once and runs each test through no_cloud_run, and a test run
# by hand guards itself with no_cloud_guard, below (#859).

NO_CLOUD_TOOLS=(aws kubectl eksctl helm terraform)

# no_cloud_setup <dir> [tool...]: write a stub for each tool (all of NO_CLOUD_TOOLS when none is named) into
# <dir>/bin and the call log at <dir>/cloud-calls.
no_cloud_setup() {
    local dir="$1" tool
    shift
    local tools=("$@")
    [[ "${#tools[@]}" -gt 0 ]] || tools=("${NO_CLOUD_TOOLS[@]}")
    NO_CLOUD_BIN="${dir}/bin"
    NO_CLOUD_LOG="${dir}/cloud-calls"
    mkdir -p "${NO_CLOUD_BIN}"
    : >"${NO_CLOUD_LOG}"
    for tool in "${tools[@]}"; do
        # printf %q keeps a log path with spaces or quotes one word inside the stub.
        cat >"${NO_CLOUD_BIN}/${tool}" <<EOF
#!/bin/sh
printf '%s\n' "${tool} \$*" >>$(printf '%q' "${NO_CLOUD_LOG}")
echo "no-cloud guard: ${tool} is stubbed here; stub the call or put a fake ${tool} first on PATH (#857, #865)" >&2
exit 1
EOF
        chmod +x "${NO_CLOUD_BIN}/${tool}"
    done
}

# no_cloud_run <command...>: run the command with the stubs first on PATH. Returns the command's own exit code, or 1
# when the command passed but called a stubbed tool; either way the calls are printed and the log is emptied.
no_cloud_run() {
    local rc=0
    [[ -n "${NO_CLOUD_BIN:-}" && -x "${NO_CLOUD_BIN}/aws" ]] || {
        echo "no_cloud_run: no_cloud_setup has not run, so the guard is not in place" >&2; return 1; }
    PATH="${NO_CLOUD_BIN}:${PATH}" "$@" || rc=$?
    if [[ -s "${NO_CLOUD_LOG}" ]]; then
        printf 'TEST CALLED A CLOUD TOOL (#857, #865); no offline or tools-tier test reaches a cluster or an AWS account:\n' >&2
        sed 's/^/    /' "${NO_CLOUD_LOG}" >&2
        : >"${NO_CLOUD_LOG}"
        [[ "${rc}" -ne 0 ]] || rc=1
    fi
    return "${rc}"
}

# A test run by hand (#859). run-tests.sh guards each test it runs, but `bash verify/test_x.sh` on a dispatched run
# goes past the runner and reaches the live session. So each offline test that sources or runs fleet.sh guards
# itself too: it calls no_cloud_guard once its temp dir exists and ends with a check on no_cloud_clean. Under the
# runner its stubs stand ahead of the runner's, so a call fails the test's own last check and names the call there.
# A test's own fakes, put on PATH after no_cloud_guard, still answer first. no_cloud.py is the same for Python tests.

# A test run by hand also inherits the run's KUBECONFIG and AWS variables, which #421's backstop cleared, so the
# guard clears them too: unset, and the three config paths pointed at files that do not exist under <dir>. A real
# kubectl reached by an absolute path, or boto3 in a helper, then finds no context, profile or credentials, and
# AWS_EC2_METADATA_DISABLED keeps the SDKs off the host's instance role. Unset, not blanked: an empty AWS_PROFILE is
# itself an error to the AWS CLI.
NO_CLOUD_UNSET=(HECATON_CLUSTER_ENV AWS_PROFILE AWS_DEFAULT_PROFILE AWS_REGION AWS_DEFAULT_REGION
    AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN AWS_ROLE_ARN
    AWS_ROLE_SESSION_NAME AWS_WEB_IDENTITY_TOKEN_FILE AWS_CONTAINER_CREDENTIALS_FULL_URI
    AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_CONTAINER_AUTHORIZATION_TOKEN
    WIB_TERMINAL_USER WIB_TERMINAL_PASSWORD)

# The presenter terminal login (#910) is a secret too: fleet.sh reads it from mrf-secrets through WIB_TERMINAL_ENV,
# default ~/secrets/projects/watch-it-burn-terminal.env, so a test run on a presenter's machine would read the real
# one. The guard clears the two variables above and points WIB_TERMINAL_ENV at a file that does not exist under
# <dir>; a test that needs a presenter login sets its own placeholder (Tests own their inputs).

# no_cloud_guard <dir>: no_cloud_setup, put the stubs first on PATH and clear the cloud environment, for this shell
# and everything it starts.
no_cloud_guard() {
    local dir="${1:?no_cloud_guard needs a directory}"
    no_cloud_setup "${dir}" || return 1
    unset "${NO_CLOUD_UNSET[@]}"
    export KUBECONFIG="${dir}/no-kubeconfig" AWS_CONFIG_FILE="${dir}/no-aws-config" \
        AWS_SHARED_CREDENTIALS_FILE="${dir}/no-aws-credentials" AWS_EC2_METADATA_DISABLED=true \
        WIB_TERMINAL_ENV="${dir}/no-terminal-login.env"
    export PATH="${NO_CLOUD_BIN}:${PATH}"
}

# no_cloud_clean: true when no stubbed tool was called since no_cloud_setup; otherwise print each call, indented,
# and return 1.
no_cloud_clean() {
    [[ -s "${NO_CLOUD_LOG:?no_cloud_setup has not run, so the guard is not in place}" ]] || return 0
    sed 's/^/        /' "${NO_CLOUD_LOG}"
    return 1
}
