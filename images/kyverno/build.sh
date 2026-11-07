#!/usr/bin/env bash
# ABOUTME: Builds Kyverno v1.19.1's admission controller and reports controller with upstream's breaker fix,
# ABOUTME: kyverno/kyverno#17085, into a loopback registry only (#1015). push-kyverno.yml copies each to its pinned tag.
#
# Usage: CRANE=<crane> bash images/kyverno/build.sh <127.0.0.1:port>
#
# Why (#1015). Both Kyverno controllers that write reports guard the write with a circuit breaker
# (pkg/breaker). The breaker counts EphemeralReports through a RetryWatcher, and it counts as open, so every report
# is dropped, whenever that watcher is not running. In v1.19.1 the watcher stops for good the first time the API
# server answers its watch with 410 Gone (too old resource version), and nothing restarts it, so the controller
# writes no report for any new resource until its pod is restarted. On 2026-11-07 both KubeCon clusters showed it:
# kyverno_breaker_drops_total had dropped 14386 of 14704 background-scan writes on community and 717 of 720
# admission writes, and no EphemeralReport existed for the count to be over its limit. Upstream fixed it on main in
# #17085 (merged 2026-09-10): the counter lists again and starts a new watcher when the old one ends. That is in
# v1.20.0-rc.1 and in no 1.19 release, v1.19.2 included.
#
# What this builds. The kyverno and reports-controller images of the v1.19.1 tag, each with one layer laid over
# upstream's own image (the digests images.lock pins): /ko-app/<binary> rebuilt from the v1.19.1 commit with
# 17085-breaker-recovery.patch applied, which is #17085's diff as merged (its three files, the recovery tests among
# them). Before building, upstream's recovery tests run on the patched tree. Nothing else in the images changes:
# the entrypoint, the user (65532), the CA bundle and ko's LICENSE and NOTICE are upstream's.
#
# The build is reproducible: the Go toolchain is pinned (GOTOOLCHAIN downloads exactly that one, checked against
# Go's checksum database), the binaries are built with -trimpath and no VCS stamp, and the layer's tar sets owner,
# mtime, order and modes, which crane 0.22.1 compresses the same way each time. So images.lock pins each digest
# before it is pushed, verify/test_kyverno_build_digest.py rebuilds both and holds them to those pins, and
# .github/workflows/push-kyverno.yml pushes a build to its tag only when its digest is the pin. A run may not write
# to ghcr.io, and this script cannot: the registry must be loopback.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
addr="${1:-}"
[[ "${addr}" =~ ^127\.0\.0\.1:[0-9]+$ ]] || { echo "build.sh: give a loopback registry, 127.0.0.1:<port>; got '${addr}'" >&2; exit 1; }
CR="${CRANE:-}"
[[ -n "${CR}" && -x "${CR}" ]] || { echo "build.sh: CRANE must name the pinned crane (verify/.tools/bin/crane); got '${CR}'" >&2; exit 1; }
command -v go >/dev/null || { echo "build.sh: no go on PATH; any go 1.21 or later fetches the pinned toolchain" >&2; exit 1; }

KYVERNO_TAG="v1.19.1"
KYVERNO_COMMIT="40ec788d48bb28d83dbf85538e962a59db9d45c6"
# v1.19.1's go.mod says go 1.26.6 and names no toolchain.
GO_TOOLCHAIN="go1.26.6"
# What the binaries report as their version (kyverno_info and the OpenTelemetry service.version): the release, and
# the upstream PR as build metadata, so a scrape of :8000/metrics tells this build from upstream's.
BUILD_VERSION="${KYVERNO_TAG}+17085"
PATCH="${HERE}/17085-breaker-recovery.patch"
# Upstream's images, as images.lock pins them; the linux/amd64 image of each is the base (the nodes are x86_64).
KYVERNO_BASE="reg.kyverno.io/kyverno/kyverno:v1.19.1@sha256:b31d8511ae5fd6010e2a01ea72ebae08eb82fa51d91af14a1d9fe989949b4edb"
REPORTS_BASE="reg.kyverno.io/kyverno/reports-controller:v1.19.1@sha256:c0eee97b9b44a0dd35805d56b358fa52548480f79d4944602b9609538eccd64c"
# The tags gitops/bootstrap/apps/kyverno.yaml runs, in the public package the clusters already pull from.
KYVERNO_REF="ghcr.io/peopleforrester/watch-it-burn:kyverno-v1.19.1-17085"
REPORTS_REF="ghcr.io/peopleforrester/watch-it-burn:kyverno-reports-controller-v1.19.1-17085"
LABEL="io.github.peopleforrester.watch-it-burn.kyverno-patch=https://github.com/kyverno/kyverno/pull/17085"

export GOTOOLCHAIN="${GO_TOOLCHAIN}" CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOAMD64=v1 GOFLAGS=-mod=readonly
unset GOEXPERIMENT
got_go="$(go env GOVERSION)"
[[ "${got_go}" == "${GO_TOOLCHAIN}" ]] || { echo "build.sh: go is ${got_go}, not ${GO_TOOLCHAIN}" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
src="${tmp}/kyverno"
git -c advice.detachedHead=false clone -q --depth 1 --branch "${KYVERNO_TAG}" https://github.com/kyverno/kyverno.git "${src}"
head="$(git -C "${src}" rev-parse HEAD)"
[[ "${head}" == "${KYVERNO_COMMIT}" ]] || { echo "build.sh: ${KYVERNO_TAG} is ${head}, not ${KYVERNO_COMMIT}" >&2; exit 1; }
git -C "${src}" apply "${PATCH}"
echo "build.sh: upstream's recovery tests on the patched tree"
(cd "${src}" && go test -count=1 ./pkg/breaker/ ./cmd/kyverno/watch/)

# build_one <cmd dir> <binary name> <base> <ref>
build_one() {
  local cmd="$1" bin="$2" base="$3" ref="$4" out="${tmp}/layer-$2"
  mkdir -p "${out}/ko-app"
  (cd "${src}" && go build -trimpath -buildvcs=false \
    -ldflags "-s -w -X github.com/kyverno/kyverno/pkg/version.BuildVersion=${BUILD_VERSION}" \
    -o "${out}/ko-app/${bin}" "./${cmd}")
  # ko's own layer: ko-app/ and the binary, both r-xr-xr-x and root-owned, at the epoch.
  tar --owner=0 --group=0 --numeric-owner --mtime=@0 --sort=name --mode='a=rx' -C "${out}" -cf "${out}.tar" ko-app
  local here="${ref/ghcr.io\//${addr}/}"
  "${CR}" --insecure append --platform linux/amd64 -b "${base}" -f "${out}.tar" -t "${here}"
  "${CR}" --insecure mutate "${here}" --label "${LABEL}" -t "${here}"
  echo "build.sh: built ${here} ($("${CR}" --insecure digest "${here}")), for ${ref}"
}
build_one cmd/kyverno kyverno "${KYVERNO_BASE}" "${KYVERNO_REF}"
build_one cmd/reports-controller reports-controller "${REPORTS_BASE}" "${REPORTS_REF}"
echo "build.sh: both went to ${addr} only, and nothing left this host"
