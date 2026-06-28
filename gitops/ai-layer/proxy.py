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
import logging
import os
import threading
import time
import urllib.request
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# OTel instrumentation (PRD #22 M1 / issue #19). The stock python image carries no opentelemetry; the
# OTel Operator injects the SDK at pod startup (PYTHONPATH). The try/except guard keeps this file runnable
# with no OTel present (local dev, test clusters) as a no-op until the Operator's annotation is applied.
try:
    from opentelemetry import trace, metrics
    from opentelemetry.trace import SpanKind, Status, StatusCode
    from opentelemetry.metrics import Observation
    from opentelemetry.propagate import extract, inject
    _OTEL_AVAILABLE = True
    _tracer = trace.get_tracer(__name__)
    _meter = metrics.get_meter(__name__)
except ImportError:
    _OTEL_AVAILABLE = False
    _tracer = None
    _meter = None


# Structured JSON logging with trace correlation (PRD #27 M2). Every log line is one JSON object
# carrying the active span's trace_id/span_id, so Datadog ties guard-decision logs to the trace in
# the waterfall. Field names are the OTel-standard `trace_id`/`span_id` (lowercase hex) which Datadog
# auto-recognizes — NO dd.trace_id/dd.span_id 64-bit-decimal remapping (locked PRD #27 Decision Log,
# 2026-06-25). Stdlib logging only; no SDK dependency.
class _TraceJsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if event:
            payload["event"] = event
        if _OTEL_AVAILABLE:
            ctx = trace.get_current_span().get_span_context()
            if ctx.is_valid:
                payload["trace_id"] = format(ctx.trace_id, "032x")
                payload["span_id"] = format(ctx.span_id, "016x")
        return json.dumps(payload)


log = logging.getLogger("guard-proxy")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(_TraceJsonFormatter())
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False

# Content capture is gated on the OTel GenAI capture env var, read ONCE at module load. This env var is
# specific to opentelemetry-util-genai / contrib instrumentations; it does NOT govern hand-written SDK
# spans automatically (research/31 Q3), so this proxy reads it explicitly. Valid enum values:
# NO_CONTENT (default), SPAN_ONLY, EVENT_ONLY, SPAN_AND_EVENT. "true" is NOT valid and must NOT enable
# capture (it silently collects nothing on the ADK path too). Default OFF matches BUILD-SPEC s4.
_CAPTURE_MODE = os.environ.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "NO_CONTENT").upper()
_CAPTURE_CONTENT = _CAPTURE_MODE in ("SPAN_ONLY", "EVENT_ONLY", "SPAN_AND_EVENT")


def _genai_messages(text):
    """One OTel GenAI message envelope (user/text) as a JSON string, per the messages schema."""
    return json.dumps([{"role": "user", "parts": [{"type": "text", "content": text}]}])

AGENT_URL = os.environ.get("AGENT_URL", "http://workshop-agent.attendee-test:8080")
# peer.service for the outbound CLIENT span (PRD #27 M2): the downstream node the Datadog Service Map
# draws an edge to. Derived from AGENT_URL's host so the edge always names whatever this proxy really
# calls. Target topology: AGENT_URL fronts agentgateway (-> "agentgateway"); until agentgateway is
# deployed it points straight at the kagent agent. PEER_SERVICE overrides if the host label is wrong.
_PEER_SERVICE = os.environ.get("PEER_SERVICE") or (urlparse(AGENT_URL).hostname or "agentgateway").split(".")[0]
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
# The model attribute on gen_ai.client.cost is the gen_ai.request.model identifier (the standard semconv
# attribute, NOT a tier). proxy.py does not see the model in the A2A request (kagent's
# ModelConfig owns it), so it is supplied per cluster via MODEL_NAME to match that ModelConfig; falls back
# to the tier name if unset. verify-at-build: set MODEL_NAME to the cluster's Bedrock model id.
MODEL_NAME = os.environ.get("MODEL_NAME", MODEL_TIER)
_tier_price = TIER_PRICES_PER_1K.get(MODEL_TIER, TIER_PRICES_PER_1K["haiku"])
# Optional explicit per-1K overrides; if unset, the tier table above is authoritative.
COST_PER_1K_IN = float(os.environ.get("COST_PER_1K_IN", str(_tier_price["in"])))
COST_PER_1K_OUT = float(os.environ.get("COST_PER_1K_OUT", str(_tier_price["out"])))
_cost_lock = threading.Lock()
_cost = {"tier": MODEL_TIER, "requests": 0, "input_tokens": 0, "output_tokens": 0,
         "total_tokens": 0, "usd": 0.0}

# Export the running spend as `gen_ai.client.cost` via OTLP, the SAME pipeline as the spans and the
# standard token metric. Tokens are the standard `gen_ai.client.token.usage` (emitted by the kagent ADK
# agent, the actual LLM client). The OTel GenAI semconv defines NO monetary metric, so cost is a project
# suffix UNDER the standard gen_ai namespace (NOT a custom metric tree). Datadog derives cost from tokens
# in LLM Observability anyway; this metric is the pre-computed visual for the live counter. Attribute is
# the standard gen_ai.request.model.
if _meter is not None:
    def _observe_cost(_options):
        with _cost_lock:
            # gen_ai.provider.name MUST be aws.bedrock for a Bedrock model (OTel GenAI semconv); without
            # it Datadog tags the cost metric provider as "N/A". The Collector also stamps this as a safety
            # net, but set it at the source too.
            yield Observation(_cost["usd"], {"gen_ai.request.model": MODEL_NAME,
                                             "gen_ai.provider.name": "aws.bedrock"})
    _meter.create_observable_gauge(
        "gen_ai.client.cost", callbacks=[_observe_cost], unit="USD",
        description="Estimated Bedrock spend (USD) for this cluster, derived from token usage.")

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

    # Live kagent 0.9.9 emits the token usage at result.metadata.kagent_usage_metadata (confirmed on a
    # real A2A response on watch-it-burn-test, 2026-06-21). research/14 read the published docs as
    # `adk_usage_metadata`, but the running controller uses `kagent_usage_metadata`; the live cluster is
    # ground truth. Accept both keys (kagent first) so a future re-key does not silently zero the counter.
    def _usage(metadata):
        metadata = metadata or {}
        return metadata.get("kagent_usage_metadata") or metadata.get("adk_usage_metadata")

    meta = _usage(result.get("metadata"))
    if not meta:
        meta = _usage(result.get("status", {}).get("message", {}).get("metadata"))
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


# Monotonic id for /chat A2A messageIds (kagent requires a messageId; avoids a time-format dependency).
_chat_seq = 0


def chat_reply_text(resp):
    """The AGENT's reply text from an A2A response. kagent echoes the SAME text into artifacts AND the
    agent-role history, so take ONE source (artifacts first, then agent history, then status) rather than
    concatenating all three, or the storefront reply comes back doubled."""
    result = resp.get("result") if isinstance(resp, dict) else None
    if not isinstance(result, dict):
        return ""
    art = " ".join(extract_text(a.get("parts")) for a in (result.get("artifacts") or [])).strip()
    if art:
        return art
    hist = " ".join(extract_text(h.get("parts")) for h in (result.get("history") or [])
                    if h.get("role") == "agent").strip()
    if hist:
        return hist
    return extract_text(result.get("status", {}).get("message", {}).get("parts")).strip()


def chat_usage_tokens(resp):
    """(input_tokens, output_tokens) for one A2A response from kagent_usage_metadata (adk fallback)."""
    result = resp.get("result", {}) if isinstance(resp, dict) else {}

    def _u(m):
        m = m or {}
        return m.get("kagent_usage_metadata") or m.get("adk_usage_metadata")

    u = _u(result.get("metadata")) or _u(result.get("status", {}).get("message", {}).get("metadata")) or {}
    return int(u.get("promptTokenCount", 0) or 0), int(u.get("candidatesTokenCount", 0) or 0)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body_obj):
        # Record the response code on the in-flight HTTP SERVER span (set in do_POST), if any. _send is
        # the single response path for POST, so this captures the status at every exit (403/429/502/200).
        _sp = getattr(self, "_server_span", None)
        if _sp is not None:
            _sp.set_attribute("http.response.status_code", code)
        body = json.dumps(body_obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        # Allow the instructor index (start.agenticburn.com) to read /cost and /prompts cross-subdomain
        # for the one-place live room view. These are read-only, already-moderated surfaces.
        self.send_header("Access-Control-Allow-Origin", "*")
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
        # NOTE: the old custom Prometheus /metrics cost endpoint is REMOVED. Cost is now the
        # OTLP metric `gen_ai.client.cost` (registered above, under the standard gen_ai namespace), and
        # tokens are the standard `gen_ai.client.token.usage` from the kagent ADK agent. Both flow via the
        # OTel Collector, so there is nothing to scrape here.
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
        # HTTP SERVER span (PRD #22 M1): joins the upstream trace from agentgateway via extracted W3C
        # context, so the guard-proxy hop appears in the waterfall. http.response.status_code is set by
        # _send at every exit. No-op when the OTel SDK is absent (import guard).
        self._server_span = None
        server_cm = (
            _tracer.start_as_current_span(
                f"POST {self.path}", context=extract(dict(self.headers)), kind=SpanKind.SERVER)
            if _OTEL_AVAILABLE else nullcontext()
        )
        with server_cm as server_span:
            self._server_span = server_span
            if server_span is not None:
                server_span.set_attribute("http.request.method", "POST")
                server_span.set_attribute("url.path", self.path)
            # /chat is the BurritoBot storefront contract (B1); everything else is the A2A passthrough.
            if self.path.rstrip("/") == "/chat":
                self._handle_chat()
            else:
                self._handle_post()

    def _handle_post(self):
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

        # The `sanitize` INTERNAL child span wraps the guard decision + the forward (PRD #22 M1).
        # gen_ai.operation.name="chat" so Datadog classifies it as an llm-kind span and renders the
        # before/after message panel in LLM Observability. NOTE: this proxy forwards the prompt UNCHANGED
        # (it blocks-or-passes; it does not rewrite prompt content), so input.messages (original) and
        # output.messages (forwarded) are equal here; the re-leak redaction is the Collector OTTL Act-2
        # step (PRD #22 M2), not in-proxy. Content capture is gated (default OFF; "true" never enables it).
        san_cm = (
            _tracer.start_as_current_span("sanitize", kind=SpanKind.INTERNAL)
            if _OTEL_AVAILABLE else nullcontext()
        )
        with san_cm as san_span:
            if san_span is not None:
                san_span.set_attribute("gen_ai.operation.name", "chat")
                if _CAPTURE_CONTENT:
                    san_span.set_attribute("gen_ai.input.messages", _genai_messages(text))
                    san_span.set_attribute("gen_ai.output.messages", _genai_messages(text))

            # Stage 1: deterministic block-list (cheapest, pre-LLM, zero tokens). Toggled independently.
            if GUARDS["input_blocklist"] and text:
                hit = blocklisted(text)
                if hit:
                    log.info("input blocked by deterministic block-list (matched %r)", hit,
                             extra={"event": "input_blocklist_hit"})
                    self._send(403, {
                        "jsonrpc": "2.0", "id": payload.get("id"),
                        "error": {"code": -32600,
                                  "message": f"Request blocked by input block-list (matched '{hit}'). "
                                             "No model tokens were spent."},
                    })
                    return
            # Stage 2: model-based prompt-injection classifier (costlier gate; NOT deterministic).
            if GUARDS["input_classifier"] and text:
                if not input_allowed(text):
                    log.info("input blocked by prompt-injection classifier",
                             extra={"event": "input_classifier_block"})
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

            # Forward to the agent inside a CLIENT span (PRD #27 M2): this models the egress hop in the
            # Datadog Service Map. peer.service names the downstream node so the map draws
            # guard-proxy -> <next hop>; http.request.method / url.full / http.response.status_code give
            # it http.client semantics. inject() runs INSIDE the span so the forwarded W3C context is the
            # CLIENT span's, and kagent's ADK spans parent onto THIS hop (not the sanitize span).
            fwd_url = AGENT_URL + self.path
            client_cm = (
                _tracer.start_as_current_span("agent.forward", kind=SpanKind.CLIENT)
                if _OTEL_AVAILABLE else nullcontext()
            )
            with client_cm as client_span:
                fwd_headers = {"Content-Type": "application/json"}
                if client_span is not None:
                    client_span.set_attribute("peer.service", _PEER_SERVICE)
                    client_span.set_attribute("http.request.method", "POST")
                    client_span.set_attribute("url.full", fwd_url)
                    inject(fwd_headers)
                try:
                    req = urllib.request.Request(
                        fwd_url, data=raw, headers=fwd_headers, method="POST")
                    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                        if client_span is not None:
                            client_span.set_attribute("http.response.status_code", r.status)
                        resp = json.loads(r.read())
                except Exception as exc:
                    if client_span is not None:
                        # HTTPError carries .code; connection-level failures do not.
                        code = getattr(exc, "code", None)
                        if code is not None:
                            client_span.set_attribute("http.response.status_code", code)
                        client_span.set_attribute("error.type", type(exc).__name__)
                        client_span.set_status(Status(StatusCode.ERROR, str(exc)))
                    log.error("agent forward failed: %s", exc, extra={"event": "forward_error"})
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
                    if scrubbed != p["text"]:
                        log.info("output guardrail modified response content",
                                 extra={"event": "output_scrub"})
                    p["text"] = "[BLOCKED BY OUTPUT GUARDRAIL]" if scrubbed is None else scrubbed

        for artifact in result.get("artifacts", []) or []:
            scrub(artifact.get("parts", []))
        for entry in result.get("history", []) or []:
            if entry.get("role") == "agent":
                scrub(entry.get("parts", []))
        status_msg = result.get("status", {}).get("message", {})
        scrub(status_msg.get("parts", []))
        return resp

    def _handle_chat(self):
        """BurritoBot storefront contract (B1): POST {prompt} -> {reply, guarded, input_tokens,
        output_tokens}. Wraps the prompt as an A2A message/send and runs the SAME input/output guards,
        rate/cost cap, cost metering, and agent forward as the A2A root, then reshapes the response. The
        guard TOGGLES apply identically, so the round-2/round-3 guardrail demo affects BurritoBot too."""
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            body = json.loads(raw) or {}
            prompt = body.get("prompt", "")
            session = body.get("session", "")  # per-browser-session id -> A2A contextId for conversation memory
        except Exception:
            prompt = ""
            session = ""
        if not isinstance(prompt, str) or not prompt.strip():
            self._send(400, {"reply": "Tell BurritoBot what you'd like.", "guarded": False,
                             "input_tokens": 0, "output_tokens": 0})
            return
        if STREAM_ENABLED:
            with _stream_lock:
                _prompts.append(moderate(prompt))
        # Input guards (same toggles as the A2A path), then rate/cost cap. A blocked request spends 0 tokens.
        if GUARDS["input_blocklist"]:
            hit = blocklisted(prompt)
            if hit:
                log.info("chat input blocked by block-list (matched %r)", hit,
                         extra={"event": "input_blocklist_hit"})
                self._send(200, {"reply": f"BurritoBot can't help with that (blocked: '{hit}'). "
                                          "No model tokens were spent.",
                                 "guarded": True, "input_tokens": 0, "output_tokens": 0})
                return
        if GUARDS["input_classifier"] and not input_allowed(prompt):
            log.info("chat input blocked by classifier", extra={"event": "input_classifier_block"})
            self._send(200, {"reply": "BurritoBot can't help with that (blocked by the input guardrail).",
                             "guarded": True, "input_tokens": 0, "output_tokens": 0})
            return
        if rate_limited():
            self._send(200, {"reply": f"Slow down, hungry traveler. ({RATE_LIMIT_RPM}/min cap on this cluster.)",
                             "guarded": True, "input_tokens": 0, "output_tokens": 0})
            return
        if cost_capped():
            self._send(200, {"reply": f"The kitchen tab is frozen (cost cap ${COST_CAP_USD:.2f}).",
                             "guarded": True, "input_tokens": 0, "output_tokens": 0})
            return
        # Forward as A2A message/send to the agent root, inside a CLIENT span (the Service Map egress hop).
        global _chat_seq
        _chat_seq += 1
        msg = {"role": "user", "messageId": f"chat-{_chat_seq}",
               "parts": [{"kind": "text", "text": prompt}]}
        if session:
            # Carry the browser session as the A2A contextId so kagent threads the order across turns.
            msg["contextId"] = session
        a2a = {"jsonrpc": "2.0", "id": "chat", "method": "message/send", "params": {"message": msg}}
        fwd_headers = {"Content-Type": "application/json"}
        client_cm = (_tracer.start_as_current_span("agent.forward", kind=SpanKind.CLIENT)
                     if _OTEL_AVAILABLE else nullcontext())
        with client_cm as client_span:
            if client_span is not None:
                client_span.set_attribute("peer.service", _PEER_SERVICE)
                client_span.set_attribute("http.request.method", "POST")
                inject(fwd_headers)
            try:
                req = urllib.request.Request(AGENT_URL + "/", data=json.dumps(a2a).encode(),
                                             headers=fwd_headers, method="POST")
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    resp = json.loads(r.read())
            except Exception as exc:
                log.error("chat forward failed: %s", exc, extra={"event": "forward_error"})
                self._send(502, {"reply": "BurritoBot's kitchen isn't answering. Try again in a moment.",
                                 "guarded": False, "input_tokens": 0, "output_tokens": 0})
                return
        record_usage(resp)  # feed the live cost counter (same path as A2A)
        pin, pout = chat_usage_tokens(resp)
        reply = chat_reply_text(resp)
        guarded = False
        if GUARDS["output"] and reply:
            scrubbed = output_scrub(reply)
            if scrubbed is None:
                reply, guarded = "[blocked by the output guardrail]", True
            elif scrubbed != reply:
                reply, guarded = scrubbed, True
        # Per-call cost so the storefront can show a live dollar counter without hardcoding rates client-side.
        cost_usd = (pin / 1000.0) * COST_PER_1K_IN + (pout / 1000.0) * COST_PER_1K_OUT
        self._send(200, {"reply": reply or "...", "guarded": guarded,
                         "input_tokens": pin, "output_tokens": pout, "cost_usd": cost_usd})

    def log_message(self, fmt, *args):
        # Route BaseHTTPRequestHandler's default access logging through the structured JSON logger
        # (PRD #27 M2) instead of its plain-text stderr line. Debug level keeps it out of the INFO
        # stream that carries the guard-decision events.
        log.debug(fmt % args, extra={"event": "http_access"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
