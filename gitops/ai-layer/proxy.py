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
import collections
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

AGENT_URL = os.environ.get("AGENT_URL", "http://workshop-agent.attendee-test:8080")
LLM_GUARD_URL = os.environ.get("LLM_GUARD_URL", "http://llm-guard.attendee-test:8000")
LLM_GUARD_TOKEN = os.environ.get("LLM_GUARD_TOKEN", "")
# Guard state is RUNTIME-mutable (flipped via GET /toggle), seeded from env. This is deliberate:
# the platform is Argo CD-managed and self-heal would revert a `kubectl set env` change, and an env
# change also restarts the pod (resetting the cost counter). A runtime toggle changes no managed
# spec, so it sticks AND the counter survives. The live demo flips guards via /toggle, not kubectl.
_guard_lock = threading.Lock()
# Input guard is TWO progressively-enabled stages (ruling 2026-06-19): stage 1 is the deterministic
# block-list (cheapest, pre-LLM, zero tokens), stage 2 is the model-based classifier. They toggle
# INDEPENDENTLY so the demo shows "cheaper first" on the cost counter. Output is the exfil sidecar.
# Back-compat: INPUT_GUARD=on seeds both input stages on.
_input_legacy = os.environ.get("INPUT_GUARD", "").lower() == "on"
GUARDS = {
    "input_blocklist": _input_legacy or os.environ.get("INPUT_BLOCKLIST", "off").lower() == "on",
    "input_classifier": _input_legacy or os.environ.get("INPUT_CLASSIFIER", "off").lower() == "on",
    "output": os.environ.get("OUTPUT_GUARD", "off").lower() == "on",
}
# Fail closed: if LLM Guard is unreachable, block rather than silently leak (no-silent-fallback rule).
FAIL_CLOSED = os.environ.get("PROXY_FAIL_CLOSED", "true").lower() == "true"
TIMEOUT = float(os.environ.get("PROXY_TIMEOUT", "150"))

# Rate-limit + cost-cap the demo ITSELF: a room hammering the chaos agent must not run up the real
# Bedrock bill or DoS the demo (the cost demo cannot itself run away). Both are per-cluster (this
# proxy fronts one cluster) and env-tunable; 0 disables. verify-at-build: set caps to the room size.
COST_CAP_USD = float(os.environ.get("COST_CAP_USD", "0") or "0")     # reject once this cluster's tally hits it
RATE_LIMIT_RPM = int(os.environ.get("RATE_LIMIT_RPM", "0") or "0")   # max model-bound requests per 60s
_rate_lock = threading.Lock()
_req_times = collections.deque()  # timestamps of recent forwarded POSTs (sliding 60s window)


def rate_limited():
    """True if this cluster is over its requests-per-minute cap. Sliding 60s window."""
    if RATE_LIMIT_RPM <= 0:
        return False
    now = time.monotonic()
    with _rate_lock:
        while _req_times and now - _req_times[0] > 60.0:
            _req_times.popleft()
        if len(_req_times) >= RATE_LIMIT_RPM:
            return True
        _req_times.append(now)
        return False


def cost_capped():
    """True if this cluster's metered spend has reached the cap."""
    if COST_CAP_USD <= 0:
        return False
    with _cost_lock:
        return _cost["usd"] >= COST_CAP_USD

# Cost-saving input block-list: deterministic, runs BEFORE any LLM call. Destructive intent that
# matches here is rejected without spending a single Bedrock token — the workshop's cost lesson.
# Comma-separated terms; case-insensitive substring match. Cheap by design (no model).
BLOCK_LIST = [t.strip().lower() for t in os.environ.get(
    "BLOCK_LIST",
    "delete,destroy,rm -rf,drop database,kubectl delete,shutdown,terminate,wipe,nuke",
).split(",") if t.strip()]

# Live cost meter: tally Bedrock token usage from each agent response (kagent reports the real
# promptTokenCount / candidatesTokenCount) and convert to USD for the "wasted tokens are the new DoS"
# story. The COUNTER value is never hardcoded; only the per-tier PRICE table is config, and the
# authoritative post-hoc total is Cost Explorer (teardown/cost-report.sh).
#
# Per-1K-token list prices (USD), sourced 2026-06-19 from Anthropic + AWS Bedrock pricing pages:
#   Haiku 4.5 $1/$5, Sonnet 4.6 $3/$15, Opus 4.8 $5/$25 per 1M tokens.
# verify-at-build: confirm the Bedrock list price for the deployed region. Anthropic API list prices
#   (used here) historically match Bedrock for these models, but confirm before quoting a number.
TIER_PRICES_PER_1K = {
    "haiku":  {"in": 0.001, "out": 0.005},
    "sonnet": {"in": 0.003, "out": 0.015},
    "opus":   {"in": 0.005, "out": 0.025},
}
# Which tier this cluster runs (set per cluster to match the kagent ModelConfig). Defaults to haiku.
MODEL_TIER = os.environ.get("MODEL_TIER", "haiku").lower()
_tier_price = TIER_PRICES_PER_1K.get(MODEL_TIER, TIER_PRICES_PER_1K["haiku"])
# Optional explicit per-1K overrides; if unset, the tier table above is authoritative.
COST_PER_1K_IN = float(os.environ.get("COST_PER_1K_IN", str(_tier_price["in"])))
COST_PER_1K_OUT = float(os.environ.get("COST_PER_1K_OUT", str(_tier_price["out"])))
_cost_lock = threading.Lock()
_cost = {"tier": MODEL_TIER, "requests": 0, "input_tokens": 0, "output_tokens": 0,
         "total_tokens": 0, "usd": 0.0}

# Optional gamification: stream attendees' prompts to a side screen ("screen goes black, someone won").
# Projecting attendee input on a public screen needs moderation under the code of conduct, so capture
# is DEFAULT OFF and the /prompts feed only ever returns MODERATED text. verify-at-build: for a real
# public screen, back this with a content-moderation service (agentgateway external moderation / LLM
# Guard), not just this deterministic mask.
STREAM_ENABLED = os.environ.get("STREAM_PROMPTS", "off").lower() == "on"
PROFANITY = [t.strip().lower() for t in os.environ.get("PROFANITY_LIST", "").split(",") if t.strip()]
_stream_lock = threading.Lock()
_prompts = collections.deque(maxlen=50)  # recent MODERATED prompts for the display


def moderate(text):
    """Mask block-listed + profane terms so the side-screen stays within the code of conduct."""
    masked = text
    low = masked.lower()
    for term in set(BLOCK_LIST + PROFANITY):
        if term and term in low:
            masked = masked.replace(term, "[redacted]").replace(term.upper(), "[redacted]")
            low = masked.lower()
    return masked[:280]


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
        if self.path == "/prompts":
            # Side-screen feed: MODERATED prompts only, and only if capture is enabled.
            with _stream_lock:
                self._send(200, {"enabled": STREAM_ENABLED, "prompts": list(_prompts)})
            return
        if self.path == "/metrics":
            # Prometheus text format so kube-prometheus scrapes it and Grafana graphs the climbing
            # counter live. Block-listed requests never reach record_usage, so witb_requests_total /
            # witb_cost_usd flatline exactly when the input guard fires (the cost lesson, on a graph).
            with _cost_lock:
                c = dict(_cost)
            tier = c["tier"]
            lines = [
                "# HELP witb_cost_usd Estimated Bedrock spend (USD), metered from real token usage.",
                "# TYPE witb_cost_usd counter",
                f'witb_cost_usd{{tier="{tier}"}} {c["usd"]:.6f}',
                "# HELP witb_tokens_total Bedrock tokens metered at the guard-proxy.",
                "# TYPE witb_tokens_total counter",
                f'witb_tokens_total{{tier="{tier}",kind="input"}} {c["input_tokens"]}',
                f'witb_tokens_total{{tier="{tier}",kind="output"}} {c["output_tokens"]}',
                "# HELP witb_requests_total Agent requests that reached the model (block-listed excluded).",
                "# TYPE witb_requests_total counter",
                f'witb_requests_total{{tier="{tier}"}} {c["requests"]}',
                "",
            ]
            body = "\n".join(lines).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/guards"):
            with _guard_lock:
                self._send(200, dict(GUARDS))
            return
        if self.path.startswith("/toggle"):
            # Runtime flip, no restart, no spec change. Keys: input_blocklist, input_classifier, output.
            # Convenience: input=on flips BOTH input stages. e.g. /toggle?input_blocklist=on
            q = parse_qs(urlparse(self.path).query)
            with _guard_lock:
                if "input" in q:
                    on = q["input"][0].lower() == "on"
                    GUARDS["input_blocklist"] = on
                    GUARDS["input_classifier"] = on
                for k in ("input_blocklist", "input_classifier", "output"):
                    if k in q:
                        GUARDS[k] = q[k][0].lower() == "on"
                self._send(200, dict(GUARDS))
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

        text = ""
        if isinstance(payload, dict):
            text = extract_text(payload.get("params", {}).get("message", {}).get("parts", []))
        if STREAM_ENABLED and text:
            with _stream_lock:
                _prompts.append(moderate(text))  # moderated; side-screen feed only

        # Stage 1: deterministic block-list (cheapest, pre-LLM, zero tokens). Toggled independently.
        if GUARDS["input_blocklist"] and text:
            hit = blocklisted(text)
            if hit:
                self._send(403, {
                    "jsonrpc": "2.0", "id": payload.get("id"),
                    "error": {"code": -32600,
                              "message": f"Request blocked by input block-list (matched '{hit}'). "
                                         "No model tokens were spent."},
                })
                return
        # Stage 2: model-based prompt-injection classifier (costlier gate; NOT deterministic). Independent.
        if GUARDS["input_classifier"] and text:
            if not input_allowed(text):
                self._send(403, {
                    "jsonrpc": "2.0", "id": payload.get("id"),
                    "error": {"code": -32600,
                              "message": "Request blocked by input guardrail (prompt injection detected)."},
                })
                return

        # Protect the demo from itself: rate-limit + cost-cap BEFORE spending any Bedrock tokens.
        if rate_limited():
            self._send(429, {
                "jsonrpc": "2.0", "id": payload.get("id") if isinstance(payload, dict) else None,
                "error": {"code": -32000,
                          "message": f"Rate limit reached ({RATE_LIMIT_RPM}/min on this cluster). "
                                     "Slow down; the cost demo will not run away."},
            })
            return
        if cost_capped():
            self._send(429, {
                "jsonrpc": "2.0", "id": payload.get("id") if isinstance(payload, dict) else None,
                "error": {"code": -32000,
                          "message": f"Cost cap reached (${COST_CAP_USD:.2f} on this cluster). "
                                     "Spend is frozen for the rest of the segment."},
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
        if GUARDS["output"]:
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
