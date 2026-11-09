#!/usr/bin/env bash
# ABOUTME: Builds kagent v0.10.1's Go agent runtime (golang-adk) with its MCP client sending the active span's W3C
# ABOUTME: trace context (#1222), reproducibly, over upstream's image into a loopback registry; CI copies the pinned digest.
#
# Usage: CRANE=<crane 0.22.1> bash images/kagent-mcp-traceparent/build.sh <127.0.0.1:port>
#
# Why (#1222, found by #877). golang-adk v0.10.1 builds its MCP client on a plain http.Transport
# (go/adk/pkg/mcp/registry.go, createTransport), so a tool call's request carries no trace context of the
# execute_tool span that makes it. The gateway's tools/call pair for an evil-mcp call is then a trace of its own, and
# a workshop-mcp call, which carries the traceparent kagent forwards from its A2A request (agent.yaml's
# allowedHeaders, #885), hangs under the gateway's A2A hop instead of under the tool span. Read in Tempo on
# watch-it-burn-private on 2026-11-09 over the three days before: all 176 evil-mcp calls were traces of their own;
# workshop-mcp's 418 calls up to 2026-11-07 06:03Z were too, and its 299 since 12:54Z, after #885's forward synced,
# were in the turn's trace, under the gateway's A2A client span. Upstream fixed the injection on main in
# kagent-dev/kagent#2809 (81af4dbe68, 2026-09-14, closing kagent-dev/kagent#2550) with otelhttp.NewTransport, and
# only the 1.0 line carries it (v1.0.0-alpha1 to v1.0.0-rc3); v0.10.6 and release/v0.10.x do not. Question 1138 chose
# a patched 0.10.1 runtime over a move to 1.0, which renames the CRD group (kagent.dev to api.kagent.dev).
#
# What the patch does. mcp-traceparent.patch is the header-only form #2809's description names as its alternative:
# a round tripper that injects the global propagator's fields (traceparent, tracestate, baggage) for the request's
# active span and records no span itself. otelhttp (v0.69.0, the one go.mod pins) would add an "HTTP POST" client span
# of kagent's for every request an MCP call makes, the session's initialize, notification and tools/list as well as its
# tools/call (kagent opens a session per tool use), which no rule in gitops/otel-collector/values.yaml sorts, and the
# gateway's spans would hang under that span, not under execute_tool. The round tripper sits under headerRoundTripper, so the active span
# outranks the traceparent allowedHeaders forwards; both are in the turn's trace, so workshop-mcp's turn guard, which
# keys on the trace id (#885), reads the same id. With no active span (the MCP session's initialize and tools/list) the
# request goes as it came. The patch adds trace_context_test.go, which this build runs before it builds: four of its
# seven tests fail on stock v0.10.1.
#
# What is built. The source is the v0.10.1 tag at the commit upstream's binary names (a3d26ea, in its build info),
# with the patch applied. Only the agent runtime binary, /app, is rebuilt (adk/cmd/main.go, as kagent's Makefile
# build-golang-adk target builds it), and it goes in as one layer on top of upstream's linux/amd64 image of the same
# release, pinned by the index digest images.lock records for ghcr.io/kagent-dev/kagent/golang-adk:0.10.1, so the
# entrypoint, user and environment are upstream's. The nodes are AL2023_x86_64 (infra/terraform/aws/cluster/main.tf),
# so amd64 only. The toolchain and GOAMD64 are the ones upstream's binary reports (`go version -m`: go1.27.1, v2).
# Upstream's -X version ldflags are left out: the runtime binary does not link go/core/internal/version, so they set
# nothing. The image's io.github.peopleforrester.watch-it-burn.kagent-patch label names the build instead.
#
# Reproducible, so the digest is pinned before the first push (no run may write to ghcr.io), as the Kyverno counter
# fix's are (#1015): the Go toolchain is fixed by GOTOOLCHAIN (fetched and checksummed by the go command), the build is
# -trimpath with VCS stamping off, the layer tar is ustar with fixed owner, mode and mtime, and
# crane 0.22.1 (verify/e2e-tools.lock) appends it. The base comes from verify/image_cache.py and the source from
# verify/git_mirror.py, the host artifact cache (#1216), so on a warm cache the build reaches no registry but its own on
# loopback; the Go toolchain and modules still come through the go command's own proxy and checksum database.
#
# Signing. policies/kyverno/verify-image-signatures.yaml requires the workshop key's cosign signature on every
# ghcr.io/peopleforrester/watch-it-burn image a Pod in agent runs, and no run or workflow holds that key. Until the
# pushed digest is signed (verify/sign-images.sh, where the key lives), admission refuses the new Pod; the agent's
# Deployment rolls with maxUnavailable 0, so the stock Pod keeps serving until then.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY="$(cd "${HERE}/../../verify" && pwd)"
addr="${1:-}"
[[ "${addr}" =~ ^127\.0\.0\.1:[0-9]+$ ]] || { echo "build.sh: give a loopback registry, 127.0.0.1:<port>; got '${addr}'" >&2; exit 1; }
crane="${CRANE:-}"
[[ -n "${crane}" && -x "${crane}" ]] || { echo "build.sh: CRANE must name the pinned crane (verify/.tools/bin/crane); got '${crane}'" >&2; exit 1; }
[[ "$("${crane}" version)" == "0.22.1" ]] || { echo "build.sh: CRANE is crane $("${crane}" version), not 0.22.1" >&2; exit 1; }

KAGENT_URL="https://github.com/kagent-dev/kagent.git"
KAGENT_TAG="v0.10.1"
KAGENT_COMMIT="a3d26eaf2eda002d9c9104d2a8f6f27a2ff23ec3"
GO_TOOLCHAIN="go1.27.1"
GO_AMD64="v2"
PATCH_SHA256="f2882930470308acea692804e75f8452a38ce2068aadafd507b671cc45f8d376"
BASE="ghcr.io/kagent-dev/kagent/golang-adk:0.10.1@sha256:120353200c0226b322e2830de2844eaf02ae4a4c06e778ee60014e5f6ed4a6d0"
TAG="golang-adk-0.10.1-mcptrace"

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
echo "${PATCH_SHA256}  ${HERE}/mcp-traceparent.patch" | sha256sum -c --quiet - \
  || { echo "build.sh: mcp-traceparent.patch is not the patch build.sh pins (sha256 ${PATCH_SHA256})" >&2; exit 1; }

mirror="$(python3 "${VERIFY}/git_mirror.py" ensure "${KAGENT_URL}" "${KAGENT_COMMIT}")" \
  || { echo "build.sh: the host artifact cache's mirror could not serve ${KAGENT_URL} at ${KAGENT_COMMIT}" >&2; exit 1; }
tagged="$(git --git-dir "${mirror}" rev-parse --verify --quiet "refs/tags/${KAGENT_TAG}^{commit}")" \
  || { echo "build.sh: the mirror ${mirror} has no tag ${KAGENT_TAG}" >&2; exit 1; }
[[ "${tagged}" == "${KAGENT_COMMIT}" ]] \
  || { echo "build.sh: kagent ${KAGENT_TAG} is ${tagged} in the mirror ${mirror}, not ${KAGENT_COMMIT}" >&2; exit 1; }
# --shared reads the mirror's objects in place (the mirror never runs gc), so nothing is copied and nothing is fetched.
git clone --quiet --shared --no-checkout "${mirror}" "${tmp}/src"
git -C "${tmp}/src" -c advice.detachedHead=false checkout --quiet --detach "${KAGENT_COMMIT}"
head="$(git -C "${tmp}/src" rev-parse HEAD)"
[[ "${head}" == "${KAGENT_COMMIT}" ]] \
  || { echo "build.sh: the kagent checkout from ${mirror} is at ${head}, not ${KAGENT_COMMIT}" >&2; exit 1; }
git -C "${tmp}/src" apply "${HERE}/mcp-traceparent.patch"

digest="$(python3 "${VERIFY}/image_cache.py" platform-layout "${BASE}" "${tmp}/base" linux/amd64)" \
  || { echo "build.sh: the host artifact cache could not serve ${BASE}" >&2; exit 1; }
LOCAL_BASE="${addr}/kagent-base/golang-adk@${digest}"
pushed="$("${crane}" --insecure push "${tmp}/base" "${addr}/kagent-base/golang-adk")"
[[ "${pushed}" == "${LOCAL_BASE}" ]] \
  || { echo "build.sh: the cached base ${BASE} pushed as '${pushed}', not ${LOCAL_BASE}" >&2; exit 1; }

export GOTOOLCHAIN="${GO_TOOLCHAIN}" CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOAMD64="${GO_AMD64}" GOFLAGS=-buildvcs=false
go_version="$(cd "${tmp}/src/go" && go env GOVERSION)"
[[ "${go_version}" == "${GO_TOOLCHAIN}" ]] || { echo "build.sh: go is ${go_version}, not ${GO_TOOLCHAIN}" >&2; exit 1; }

# The patch's own tests, and the package's existing ones, before anything is built.
(cd "${tmp}/src/go" && go test -count=1 ./adk/pkg/mcp/)

mkdir -p "${tmp}/layer"
(cd "${tmp}/src/go" && go build -trimpath -o "${tmp}/layer/app" ./adk/cmd/main.go)
# One file entry, as upstream's own top layer has (app, 0755, root), and no directory entry.
tar --format=ustar --owner=0 --group=0 --numeric-owner --mtime=@0 --mode=0755 -C "${tmp}/layer" -cf "${tmp}/app.tar" app
ref="${addr}/peopleforrester/watch-it-burn:${TAG}"
"${crane}" --insecure append --platform linux/amd64 -b "${LOCAL_BASE}" -f "${tmp}/app.tar" -t "${ref}"
"${crane}" --insecure mutate "${ref}" \
  --label "io.github.peopleforrester.watch-it-burn.kagent-patch=Unleash_an_Agent_Watch_It_Burn#1222 mcp-traceparent ${PATCH_SHA256}" \
  -t "${ref}" >/dev/null
echo "built ${ref} $("${crane}" --insecure digest "${ref}")"
