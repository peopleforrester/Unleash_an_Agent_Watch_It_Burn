#!/usr/bin/env bash
# ABOUTME: ensure-submodules.sh checks out a missing submodule, and moves one checked out at another commit back
# ABOUTME: to the superproject's pin, so the suites never read a stale proxy.py (#837). Offline: local repos only.
# Since #1122 the checkout comes from a bare mirror in the host artifact cache (verify/git_mirror.py, which
# test_git_mirror.py holds case by case); here the cache root is a scratch directory outside every worktree.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
CACHE="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import artifact_cache; print(artifact_cache.scratch_dir("ensure-submodules-test-"))' "${HERE}")"
trap 'rm -rf "${WORK}" "${CACHE}"' EXIT
unset HECATON_TOOLS_CACHE ARTIFACT_FETCH_LOG
export WIB_ARTIFACT_CACHE="${CACHE}"
# Local file:// submodule clones are refused by default since git 2.38.1; allow them for this process only.
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=protocol.file.allow GIT_CONFIG_VALUE_0=always
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

fail=0
check() {
    if [[ "$2" == "$3" ]]; then printf '  PASS  %s\n' "$1"; else printf '  FAIL  %s  (got %s, want %s)\n' "$1" "$2" "$3"; fail=1; fi
}

git init -q -b main "${WORK}/sub"
echo old >"${WORK}/sub/proxy.py"; git -C "${WORK}/sub" add proxy.py; git -C "${WORK}/sub" commit -qm old
OLD="$(git -C "${WORK}/sub" rev-parse HEAD)"
echo new >"${WORK}/sub/proxy.py"; git -C "${WORK}/sub" commit -qam new
NEW="$(git -C "${WORK}/sub" rev-parse HEAD)"

git init -q -b main "${WORK}/super"
git -C "${WORK}/super" submodule add -q "${WORK}/sub" guard-proxy
mkdir "${WORK}/super/verify"
cp "${HERE}/ensure-submodules.sh" "${HERE}/git_mirror.py" "${HERE}/artifact_cache.py" "${WORK}/super/verify/"
git -C "${WORK}/super" add verify; git -C "${WORK}/super" commit -qm pin

echo "== a submodule checked out at another commit is moved to the pin =="
git -C "${WORK}/super/guard-proxy" checkout -q "${OLD}"
check "the setup leaves the submodule off its pin" "$(git -C "${WORK}/super" submodule status | cut -c1)" "+"
bash "${WORK}/super/verify/ensure-submodules.sh" >/dev/null
check "the submodule is back at the pinned commit" "$(git -C "${WORK}/super/guard-proxy" rev-parse HEAD)" "${NEW}"
check "the checks read the pinned file" "$(cat "${WORK}/super/guard-proxy/proxy.py")" "new"

echo "== a fresh clone has its submodule checked out =="
git clone -q "${WORK}/super" "${WORK}/fresh"
check "the fresh clone starts with the submodule uninitialised" "$(git -C "${WORK}/fresh" submodule status | cut -c1)" "-"
bash "${WORK}/fresh/verify/ensure-submodules.sh" >/dev/null
check "the submodule is checked out at the pin" "$(git -C "${WORK}/fresh/guard-proxy" rev-parse HEAD)" "${NEW}"
check "it came from the host cache's mirror, cloned once" "$(wc -l <"${CACHE}/fetch.log" | tr -d ' ')" "1"
check "its origin is the submodule's own URL" "$(git -C "${WORK}/fresh/guard-proxy" remote get-url origin)" "${WORK}/sub"

echo "== a submodule at its pin is left alone =="
check "status reads clean" "$(git -C "${WORK}/fresh" submodule status | cut -c1)" " "
bash "${WORK}/fresh/verify/ensure-submodules.sh" >"${WORK}/out"
check "nothing is printed or moved" "$(cat "${WORK}/out")" ""

if [[ "${fail}" -ne 0 ]]; then
    printf '\nFAILED: ensure-submodules.sh leaves a submodule off its pin\n' >&2
    exit 1
fi
printf '\nensure-submodules.sh checks out every submodule at its pinned commit.\n'
