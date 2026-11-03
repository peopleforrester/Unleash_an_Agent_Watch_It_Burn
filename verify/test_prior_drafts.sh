#!/usr/bin/env bash
# ABOUTME: Tests verify/prior-drafts.sh (#798) on a throwaway repo: an issue's unlanded draft is a DRAFT with its
# ABOUTME: drift verdict and a START line, a landed or redone one is not started from, and bad input exits 2.
#
# Usage: verify/test_prior_drafts.sh      (no network; the fixture is a local repo in a temp directory)
# shellcheck disable=SC2016,SC2034  # check() evals its single-quoted condition; rc is read there
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="${HERE}/prior-drafts.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# Fixture git runs with no user config and a fixed identity.
gx() { env -u GIT_DIR -u GIT_WORK_TREE HOME="${T}" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
    GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t \
    git -c init.defaultBranch=staging "$@"; }
g() { gx -C "${T}/r" "$@"; }
run() { rc=0; (cd "${T}/r" && env -u GIT_DIR -u GIT_WORK_TREE HOME="${T}" GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null bash "${CHECK}" "$@") >"${T}/out" 2>&1 || rc=$?; }
put() { mkdir -p "$(dirname "${T}/r/$1")" && printf '%s\n' "$2" >"${T}/r/$1"; }
# A run's draft: a branch off staging with one commit, published as origin/agent/<issue>-<run>, dated in order.
n=0
draft() { # $1: issue-run, $2: path, $3: subject
    n=$((n + 1))
    g checkout -q -b "agent/$1" staging
    put "$2" "$1"
    g add -A && GIT_COMMITTER_DATE="2026-10-0${n}T00:00:00Z" g commit -q -m "$3"
    g update-ref "refs/remotes/origin/agent/$1" "agent/$1"
    g checkout -q staging
}

gx init -q "${T}/r"
put README.md readme
put decisions.md "## the first entry"
g add -A && g commit -q -m "start"

echo "== an issue with no draft has nothing to reuse =="
run 604 staging
check "exits 0" '[[ ${rc} -eq 0 ]]'
check "says there is no branch, and where else to look" 'grep -q "^NONE  no agent/604-<run> branch here; check the issue.s comments" "${T}/out"'

echo "== a draft that never landed is the one to start from =="
draft 604-1 verify/test_measure.py "Measure #604 (#604)"
put README.md "readme, edited"
g commit -q -am "an unrelated change (#600)"
run 604 staging
check "exits 1" '[[ ${rc} -eq 1 ]]'
check "lists it as a DRAFT with its commit count" 'grep -q "^DRAFT  origin/agent/604-1  (2026-10-01): 1 of 1 commit(s) not in staging$" "${T}/out"'
check "names its commit" 'grep -q "^    [0-9a-f]* Measure #604 (#604)$" "${T}/out"'
check "gives draft-drift.sh's verdict, indented" 'grep -q "^    CLEAN  staging has not touched any of the draft.s 1 path(s)$" "${T}/out"'
check "says to start from it and to read the issue's comments" \
    'grep -q "^START  from origin/agent/604-1, the newest draft with no later #604 work in staging, .*gh issue view 604 --comments$" "${T}/out"'

echo "== of two unlanded drafts, the newer is started from =="
draft 604-2 verify/test_measure.py "Measure #604 again (#604)"
run 604 staging
check "exits 1" '[[ ${rc} -eq 1 ]]'
check "lists the newer first" '[[ "$(grep -m1 "^DRAFT" "${T}/out")" == "DRAFT  origin/agent/604-2 "* ]]'
check "starts from the newer" 'grep -q "^START  from origin/agent/604-2," "${T}/out"'
check "does not list another issue's branch" '! grep -q "agent/60[0-9][0-9]-" "${T}/out"'

echo "== a draft the dispatcher rebased into staging has landed =="
g cherry-pick agent/604-2 >/dev/null
run 604 staging
check "lists it as LANDED" 'grep -q "^LANDED  origin/agent/604-2  (2026-10-02): its 1 commit(s) are in staging$" "${T}/out"'
check "lists the older draft, followed by the landed #604 work, as a LATER one" \
    'grep -q "^    LATER  1 base commit(s) since name #604, the newest [0-9a-f]* Measure #604 again (#604): it may hold this work" "${T}/out"'
check "starts from no draft, and exits 0" '[[ ${rc} -eq 0 ]] && ! grep -q "^START" "${T}/out"'
check "says to start from staging" 'grep -q "^NONE  each draft not in staging is followed there by later #604 work; start from staging" "${T}/out"'

echo "== a draft merged as it is has landed =="
draft 605-1 docs/glance.md "Count apps (#605)"
g merge -q --no-edit agent/605-1
run 605 staging
check "exits 0" '[[ ${rc} -eq 0 ]]'
check "says staging contains it" 'grep -q "^LANDED  origin/agent/605-1  (2026-10-03): staging already contains it$" "${T}/out"'
check "says every draft is in staging" 'grep -q "^NONE  every earlier draft of #605 is in staging; start from it$" "${T}/out"'

echo "== #60 does not match #604's drafts or commits =="
draft 60-1 docs/sixty.md "Sixty (#60)"
run 60 staging
check "lists only agent/60-1" '[[ "$(grep -c "^DRAFT\|^LANDED" "${T}/out")" -eq 1 ]] && grep -q "^DRAFT  origin/agent/60-1 " "${T}/out"'
check "sees no later #60 work in #604's commits" '! grep -q "LATER" "${T}/out" && grep -q "^START  from origin/agent/60-1," "${T}/out"'

echo "== bad input is loud =="
run
check "no arguments exits 2" '[[ ${rc} -eq 2 ]]'
check "and prints the usage" 'grep -q "^usage: verify/prior-drafts.sh <issue-number> \[base-ref\]" "${T}/out"'
run "#604"
check "an issue that is not a number exits 2" '[[ ${rc} -eq 2 ]]'
run 604 origin/staging-nope
check "a base that does not resolve exits 2" '[[ ${rc} -eq 2 ]]'
check "and says so" 'grep -q "origin/staging-nope does not resolve to a commit here" "${T}/out"'

echo
echo "${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
