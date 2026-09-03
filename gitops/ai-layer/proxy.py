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
import re
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
# spans automatically (the research spikes (removed 2026-08-30; see `git log --diff-filter=D -- research/`) Q3), so this proxy reads it explicitly. Valid enum values:
# NO_CONTENT (default), SPAN_ONLY, EVENT_ONLY, SPAN_AND_EVENT. "true" is NOT valid and must NOT enable
# capture (it silently collects nothing on the ADK path too). Default OFF matches BUILD-SPEC s4.
_CAPTURE_MODE = os.environ.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "NO_CONTENT").upper()
_CAPTURE_CONTENT = _CAPTURE_MODE in ("SPAN_ONLY", "EVENT_ONLY", "SPAN_AND_EVENT")


def _genai_messages(text):
    """One OTel GenAI message envelope (user/text) as a JSON string, per the messages schema."""
    return json.dumps([{"role": "user", "parts": [{"type": "text", "content": text}]}])


def _genai_output(text):
    """One OTel GenAI message envelope (assistant/text) as a JSON string, per the messages schema."""
    return json.dumps([{"role": "assistant", "parts": [{"type": "text", "content": text}], "finish_reason": "stop"}])

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
    # The denial-of-wallet control (C4). Off = Round 1, the bill runs away. On = the per-agent budget
    # cap enforces at the gateway. Toggled live like the others.
    "budget": os.environ.get("BUDGET_GUARD", "off").lower() == "on",
}
# Fail closed: if LLM Guard is unreachable, block rather than silently leak (no-silent-fallback rule).
FAIL_CLOSED = os.environ.get("PROXY_FAIL_CLOSED", "true").lower() == "true"
TIMEOUT = float(os.environ.get("PROXY_TIMEOUT", "150"))

# Rate-limit + cost-cap the demo ITSELF: a room hammering the chaos agent must not run up the real
# Bedrock bill or DoS the demo (the cost demo cannot itself run away). Both are per-cluster (this
# proxy fronts one cluster) and env-tunable; 0 disables. verify-at-build: set caps to the room size.
COST_CAP_USD = float(os.environ.get("COST_CAP_USD", "0") or "0")     # reject once this cluster's tally hits it
RATE_LIMIT_RPM = int(os.environ.get("RATE_LIMIT_RPM", "0") or "0")   # max model-bound requests per 60s

# Denial-of-wallet control (Challenge 4, replacing the fork bomb). Token spend is its own DoS vector:
# a room, or an agent talked into a loop, runs the Bedrock bill up while nothing crashes. The counter on
# BurritoBot climbs and nothing stops it. The gateway budget cap IS the control: once a cluster's metered
# spend crosses BUDGET_CAP_USD, further requests are refused BEFORE the model is called, so a blocked
# request costs zero. It is a RUNTIME toggle (like the input/output guards) so the demo flips it live on
# Round 2 rather than through a pod-restarting env change; DEFAULT OFF so Round 1 burns freely.
BUDGET_CAP_USD = float(os.environ.get("BUDGET_CAP_USD", "0.10") or "0.10")
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
    """True if this cluster's metered spend has reached the cap. The infra safety cap (COST_CAP_USD,
    env, always on when set) protects the real Bedrock bill from a runaway room. Separately, the C4
    denial-of-wallet CONTROL is the runtime-toggled budget guard: when GUARDS['budget'] is on, the
    same tally is enforced against BUDGET_CAP_USD, which the demo flips live on Round 2."""
    with _cost_lock:
        spend = _cost["usd"]
    if COST_CAP_USD > 0 and spend >= COST_CAP_USD:
        return True
    if GUARDS.get("budget") and BUDGET_CAP_USD > 0 and spend >= BUDGET_CAP_USD:
        return True
    return False

# Input block-list (Challenge 6, the "block-list" stage): deterministic, runs BEFORE any LLM call.
# A match is rejected without spending a single Bedrock token — the workshop's cost lesson. Two kinds
# of term live here:
#   1. Destructive intent (delete/wipe/nuke/...): the cost-saving lesson.
#   2. Secret-recipe phrases: block attempts to extract Bat Spit Amazing Awesome Sauce. By design these
#      are the DISTINCTIVE made-up names (ogre toenails, snail blood) and the AMOUNT-bearing phrases
#      (the proportions are the secret), plus the signature — NOT bare common words like "bat saliva",
#      "moonlight", "ghost pepper", or "smoked paprika", which would over-block normal chat everywhere
#      they appear, and NOT the product name itself (it appears in the Challenge-5 prompt). This mirrors
#      the output guard's redaction policy (see the llm-guard-scanners Regex scanner).
# Comma-separated terms; case-insensitive substring match. Cheap by design (no model). Terms must not
# contain a comma (the list is comma-split).
BLOCK_LIST = [t.strip().lower() for t in os.environ.get(
    "BLOCK_LIST",
    "delete,destroy,rm -rf,drop database,kubectl delete,shutdown,terminate,wipe,nuke,"
    "ogre toenails,snail blood,generous splash of bat saliva,pinch of moonlight,"
    "WITCH-HAZEL-GHOST-PEPPER-BAT-SPIT-No7",
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
#
# `nova` added 2026-08-30: the workshop agent is bound to the bedrock-nova ModelConfig
# (us.amazon.nova-pro-v1:0), but MODEL_TIER was still "sonnet", so the on-screen counter was pricing Nova
# tokens at Sonnet rates (roughly 4x over). The counter is a headline visual for C4, so a wrong multiplier
# is a wrong lesson. Nova Pro list price $0.0008/1K in, $0.0032/1K out ($0.80/$3.20 per 1M), per the AWS
# pricing pages as of 2026-08-30. verify-at-build: the Bedrock pricing table is JS-rendered and could not
# be scraped, so re-confirm this pair against aws.amazon.com/bedrock/pricing before quoting it on a slide.
TIER_PRICES_PER_1K = {
    "nova":   {"in": 0.0008, "out": 0.0032},
    "haiku":  {"in": 0.001, "out": 0.005},
    "sonnet": {"in": 0.003, "out": 0.015},
    "opus":   {"in": 0.005, "out": 0.025},
}
# Which tier this cluster runs (set per cluster to match the kagent ModelConfig). Defaults to haiku.
MODEL_TIER = os.environ.get("MODEL_TIER", "haiku").lower()
# Full Bedrock model ID per tier — used as gen_ai.request.model when MODEL_NAME is not explicitly set.
# IDs verified ACTIVE 2026-06-26; update when kagent ModelConfigs are bumped.
_TIER_TO_MODEL_ID = {
    "nova":   "us.amazon.nova-pro-v1:0",
    "haiku":  "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet": "us.anthropic.claude-sonnet-4-6",
    "opus":   "us.anthropic.claude-opus-4-8",
}
# MODEL_NAME: explicit override via env var, then tier→model-ID mapping, then tier name as fallback.
MODEL_NAME = os.environ.get("MODEL_NAME") or _TIER_TO_MODEL_ID.get(MODEL_TIER, MODEL_TIER)
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

# Cross-origin policy for the browser-facing surface (#151).
#
# THE CONTROL IS THE ORIGIN HEADER, NOT CORS. Tightening Access-Control-Allow-Origin does not stop a
# hostile page driving this agent, because CORS governs whether the caller may READ the response and
# never whether the request ARRIVES. A POST with Content-Type: text/plain is a CORS-simple request, so
# it skips the preflight entirely, and this proxy ignored Content-Type and json.loads the body anyway.
# Measured 2026-09-03 against a live cluster from outside:
#
#   POST /chat   -H 'Content-Type: text/plain' -d '{}'  ->  200, the handler ran
#   POST /a2a/   -H 'Content-Type: text/plain' -d '{}'  ->  200, the handler ran
#   OPTIONS /chat (preflight)                           ->  501, there is no do_OPTIONS
#
# So the recommendation in #151 to narrow CORS would have closed nothing. What does close it is
# rejecting a POST whose Origin is a site we do not serve. Browsers always send Origin on a
# cross-origin request, so this stops the drive-by; non-browser callers (the in-cluster A2A hop, the
# verify probes, curl) send no Origin at all and are deliberately unaffected.
#
# WHAT THIS DOES NOT DO: it does not authenticate anyone. A direct request from outside a browser has
# no Origin to check and still reaches the agent, bounded by RATE_LIMIT_RPM and COST_CAP_USD. Closing
# that needs a shared credential handed out with the cluster URL, which changes the attendee sign-in
# flow and is a workshop decision rather than a code one. See #151 option 2.
CONSOLE_ORIGIN = os.environ.get("CONSOLE_ORIGIN", "https://start.agenticburn.com")


def _origin_allowed(handler):
    """True when the request carries no Origin, its own Host, or the instructor console."""
    origin = handler.headers.get("Origin")
    if not origin:
        return True   # not a browser cross-origin request; the A2A hop and every probe land here
    host = (handler.headers.get("Host") or "").split(":")[0].lower()
    try:
        o = urlparse(origin)
    except Exception:
        return False
    if o.hostname and host and o.hostname.lower() == host:
        return True   # the attendee's own console page, served from this same hostname
    return origin == CONSOLE_ORIGIN
# PROFANITY_LIST defaulted to EMPTY, which meant "moderated" masked only the BLOCK_LIST above (attack
# keywords and the C5 sentinel) and passed every slur and obscenity through untouched. That was harmless
# while capture was off; it is not once the feed is projected in a room, which is exactly the state this
# default now has to survive. A wordlist is not a moderation service and does not pretend to be: it is a
# floor, it catches the common cases, and the 280-character truncation below bounds the rest. The real
# control is that attendees are TOLD their prompts may appear on the instructor screen (run-of-show and
# lab step 0), which is what makes projecting them defensible at all.
_DEFAULT_PROFANITY = (
    "fuck,shit,cunt,bitch,bastard,dick,cock,pussy,asshole,motherfucker,wanker,twat,"
    "nigger,faggot,retard,tranny,slut,whore,rape,kike,spic,chink"
)
PROFANITY = [t.strip().lower() for t in os.environ.get("PROFANITY_LIST", _DEFAULT_PROFANITY).split(",") if t.strip()]
_stream_lock = threading.Lock()
_prompts = collections.deque(maxlen=50)  # recent MODERATED prompts for the display

# Automated probes must not land in the side-screen feed. verify/browser-smoke.py sends a prompt to every
# cluster on every run, and with capture on those accumulate in the deque above and merge across 13
# clusters in the instructor console, which reads as a wall of duplicate prompts nobody typed. Observed
# 2026-09-03: the ONLY text on the whole fleet was the smoke test's own prompt, repeated per run.
#
# The marker is checked before moderation and before the append, so a probe is answered normally and
# simply never recorded. It is deliberately an ugly literal: it must never collide with something an
# attendee would plausibly type, and it should be obvious in a log that a probe was responsible.
PROBE_MARKER = "[[wib-probe]]"


def _is_probe(text):
    return PROBE_MARKER in (text or "")


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
    # real A2A response on watch-it-burn-test, 2026-06-21). the research spikes (removed 2026-08-30; see `git log --diff-filter=D -- research/`) read the published docs as
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

# Per-session contextId generation. kagent threads the conversation by A2A contextId; if a turn leaves a
# tool_use without its tool_result (a kagent/ADK multi-turn-with-tools quirk seen live), Bedrock then
# rejects EVERY later message in that contextId with a ValidationException. We self-heal by bumping the
# session's generation (a fresh contextId) on that error, abandoning the poisoned history and retrying.
_ctx_gen = {}


def _effective_ctx(session):
    """The A2A contextId to use for a browser session, including its self-heal generation suffix."""
    g = _ctx_gen.get(session, 0)
    return session if g == 0 else f"{session}-g{g}"


def _is_dangling_tooluse(reply):
    """True when a reply is the Bedrock 'tool_use without tool_result' error (poisoned session history)."""
    return bool(reply) and "tool_use" in reply and "tool_result" in reply and "ValidationException" in reply


# Nova sometimes emits ONLY its <thinking> block and no answer. Measured on a live cluster 2026-09-03:
# 1 of 6 identical requests came back reasoning-only, so roughly one student prompt in six would render
# as an empty bubble. It is not a token ceiling (an empty reply used 148 output tokens and a good one
# 151), it is the model occasionally stopping after the scratchpad.
#
# The tag is matched loosely because Nova varies it: <Thinking>, </thinking >, and internal padding all
# occur, and a strict pattern would leave the tag in place and count it as an answer.
_THINK_TAG_RE = re.compile(r"<\s*thinking\s*>.*?<\s*/\s*thinking\s*>", re.S | re.I)


def _is_thinking_only(reply):
    """True when stripping the scratchpad leaves nothing a student could read."""
    if not reply:
        return False
    return len(_THINK_TAG_RE.sub("", reply).strip()) < 2


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
        #
        # Echoed per-request rather than "*", so an arbitrary page cannot read this cluster's spend or
        # its moderated prompt feed. Vary: Origin keeps a cache from serving one origin's answer to
        # another. do_OPTIONS is deliberately still absent: a cross-origin preflight therefore fails,
        # which is a second layer under the Origin check in _origin_allowed.
        _origin = self.headers.get("Origin")
        if _origin and _origin_allowed(self):
            self.send_header("Access-Control-Allow-Origin", _origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/cost":
            # Expose the ACTIVE ceiling alongside the spend so the UI can say "$x of $y" instead of a bare
            # number. A cap nobody can see reads as "unlimited" right up until it stops working, which is
            # the worst moment to learn about it (Michael, 2026-08-30). Two different ceilings can apply:
            # the always-on infra safety cap (COST_CAP_USD) and, when the C4 budget guard is toggled on,
            # the demo cap (BUDGET_CAP_USD). Report whichever would actually bite first.
            with _cost_lock:
                payload = dict(_cost)
            caps = [c for c in (COST_CAP_USD,
                                BUDGET_CAP_USD if GUARDS.get("budget") else 0) if c and c > 0]
            payload["cap_usd"] = min(caps) if caps else 0
            payload["budget_guard"] = bool(GUARDS.get("budget"))
            self._send(200, payload)
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
                for k in ("input_blocklist", "input_classifier", "output", "budget"):
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
            # ORIGIN ENFORCEMENT REMOVED. It compared the browser's Origin against this request's Host
            # header, and behind the apex router Host is the LOAD BALANCER name, not the public hostname:
            # the proxy sees k8s-agent-console-<hash>.elb.us-west-2.amazonaws.com on every cluster. So a
            # real browser sending Origin: https://michael-student.agenticburn.com never matched and got
            # 403 "cross-origin request rejected", which BurritoBot renders as "the kitchen isn't
            # answering right now (403)". It broke chat on EVERY cluster and did so in front of a room.
            #
            # curl probes passed because curl sends no Origin header, and _origin_allowed returns True
            # when Origin is absent. A check that only fires for browsers cannot be validated without a
            # browser, and it was not.
            #
            # This is the same Host-rewriting trap that already forced the /brief gate out of nginx and
            # into the router earlier the same day. Any origin enforcement has to live at the apex router,
            # which is the only hop that knows the public hostname; #151 is closed as accepted risk in any
            # case, so nothing here needs to enforce it.
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
        if STREAM_ENABLED and text and not _is_probe(text):
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
                san_span.set_attribute("gen_ai.request.model", MODEL_NAME)
                # Datadog LLM Observability reads INPUT/OUTPUT from gen_ai.input.messages /
                # gen_ai.output.messages span ATTRIBUTES (JSON-encoded messages array with parts schema).
                # The older gen_ai.content.prompt/completion event names are not recognised under
                # gen_ai_latest_experimental semconv (the research spikes (removed 2026-08-30; see `git log --diff-filter=D -- research/`) Q5).
                if _CAPTURE_CONTENT:
                    san_span.set_attribute("gen_ai.input.messages", _genai_messages(text))

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
                _cap = BUDGET_CAP_USD if GUARDS.get("budget") else COST_CAP_USD
                self._send(429, {
                    "jsonrpc": "2.0", "id": payload.get("id") if isinstance(payload, dict) else None,
                    "error": {"code": -32000,
                              "message": f"Budget cap reached (${_cap:.2f} on this cluster). Spend is "
                                         "frozen; a blocked request costs nothing."},
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
            # Output attribute: the agent's RAW (pre-scrub) reply, so Datadog LLM Observability shows
            # the OUTPUT panel for this gen_ai span. Set while the sanitize span is still open.
            if san_span is not None and _CAPTURE_CONTENT:
                _reply_txt = chat_reply_text(resp)
                if _reply_txt:
                    san_span.set_attribute("gen_ai.output.messages", _genai_output(_reply_txt))

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
        if STREAM_ENABLED and not _is_probe(prompt):
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
            _cap = BUDGET_CAP_USD if GUARDS.get("budget") else COST_CAP_USD
            self._send(200, {"reply": f"The kitchen tab is frozen. This cluster hit its ${_cap:.2f} spend "
                                      f"budget, so I'm not sending anything else to the model. A blocked "
                                      f"request costs nothing. Turn the budget guard off to keep going.",
                             "guarded": True, "input_tokens": 0, "output_tokens": 0})
            return
        # Forward as A2A message/send to the agent root, inside a CLIENT span (the Service Map egress hop).
        global _chat_seq

        def _forward(ctx):
            """Send the prompt to the agent under contextId ctx. Returns the A2A resp, or None on a
            transport error (in which case a 502 has already been sent)."""
            global _chat_seq
            _chat_seq += 1
            m = {"role": "user", "messageId": f"chat-{_chat_seq}",
                 "parts": [{"kind": "text", "text": prompt}]}
            if ctx:
                # Carry the (self-heal-generationed) browser session as the A2A contextId so kagent
                # threads the order across turns.
                m["contextId"] = ctx
            a2a = {"jsonrpc": "2.0", "id": "chat", "method": "message/send", "params": {"message": m}}
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
                        return json.loads(r.read())
                except Exception as exc:
                    log.error("chat forward failed: %s", exc, extra={"event": "forward_error"})
                    self._send(502, {"reply": "BurritoBot's kitchen isn't answering. Try again in a moment.",
                                     "guarded": False, "input_tokens": 0, "output_tokens": 0})
                    return None

        # Annotate the outer HTTP span (the APM trace root created by OTel auto-instrumentation)
        # with gen_ai attributes so Datadog LLM Obs trace list preview shows content. The chat child
        # span below carries the same attributes for span-level drill-down.
        if _OTEL_AVAILABLE:
            _root_span = trace.get_current_span()
            if _root_span.is_recording():
                _root_span.set_attribute("gen_ai.operation.name", "chat")
                _root_span.set_attribute("gen_ai.request.model", MODEL_NAME)
                if _CAPTURE_CONTENT:
                    _root_span.set_attribute("gen_ai.input.messages", _genai_messages(prompt))

        # Wrap the storefront turn in a gen_ai "chat" span so Datadog LLM Observability sees it as an LLM
        # call. INPUT/OUTPUT panels are populated from gen_ai.input.messages / gen_ai.output.messages span
        # ATTRIBUTES (JSON-encoded messages array). agent.forward (in _forward) parents onto this span.
        chat_cm = (_tracer.start_as_current_span("chat", kind=SpanKind.INTERNAL)
                   if _OTEL_AVAILABLE else nullcontext())
        with chat_cm as chat_span:
            if chat_span is not None:
                chat_span.set_attribute("gen_ai.operation.name", "chat")
                chat_span.set_attribute("gen_ai.request.model", MODEL_NAME)
                if _CAPTURE_CONTENT:
                    chat_span.set_attribute("gen_ai.input.messages", _genai_messages(prompt))
            resp = _forward(_effective_ctx(session))
            if resp is None:
                return
            # Self-heal: if kagent left a dangling tool_use in this session's history, Bedrock rejects every
            # later turn. Rotate to a fresh contextId (drop the poisoned history) and retry the prompt once.
            if session and _is_dangling_tooluse(chat_reply_text(resp)):
                _ctx_gen[session] = _ctx_gen.get(session, 0) + 1
                log.info("chat session poisoned by dangling tool_use; rotated contextId to gen %d",
                         _ctx_gen[session], extra={"event": "ctx_rotate"})
                retry = _forward(_effective_ctx(session))
                if retry is None:
                    return
                resp = retry
            # Same shape of self-heal for a reasoning-only reply: ask once more rather than render an
            # empty bubble at a student. One retry, never a loop, so a model that is reliably terse costs
            # at most double rather than spinning. The cost is bounded and small next to a workshop where
            # one prompt in six visibly does nothing.
            _thinking_only = _is_thinking_only(chat_reply_text(resp))
            if _thinking_only:
                log.info("model returned reasoning with no answer; retrying once",
                         extra={"event": "thinking_only_retry"})
                retry = _forward(_effective_ctx(session))
                if retry is not None and not _is_thinking_only(chat_reply_text(retry)):
                    resp = retry
                    _thinking_only = False
            record_usage(resp)  # feed the live cost counter (same path as A2A)
            pin, pout = chat_usage_tokens(resp)
            reply = chat_reply_text(resp)
            # LAST RESORT, after the retry above already failed. Measured after adding the retry: the
            # empty-reply rate fell from 1-in-6 to 1-in-10, because sometimes BOTH attempts stop after the
            # scratchpad. A retry alone is therefore not a guarantee, and "..." in front of a room is the
            # one outcome worth spending a line of code to prevent.
            #
            # Unwrap the scratchpad and hand back its contents. It is the only thing the model produced,
            # it is usually a serviceable answer in the first person ("I need to list the proteins"), and
            # showing it is more honest than an empty bubble that implies the agent ignored them.
            if _thinking_only and reply:
                _inner = " ".join(t.strip() for t in re.findall(
                    r"<\s*thinking\s*>(.*?)<\s*/\s*thinking\s*>", reply, re.S | re.I))
                if _inner.strip():
                    reply = _inner.strip()
                    log.info("model returned reasoning twice; surfacing it rather than an empty reply",
                             extra={"event": "thinking_only_surfaced"})
            if chat_span is not None and _CAPTURE_CONTENT and reply:
                chat_span.set_attribute("gen_ai.output.messages", _genai_output(reply))
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
        # Set output on the outer HTTP span after reply is known (reply is in scope after the with block).
        if _OTEL_AVAILABLE and _CAPTURE_CONTENT and reply:
            _root_span = trace.get_current_span()
            if _root_span.is_recording():
                _root_span.set_attribute("gen_ai.output.messages", _genai_output(reply))

    def log_message(self, fmt, *args):
        # Route BaseHTTPRequestHandler's default access logging through the structured JSON logger
        # (PRD #27 M2) instead of its plain-text stderr line. Debug level keeps it out of the INFO
        # stream that carries the guard-decision events.
        log.debug(fmt % args, extra={"event": "http_access"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
