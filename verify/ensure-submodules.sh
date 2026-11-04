#!/usr/bin/env bash
# ABOUTME: Checks out this repo's submodules at their pinned commits when they are missing or sit elsewhere,
# ABOUTME: so both test runners read what the superproject pins. A dozen checks read guard-proxy/proxy.py.
#
# A fresh clone has the submodule directories empty, and every check that reads proxy.py then dies on a
# missing file. Doing it here, not in the caller, keeps `bash verify/run-tests.sh` the whole command.
#
# A submodule checked out at a commit other than the pin (`git submodule status` prints `+`) is moved to the
# pin too (#837). Run 16845's suite went green while the gate, on a fresh clone, failed
# test_weaver_guard_proxy_spans.py against the guard-proxy that a65f748d repinned to c2eb4cf2. The draft it
# reused predates that repin, so its workspace most likely still had the old proxy.py checked out.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ -e "${REPO_DIR}/.git" ]] || exit 0
status="$(git -C "${REPO_DIR}" submodule status)"
if grep -q '^-' <<<"${status}"; then
    printf 'initialising submodules\n'
    git -C "${REPO_DIR}" submodule update --init \
        || { printf 'FAILED to initialise submodules; the guard-proxy checks cannot run\n' >&2; exit 1; }
fi
stale="$(grep '^+' <<<"${status}" | awk '{print $2}' || true)"
if [[ -n "${stale}" ]]; then
    for path in ${stale}; do
        printf 'moving %s to its pinned commit\n' "${path}"
        git -C "${REPO_DIR}" submodule update --init -- "${path}" \
            || { printf 'FAILED to check out %s at its pin; the checks would read another commit\n' "${path}" >&2; exit 1; }
    done
fi
