#!/usr/bin/env bash
# ABOUTME: Writes HECATON_BASE_SHA, the merge base of the checked-out commit and origin/staging, into $GITHUB_ENV for
# ABOUTME: .github/workflows/verify-suites.yml (#1020), so the scoped runners from #1018 run only what the push touched.
#
# Usage: GITHUB_ENV=<file> bash verify/ci-base-sha.sh
#
# It fetches staging first, so the base is staging as GitHub has it now, not as the runner's workspace last saw it.
# When the merge base is the commit itself (a push to staging, or an agent branch with nothing past staging), the
# merge base gives no change to scope by. A push then scopes by what the push itself brought: PUSH_BEFORE, the
# workflow's github.event.before, is the branch tip before the push, and when it is a real commit that is an ancestor
# of the pushed one it becomes HECATON_BASE_SHA (#1189), so a run-of-show edit on staging runs only the tests that
# read it. When PUSH_BEFORE is unset, all zeros (a new branch), not in the history, not an ancestor (a force push), or
# the commit itself, HECATON_BASE_SHA is left unset and both runners run whole, as they do when a person runs them by
# hand. A change to verify/scope-map.yaml is scope_tests.py's to widen, as for any base.
#
# Nothing here falls back. No GITHUB_ENV, no origin, no staging there, or no common ancestor exits 1, naming which.
set -euo pipefail

[[ -n "${GITHUB_ENV:-}" ]] || { printf 'ci-base-sha: GITHUB_ENV is not set; nothing to write the base to\n' >&2; exit 1; }

git fetch --no-tags --prune origin '+refs/heads/staging:refs/remotes/origin/staging' \
    || { printf 'ci-base-sha: could not fetch staging from origin\n' >&2; exit 1; }
head="$(git rev-parse HEAD)"
base="$(git merge-base "${head}" refs/remotes/origin/staging)" \
    || { printf 'ci-base-sha: %s and origin/staging have no common ancestor\n' "${head}" >&2; exit 1; }

if [[ "${base}" == "${head}" ]]; then
    before="${PUSH_BEFORE:-}"
    why=""
    if [[ -z "${before}" ]]; then
        why="no PUSH_BEFORE"
    elif [[ "${before}" =~ ^0+$ ]]; then
        why="PUSH_BEFORE is all zeros, a new branch"
    elif ! git cat-file -e "${before}^{commit}" 2>/dev/null; then
        why="PUSH_BEFORE ${before} is not in the history"
    elif [[ "$(git rev-parse "${before}")" == "${head}" ]]; then
        why="PUSH_BEFORE is the commit itself"
    elif ! git merge-base --is-ancestor "${before}" "${head}"; then
        why="PUSH_BEFORE ${before} is not an ancestor of ${head}, a force push"
    fi
    if [[ -z "${why}" ]]; then
        printf 'HECATON_BASE_SHA=%s\n' "${before}" >>"${GITHUB_ENV}"
        printf 'ci-base-sha: HECATON_BASE_SHA=%s (the tip before this push of %s, already in origin/staging)\n' \
            "${before}" "${head}"
    else
        printf 'ci-base-sha: %s is already in origin/staging and %s; HECATON_BASE_SHA left unset, so both suites run whole\n' \
            "${head}" "${why}"
    fi
else
    printf 'HECATON_BASE_SHA=%s\n' "${base}" >>"${GITHUB_ENV}"
    printf 'ci-base-sha: HECATON_BASE_SHA=%s (merge base of %s and origin/staging)\n' "${base}" "${head}"
fi
