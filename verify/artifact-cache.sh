#!/usr/bin/env bash
# ABOUTME: Shell entry point to the host artifact cache (#1117): `root` prints the cache root, `get <sha256> <url>` prints
# ABOUTME: the verified cached file, fetching it only on a miss. artifact_cache.py holds the rules; any failure exits 1.
#
# Usage: bash verify/artifact-cache.sh root
#        bash verify/artifact-cache.sh get <sha256> <url>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/artifact_cache.py" "$@"
