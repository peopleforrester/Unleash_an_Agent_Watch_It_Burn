#!/usr/bin/env bash
# ABOUTME: Checks out this repo's submodules at their pinned commits when they are missing or sit elsewhere,
# ABOUTME: from a bare mirror in the host artifact cache (#1122), so both test runners read what the superproject pins.
#
# A fresh clone has the submodule directories empty, and every check that reads proxy.py then dies on a
# missing file. Doing it here, not in the caller, keeps `bash verify/run-tests.sh` the whole command.
#
# A submodule checked out at a commit other than the pin (`git submodule status` prints `+`) is moved to the
# pin too (#837). Run 16845's suite went green while the gate, on a fresh clone, failed
# test_weaver_guard_proxy_spans.py against the guard-proxy that a65f748d repinned to c2eb4cf2. The draft it
# reused predates that repin, so its workspace most likely still had the old proxy.py checked out.
#
# Each worktree used to clone both submodules from GitHub (#1115). verify/git_mirror.py now keeps one bare mirror per
# submodule URL in the host artifact cache: a hit is checked against the pin and fetches nothing, a miss clones or
# fetches the mirror once, and a checkout that does not land on the pin fails naming both hashes. Its submodule
# update reads the mirror under `-c submodule.<name>.url=`, so this script's one checkout is a submodule update.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ -e "${REPO_DIR}/.git" ]] || exit 0
# Nothing to do when every submodule is checked out at its pin: no `-` (not initialised) and no `+` (elsewhere).
grep -q '^[-+]' <<<"$(git -C "${REPO_DIR}" submodule status)" || exit 0
python3 "${REPO_DIR}/verify/git_mirror.py" submodules "${REPO_DIR}" \
    || { printf 'FAILED to check out the submodules at their pins; the checks would read another commit or none\n' >&2; exit 1; }
