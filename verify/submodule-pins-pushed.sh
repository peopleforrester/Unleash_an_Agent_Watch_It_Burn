#!/usr/bin/env bash
# ABOUTME: Fails when a submodule gitlink pins a commit that no branch of the submodule's remote holds (#521).
# ABOUTME: Offline: reads the remote-tracking refs of each initialised submodule clone, never the network.
#
# Usage: verify/submodule-pins-pushed.sh [repo-dir]      (default: this repo)
#
# A pin to a commit that exists only in the clone that made it looks fine there: the submodule checks out
# and every test passes. Every other clone then fails `git submodule update --init` with "upload-pack: not
# our ref", and so do both test runners. Branch agent/487-7110 pinned guard-proxy at 627cb97 that way.
# Here "pushed" means reachable from a refs/remotes/ ref as of the submodule's last fetch; a commit pushed
# since then reads as unpushed until `git -C <submodule> fetch` updates those refs.
set -uo pipefail
REPO_DIR="$(cd "${1:-$(dirname "${BASH_SOURCE[0]}")/..}" && pwd)"

fail=0
checked=0
while read -r mode sha path; do
    [[ "${mode}" == "160000" ]] || continue
    sub="${REPO_DIR}/${path}"
    # An uninitialised submodule directory is not a repo, and git -C would fall through to the superproject
    # and answer from its refs, so the top-level must be the submodule itself.
    if [[ "$(git -C "${sub}" rev-parse --show-toplevel 2>/dev/null)" != "${sub}" ]]; then
        printf 'FAIL  %s is not initialised; run git submodule update --init (verify/ensure-submodules.sh)\n' "${path}" >&2
        fail=1
        continue
    fi
    checked=$((checked + 1))
    if ! git -C "${sub}" cat-file -e "${sha}^{commit}" 2>/dev/null; then
        printf 'FAIL  %s pins %s, which its clone does not have; no remote served it\n' "${path}" "${sha}" >&2
        fail=1
        continue
    fi
    # origin/HEAD is a symref to the default branch; name the branch itself.
    branches="$(git -C "${sub}" for-each-ref --contains "${sha}" --format='%(refname)' refs/remotes/ \
        | grep -v '/HEAD$' | sed 's|^refs/remotes/||')"
    if [[ -z "${branches}" ]]; then
        url="$(git -C "${sub}" remote get-url origin 2>/dev/null || echo 'its remote')"
        printf 'FAIL  %s pins %s, which no branch of %s holds; push it there first, or pin a pushed commit\n' \
            "${path}" "${sha}" "${url}" >&2
        fail=1
        continue
    fi
    printf 'ok    %s pins %s, held by %s\n' "${path}" "${sha:0:7}" "$(echo "${branches}" | head -n1)"
done < <(git -C "${REPO_DIR}" ls-tree -r HEAD | awk '{print $1, $3, $4}')

if [[ "${checked}" -eq 0 && "${fail}" -eq 0 ]]; then
    printf 'FAIL  no submodule gitlinks found in %s\n' "${REPO_DIR}" >&2
    exit 1
fi
exit "${fail}"
