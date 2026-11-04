#!/usr/bin/env bash
# ABOUTME: The offline suite's no-cloud guard (#857): each test runs with aws, kubectl, eksctl, helm and terraform
# ABOUTME: replaced by stubs that log the call and fail, and a test that called one fails, naming the calls.
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
# never reaches the stub, so it logs nothing. The tools tier (run-e2e-tools.sh) runs its real pinned tools and does
# not use this.
#
# Sourced, not run: run-tests.sh calls no_cloud_setup once and runs each test through no_cloud_run.

NO_CLOUD_TOOLS=(aws kubectl eksctl helm terraform)

# no_cloud_setup <dir>: write the stubs into <dir>/bin and the call log at <dir>/cloud-calls.
no_cloud_setup() {
    local dir="$1" tool
    NO_CLOUD_BIN="${dir}/bin"
    NO_CLOUD_LOG="${dir}/cloud-calls"
    mkdir -p "${NO_CLOUD_BIN}"
    : >"${NO_CLOUD_LOG}"
    for tool in "${NO_CLOUD_TOOLS[@]}"; do
        # printf %q keeps a log path with spaces or quotes one word inside the stub.
        cat >"${NO_CLOUD_BIN}/${tool}" <<EOF
#!/bin/sh
printf '%s\n' "${tool} \$*" >>$(printf '%q' "${NO_CLOUD_LOG}")
echo "offline suite: ${tool} is stubbed here; stub the call or put a fake ${tool} first on PATH (#857)" >&2
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
        printf 'OFFLINE TEST CALLED A CLOUD TOOL (#857); the offline suite never reaches a cluster or an AWS account:\n' >&2
        sed 's/^/    /' "${NO_CLOUD_LOG}" >&2
        : >"${NO_CLOUD_LOG}"
        [[ "${rc}" -ne 0 ]] || rc=1
    fi
    return "${rc}"
}
