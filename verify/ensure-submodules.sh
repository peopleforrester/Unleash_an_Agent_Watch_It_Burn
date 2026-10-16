#!/usr/bin/env bash
# ABOUTME: Checks out this repo's submodules when they are missing, so both test runners work on a fresh clone.
# ABOUTME: A dozen checks read gitops/ai-layer/guard-proxy/proxy.py, which lives in a submodule.
#
# A fresh clone has the submodule directories empty, and every check that reads proxy.py then dies on a
# missing file. Doing it here, not in the caller, keeps `bash verify/run-tests.sh` the whole command.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ -e "${REPO_DIR}/.git" ]] || exit 0
if git -C "${REPO_DIR}" submodule status | grep -q '^-'; then
    printf 'initialising submodules\n'
    git -C "${REPO_DIR}" submodule update --init \
        || { printf 'FAILED to initialise submodules; the guard-proxy checks cannot run\n' >&2; exit 1; }
fi
