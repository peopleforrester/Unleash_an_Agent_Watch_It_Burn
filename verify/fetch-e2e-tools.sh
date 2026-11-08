#!/usr/bin/env bash
# ABOUTME: Fetches the cluster-free E2E tier's pinned binaries (e2e-tools.lock) into verify/.tools/bin, which git
# ABOUTME: ignores, and checks each download's SHA-256 before using it. Any failed fetch or mismatch exits 1 (#572).
#
# Usage: bash verify/fetch-e2e-tools.sh
#
# Each download comes from the host's artifact cache by the lock's SHA-256 (verify/artifact-cache.sh, #1117, #1118),
# which keeps one copy per host outside every worktree, re-checks the sum on every hit, and goes to the network only
# on a miss, retrying one the network broke. So a second run on the host, from any worktree, downloads nothing, and a
# cached file that no longer matches its sum fails by name and is never fetched again over it. Before #1118 each
# worktree kept its own copy in .tools/dl, about 3.1 GB a run (#1004); that directory is removed here. The binaries
# are always extracted again from the verified file, so .tools/bin never holds a binary the lock does not vouch for,
# and a tool whose fetch fails has its old binary removed. Every tool is tried before exiting, so one run names every
# failure.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK="${SCRIPT_DIR}/e2e-tools.lock"
TOOLS_DIR="${SCRIPT_DIR}/.tools"
CACHE="${SCRIPT_DIR}/artifact-cache.sh"

# The lock pins linux/x86_64 artifacts only; on anything else they would not run, so say so instead of trying.
platform="$(uname -s) $(uname -m)"
if [[ "${platform}" != "Linux x86_64" ]]; then
    printf 'E2E TOOLS FETCH FAILED: e2e-tools.lock pins Linux x86_64 binaries; this host is %s\n' "${platform}" >&2
    exit 1
fi
[[ -f "${LOCK}" ]] || { printf 'E2E TOOLS FETCH FAILED: %s is missing\n' "${LOCK}" >&2; exit 1; }

if ! root="$(bash "${CACHE}" root 2>&1)"; then
    printf 'E2E TOOLS FETCH FAILED: no usable artifact cache: %s\n' "${root#ARTIFACT CACHE FAILED: }" >&2
    exit 1
fi
rm -rf "${TOOLS_DIR}/dl"
mkdir -p "${TOOLS_DIR}/bin"
errlog="$(mktemp "${TOOLS_DIR}/.fetch-err.XXXXXX")"
trap 'rm -f "${errlog}"' EXIT
failed=()
count=0

fetch_one() { # name version sha256 url member
    local name="$1" version="$2" want="$3" url="$4" member="$5"
    local file tmp why
    if ! file="$(bash "${CACHE}" get "${want}" "${url}" 2>"${errlog}")"; then
        grep -v '^ARTIFACT CACHE FAILED: ' "${errlog}" >&2 || true
        rm -f "${TOOLS_DIR}/bin/${name}"
        why="$(sed -n 's/^ARTIFACT CACHE FAILED: //p' "${errlog}" | tail -n 1)"
        failed+=("${name} ${version}: ${why:-artifact-cache.sh failed: $(tail -n 1 "${errlog}")}")
        return
    fi
    cat "${errlog}" >&2
    tmp="$(mktemp "${TOOLS_DIR}/bin/.${name}.XXXXXX")"
    # The cached file is named by its sum alone, so the archive kind is read off the URL. A zip member is read with
    # python3's zipfile, not unzip: Tanjiro's CI runner has no unzip and its account no sudo to install one (#1047), and
    # python3 is a prerequisite of both runners already.
    case "${member}:${url}" in
        -:*)        cp "${file}" "${tmp}" ;;
        *:*.tar.gz) tar -xzOf "${file}" "${member}" >"${tmp}" ;;
        *:*.tar.xz) tar -xJOf "${file}" "${member}" >"${tmp}" ;;
        *:*.zip)    python3 -c 'import sys, zipfile; sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[1]).read(sys.argv[2]))' \
                        "${file}" "${member}" >"${tmp}" ;;
        *)          false ;;
    esac || {
        rm -f "${tmp}" "${TOOLS_DIR}/bin/${name}"
        failed+=("${name} ${version}: could not extract ${member} from ${url##*/} (${file})")
        return
    }
    if [[ ! -s "${tmp}" ]]; then
        rm -f "${tmp}" "${TOOLS_DIR}/bin/${name}"
        failed+=("${name} ${version}: ${member} in ${url##*/} is empty")
        return
    fi
    chmod 0755 "${tmp}"
    mv -f "${tmp}" "${TOOLS_DIR}/bin/${name}"
    count=$((count + 1))
    printf '  %-10s %-8s %s\n' "${name}" "${version}" "${TOOLS_DIR}/bin/${name}"
}

printf 'Fetching the E2E tier tools into %s, from the artifact cache at %s\n' "${TOOLS_DIR}/bin" "${root}"
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
