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
            if text and not input_allowed(text):
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
