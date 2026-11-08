#!/usr/bin/env bash
# ABOUTME: Runs build.sh, unchanged, with its ghcr.io festival-ops/ references sent to a registry on loopback (#775), so
# ABOUTME: both Jokers are built where nothing is published. push-jokers.yml and test_joker_build_digest.py both use it.
#
# Usage: CRANE=<crane> bash images/villains/build-loopback.sh <127.0.0.1:port> [joker|joker-internal ...]
#
# The registry at <127.0.0.1:port> is the caller's (crane registry serve). build.sh's crane runs through a wrapper that
# rewrites ghcr.io/peopleforrester/festival-ops/ to <127.0.0.1:port>/festival-ops/ in every argument, so each Joker
# lands at <127.0.0.1:port>/festival-ops/maintenance-shell:<tag>. The address must be loopback: anything else is
# refused before build.sh runs, so this script cannot push anywhere a person reads.
#
# build.sh's base, JOKER_BASE, is pinned by digest, and it comes from the host artifact cache, not ghcr.io (#1122):
# verify/image_cache.py serves it as an OCI layout keyed by that digest, fetching it from ghcr.io only on a cache miss
# and checking every blob on a hit. crane pushes the layout to <127.0.0.1:port>/joker-base/busybox, which must land on
# the pinned digest or the build stops before build.sh runs, and the wrapper sends JOKER_BASE there. Where the base
# was read from is not part of a Joker's digest, so the build is byte for byte the one built on ghcr.io's copy.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
addr="${1:-}"
[[ "${addr}" =~ ^127\.0\.0\.1:[0-9]+$ ]] || { echo "build-loopback.sh: give a loopback registry, 127.0.0.1:<port>; got '${addr}'" >&2; exit 1; }
shift
crane="${CRANE:-}"
[[ -n "${crane}" && -x "${crane}" ]] || { echo "build-loopback.sh: CRANE must name the pinned crane (verify/.tools/bin/crane); got '${crane}'" >&2; exit 1; }
crane="$(cd "$(dirname "${crane}")" && pwd)/$(basename "${crane}")"
base="$(sed -n 's/^JOKER_BASE="\([^"]*\)"$/\1/p' "${HERE}/build.sh")"
[[ "${base}" =~ @sha256:[0-9a-f]{64}$ ]] || { echo "build-loopback.sh: build.sh's JOKER_BASE is not pinned by digest; got '${base}'" >&2; exit 1; }
layout="$(python3 "${HERE}/../../verify/image_cache.py" layout "${base}")" \
    || { echo "build-loopback.sh: the host artifact cache could not serve ${base}" >&2; exit 1; }
local_base="${addr}/joker-base/busybox@${base##*@}"
pushed="$("${crane}" --insecure push "${layout}" "${addr}/joker-base/busybox")"
[[ "${pushed}" == "${local_base}" ]] \
    || { echo "build-loopback.sh: the cached base pushed as '${pushed}', not ${local_base}" >&2; exit 1; }
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
cat >"${tmp}/crane" <<'EOF'
#!/usr/bin/env bash
args=()
for a in "$@"; do
  a="${a//"${LOOPBACK_BASE_FROM}"/"${LOOPBACK_BASE_TO}"}"
  args+=("${a//ghcr.io\/peopleforrester\/festival-ops\//"${LOOPBACK_ADDR}"/festival-ops/}")
done
exec "${LOOPBACK_CRANE}" --insecure "${args[@]}"
EOF
chmod 755 "${tmp}/crane"
LOOPBACK_BASE_FROM="${base}" LOOPBACK_BASE_TO="${local_base}" LOOPBACK_ADDR="${addr}" LOOPBACK_CRANE="${crane}" \
    CRANE="${tmp}/crane" bash "${HERE}/build.sh" "$@"
echo "build-loopback.sh: the 'pushed' lines above name ghcr.io; each went to ${addr}/festival-ops/ instead, built on the cached base, and nothing left this host"
