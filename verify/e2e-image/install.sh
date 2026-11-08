#!/usr/bin/env bash
# ABOUTME: Build-time installer of the wib-e2e-tools image (#1188): fetches one pinned file, checks its SHA-256 before
# ABOUTME: anything reads it, and unpacks it. Run only by verify/e2e-image/Containerfile; any mismatch fails the build.
#
# Usage, from the Containerfile:
#   install.sh tool <name> <version> <sha256> <url> <member>   one e2e-tools.lock row: the binary goes to
#                                                               $WIB_E2E_TOOLS/bin/<name> and the row's name, version
#                                                               and sum to $WIB_E2E_TOOLS/tools.txt
#   install.sh bin <dir> <name> <sha256> <url> <member>         a runtime binary the lock does not cover (uv)
#
# <member> is the archive member that is the binary, or "-" when the URL is the binary itself, as in e2e-tools.lock.
# Each file is fetched once, here, at build time; a host that runs the image never fetches it (#1188).
set -euo pipefail

die() { printf 'E2E IMAGE BUILD FAILED: %s\n' "$*" >&2; exit 1; }

fetch() { # url sha256 -> path of the verified download
    local url="$1" want="$2" file got
    [[ "${want}" =~ ^[0-9a-f]{64}$ ]] || die "${url}: '${want}' is not a SHA-256"
    file="$(mktemp /tmp/wib-e2e-fetch.XXXXXX)"
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 5 -o "${file}" "${url}" || die "could not fetch ${url}"
    got="$(sha256sum "${file}" | awk '{print $1}')"
    [[ "${got}" == "${want}" ]] || die "${url} has SHA-256 ${got}, and the pin is ${want}"
    printf '%s\n' "${file}"
}

member_out() { # file url member dest: write the member (or the file itself) to dest
    local file="$1" url="$2" member="$3" dest="$4"
    case "${member}:${url}" in
        -:*)        cp "${file}" "${dest}" ;;
        *:*.tar.gz) tar -xzOf "${file}" "${member}" >"${dest}" ;;
        *:*.tar.xz) tar -xJOf "${file}" "${member}" >"${dest}" ;;
        *:*.zip)    unzip -p "${file}" "${member}" >"${dest}" ;;
        *)          die "${url}: no way to read ${member} from it" ;;
    esac || die "could not read ${member} from ${url##*/}"
    [[ -s "${dest}" ]] || die "${member} in ${url##*/} is empty"
    chmod 0755 "${dest}"
}

verb="${1:-}"
shift || true
case "${verb}" in
    tool)
        [[ $# -eq 5 ]] || die "tool wants <name> <version> <sha256> <url> <member>, got: $*"
        name="$1" version="$2" sha="$3" url="$4" member="$5"
        : "${WIB_E2E_TOOLS:?the Containerfile sets WIB_E2E_TOOLS}"
        mkdir -p "${WIB_E2E_TOOLS}/bin"
        file="$(fetch "${url}" "${sha}")"
        member_out "${file}" "${url}" "${member}" "${WIB_E2E_TOOLS}/bin/${name}"
        rm -f "${file}"
        printf '%s %s %s\n' "${name}" "${version}" "${sha}" >>"${WIB_E2E_TOOLS}/tools.txt"
        printf '  %-16s %-9s %s\n' "${name}" "${version}" "${WIB_E2E_TOOLS}/bin/${name}"
        ;;
    bin)
        [[ $# -eq 5 ]] || die "bin wants <dir> <name> <sha256> <url> <member>, got: $*"
        dir="$1" name="$2" sha="$3" url="$4" member="$5"
        mkdir -p "${dir}"
        file="$(fetch "${url}" "${sha}")"
        member_out "${file}" "${url}" "${member}" "${dir}/${name}"
        rm -f "${file}"
        ;;
    *)
        die "unknown verb '${verb}'; want tool or bin"
        ;;
esac
