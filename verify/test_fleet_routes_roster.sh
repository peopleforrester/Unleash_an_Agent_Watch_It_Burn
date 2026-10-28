#!/usr/bin/env bash
# ABOUTME: Behavioural test for the KubeCon routes table (#502): `fleet.sh routes roster` emits exactly the
# ABOUTME: community and admin hosts and their service hosts, and `router-check` holds the live router to them.
#
# Usage: verify/test_fleet_routes_roster.sh      (offline: kubectl, the record and the reload are stubbed)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .fleet-roster-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 TMPDIR="${T}"

# The breakout's two clusters, and every service host each one carries (console.conf, #233). The service
# list is read from fleet.sh's WIB_SERVICE_HOSTS so a new service host does not need a second edit here.
SERVICES="$(sed -n 's/^readonly WIB_SERVICE_HOSTS="\(.*\)"$/\1/p' "${FLEET}")"
NSVC="$(wc -w <<<"${SERVICES}")"
# Both domains serve the roster (#651): every row has a burritobot.co twin on the same upstream.
expected() {
    local h d
    for d in agenticburn.com burritobot.co; do
        for h in attackme burritobot-private; do
            echo "${h}.${d}"
            for s in ${SERVICES}; do echo "${s}-${h}.${d}"; done
        done
    done | sort
}

# An apex checkout whose HEAD carries $1 as routes.map, and a state dir holding a leftover attendee cluster.
fixture() {   # $1 the published table; leaves ${T}/apex and ${T}/states
    rm -rf "${T}/apex" "${T}/states" "${T}/logs"; mkdir -p "${T}/apex" "${T}/states" "${T}/logs"
    git init -q -b main "${T}/apex"
    git -C "${T}/apex" config user.email fixture@test; git -C "${T}/apex" config user.name fixture
    printf '%s' "$1" >"${T}/apex/routes.map"
    git -C "${T}/apex" add -A; git -C "${T}/apex" commit -qm base
    # A Portland-era attendee left on disk: one resource, so prune_empty_states keeps it.
    echo '{"resources":[{}]}' >"${T}/states/watch-it-burn-attendee-007.tfstate"
}

# Run cmd_routes against a sourced fleet.sh, under the set -e it runs with in production, so its status is
# the shell's exit code. Every console answers with an LB named for its cluster,
# except the clusters in NO_LB. Nothing records or reloads: those two have their own tests.
routes() {   # $@ cmd_routes arguments; prints rc=<n>, stderr to ${T}/log
    ( cd "$(dirname "${FLEET}")" && WIB_APEX_DIR="${T}/apex" WIB_STATE_DIR="${T}/states" \
        WIB_LOG_DIR="${T}/logs" NO_LB="${NO_LB:-}" bash -c '
        source "'"${FLEET}"'" >/dev/null 2>&1
        load_roster
        require_tools() { :; }
        provider_write_kubeconfig() { printf "%s\n" "$1" >"$2"; }
        read_membership() { echo accen-dev; }
        kubectl() { local n; n="$(cat "${KUBECONFIG}")"; [[ " ${NO_LB} " == *" ${n} "* ]] || printf "lb-%s.elb.test" "${n}"; }
        publish_routes_table() { :; }
        apply_routes_table() { :; }
        cmd_routes '"$*"'' 2>"${T}/log"; echo "rc=$?" )
}
table_hosts() { awk '!/^#/ && NF { print $1 }' "${T}/apex/routes.map" | sort; }

echo "== routes roster emits exactly the community and admin hosts =="
fixture $'# old\n'
out="$(routes roster)"
check "it succeeds" '[[ "${out}" == *rc=0* ]]'
check "the table is exactly the two roster hosts and their service hosts" \
  'diff <(table_hosts) <(expected) >/dev/null'
check "that is two consoles and ${NSVC} services each, on both domains" '[[ "$(table_hosts | wc -l)" -eq $(( 4 * (NSVC + 1) )) ]]'
check "each burritobot.co twin points at the same cluster as its agenticburn.com row" \
  'grep -qx "attackme.burritobot.co  lb-watch-it-burn-community.elb.test:443" "${T}/apex/routes.map" &&
   grep -qx "grafana-burritobot-private.burritobot.co  lb-watch-it-burn-private.elb.test:443" "${T}/apex/routes.map"'
# derive-roster keeps the FIRST host it meets for a cluster, so agenticburn.com stays the wall's name until #651 step B.
check "the burritobot.co row comes before its agenticburn.com twin, so the router's roster names burritobot.co" \
  '[[ "$(grep -n "^attackme.burritobot.co " "${T}/apex/routes.map" | cut -d: -f1)" -lt "$(grep -n "^attackme.agenticburn.com " "${T}/apex/routes.map" | cut -d: -f1)" ]]'
check "no attendee-pool row, although attendee state is on disk" '! grep -q attendee "${T}/apex/routes.map"'
check "no roundN alias (#502)" '! grep -q "^round" "${T}/apex/routes.map"'
check "each host points at its own cluster on :443" \
  'grep -qx "attackme.agenticburn.com  lb-watch-it-burn-community.elb.test:443" "${T}/apex/routes.map" &&
   grep -qx "grafana-burritobot-private.agenticburn.com  lb-watch-it-burn-private.elb.test:443" "${T}/apex/routes.map"'
check "roster_route_hosts names the same set the table carries" \
  'diff <(cd "$(dirname "${FLEET}")" && bash -c "source \"${FLEET}\" >/dev/null 2>&1; load_roster; roster_route_hosts" 2>/dev/null | sort) <(expected) >/dev/null'

echo "== the default run still carries the pool =="
fixture $'# old\n'
out="$(routes)"
check "routes with no argument also routes the leftover attendee" \
  '[[ "${out}" == *rc=0* ]] && grep -q "lb-watch-it-burn-attendee-007.elb.test" "${T}/apex/routes.map"'
check "and still emits no roundN alias" '! grep -q "^round" "${T}/apex/routes.map"'

echo "== a roster run drops the published pool rows, and says so =="
old=$'# old\nattackme.agenticburn.com  old:443\nburritobot-private.agenticburn.com  old:443\nroundadmin.agenticburn.com  old:443\nbane-sabrina.agenticburn.com  old:443\ngrafana-bane-sabrina.agenticburn.com  old:443\n'
fixture "${old}"
out="$(routes roster)"
check "it is not refused as a shrink" '[[ "${out}" == *rc=0* ]] && diff <(table_hosts) <(expected) >/dev/null'
check "the log names the pool rows leaving" \
  'grep -q "leave the table" "${T}/log" && grep -q -- "- bane-sabrina.agenticburn.com" "${T}/log"'
check "the retired roundadmin alias is not counted as a loss" '! grep -q -- "- roundadmin" "${T}/log"'

echo "== a roster run with an admin console down is still refused =="
fixture "${old}"
out="$(NO_LB=watch-it-burn-private routes roster)"
check "it refuses" '[[ "${out}" == *rc=1* ]] && grep -q REFUSING "${T}/log"'
check "it names the roster host it would drop" 'grep -q -- "- burritobot-private.agenticburn.com" "${T}/log"'
check "and leaves the table as it was" 'diff -q <(printf "%s" "${old}") "${T}/apex/routes.map" >/dev/null'

echo "== an unknown scope is a usage error =="
fixture $'# old\n'
out="$(routes pool)"
check "routes pool exits 2" '[[ "${out}" == *rc=2* ]]'

echo "== router-check holds the live router to the roster =="
rc_of() {   # $1 roster.json body; prints rc=<n>, stderr to ${T}/log
    printf '%s' "$1" >"${T}/roster.json"
    ( cd "$(dirname "${FLEET}")" && WIB_ROUTER_ROSTER_URL="file://${T}/roster.json" bash -c '
        source "'"${FLEET}"'" >/dev/null 2>&1; load_roster; cmd_router_check' 2>"${T}/log"; echo "rc=$?" )
}
two='{"host":"attackme.burritobot.co","name":"attackme"},{"host":"burritobot-private.burritobot.co","name":"burritobot-private"}'
check "exactly the two roster hosts passes" '[[ "$(rc_of "[${two}]")" == rc=0 ]]'
check "the roster under its agenticburn.com names fails: the wall must show burritobot.co" \
  '[[ "$(rc_of "[{\"host\":\"attackme.agenticburn.com\"},{\"host\":\"burritobot-private.agenticburn.com\"}]")" == rc=1 ]]'
check "a pool cluster still routed fails, and is named" \
  '[[ "$(rc_of "[${two},{\"host\":\"bane-sabrina.agenticburn.com\",\"name\":\"bane-sabrina\"}]")" == rc=1 ]] &&
   grep -q "still serves bane-sabrina.agenticburn.com" "${T}/log"'
check "a missing admin host fails, and is named" \
  '[[ "$(rc_of "[{\"host\":\"attackme.burritobot.co\"}]")" == rc=1 ]] &&
   grep -q "no row for burritobot-private.burritobot.co" "${T}/log"'
check "an empty router fails" '[[ "$(rc_of "[]")" == rc=1 ]]'
check "a reply that is not the host list fails" '[[ "$(rc_of "<html>404</html>")" == rc=1 ]]'
rm -f "${T}/roster.json"
check "an unreachable router fails" \
  '[[ "$(cd "$(dirname "${FLEET}")" && WIB_ROUTER_ROSTER_URL="file://${T}/absent.json" bash -c "source \"${FLEET}\" >/dev/null 2>&1; load_roster; cmd_router_check" 2>/dev/null; echo "rc=$?")" == rc=1 ]]'

echo "== wiring =="
check "fleet.sh dispatches router-check" 'grep -q "^        router-check) cmd_router_check ;;$" "${FLEET}"'
check "the usage text names routes roster and router-check" \
  'grep -q "^  routes \[roster\]" "${FLEET}" && grep -q "^  router-check" "${FLEET}"'

ROS="${HERE}/../facilitation/kubecon-na-2026-run-of-show.md"
line_of() { grep -nF -- "$1" "${ROS}" | head -1 | cut -d: -f1; }
check "the Night Before writes the roster table and checks the router before check-tls" \
  '[[ -n "$(line_of "./fleet.sh routes roster")" && -n "$(line_of "./fleet.sh router-check")" ]] &&
   (( $(line_of "./fleet.sh routes roster") < $(line_of "./fleet.sh router-check") &&
      $(line_of "./fleet.sh router-check") < $(line_of "./fleet.sh check-tls attackme") ))'
check "the C1 beat names the beacon view by URL" \
  'grep -A3 "^- C1 exfiltrate" "${ROS}" | grep -qF "https://agenticburn.com/beacon/view"'

echo; echo "  ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]] || { echo "  (last log)"; sed "s/^/    /" "${T}/log"; }
exit $(( fail > 0 ))
