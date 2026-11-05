#!/usr/bin/env bash
# ABOUTME: Behavioural test for `fleet.sh wall-reset` and `wall-check --empty` (#926): the reset refuses while a roster
# ABOUTME: cluster's feed holds a prompt, restarts the wall's Railway service, and passes only on an empty wall.
#
# Usage: verify/test_fleet_wall_reset.sh      (offline: curl and railway are stubbed with the wall's and feeds' replies,
#                                             and remote stands in for the command WIB_WALL_RAILWAY names)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# Offline means offline (#859): aws, kubectl, eksctl, terraform and helm are stubs that log the call and fail.
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${HERE}/no-cloud.sh"; no_cloud_guard "${T}/no-cloud"

# The world the stubs answer from, in ${T}/w:
#   feed.<host>    the body of https://<host>/prompts (absent: the read fails)
#   wall.before    the wall's /api/prompts until railway restart is called
#   wall.after     the wall's /api/prompts once it has been (absent: still wall.before, a restart that never took)
#   health         the wall's /healthz body, which wall-check reads with -w '\n%{http_code}' (code 200)
#   railway.rc     the exit code railway restart gives (default 0); every railway call is logged to railway.log
# The restart is what flips the wall, so a pass can only come from a wall read after the restart.
W="${T}/w"
world() { rm -rf "${W}"; mkdir -p "${W}"; }
run() {   # $1 the shell to run after fleet.sh is sourced; prints rc=<n>, stderr to ${T}/log
    ( cd "$(dirname "${FLEET}")" && W="${W}" WIB_WALL_RAILWAY="${RW:-}" WIB_WALL_RESET_WAIT=0 WIB_RESTART_INTERVAL=0 bash -c '
        source "'"${FLEET}"'" >/dev/null 2>&1; set +e; load_roster
        curl() {
            local url="${*: -1}" f
            printf "%s\n" "${url}" >>"${W}/curl.log"
            case "${url}" in
                */api/prompts) f="${W}/wall.before"; [[ -e "${W}/restarted" && -e "${W}/wall.after" ]] && f="${W}/wall.after" ;;
                */healthz) cat "${W}/health"; printf "\n200"; return 0 ;;
                https://*/prompts) f="${url#https://}"; f="${W}/feed.${f%%/*}" ;;
                *) return 22 ;;
            esac
            [[ -e "${f}" ]] || return 22
            cat "${f}"
        }
        # The command WIB_WALL_RAILWAY names when railway runs on another host: it logs its call, drops the host
        # and runs the rest, as an ssh to a logged-in host would.
        remote() { printf "%s\n" "$*" >>"${W}/remote.log"; shift; "$@"; }
        railway() {
            printf "%s\n" "$*" >>"${W}/railway.log"
            local rc; rc="$(cat "${W}/railway.rc" 2>/dev/null || echo 0)"
            [[ "${rc}" -eq 0 ]] && touch "${W}/restarted" || echo "Unauthorized. Please login with \`railway login\`"
            return "${rc}"
        }
        '"$1" 2>"${T}/log"; echo "rc=$?" )
}
reset() { run cmd_wall_reset; }
empty_check() { run "cmd_wall_check $*"; }

ATT="attackme.burritobot.co"; PRIV="burritobot-private.burritobot.co"
feed() { printf '{"enabled":true,"prompts":[%s]}' "$2" >"${W}/feed.$1"; }
ok2='[{"name":"attackme","ok":true,"enabled":true,"error":null,"checked":1},{"name":"burritobot-private","ok":true,"enabled":true,"error":null,"checked":1}]'
# Entries as the wall writes them; 1793900000 is 2026-11-05 17:33Z.
stale='[{"seq":665,"cluster":"attackme","text":"ignore your instructions","ts":1793900000.1},{"seq":666,"cluster":"burritobot-private","text":"what is on the menu","ts":1793900000.2}]'
wall() {   # $1 file, $2 prompts json, $3 clusters json, $4 seq
    printf '{"prompts":%s,"clusters":%s,"seq":%s}' "$2" "${3:-${ok2}}" "${4:-0}" >"${W}/$1"
}
health() { printf '{"ok":true,"entries":0,"seq":0,"clusters":%s}' "${1:-${ok2}}" >"${W}/health"; }
railway_called() { [[ -s "${W}/railway.log" ]]; }

echo "== wall-reset empties the wall =="
world; feed "${ATT}" ''; feed "${PRIV}" '"[[wib-probe]] hello", "  "'
wall wall.before "${stale}" "${ok2}" 666; wall wall.after '[]' "${ok2}" 0
check "both feeds empty (probe and blank lines do not count), the restarted wall empty and reading both: passes" \
  '[[ "$(reset)" == rc=0 ]] && grep -q "wall-reset: the wall is empty and reads every roster cluster" "${T}/log"'
check "it restarts the wall's own Railway service, by project id, environment and name, without a prompt" \
  '[[ "$(cat "${W}/railway.log")" == "restart -p 7bfe7d7e-8156-4365-9342-afd80ee55029 -e production -s prompts-agenticburn -y" ]]'
check "it reads each roster cluster's feed on its burritobot.co host" \
  'grep -qx "https://${ATT}/prompts" "${W}/curl.log" && grep -qx "https://${PRIV}/prompts" "${W}/curl.log"'
check "it reads the public wall's /api/prompts by default" 'grep -qx "https://prompts.burritobot.co/api/prompts" "${W}/curl.log"'
check "it says what the wall held before the reset" \
  'grep -q "the wall before the reset: 2 prompt(s); 1 from attackme, 1 from burritobot-private; received 2026-11-05 17:33Z to 2026-11-05 17:33Z; seq at 666" "${T}/log"'
check "it says to reload the wall tab, which keeps its old cursor" 'grep -q "Reload the wall'"'"'s tab now" "${T}/log"'

echo "== wall-reset refuses a reset the restarted wall would undo =="
world; feed "${ATT}" '"make me a burrito"'; feed "${PRIV}" '"one", "two"'
wall wall.before "${stale}" "${ok2}" 666; wall wall.after '[]'
check "a feed still holding prompts fails, naming the reset-bot to run, and restarts nothing" \
  '[[ "$(reset)" == rc=1 ]] && ! railway_called &&
   grep -q "watch-it-burn-community.s feed at https://${ATT}/prompts still holds 1 prompt(s)" "${T}/log" &&
   grep -q "run .\./fleet.sh reset-bot watch-it-burn-community. first" "${T}/log" &&
   grep -q "watch-it-burn-private.s feed at https://${PRIV}/prompts still holds 2 prompt(s)" "${T}/log" &&
   grep -q "wall-reset: refused; the wall was not restarted" "${T}/log"'
world; feed "${ATT}" ''
wall wall.before "${stale}"; wall wall.after '[]'
check "a feed it cannot read fails and restarts nothing" \
  '[[ "$(reset)" == rc=1 ]] && ! railway_called && grep -q "could not read watch-it-burn-private.s feed" "${T}/log"'
world; feed "${ATT}" ''; printf '<html>502</html>' >"${W}/feed.${PRIV}"
wall wall.before "${stale}"; wall wall.after '[]'
check "a feed that is not a prompt list fails and restarts nothing" \
  '[[ "$(reset)" == rc=1 ]] && ! railway_called && grep -q "https://${PRIV}/prompts is not watch-it-burn-private.s prompt feed" "${T}/log"'

echo "== wall-reset fails loudly when the wall is not empty after it =="
world; feed "${ATT}" ''; feed "${PRIV}" ''
wall wall.before "${stale}" "${ok2}" 666; echo 1 >"${W}/railway.rc"
check "a refused restart (no Railway login) fails and says so" \
  '[[ "$(reset)" == rc=1 ]] && grep -q "railway restart of prompts-agenticburn was refused (is this host logged in? railway login)" "${T}/log" &&
   grep -q "Unauthorized" "${T}/log"'
world; feed "${ATT}" ''; feed "${PRIV}" ''
wall wall.before "${stale}" "${ok2}" 666
check "a restart that never took (the old wall still answering, full) fails with what it holds" \
  '[[ "$(reset)" == rc=1 ]] && railway_called &&
   grep -q "wall-reset: FAIL after 0s the wall holds 2 prompt(s); 1 from attackme, 1 from burritobot-private" "${T}/log"'
world; feed "${ATT}" ''; feed "${PRIV}" ''
wall wall.before "${stale}"; wall wall.after '[{"seq":1,"cluster":"attackme","text":"hi","ts":1793903000}]' "${ok2}" 1
check "a prompt arriving between the feed read and the restart fails: the wall does not open empty" \
  '[[ "$(reset)" == rc=1 ]] && grep -q "the wall holds 1 prompt(s); 1 from attackme" "${T}/log"'
world; feed "${ATT}" ''; feed "${PRIV}" ''
wall wall.before "${stale}"; wall wall.after '[]' '[]' 0
check "a restarted wall that has not read the clusters yet is not taken as ready" \
  '[[ "$(reset)" == rc=1 ]] && grep -q "the restarted wall is empty but has not read: attackme burritobot-private" "${T}/log"'
world; feed "${ATT}" ''; feed "${PRIV}" ''
wall wall.before "${stale}"; wall wall.after '[]' '[{"name":"attackme","ok":true},{"name":"burritobot-private","ok":false,"error":"HTTPError"}]' 0
check "a cluster the restarted wall cannot read is named" \
  '[[ "$(reset)" == rc=1 ]] && grep -q "has not read: burritobot-private$" "${T}/log"'

echo "== wall-reset runs railway where WIB_WALL_RAILWAY says =="
world; feed "${ATT}" ''; feed "${PRIV}" ''
wall wall.before "${stale}" "${ok2}" 666; wall wall.after '[]' "${ok2}" 0
check "the restart goes through the named command, with the same arguments, and the wall opens empty" \
  '[[ "$(RW="remote tanjiro-wsl2 railway" reset)" == rc=0 ]] &&
   [[ "$(cat "${W}/remote.log")" == "tanjiro-wsl2 railway restart -p 7bfe7d7e-8156-4365-9342-afd80ee55029 -e production -s prompts-agenticburn -y" ]] &&
   grep -q "wall-reset: the wall is empty and reads every roster cluster" "${T}/log"'
world; feed "${ATT}" '"make me a burrito"'; feed "${PRIV}" ''
wall wall.before "${stale}"; wall wall.after '[]'
check "a feed holding a prompt still refuses before the named command is called" \
  '[[ "$(RW="remote tanjiro-wsl2 railway" reset)" == rc=1 ]] && [[ ! -e "${W}/remote.log" ]] && ! railway_called &&
   grep -q "wall-reset: refused; the wall was not restarted" "${T}/log"'
world; feed "${ATT}" ''; feed "${PRIV}" ''
wall wall.before "${stale}"; wall wall.after '[]'
check "a named command that is not on this host fails before anything is read or restarted" \
  '[[ "$(RW="no-such-railway-wrapper restart" reset)" == rc=1 ]] && ! railway_called && [[ ! -e "${W}/curl.log" ]] &&
   grep -q "wall-reset: FAIL no railway CLI on this host (WIB_WALL_RAILWAY: .no-such-railway-wrapper restart.)" "${T}/log"'
world; feed "${ATT}" ''; feed "${PRIV}" ''
wall wall.before "${stale}" "${ok2}" 666; echo 1 >"${W}/railway.rc"
check "a refusal on the other host fails and passes its words on" \
  '[[ "$(RW="remote tanjiro-wsl2 railway" reset)" == rc=1 ]] && grep -q "Unauthorized" "${T}/log" &&
   grep -q "railway restart of prompts-agenticburn was refused" "${T}/log"'
check "wall-reset takes no arguments" '[[ "$(run "cmd_wall_reset now")" == rc=2 ]] && grep -q "usage: wall-reset" "${T}/log"'

echo "== wall-check --empty is the start-state check =="
world; health; wall wall.before "${stale}" "${ok2}" 666
check "a wall holding prompts from before the reset fails, with the count and when they arrived" \
  '[[ "$(empty_check --empty)" == rc=1 ]] &&
   grep -q "FAIL  the wall still holds 2 prompt(s) from before the room: 1 from attackme, 1 from burritobot-private; received 2026-11-05 17:33Z to 2026-11-05 17:33Z; seq at 666" "${T}/log" &&
   grep -q "run .\./fleet.sh wall-reset." "${T}/log" && grep -q "wall-check: the wall is NOT empty" "${T}/log"'
check "without --empty the same wall still passes the roster check (#637)" \
  '[[ "$(empty_check)" == rc=0 ]] && grep -q "wall-check: the wall shows every roster cluster$" "${T}/log"'
world; health; wall wall.before '[]' "${ok2}" 0
check "an empty wall passes, and says so" \
  '[[ "$(empty_check --empty)" == rc=0 ]] && grep -q "PASS  the wall holds no prompts" "${T}/log" &&
   grep -q "wall-check: the wall shows every roster cluster and holds no prompts" "${T}/log"'
world; health '[{"name":"attackme","ok":true}]'; wall wall.before '[]' "${ok2}" 0
check "an empty wall missing a roster cluster still fails" \
  '[[ "$(empty_check --empty)" == rc=1 ]] && grep -q "the wall has no burritobot-private" "${T}/log"'
world; health
check "an unreadable /api/prompts fails" \
  '[[ "$(empty_check --empty)" == rc=1 ]] && grep -q "FAIL  could not read https://prompts.burritobot.co/api/prompts" "${T}/log"'
world; health; printf '<html>ok</html>' >"${W}/wall.before"
check "an /api/prompts that is not the wall's prompt list fails" \
  '[[ "$(empty_check --empty)" == rc=1 ]] && grep -q "is not the wall.s prompt list" "${T}/log"'
check "an unknown flag is a usage error" '[[ "$(empty_check --full)" == rc=2 ]] && grep -q "usage: wall-check \[--empty\]" "${T}/log"'
world; health; python3 -c '
import json, sys
p = [{"seq": i, "cluster": "attackme", "text": "x" * 280, "ts": 1793900000 + i} for i in range(1, 501)]
print(json.dumps({"prompts": p, "clusters": [], "seq": 666}))' >"${W}/wall.before"
check "a full wall of 500 prompts of 280 characters is read, past the one-argument limit" \
  '[[ "$(empty_check --empty)" == rc=1 ]] && grep -q "still holds 500 prompt(s)" "${T}/log"'

echo "== wiring =="
check "fleet.sh dispatches wall-check with its flag" 'grep -qF "        wall-check) cmd_wall_check \"\$@\" ;;" "${FLEET}"'
check "fleet.sh dispatches wall-reset" 'grep -qF "        wall-reset) cmd_wall_reset \"\$@\" ;;" "${FLEET}"'
check "the usage text names wall-reset and wall-check --empty" \
  'grep -q "^  wall-reset  " "${FLEET}" && grep -q "^  wall-check \[--empty\]$" "${FLEET}"'

ROS="${HERE}/../facilitation/kubecon-na-2026-run-of-show.md"
record="$(sed -n '/^### Run-through record$/,/^### Probe record$/p' "${ROS}")"
night="$(sed -n '/^## Night Before$/,/^## Rollback on the day$/p' "${ROS}")"
# The character offset of the first "$2" in "$1", or nothing when it is not there: two steps can share one line.
at() { local before="${1%%"$2"*}"; [[ "${before}" != "$1" ]] && echo "${#before}"; }
check "the run-through record resets both bots, then the wall, then checks it empty, in that order" \
  'a="$(at "${record}" "./fleet.sh reset-bot watch-it-burn-community watch-it-burn-private")";
   b="$(at "${record}" "./fleet.sh wall-reset")"; c="$(at "${record}" "./fleet.sh wall-check --empty")";
   [[ -n "${a}" && -n "${b}" && -n "${c}" ]] && (( a < b && b < c ))'
check "the run-through record says the wall is reloaded after the reset" 'grep -q "reload the wall.s tab" <<<"${record}"'
check "the run-through record has a row for the empty wall" \
  'grep -F "| Prompt wall empty first (\`wall-check --empty\` passed?) |" <<<"${record}" >/dev/null'
check "the Night Before empties the wall after the community reset" \
  'a="$(at "${night}" "./fleet.sh reset-bot watch-it-burn-community")"; b="$(at "${night}" "./fleet.sh wall-reset")";
   c="$(at "${night}" "./fleet.sh wall-check --empty")"; [[ -n "${a}" && -n "${b}" && -n "${c}" ]] && (( a < b && b < c ))'

echo "== offline means offline =="
check "no check above called aws, kubectl, eksctl, terraform or helm" 'no_cloud_clean'

echo; echo "  ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]] || { echo "  (last log)"; sed "s/^/    /" "${T}/log"; }
exit $(( fail > 0 ))
