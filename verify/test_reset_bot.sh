#!/usr/bin/env bash
# ABOUTME: Behavioural tests for `fleet.sh reset-bot` (#539): guard-proxy is restarted by a pod delete and the
# ABOUTME: public /cost must read $0 over 0 requests afterwards. Offline; kubectl and curl are shims.
#
# Usage: verify/test_reset_bot.sh      (no cloud access)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
ROS="${HERE}/../facilitation/kubecon-na-2026-run-of-show.md"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/states"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# ---- shims: every external command records its argv and answers from env the test controls ----
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $*" >>"${CALLS}"; exit 0
S
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $* [AWS_PROFILE=${AWS_PROFILE:-}]" >>"${CALLS}"
case "$*" in
  "config current-context") echo "${KCTX}" ;;
  *"get pods"*"-o jsonpath"*) echo "guard-proxy-old" ;;
  *"get pods"*"-o json"*)
      if [[ "${READY:-1}" == 1 ]]; then
          echo '{"items":[{"metadata":{"name":"guard-proxy-old","deletionTimestamp":"x"},"status":{"conditions":[{"type":"Ready","status":"True"}]}},
                          {"metadata":{"name":"guard-proxy-new"},"status":{"conditions":[{"type":"Ready","status":"True"}]}}]}'
      else
          echo '{"items":[{"metadata":{"name":"guard-proxy-new"},"status":{"conditions":[{"type":"Ready","status":"False"}]}}]}'
      fi ;;
  *"delete pod"*) exit "${DELETE_RC:-0}" ;;
esac
exit 0
S
# curl: answers /cost with the next line of ${T}/cost.replies, the last line again once they run out. A line
# reading FAIL is an unreachable host (curl -f exits non-zero with nothing on stdout).
cat >"${SHIM}/curl" <<'S'
#!/usr/bin/env bash
url=""; for a in "$@"; do [[ "${a}" == http* ]] && url="${a}"; done
echo "curl ${url}" >>"${CALLS}"
n="$(grep -c '^curl ' "${CALLS}")"; total="$(wc -l <"${T}/cost.replies")"
reply="$(sed -n "$(( n < total ? n : total ))p" "${T}/cost.replies")"
[[ "${reply}" == FAIL ]] && exit 22
printf '%s' "${reply}"
S
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"
C=watch-it-burn-community; ADMIN=watch-it-burn-private
touch "${T}/states/${C}.tfstate" "${T}/states/${ADMIN}.tfstate"
ctx_of() { printf 'arn:aws:eks:us-west-2:111122223333:cluster/%s' "$1"; }
ZERO='{"tier": "nova", "requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "usd": 0.0, "cap_usd": 25.0, "budget_guard": false}'
SPENT='{"tier": "nova", "requests": 3, "input_tokens": 9000, "output_tokens": 1300, "total_tokens": 10300, "usd": 0.0114, "cap_usd": 25.0, "budget_guard": false}'
replies() { printf '%s\n' "$@" >"${T}/cost.replies"; }
# Sourcing fleet.sh: the source guard keeps main() from running; WIB_* settings make every wait instant.
src() { # $1: bash snippet to run after sourcing
  : >"${CALLS}"; : >"${T}/stderr"
  ( cd "$(dirname "${FLEET}")" && WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" WIB_DEFAULT_ACCOUNT=accen-dev \
      WIB_RESTART_WAIT=2 WIB_RESTART_INTERVAL=1 \
      bash -c "source '${FLEET}' >/dev/null 2>&1; $1" 2>>"${T}/stderr" )
}

echo "== reset-bot restarts guard-proxy and reads the counter back at zero =="
replies "${ZERO}"
KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "exits 0 once the new pod is Ready and /cost reads zero" '[[ "${rc}" -eq 0 ]]'
check "deletes the guard-proxy pod by its selector, in ns agent, with an explicit context" \
  'grep -q -- "kubectl --context $(ctx_of "${C}") -n agent get pods -l app.kubernetes.io/name=guard-proxy" "${CALLS}" && grep -q "kubectl --context $(ctx_of "${C}") -n agent delete pod guard-proxy-old --wait=false" "${CALLS}"'
check "runs in the roster's account" 'grep "delete pod" "${CALLS}" | grep -q "AWS_PROFILE=accen-dev"'
check "a pod delete, never a rollout restart or a spec edit (Argo CD owns the spec)" '! grep -qE "rollout|set env|patch|annotate|scale" "${CALLS}"'
check "reads the counter the room sees, on attackme" 'grep -q "^curl https://attackme.agenticburn.com/cost$" "${CALLS}"'
check "the delete comes before the read" 'grep -n "delete pod\|^curl " "${CALLS}" | head -1 | grep -q "delete pod"'
check "says the counter is at zero, with the figure" 'grep -q "counter at zero on https://attackme.agenticburn.com/cost (\$0.0000 over 0 requests)" "${T}/stderr"'

echo "== the old pod answering for a moment is waited out, not taken as the reset =="
replies "${SPENT}" "${ZERO}"
KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a first read of the old figure, then zero, passes" '[[ "${rc}" -eq 0 ]] && [[ "$(grep -c "^curl " "${CALLS}")" -eq 2 ]]'

echo "== a counter that is not zero, or cannot be read, is a failure =="
replies "${SPENT}"
KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a counter still at the first run's spend fails" '[[ "${rc}" -ne 0 ]]'
check "and says what it read" 'grep -q "still reads \$0.0114 over 3 requests" "${T}/stderr"'
replies FAIL
KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "an unreachable /cost fails" '[[ "${rc}" -ne 0 ]] && grep -q "still reads unreadable" "${T}/stderr"'
replies '{"usd": 0.0}'
KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a reply without the request count is not taken as zero" '[[ "${rc}" -ne 0 ]]'

echo "== the restart has to finish before anything is read =="
replies "${ZERO}"
READY=0 KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "no Ready replacement fails, and /cost is not read" '[[ "${rc}" -ne 0 ]] && ! grep -q "^curl " "${CALLS}"'
DELETE_RC=1 KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a refused delete fails" '[[ "${rc}" -ne 0 ]] && grep -q "the delete was refused" "${T}/stderr"'

echo "== the target is confirmed before any mutation =="
KCTX="$(ctx_of watch-it-burn-whitney-admin)" src "cmd_reset_bot ${C}"; rc=$?
check "a kubeconfig pointing at another cluster is refused" '[[ "${rc}" -ne 0 ]] && ! grep -q "delete" "${CALLS}"'
src "cmd_reset_bot packt-cluster-1"; rc=$?
check "a non-watch-it-burn name is refused before kubectl runs" '[[ "${rc}" -ne 0 ]] && ! grep -q "kubectl" "${CALLS}"'
src "cmd_reset_bot"; rc=$?
check "no name is a usage error" '[[ "${rc}" -ne 0 ]] && grep -q "usage: reset-bot <name...>" "${T}/stderr"'

echo "== an admin cluster is read on its own host =="
replies "${ZERO}"
KCTX="$(ctx_of "${ADMIN}")" src "cmd_reset_bot ${ADMIN}"; rc=$?
check "michael-admin reads burritobot-private.agenticburn.com/cost" '[[ "${rc}" -eq 0 ]] && grep -q "^curl https://burritobot-private.agenticburn.com/cost$" "${CALLS}"'

echo "== wired into the driver =="
src_txt="$(cat "${FLEET}")"; usage_txt="$(sed -n '/^usage() {/,/^}/p' "${FLEET}")"
check "main dispatches reset-bot" 'grep -qE "^        reset-bot\) cmd_reset_bot" <<<"${src_txt}"'
check "usage documents reset-bot" 'grep -q "^    reset-bot <name...>" <<<"${usage_txt}"'

echo "== the run-of-show resets the community bot before every run on one bring-up =="
ros="$(cat "${ROS}")"
night="$(sed -n '/^## Night Before$/,/^## Rollback on the day$/p' "${ROS}")"
record="$(sed -n '/^### Run-through record$/,/^### Probe record$/p' "${ROS}")"
check "Night Before resets the community cluster" 'grep -q "fleet.sh reset-bot watch-it-burn-community" <<<"${night}"'
check "the reset comes after the probe, which spends on attackme" \
  '[[ "$(grep -n "kubecon_probe.py community" <<<"${night}" | head -1 | cut -d: -f1)" -lt "$(grep -n "reset-bot" <<<"${night}" | head -1 | cut -d: -f1)" ]]'
check "the run-through record says to reset before each run" 'grep -q "fleet.sh reset-bot watch-it-burn-community" <<<"${record}"'
check "the counter is read back at zero in the run-of-show" 'grep -q "https://attackme.agenticburn.com/cost" <<<"${ros}"'
check "the run-of-show never restarts guard-proxy with rollout restart" '! grep -qE "rollout restart[^|]*guard-proxy" <<<"${ros}"'
echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
