# ABOUTME: A2A-aware guard proxy that fronts the kagent agent and calls LLM Guard.
# ABOUTME: Input guard (prompt-injection on the request) + output guard (sentinel exfil on the
# ABOUTME: response), each toggled by env. Realizes the spec's output-sidecar as a standalone
# ABOUTME: inspection point because the kagent controller owns the agent pod (no in-pod sidecar).
#
# Stdlib only — runs in a stock python image via a mounted ConfigMap; no registry/build needed
# for the test cluster. For production, bake this into a pinned image (see GATEWAY-NOTES.md).
#
# Verdict envelope (confirmed live 2026-06-17): /analyze/prompt and /analyze/output return
# {"is_valid": bool, "scanners": {...}, "sanitized_prompt"|"sanitized_output": "..."}.
import json
import os
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AGENT_URL = os.environ.get("AGENT_URL", "http://workshop-agent.attendee-test:8080")
LLM_GUARD_URL = os.environ.get("LLM_GUARD_URL", "http://llm-guard.attendee-test:8000")
LLM_GUARD_TOKEN = os.environ.get("LLM_GUARD_TOKEN", "")
INPUT_GUARD = os.environ.get("INPUT_GUARD", "off").lower() == "on"
OUTPUT_GUARD = os.environ.get("OUTPUT_GUARD", "off").lower() == "on"
# Fail closed: if LLM Guard is unreachable, block rather than silently leak (no-silent-fallback rule).
FAIL_CLOSED = os.environ.get("PROXY_FAIL_CLOSED", "true").lower() == "true"
TIMEOUT = float(os.environ.get("PROXY_TIMEOUT", "150"))

# Cost-saving input block-list: deterministic, runs BEFORE any LLM call. Destructive intent that
# matches here is rejected without spending a single Bedrock token — the workshop's cost lesson.
# Comma-separated terms; case-insensitive substring match. Cheap by design (no model).
BLOCK_LIST = [t.strip().lower() for t in os.environ.get(
    "BLOCK_LIST",
    "delete,destroy,rm -rf,drop database,kubectl delete,shutdown,terminate,wipe,nuke",
).split(",") if t.strip()]

# Live cost meter: tally Bedrock token usage from each agent response (kagent reports it) and
# convert to $ for the "wasted tokens are the new DoS" story. Prices are env-driven and are an
# ESTIMATE for the live counter; the authoritative spend is Cost Explorer (teardown/cost-report.sh).
# verify-at-build: set the real per-1K Bedrock prices for the chosen Claude model.
COST_PER_1K_IN = float(os.environ.get("COST_PER_1K_IN", "0.001"))
COST_PER_1K_OUT = float(os.environ.get("COST_PER_1K_OUT", "0.005"))
_cost_lock = threading.Lock()
_cost = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "usd": 0.0}


def record_usage(resp):
    """Pull kagent token usage from an A2A response and add it to the running cost tally."""
    result = resp.get("result", {}) if isinstance(resp, dict) else {}
    meta = (result.get("metadata") or {}).get("kagent_usage_metadata")
    if not meta:
        meta = (result.get("status", {}).get("message", {}).get("metadata") or {}).get("kagent_usage_metadata")
    if not isinstance(meta, dict):
        return
    pin = int(meta.get("promptTokenCount", 0) or 0)
    pout = int(meta.get("candidatesTokenCount", 0) or 0)
    with _cost_lock:
        _cost["requests"] += 1
        _cost["input_tokens"] += pin
        _cost["output_tokens"] += pout
        _cost["total_tokens"] += int(meta.get("totalTokenCount", pin + pout) or 0)
        _cost["usd"] += (pin / 1000.0) * COST_PER_1K_IN + (pout / 1000.0) * COST_PER_1K_OUT


def _post_guard(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{LLM_GUARD_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LLM_GUARD_TOKEN}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def blocklisted(text):
    """Return the matched block-list term, or None. Deterministic, pre-LLM, zero token spend."""
    low = text.lower()
    return next((t for t in BLOCK_LIST if t in low), None)


def input_allowed(text):
    """True if the request prompt is allowed; False if the input scanner flags it."""
    try:
        verdict = _post_guard("/analyze/prompt", {"prompt": text})
        return bool(verdict.get("is_valid", True))
    except Exception:
        return not FAIL_CLOSED


def output_scrub(text):
    """Return redacted text, or None to signal a hard block."""
    try:
        verdict = _post_guard("/analyze/output", {"prompt": "", "output": text})
        if verdict.get("is_valid", True):
            return text
        return verdict.get("sanitized_output") or "[REDACTED]"
    except Exception:
        return None if FAIL_CLOSED else text


def extract_text(parts):
    return " ".join(
        p.get("text", "") for p in (parts or []) if isinstance(p, dict) and p.get("kind") == "text"
    )


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body_obj):
        body = json.dumps(body_obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/cost":
            with _cost_lock:
                self._send(200, dict(_cost))
            return
        # Pass through agent-card / .well-known discovery unchanged.
        try:
            req = urllib.request.Request(AGENT_URL + self.path, method="GET")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                body = r.read()
                self.send_response(r.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except Exception as exc:
            self._send(502, {"error": f"agent GET failed: {exc}"})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            payload = json.loads(raw)
        except Exception:
            payload = None

        if INPUT_GUARD and isinstance(payload, dict):
            text = extract_text(payload.get("params", {}).get("message", {}).get("parts", []))
            if text:
                # 1) Cheap deterministic block-list FIRST — rejects destructive intent with zero LLM spend.
                hit = blocklisted(text)
                if hit:
                    self._send(403, {
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "error": {"code": -32600,
                                  "message": f"Request blocked by input block-list (matched '{hit}'). "
                                             "No model tokens were spent."},
                    })
                    return
                # 2) Model-based scanner (prompt injection) as the second, costlier gate.
                if not input_allowed(text):
                    self._send(403, {
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "error": {"code": -32600,
                                  "message": "Request blocked by input guardrail (prompt injection detected)."},
                    })
                    return

        try:
            req = urllib.request.Request(
                AGENT_URL + self.path, data=raw,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                resp = json.loads(r.read())
        except Exception as exc:
            self._send(502, {"error": f"agent forward failed: {exc}"})
            return

        record_usage(resp)  # tally Bedrock token spend for the live cost counter
        if OUTPUT_GUARD:
            resp = self._scrub_response(resp)
        self._send(200, resp)

    def _scrub_response(self, resp):
        result = resp.get("result")
        if not isinstance(result, dict):
            return resp

        def scrub(parts):
            for p in parts or []:
                if isinstance(p, dict) and p.get("kind") == "text" and p.get("text"):
                    scrubbed = output_scrub(p["text"])
                    p["text"] = "[BLOCKED BY OUTPUT GUARDRAIL]" if scrubbed is None else scrubbed

        for artifact in result.get("artifacts", []) or []:
            scrub(artifact.get("parts", []))
        for entry in result.get("history", []) or []:
            if entry.get("role") == "agent":
                scrub(entry.get("parts", []))
        status_msg = result.get("status", {}).get("message", {})
        scrub(status_msg.get("parts", []))
        return resp

    def log_message(self, *args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
