#!/usr/bin/env bash
# ABOUTME: Writes HECATON_BASE_SHA, the merge base of the checked-out commit and origin/staging, into $GITHUB_ENV for
# ABOUTME: .github/workflows/verify-suites.yml (#1020), so the scoped runners from #1018 run only what the push touched.
#
# Usage: GITHUB_ENV=<file> bash verify/ci-base-sha.sh
#
# It fetches staging first, so the base is staging as GitHub has it now, not as the runner's workspace last saw it.
# When the merge base is the commit itself (a push to staging, or an agent branch with nothing past staging), there is
# no change to scope by: an empty diff would read as "nothing touched" and run nothing. HECATON_BASE_SHA is then left
# unset, and both runners run whole, as they do when a person runs them by hand.
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
    printf 'ci-base-sha: %s is already in origin/staging; HECATON_BASE_SHA left unset, so both suites run whole\n' \
        "${head}"
else
    printf 'HECATON_BASE_SHA=%s\n' "${base}" >>"${GITHUB_ENV}"
    printf 'ci-base-sha: HECATON_BASE_SHA=%s (merge base of %s and origin/staging)\n' "${base}" "${head}"
fi
