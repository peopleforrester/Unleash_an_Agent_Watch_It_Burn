#!/usr/bin/env bash
# ABOUTME: Fetches the cluster-free E2E tier's pinned binaries (e2e-tools.lock) into verify/.tools/bin, which git
# ABOUTME: ignores, each download taken from the host artifact cache by its SHA-256 (#1118). Any failure exits 1 (#572).
#
# Usage: bash verify/fetch-e2e-tools.sh
#
# Each lock entry's download comes from verify/artifact-cache.sh (#1117): the host's one copy, outside every worktree,
# hashed again on every use and fetched from the lock's URL only when the host has none, so a second run on the same
# host, from any worktree, makes no network fetch. A cache file that does not match its sum fails and is never
# replaced by a fresh download. The binaries are always extracted again from that verified file, so .tools/bin never
# holds a binary the lock does not vouch for. Every tool is tried before exiting, so one run names every failure.
#
# Before #1118 each worktree kept its own copy of every download in .tools/dl, about 3.1 GB a run and about 300 GB of
# old hecaton workspaces on 2026-11-06 (#1004). A .tools/dl left by an older run is removed.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK="${SCRIPT_DIR}/e2e-tools.lock"
TOOLS_DIR="${SCRIPT_DIR}/.tools"

# The lock pins linux/x86_64 artifacts only; on anything else they would not run, so say so instead of trying.
platform="$(uname -s) $(uname -m)"
if [[ "${platform}" != "Linux x86_64" ]]; then
    printf 'E2E TOOLS FETCH FAILED: e2e-tools.lock pins Linux x86_64 binaries; this host is %s\n' "${platform}" >&2
    exit 1
fi
[[ -f "${LOCK}" ]] || { printf 'E2E TOOLS FETCH FAILED: %s is missing\n' "${LOCK}" >&2; exit 1; }

if [[ -d "${TOOLS_DIR}/dl" ]]; then
    printf 'Removing %s: the downloads live in the host artifact cache now (#1118)\n' "${TOOLS_DIR}/dl"
    rm -rf "${TOOLS_DIR}/dl"
fi
mkdir -p "${TOOLS_DIR}/bin"
failed=()
count=0
cache_err="$(mktemp "${TOOLS_DIR}/.cache-err.XXXXXX")"
trap 'rm -f "${cache_err}"' EXIT

fetch_one() { # name version sha256 url member
    local name="$1" version="$2" want="$3" url="$4" member="$5"
    local file artifact="${url##*/}" tmp why
    # The cache's path has no file name, so the archive's kind is read from the URL's. Its stderr is kept apart so a
    # failure is named once, in the list below, and anything else it printed (a RETRY line) is passed on as it was.
    if ! file="$(bash "${SCRIPT_DIR}/artifact-cache.sh" get "${want}" "${url}" 2>"${cache_err}")"; then
        why="$(grep -m1 '^ARTIFACT CACHE FAILED: ' "${cache_err}" || true)"
        grep -v '^ARTIFACT CACHE FAILED: ' "${cache_err}" >&2 || true
        failed+=("${name} ${version}: ${why#ARTIFACT CACHE FAILED: }")
        return
    fi
    cat "${cache_err}" >&2
    tmp="$(mktemp "${TOOLS_DIR}/bin/.${name}.XXXXXX")"
    # A zip member is read with python3's zipfile, not unzip: Tanjiro's CI runner has no unzip and its account no
    # sudo to install one (#1047), and python3 is a prerequisite of both runners already.
    case "${member}:${artifact}" in
        -:*)        cp "${file}" "${tmp}" ;;
        *:*.tar.gz) tar -xzOf "${file}" "${member}" >"${tmp}" ;;
        *:*.tar.xz) tar -xJOf "${file}" "${member}" >"${tmp}" ;;
        *:*.zip)    python3 -c 'import sys, zipfile; sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[1]).read(sys.argv[2]))' \
                        "${file}" "${member}" >"${tmp}" ;;
        *)          false ;;
    esac || {
        rm -f "${tmp}"
        failed+=("${name} ${version}: could not extract ${member} from ${artifact} (${file})")
        return
    }
    if [[ ! -s "${tmp}" ]]; then
        rm -f "${tmp}"
        failed+=("${name} ${version}: ${member} in ${artifact} (${file}) is empty")
        return
    fi
    chmod 0755 "${tmp}"
    mv -f "${tmp}" "${TOOLS_DIR}/bin/${name}"
    count=$((count + 1))
    printf '  %-10s %-8s %s\n' "${name}" "${version}" "${TOOLS_DIR}/bin/${name}"
}

printf 'Fetching the E2E tier tools into %s, each download from the host artifact cache\n' "${TOOLS_DIR}/bin"
lines=0
while read -r name version sha url member extra; do
    [[ -z "${name}" || "${name}" == \#* ]] && continue
    lines=$((lines + 1))
    if [[ -z "${member}" || -n "${extra}" || ! "${sha}" =~ ^[0-9a-f]{64}$ ]]; then
        failed+=("e2e-tools.lock line for '${name}' is malformed: want name, version, sha256, url, member")
        continue
    fi
    fetch_one "${name}" "${version}" "${sha}" "${url}" "${member}"
done <"${LOCK}"

if [[ "${lines}" -eq 0 ]]; then
    failed+=("e2e-tools.lock names no tools")
fi
if [[ "${#failed[@]}" -gt 0 ]]; then
    printf 'E2E TOOLS FETCH FAILED; this is a failure, not a skip:\n' >&2
    printf '  - %s\n' "${failed[@]}" >&2
    exit 1
fi
printf '%d pinned tools ready\n' "${count}"
