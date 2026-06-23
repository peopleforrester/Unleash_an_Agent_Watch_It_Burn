<!-- ABOUTME: Grounded research spike on the Python AI-layer instrumentation landscape for Watch-It-Burn. -->
<!-- ABOUTME: Per-component answer to "which instrumentation approach produces OTel-GenAI-semconv-compliant gen_ai.* spans" for PRD #7 Milestone 2. -->

# 29. Python AI-Layer Instrumentation Landscape (PRD #7 Milestone 2)

## Verification Method

- **Approach:** Deep web research, re-verified **2026-06-23** against current (2026) official docs:
  kagent (`kagent.dev/docs`, `github.com/kagent-dev/kagent`), agentgateway
  (`agentgateway.dev/docs/standalone`), Google ADK (Google Cloud Observability),
  OpenTelemetry Python contrib (`opentelemetry-python-contrib`, PyPI), OpenLLMetry
  (`github.com/traceloop/openllmetry`), and Datadog **Agent Observability** docs/blog (the
  product Datadog historically branded "LLM Observability"; see the naming note in Q7). Every
  material claim carries an inline source URL.
- **In-repo facts taken as CONFIRMED** (read directly this session):
  `gitops/ai-layer/resources.yaml` (kagent v1alpha2 Agent + ModelConfig, guard-proxy,
  llm-guard, evil-mcp/workshop-mcp, chat-ui), `agent/gateway/guard-proxy/proxy.py` (stdlib
  HTTP proxy; A2A-aware; fronts the agent Service; calls LLM Guard; meters cost),
  `agent/gateway/agentgateway.yaml` (agentgateway v1.3.0, OTLP env vars), and
  `beats/03-bad-mcp-excessive-agency/evil-mcp-shim/server.py` (FastMCP shim with poisoned
  tool descriptions).
- **Builds on (NOT re-researched):** `research/05-otel-genai-observability.md` (GenAI semconv
  status, `execute_tool`/`gen_ai.tool.name` span shape, content-capture re-leak trap,
  `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`), `research/23-observability-decision-points-2026.md`
  (Datadog-additive / OTel-neutral principle, `OTEL_RESOURCE_ATTRIBUTES` UST wiring),
  `research/01-kagent.md` (v1alpha2 CRD, Bedrock provider, `toolNames` allowlist),
  `research/02-agentgateway.md` (OSS vs Enterprise doc split, MCP authz, guardrail webhook).
- **NOTE on the cross-reference Whitney listed:** Issue #9's output (`research/28-...`,
  Datadog ingestion + what ADK emits) **does not exist in `research/` yet** (verified by
  `ls research/`). This spike does not depend on it; where their scopes touch (Datadog
  OTLP ingest of `gen_ai.*`, ADK emission), the findings here are independently cited and
  should be reconciled with `research/28` once it lands.
- **PRD framing:** Milestone 2 migrates the AI layer off custom `witb_*` conventions to OTel
  GenAI semconv. CRITICAL distinction throughout: `witb_*` in the repo today are
  **Prometheus *metric* names** on the guard-proxy `/metrics` endpoint (`witb_cost_usd`,
  `witb_tokens_total`, `witb_requests_total`); they are NOT span attributes. The migration
  target (`gen_ai.*`) is the **trace/span** semantic convention. These are two different
  signals; "off `witb_*` to `gen_ai.*`" means *adding compliant GenAI spans*, not renaming
  the Prometheus counters (those can stay as the cost-counter scrape source). This is called
  out per-component below because it changes what each answer has to deliver.

GenAI semconv is still **Development** status (per `research/05`, reconfirmed: "still in
Development status, not Stable" as of semconv v1.41,
https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions). Pin emitter
versions and set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` deliberately.

---

## Executive summary (per-component verdict)

| Component | Emits `gen_ai.*` today? | Recommended approach | Config-only or packages? |
|---|---|---|---|
| **kagent / ADK agent** | Yes, via ADK's built-in OTel once enabled | Turn on `otel.tracing.enabled` in the v0.9.9 Helm chart; ADK (Python runtime) emits GenAI spans | Config-only (Helm), no extra repo packages |
| **agentgateway v1.3.0** | Yes, built-in GenAI-semconv tracing | Set `frontendPolicies.tracing.otlpEndpoint` in the config file (NOT the env var the repo uses) | Config-only |
| **guard-proxy** | No (stdlib HTTP, no OTel) | Manual OTel SDK spans, and it does NOT call Bedrock; it proxies A2A. Instrument as a proxy span + propagate context | Add OTel SDK packages |
| **evil-mcp-shim** | No (FastMCP, no OTel) | No instrumentation needed; visible as the agent's `execute_tool` spans | n/a |

The single most consequential correction below: **the guard-proxy does not make Bedrock LLM
calls.** OpenLLMetry vs `opentelemetry-instrumentation-botocore` for "the proxy's Bedrock
calls" is a **false premise**: the proxy forwards JSON-RPC to the kagent agent, and the
agent (ADK) is what calls Bedrock. The botocore Bedrock auto-instrumentation answer applies
to the **agent pod**, not the proxy.

---

## Q1. kagent / ADK: what does `otel.tracing.enabled: true` turn on in the v0.9.9 Helm chart?

**Confirmed mechanism + field path.** kagent's tracing is OFF by default and enabled through
Helm values. The exact path is:

```yaml
otel:
  tracing:
    enabled: true
    exporter:
      otlp:
        endpoint: http://<collector-or-jaeger>:4317   # OTLP gRPC
```

This is the field path confirmed both in `research/05` and re-verified against the current
kagent tracing doc (`otel.tracing.enabled: true`, endpoint at
`otel.tracing.exporter.otlp.endpoint`). It is **config-only**: you install the OTLP backend
(the doc demonstrates Jaeger) separately, then `helm upgrade` kagent with these values. No
extra Python packages are added by the operator; the instrumentation ships inside the agent
runtime.
Source: https://kagent.dev/docs/kagent/observability/tracing

**Is it `gen_ai.*` compliant?** **Yes, by inheritance from Google ADK**, with one
verify-at-build caveat. The chain of evidence:

1. **kagent's engine runs agents on Google ADK.** The kagent README/architecture states
   plainly: "The engine runs your agents using ADK" (Google Agent Development Kit), and the
   project uses the **Python ADK runtime** (the agent pod is the Python ADK app; this matches
   the repo's `adk_usage_metadata`/`kagent_usage_metadata` token keys in `proxy.py`).
   Source: https://github.com/kagent-dev/kagent (architecture section)
2. **ADK ≥ 1.17.0 emits OTel GenAI semantic-convention spans natively.** Google's own
   instrumentation guide: "ADK framework versions 1.17.0 and later include built-in support
   for OpenTelemetry," producing GenAI spans (e.g. `call_llm` spans with GenAI events) when
   you set `OTEL_SEMCONV_STABILITY_OPT_IN='gen_ai_latest_experimental'` plus
   `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` and an OTLP exporter.
   Source: https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk
3. **Datadog and others classify ADK as an OTel-GenAI-compliant emitter.** MLflow lists
   "Google ADK" among tools whose traces it recognizes as GenAI-semconv-compliant.
   Source: https://mlflow.org/docs/latest/genai/tracing/opentelemetry/genai-semconv/

**Correction (validation pass 2026-06-23):** The original draft listed
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` as a plain on/off flag. Google's ADK
instrumentation doc is explicit that with `gen_ai_latest_experimental` semconv the valid value
is `EVENT_ONLY` and that setting it to `true` "results in an invalid configuration … therefore,
log and trace data isn't collected." Set it to `EVENT_ONLY` (not `true`) on the ADK path. See Q5.
The same Google ADK doc (re-verified 2026-06-23) also recommends
`ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS='false'` to prevent PII/prompt content from landing in
spans, relevant to the content re-leak trap `research/05` flags for the redaction beat.
Source: https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk

**The caveat (verify-at-build, not config):** The kagent tracing doc itself does **not**
state semconv compliance and only demonstrates filtering by `service.name=kagent` and the
`agent_run [<agent>]` operation in Jaeger (per `research/05`, reconfirmed). The
`gen_ai.*`/`execute_tool` richness is a property of the **ADK version kagent bundles** and of
whether kagent passes the `OTEL_SEMCONV_STABILITY_OPT_IN`/capture env vars into the ADK
runtime. Two things to confirm on a live v0.9.9 cluster (Phase 3): (a) the bundled ADK is
≥ 1.17.0; (b) the agent pod actually receives `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`.
The repo already wires `deployment.env` on the Agent (currently only `OTEL_RESOURCE_ATTRIBUTES`),
so the semconv opt-in env can be added there if kagent honors `deployment.env` (itself a
standing verify-at-build flag in `resources.yaml`). If `deployment.env` is not honored on
chart 0.9.9, set it via the kagent Helm pod template instead.

**Extra packages or config-only?** **Config-only for the workshop.** kagent + ADK ship the
instrumentation; the operator turns it on with Helm values and (if needed) the two env vars.
You do NOT pip-install anything into the agent for tracing. (Contrast: a *bare* ADK app per
Google's guide installs `opentelemetry-instrumentation-google-genai>=0.4b0` +
`opentelemetry-exporter-otlp-proto-grpc`, but kagent bundles the runtime, so that is the
kagent maintainers' concern, not the workshop's. Confirm at build that the chart includes it.)

**Confidence: HIGH** on the field path and config-only nature; **MEDIUM** on automatic
`gen_ai.*` richness without setting the semconv opt-in env (gated on the live Phase-3 span
capture that `research/05` already flagged as mandatory).

---

## Q2. agentgateway v1.3.0: built-in OTel tracing emitting semconv spans? How to activate?

**Yes: built-in, config-only, GenAI-semconv-aware. But the repo manifest activates it the
WRONG way and must change.**

**What v1.3.0 GA has.** agentgateway "has built-in OpenTelemetry support for distributed
tracing, metrics, and logs" and "natively emits OpenTelemetry traces using the GenAI semantic
conventions (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.operation.name`,
…)." This is a config-only feature; no extra component is installed.
Sources: https://agentgateway.dev/docs/standalone/main/integrations/observability/opentelemetry/ ;
https://agentgateway.dev/docs/standalone/latest/tutorials/telemetry/

**The correct field path (verified, replaces the repo's pinned guess).** Tracing is enabled
in the **config file** under `frontendPolicies.tracing`:

```yaml
frontendPolicies:
  tracing:
    otlpEndpoint: http://<collector>:4317   # OTLP gRPC
    randomSampling: true                     # dev: capture every trace; prod: a 0..1 ratio
```

`randomSampling: true` captures every trace (use in the demo); in production set a 0 to 1 ratio.
Source: https://agentgateway.dev/docs/standalone/main/integrations/observability/opentelemetry/

**REPO GAP (load-bearing finding).** `agent/gateway/agentgateway.yaml` configures tracing via
the **`OTEL_EXPORTER_OTLP_ENDPOINT` environment variable** on the container (plus
`OTEL_RESOURCE_ATTRIBUTES`). The verified v1.3.0 OSS standalone docs document tracing **only**
via the `frontendPolicies.tracing.otlpEndpoint` **config-file field**, and make no mention of
an `OTEL_EXPORTER_OTLP_ENDPOINT` env var path. The manifest's inline `verify-at-build` note
(re-verify v1.3.0 field paths against the standalone docs) is exactly right and now resolved:
**the env-var approach is unverified/likely inert; the supported activation is the config-file
`frontendPolicies.tracing` block.** This is a config change to make in Milestone 2 (NOT in
this research-only spike). The `OTEL_RESOURCE_ATTRIBUTES` env is still useful for UST
(`service.name`/`version`/`env`) per `research/23`, but the OTLP *endpoint* belongs in the
config file.

**Does it tag the A2A / MCP path with `gen_ai.*`?** Partially confirmed, partially
verify-at-build. The docs name `gen_ai.operation.name` and `gen_ai.request.model` as
LLM-specific attributes and say "attributes might vary by deployment mode and request type,"
referencing separate observability sections for MCP and LLM traffic, i.e. tracing spans MCP
+ LLM, but the page does not guarantee full `gen_ai.*` enrichment for a **kagent A2A
(JSON-RPC) backend** specifically (the same backend-type uncertainty `research/02` flagged for
the guardrail webhook). Treat: agentgateway WILL produce OTLP spans for traffic through it;
whether they carry the full `gen_ai.*` set for the A2A backend (vs a recognized
chat-completions LLM provider) must be confirmed on a live v1.3.0 by inspecting emitted spans.
Source: https://agentgateway.dev/docs/standalone/latest/tutorials/telemetry/

**Confidence: HIGH** that the activation is `frontendPolicies.tracing.otlpEndpoint`
(config-only) and that the repo's env-var path is wrong; **MEDIUM** on full `gen_ai.*`
enrichment for the A2A backend (verify-at-build, same caveat as `research/02`).

---

## Q3. guard-proxy: right approach to instrument its "Bedrock LLM calls" as `gen_ai.*` spans?

**FALSE PREMISE, corrected.** The guard-proxy **does not make Bedrock / LLM calls.** Reading
`agent/gateway/guard-proxy/proxy.py` directly: it is a stdlib `ThreadingHTTPServer` that
(1) receives A2A JSON-RPC POSTs from the chat UI, (2) optionally checks the prompt against a
block-list and an LLM-Guard `/analyze/prompt` call, (3) **forwards the request to the kagent
agent Service** (`AGENT_URL = http://workshop-agent.agent...:8080`) via `urllib.request`,
(4) optionally scrubs the response via LLM Guard `/analyze/output`, and (5) tallies token
usage *parsed out of the agent's A2A response metadata* (`kagent_usage_metadata` /
`adk_usage_metadata`) for the cost counter. There is no `boto3`, no `bedrock-runtime` client,
no model invocation anywhere in the proxy. **The agent pod (ADK) is what calls Bedrock.**

So the question reframes to: **how should the guard-proxy be instrumented, and where do the
`gen_ai.*` Bedrock spans actually come from?**

1. **The `gen_ai.*` Bedrock spans come from the agent, not the proxy.** They are produced by
   ADK inside the agent pod (Q1). If you want a *separate* Bedrock span from the agent pod via
   the SDK path, that is `opentelemetry-instrumentation-botocore` on the agent (Q5/Q6), again
   not on the proxy.
2. **The guard-proxy should be instrumented as what it is: an HTTP proxy / guardrail span.**
   The valuable, semconv-honest telemetry from the proxy is NOT `gen_ai.*` model spans (it
   does not call a model). It is a SERVER span for the inbound request, a CLIENT span for
   the forward to the agent (with **W3C trace-context propagation** so the proxy span is the
   parent of the agent's `invoke_agent`/`call_llm` spans), and span events/attributes for the
   guard decisions (block-list hit, classifier verdict, output redaction). That makes the
   guardrail visible in the same waterfall as the agent's `gen_ai.*` spans without
   misattributing model semantics to a component that has none.
3. **OpenLLMetry vs manual OTel SDK for the proxy:** OpenLLMetry is the wrong tool here. It
   instruments *LLM client libraries* (OpenAI, Anthropic, Bedrock/boto3, LangChain, etc.). The
   proxy uses none of those; it speaks raw `urllib` HTTP to another in-cluster service. There
   is nothing for OpenLLMetry to hook. **Use the manual OTel SDK** (small, explicit spans) for
   the proxy. See Q6 for the minimal pattern, adapted to a proxy/guard span rather than a
   fictitious Bedrock span.
   Source (OpenLLMetry scope = LLM client libraries / frameworks, incl. Bedrock):
   https://github.com/traceloop/openllmetry ;
   https://futureagi.com/blog/openinference-vs-openllmetry-vs-openlit-2026/

**If the intent is "the proxy should carry the cost/token data as `gen_ai.*` spans":** the
proxy already has the token counts (it parses `promptTokenCount` / `candidatesTokenCount` from
the agent response). It *could* attach `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens`
to its forward span as a convenience. But the **authoritative** GenAI usage spans should be the
agent's (ADK); duplicating them on the proxy risks double-counting in a GenAI-aware backend
(Datadog maps `gen_ai.usage.*` to cost). Recommendation: keep the proxy's role to
proxy/guard/propagation spans + the existing Prometheus `witb_*` counters for the live cost
panel; let the agent own the `gen_ai.*` usage attributes.

**Confidence: HIGH** (read from source; the proxy's call graph is unambiguous).

---

## Q4. evil-mcp-shim: does it need instrumentation?

**No instrumentation needed. It is visible through the agent's tool-call spans.**

`beats/03-bad-mcp-excessive-agency/evil-mcp-shim/server.py` is a `FastMCP` server exposing
`get_weather` (poisoned description), `read_internal_config` (the rogue tool), and
`apply_optimization` (clown-file). When the agent is induced to call a rogue tool, the
**caller side** of that call is what the workshop narrates, and the caller is the ADK agent.
Per `research/05` (reconfirmed against the GenAI agent-spans spec), tool calls are first-class:
the agent emits an **`execute_tool {gen_ai.tool.name}`** span (e.g. `execute_tool read_internal_config`)
with `gen_ai.tool.name` / `gen_ai.tool.call.id`. That span, nested under `invoke_agent`, is
exactly the "the agent called the tool it should not have" picture; it appears whether or not
the MCP server itself is instrumented.
Sources: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/ ;
research/05 §2.

Two refinements:

- **agentgateway fronts the MCP traffic** (per the build and `research/02`), so the MCP call
  also traverses the gateway and shows up in agentgateway's own OTLP spans (Q2). That is a
  second, independent witness to the rogue call: useful but still not requiring shim
  instrumentation.
- **Instrumenting the shim would actively muddy the lesson.** The teaching point is that an
  *untrusted* server need not cooperate with your observability; you still see the abuse
  because **your** agent (and **your** gateway) are instrumented. Adding OTel to the shim would
  imply the attacker helpfully traces themselves. Leave it un-instrumented.

**Confidence: HIGH.**

---

## Q5. For any auto-instrumentation answer: which packages, and do they conflict with the in-use Python OTel SDK?

Auto-instrumentation is relevant to exactly two places, **both on the agent pod, neither on
the guard-proxy**:

**(a) ADK's built-in instrumentation (Q1).** Bundled in the kagent agent runtime. If a *bare*
ADK app is ever built (it is not, for kagent), Google's guide installs
`opentelemetry-instrumentation-google-genai>=0.4b0` and `opentelemetry-exporter-otlp-proto-grpc`.
For kagent, these are the chart maintainers' dependency, not the workshop's.
Source: https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk

**(b) botocore Bedrock auto-instrumentation (relevant if you want SDK-level Bedrock spans from
the agent pod, in addition to or instead of ADK's).**
- **Package:** `opentelemetry-instrumentation-botocore`. Current version **0.63b1 (released
  2026-05-21)**. Its Bedrock extension "implements the GenAI semantic conventions for the
  following API calls: **Converse, ConverseStream, InvokeModel, InvokeModelWithResponseStream**,"
  with enhanced support for Amazon Titan, Nova, and **Anthropic Claude**, i.e. exactly the
  Bedrock-Claude path this workshop uses.
  Sources: https://pypi.org/project/opentelemetry-instrumentation-botocore/ ;
  https://github.com/open-telemetry/opentelemetry-python-contrib/blob/main/instrumentation/opentelemetry-instrumentation-botocore/src/opentelemetry/instrumentation/botocore/extensions/bedrock_utils.py
- **Enablement:** either programmatic `BotocoreInstrumentor().instrument()` or the
  `opentelemetry-instrument` CLI / `opentelemetry-distro` auto-loader. It hooks botocore's
  client machinery, so the same hook covers all AWS calls including bedrock-runtime.
- **Content capture** is gated by `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`
  (default off, the same flag `research/05` covers for the re-leak trap), so it does not leak
  prompts/responses by default. **Correction (validation 2026-06-23):** on the ADK path with
  `gen_ai_latest_experimental` semconv, the valid enabling value is `EVENT_ONLY`; Google's ADK
  doc states that setting it to `true` "results in an invalid configuration." Use `EVENT_ONLY`,
  not `true`, when enabling content capture for ADK.

**Conflict with the in-use Python OTel SDK?**
- **No conflict in principle.** `opentelemetry-instrumentation-*` packages are *built on* the
  OTel API/SDK; they register spans through the same `TracerProvider`. Using the manual SDK
  (`opentelemetry-api` + `opentelemetry-sdk`) alongside instrumentation packages is the normal,
  supported pattern (one provider, both manual and auto spans land in the same pipeline).
- **The real conflict risk is DOUBLE-INSTRUMENTATION of Bedrock**, not an SDK clash. If ADK
  already emits a `gen_ai.*` model span for the Bedrock call *and* botocore also emits one for
  the same `InvokeModel`, you get two overlapping GenAI spans for one model call → inflated
  token/cost in a GenAI-aware backend (Datadog maps `gen_ai.usage.*` to cost). **Pick one
  source of the model span:** prefer ADK's (it carries agent/tool context), and only add
  botocore Bedrock instrumentation if ADK's bundled version turns out NOT to emit a usable
  `gen_ai.*` model span (decide after the Phase-3 live span capture). Do not run both for the
  same call without a dedup/filter plan.
- **Version-skew risk:** keep all `opentelemetry-*` packages on compatible versions; mixing a
  very new instrumentation (`0.63b1`) with an old core SDK can break. Pin together in
  `VERSIONS.lock`.
- **The guard-proxy is unaffected**: it ships no boto3 and currently no OTel; auto-instrumentation
  has nothing to hook there (Q3).

**Confidence: HIGH** on packages/versions and the SDK-coexistence rule; **MEDIUM** on whether
botocore Bedrock instrumentation is *needed at all* (depends on what ADK already emits; the
Phase-3 capture decides it).

---

## Q6. guard-proxy manual spans: minimal Python OTel SDK pattern

Because the proxy is a stdlib HTTP server that **forwards to the agent** (not a Bedrock
client; Q3), the minimal-and-honest pattern instruments the **forward as a CLIENT span with
context propagation**, plus guard-decision attributes. (If a future component truly does call
Bedrock with boto3, the same SDK setup plus `opentelemetry-instrumentation-botocore` from Q5
gives the `gen_ai.*` model span for free, shown second.)

**Packages:** `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`.
(Note: this adds dependencies to a proxy that is deliberately stdlib-only and runs from a stock
`python:3.12-slim` via a mounted ConfigMap, so Milestone 2 will need to bake an image or
`pip install` at startup. That is a real cost to weigh; it is NOT a research finding to
implement here.)

**One-time SDK init (module load):**

```python
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Resource attributes come from OTEL_RESOURCE_ATTRIBUTES (UST per research/23); endpoint
# from OTEL_EXPORTER_OTLP_ENDPOINT. Both are already set as env on the proxy Deployment.
provider = TracerProvider(resource=Resource.create())
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("watch-it-burn.guard-proxy")
```

**Honest proxy/guard span around the forward (with W3C context propagation so the agent's
`gen_ai.*` spans nest under it):**

```python
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.propagate import inject

# inside do_POST, replacing the bare urllib forward:
with tracer.start_as_current_span("guard_proxy.forward", kind=SpanKind.CLIENT) as span:
    span.set_attribute("witb.input_blocklist", GUARDS["input_blocklist"])
    span.set_attribute("witb.input_classifier", GUARDS["input_classifier"])
    span.set_attribute("witb.output_guard", GUARDS["output"])
    headers = {"Content-Type": "application/json"}
    inject(headers)  # W3C traceparent -> agent spans become children
    req = urllib.request.Request(AGENT_URL + self.path, data=raw, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            resp = json.loads(r.read())
    except Exception as exc:
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        raise
    # token usage the proxy already parses; attach as GenAI usage IF (and only if) the proxy is
    # chosen as the usage source (see Q3 — prefer the agent owning gen_ai.usage.* to avoid dupes):
    # span.set_attribute("gen_ai.usage.input_tokens", pin)
    # span.set_attribute("gen_ai.usage.output_tokens", pout)
```

**If/when a component actually calls Bedrock with boto3** (the literal "Bedrock call as
`gen_ai.*` span"), the manual span is unnecessary; auto-instrumentation produces the compliant
span:

```python
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
BotocoreInstrumentor().instrument()   # Converse/InvokeModel -> gen_ai.* span automatically
# import os; os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = "gen_ai_latest_experimental"
```

This emits `gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, etc.,
per the contrib Bedrock extension (Q5).
Sources: https://pypi.org/project/opentelemetry-instrumentation-botocore/ ;
OTel SDK conventions per the repo's own `rules/tools/opentelemetry.md`
(`tracer.start_as_current_span`, `SpanKind.CLIENT` for outbound, `Status(ERROR)` on failure).

**Confidence: HIGH** on the SDK pattern; the propagation/`inject` step is the key correctness
detail (without it the proxy's span and the agent's `gen_ai.*` spans live in separate traces).

---

## Q7. OpenLLMetry status (2026): standalone, deprecated, or absorbed? Recommended path? Datadog-supported?

**Status: STILL STANDALONE and actively maintained. NOT deprecated, NOT absorbed into
OpenTelemetry as a project.** Details, all verified:

- **The project is alive and maintained.** ServiceNow **acquired Traceloop/OpenLLMetry in
  March 2026**, which "validated OTel as the substrate, confirming OpenLLMetry's ongoing
  maintenance and support." The README still ships 30+ Python integrations (incl. Bedrock,
  Anthropic, Google GenAI, LangChain, etc.) and an active 2026 release cadence: latest
  **v0.61.0 (2026-05-31)**, 258 releases, ~7.2k GitHub stars (re-verified 2026-06-23). The
  GitHub org now displays as **"traceloop from ServiceNow"** (corroborating the acquisition).
  Sources: https://futureagi.com/blog/openinference-vs-openllmetry-vs-openlit-2026/ ;
  https://github.com/traceloop/openllmetry ; https://github.com/traceloop
- **"Absorbed into OpenTelemetry" is half-true and must be stated precisely.** What was
  contributed upstream is the **semantic conventions**, not the codebase: the README states
  "Our semantic conventions are now part of OpenTelemetry!" OpenLLMetry remains a **separate
  instrumentation library** built on the OTel SDK; it was not merged into the OTel project.
  Source: https://github.com/traceloop/openllmetry (README)
- **Semconv-compliance caveat (load-bearing for "produces compliant spans").** OpenLLMetry has
  a **known lag** emitting *deprecated* GenAI attributes. Issue #3515 (opened 2025-12-12)
  reports OpenLLMetry still emits `gen_ai.prompt` / `gen_ai.completion`, attributes the spec
  removed (the spec now uses `gen_ai.input.messages` / `gen_ai.output.messages` /
  `gen_ai.system_instructions`, per `research/05`). As captured, the issue had no maintainer
  resolution in-thread (two linked PRs shown Closed, resolution not detailed). So "OpenLLMetry
  → automatically fully current semconv-compliant" is NOT safe to assume in 2026; verify the
  exact attribute names it emits for your version before trusting it for a *strict*-semconv
  migration.
  Source: https://github.com/traceloop/openllmetry/issues/3515

**Current recommended Python OTel GenAI semconv auto-instrumentation path (2026):** the
industry has converged on the **OpenTelemetry GenAI Semantic Conventions** as the standard,
emitted by **framework-native or official contrib instrumentation**. For THIS stack the
recommended path is, in order:

1. **Let the framework emit it natively**: ADK (Q1) for the agent, agentgateway built-in (Q2)
   for the gateway. No third-party instrumentation library needed.
2. **Official OTel contrib `opentelemetry-instrumentation-botocore`** (Q5) for SDK-level
   Bedrock spans if/where a component calls boto3 directly. This is the
   first-party, spec-aligned path for Bedrock-Claude.
3. **OpenLLMetry / OpenInference / OpenLIT** are valid *alternatives* if you want a single
   library spanning many providers, but for this workshop they add a dependency and the
   semconv-currency caveat above, while ADK + agentgateway + botocore already cover every model
   call in the stack. **Do not adopt OpenLLMetry here**: there is no instrumentation gap it
   fills (the proxy has no LLM client to hook; the agent and gateway self-instrument).
   Sources: https://futureagi.com/blog/openinference-vs-openllmetry-vs-openlit-2026/ ;
   https://zylos.ai/research/2026-02-28-opentelemetry-ai-agent-observability

**Is the OTel-native path Datadog-supported?** **Yes, first-class.**

**Datadog product-name note (updated 2026-06-23).** The Datadog product that ingests
`gen_ai.*` spans is now branded **"Agent Observability"**: the current docs landing page
(`/llm_observability/`) is titled **"Agent Observability"**, and the marketing
product page's browser title is **"Agent Observability | LLM Observability"** (the two names refer to the
same offering; "LLM Observability" is the prior/legacy brand and is still used interchangeably,
including in the original December-2025 blog and in the still-`/llm_observability/`-rooted docs
URLs). The docs and blog cited below predate the rename in their *prose* but are the same
product surface. Datadog also added Agentic-AI features (AI Agent Monitoring: agent decision-path
graphs, AI Agents Console, LLM Experiments; GA announced at DASH June 2025) and shipped
**automatic instrumentation for Google ADK** in Feb 2026, directly relevant to the kagent/ADK
path in Q1.
Sources: https://docs.datadoghq.com/llm_observability/ (landing-page title "Agent Observability") ;
https://www.datadoghq.com/products/ai/agent-observability/ (browser title "Agent Observability | LLM Observability") ;
https://www.infoq.com/news/2026/02/datadog-google-llm-observability/ (Datadog auto-instruments Google ADK).

It "natively supports OpenTelemetry GenAI Semantic Conventions (v1.37 and up)" with **no code
changes**: it ingests `gen_ai.*` spans "from any OTel-compatible SDK or framework that emits
spans conforming to the GenAI Semantic Conventions v1.37 schema," via direct OTLP intake, the
Datadog Agent in OTLP mode, or the OTel Collector / DDOT. It auto-maps `gen_ai.request.model`,
`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.operation.name`,
`gen_ai.provider.name` to its native Agent/LLM Observability schema (latency / tokens / cost /
model / finish reason), and explicitly lists **Bedrock** (via
`opentelemetry-instrumentation-botocore >= 1.31.57`) among tested frameworks alongside agent
frameworks (e.g. Strands Agents). This is exactly the Datadog-additive / OTel-neutral
principle from `research/23`: instrument once in OTel GenAI semconv, Datadog and the OSS
backends both consume it.
Sources: https://www.datadoghq.com/blog/llm-otel-semantic-convention/ (2025-12-01) ;
https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ (H1 "OpenTelemetry Instrumentation"; body refers to "Agent Observability" supporting OTel GenAI semconv v1.37+) ;
https://docs.datadoghq.com/llm_observability/instrumentation/auto_instrumentation/

**Confidence: HIGH** on standalone/maintained, the semconv-contribution detail, the deprecated-
attribute caveat, and Datadog's native OTel-GenAI support.

---

## Cross-cutting risks / verify-at-build

1. **`witb_*` vs `gen_ai.*` are different signals.** The migration adds compliant GenAI
   **spans** (from ADK + agentgateway + optionally botocore); the **Prometheus `witb_*`
   metrics** on the proxy can stay as the cheap live cost-counter scrape. Do not conflate
   "migrate off `witb_*`" with "rename the counters." (HIGH)
2. **agentgateway tracing field path** must move from the env var `OTEL_EXPORTER_OTLP_ENDPOINT`
   to the config-file `frontendPolicies.tracing.otlpEndpoint` (Q2). The env-var path is
   unverified on v1.3.0 standalone. (HIGH, confirmed against docs.)
3. **Double-instrumentation of Bedrock** (ADK span + botocore span for the same call) inflates
   token/cost in Datadog. Pick one source; prefer ADK. Decide after the Phase-3 live span
   capture. (MEDIUM)
4. **GenAI semconv is Development**: attribute names churn; set
   `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` deliberately and record emitted
   names in `VERSIONS.lock` (per `research/05`). (HIGH)
5. **kagent `deployment.env` honored on chart 0.9.9?** The repo already flags this; the
   semconv opt-in env (and content-capture flag for the re-leak beat) depend on it. (MEDIUM)
6. **Adding the OTel SDK to the stdlib guard-proxy** changes its deploy story (currently
   ConfigMap-mounted into a stock python image). A manual-span build means baking an image or
   `pip install` at startup. (cost note, not a blocker)
7. **OpenLLMetry deprecated-attribute lag** (issue #3515): if OpenLLMetry is ever chosen
   anyway, verify it emits `gen_ai.input.messages`/`gen_ai.output.messages`, not the removed
   `gen_ai.prompt`/`gen_ai.completion`. (MEDIUM)

---

## Sources (distinct citations)

1. https://kagent.dev/docs/kagent/observability/tracing : kagent `otel.tracing.enabled` field path, config-only, Jaeger backend.
2. https://github.com/kagent-dev/kagent : kagent engine runs on Google ADK; OTel tracing support.
3. https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk : ADK ≥1.17.0 native OTel GenAI spans; env vars; `opentelemetry-instrumentation-google-genai` package.
4. https://mlflow.org/docs/latest/genai/tracing/opentelemetry/genai-semconv/ : ADK listed as a GenAI-semconv-compliant emitter; semconv still Development.
5. https://agentgateway.dev/docs/standalone/main/integrations/observability/opentelemetry/ : `frontendPolicies.tracing.otlpEndpoint` / `randomSampling`; native GenAI-semconv spans.
6. https://agentgateway.dev/docs/standalone/latest/tutorials/telemetry/ : agentgateway GenAI attributes; MCP + LLM telemetry scope.
7. https://pypi.org/project/opentelemetry-instrumentation-botocore/ : v0.63b1 (2026-05-21); Bedrock Converse/InvokeModel GenAI-semconv spans; Anthropic Claude support.
8. https://github.com/open-telemetry/opentelemetry-python-contrib/blob/main/instrumentation/opentelemetry-instrumentation-botocore/src/opentelemetry/instrumentation/botocore/extensions/bedrock_utils.py : Bedrock GenAI extension source + content-capture flag.
9. https://github.com/traceloop/openllmetry : OpenLLMetry standalone, "semantic conventions now part of OpenTelemetry," 30+ integrations incl. Bedrock.
10. https://github.com/traceloop/openllmetry/issues/3515 : OpenLLMetry still emits deprecated `gen_ai.prompt`/`gen_ai.completion` (opened 2025-12-12).
11. https://futureagi.com/blog/openinference-vs-openllmetry-vs-openlit-2026/ : ServiceNow acquired Traceloop/OpenLLMetry (March 2026); maintained; OpenLLMetry scope = LLM client libs/frameworks.
12. https://zylos.ai/research/2026-02-28-opentelemetry-ai-agent-observability : industry convergence on OTel GenAI semconv; native/contrib emission.
13. https://www.datadoghq.com/blog/llm-otel-semantic-convention/ : Datadog natively supports OTel GenAI semconv v1.37+; no code changes; attribute mapping; Bedrock supported (2025-12-01).
14. https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ : Datadog OTLP ingest of GenAI spans; page H1 "OpenTelemetry Instrumentation" (body: "Agent Observability supports … OTel 1.37+ GenAI semconv"); Bedrock via `opentelemetry-instrumentation-botocore >= 1.31.57`; agent frameworks (Strands).
15. https://docs.datadoghq.com/llm_observability/instrumentation/auto_instrumentation/ : Datadog auto-instrumentation framework list (incl. Bedrock).
16. https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/ : GenAI agent spans: `execute_tool {gen_ai.tool.name}`, `invoke_agent`, tool-call first-class (now relocated; see #18).
17. https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions : GenAI semconv still Development (v1.41); `OTEL_SEMCONV_STABILITY_OPT_IN` behavior.
18. https://docs.datadoghq.com/llm_observability/ : Datadog docs landing page now titled **"Agent Observability"** (the rename of the LLM Observability product surface).
19. https://www.datadoghq.com/products/ai/agent-observability/ : Datadog product page titled **"Agent Observability | LLM Observability"**; AI Agent Monitoring / Agents Console / Experiments.
20. https://www.infoq.com/news/2026/02/datadog-google-llm-observability/ : Datadog ships automatic instrumentation for Google ADK (Feb 2026).
21. https://github.com/traceloop : GitHub org displays as "traceloop from ServiceNow" (corroborates the acquisition).
22. https://opentelemetry.io/docs/specs/semconv/gen-ai/ : GenAI semconv spec "Moved" notice (spec relocated to the dedicated semantic-conventions-genai repo).

(22 distinct external citations; builds on in-repo `research/05` and `research/23` as
instructed, and on `research/01`/`research/02` for kagent/agentgateway CRD + guardrail context.)

---

## Validation pass (adversarial, 2026-06-23)

Independent skeptical re-verification of the load-bearing claims against current (2026) official
sources via live WebFetch/WebSearch. Default posture: a claim not backed by a current official
source is UNVERIFIED. Verdicts below; one inline correction was applied (the ADK content-capture
flag value), noted in Q1 and Q5.

**Q1, kagent tracing field path + ADK GenAI semconv:**

- **CONFIRMED**: kagent enables tracing via Helm values `otel.tracing.enabled: true` and
  `otel.tracing.exporter.otlp.endpoint`; config-only; the doc demonstrates a Jaeger OTLP backend
  and does **not** itself mention `gen_ai.*` semconv (matches the spike's verify-at-build caveat).
  Source: https://kagent.dev/docs/kagent/observability/tracing
- **CONFIRMED**: ADK ≥ 1.17.0 includes built-in OpenTelemetry and emits GenAI-semconv telemetry
  with `OTEL_SEMCONV_STABILITY_OPT_IN='gen_ai_latest_experimental'`; installs
  `opentelemetry-instrumentation-google-genai>=0.4b0` + `opentelemetry-exporter-otlp-proto-grpc`.
  Source: https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk
- **REFUTED (inline detail, corrected)**: the draft treated
  `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` as a plain on/off flag. The Google ADK doc
  states that with latest semconv the valid value is `EVENT_ONLY`, and setting it to `true`
  "results in an invalid configuration." Corrected in Q1 and Q5.
  Source: https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk
- **CONFIRMED**: MLflow lists Google ADK as a GenAI-semconv-compliant emitter.
  Source: https://mlflow.org/docs/latest/genai/tracing/opentelemetry/genai-semconv/

**Q2, agentgateway v1.3.0 tracing field path:**

- **CONFIRMED**: tracing is enabled in the config file under `frontendPolicies.tracing` with
  fields `otlpEndpoint` and `randomSampling`; the docs show **no** `OTEL_EXPORTER_OTLP_ENDPOINT`
  env-var path, and natively emit GenAI semconv (`gen_ai.operation.name`, `gen_ai.request.model`).
  The spike's "repo env-var path is wrong; use the config-file field" finding holds.
  Source: https://agentgateway.dev/docs/standalone/main/integrations/observability/opentelemetry/

**Q3 / Q6, guard-proxy approach + manual span pattern:** in-repo source claims
(`proxy.py` makes no Bedrock call; forwards A2A; uses `urllib`) are taken as CONFIRMED per the
instructions (read directly this session). The external claim that OpenLLMetry instruments LLM
**client libraries** (so it has nothing to hook in a stdlib `urllib` proxy) is **CONFIRMED**:
OpenLLMetry's integration list is LLM SDKs/frameworks (Bedrock, Anthropic, LangChain, etc.).
Source: https://github.com/traceloop/openllmetry

**Q5, auto-instrumentation packages:**

- **CONFIRMED**: `opentelemetry-instrumentation-botocore` latest is **0.63b1 (2026-05-21)**; its
  Bedrock extension implements GenAI semconv for Converse, ConverseStream, InvokeModel,
  InvokeModelWithResponseStream, with Anthropic Claude support.
  Source: https://pypi.org/project/opentelemetry-instrumentation-botocore/

**Q7, OpenLLMetry status + Datadog support:**

- **CONFIRMED**: OpenLLMetry is standalone and maintained (Apache 2.0); README states its
  semantic conventions are now part of OpenTelemetry; supports Bedrock + Anthropic.
  Source: https://github.com/traceloop/openllmetry
- **CONFIRMED**: ServiceNow acquired Traceloop (OpenLLMetry's maintainer) in **March 2026**
  ($60–80M); OpenLLMetry stays open source. (The spike cited only a third-party blog; the
  acquisition is corroborated by Traceloop's own announcement and CTech.)
  Sources: https://traceloop.com/blog/traceloop-is-joining-servicenow ;
  https://www.calcalistech.com/ctechnews/article/sjghwiqf11e
- **CONFIRMED (with a minor citation correction)**: OpenLLMetry issue #3515 (opened 2025-12-12)
  reports it still emits deprecated `gen_ai.prompt`/`gen_ai.completion` instead of
  `gen_ai.input.messages`/`gen_ai.output.messages`/`gen_ai.system_instructions`. The issue
  references PRs **#3990 and #3948** (the spike said "two linked PRs … resolution not detailed");
  the substantive claim, the deprecated-attribute lag, stands.
  Source: https://github.com/traceloop/openllmetry/issues/3515
- **CONFIRMED**: Datadog LLM Observability natively ingests OTel GenAI semconv **v1.37+** with no
  code changes; maps `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.operation.name`;
  Bedrock supported.
  Source: https://www.datadoghq.com/blog/llm-otel-semantic-convention/

**Cross-cutting, GenAI semconv status + agent span shape:**

- **CONFIRMED**: GenAI semconv is still **Development** (not Stable) as of v1.41; `gen_ai.*`
  attributes carry Development stability and can change without a major bump.
  Source: https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions
- **CONFIRMED (with a doc-location note)**: the GenAI agent-spans spec has **moved** off
  opentelemetry.io to the dedicated `semantic-conventions-genai` repo; the relocated spec defines
  `invoke_agent {gen_ai.agent.name}` and an `execute_tool` span. The opentelemetry.io URL the
  spike cites (source #16) now only redirects; the live spec is at the new repo. The
  `gen_ai.tool.name`/`gen_ai.tool.call.id` attribute names are referenced by the spec but the
  fetched section was truncated, so the exact `execute_tool {gen_ai.tool.name}` span-name format
  is taken as CONFIRMED via research/05 + the parallel `invoke_agent {…}` naming pattern rather
  than a direct quote.
  Sources: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/ (moved) ;
  https://github.com/open-telemetry/semantic-conventions-genai

**UNVERIFIED:** none of the load-bearing external claims failed verification. The two items the
spike already flagged as live-cluster verify-at-build (kagent chart 0.9.9 bundling ADK ≥1.17.0
and honoring `deployment.env`; full `gen_ai.*` enrichment for an agentgateway A2A/JSON-RPC
backend) remain correctly scoped as build-time checks, not doc-verifiable claims.

---

## Validation pass (adversarial, 2026-06-23, re-run for issue updates)

Second re-verification, triggered by Whitney's directive to re-check the time-sensitive claims
(OpenLLMetry status/ownership, agentgateway v1.3.0 fields, ADK version + `EVENT_ONLY` enum) and
to reflect Datadog's current product name (Agent Observability vs LLM Observability). Live
WebSearch/WebFetch against current official sources.

- **Datadog product name (NEW, the substantive change this re-run).** **CONFIRMED that the
  product is now branded "Agent Observability."** The Datadog docs landing page
  (`/llm_observability/`) and the OTel-instrumentation docs page are both titled **"Agent
  Observability"**; the marketing product page is titled **"Agent Observability | LLM
  Observability."** "LLM Observability" is the legacy brand, still used interchangeably (incl.
  the Dec-2025 blog and the unchanged `/llm_observability/` URL roots). Datadog also shipped
  agentic features (AI Agent Monitoring GA at DASH June 2025) and **auto-instrumentation for
  Google ADK** (Feb 2026). The file's Q7 Datadog subsection and the Sources list were updated.
  Sources: https://docs.datadoghq.com/llm_observability/ ;
  https://www.datadoghq.com/products/ai/agent-observability/ ;
  https://www.infoq.com/news/2026/02/datadog-google-llm-observability/
- **OpenLLMetry status/ownership: CONFIRMED, refreshed.** Still standalone, Apache-2.0,
  actively maintained; latest **v0.61.0 (2026-05-31)**, 258 releases, ~7.2k stars; README still
  states "Our semantic conventions are now part of OpenTelemetry"; GitHub org now shows
  **"traceloop from ServiceNow"** (corroborates the March-2026 acquisition). Bedrock + Anthropic
  still in the integration list. Verdict unchanged: do not adopt it for this stack.
  Sources: https://github.com/traceloop/openllmetry ; https://github.com/traceloop
- **agentgateway v1.3.0 fields: CONFIRMED, unchanged.** Tracing is enabled in the config file
  under `frontendPolicies.tracing` with `otlpEndpoint` + `randomSampling`; the docs document
  **no** `OTEL_EXPORTER_OTLP_ENDPOINT` env-var path; GenAI attributes (`gen_ai.operation.name`,
  `gen_ai.request.model`) referenced via the separate LLM-observability section. The repo's
  env-var path remains wrong; the config-file field is the supported activation.
  Source: https://agentgateway.dev/docs/standalone/main/integrations/observability/opentelemetry/
- **ADK version + content-capture enum: CONFIRMED, unchanged + one new detail.** ADK ≥ 1.17.0
  has built-in OTel; with `gen_ai_latest_experimental` the valid value is
  `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT='EVENT_ONLY'`, and `true` "results in an
  invalid configuration … therefore, log and trace data isn't collected." New this pass: the
  doc also recommends `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS='false'` for PII safety (added to Q1).
  Source: https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk
- **botocore instrumentation: CONFIRMED, unchanged.** Latest `opentelemetry-instrumentation-botocore`
  is **0.63b1 (2026-05-21)**; Bedrock Converse/ConverseStream/InvokeModel/InvokeModelWithResponseStream
  GenAI semconv, Anthropic Claude (incl. tool calls for Claude 3+).
  Source: https://pypi.org/project/opentelemetry-instrumentation-botocore/
- **GenAI semconv status: CONFIRMED, unchanged.** Still **Development** (not Stable) as of
  semconv **v1.41** (latest tag v1.41.1, a k8s codegen fix, no GenAI change); `gen_ai.*`
  attributes can change without a major bump. The opentelemetry.io GenAI spec index now shows a
  **"Moved"** notice (spec relocated to the dedicated `semantic-conventions-genai` repo); the
  doc-location note already in the prior validation pass holds.
  Sources: https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions ;
  https://opentelemetry.io/docs/specs/semconv/gen-ai/

**Net change vs prior run:** only the Datadog product-name rebrand (LLM Observability → Agent
Observability) is materially new; every other load-bearing claim re-verified identical. Nothing
refuted this pass. Live-cluster verify-at-build items remain as previously scoped.

---

## Validation pass (adversarial, 2026-06-23, independent re-verification)

Third, fully independent skeptical re-verification by the adversarial validator, focused on the
NEW/CHANGED claims this re-run introduced (Datadog "Agent Observability" rebrand, OpenLLMetry
v0.61.0 + "traceloop from ServiceNow", ADK `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS='false'`,
botocore 0.63b1). Live WebFetch/WebSearch against current official sources. Default posture:
unbacked → UNVERIFIED. One inline overstatement was corrected (see below).

- **Datadog "Agent Observability" rebrand: CONFIRMED.** The docs landing page
  (`/llm_observability/`) carries the H1 **"Agent Observability"**; the marketing product page's
  browser title is **"Agent Observability | LLM Observability."** Both names are used
  interchangeably as the spike states.
  Sources: https://docs.datadoghq.com/llm_observability/ ;
  https://www.datadoghq.com/products/ai/agent-observability/
- **REFUTED (overstatement, corrected inline): the OTel-instrumentation docs page is NOT
  "titled Agent Observability."** That specific page's H1 is **"OpenTelemetry Instrumentation"**;
  its *body* states "Agent Observability supports ingesting OpenTelemetry traces that follow the
  OpenTelemetry 1.37+ semantic conventions for generative AI." The prior pass and Q7/Source #14
  over-claimed the page title. Corrected in Q7's Datadog subsection and Source #14. The
  substantive claim (Datadog natively ingests OTel GenAI semconv v1.37+; Bedrock via
  `opentelemetry-instrumentation-botocore >= 1.31.57`) is CONFIRMED.
  Source: https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/
- **OpenLLMetry v0.61.0 (2026-05-31), 258 releases, ~7.2k stars: CONFIRMED.** README confirms
  "Our semantic conventions are now part of OpenTelemetry"; Bedrock + Anthropic in the
  integration list. The org display name **"traceloop from ServiceNow"** is CONFIRMED on the org
  page header (corroborates the March-2026 acquisition).
  Sources: https://github.com/traceloop/openllmetry ; https://github.com/traceloop
- **ADK PII flag: CONFIRMED.** Google's ADK doc explicitly recommends
  `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS='false'` to keep PII off spans and stay under the
  attribute size limit; ADK 1.17.0+ has built-in OTel; `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`
  valid value is `EVENT_ONLY` and `true` "results in an invalid configuration." All as stated.
  Source: https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk
- **botocore 0.63b1 (2026-05-21): CONFIRMED.** Bedrock Converse/ConverseStream/InvokeModel/
  InvokeModelWithResponseStream GenAI semconv, Anthropic Claude (incl. tool calls for Claude 3+).
  Source: https://pypi.org/project/opentelemetry-instrumentation-botocore/
- **Datadog auto-instrumentation for Google ADK: CONFIRMED.** Corroborated by InfoQ and the
  Google Cloud blog; Datadog auto-instruments ADK agents (no code changes), tracing orchestration
  + tool calls, token/cost per branch. (Minor: the announcement timing reads as
  January to February 2026 across sources; the spike's "Feb 2026" matches the InfoQ article slug,
  not load-bearing.)
  Sources: https://www.infoq.com/news/2026/02/datadog-google-llm-observability/ ;
  https://cloud.google.com/blog/products/management-tools/datadog-integrates-agent-development-kit-or-adk

**UNVERIFIED:** none of the load-bearing external claims failed verification this pass. The two
live-cluster verify-at-build items (kagent chart 0.9.9 bundling ADK ≥1.17.0 and honoring
`deployment.env`; full `gen_ai.*` enrichment for an agentgateway A2A/JSON-RPC backend) remain
correctly scoped as Phase-3 build-time checks, not doc-verifiable.

**Net result this pass:** one overstatement refuted and fixed inline (OTel-instrumentation docs
page H1 is "OpenTelemetry Instrumentation," not "Agent Observability"); all other NEW/CHANGED
claims confirmed against current official sources.
