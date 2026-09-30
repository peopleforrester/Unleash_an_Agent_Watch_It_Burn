#!/usr/bin/env bash
# ABOUTME: Sign every image the manifests reference, in the format Kyverno can actually verify, and
# ABOUTME: prove each signature before returning. Run this after any image build, before deploying.
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
# Usage: verify/sign-images.sh [--check]
#   (no args)  sign every referenced image, then verify each one
#   --check    verify only, sign nothing; exits non-zero if any image is unsigned
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
REGISTRY="ghcr.io/peopleforrester/watch-it-burn"
PUB="${REPO}/policies/cosign/watch-it-burn.pub"
KEY="${WIB_COSIGN_KEY:-${HOME}/secrets/cosign/watch-it-burn.key}"
PWFILE="${WIB_COSIGN_PW:-${HOME}/secrets/cosign/watch-it-burn.pw}"
COSIGN="${WIB_COSIGN:-cosign2}"
CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

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

# Every distinct tag of ours, from BOTH places one can be named:
#
#   - a manifest `image:` line, with the comment stripped first, so an '@sha256' inside a comment
#     cannot be mistaken for a digest (that mistake once made a sweep report "none left" while two
#     files were still unpinned);
#   - a Dockerfile, where an image can arrive as a FROM or a build ARG and never appear in any
#     manifest. llm-guard-model is exactly that: consumed by images/llm-guard/Dockerfile as
#     ARG MODEL_IMAGE, so a manifest-only scan signed seven of our eight images and called it done.
mapfile -t tags < <( {
    grep -rhE "^[[:space:]]*image:" "${REPO}" --include=*.yaml 2>/dev/null | sed 's/#.*//'
    grep -rhE "^[[:space:]]*(FROM|ARG)[[:space:]]" "${REPO}"/images --include=Dockerfile 2>/dev/null | sed 's/#.*//'
  } | grep -oE "${REGISTRY}:[A-Za-z0-9._-]+" \
    | sed "s|${REGISTRY}:||" | sort -u)
[[ "${#tags[@]}" -gt 0 ]] || { echo "no images found: the matcher is broken, not the manifests" >&2; exit 1; }

token="$(curl -sS "https://ghcr.io/token?scope=repository:peopleforrester/watch-it-burn:pull&service=ghcr.io" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')"

fail=0
for tag in "${tags[@]}"; do
    digest="$(curl -sS -D- -o /dev/null -H "Authorization: Bearer ${token}" \
        -H 'Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json' \
        "https://ghcr.io/v2/peopleforrester/watch-it-burn/manifests/${tag}" 2>/dev/null \
        | grep -i '^docker-content-digest:' | tr -d '\r' | awk '{print $2}')"
    if [[ -z "${digest}" ]]; then
        printf '%-30s NOT IN THE REGISTRY\n' "${tag}"; fail=1; continue
    fi
    ref="${REGISTRY}@${digest}"
    printf '%-30s ' "${tag}"
    if [[ "${CHECK_ONLY}" -eq 0 ]]; then
        # Sign the DIGEST, never the tag: the signature belongs to the artifact, not to a pointer.
        COSIGN_PASSWORD="$(cat "${PWFILE}")" "${COSIGN}" sign --key "${KEY}" --tlog-upload=false --yes "${ref}" \
            >/dev/null 2>&1 && printf 'signed  ' || { printf 'SIGN FAILED\n'; fail=1; continue; }
    fi
    # --insecure-ignore-tlog matches the policy's rekor.ignoreTlog: verify the path the cluster uses.
    if "${COSIGN}" verify --key "${PUB}" --insecure-ignore-tlog "${ref}" >/dev/null 2>&1; then
        echo "verified"
    else
        echo "NOT VERIFIED"; fail=1
    fi
done

if [[ "${fail}" -ne 0 ]]; then
    echo
    echo "At least one image is unsigned or unverifiable, and verify-image-signatures is Enforce," >&2
    echo "so a cluster would DENY it at admission. Fix before deploying." >&2
    exit 1
fi
echo
echo "all ${#tags[@]} images signed and verified against policies/cosign/watch-it-burn.pub"
