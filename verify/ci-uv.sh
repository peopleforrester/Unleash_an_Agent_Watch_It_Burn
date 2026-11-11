#!/usr/bin/env bash
# ABOUTME: Puts uv 0.13.7 on a CI job's PATH from the runner's artifact cache, pinned by SHA-256, and sets what the
# ABOUTME: setup action it replaces set on a self-hosted runner (#1331). Any doubt about the binary or the job exits 1.
#
# Usage, as a workflow step after verify/ci-artifact-cache.sh: bash verify/ci-uv.sh
#
# verify-suites.yml installed uv with astral-sh/setup-uv until #1331. The runner empties its action directory at the
# start of every job and downloads each action again from codeload.github.com, and on Tanjiro's link the 2.4 MB setup-uv
# archive timed out three times in both jobs, on staging 44f3939c (Actions run 42966599043) and d2ebbd3e (42968258309),
# so "Set up job" failed before any step ran and no workflow step could retry it. This script runs as a step instead: it
# reads uv's release archive from the host artifact cache (verify/artifact_cache.py, #1117) by its SHA-256, which serves
# a warm runner with no network at all and fetches a miss with the cache's own retries (get_retrying).
#
# The archive is the one setup-uv itself fetched, from Astral's mirror of the GitHub release (its default
# download-from-astral-mirror). UV_SHA256 was read from the release's uv-x86_64-unknown-linux-gnu.tar.gz.sha256 and
# from Astral's versions manifest for 0.13.7 on 2026-11-11, and the downloaded file hashed to it.
#
# On a self-hosted runner, with none of its inputs set, setup-uv added to PATH, in this order: $XDG_BIN_HOME (else
# $XDG_DATA_HOME/../bin, else $HOME/.local/bin), uv's own directory, and UV_PYTHON_INSTALL_DIR, which it also exported
# (the runner's own value, else $HOME/.local/share/uv/python). This does the same, so verify/package_cache.py finds and
# installs its Pythons where it did before. uv is unpacked under $RUNNER_TEMP, which the runner empties for every job.
# Only the uv binary is unpacked: the archive's second binary runs tools ad hoc, which no job here does and
# verify/test_package_cache.py forbids, so it is left in the archive.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

UV_VERSION="0.13.7"
UV_SHA256="c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83"
UV_URL="https://releases.astral.sh/github/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"
UV_MEMBER_DIR="uv-x86_64-unknown-linux-gnu"

fail() {
    printf 'CI UV FAILED: %s\n' "$1" >&2
    exit 1
}

[[ -n "${GITHUB_PATH:-}" ]] || fail "GITHUB_PATH is not set, so the job's later steps would not find uv"
[[ -n "${GITHUB_ENV:-}" ]] || fail "GITHUB_ENV is not set, so the job's later steps would not see UV_PYTHON_INSTALL_DIR"
[[ -n "${RUNNER_TEMP:-}" && -d "${RUNNER_TEMP}" ]] || fail "RUNNER_TEMP is not set to a directory to unpack uv into"
[[ -n "${HOME:-}" ]] || fail "HOME is not set, so there is no default UV_PYTHON_INSTALL_DIR"
[[ -n "${WIB_ARTIFACT_CACHE:-}" ]] \
    || fail "WIB_ARTIFACT_CACHE is not set; run bash verify/ci-artifact-cache.sh first, so uv comes from the runner's cache"

archive="$(bash "${SCRIPT_DIR}/artifact-cache.sh" get "${UV_SHA256}" "${UV_URL}")" \
    || fail "the artifact cache could not serve uv ${UV_VERSION} (${UV_SHA256}) from ${UV_URL}"
[[ -f "${archive}" ]] || fail "the artifact cache named ${archive} for uv ${UV_VERSION}, which is not a file"

dest="${RUNNER_TEMP}/uv-${UV_VERSION}"
rm -rf "${dest}"
mkdir -p "${dest}"
tar -xzf "${archive}" -C "${dest}" --strip-components=1 "${UV_MEMBER_DIR}/uv" \
    || fail "cannot unpack ${UV_MEMBER_DIR}/uv from ${archive}"

got="$("${dest}/uv" --version 2>&1)" || fail "${dest}/uv --version failed: ${got}"
[[ "${got}" == "uv ${UV_VERSION}" || "${got}" == "uv ${UV_VERSION} "* ]] \
    || fail "${dest}/uv reports '${got}', not uv ${UV_VERSION}"

if [[ -n "${XDG_BIN_HOME:-}" ]]; then
    tool_bin="${XDG_BIN_HOME}"
elif [[ -n "${XDG_DATA_HOME:-}" ]]; then
    tool_bin="${XDG_DATA_HOME}/../bin"
else
    tool_bin="${HOME}/.local/bin"
fi
python_dir="${UV_PYTHON_INSTALL_DIR:-${HOME}/.local/share/uv/python}"

{
    printf '%s\n' "${tool_bin}"
    printf '%s\n' "${dest}"
    printf '%s\n' "${python_dir}"
} >>"${GITHUB_PATH}"
printf 'UV_PYTHON_INSTALL_DIR=%s\n' "${python_dir}" >>"${GITHUB_ENV}"

printf '%s from %s, unpacked to %s; UV_PYTHON_INSTALL_DIR=%s\n' "${got}" "${archive}" "${dest}" "${python_dir}"
