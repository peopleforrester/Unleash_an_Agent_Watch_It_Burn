#!/usr/bin/env bash
# ABOUTME: Sets WIB_ARTIFACT_CACHE for a CI job to the runner's own artifact cache, $RUNNER_TOOL_CACHE/wib-artifacts,
# ABOUTME: outside $GITHUB_WORKSPACE and every checkout, and writes it to $GITHUB_ENV. Any doubt about the path exits 1.
#
# Usage, as a workflow step before the job's first pinned fetch: bash verify/ci-artifact-cache.sh
#
# Every workflow job under .github/workflows/ that fetches a pinned artifact runs this, and only this, to name the host
# artifact cache (verify/artifact_cache.py, #1117), so each job on a runner reads the one copy that runner already holds
# (#1123). RUNNER_TOOL_CACHE is the runner's own variable: on a self-hosted runner it is <runner>/_work/_tool, beside
# the job workspaces and shared by every job the runner takes (on Tanjiro,
# /srv/gha-agent/Unleash_an_Agent_Watch_It_Burn/_work/_tool, where setup-uv and setup-node keep their tools), and the
# runner's .env can move it; on a GitHub-hosted runner it is /opt/hostedtoolcache. So the same step serves the tanjiro
# and megumi runners and the hosted ones without naming any of them. Before #1123 the e2e job's downloads sat in the
# workspace's verify/.tools, and the clean step had to spare it; that step now removes everything git does not track.
#
# The path is refused, by name, when RUNNER_TOOL_CACHE or GITHUB_ENV is unset, when it is not absolute, when it lies
# inside $GITHUB_WORKSPACE, and when artifact_cache.py, given it, resolves another root (a root inside a git worktree,
# or a HECATON_TOOLS_CACHE in the job's environment that would take precedence).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() {
    printf 'CI ARTIFACT CACHE FAILED: %s\n' "$1" >&2
    exit 1
}

[[ -n "${GITHUB_ENV:-}" ]] || fail "GITHUB_ENV is not set, so the job's later steps would not see WIB_ARTIFACT_CACHE"
[[ -n "${RUNNER_TOOL_CACHE:-}" ]] || fail "RUNNER_TOOL_CACHE is not set; the runner names no tool cache to keep artifacts in"
[[ "${RUNNER_TOOL_CACHE}" == /* ]] || fail "RUNNER_TOOL_CACHE is ${RUNNER_TOOL_CACHE}, not an absolute path"
[[ -n "${GITHUB_WORKSPACE:-}" ]] || fail "GITHUB_WORKSPACE is not set, so the cache cannot be shown to lie outside it"

# Both paths with every symlink resolved, the cache's before it exists, so a link into the workspace is seen as that and
# nothing is created there.
workspace="$(cd "${GITHUB_WORKSPACE}" 2>/dev/null && pwd -P)" || fail "GITHUB_WORKSPACE ${GITHUB_WORKSPACE} is not a directory"
cache="$(realpath -m "${RUNNER_TOOL_CACHE}/wib-artifacts")" || fail "cannot resolve ${RUNNER_TOOL_CACHE}/wib-artifacts"
case "${cache}/" in
    "${workspace}/"*) fail "the cache ${cache} is inside the job workspace ${workspace}, which the clean step empties" ;;
esac

# artifact_cache.py decides the root every fetch uses; it must come out as this path and nothing else.
if ! root="$(WIB_ARTIFACT_CACHE="${cache}" python3 "${SCRIPT_DIR}/artifact_cache.py" root 2>&1)"; then
    fail "artifact_cache.py refuses ${cache}: ${root#ARTIFACT CACHE FAILED: }"
fi
[[ "${root}" == "${cache}" ]] || fail "artifact_cache.py resolves the root ${root}, not ${cache}; is HECATON_TOOLS_CACHE set?"
mkdir -p "${cache}" || fail "cannot create ${cache}"

printf 'WIB_ARTIFACT_CACHE=%s\n' "${cache}" >>"${GITHUB_ENV}"
printf 'WIB_ARTIFACT_CACHE=%s (the runner'"'"'s artifact cache, outside %s)\n' "${cache}" "${workspace}"
