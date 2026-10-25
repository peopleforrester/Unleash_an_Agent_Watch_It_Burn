#!/usr/bin/env bash
# ABOUTME: Fetches the cluster-free E2E tier's pinned binaries (e2e-tools.lock) into verify/.tools/bin, which git
# ABOUTME: ignores, and checks each download's SHA-256 before using it. Any failed fetch or mismatch exits 1 (#572).
#
# Usage: bash verify/fetch-e2e-tools.sh
#
# Downloads are kept in .tools/dl and reused only while their checksum still matches the lock, so a second run
# needs no network. The binaries are always extracted again from a verified download, so .tools/bin never holds
# a binary the lock does not vouch for. Every tool is tried before exiting, so one run names every failure.
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

mkdir -p "${TOOLS_DIR}/dl" "${TOOLS_DIR}/bin"
failed=()
count=0

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

fetch_one() { # name version sha256 url member
    local name="$1" version="$2" want="$3" url="$4" member="$5"
    local file="${TOOLS_DIR}/dl/${url##*/}" got tmp
    if [[ ! -f "${file}" || "$(sha_of "${file}")" != "${want}" ]]; then
        rm -f "${file}" "${file}.part"
        if ! curl -fsSL --retry 3 --connect-timeout 20 --max-time 600 -o "${file}.part" "${url}"; then
            rm -f "${file}.part"
            failed+=("${name} ${version}: download failed: ${url}")
            return
        fi
        got="$(sha_of "${file}.part")"
        if [[ "${got}" != "${want}" ]]; then
            rm -f "${file}.part"
            failed+=("${name} ${version}: SHA-256 mismatch for ${url}: expected ${want}, got ${got}")
            return
        fi
        mv "${file}.part" "${file}"
    fi
    tmp="$(mktemp "${TOOLS_DIR}/bin/.${name}.XXXXXX")"
    case "${member}:${file}" in
        -:*)        cp "${file}" "${tmp}" ;;
        *:*.tar.gz) tar -xzOf "${file}" "${member}" >"${tmp}" ;;
        *:*.zip)    unzip -p "${file}" "${member}" >"${tmp}" ;;
        *)          false ;;
    esac || {
        rm -f "${tmp}"
        failed+=("${name} ${version}: could not extract ${member} from ${file##*/}")
        return
    }
    if [[ ! -s "${tmp}" ]]; then
        rm -f "${tmp}"
        failed+=("${name} ${version}: ${member} in ${file##*/} is empty")
        return
    fi
    chmod 0755 "${tmp}"
    mv -f "${tmp}" "${TOOLS_DIR}/bin/${name}"
    count=$((count + 1))
    printf '  %-10s %-8s %s\n' "${name}" "${version}" "${TOOLS_DIR}/bin/${name}"
}

printf 'Fetching the E2E tier tools into %s\n' "${TOOLS_DIR}/bin"
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
