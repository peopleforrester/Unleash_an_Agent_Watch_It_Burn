#!/usr/bin/env bash
# ABOUTME: Builds, pushes, and cosign-signs a demo image into Harbor (the signed-image path for attack 2).
# ABOUTME: Key-based signing with the same key as every other image we publish; see policies/cosign/.
set -euo pipefail
HARBOR_HOST="${HARBOR_HOST:?set HARBOR_HOST (e.g. harbor.agenticburn.com)}"
IMAGE="${1:?usage: sign-and-push.sh <repo/name:tag> [build-context]}"
CTX="${2:-.}"
REF="${HARBOR_HOST}/${IMAGE}"
command -v cosign >/dev/null 2>&1 || { echo "cosign not found" >&2; exit 1; }
echo "==> build + push ${REF}" >&2
docker build -t "${REF}" "${CTX}"
docker push "${REF}"
# Key-based, not keyless, and with cosign 2.x. Both choices are forced, and the reasons are in
# policies/cosign/README.md: there is no CI identity that signs these, and cosign 3.x writes a bundle
# format Kyverno 1.19 reports as "no signatures found" while `cosign verify` passes.
COSIGN="${WIB_COSIGN:-cosign}"
ver="$("${COSIGN}" version 2>/dev/null | awk '/GitVersion/{print $2}')"
case "${ver}" in
    v2.*) : ;;
    *) echo "refusing to sign with cosign ${ver:-unknown}: Kyverno cannot verify the 3.x format" >&2
       echo "see policies/cosign/README.md; set WIB_COSIGN to a 2.x binary" >&2
       exit 1 ;;
esac
KEY="${WIB_COSIGN_KEY:-${HOME}/secrets/cosign/watch-it-burn.key}"
PWFILE="${WIB_COSIGN_PW:-${HOME}/secrets/cosign/watch-it-burn.pw}"
# Resolve the digest and sign THAT: a tag is a moving pointer and the signature belongs to the artifact.
DIGEST="$(docker inspect --format '{{index .RepoDigests 0}}' "${REF}" 2>/dev/null | cut -d@ -f2)"
[[ -n "${DIGEST}" ]] || { echo "could not resolve the pushed digest for ${REF}" >&2; exit 1; }
echo "==> cosign sign ${HARBOR_HOST}/${IMAGE%%:*}@${DIGEST}" >&2
COSIGN_PASSWORD="$(cat "${PWFILE}")" "${COSIGN}" sign --key "${KEY}" --tlog-upload=false --yes \
    "${HARBOR_HOST}/${IMAGE%%:*}@${DIGEST}"
"${COSIGN}" verify --key "$(dirname "${BASH_SOURCE[0]}")/../../policies/cosign/watch-it-burn.pub" \
    --insecure-ignore-tlog "${HARBOR_HOST}/${IMAGE%%:*}@${DIGEST}" >/dev/null
echo "==> signed and verified. Harbor images satisfy verify-image-signatures (Enforce)." >&2
