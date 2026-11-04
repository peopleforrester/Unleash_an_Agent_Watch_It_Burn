# ABOUTME: Holds #784's token counts (#839): the pinned guard-proxy sets gen_ai.usage.input_tokens and output_tokens on
# ABOUTME: its /chat chat span, summed over every forward of the turn, and on no other span. Runs the pinned proxy.py.
"""#784 asked for token counts on guard-proxy's model-call span. Datadog's Agent Observability reads an llm span's
counts, and prices it, from gen_ai.usage.input_tokens and gen_ai.usage.output_tokens; guard-proxy's /chat `chat` span
set neither, so Agent Observability showed the row as skipped_tokens_missing. weaver/registry declares both on
span.witb.guard_proxy.chat, and guard-proxy-agenticburn#49 (96d16214) sets them in proxy.py and the Go build.
test_genai_semconv_pin.py holds the declaration; this holds what the pinned proxy.py emits (#839).

What this holds, offline, by running the pinned proxy.py in this process with a fake kagent and a recording stand-in
for the OpenTelemetry API (the stock image carries no SDK; the Operator injects one, so the offline suite has none):
- The pinned guard-proxy contains 96d16214, so a re-pin cannot drop the counts.
- A /chat turn's `chat` span carries both counts, equal to what kagent reported and to what the storefront is sent.
- A turn that forwards twice (a reasoning-only first reply, retried once) carries the sum of both forwards.
- A turn whose reply carries no usage sets both counts to 0, so the span is never left without them.
- The counts are on the `chat` span alone: not on the POST /chat root, not on agent.forward, and not on the A2A
  pass-through's POST / root or its `sanitize` span. The collector turns the root and sanitize into Agent
  Observability's invoke_agent span, where they would be a second count beside kagent's own model spans (#746).

The live half (the APM `chat` span on a cluster carrying both counts after the repin syncs) is step 3 of #784's
"Not yet run on a cluster" in decisions.md.
"""
from __future__ import annotations

import contextlib
import contextvars
import itertools
import json
import os
import pathlib
import subprocess
import sys
import threading
import types
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
SUB = REPO / "gitops/ai-layer/guard-proxy"
COUNTS_FIX = "96d162141800f6408c70a4cfc5bc3e9f0bc12ecb"  # guard-proxy-agenticburn#49
KEYS = ("gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens")
PROMPT = "One bean burrito with extra salsa, please"
REPLY = "Coming right up."
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== the pinned guard-proxy sets the counts ==")
pin = subprocess.run(["git", "-C", str(REPO), "ls-tree", "HEAD", "--", "gitops/ai-layer/guard-proxy"],
                     capture_output=True, text=True).stdout.split()
pin_sha = pin[2] if len(pin) >= 3 and pin[0] == "160000" else ""
check("gitops/ai-layer/guard-proxy is a submodule gitlink", bool(pin_sha), f"ls-tree said {pin}")
contains = subprocess.run(["git", "-C", str(SUB), "merge-base", "--is-ancestor", COUNTS_FIX, pin_sha or "HEAD"],
                          capture_output=True, text=True)
check(f"the pin {pin_sha[:7]} contains guard-proxy-agenticburn#49's chat-span token counts {COUNTS_FIX[:7]}",
      contains.returncode == 0, contains.stderr.strip() or f"{COUNTS_FIX[:7]} is not an ancestor of {pin_sha[:7]}")


# A recording stand-in for the parts of the OpenTelemetry API proxy.py imports. Each request runs on its own server
# thread, which starts with an empty context, so the current span is a ContextVar, as the real API keeps it.
class _Ctx:
    def __init__(self, trace_id: int, span_id: int, valid: bool = True):
        self.trace_id, self.span_id, self.is_valid = trace_id, span_id, valid


class _Span:
    def __init__(self, name: str, kind, parent):
        self.name, self.kind, self.parent = name, kind, parent
        self.attributes: dict = {}
        self.status = None
        self._ctx = _Ctx(parent._ctx.trace_id if parent else next(_ids), next(_ids))

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def set_status(self, status):
        self.status = status

    def is_recording(self):
        return True

    def get_span_context(self):
        return self._ctx


class _NoSpan(_Span):
    def __init__(self):
        self.name, self.kind, self.parent, self.attributes, self._ctx = "", None, None, {}, _Ctx(0, 0, False)

    def set_attribute(self, key, value):
        pass

    def is_recording(self):
        return False


_ids = itertools.count(1)
_current: contextvars.ContextVar = contextvars.ContextVar("span", default=None)
SPANS: list[_Span] = []
_spans_lock = threading.Condition()


@contextlib.contextmanager
def _start(name, context=None, kind=None):
    span = _Span(name, kind, _current.get())
    token = _current.set(span)
    try:
        yield span
    finally:
        _current.reset(token)
        with _spans_lock:
            SPANS.append(span)
            _spans_lock.notify_all()


otel = types.ModuleType("opentelemetry")
otel_trace = types.ModuleType("opentelemetry.trace")
otel_trace.SpanKind = types.SimpleNamespace(SERVER="SERVER", CLIENT="CLIENT", INTERNAL="INTERNAL")
otel_trace.StatusCode = types.SimpleNamespace(ERROR="ERROR", OK="OK", UNSET="UNSET")
otel_trace.Status = lambda code, description=None: (code, description)
otel_trace.get_tracer = lambda *a, **k: types.SimpleNamespace(start_as_current_span=_start)
otel_trace.get_current_span = lambda: _current.get() or _NoSpan()
otel_metrics = types.ModuleType("opentelemetry.metrics")
otel_metrics.Observation = lambda value, attributes=None: (value, attributes)
otel_metrics.get_meter = lambda *a, **k: types.SimpleNamespace(create_observable_gauge=lambda *a, **k: None)
otel_propagate = types.ModuleType("opentelemetry.propagate")
otel_propagate.extract = lambda carrier: None
otel_propagate.inject = lambda carrier: None
otel.trace, otel.metrics, otel.propagate = otel_trace, otel_metrics, otel_propagate
sys.modules.update({"opentelemetry": otel, "opentelemetry.trace": otel_trace,
                    "opentelemetry.metrics": otel_metrics, "opentelemetry.propagate": otel_propagate})


class Agent(BaseHTTPRequestHandler):
    """Answers message/send with a finished task, as kagent does for a short turn. `script` is the queue of replies
    still to send, each (text, usage), where usage is (promptTokenCount, candidatesTokenCount) or None for none."""
    script: list[tuple[str, tuple[int, int] | None]] = []
    calls = 0

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        Agent.calls += 1
        text, usage = Agent.script.pop(0) if Agent.script else (REPLY, None)
        result = {"kind": "task", "id": f"task-839-{Agent.calls}", "contextId": "ctx-839",
                  "status": {"state": "completed"}, "artifacts": [{"parts": [{"kind": "text", "text": text}]}]}
        if usage is not None:
            result["metadata"] = {"kagent_usage_metadata": {"promptTokenCount": usage[0],
                                                            "candidatesTokenCount": usage[1],
                                                            "totalTokenCount": usage[0] + usage[1]}}
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


agent_srv = ThreadingHTTPServer(("127.0.0.1", 0), Agent)
threading.Thread(target=agent_srv.serve_forever, daemon=True).start()

ai_docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")) if d]
deploy = next(d for d in ai_docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
container = next(c for c in deploy["spec"]["template"]["spec"]["containers"] if c["name"] == "proxy")
os.environ.update({e["name"]: e["value"] for e in container["env"] if "value" in e})
os.environ["AGENT_URL"] = f"http://127.0.0.1:{agent_srv.server_address[1]}"
sys.path.insert(0, str(SUB))
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("guard_proxy_839", SUB / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)  # safe: the server only starts under __main__
proxy.Handler.log_message = lambda *a: None
check("proxy.py took the OpenTelemetry stand-in (its spans are recorded)", proxy._OTEL_AVAILABLE is True)
# Every guard off and no budget: the counts are the subject here, and a guard would need an LLM Guard to answer.
proxy.GUARDS.update(dict.fromkeys(proxy.GUARDS, False))

proxy_srv = ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
threading.Thread(target=proxy_srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{proxy_srv.server_address[1]}"
_turn = itertools.count(1)


def post(path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(f"{BASE}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, {}


def turn(script: list[tuple[str, tuple[int, int] | None]], path: str = "/chat") -> tuple[int, dict, list[_Span]]:
    """One request under its own session (the Deployment's per-conversation limit stays out of it). Returns the
    status, the reply and the spans it recorded."""
    n = next(_turn)
    Agent.script = list(script)
    with _spans_lock:
        start = len(SPANS)
    if path == "/chat":
        status, reply = post("/chat", {"prompt": PROMPT, "session": f"s-839-{n}"})
    else:
        status, reply = post("/", {"jsonrpc": "2.0", "id": f"a2a-839-{n}", "method": "message/send",
                                   "params": {"message": {"kind": "message", "role": "user", "messageId": f"m-{n}",
                                                          "parts": [{"kind": "text", "text": PROMPT}]}}})
    # A span is recorded when it ends, and proxy.py ends the chat span and the root after the reply is written, so
    # the visitor can hold the reply before either is recorded (one turn in six, #842). Wait for this turn's root,
    # the last span to end; a root that never ends leaves the turn's checks to fail on what was recorded.
    root = "POST /chat" if path == "/chat" else "POST /"
    with _spans_lock:
        _spans_lock.wait_for(lambda: any(s.name == root and s.parent is None for s in SPANS[start:]), timeout=10)
        return status, reply, SPANS[start:]


def named(spans: list[_Span], name: str) -> list[_Span]:
    return [s for s in spans if s.name == name]


def counts(span: _Span) -> tuple:
    return tuple(span.attributes.get(k) for k in KEYS)


def only_chat_counts(label: str, spans: list[_Span]) -> None:
    carrying = sorted(s.name for s in spans if s.name != "chat" and any(k in s.attributes for k in KEYS))
    check(f"{label}: no span but chat carries a gen_ai.usage count", not carrying, f"carrying: {carrying}")


print("== a /chat turn: the chat span carries what kagent reported ==")
status, reply, spans = turn([(REPLY, (1234, 56))])
chats = named(spans, "chat")
check("the visitor gets the agent's reply", status == 200 and reply.get("reply") == REPLY, f"got {status} {reply}")
check("the turn records one chat span, under the POST /chat root",
      len(chats) == 1 and chats[0].parent is not None and chats[0].parent.name == "POST /chat",
      f"spans {[(s.name, s.parent.name if s.parent else None) for s in spans]}")
check("the chat span is INTERNAL with gen_ai.operation.name chat",
      bool(chats) and chats[0].kind == "INTERNAL" and chats[0].attributes.get("gen_ai.operation.name") == "chat")
check("the chat span sets gen_ai.usage.input_tokens 1234 and gen_ai.usage.output_tokens 56",
      bool(chats) and counts(chats[0]) == (1234, 56), f"set {counts(chats[0]) if chats else None}")
check("both counts are integers, as the semconv types them",
      bool(chats) and all(type(v) is int for v in counts(chats[0])), f"set {counts(chats[0]) if chats else None}")
check("the counts equal what the storefront is sent",
      bool(chats) and counts(chats[0]) == (reply.get("input_tokens"), reply.get("output_tokens")),
      f"span {counts(chats[0]) if chats else None}, reply {reply.get('input_tokens')}/{reply.get('output_tokens')}")
check("agent.forward runs under the chat span",
      [s.parent.name for s in named(spans, "agent.forward")] == ["chat"],
      f"agent.forward parents {[s.parent.name if s.parent else None for s in named(spans, 'agent.forward')]}")
only_chat_counts("a /chat turn", spans)

print("== a turn that forwards twice: the chat span carries the sum ==")
calls_before = Agent.calls
status, reply, spans = turn([("<thinking>I should list the fillings.</thinking>", (900, 40)), (REPLY, (1100, 70))])
chats = named(spans, "chat")
check("the reasoning-only first reply is retried once (two forwards reach the agent)",
      Agent.calls - calls_before == 2, f"{Agent.calls - calls_before} forwards")
check("the visitor gets the retry's reply", status == 200 and reply.get("reply") == REPLY, f"got {status} {reply}")
check("the chat span carries both forwards' input tokens summed (900 + 1100 = 2000) and output tokens (40 + 70 = 110)",
      len(chats) == 1 and counts(chats[0]) == (2000, 110), f"set {counts(chats[0]) if chats else None}")
check("the sum equals what the storefront is sent",
      len(chats) == 1 and counts(chats[0]) == (reply.get("input_tokens"), reply.get("output_tokens")),
      f"span {counts(chats[0]) if chats else None}, reply {reply.get('input_tokens')}/{reply.get('output_tokens')}")
only_chat_counts("a retried turn", spans)

print("== a turn whose reply reports no usage: both counts are 0, never absent ==")
status, reply, spans = turn([(REPLY, None)])
chats = named(spans, "chat")
check("the visitor gets the agent's reply", status == 200 and reply.get("reply") == REPLY, f"got {status} {reply}")
check("the chat span sets both counts to 0", len(chats) == 1 and counts(chats[0]) == (0, 0),
      f"set {counts(chats[0]) if chats else None}")
only_chat_counts("a turn with no usage", spans)

print("== the A2A pass-through: no count on its root or on sanitize ==")
status, reply, spans = turn([(REPLY, (500, 25))], path="/")
check("the A2A message/send is forwarded and answered", status == 200 and "result" in reply, f"got {status}")
check("the pass-through records a sanitize span under the POST / root",
      [s.parent.name for s in named(spans, "sanitize")] == ["POST /"],
      f"spans {[(s.name, s.parent.name if s.parent else None) for s in spans]}")
only_chat_counts("the A2A pass-through", spans)

proxy_srv.shutdown()
agent_srv.shutdown()
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All chat-span token count checks passed.")
