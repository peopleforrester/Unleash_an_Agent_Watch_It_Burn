#!/usr/bin/env bash
# ABOUTME: Behavioural test for how fleet.sh routes records routes.map in the apex repo (#531): main gains
# ABOUTME: only the routes commit even when the apex checkout is on a branch ahead of main. Offline fixture repos.
#
# Usage: verify/test_fleet_routes_publish.sh      (no network: "origin" is a bare repo in a temp dir)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .fleet-routes-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# The fixture must not read the machine's git config (signing, hooks, default branch) and fleet.sh's
# worktree goes under TMPDIR, so both stay inside ${T}.
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 TMPDIR="${T}"
g() { git -C "$1" "${@:2}"; }

# An apex origin whose staging is three commits ahead of main, like the 17 at the 2026-10-24 bring-up.
fixture() {   # $1 name; leaves ${T}/$1/origin.git and a clone at ${T}/$1/apex on staging
    local d="${T}/$1" i
    mkdir -p "${d}"
    git init -q --bare -b main "${d}/origin.git"
    git clone -q "${d}/origin.git" "${d}/apex" 2>/dev/null
    g "${d}/apex" config user.email fixture@test; g "${d}/apex" config user.name fixture
    printf '# old\nr1-1.agenticburn.com  old-lb:443\n' >"${d}/apex/routes.map"
    echo 'caddy v1' >"${d}/apex/Caddyfile"
    g "${d}/apex" add -A; g "${d}/apex" commit -qm "main: base"
    g "${d}/apex" push -q origin HEAD:main 2>/dev/null
    g "${d}/apex" checkout -qb staging
    for i in 1 2 3; do
        echo "caddy staging ${i}" >"${d}/apex/Caddyfile"
        g "${d}/apex" commit -qam "staging: unreleased change ${i}"
    done
    g "${d}/apex" push -q -u origin staging 2>/dev/null
}
new_table() { printf '# new\nr1-1.agenticburn.com  new-lb:443\nbane-sabrina.agenticburn.com  new-lb2:443\n' >"$1/routes.map"; }
publish() {   # $1 apex dir; runs publish_routes_table from a sourced fleet.sh, stderr to ${T}/log
    ( cd "$(dirname "${FLEET}")" && WIB_APEX_DIR="$1" \
        bash -c "source '${FLEET}' >/dev/null 2>&1; publish_routes_table '$1/routes.map' 2" >/dev/null 2>"${T}/log" )
}

echo "== checkout on staging, three commits ahead of main =="
fixture staging; A="${T}/staging/apex"; O="${T}/staging/origin.git"
main_before="$(g "${O}" rev-parse main)"; staging_before="$(g "${O}" rev-parse staging)"
new_table "${A}"; publish "${A}"
main_after="$(g "${O}" rev-parse main)"
check "main moved" '[[ "${main_after}" != "${main_before}" ]]'
check "main gained exactly one commit" '[[ "$(g "${O}" rev-list --count "${main_before}..main")" -eq 1 ]]'
check "that commit sits directly on the old main" '[[ "$(g "${O}" rev-parse main^)" == "${main_before}" ]]'
check "that commit changes routes.map and nothing else" '[[ "$(g "${O}" diff --name-only main^ main)" == "routes.map" ]]'
check "main carries the new table" 'diff -q <(g "${O}" show main:routes.map) "${A}/routes.map" >/dev/null'
check "no staging commit reached main" '! g "${O}" merge-base --is-ancestor "${staging_before}" main'
check "main's Caddyfile is still main's" '[[ "$(g "${O}" show main:Caddyfile)" == "caddy v1" ]]'
check "staging keeps its own record of the table" \
  '[[ "$(g "${O}" rev-parse staging^)" == "${staging_before}" ]] && diff -q <(g "${O}" show staging:routes.map) "${A}/routes.map" >/dev/null'
check "the log names the staging commits kept off main" \
  'grep -q "stayed off" "${T}/log" && [[ "$(grep -c "staging: unreleased change" "${T}/log")" -eq 3 ]]'
check "the checkout is still on staging with a clean tree" \
  '[[ "$(g "${A}" symbolic-ref --short HEAD)" == staging && -z "$(g "${A}" status --porcelain)" ]]'
check "no worktree is left behind" '[[ "$(g "${A}" worktree list | wc -l)" -eq 1 ]]'

echo "== the same table again =="
main_before="$(g "${O}" rev-parse main)"; publish "${A}"
check "main does not move when it already carries the table" '[[ "$(g "${O}" rev-parse main)" == "${main_before}" ]]'

echo "== checkout on main =="
fixture onmain; A="${T}/onmain/apex"; O="${T}/onmain/origin.git"
g "${A}" checkout -q main; main_before="$(g "${O}" rev-parse main)"; staging_before="$(g "${O}" rev-parse staging)"
new_table "${A}"; publish "${A}"
check "main gained exactly one commit, routes.map only" \
  '[[ "$(g "${O}" rev-list --count "${main_before}..main")" -eq 1 && "$(g "${O}" diff --name-only main^ main)" == "routes.map" ]]'
check "local main caught up with origin main, tree clean" \
  '[[ "$(g "${A}" rev-parse HEAD)" == "$(g "${O}" rev-parse main)" && -z "$(g "${A}" status --porcelain)" ]]'
check "staging was not touched" '[[ "$(g "${O}" rev-parse staging)" == "${staging_before}" ]]'

echo "== wiring =="
check "cmd_routes records the table through publish_routes_table" \
  'grep -q "^    publish_routes_table \"\${out}\" \"\${lines}\"$" "${FLEET}"'
check "nothing pushes the apex checkout's HEAD to main" '! grep -q "WIB_APEX_DIR}\" push origin HEAD:main" "${FLEET}"'

echo; echo "  ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]] || { echo "  (publish log)"; sed 's/^/    /' "${T}/log"; }
exit $(( fail > 0 ))
