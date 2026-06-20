#!/usr/bin/env bash
# ABOUTME: Builds, pushes, and cosign-signs a demo image into Harbor (the signed-image path for attack 2).
# ABOUTME: Keyless signing (Fulcio/Rekor). verify-at-build: set HARBOR_HOST + the CI identity that signs.
set -euo pipefail
HARBOR_HOST="${HARBOR_HOST:?set HARBOR_HOST (e.g. harbor.agenticburn.com)}"
IMAGE="${1:?usage: sign-and-push.sh <repo/name:tag> [build-context]}"
CTX="${2:-.}"
REF="${HARBOR_HOST}/${IMAGE}"
command -v cosign >/dev/null 2>&1 || { echo "cosign not found" >&2; exit 1; }
echo "==> build + push ${REF}" >&2
docker build -t "${REF}" "${CTX}"
docker push "${REF}"
echo "==> cosign sign (keyless) ${REF}" >&2
COSIGN_EXPERIMENTAL=1 cosign sign --yes "${REF}"   # verify-at-build: keyless via Fulcio/Rekor (CI OIDC)
echo "==> signed. Harbor images now satisfy verify-image-signatures (Enforce)." >&2
