#!/usr/bin/env bash
# ABOUTME: Behavioural tests for the unattended scheduled bring-up: stage order and arguments, refusal on
# ABOUTME: a missing dependency or credential, the single-run lock, and stopping at the first failed stage.
# ABOUTME: Offline. fleet.sh, aws and railway are shims; nothing here can reach AWS.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHED="${HERE}/../infra/terraform/fleet/scheduled-up.sh"
T="$(mktemp -d -p "${HERE}/.." .sched-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/logs"; fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# A fake fleet driver that records the verbs it was called with, and fails whichever verb FAIL_VERB names.
cat >"${SHIM}/fleet.sh" <<'S'
#!/usr/bin/env bash
echo "$*" >> "${T}/calls"
[[ "${FAIL_VERB:-}" != "" && "$1" == "${FAIL_VERB}" ]] && exit 7
exit 0
S
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
[[ "${AWS_OK:-1}" == "1" ]] || exit 255
echo 515966504359
S
cat >"${SHIM}/railway" <<'S'
#!/usr/bin/env bash
[[ "${RAILWAY_OK:-1}" == "1" ]] || exit 1
echo "Logged in as Test"
S
chmod +x "${SHIM}"/*
# terraform/kubectl/helm/dig are only probed for presence, so an empty stub is enough.
for b in terraform kubectl helm dig; do printf '#!/usr/bin/env bash\nexit 0\n' >"${SHIM}/${b}"; chmod +x "${SHIM}/${b}"; done

run() { # run <args...> ; env overrides come from the caller
    rm -f "${T}/calls"
    ( export T PATH="${SHIM}:${PATH}" WIB_FLEET_BIN="${SHIM}/fleet.sh" WIB_SCHED_LOG_DIR="${T}/logs" \
             WIB_SCHED_LOCK="${T}/logs/.lock"
      bash "${SCHED}" "$@" 2>&1; echo "rc=$?" )
}

echo "== the happy path builds the roster, then the pool, then verifies =="
out="$(run 2)"
calls="$(cat "${T}/calls" 2>/dev/null)"
check "exits zero" 'grep -q "rc=0" <<<"$out"'
check "stage 1 is the instructor roster, both owners" '[[ "$(sed -n 1p <<<"$calls")" == "instructors up both" ]]'
check "stage 2 scales the attendee pool to the count given" '[[ "$(sed -n 2p <<<"$calls")" == "scale 2" ]]'
check "stage 3 verifies everything" '[[ "$(sed -n 3p <<<"$calls")" == "verify all" ]]'
check "no fourth stage" '[[ "$(wc -l <<<"$calls")" == "3" ]]'
check "reports completion with the count" 'grep -q "COMPLETE: instructor roster + 2 attendee cluster" <<<"$out"'

echo "== the count is the argument, then the env, then 2 =="
out="$(run 7)"; check "an argument wins" 'grep -qx "scale 7" "${T}/calls"'
out="$(WIB_SCHED_ATTENDEES=5 run)"; check "the env is used when no argument is given" 'grep -qx "scale 5" "${T}/calls"'
out="$(run)"; check "the default is 2" 'grep -qx "scale 2" "${T}/calls"'
out="$(run twelve)"; check "a non-numeric count is a usage error, and builds nothing" \
    'grep -q "rc=2" <<<"$out" && [[ ! -s "${T}/calls" ]]'

echo "== the roster can be skipped =="
out="$(WIB_SCHED_INSTRUCTORS=none run 2)"
check "'none' builds attendees only" '! grep -q "instructors" "${T}/calls" && grep -qx "scale 2" "${T}/calls"'
out="$(WIB_SCHED_INSTRUCTORS=whitney run 2)"
check "an owner selector is passed through" 'grep -qx "instructors up whitney" "${T}/calls"'

echo "== it refuses to start when a dependency or credential is missing =="
out="$(AWS_OK=0 run 2)"
check "a profile that does not authenticate stops the run before any build" \
    'grep -q "PREFLIGHT FAILED" <<<"$out" && grep -q "does not authenticate" <<<"$out" && [[ ! -s "${T}/calls" ]]'
out="$(RAILWAY_OK=0 run 2)"
check "no railway login stops the run, naming the claimable consequence" \
    'grep -q "railway is not logged in" <<<"$out" && grep -q "claimable" <<<"$out" && [[ ! -s "${T}/calls" ]]'
# A tool that is genuinely absent everywhere, rather than one hidden from the shim: setup_env appends the
# known tool directories, so hiding a shim only unhides the real binary behind it.
out="$( export T PATH="${SHIM}:${PATH}" WIB_FLEET_BIN="${T}/no-such-fleet.sh" WIB_SCHED_LOG_DIR="${T}/logs" \
               WIB_SCHED_LOCK="${T}/logs/.lock"; rm -f "${T}/calls"; bash "${SCHED}" 2 2>&1; echo "rc=$?" )"
check "a missing fleet driver is named and nothing is built" \
    'grep -q "not on PATH: fleet.sh at" <<<"$out" && grep -q "rc=1" <<<"$out" && [[ ! -s "${T}/calls" ]]'

echo "== a failed stage stops the run =="
out="$(FAIL_VERB=instructors run 2)"
check "a failed roster stage does not go on to scale or verify" \
    'grep -q "STAGE instructors: FAILED (exit 7)" <<<"$out" && ! grep -q "scale" "${T}/calls" && grep -q "rc=7" <<<"$out"'
out="$(FAIL_VERB=scale run 2)"
check "a failed scale stage does not report completion" \
    'grep -q "STAGE attendees: FAILED" <<<"$out" && ! grep -q "COMPLETE" <<<"$out"'
out="$(FAIL_VERB=verify run 2)"
check "a failed verify fails the whole run" 'grep -q "rc=7" <<<"$out" && ! grep -q "COMPLETE" <<<"$out"'

echo "== two runs cannot build at once, and a bring-up waits out a running teardown =="
( export T PATH="${SHIM}:${PATH}"; exec 9>"${T}/logs/.lock"; flock 9; sleep 5 ) &
locker=$!; sleep 0.5
out="$(WIB_SCHED_LOCK_WAIT=1 run 2)"
check "a run gives up rather than building on top of another" \
    'grep -q "still holds" <<<"$out" && grep -q "rc=1" <<<"$out" && [[ ! -s "${T}/calls" ]]'
# The default wait is long enough for a teardown to finish and hand the lock over, so the bring-up runs.
out="$(WIB_SCHED_LOCK_WAIT=30 run 2)"; wait "${locker}"
check "a run that waits out the lock then builds normally" \
    'grep -q "rc=0" <<<"$out" && grep -qx "instructors up both" "${T}/calls"'

echo "== the one-shot crontab line is only removed on request, after a clean run =="
crontab_shim() { printf '#!/usr/bin/env bash\nif [[ "$*" == "-l" ]]; then cat "%s"; else cat > "%s"; fi\n' "${T}/crontab" "${T}/crontab.new" > "${SHIM}/crontab"; chmod +x "${SHIM}/crontab"; }
crontab_shim; printf '0 5 * * * something-else\n30 12 7 9 * wib-scheduled-up run\n' >"${T}/crontab"
rm -f "${T}/crontab.new"; out="$(run 2)"
check "without the flag the crontab is untouched" '[[ ! -f "${T}/crontab.new" ]]'
rm -f "${T}/crontab.new"; out="$(WIB_CRON_SELF_REMOVE=1 run 2)"
check "with the flag only the tagged line goes" \
    '[[ -f "${T}/crontab.new" ]] && ! grep -q "wib-scheduled-up" "${T}/crontab.new" && grep -q "something-else" "${T}/crontab.new"'
check "the previous crontab is backed up before the rewrite" 'ls "${T}/logs"/crontab.before-self-remove.* >/dev/null 2>&1'
rm -f "${T}/crontab.new"; out="$(WIB_CRON_SELF_REMOVE=1 FAIL_VERB=verify run 2)"
check "a failed run leaves the schedule in place" '[[ ! -f "${T}/crontab.new" ]]'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
