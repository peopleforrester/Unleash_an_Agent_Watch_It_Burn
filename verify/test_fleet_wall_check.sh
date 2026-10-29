#!/usr/bin/env bash
# ABOUTME: Behavioural test for `fleet.sh wall-check` (#637): the prompt wall's /healthz answers 200 and lists every
# ABOUTME: roster cluster with its prompts readable, and the KubeCon Night Before and segment 2 name the wall.
#
# Usage: verify/test_fleet_wall_check.sh      (offline: curl is stubbed with the wall's reply)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# Run cmd_wall_check against a sourced fleet.sh with curl answering $2 (HTTP code) and $1 (body), the way
# `curl -sS -w '\n%{http_code}'` prints them. CURL_RC non-zero is a wall that cannot be reached at all.
wall() {   # $1 body, $2 code; prints rc=<n>, stderr to ${T}/log
    printf '%s' "$1" >"${T}/body"
    ( cd "$(dirname "${FLEET}")" && BODY="${T}/body" CODE="$2" CURL_RC="${CURL_RC:-0}" bash -c '
        source "'"${FLEET}"'" >/dev/null 2>&1; load_roster
        curl() { [[ "${CURL_RC}" -eq 0 ]] || return "${CURL_RC}"; printf "%s\n" "${*: -1}" >"${BODY}.url"; cat "${BODY}"; printf "\n%s" "${CODE}"; }
        cmd_wall_check' 2>"${T}/log"; echo "rc=$?" )
}
c() { printf '{"name":"%s","enabled":true,"ok":%s,"error":%s,"checked":1793222017.95}' "$1" "${2:-true}" "${3:-null}"; }
both="$(c attackme),$(c burritobot-private)"

echo "== wall-check holds the wall to the roster =="
check "both roster clusters, readable, passes" \
  '[[ "$(wall "{\"ok\":true,\"entries\":2,\"seq\":2,\"clusters\":[${both}]}" 200)" == rc=0 ]] &&
   grep -q "PASS  the wall shows attackme" "${T}/log" && grep -q "PASS  the wall shows burritobot-private" "${T}/log"'
check "it reads the public wall's /healthz by default" \
  '[[ "$(cat "${T}/body.url")" == "https://prompts.agenticburn.com/healthz" ]]'
check "a cluster beyond the roster does not fail it (router-check owns extra hosts)" \
  '[[ "$(wall "{\"clusters\":[${both},$(c bane-sabrina)]}" 200)" == rc=0 ]]'
check "a missing admin cluster fails, and is named" \
  '[[ "$(wall "{\"clusters\":[$(c attackme)]}" 200)" == rc=1 ]] && grep -q "the wall has no burritobot-private" "${T}/log"'
check "a missing community cluster fails, and is named" \
  '[[ "$(wall "{\"clusters\":[$(c burritobot-private)]}" 200)" == rc=1 ]] && grep -q "the wall has no attackme" "${T}/log"'
check "a listed cluster the wall cannot read fails, with the error the wall gives" \
  '[[ "$(wall "{\"clusters\":[$(c attackme false "\"HTTP 502\""),$(c burritobot-private)]}" 200)" == rc=1 ]] &&
   grep -q "lists attackme but cannot read its prompts: HTTP 502" "${T}/log"'
check "a name that only starts with a roster name does not count" \
  '[[ "$(wall "{\"clusters\":[$(c attackme-old),$(c burritobot-private)]}" 200)" == rc=1 ]] && grep -q "the wall has no attackme" "${T}/log"'
check "an empty cluster list fails on both" \
  '[[ "$(wall "{\"clusters\":[]}" 200)" == rc=1 ]] && [[ "$(grep -c "the wall has no" "${T}/log")" -eq 2 ]]'
check "a 404 from the router fails, and names the code" \
  '[[ "$(wall "<html>404</html>" 404)" == rc=1 ]] && grep -q "answered 404, not 200" "${T}/log"'
check "a 200 that is not the health report fails" '[[ "$(wall "<html>ok</html>" 200)" == rc=1 ]]'
check "a 200 with no cluster list fails" '[[ "$(wall "{\"ok\":true}" 200)" == rc=1 ]]'
check "an unreachable wall fails" '[[ "$(CURL_RC=7 wall "" 000)" == rc=1 ]] && grep -q "could not read" "${T}/log"'

echo "== wiring =="
check "fleet.sh dispatches wall-check" 'grep -q "^        wall-check) cmd_wall_check ;;$" "${FLEET}"'
check "the usage text names wall-check" 'grep -q "^  wall-check" "${FLEET}"'

ROS="${HERE}/../facilitation/kubecon-na-2026-run-of-show.md"
KUBECON="${HERE}/../gitops/ai-layer/web/kubecon.html"
WALL="https://prompts.agenticburn.com"
line_of() { grep -nF -- "$1" "${ROS}" | head -1 | cut -d: -f1; }
section() { awk -v h="$1" '$0 ~ "^#+ "h { on=1; next } on && /^#+ / { exit } on' "${ROS}"; }   # to the next heading
check "the Night Before runs wall-check after router-check and before check-tls" \
  '[[ -n "$(line_of "./fleet.sh wall-check")" ]] &&
   (( $(line_of "./fleet.sh router-check") < $(line_of "./fleet.sh wall-check") &&
      $(line_of "./fleet.sh wall-check") < $(line_of "./fleet.sh check-tls attackme") ))'
check "the Night Before step names the health URL of the wall" 'section "Night Before" | grep -qF "${WALL}/healthz"'
check "the Night Before keeps the wall off the lab-platform roster until after the event" \
  'section "Night Before" | tr "\n" " " | grep -q "lab-platform#137"'
check "segment 1 puts the wall URL on screen (#639)" \
  'section "Segment 1: Cold open" | grep -qF "${WALL}"'
check "the segment table shows the wall on screen from segment 1" \
  'grep -E "^\| 1 \|" "${ROS}" | grep -qF "prompts.agenticburn.com"'
check "the /kubecon page projects the wall in segment 1, as the run-of-show does (#639)" \
  'sed -n "/SEGMENT 1:/,/<article/p" "${KUBECON}" | grep -qF "href=\"${WALL}\""'

echo; echo "  ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]] || { echo "  (last log)"; sed "s/^/    /" "${T}/log"; }
exit $(( fail > 0 ))
