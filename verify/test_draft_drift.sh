#!/usr/bin/env bash
# ABOUTME: Tests verify/draft-drift.sh (#633) on a throwaway repo: a draft whose paths the base moved, edited or
# ABOUTME: removed the directory of exits 1 and names each, a draft the base left alone exits 0, bad input exits 2.
#
# Usage: verify/test_draft_drift.sh      (no network; the fixture is a local repo in a temp directory)
# shellcheck disable=SC2016,SC2034  # check() evals its single-quoted condition; rc is read there
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="${HERE}/draft-drift.sh"
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

# The layout before #609: Argo CD apps in gitops/apps/, docs beside them.
gx init -q "${T}/r"
put gitops/apps/loki.yaml loki
put gitops/apps/prometheus.yaml "prometheus with loki"
put docs/glance.md "34 apps"
put README.md readme
g add -A && g commit -q -m "the old layout"

# The draft, cut from that staging: edits one app, deletes another, adds a third, edits a doc.
g checkout -q -b agent/474-1
put gitops/apps/prometheus.yaml "prometheus"
g rm -q gitops/apps/loki.yaml
put gitops/apps/tempo.yaml tempo
put docs/glance.md "32 apps"
g add -A && g commit -q -m "drop loki (#474)"
g checkout -q staging

echo "== a base that touched none of the draft's paths is clean =="
put README.md "readme, edited"
g commit -q -am "an unrelated change"
run agent/474-1 staging
check "exits 0" '[[ ${rc} -eq 0 ]]'
check "says CLEAN" 'grep -q "^CLEAN " "${T}/out"'
check "prints no DRIFT line" '! grep -q "^DRIFT" "${T}/out"'
check "counts one draft commit and one base commit" 'grep -q "1 draft commit(s), 1 base commit(s) since" "${T}/out"'

echo "== a base that moved gitops/apps/ and edited the doc is drift, each path named =="
mkdir -p "${T}/r/gitops/bootstrap" && g mv gitops/apps gitops/bootstrap/apps
g commit -q -m "move the apps into the chart (#609)"
put docs/glance.md "34 apps, counted from the chart"
g commit -q -am "count apps from the chart (#551)"
run agent/474-1 staging
check "exits 1" '[[ ${rc} -eq 1 ]]'
check "names the rename of an app the draft edits, and where it went" \
    'grep -q "^DRIFT  R[0-9]* gitops/apps/prometheus.yaml -> gitops/bootstrap/apps/prometheus.yaml  ([0-9a-f]* move the apps into the chart (#609))" "${T}/out"'
check "names the rename of an app the draft deletes" 'grep -q "^DRIFT  R[0-9]* gitops/apps/loki.yaml -> gitops/bootstrap/apps/loki.yaml" "${T}/out"'
check "names the doc both edited, with the base commit that did it" \
    'grep -q "^DRIFT  M docs/glance.md  ([0-9a-f]* count apps from the chart (#551))" "${T}/out"'
check "names the directory the base removed" 'grep -q "^DRIFT  gone gitops/apps/" "${T}/out"'
check "names the file the draft adds there" 'grep -q "^DRIFT  adds gitops/apps/tempo.yaml, in a directory staging no longer has" "${T}/out"'
check "does not name the README, which the draft never touched" '! grep -q "README.md" "${T}/out"'
check "says to make the design again, not cherry-pick" 'grep -q "5 drift line(s): make the draft.s design again on staging.s layout, not by cherry-pick" "${T}/out"'

echo "== the base defaults to HEAD =="
run agent/474-1
check "exits 1 against the checked-out staging" '[[ ${rc} -eq 1 ]]'
check "reports against HEAD" 'grep -q "agent/474-1 branched from HEAD at" "${T}/out"'

echo "== a draft already in the base has nothing to port =="
run "staging~1" staging
check "exits 0" '[[ ${rc} -eq 0 ]]'
check "says the draft has nothing beyond the base" 'grep -q "^CLEAN  the draft has nothing beyond staging" "${T}/out"'

echo "== bad input is loud =="
run
check "no arguments exits 2" '[[ ${rc} -eq 2 ]]'
check "and prints the usage" 'grep -q "^usage: verify/draft-drift.sh <draft-ref> \[base-ref\]" "${T}/out"'
run origin/agent/999-1 staging
check "a ref that does not resolve exits 2" '[[ ${rc} -eq 2 ]]'
check "and says to fetch and name it as origin/<branch>" 'grep -q "origin/agent/999-1 does not resolve to a commit here; git fetch origin" "${T}/out"'
g checkout -q --orphan unrelated && g commit -q --allow-empty -m "no shared history"
run unrelated staging
check "a draft with no common history exits 2" '[[ ${rc} -eq 2 ]]'
check "and says so" 'grep -q "share no history" "${T}/out"'

echo
echo "${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
