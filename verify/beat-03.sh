#!/usr/bin/env bash
# ABOUTME: Phase-6 abstract-truth gate for Beat 3 (excessive agency via a bad MCP server) against one attendee spoke.
# ABOUTME: If the Phase-4b spike PASSED, asserts the live mcp-authz toggle; otherwise asserts the recorded fallback artifact exists.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly SCRIPT_DIR REPO_ROOT
readonly BEAT_DIR="${REPO_ROOT}/challenges/03-bad-mcp-excessive-agency"
readonly SPIKE_FILE="${BEAT_DIR}/BUILD-SPIKE.md"
readonly FALLBACK="${BEAT_DIR}/fallback.curl.sh"
readonly RECORDINGS_DIR="${REPO_ROOT}/fallback/recordings"

usage() {
    cat >&2 <<'EOF'
Usage: beat-03.sh <kube-context> <attendee-namespace>

  <kube-context>         kubeconfig context for the attendee's cluster
  <attendee-namespace>   namespace holding the gateway, agent, and evil-mcp-shim

Asserts Beat 3's §2 outcome. The beat is SPIKE-GATED (§2, Phase 4b):

  IF challenges/03-.../BUILD-SPIKE.md contains a PASS marker -> assert the LIVE path with
    CONTEXT=<kube-context> fallback.curl.sh (admin clusters only; it refuses a workshop cluster):
    rule open (guard-mcp-off)    -> read_internal_config via :3003 leaks FAKE-MCP-EXFIL-sentinel-4c1d
    rule narrowed (guard-mcp-on) -> agentgateway refuses the call; the rule is put back after

  ELSE (spike not passed / no marker) -> assert the recorded fallback artifact
    exists under fallback/recordings/ (Beat 3's recording is mandatory until the
    spike passes, per §3 / Phase 9).

Exit: 0 = §2 outcome holds for whichever path applies; non-zero = mismatch (loud FAIL).
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; exit 2; fi
export CONTEXT="${1:?$(usage)}"
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
    step "Phase-4b spike PASSED -> asserting the LIVE gateway-rule path"
    command -v kubectl >/dev/null 2>&1 || fail "kubectl not found on PATH (required for live path)"
    [[ -x "${FALLBACK}" ]]            || fail "missing model-independent driver: ${FALLBACK}"

    # fallback.curl.sh contract (Beat 3, #517): CONTEXT is its only input. It flips the C7 rule with the web
    # terminal's guard-mcp-off and guard-mcp-on, calls read_internal_config through agentgateway :3003 each way,
    # puts the rule back as it found it, and ends with "C7 PROVEN" (exit 0) or "C7 NOT PROVEN" (exit 1). It
    # refuses (exit 2) a cluster without app-of-apps-admin, whose C7 is toggle-mcp-authz-on.sh's toolNames list.
    step "Running ${FALLBACK} on ${CONTEXT}"
    rc=0
    OUT="$(CONTEXT="${CONTEXT}" "${FALLBACK}" 2>&1)" || rc=$?
    echo "${OUT}" >&2
    [[ "${rc}" -ne 2 ]] || fail "fallback.curl.sh refused ${CONTEXT}: not an admin cluster, so no gateway rule to prove"
    if [[ "${rc}" -ne 0 ]] || ! grep -qF "C7 PROVEN" <<<"${OUT}"; then
        fail "fallback.curl.sh did not prove the gateway rule (exit ${rc}; see its FAIL lines)"
    fi

    echo "PASS [beat-03]: LIVE gateway-rule path behaves per §2 (spike passed)." >&2
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
