#!/usr/bin/env bash
# ABOUTME: Builds Kyverno v1.19.1's admission, reports and background controllers with upstream's breaker fix
# ABOUTME: (kyverno#17085) over upstream's images, reproducibly, into a loopback registry; CI copies the pinned digests.
#
# Usage: CRANE=<crane 0.22.1> bash images/kyverno-counter-fix/build.sh <127.0.0.1:port>
#
# Why (#1015). Both Kyverno controllers that write reports gate every report on a breaker whose counter watches the
# EphemeralReports. In v1.19.1 that counter starts one RetryWatcher and never replaces it. When the apiserver answers
# its watch with 410 (too old resource version), the watcher stops for good, the counter reads as not running, and the
# breaker drops every report until the pod restarts. On 2026-11-08 the reports controller had dropped 26085 of 26403
# background-scan reports on watch-it-burn-community and the admission controller 1297 of 1300 admission reports, and
# no Pod created in agent after the controllers' first minutes had a PolicyReport. Upstream fixed it on main in
# 7c7042fb (kyverno#17085, 2026-09-10): the counter lists again and starts a new watcher. No release carries it but
# v1.20.0-rc.1; release-1.19 and v1.19.2 do not. pr17085.patch is that commit, byte for byte as GitHub serves it.
# The background controller runs the same counter for the reports of mutate-existing and generate rules, so it is
# rebuilt too, although no policy here has such a rule yet.
#
# What is built. The source is the v1.19.1 tag at the commit the running controllers log (40ec788d), with the patch
# applied. Only the three binaries that gate reports on that breaker are rebuilt: kyverno (the admission controller),
# reports-controller and background-controller. Each goes in as one layer at /ko-app/<name> on top of upstream's
# linux/amd64 image of the same release, pinned by the index digests images.lock records for v1.19.1, so the
# entrypoint, user, environment and kodata are upstream's. The nodes are AL2023_x86_64
# (infra/terraform/aws/cluster/main.tf), so amd64 only.
#
# Reproducible, so the digests are pinned before the first push (no run may write to ghcr.io), as the Jokers' are:
# the Go toolchain is fixed by GOTOOLCHAIN (go.mod's go1.26.6, fetched and checksummed by the go command), the build
# is -trimpath with VCS stamping off, the layer tar is ustar with fixed owner, mode and mtime, and crane 0.22.1
# (verify/e2e-tools.lock) appends it. The version string is v1.19.1-pr17085, so a controller's startup log line
# (version=...) and kyverno_info name the build it runs.
#
# Read from the host artifact cache (#1216), as the Jokers' build reads its base (#1122). Each base comes from
# verify/image_cache.py, an OCI layout keyed by its pinned index digest that reads reg.kyverno.io only on a miss and
# checks every blob on a hit. Its platform-layout verb writes the linux/amd64 image of that index as a layout of its own,
# crane pushes it to <addr>/kyverno-base/<name>, where it must land on that image's digest, and crane append builds on
# it there. A base by its amd64 image digest and a base by the index with --platform linux/amd64 append to the same
# digest, since crane append sets no base annotation unless asked, so the build is byte for byte the one built on
# reg.kyverno.io's copy. The source comes from verify/git_mirror.py, a bare mirror of the kyverno repository that
# reads GitHub only when it lacks KYVERNO_COMMIT and fails naming both hashes when its object is not that commit. The
# v1.19.1 tag in the mirror must name KYVERNO_COMMIT and the checkout's HEAD must be it, or the build stops naming
# both. On a warm cache the build reaches no registry but its own on loopback; the Go toolchain and modules still come
# through the go command's own proxy and checksum database.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY="$(cd "${HERE}/../../verify" && pwd)"
addr="${1:-}"
[[ "${addr}" =~ ^127\.0\.0\.1:[0-9]+$ ]] || { echo "build.sh: give a loopback registry, 127.0.0.1:<port>; got '${addr}'" >&2; exit 1; }
crane="${CRANE:-}"
[[ -n "${crane}" && -x "${crane}" ]] || { echo "build.sh: CRANE must name the pinned crane (verify/.tools/bin/crane); got '${crane}'" >&2; exit 1; }
[[ "$("${crane}" version)" == "0.22.1" ]] || { echo "build.sh: CRANE is crane $("${crane}" version), not 0.22.1" >&2; exit 1; }

KYVERNO_URL="https://github.com/kyverno/kyverno.git"
KYVERNO_TAG="v1.19.1"
KYVERNO_COMMIT="40ec788d48bb28d83dbf85538e962a59db9d45c6"
GO_TOOLCHAIN="go1.26.6"
PATCH_SHA256="254ebcfc83c11f74ec7bb0d43cef33dd1010340521f902e2634c3014946a7523"
BUILD_VERSION="v1.19.1-pr17085"
BINS=(kyverno reports-controller background-controller)
declare -A BASE=(
  [kyverno]="reg.kyverno.io/kyverno/kyverno:v1.19.1@sha256:b31d8511ae5fd6010e2a01ea72ebae08eb82fa51d91af14a1d9fe989949b4edb"
  [reports-controller]="reg.kyverno.io/kyverno/reports-controller:v1.19.1@sha256:c0eee97b9b44a0dd35805d56b358fa52548480f79d4944602b9609538eccd64c"
  [background-controller]="reg.kyverno.io/kyverno/background-controller:v1.19.1@sha256:8f1e9143373a27578cafc2d28d2c66ba0926c63b4c77e63de8d2fdd4a122859f"
)
declare -A TAG=(
  [kyverno]="kyverno-v1.19.1-pr17085"
  [reports-controller]="kyverno-reports-controller-v1.19.1-pr17085"
  [background-controller]="kyverno-background-controller-v1.19.1-pr17085"
)

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
echo "${PATCH_SHA256}  ${HERE}/pr17085.patch" | sha256sum -c --quiet - \
  || { echo "build.sh: pr17085.patch is not the upstream commit it pins (sha256 ${PATCH_SHA256})" >&2; exit 1; }

mirror="$(python3 "${VERIFY}/git_mirror.py" ensure "${KYVERNO_URL}" "${KYVERNO_COMMIT}")" \
  || { echo "build.sh: the host artifact cache's mirror could not serve ${KYVERNO_URL} at ${KYVERNO_COMMIT}" >&2; exit 1; }
tagged="$(git --git-dir "${mirror}" rev-parse --verify --quiet "refs/tags/${KYVERNO_TAG}^{commit}")" \
  || { echo "build.sh: the mirror ${mirror} has no tag ${KYVERNO_TAG}" >&2; exit 1; }
[[ "${tagged}" == "${KYVERNO_COMMIT}" ]] \
  || { echo "build.sh: kyverno ${KYVERNO_TAG} is ${tagged} in the mirror ${mirror}, not ${KYVERNO_COMMIT}" >&2; exit 1; }
# --shared reads the mirror's objects in place (the mirror never runs gc), so nothing is copied and nothing is fetched.
git clone --quiet --shared --no-checkout "${mirror}" "${tmp}/src"
git -C "${tmp}/src" -c advice.detachedHead=false checkout --quiet --detach "${KYVERNO_COMMIT}"
head="$(git -C "${tmp}/src" rev-parse HEAD)"
[[ "${head}" == "${KYVERNO_COMMIT}" ]] \
  || { echo "build.sh: the kyverno checkout from ${mirror} is at ${head}, not ${KYVERNO_COMMIT}" >&2; exit 1; }
git -C "${tmp}/src" apply "${HERE}/pr17085.patch"

declare -A LOCAL_BASE=()
for bin in "${BINS[@]}"; do
  digest="$(python3 "${VERIFY}/image_cache.py" platform-layout "${BASE[${bin}]}" "${tmp}/base-${bin}" linux/amd64)" \
    || { echo "build.sh: the host artifact cache could not serve ${BASE[${bin}]}" >&2; exit 1; }
  LOCAL_BASE[${bin}]="${addr}/kyverno-base/${bin}@${digest}"
  pushed="$("${crane}" --insecure push "${tmp}/base-${bin}" "${addr}/kyverno-base/${bin}")"
  [[ "${pushed}" == "${LOCAL_BASE[${bin}]}" ]] \
    || { echo "build.sh: the cached base ${BASE[${bin}]} pushed as '${pushed}', not ${LOCAL_BASE[${bin}]}" >&2; exit 1; }
done

export GOTOOLCHAIN="${GO_TOOLCHAIN}" CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOAMD64=v1 GOFLAGS=-buildvcs=false
go_version="$(cd "${tmp}/src" && go env GOVERSION)"
[[ "${go_version}" == "${GO_TOOLCHAIN}" ]] || { echo "build.sh: go is ${go_version}, not ${GO_TOOLCHAIN}" >&2; exit 1; }

for bin in "${BINS[@]}"; do
  mkdir -p "${tmp}/layer-${bin}/ko-app"
  (cd "${tmp}/src" && go build -trimpath \
    -ldflags "-s -w -X github.com/kyverno/kyverno/pkg/version.BuildVersion=${BUILD_VERSION}" \
    -o "${tmp}/layer-${bin}/ko-app/${bin}" "./cmd/${bin}")
  # One file entry and no directory entry, so upstream's /ko-app keeps its own mode; ko writes the binary 0555.
  tar --format=ustar --owner=0 --group=0 --numeric-owner --mtime=@0 --mode=0555 \
    -C "${tmp}/layer-${bin}" -cf "${tmp}/${bin}.tar" "ko-app/${bin}"
  ref="${addr}/peopleforrester/watch-it-burn:${TAG[${bin}]}"
  "${crane}" --insecure append --platform linux/amd64 -b "${LOCAL_BASE[${bin}]}" -f "${tmp}/${bin}.tar" -t "${ref}"
  "${crane}" --insecure mutate "${ref}" \
    --label "io.github.peopleforrester.watch-it-burn.kyverno-patch=kyverno/kyverno#17085 7c7042fb5fd9f6855ed1c5287d1233867a160b5f" \
    -t "${ref}" >/dev/null
  echo "built ${ref} $("${crane}" --insecure digest "${ref}")"
done
