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
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
addr="${1:-}"
[[ "${addr}" =~ ^127\.0\.0\.1:[0-9]+$ ]] || { echo "build-loopback.sh: give a loopback registry, 127.0.0.1:<port>; got '${addr}'" >&2; exit 1; }
shift
crane="${CRANE:-}"
[[ -n "${crane}" && -x "${crane}" ]] || { echo "build-loopback.sh: CRANE must name the pinned crane (verify/.tools/bin/crane); got '${crane}'" >&2; exit 1; }
crane="$(cd "$(dirname "${crane}")" && pwd)/$(basename "${crane}")"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
cat >"${tmp}/crane" <<EOF
#!/usr/bin/env bash
args=()
for a in "\$@"; do args+=("\${a//ghcr.io\/peopleforrester\/festival-ops\//${addr}\/festival-ops\/}"); done
exec "${crane}" --insecure "\${args[@]}"
EOF
chmod 755 "${tmp}/crane"
CRANE="${tmp}/crane" bash "${HERE}/build.sh" "$@"
echo "build-loopback.sh: the 'pushed' lines above name ghcr.io; each went to ${addr}/festival-ops/ instead, and nothing left this host"
