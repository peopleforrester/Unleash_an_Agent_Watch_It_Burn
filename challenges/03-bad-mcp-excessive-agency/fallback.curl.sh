#!/usr/bin/env bash
# ABOUTME: C7 fallback: from the web terminal, calls evil-mcp's read_internal_config through agentgateway :3003 with
# ABOUTME: the rule open (the sentinel leaks), then narrowed (the gateway refuses), using guard-mcp-off/on. No model.
#
# Usage: CONTEXT=<admin-cluster kube-context> challenges/03-bad-mcp-excessive-agency/fallback.curl.sh
#
# On an admin cluster C7's control is agentgateway's mcpAuthorization rule for evil-mcp, the `# c7-rule` line of
# agentgateway-c7-config, served on its own bind, :3003 (#496, #514). The terminal's guard-mcp-on narrows it to
# get_weather and guard-mcp-off puts back 'true'. The web-terminal pod is the one principal block-argocd-drift
# lets edit that ConfigMap (#515), so both run there, through kubectl exec, exactly as a presenter would type
# them. The MCP exchange runs there too: the pod is in agent, next to the gateway, and has python3.
#
#   1. guard-mcp-off, then read_internal_config through :3003 until FAKE-MCP-EXFIL-sentinel-4c1d comes back.
#   2. guard-mcp-on, then the same call until the gateway refuses it. The seconds that took are the reload
#      delay the Night Before step reads at bring-up. get_weather must still answer, so the refusal is the
#      rule's and not an outage.
#   3. The rule is put back the way it was found, with the toggle that writes that rule.
#
# The old version posted to a pre-gitops localhost:8080 endpoint with --expect-allow/--expect-deny flags and kept
# the response in a scratch file (#517). This one takes no arguments and holds everything in shell variables.
# A workshop cluster is refused: its :3003 rule stays 'true' and its C7 control is the toolNames list that
# toggle-mcp-authz-on.sh patches, so no gateway deny can be asserted there.
set -euo pipefail

# Kube-context safety (see CLAUDE.md): target an explicit context; never the global current-context.
CONTEXT="${CONTEXT:?set CONTEXT to the admin cluster kube-context}"
command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found on PATH" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not found on PATH" >&2; exit 1; }
[[ $# -eq 0 ]] || { echo "usage: CONTEXT=<kube-context> fallback.curl.sh   (no arguments)" >&2; exit 2; }

readonly NS="agent"
readonly POD="deploy/web-terminal"
readonly CONTAINER="ttyd"
readonly TERMINAL_HOME="/home/student"
# The evil-mcp RemoteMCPServer's url (gitops/ai-layer/resources.yaml): the address the agent dials.
readonly GATEWAY="http://agentgateway.agent:3003/mcp"
readonly TOOL="read_internal_config"
readonly SENTINEL="FAKE-MCP-EXFIL-sentinel-4c1d"
readonly C7_CONFIGMAP="agentgateway-c7-config"
readonly RULE_OPEN="true"
readonly RULE_NARROWED='mcp.tool.name == "get_weather"'
# How long a rule change may take to reach the gateway: the kubelet refreshes the mount, then agentgateway
# reloads the file. Measured by step 2, never assumed.
readonly WAIT_SECONDS=120
readonly POLL_SECONDS=3

kc() { kubectl --context "${CONTEXT}" "$@"; }
terminal() { kc -n "${NS}" exec "${POD}" -c "${CONTAINER}" -- env HOME="${TERMINAL_HOME}" "$@"; }

# One MCP exchange, run in the terminal pod: initialize, notifications/initialized, tools/call <tool>. argv:
# <url> <tool> <sentinel>. Prints one JSON line whose verdict is leaked (the sentinel came back), refused (the
# gateway opened a session and then answered the call with an error), answered (a result without the sentinel)
# or none (no session: the gateway did not answer). The reply may be JSON or an event stream; the stream is
# read only up to the answer, so a stream left open cannot hang the check.
read -r -d '' CALL_PY <<'PY' || true
import json, sys, urllib.error, urllib.request
URL, TOOL, SENTINEL = sys.argv[1:4]

def post(msg, sid=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        headers["Mcp-Session-Id"] = sid
    req = urllib.request.Request(URL, data=json.dumps(msg).encode(), headers=headers, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        try:
            m = json.loads(text)
        except ValueError:
            m = None
        return e.code, sid, m if isinstance(m, dict) else None, text
    with r:
        sid = r.headers.get("Mcp-Session-Id") or sid
        if "id" not in msg:
            return r.status, sid, None, ""
        if "text/event-stream" in (r.headers.get("Content-Type") or ""):
            seen = []
            for raw in r:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                seen.append(line)
                if line.startswith("data:"):
                    try:
                        m = json.loads(line[5:])
                    except ValueError:
                        continue
                    if isinstance(m, dict) and m.get("id") == msg["id"]:
                        return r.status, sid, m, "\n".join(seen)
            return r.status, sid, None, "\n".join(seen)
        text = r.read().decode("utf-8", "replace")
        try:
            m = json.loads(text)
        except ValueError:
            m = None
        return r.status, sid, m if isinstance(m, dict) else None, text

out = {"tool": TOOL, "verdict": "none"}
try:
    st, sid, m, _ = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "wib-c7-fallback", "version": "1"}}})
    out["init"] = st
    if st == 200 and m and "result" in m:
        post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
        st, _, m, body = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                               "params": {"name": TOOL, "arguments": {}}}, sid)
        m = m or {}
        res = m.get("result") if isinstance(m.get("result"), dict) else {}
        err = m.get("error") if isinstance(m.get("error"), dict) else None
        text = " ".join(c.get("text", "") for c in res.get("content") or [] if isinstance(c, dict))
        out.update(status=st, error=(err or {}).get("message") if err else None, text=text[:300] or body[:300])
        if SENTINEL in body:
            out["verdict"] = "leaked"
        elif st >= 400 or err or res.get("isError"):
            out["verdict"] = "refused"
        elif "result" in m:
            out["verdict"] = "answered"
except Exception as e:  # the gateway did not answer at all
    out["unreachable"] = repr(e)[:200]
print(json.dumps(out))
PY

# The rule on the C7 bind, read from the ConfigMap: the CEL text between the quotes, or nothing when unreadable.
read -r -d '' RULE_PY <<'PY' || true
import json, re, sys
lines = json.load(sys.stdin)["data"]["config.yaml"].split("\n")
marked = [line.strip() for line in lines if line.rstrip().endswith("# c7-rule")]
m = re.fullmatch(r"-\s+'(.*)'\s+# c7-rule", marked[0]) if len(marked) == 1 else None
print(m.group(1) if m else "")
PY
rule_now() { kc -n "${NS}" get configmap "${C7_CONFIGMAP}" -o json 2>/dev/null | python3 -c "${RULE_PY}" 2>/dev/null || true; }

# json_get <json> <key>: prints the value, true/false/null as the JSON words, and nothing for non-JSON.
json_get() {
    python3 -c '
import json, sys
try:
    v = json.loads(sys.argv[1]).get(sys.argv[2])
except Exception:
    sys.exit(0)
print(v if isinstance(v, str) else json.dumps(v))' "$1" "$2"
}

# call <tool>: one exchange through :3003. Prints the pod's JSON line, or nothing when the exec failed.
call() { terminal python3 -c "${CALL_PY}" "${GATEWAY}" "$1" "${SENTINEL}" 2>/dev/null || true; }
# wait_for <verdict>: repeats the read_internal_config call until it reads <verdict> or WAIT_SECONDS pass.
# Leaves the last answer in LAST and the seconds since the call started in WAITED.
wait_for() {
    local start
    start="$(date +%s)"
    while :; do
        LAST="$(call "${TOOL}")"
        WAITED=$(( $(date +%s) - start ))
        [[ "$(json_get "${LAST}" verdict)" == "$1" ]] && return 0
        (( WAITED >= WAIT_SECONDS )) && return 1
        sleep "${POLL_SECONDS}"
    done
}
# What a non-matching answer was, for the FAIL line.
answer() {
    case "$(json_get "${LAST}" verdict)" in
        leaked)   echo "the sentinel came back" ;;
        refused)  echo "the gateway refused it ($(json_get "${LAST}" error))" ;;
        answered) echo "it answered without the sentinel: $(json_get "${LAST}" text)" ;;
        *)        echo "the gateway did not answer (${LAST:-the exec failed})" ;;
    esac
}

failed=0
check() {
    if [[ "$2" == "ok" ]]; then
        echo "  PASS  $1"
    else
        echo "  FAIL  $1${3:+: $3}"
        failed=1
    fi
}

# toggle <guard-mcp-on|guard-mcp-off> <what the rule must read after>: runs the terminal's own command in the
# terminal pod, then reads the rule back. Returns non-zero when either did not hold.
toggle() {
    local out rc=0 now
    out="$(terminal bash "${TERMINAL_HOME}/$1" 2>&1)" || rc=$?
    if [[ "${rc}" -ne 0 || "${out}" != *"at the gateway"* ]]; then
        check "$1 switches C7 at the gateway" fail "exit ${rc}: ${out:0:200}"
        return 1
    fi
    now="$(rule_now)"
    if [[ "${now}" != "$2" ]]; then
        check "$1 switches C7 at the gateway" fail "the rule reads '${now}', not '$2'"
        return 1
    fi
    check "$1 switches C7 at the gateway: the rule reads '$2'" ok
}

# The rule goes back the way it was found, with the toggle that writes it. RESTORE is set once the rule may have
# moved; finish (or the EXIT trap, when the script dies on the way) clears it after one try.
RESTORE=""
restore_quietly() { [[ -z "${RESTORE}" ]] || { local t="${RESTORE}"; RESTORE=""; terminal bash "${TERMINAL_HOME}/${t}" >/dev/null 2>&1 || true; }; }
trap restore_quietly EXIT

finish() {
    local t now
    if [[ -n "${RESTORE}" ]]; then
        t="${RESTORE}"
        RESTORE=""
        terminal bash "${TERMINAL_HOME}/${t}" >/dev/null 2>&1 || true
        now="$(rule_now)"
        if [[ "${now}" == "${FOUND}" ]]; then
            check "the rule is left as it was found ('${FOUND}', by ${t})" ok
        else
            check "the rule is left as it was found ('${FOUND}')" fail "it reads '${now}' after ${t}"
        fi
    fi
    if [[ "${failed}" -eq 0 ]]; then
        echo "==> C7 PROVEN: agentgateway let read_internal_config through with the rule open and refused it once guard-mcp-on narrowed the rule."
        exit 0
    fi
    echo "==> C7 NOT PROVEN: see the FAIL lines above." >&2
    exit 1
}

echo "==> C7 gateway rule: read_internal_config through ${GATEWAY}, from ${POD} (container ${CONTAINER}) in ${NS} on ${CONTEXT}"

# Only an admin cluster's terminal flips the gateway rule (gitops/bootstrap/admin). Asked the way the terminal asks.
admin="" rc=0
admin="$(kc -n argocd get application app-of-apps-admin --ignore-not-found -o name 2>/dev/null)" || rc=$?
if [[ "${rc}" -ne 0 ]]; then
    check "Argo CD answers whether this is an admin cluster" fail "kubectl exit ${rc}; nothing was touched"
    finish
fi
if [[ -z "${admin}" ]]; then
    echo "==> Refused: ${CONTEXT} has no Argo CD Application app-of-apps-admin, so it is not an admin cluster." >&2
    echo "    Its :3003 rule stays 'true' and its C7 control is evil-mcp's toolNames list, so no gateway deny can" >&2
    echo "    be asserted. Use challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh there." >&2
    exit 2
fi

if ! terminal true >/dev/null 2>&1; then
    check "can exec into ${POD} -c ${CONTAINER}" fail "nothing below can be proven; is the ai-layer synced?"
    finish
fi

FOUND="$(rule_now)"
case "${FOUND}" in
    "${RULE_OPEN}")     back="guard-mcp-off" ;;
    "${RULE_NARROWED}") back="guard-mcp-on" ;;
    *)
        check "the C7 rule in ${C7_CONFIGMAP} reads '${RULE_OPEN}' or '${RULE_NARROWED}'" fail \
            "it reads '${FOUND}', which neither toggle would put back, so it is left alone"
        finish ;;
esac
echo "    rule found: '${FOUND}'"
RESTORE="${back}"

# 1. Open: the rogue tool answers through the gateway.
toggle guard-mcp-off "${RULE_OPEN}" || finish
if wait_for leaked; then
    check "with the rule open, ${TOOL} through :3003 returns ${SENTINEL}" ok
    echo "    the gateway answered: $(json_get "${LAST}" text | tr '\n' ' ')"
else
    check "with the rule open, ${TOOL} through :3003 returns ${SENTINEL}" fail "after ${WAITED} s, $(answer)"
    # A refusal now could not be told from a gateway that refuses everything.
    finish
fi

# 2. Narrowed: the gateway refuses the same call before evil-mcp runs it.
toggle guard-mcp-on "${RULE_NARROWED}" || finish
if wait_for refused; then
    check "with the rule narrowed, the gateway refuses ${TOOL}, and ${SENTINEL} does not come back" ok
    echo "    the gateway answered: $(json_get "${LAST}" error)"
    echo "    the narrowed rule took effect after ${WAITED} s (guard-mcp-on to the first refused call)"
    weather="$(call get_weather)"
    if [[ "$(json_get "${weather}" verdict)" == "answered" ]]; then
        check "get_weather still answers through :3003, so the refusal is the rule's" ok
    else
        LAST="${weather}"
        check "get_weather still answers through :3003, so the refusal is the rule's" fail "$(answer)"
    fi
else
    check "with the rule narrowed, the gateway refuses ${TOOL}" fail "after ${WAITED} s, $(answer)"
fi

finish
