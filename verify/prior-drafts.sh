#!/usr/bin/env bash
# ABOUTME: Lists an issue's earlier hecaton drafts (origin/agent/<issue>-<run>) whose commits never reached the base,
# ABOUTME: newest first, each with verify/draft-drift.sh's verdict, so a re-dispatched run reuses work instead of redoing it (#798).
#
# Usage: verify/prior-drafts.sh <issue-number> [base-ref]      (base defaults to HEAD; the repo is the current directory)
#
#   exit 0  no earlier draft, every one is in the base, or each is followed there by later work on the issue
#   exit 1  a START line names the newest draft to reuse, as its draft-drift verdict says
#   exit 2  usage error, or a base that does not resolve
#
# Offline: reads local refs only, so `git fetch origin` first if they may be stale. A run's commits reach GitHub
# when hecaton promotes them, or when it retires the run's workspace; the issue's comments name commits that are
# not on GitHub yet, and say why a run's work did not merge (`gh issue view <issue> --comments`).
#
# Why. Run 9277 (#604) redid a whole measurement that run 9249 had committed and that failed only the prose gate;
# run 9249's branch applied to 9277's base with no conflict. Run 15763 (#205) found its predecessor's draft 125
# commits behind staging and redid it. A draft counts as landed when each of its commit subjects is in the base
# since the two parted, which is how the dispatcher's rebase keeps them. A draft that never landed but is followed
# in the base by a commit naming the issue was most likely redone by a later run: it is listed, and START passes over it.
set -uo pipefail

if [[ $# -lt 1 || $# -gt 2 || ! "$1" =~ ^[0-9]+$ ]]; then
    echo "usage: verify/prior-drafts.sh <issue-number> [base-ref]" >&2
    exit 2
fi
issue="$1"
base_ref="${2:-HEAD}"
DRIFT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/draft-drift.sh"

g() { git -c core.quotePath=false "$@"; }

if ! g rev-parse --verify -q "${base_ref}^{commit}" >/dev/null; then
    echo "FAIL  ${base_ref} does not resolve to a commit here" >&2
    exit 2
fi

found=0
drafts=()
reuse=()
while IFS= read -r ref; do
    [[ -n "${ref}" ]] || continue
    found=$((found + 1))
    mb="$(g merge-base "${base_ref}" "${ref}")" || { echo "UNRELATED  ${ref} shares no history with ${base_ref}"; continue; }
    # Subjects in the base since the draft branched; a draft commit whose subject is there has landed.
    declare -A landed=()
    while IFS= read -r subject; do landed["${subject}"]=1; done < <(g log --format=%s "${mb}..${base_ref}")
    total=0
    open=()
    while IFS= read -r line; do
        total=$((total + 1))
        [[ -n "${landed[${line#* }]+x}" ]] || open+=("${line}")
    done < <(g log --reverse --format='%h %s' "${mb}..${ref}")
    unset landed
    when="$(g log -1 --format=%cs "${ref}")"
    if [[ "${#open[@]}" -eq 0 ]]; then
        if [[ "${total}" -eq 0 ]]; then
            echo "LANDED  ${ref}  (${when}): ${base_ref} already contains it"
        else
            echo "LANDED  ${ref}  (${when}): its ${total} commit(s) are in ${base_ref}"
        fi
        continue
    fi
    drafts+=("${ref}")
    echo "DRAFT  ${ref}  (${when}): ${#open[@]} of ${total} commit(s) not in ${base_ref}"
    for line in "${open[@]}"; do
        [[ ${#line} -le 100 ]] && echo "    ${line}" || echo "    ${line:0:97}..."
    done
    later="$(g log -E --grep="#${issue}([^0-9]|$)" --format='%h %s' "${mb}..${base_ref}")"
    if [[ -n "${later}" ]]; then
        newest="$(head -n 1 <<<"${later}")"
        [[ ${#newest} -le 90 ]] || newest="${newest:0:87}..."
        echo "    LATER  $(wc -l <<<"${later}") base commit(s) since name #${issue}, the newest ${newest}:" \
            "it may hold this work; compare before porting any of it"
    else
        reuse+=("${ref}")
    fi
    bash "${DRIFT}" "${ref}" "${base_ref}" 2>&1 | sed 's/^/    /'
done < <(g for-each-ref --sort=-committerdate --format='%(refname:short)' "refs/remotes/*/agent/${issue}-*")

if [[ "${found}" -eq 0 ]]; then
    echo "NONE  no agent/${issue}-<run> branch here; check the issue's comments for commits not yet on GitHub"
    exit 0
fi
if [[ "${#drafts[@]}" -eq 0 ]]; then
    echo "NONE  every earlier draft of #${issue} is in ${base_ref}; start from it"
    exit 0
fi
if [[ "${#reuse[@]}" -eq 0 ]]; then
    echo "NONE  each draft not in ${base_ref} is followed there by later #${issue} work; start from ${base_ref}" \
        "and take from a draft only what that work lacks"
    exit 0
fi
echo "START  from ${reuse[0]}, the newest draft with no later #${issue} work in ${base_ref}, as its verdict" \
    "above says; read why it did not land: gh issue view ${issue} --comments"
exit 1
