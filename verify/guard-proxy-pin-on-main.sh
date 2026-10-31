#!/usr/bin/env bash
# ABOUTME: Fails unless gitops/ai-layer/guard-proxy pins a commit on guard-proxy-agenticburn's main that contains the
# ABOUTME: guard-proxy-agenticburn#5 fix (8b525c6, the C7 badge reading the gateway rule) (#519, #681). Offline.
#
# Usage: verify/guard-proxy-pin-on-main.sh [repo-dir] [submodule-path] [fix-sha]
#        (defaults: this repo, gitops/ai-layer/guard-proxy, 8b525c6's full sha; the last two are for the fixture test)
#
# submodule-pins-pushed.sh (#521) passes a pin that any remote branch holds, staging included. #519 asks for more:
# the pin is on main, and main's history has #5's fix in it. A re-pin to a staging-only commit, or to a main commit
# from before 8b525c6, fails here. When the fix itself is not on main, the message says so: the run that would pin
# reports blocked on guard-proxy-agenticburn#5 and pins nothing.
# "On main" means reachable from refs/remotes/origin/main as of the submodule's last fetch, as in #521: a commit
# merged to main since then reads as off main until `git -C <submodule> fetch` updates that ref.
set -uo pipefail
REPO_DIR="$(cd "${1:-$(dirname "${BASH_SOURCE[0]}")/..}" && pwd)"
SUB_PATH="${2:-gitops/ai-layer/guard-proxy}"
FIX="${3:-8b525c617b7543f7d957b87c1ff0228e318831d3}"
sub="${REPO_DIR}/${SUB_PATH}"

die() { printf 'FAIL  %s\n' "$1" >&2; exit 1; }

pin="$(git -C "${REPO_DIR}" ls-tree HEAD -- "${SUB_PATH}" | awk '$1 == "160000" {print $3}')"
[[ -n "${pin}" ]] || die "${SUB_PATH} is not a submodule gitlink in ${REPO_DIR}'s HEAD"
# An uninitialised submodule directory is not a repo, and git -C would answer from the superproject's refs.
[[ "$(git -C "${sub}" rev-parse --show-toplevel 2>/dev/null)" == "${sub}" ]] \
    || die "${SUB_PATH} is not initialised; run git submodule update --init (verify/ensure-submodules.sh)"
main="$(git -C "${sub}" rev-parse -q --verify 'refs/remotes/origin/main^{commit}')" \
    || die "${SUB_PATH} has no origin/main; run git -C ${SUB_PATH} fetch origin"
git -C "${sub}" cat-file -e "${pin}^{commit}" 2>/dev/null \
    || die "${SUB_PATH} pins ${pin}, which its clone does not have; no remote served it"
if ! git -C "${sub}" cat-file -e "${FIX}^{commit}" 2>/dev/null \
    || ! git -C "${sub}" merge-base --is-ancestor "${FIX}" "${main}"; then
    die "guard-proxy-agenticburn#5's fix ${FIX:0:7} is not on origin/main yet; report blocked on guard-proxy-agenticburn#5 and pin nothing"
fi
git -C "${sub}" merge-base --is-ancestor "${pin}" "${main}" \
    || die "${SUB_PATH} pins ${pin:0:7}, which is not on origin/main (head ${main:0:7}); pin a main commit"
git -C "${sub}" merge-base --is-ancestor "${FIX}" "${pin}" \
    || die "${SUB_PATH} pins ${pin:0:7}, a main commit from before guard-proxy-agenticburn#5's fix ${FIX:0:7}; pin a main commit that contains it"
printf 'ok    %s pins %s, on origin/main (head %s) and containing guard-proxy-agenticburn#5 (%s)\n' \
    "${SUB_PATH}" "${pin:0:7}" "${main:0:7}" "${FIX:0:7}"
