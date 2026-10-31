#!/usr/bin/env bash
# ABOUTME: Tests verify/guard-proxy-pin-on-main.sh (#681) on throwaway repos, then holds this repo's guard-proxy pin
# ABOUTME: to it: on guard-proxy-agenticburn's main, and containing the guard-proxy-agenticburn#5 fix (#519).
#
# Usage: verify/test_guard_proxy_pin_on_main.sh      (no network; the fixture remote is a local bare repo)
# shellcheck disable=SC2016,SC2034  # check() evals its single-quoted condition; rc is read there
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="${HERE}/guard-proxy-pin-on-main.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# Fixture git runs with no user config, a fixed identity and file:// submodules allowed.
g() { env -u GIT_DIR -u GIT_WORK_TREE HOME="${T}" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
    GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t \
    git -c protocol.file.allow=always -c init.defaultBranch=main "$@"; }
run() { rc=0; env -u GIT_DIR -u GIT_WORK_TREE bash "${CHECK}" "$@" >"${T}/out" 2>&1 || rc=$?; }
commit() { g -C "${T}/seed" commit -q --allow-empty -m "$1" && g -C "${T}/seed" rev-parse HEAD; }
pin() { g -C "${T}/super/lib" checkout -q "$1" && g -C "${T}/super" add lib && g -C "${T}/super" commit -q --allow-empty -m "pin lib at $1"; }

# The "remote": main is before -> fix -> after; staging is one commit past main.
g init -q --bare "${T}/sub.git"
g init -q "${T}/seed"
before="$(commit before)"; fix="$(commit fix)"; after="$(commit after)"
g -C "${T}/seed" push -q "${T}/sub.git" main
g -C "${T}/seed" checkout -q -b staging
staged="$(commit staged)"
g -C "${T}/seed" push -q "${T}/sub.git" staging
g init -q "${T}/super"
g -C "${T}/super" submodule add -q "${T}/sub.git" lib >/dev/null 2>&1
g -C "${T}/super" commit -q -m "add lib"

echo "== a pin at main's head, past the fix, passes =="
pin "${after}"
run "${T}/super" lib "${fix}"
check "exits 0" '[[ ${rc} -eq 0 ]]'
check "says it is on origin/main and contains the fix" 'grep -q "lib pins ${after:0:7}, on origin/main .* containing guard-proxy-agenticburn#5" "${T}/out"'

echo "== a pin at the fix commit itself passes =="
pin "${fix}"
run "${T}/super" lib "${fix}"
check "exits 0" '[[ ${rc} -eq 0 ]]'

echo "== a pin at a main commit from before the fix fails =="
pin "${before}"
run "${T}/super" lib "${fix}"
check "exits non-zero" '[[ ${rc} -ne 0 ]]'
check "says the pin is from before the fix" 'grep -q "lib pins ${before:0:7}, a main commit from before guard-proxy-agenticburn#5" "${T}/out"'

echo "== a pin that only staging holds fails, though submodule-pins-pushed.sh passes it =="
pin "${staged}"
run "${T}/super" lib "${fix}"
check "exits non-zero" '[[ ${rc} -ne 0 ]]'
check "says the pin is not on origin/main" 'grep -q "lib pins ${staged:0:7}, which is not on origin/main" "${T}/out"'
rc_pushed=0; env -u GIT_DIR -u GIT_WORK_TREE bash "${HERE}/submodule-pins-pushed.sh" "${T}/super" >/dev/null 2>&1 || rc_pushed=$?
check "submodule-pins-pushed.sh passes the same pin, so this is the check that holds it to main" '[[ ${rc_pushed} -eq 0 ]]'

echo "== when the fix is only on staging, the check says to report blocked and pin nothing =="
pin "${after}"
run "${T}/super" lib "${staged}"
check "exits non-zero" '[[ ${rc} -ne 0 ]]'
check "says the fix is not on main and to report blocked on guard-proxy-agenticburn#5" \
    'grep -q "fix ${staged:0:7} is not on origin/main yet; report blocked on guard-proxy-agenticburn#5 and pin nothing" "${T}/out"'

echo "== a fix commit the clone has never seen reads as not on main =="
run "${T}/super" lib 0123456789abcdef0123456789abcdef01234567
check "exits non-zero" '[[ ${rc} -ne 0 ]]'
check "says the fix is not on main yet" 'grep -q "fix 0123456 is not on origin/main yet" "${T}/out"'

echo "== an uninitialised submodule fails loudly, not against the superproject's refs =="
g clone -q "${T}/super" "${T}/bare-checkout"
run "${T}/bare-checkout" lib "${fix}"
check "exits non-zero" '[[ ${rc} -ne 0 ]]'
check "says it is not initialised" 'grep -q "lib is not initialised" "${T}/out"'

echo "== a path that is not a gitlink fails =="
run "${T}/super" nowhere "${fix}"
check "exits non-zero" '[[ ${rc} -ne 0 ]]'
check "says it is not a submodule gitlink" 'grep -q "nowhere is not a submodule gitlink" "${T}/out"'

echo "== this repo's guard-proxy pin is on guard-proxy-agenticburn's main and contains #5's fix =="
bash "${HERE}/ensure-submodules.sh" >/dev/null 2>&1
run "${HERE}/.."
cat "${T}/out"
check "gitops/ai-layer/guard-proxy passes" '[[ ${rc} -eq 0 ]]'
check "the check ran on gitops/ai-layer/guard-proxy" 'grep -q "^ok    gitops/ai-layer/guard-proxy pins " "${T}/out"'

echo
echo "${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
