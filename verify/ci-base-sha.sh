#!/usr/bin/env bash
# ABOUTME: Writes HECATON_BASE_SHA into $GITHUB_ENV for .github/workflows/verify-suites.yml (#1020): the merge base with
# ABOUTME: origin/staging, or for a commit in staging its newest first-parent ancestor whose staging run went green (#1195).
#
# Usage: GITHUB_ENV=<file> GH_TOKEN=<token> GITHUB_REPOSITORY=<owner/repo> bash verify/ci-base-sha.sh
#
# It fetches staging first, so the base is staging as GitHub has it now, not as the runner's workspace last saw it.
# An agent branch with commits past staging is scoped by the merge base, so #1018's runners run only what it touched.
#
# When the merge base is the commit itself (a push to staging, or an agent branch with nothing past staging), the
# merge base gives no change to scope by. The base is then the newest first-parent ancestor of the commit, the commit
# itself left out, whose verify-suites run on staging finished success (#1195). #1189 used the tip before the push,
# github.event.before, but since #1113 a newer staging push cancels the run before it, so a cancelled push's changes
# fell in no run's scope: 2800e073's were in the cancelled run 42480132771 and staging went green at d7a1b91e without
# running them. Scoping from the last green run puts every change since it, a cancelled or failed push's included,
# in the next run's scope. The runs come from the Actions API, the newest 100 green staging push runs of this
# workflow, read with gh and GH_TOKEN (the job's own token, with actions: read). When none of them is a first-parent
# ancestor (no green run yet, a force push past every one, or a root commit), HECATON_BASE_SHA is left unset and both
# runners run whole, as they do when a person runs them by hand. A change to verify/scope-map.yaml is
# scope_tests.py's to widen, as for any base.
#
# Nothing here falls back. No GITHUB_ENV, no origin, no staging there, or no common ancestor exits 1, naming which;
# so does a commit in staging with no GH_TOKEN, no GITHUB_REPOSITORY, or an Actions API read that fails.
set -euo pipefail

[[ -n "${GITHUB_ENV:-}" ]] || { printf 'ci-base-sha: GITHUB_ENV is not set; nothing to write the base to\n' >&2; exit 1; }

WORKFLOW_FILE="verify-suites.yml"

git fetch --no-tags --prune origin '+refs/heads/staging:refs/remotes/origin/staging' \
    || { printf 'ci-base-sha: could not fetch staging from origin\n' >&2; exit 1; }
head="$(git rev-parse HEAD)"
base="$(git merge-base "${head}" refs/remotes/origin/staging)" \
    || { printf 'ci-base-sha: %s and origin/staging have no common ancestor\n' "${head}" >&2; exit 1; }

if [[ "${base}" != "${head}" ]]; then
    printf 'HECATON_BASE_SHA=%s\n' "${base}" >>"${GITHUB_ENV}"
    printf 'ci-base-sha: HECATON_BASE_SHA=%s (merge base of %s and origin/staging)\n' "${base}" "${head}"
    exit 0
fi

[[ -n "${GH_TOKEN:-}" ]] \
    || { printf 'ci-base-sha: %s is in origin/staging and GH_TOKEN is not set, so its green staging runs cannot be read\n' "${head}" >&2; exit 1; }
[[ -n "${GITHUB_REPOSITORY:-}" ]] \
    || { printf 'ci-base-sha: %s is in origin/staging and GITHUB_REPOSITORY is not set, so its green staging runs cannot be read\n' "${head}" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

endpoint="repos/${GITHUB_REPOSITORY}/actions/workflows/${WORKFLOW_FILE}/runs?branch=staging&event=push&status=success&per_page=100"
gh api "${endpoint}" >"${work}/runs.json" \
    || { printf 'ci-base-sha: gh api %s failed\n' "${endpoint}" >&2; exit 1; }
# The query filters already; the conclusion, branch and event are read again here, so a run the API let through that
# did not go green on a staging push never becomes a base.
python3 -I -c '
import json, sys
runs = json.load(open(sys.argv[1])).get("workflow_runs")
if not isinstance(runs, list):
    sys.exit("ci-base-sha: the Actions API answer has no workflow_runs list")
for r in runs:
    if r.get("conclusion") == "success" and r.get("head_branch") == "staging" and r.get("event") == "push":
        print(r["head_sha"])
' "${work}/runs.json" >"${work}/green" \
    || { printf 'ci-base-sha: could not read the runs gh api %s returned\n' "${endpoint}" >&2; exit 1; }

green=""
if git rev-parse -q --verify "${head}^" >/dev/null; then
    git rev-list --first-parent "${head}^" >"${work}/ancestors"
    green="$(grep -m1 -Fx -f "${work}/green" "${work}/ancestors" || true)"
fi

if [[ -n "${green}" ]]; then
    printf 'HECATON_BASE_SHA=%s\n' "${green}" >>"${GITHUB_ENV}"
    printf 'ci-base-sha: HECATON_BASE_SHA=%s (the newest first-parent ancestor of %s, already in origin/staging, whose verify-suites run on staging finished success)\n' \
        "${green}" "${head}"
else
    printf 'ci-base-sha: %s is already in origin/staging and none of the %s newest green verify-suites runs on staging is a first-parent ancestor of it; HECATON_BASE_SHA left unset, so both suites run whole\n' \
        "${head}" "$(wc -l <"${work}/green" | tr -d ' ')"
fi
