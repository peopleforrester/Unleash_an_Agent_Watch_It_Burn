#!/usr/bin/env bash
# ABOUTME: Tests verify/submodule-pins-pushed.sh (#521) on throwaway repos, then holds this repo's own pins to it:
# ABOUTME: a gitlink at a commit only the local submodule clone has must fail, before any other clone does.
#
# Usage: verify/test_submodule_pins_pushed.sh      (no network; the fixture remote is a local bare repo)
# shellcheck disable=SC2016,SC2034  # check() evals its single-quoted condition; rc and local_sha are read there
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="${HERE}/submodule-pins-pushed.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# Fixture git runs with no user config, a fixed identity and file:// submodules allowed.
g() { env -u GIT_DIR -u GIT_WORK_TREE HOME="${T}" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
    GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t \
    git -c protocol.file.allow=always -c init.defaultBranch=main "$@"; }
run() { rc=0; env -u GIT_DIR -u GIT_WORK_TREE bash "${CHECK}" "$1" >"${T}/out" 2>&1 || rc=$?; }

# A bare "remote" with one commit on main, and a superproject pinning that commit.
g init -q --bare "${T}/sub.git"
g init -q "${T}/seed" && g -C "${T}/seed" commit -q --allow-empty -m one && g -C "${T}/seed" push -q "${T}/sub.git" main
g init -q "${T}/super"
g -C "${T}/super" submodule add -q "${T}/sub.git" lib >/dev/null 2>&1
g -C "${T}/super" commit -q -m "pin lib"

echo "== a pin on a branch of the remote passes =="
run "${T}/super"
check "exits 0" '[[ ${rc} -eq 0 ]]'
check "names the branch that holds it" 'grep -q "lib pins .* held by origin/main" "${T}/out"'

echo "== a pin at a commit only the local submodule clone has fails =="
g -C "${T}/super/lib" commit -q --allow-empty -m local-only
local_sha="$(g -C "${T}/super/lib" rev-parse HEAD)"
g -C "${T}/super" commit -q -am "pin lib at an unpushed commit"
run "${T}/super"
check "exits non-zero" '[[ ${rc} -ne 0 ]]'
check "names the path and the unpushed commit" 'grep -q "lib pins ${local_sha}, which no branch of" "${T}/out"'
check "says to push it or pin a pushed commit" 'grep -q "push it there first, or pin a pushed commit" "${T}/out"'

echo "== once pushed to a branch and fetched, the same pin passes =="
g -C "${T}/super/lib" push -q origin HEAD:refs/heads/staging
run "${T}/super"
check "exits 0" '[[ ${rc} -eq 0 ]]'
check "held by the branch it was pushed to" 'grep -q "held by origin/staging" "${T}/out"'

echo "== a fresh clone of a superproject whose pin no remote serves fails the check, not only the fetch =="
g -C "${T}/super/lib" commit -q --allow-empty -m gone
g -C "${T}/super" commit -q -am "pin lib at another unpushed commit"
g clone -q "${T}/super" "${T}/fresh"
g -C "${T}/fresh" submodule update --init -q >/dev/null 2>&1
run "${T}/fresh"
check "exits non-zero" '[[ ${rc} -ne 0 ]]'
check "says the clone does not have the commit" 'grep -q "which its clone does not have" "${T}/out"'

echo "== an uninitialised submodule fails loudly, not against the superproject's refs =="
g clone -q "${T}/super" "${T}/bare-checkout"
run "${T}/bare-checkout"
check "exits non-zero" '[[ ${rc} -ne 0 ]]'
check "says it is not initialised" 'grep -q "lib is not initialised" "${T}/out"'

echo "== this repo's own pins are on a branch of each submodule's remote =="
bash "${HERE}/ensure-submodules.sh" >/dev/null 2>&1
run "${HERE}/.."
cat "${T}/out"
check "every gitlink in HEAD is pushed" '[[ ${rc} -eq 0 ]]'
check "both submodules were checked" '[[ $(grep -c "^ok " "${T}/out") -eq 2 ]]'

echo
echo "${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
