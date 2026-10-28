#!/usr/bin/env bash
# ABOUTME: Names what the base branch changed, since an earlier run's draft branched off it, in the paths the draft
# ABOUTME: touches (#633). Offline: reads local refs only, so `git fetch origin` first if they may be stale.
#
# Usage: verify/draft-drift.sh <draft-ref> [base-ref]      (base defaults to HEAD; the repo is the current directory)
#
#   exit 0  the base has not touched a path the draft changes; the draft can be reused as it is
#   exit 1  DRIFT lines name each such path; make the draft's design again on the base's layout
#   exit 2  usage error, a ref that does not resolve, or no common history
#
# A re-dispatched issue starts from the current staging, and its earlier draft sits on an agent/<issue>-<run>
# branch cut from the staging of its day. #474's approved draft had to be made again three times that way, the
# last after #609 moved gitops/apps/ to gitops/bootstrap/apps/ and the draft's paths no longer existed. A
# cherry-pick finds that out one conflict at a time; this lists it before any work is redone.
set -uo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "usage: verify/draft-drift.sh <draft-ref> [base-ref]" >&2
    exit 2
fi
draft_ref="$1"
base_ref="${2:-HEAD}"

g() { git -c core.quotePath=false "$@"; }

for ref in "${draft_ref}" "${base_ref}"; do
    if ! g rev-parse --verify -q "${ref}^{commit}" >/dev/null; then
        echo "FAIL  ${ref} does not resolve to a commit here; git fetch origin, then name it as origin/<branch>" >&2
        exit 2
    fi
done
if ! mb="$(g merge-base "${base_ref}" "${draft_ref}")"; then
    echo "FAIL  ${draft_ref} and ${base_ref} share no history" >&2
    exit 2
fi
short() { g rev-parse --short "$1"; }

ahead="$(g rev-list --count "${mb}..${draft_ref}")"
behind="$(g rev-list --count "${mb}..${base_ref}")"
echo "${draft_ref} branched from ${base_ref} at $(short "${mb}"):" \
    "${ahead} draft commit(s), ${behind} base commit(s) since"
if [[ "${ahead}" -eq 0 ]]; then
    echo "CLEAN  the draft has nothing beyond ${base_ref}"
    exit 0
fi

# Every path the draft changes, old and new names both (--no-renames splits a rename into delete and add).
declare -A draft_status=()
while IFS=$'\t' read -r status path; do
    draft_status["${path}"]="${status}"
done < <(g diff --no-renames --name-status "${mb}" "${draft_ref}")

drift=0
# The newest base commit that touched them, its subject cut to fit a line.
last_commit() {
    local line
    line="$(g log -1 --format='%h %s' "${mb}..${base_ref}" -- "$@")"
    [[ ${#line} -le 90 ]] && echo "${line}" || echo "${line:0:87}..."
}

# What the base did to those paths: modified, deleted, renamed (with where to), or added the same name.
while IFS=$'\t' read -r status old new; do
    [[ -n "${draft_status[${old}]+x}" ]] || continue
    drift=$((drift + 1))
    if [[ -n "${new}" ]]; then
        printf 'DRIFT  %s %s -> %s  (%s)\n' "${status}" "${old}" "${new}" "$(last_commit "${old}" "${new}")"
    else
        printf 'DRIFT  %s %s  (%s)\n' "${status}" "${old}" "$(last_commit "${old}")"
    fi
done < <(g diff -M --name-status "${mb}" "${base_ref}")

# A file the draft adds to a directory the base has since removed lands nowhere the base still reads.
declare -A gone_seen=()
while IFS= read -r path; do
    [[ -n "${path}" && "${draft_status[${path}]}" == "A" ]] || continue
    dir="$(dirname "${path}")"
    [[ "${dir}" != "." ]] || continue
    if g cat-file -e "${mb}:${dir}" 2>/dev/null && ! g cat-file -e "${base_ref}:${dir}" 2>/dev/null; then
        drift=$((drift + 1))
        if [[ -z "${gone_seen[${dir}]+x}" ]]; then
            gone_seen["${dir}"]=1
            drift=$((drift + 1))
            printf 'DRIFT  gone %s/  (%s)\n' "${dir}" "$(last_commit "${dir}")"
        fi
        printf 'DRIFT  adds %s, in a directory %s no longer has\n' "${path}" "${base_ref}"
    fi
done < <(printf '%s\n' "${!draft_status[@]}" | sort)

if [[ "${drift}" -eq 0 ]]; then
    echo "CLEAN  ${base_ref} has not touched any of the draft's ${#draft_status[@]} path(s)"
    exit 0
fi
echo "${drift} drift line(s): make the draft's design again on ${base_ref}'s layout, not by cherry-pick"
exit 1
