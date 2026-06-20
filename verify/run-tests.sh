#!/usr/bin/env bash
# ABOUTME: Offline render-gate suite — runs the no-cluster Python checks for the build.
# ABOUTME: Green here is the buildable-without-a-cluster bar; live cluster assertions are in run-all.sh.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fail=0
for t in test_cost_counter.py test_proxy_guards.py test_beat3_mcp.py test_agent_hitl.py test_observability.py test_takeaways.py; do
    printf '\n== %s ==\n' "${t}"
    python3 "${SCRIPT_DIR}/${t}" || fail=1
done
if [[ "${fail}" -eq 0 ]]; then
    printf '\nALL OFFLINE RENDER-GATE TESTS GREEN\n'
else
    printf '\nSOME TESTS FAILED\n' >&2
    exit 1
fi
