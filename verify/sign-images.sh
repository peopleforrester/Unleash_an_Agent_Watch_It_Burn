#!/usr/bin/env bash
# ABOUTME: Sign every watch-it-burn digest images.lock and the manifests pin, by digest, in the format Kyverno can
# ABOUTME: actually verify, and prove each signature before returning. Run this after any image build, before deploying.
#
# COSIGN v3 SIGNATURES DO NOT VERIFY UNDER KYVERNO 1.19. That is the reason this script pins a version.
#
# cosign 3.x writes the new Sigstore bundle format unconditionally: the signature lands on a
# `sha256-<digest>` tag with no suffix, and there is no --new-bundle-format flag left to opt out.
# Kyverno 1.19.1 looks for the legacy `sha256-<digest>.sig` tag and reports "no signatures found",
# while `cosign verify` on the same image passes. Measured on 2026-09-30 with the Kyverno CLI at the
# cluster's own version, after first getting a false negative from CLI 1.17.1 and having to rule out
# the instrument. Signing the same digest with cosign 2.6.5 produced a `.sig` tag and Kyverno passed.
#
# So: sign with v2 until Kyverno can read the new format. If this script is ever changed to use the
# cosign on PATH, verify against the Kyverno CLI at the CLUSTER's version before believing it works.
#
# Usage: verify/sign-images.sh [--check|--list]
#   (no args)  sign every pinned digest, then verify each one
#   --check    verify only, sign nothing; exits non-zero if any digest is unsigned
#   --list     print the digests it would sign, one per line, and nothing else; needs no cosign and no network
#
# The list is verify/wib_pins.py's (#1285), the one verify/test_wib_digests_signed.py checks: every
# ghcr.io/peopleforrester/watch-it-burn...@sha256 digest images.lock's digest column holds, or a manifest pins, on an
# image: key, a FROM or ARG, a shell variable, or a Helm values or kustomize block that splits it into repository and
# tag. This script once found tags on image: keys and Dockerfile FROM/ARG lines and asked the registry which digest each
# tag served now. That missed the Kyverno counter-fix builds, which gitops/bootstrap/apps/kyverno.yaml names as Helm
# repository and tag values, and the llm-guard zero-shot model, pinned only in images.lock (#1282), and for a tag that
# had moved it signed the new digest rather than the pinned one. Signing the pinned digest itself has neither fault.
# verify/test_sign_images_list.py holds this list to wib_pins' offline.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
REGISTRY="ghcr.io/peopleforrester/watch-it-burn"
PUB="${REPO}/policies/cosign/watch-it-burn.pub"
KEY="${WIB_COSIGN_KEY:-${HOME}/secrets/cosign/watch-it-burn.key}"
PWFILE="${WIB_COSIGN_PW:-${HOME}/secrets/cosign/watch-it-burn.pw}"
COSIGN="${WIB_COSIGN:-cosign2}"
CHECK_ONLY=0
LIST_ONLY=0
case "${1:-}" in
    "") : ;;
    --check) CHECK_ONLY=1 ;;
    --list) LIST_ONLY=1 ;;
    *) echo "usage: verify/sign-images.sh [--check|--list]" >&2; exit 2 ;;
esac

# Each line is "<registry>/<package>@sha256:<hex> <where it is pinned>". wib_pins.py exits 1, naming the source, when
# images.lock or the manifests yield no digest: that is the reader broken, not a repo with nothing to sign.
pins="$(python3 "${HERE}/wib_pins.py" refs "${REPO}")" || {
    echo "verify/wib_pins.py could not read the pinned digests: the reader is broken, not the manifests" >&2
    exit 1
}
mapfile -t lines <<<"${pins}"
[[ -n "${pins}" && "${#lines[@]}" -gt 0 ]] || { echo "no pinned digests found: the reader is broken" >&2; exit 1; }

if [[ "${LIST_ONLY}" -eq 1 ]]; then
    for line in "${lines[@]}"; do echo "${line%% *}"; done
    exit 0
fi

command -v "${COSIGN}" >/dev/null 2>&1 || {
    echo "missing ${COSIGN}. This must be cosign 2.x: see the header for why." >&2
    exit 1
}
ver="$("${COSIGN}" version 2>/dev/null | awk '/GitVersion/{print $2}')"
case "${ver}" in
    v2.*) : ;;
    *) echo "refusing to sign with cosign ${ver:-unknown}: Kyverno cannot verify the 3.x format (see header)" >&2
       exit 1 ;;
esac

fail=0
for line in "${lines[@]}"; do
    ref="${line%% *}"
    at="${line#* }"
    case "${ref}" in
        "${REGISTRY}"*@sha256:*) : ;;
        *) printf '%s  NOT A DIGEST OF OURS (%s)\n' "${ref}" "${at}"; fail=1; continue ;;
    esac
    printf '%s  ' "${ref}"
    if [[ "${CHECK_ONLY}" -eq 0 ]]; then
        # Sign the DIGEST, never the tag: the signature belongs to the artifact, not to a pointer.
        COSIGN_PASSWORD="$(cat "${PWFILE}")" "${COSIGN}" sign --key "${KEY}" --tlog-upload=false --yes "${ref}" \
            >/dev/null 2>&1 && printf 'signed  ' || { printf 'SIGN FAILED  (%s)\n' "${at}"; fail=1; continue; }
    fi
    # --insecure-ignore-tlog matches the policy's rekor.ignoreTlog: verify the path the cluster uses.
    if "${COSIGN}" verify --key "${PUB}" --insecure-ignore-tlog "${ref}" >/dev/null 2>&1; then
        echo "verified  (${at})"
    else
        echo "NOT VERIFIED  (${at})"; fail=1
    fi
done

if [[ "${fail}" -ne 0 ]]; then
    echo
    echo "At least one pinned digest is unsigned or unverifiable, and verify-image-signatures is Enforce," >&2
    echo "so a cluster would DENY it at admission. Fix before deploying." >&2
    exit 1
fi
echo
echo "all ${#lines[@]} pinned digests signed and verified against policies/cosign/watch-it-burn.pub"
