#!/usr/bin/env bash
# ABOUTME: Phase-6 abstract-truth gate for Beat 3 (excessive agency via a bad MCP server) against one attendee spoke.
# ABOUTME: If the Phase-4b spike PASSED, asserts the live mcp-authz toggle; otherwise asserts the recorded fallback artifact exists.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly SCRIPT_DIR REPO_ROOT
readonly BEAT_DIR="${REPO_ROOT}/beats/03-bad-mcp-excessive-agency"
readonly SPIKE_FILE="${BEAT_DIR}/BUILD-SPIKE.md"
readonly FALLBACK="${BEAT_DIR}/fallback.curl.sh"
readonly TOGGLE_MCP_AUTHZ_ON="${BEAT_DIR}/toggle-mcp-authz-on.sh"
readonly RECORDINGS_DIR="${REPO_ROOT}/fallback/recordings"
readonly SENTINEL="FAKE-MCP-EXFIL-sentinel-4c1d"

usage() {
    cat >&2 <<'EOF'
Usage: beat-03.sh <kube-context> <attendee-namespace>

  <kube-context>         kubeconfig context for the attendee's cluster
  <attendee-namespace>   namespace holding the gateway, agent, and evil-mcp-shim

Asserts Beat 3's §2 outcome. The beat is SPIKE-GATED (§2, Phase 4b):

  IF beats/03-.../BUILD-SPIKE.md contains a PASS marker -> assert the LIVE path:
    mcp-authz OFF -> the rogue tool call leaks FAKE-MCP-EXFIL-sentinel-4c1d
    mcp-authz ON  -> the call is BLOCKED; the sentinel does not appear

  ELSE (spike not passed / no marker) -> assert the recorded fallback artifact
    exists under fallback/recordings/ (Beat 3's recording is mandatory until the
    spike passes, per §3 / Phase 9).

Exit: 0 = §2 outcome holds for whichever path applies; non-zero = mismatch (loud FAIL).
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; exit 2; fi
CONTEXT="${1:?$(usage)}"
NS="${2:?$(usage)}"

fail() { echo "FAIL [beat-03]: $*" >&2; exit 1; }
step() { echo "==> [beat-03] $*" >&2; }

# ---- Decide path from the spike marker -----------------------------------------------------
# Phase 4b records the result in BUILD-SPIKE.md. We treat the spike as PASSED only on an
# AFFIRMATIVE, recorded result - never on the template's prose ("PASS / FAIL decision box"),
# its empty checkbox ("[ ] PASS"), or its TODO/TBD placeholders. The file ships as TODO, so
# this returns false until a human records the result. The check is per-line: one line must
# both affirm PASS and be free of any placeholder token. Recognised PASS forms (one line):
#   "RESULT: PASS"   "**RESULT:** Passed"   "Status - PASS"   "RESULT: [x] PASS"
spike_passed() {
    [[ -f "${SPIKE_FILE}" ]] || return 1
    local line had_nocase=0
    shopt -q nocasematch && had_nocase=1
    shopt -s nocasematch
    local result=1
    while IFS= read -r line; do
        # A decisively CHECKED pass box wins outright, even if the same decision-box line
        # also carries an unchecked "[ ] FAIL" alternative: "RESULT: [x] PASS [ ] FAIL".
        if [[ "${line}" =~ \[[xX]\][[:space:]]*pass ]]; then
            result=0
            break
        fi
        # Otherwise require a recorded result/status/verdict line that affirms PASS...
        [[ "${line}" =~ ^[[:space:]\>\*#\|-]*(result|status|verdict|spike)[[:space:]:*\|-]+ ]] || continue
        [[ "${line}" =~ pass(ed)? ]] || continue
        # ...and is not itself a placeholder: TODO / TBD / PENDING / an UNCHECKED "[ ]" box.
        [[ "${line}" =~ todo|tbd|pending|\[[[:space:]]\] ]] && continue
        result=0
        break
    done < "${SPIKE_FILE}"
    [[ "${had_nocase}" -eq 0 ]] && shopt -u nocasematch
    return "${result}"
}

recorded_artifact_exists() {
    [[ -d "${RECORDINGS_DIR}" ]] || return 1
    # asciinema cast for beat 3 - match common naming (beat-03, beat3, bad-mcp, excessive-agency).
    find "${RECORDINGS_DIR}" -maxdepth 2 -type f \
        \( -iname '*beat*03*' -o -iname '*beat3*' -o -iname '*bad*mcp*' -o -iname '*excessive*agency*' \) \
        -size +0c 2>/dev/null | grep -q . && return 0
    return 1
}

step "Spoke context=${CONTEXT} namespace=${NS}"

if spike_passed; then
    step "Phase-4b spike PASSED -> asserting the LIVE mcp-authz path"
    command -v kubectl >/dev/null 2>&1 || fail "kubectl not found on PATH (required for live path)"
    [[ -x "${FALLBACK}" ]]            || fail "missing model-independent driver: ${FALLBACK}"
    [[ -x "${TOGGLE_MCP_AUTHZ_ON}" ]] || fail "missing toggle: ${TOGGLE_MCP_AUTHZ_ON}"

    # fallback.curl.sh contract (Beat 3): drives the rogue tool call through the gateway and
    # prints the response the caller would receive, independent of the model.
    #   fallback.curl.sh <context> <ns>
    run_call() { "${FALLBACK}" "${CONTEXT}" "${NS}" 2>/dev/null; }

    # mcp-authz off is the workshop-start default; the toggle accepts --off to restore it.
    # Reset to off at start and on EXIT so a repeated run sees the same before-state (idempotent).
    reset_authz_off() { "${TOGGLE_MCP_AUTHZ_ON}" --off >/dev/null 2>&1 || true; }
    trap reset_authz_off EXIT

    step "Resetting mcp-authz to OFF (workshop-start default)"
    reset_authz_off
    sleep 3

    step "mcp-authz OFF: driving the rogue tool call -- expect sentinel ${SENTINEL} to LEAK"
    OFF_OUT="$(run_call)" || fail "fallback.curl.sh errored with mcp-authz off"
    echo "${OFF_OUT}" | grep -qF "${SENTINEL}" \
        || fail "sentinel did NOT leak with mcp-authz off (§2 before-state broken)"
    echo "    PASS: rogue tool call leaks the sentinel while mcp-authz is off" >&2

    step "TOGGLE: applying the mcp-authz CEL deny rule"
    "${TOGGLE_MCP_AUTHZ_ON}" >/dev/null 2>&1 || fail "toggle-mcp-authz-on.sh failed"
    sleep 3

    step "mcp-authz ON: same call -- expect it BLOCKED; sentinel ABSENT"
    ON_OUT="$(run_call)" || ON_OUT="BLOCKED_NONZERO_EXIT"
    if echo "${ON_OUT}" | grep -qF "${SENTINEL}"; then
        fail "sentinel STILL leaks with mcp-authz on (§2 after-state broken; deny rule not enforcing)"
    fi
    echo "    PASS: rogue tool call blocked; sentinel does not appear" >&2

    echo "PASS [beat-03]: LIVE mcp-authz path behaves per §2 (spike passed)." >&2
    exit 0
fi

# ---- Spike not passed: recorded fallback must exist ----------------------------------------
step "Phase-4b spike NOT marked PASS -> asserting the recorded fallback artifact (mandatory per §3)"
if [[ ! -f "${SPIKE_FILE}" ]]; then
    step "note: ${SPIKE_FILE} absent; treating beat 3 as not-yet-live (recorded fallback required)"
fi
recorded_artifact_exists \
    || fail "no Beat 3 recording found under ${RECORDINGS_DIR} (mandatory until the spike passes)"

FOUND="$(find "${RECORDINGS_DIR}" -maxdepth 2 -type f \
    \( -iname '*beat*03*' -o -iname '*beat3*' -o -iname '*bad*mcp*' -o -iname '*excessive*agency*' \) \
    -size +0c 2>/dev/null | head -n1)"
echo "    PASS: recorded fallback artifact present: ${FOUND}" >&2
echo "PASS [beat-03]: recorded fallback asserted (live toggle gated off until spike passes)." >&2
exit 0
