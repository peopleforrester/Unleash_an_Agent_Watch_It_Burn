<!-- ABOUTME: Research spike on tracing before/after guard-proxy sanitization (original vs sanitized prompt) in one trace. -->
<!-- ABOUTME: Answers Issue #12: manual OTel SDK content capture, before/after in one trace, the EVENT_ONLY env var on manual code, Datadog side-by-side view, and (Q5) whether Datadog's built-in Sensitive Data Scanner applies to manual spans vs Collector-side symmetric redaction for the re-leak trap. -->

# 31. Guard-Proxy Before/After Sanitization Tracing (Issue #12)

## Verification Method

- **Approach:** Deep web research dated **2026-06-23** against current (2026) official primary
  sources: the OpenTelemetry GenAI semantic-conventions spec (now in the dedicated
  `open-telemetry/semantic-conventions-genai` repo), the `opentelemetry-util-genai` PyPI package,
  the OTel GenAI-observability blog, and the Datadog LLM (Agent) Observability docs/blog. Every
  material claim carries an inline source URL; the full list is in **Sources**.
- **Hypothesis-verification stance (Whitney's rule):** the issue's implied "gotchas," chiefly
  "does `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` apply to MANUALLY
  instrumented code," are treated as hypotheses to verify, not facts to repeat. Verdicts are
  **CONFIRMED**, **CONFIRMED-WITH-NUANCE**, **REFUTED**, or **COULD NOT FULLY CONFIRM**.
- **In-repo facts taken as CONFIRMED** (read directly this session):
  `agent/gateway/guard-proxy/proxy.py`: a stdlib `ThreadingHTTPServer` that, on `do_POST`,
  extracts the user prompt text, optionally checks it against a block-list (Stage 1) and an LLM
  Guard `/analyze/prompt` classifier (Stage 2), forwards the **original** request body (`raw`) to
  the kagent agent, and on the response optionally calls LLM Guard `/analyze/output` to produce a
  **sanitized** output (`output_scrub`). `docs/BUILD-SPEC.md` §4: "OTel content capture is itself
  an exfil channel (the re-leak trap), off by default; advanced beat." `PROJECT_STATE.md`: Datadog
  required + primary, OTel neutral, content capture is the re-leak-trap mechanism.
- **Builds on (NOT re-researched):**
  - `research/29-python-ai-instrumentation-2026.md` (Issue #10) established that the guard-proxy
    is stdlib-only with **no OTel today**, **makes no Bedrock/LLM call** (it forwards A2A JSON-RPC to
    the agent; the agent/ADK calls Bedrock), and gave the **manual OTel SDK init + `start_as_current_span`
    + `inject()` context-propagation** pattern for the proxy. This spike inherits that and does NOT
    re-derive the proxy's call graph or the SDK bootstrap.
  - `research/28-datadog-llm-obs-otlp-2026.md` (Issue #9) established native Datadog OTLP ingest of
    `gen_ai.*` (semconv v1.37+, no dd-trace SDK), the `dd-otlp-source=llmobs` routing header, the
    `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` **enum** (`NO_CONTENT`/`SPAN_ONLY`/`EVENT_ONLY`/
    `SPAN_AND_EVENT`) and the `=true`-is-invalid trap **on the ADK path**, and the
    `gen_ai.input.messages`/`gen_ai.output.messages`/`gen_ai.system_instructions` content attributes
    (Opt-In + Development). **Re-run #28 also established the built-in Sensitive Data Scanner (SDS):**
    Agent Observability includes SDS; it scans Agent-Obs traces incl. LLM inputs/outputs; it is NOT on by
    default (managed scanning group auto-created on first Agent-Obs Settings visit); it acts
    **server-side, after ingest**, and is therefore a defense-in-depth backstop, NOT a network-egress
    redactor. This spike (Q5) extends that to the precise re-leak-trap question: does SDS apply to the
    **manually instrumented** proxy span, or is **Collector-side symmetric redaction** still the right path.
  - `research/05-otel-genai-observability.md`: semconv all `Development`; content capture off by
    default; the re-leak trap.

### Cross-cutting frame the answers depend on

The proxy is **not an LLM client** and **not an ADK runtime**. So neither ADK's built-in GenAI
instrumentation nor `opentelemetry-instrumentation-botocore` applies here (per `research/29` Q3/Q5).
Capturing the original-vs-sanitized prompt at the proxy is **hand-written manual instrumentation**
against `opentelemetry-api`/`-sdk`. Every "does the GenAI env var / semconv apply" question therefore
turns on a single distinction the issue is right to probe: **the OTel GenAI semconv defines the
attribute *names and shapes*; it does NOT define runtime behavior for code you write by hand.** The
content-capture *switch* lives in *instrumentation libraries*, not in the SDK or the spec.

---

## TL;DR per question

| # | Question | Verdict |
|---|---|---|
| 1 | Which SDK call captures prompt text (attribute, event, or other); what does semconv say is correct for MANUAL code | **CONFIRMED.** `span.set_attribute(...)` or `span.add_event(...)`; semconv prefers **events** for structured content, allows JSON-string on span attributes; `gen_ai.input.messages`/`gen_ai.output.messages` are the canonical names, Opt-In |
| 2 | Capture original + sanitized in ONE trace (same span / parent-child / siblings) | **CONFIRMED.** Feasible all three ways; **recommended = two attributes on ONE span** (`gen_ai.input.messages` = sanitized, a custom `witb.input.messages.original` = pre-sanitization), because Datadog renders one Input/Output pair per span |
| 3 | Does `...CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` apply to MANUAL code? If manual, how to toggle capture | **REFUTED (as stated) / CONFIRMED-WITH-NUANCE.** The env var is **library-specific** (`opentelemetry-util-genai` / contrib instrumentations). Raw hand-written SDK code does **NOT** read it automatically; you must read it yourself or honor it via `opentelemetry-util-genai`'s `TelemetryHandler` |
| 4 | How does before/after appear in Datadog LLM Obs (side-by-side) | **CONFIRMED-WITH-NUANCE.** Per-span Input vs Output panel is the side-by-side; before/after across two values needs a deliberate layout (one span, two attributes, or two spans in the waterfall) |
| 5 | Datadog-side requirements to surface prompt text from manual spans | **CONFIRMED.** `dd-otlp-source=llmobs` routing, `gen_ai.operation.name` to classify span kind=`llm`, content in `gen_ai.input/output.messages` (or the `gen_ai.client.inference.operation.details` event); semconv v1.37+ |
| 5b | **Does Datadog's built-in Sensitive Data Scanner (SDS) redact MANUALLY instrumented spans, or is Collector-side symmetric redaction still right for the re-leak trap?** | **CONFIRMED. SDS *does* apply to manual spans (it scans by content/regex, instrumentation-agnostic), BUT it acts SERVER-SIDE AFTER INGEST**, so it CANNOT keep the "before" secret off the wire / out of Datadog. For the re-leak trap we deliberately want the *before* text in the trace then confirm sanitization. **Collector-side symmetric redaction is still the right narrative path** (it can show before, redact at the egress hop, and SDS is the defense-in-depth backstop in the UI). Datadog **SDK span processors do NOT apply to the OTLP-ingested proxy span**, so SDS is the only Datadog-*native* redaction for this path |

---

## Q1. Which Python OTel SDK call captures prompt text in a span (attribute, span event, or other)? What does OTel GenAI semconv say is correct for MANUALLY instrumented code?

**The SDK gives you exactly two primitives, and the GenAI semconv has a stated preference between
them.**

**The two SDK calls (this is all the SDK offers for content):**
- **Span attribute:** `span.set_attribute("gen_ai.input.messages", value)`, a key/value on the span
  itself.
- **Span event:** `span.add_event("gen_ai.client.inference.operation.details", attributes={...})`,
  a timestamped structured record attached to the span (events are the spec's preferred carrier for
  structured content; see below). (There is no third "content" primitive; logs via the Logs Bridge are
  the other option but for the GenAI flow the spec routes structured content through span **events**.)
  Source (SDK conventions: `start_as_current_span`, `set_attribute`, `add_event`):
  in-repo `rules/tools/opentelemetry.md`.

**What the GenAI semconv says is correct (this is the load-bearing part):**

1. **Content is OFF by default and must be opt-in, even for your own code.** The spec is explicit:
   "OpenTelemetry instrumentations **SHOULD NOT capture them by default, but SHOULD provide an option
   for users to opt in**." Instructions/inputs/outputs are "likely to be large," "may contain media,"
   and "are likely to contain sensitive information including user/PII data." This is the same
   off-by-default property `research/05` and BUILD-SPEC §4 call the re-leak trap, and it is a
   *recommendation to the instrumentation author*, i.e. **to you**, when you hand-write the proxy spans.
   Source: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md
2. **The canonical attribute names** for chat content are `gen_ai.input.messages`,
   `gen_ai.output.messages`, and `gen_ai.system_instructions`. All three are **`Opt-In`** requirement
   level and **`Development`** stability. They are NOT the older `gen_ai.prompt`/`gen_ai.completion`
   (removed; the OpenLLMetry deprecated-attribute lag in `research/29` Q7 is exactly this) and NOT the
   event-only `gen_ai.content.prompt`/`gen_ai.content.completion` (older experimental events).
   Source: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md
3. **Preferred carrier: events, with a span-attribute fallback.** The spec says "**Recording
   structured attributes is supported on events (or logs) and may not yet be supported on spans**,"
   and that "If structured attributes are not yet supported on spans in a given language, the
   corresponding attribute value **SHOULD be serialized to JSON string on spans** and recorded in its
   structured form on events." Practical reading for Python: the OTel Python SDK does **not** support
   nested/structured attribute values on spans (span attribute values must be primitives or sequences
   of one primitive type), so the message array must be **JSON-serialized to a string** if put on a
   span attribute; the structured form belongs on a span **event**. So the semconv-correct manual
   pattern is: put the structured messages on a `gen_ai.client.inference.operation.details` **event**,
   and/or a JSON string on the `gen_ai.input.messages` span **attribute**.
   Source: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md
4. **The message JSON schema** (so the attribute/event is valid): an array of objects with
   `role` ("user"/"assistant"/"tool"/"system"), `parts` (array; each part has a `type` of
   "text"/"tool_call"/"tool_call_response" plus `content`), and `finish_reason` on output messages.
   "Instrumentations MUST follow [Input messages JSON schema]." For the proxy's prompt text the minimal
   valid value is `[{"role":"user","parts":[{"type":"text","content":"<the prompt>"}]}]`.
   Source: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md

**Reconciling "attribute vs event" for THIS workshop:** the semantic answer is "events preferred,
JSON-string-on-attribute acceptable." The **Datadog** answer (Q4/Q5) is that it reads **both**:
`gen_ai.input.messages`/`gen_ai.output.messages` attributes **OR** the
`gen_ai.client.inference.operation.details` span event, so either carrier surfaces the text in
LLM Observability. For the demo, the span **attribute** (JSON string) is the simpler, sufficient choice;
the **event** is the more spec-pure choice and is what the re-leak-trap framing (`EVENT_ONLY`) points to.

**Confidence: HIGH** on the names, opt-in/off-by-default property, the event-preferred/attribute-fallback
rule, and the JSON schema (all quoted from the canonical spec).

---

## Q2. How to capture original (pre-sanitization) AND sanitized (post-sanitization) text in ONE trace: same span, parent/child, or sibling spans?

**All three are technically possible; the recommended shape is TWO ATTRIBUTES (or two events) on ONE
span, with a custom name for the "original."** Reasoning is driven by how the proxy actually works and
by how Datadog renders a span.

**What the proxy actually has (from `proxy.py`, CONFIRMED):** in a single `do_POST` the proxy holds, in
one stack frame, BOTH the original prompt `text` (extracted before any guard runs) and, when the input
classifier or block-list fires, the verdict; and on the response path it holds BOTH the raw agent
`text` and the `output_scrub`-produced sanitized text. So all four values (original-in, sanitized/blocked-in,
original-out, sanitized-out) are available within one request handler, i.e. one span's lifetime. There is no
need to span boundaries to "carry" the before value; it is local.

**Option A: ONE span, two attributes (RECOMMENDED).** On the proxy's request/forward span, set:
- `gen_ai.input.messages` = the **sanitized/forwarded** prompt (the semconv-canonical "what actually
  went to the model"), and
- a **custom** attribute, e.g. `witb.input.messages.original` (JSON string), = the **pre-sanitization**
  prompt, plus `witb.input.sanitized` (bool) / `witb.input.blocklist_hit` / `witb.input.classifier_verdict`.

  Why recommended: it keeps before+after on the SAME span the attendee clicks, and it is unambiguous which
  is canonical. The semconv has **no standard attribute for "the original, pre-sanitization input"**
  (there is one input-messages slot), so the "before" value MUST be a custom (`witb.*`) attribute or a
  custom event; do not overload `gen_ai.input.messages` with both. (This mirrors `research/29`'s rule that
  `witb.*` are the repo's own namespace; here they carry the before/after delta the GenAI semconv does not
  model.)

**Option B: ONE span, two events.** Add two `add_event(...)` calls on the proxy span: one event
`witb.input.original` and one `gen_ai.client.inference.operation.details` (or `witb.input.sanitized`)
carrying the structured message. Events are timestamped, so they also encode ordering (original captured
first, sanitized after the guard). This is the most semconv-pure (structured content on events) and is
what the `EVENT_ONLY` capture mode (Q3) conceptually targets. Trade-off: Datadog surfaces the canonical
input from the FIRST recognized source; a second custom event renders as a span event, not as a second
Input panel.

**Option C: parent + child spans (or siblings).** Wrap the guard decision in a child span
(`guard_proxy.sanitize_input`) carrying the before/after, nested under the proxy's request span; the
forward-to-agent is a sibling/child CLIENT span (the one `research/29` Q6 already defines, with `inject()`
so the agent's `gen_ai.*` spans nest under it). This gives the cleanest waterfall story for a stage talk
("here's the sanitize step, here's the forward, here's the model") and naturally puts the **original** on
the sanitize span and the **sanitized** on the forward span. Trade-off: more spans, more code on a
deliberately-minimal stdlib proxy; before/after are then on DIFFERENT spans (the attendee compares by
clicking two spans, not one panel).

**They are ALL "one trace."** A single trace is defined by one trace context; whichever option you pick,
as long as it happens inside the same request (and the forward uses `inject()` to keep the agent in the
same trace), every span and event lives under one trace id. `research/29` Q6 already supplies the
propagation step that makes the proxy span and the agent's `gen_ai.*` spans share a trace.

**Recommendation for the workshop:** **Option A** (one span, `gen_ai.input.messages` = sanitized +
`witb.input.messages.original` = original) for the *clean* before/after lesson, OPTIONALLY promoted to
**Option C** (a dedicated `sanitize_input` child span) if the on-stage waterfall narration wants a visible
"sanitize" step. Avoid putting two competing values in the standard `gen_ai.input.messages` slot.

**Confidence: HIGH** that all three work and are one-trace; **HIGH** that the semconv has no standard
"original/pre-sanitization" attribute (so the before value must be custom). The choice between A/C is a
demo-design call, not a correctness one.

---

## Q3. Does `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` apply to MANUALLY instrumented code, or only auto-instrumentation? (VERIFY; do not assume.) If manual, how to conditionally enable/disable content capture?

**VERDICT: the env var does NOT apply to raw hand-written OTel SDK code automatically. It is a
*library* setting read by `opentelemetry-util-genai` and the GenAI contrib instrumentations, NOT by
`opentelemetry-api`/`opentelemetry-sdk`.** The hypothesis "this env var governs my manual proxy spans"
is **REFUTED as stated**, **CONFIRMED-WITH-NUANCE** for "if you route through `opentelemetry-util-genai`."

**Evidence:**

1. **The variable is explicitly library-specific.** `opentelemetry-util-genai`'s own docs:
   "This package relies on environment variables to configure capturing of message content, and by
   default, message content will not be captured." [CORRECTED 2026-06-23: the previously quoted phrase
   "only affects applications using this package's instrumentation capabilities, not the base SDK itself"
   is NOT verbatim on the current PyPI page; it does not contain that sentence. The substance still
   holds: capture is controlled by *this package* via the env var, and the GenAI **spec does not define
   the env var at all** (verified; see #2 and the validation pass). The env var is therefore a
   convention of the GenAI instrumentation libraries, NOT a base-SDK feature.] So a `span.set_attribute(...)`
   you write by hand is **unaffected** by the env var: the SDK does not consult it, will not gate your
   attribute, and will not strip it.
   Source: https://pypi.org/project/opentelemetry-util-genai/
2. **The GenAI *spec* does not define this env var at all.** The semconv text says instrumentations
   SHOULD provide an opt-in option and MAY provide truncation, but it "**does not reference
   `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` or define specific enum values**"; it describes
   the three usage patterns (don't record / record on attributes / store externally) and leaves the
   *mechanism* to instrumentations. So the env var is a convention of the Python GenAI instrumentation
   ecosystem, not a spec-mandated SDK switch.
   Source: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md
3. **It is the same flag the contrib/ADK instrumentations honor.** `research/28`/`research/29`
   established that on the **ADK path** the valid value is `EVENT_ONLY` and `=true` is an invalid config
   that silently collects nothing. That behavior is real **for ADK and `opentelemetry-util-genai`-backed
   instrumentations**, which is precisely why it does NOT transfer to the stdlib proxy: the proxy uses
   none of those.
   Sources: https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk ;
   https://pypi.org/project/opentelemetry-util-genai/
4. **The enum + the companion `OTEL_INSTRUMENTATION_GENAI_EMIT_EVENT` are library config, not SDK
   behavior.** `opentelemetry-util-genai` defines `NO_CONTENT` (default) / `SPAN_ONLY` / `EVENT_ONLY` /
   `SPAN_AND_EVENT`, plus `OTEL_INSTRUMENTATION_GENAI_EMIT_EVENT` (defaults false for `NO_CONTENT`/
   `SPAN_ONLY`, true for `EVENT_ONLY`/`SPAN_AND_EVENT`). These only have effect *inside* that library's
   `TelemetryHandler`.
   Source: https://pypi.org/project/opentelemetry-util-genai/

**So, for manual code, how do you conditionally enable/disable content capture? Two clean options:**

- **Option 1: honor the convention yourself (recommended; cheapest, fits the stdlib proxy).** Read the
  same env var in the proxy and gate your own `set_attribute`/`add_event`. This makes the proxy behave
  like a well-behaved instrumentation and keeps the re-leak-trap toggle consistent with the rest of the
  stack:

  ```python
  import os
  _CAPTURE = os.environ.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "NO_CONTENT").upper()
  _CAPTURE_SPAN  = _CAPTURE in ("SPAN_ONLY", "SPAN_AND_EVENT")
  _CAPTURE_EVENT = _CAPTURE in ("EVENT_ONLY", "SPAN_AND_EVENT")
  # ... inside the span:
  if _CAPTURE_SPAN:
      span.set_attribute("gen_ai.input.messages", json.dumps(sanitized_messages))
      span.set_attribute("witb.input.messages.original", json.dumps(original_messages))
  if _CAPTURE_EVENT:
      span.add_event("gen_ai.client.inference.operation.details",
                     {"gen_ai.input.messages": json.dumps(sanitized_messages)})
  ```

  Default `NO_CONTENT` keeps the proxy SAFE (matches BUILD-SPEC §4 "off by default"); flip to
  `EVENT_ONLY` (or `SPAN_ONLY`) only for the deliberate re-leak-trap beat. NOTE: a plain `=true` would NOT
  match any branch above, which is *good*: it preserves the same "`=true` is wrong, use the enum"
  discipline the ADK path enforces. (This is research only; do NOT edit `proxy.py`.)
- **Option 2: use `opentelemetry-util-genai`'s `TelemetryHandler`.** Instrument the proxy via that
  library's manual API (it "offers APIs to minimize instrumentation work for GenAI libraries, providing a
  TelemetryHandler to manage LLM invocation lifecycles with spans, metrics, and events, along with
  structured message types"). Then the env var DOES govern capture for free. Trade-off: adds a
  `0.4b0`-beta dependency (released 2026-05-01) to a deliberately stdlib-only proxy, and its model is
  "an LLM invocation lifecycle," which the proxy is *not* (it forwards A2A; per `research/29` Q3 it makes
  no model call). So `TelemetryHandler` is a semantic mismatch for the proxy; Option 1 is the better fit.
  Source: https://pypi.org/project/opentelemetry-util-genai/

**Confidence: HIGH** (verified directly: the env var is library-scoped and the SDK ignores it; the spec
does not define it). This is the spike's most important correction: it would be wrong to set
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` on the proxy Deployment and expect the
hand-written spans to start/stop capturing; they won't, unless the code reads it (Option 1) or uses
`opentelemetry-util-genai` (Option 2).

---

## Q4. How does before/after prompt content appear in Datadog LLM Observability, a side-by-side view?

**CONFIRMED-WITH-NUANCE. Datadog's per-span "Input vs Output" is the side-by-side; getting
*original-vs-sanitized* side by side is a layout choice you make with the Q2 options, not an automatic
"diff" feature.**

**What Datadog renders, confirmed:**
- A trace is a **waterfall of spans**; "a given trace can also include input and output, latency, privacy
  issues, errors, and more," and you "drill into a trace to see … which prompts it has sent … and how the
  model replied, **all in one view**," "viewing each step of the agent's logic **side by side with the
  input and output data**."
  Sources: https://docs.datadoghq.com/llm_observability/terms/ ;
  https://www.datadoghq.com/blog/datadog-llm-observability/ ;
  https://www.datadoghq.com/blog/openai-agents-llm-observability/
- Each span has an **Input** and an **Output** field. For an LLM span, Datadog maps
  `gen_ai.input.messages` → the span's **input messages** and `gen_ai.output.messages` → the span's
  **output messages** (see Q5). So the native "side-by-side" is **Input panel vs Output panel for one
  span**, i.e. *prompt vs completion*, not *before vs after sanitization*.
  Source: https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/

**How before/after actually lands, per the Q2 option you choose:**
- **Option A (one span, two attributes):** the span's **Input** panel shows the canonical
  `gen_ai.input.messages` (sanitized). The **original** lives in the custom `witb.input.messages.original`
  metadata, surfaced under `@meta.metadata.*` (Datadog maps custom attributes to `meta.metadata.<key>`),
  visible in the span's metadata/tags pane, adjacent to, but not in, the Input panel. The attendee sees
  sanitized as the Input and original as a tagged value on the same span. Good enough for the lesson;
  it is "one click, both values," not a literal two-column diff.
  Source (custom attrs → `@meta.metadata.<key>`): https://docs.datadoghq.com/llm_observability/monitoring/querying/
- **Option C (sanitize child span + forward span):** the cleanest *visual* before/after. The
  `sanitize_input` span's Input/Output shows original→sanitized, and the forward/model spans below show
  the sanitized prompt flowing to the model. The attendee scrubs DOWN the waterfall and watches the text
  change at the guard step. This is the most "demo-legible" before/after in Datadog, at the cost of more
  spans. (If the sanitize span sets `gen_ai.input.messages`=original and `gen_ai.output.messages`=sanitized,
  Datadog's own Input-vs-Output side-by-side on that one span literally shows before vs after.)
- **The agent's own span** (ADK, `research/28`/`research/29`) will independently show the prompt it
  received, which is the **sanitized** one (the proxy forwards the request; output scrubbing happens on
  the way back). So the trace already encodes "model only ever saw the sanitized input," reinforcing the
  lesson without extra work.

**There is no built-in "compare two spans' content" diff widget documented.** The before/after contrast is
produced by deliberate span/attribute layout (Q2), then read off the waterfall + side panels. Treat the
exact UI affordance (do two `gen_ai.input/output.messages` on one span render as a true two-pane diff) as a
**verify-at-build** item to confirm live in the Datadog LLM Observability UI on a cluster emitting these
spans. The docs confirm per-span Input/Output rendering but not a pixel-level before/after layout.

**Confidence: HIGH** that per-span Input-vs-Output is the side-by-side and that custom attrs surface as
`@meta.metadata.*`; **MEDIUM** on the exact rendered appearance of an original-vs-sanitized layout (UI
detail, verify live).

---

## Q5. Datadog-side requirements to surface prompt text from manually instrumented spans, AND does the built-in Sensitive Data Scanner redact those manual spans, or is Collector-side symmetric redaction still the right path for the re-leak trap?

**Two parts.** Part A (surfacing the text) is **CONFIRMED: three concrete requirements, no
org feature-flag/plan gate.** Part B (Whitney's #12 update: SDS vs Collector-side redaction for the
re-leak trap) is **CONFIRMED with a definite verdict: SDS applies to the manual span's
*content* but only server-side after ingest, so Collector-side symmetric redaction remains the right
path for the re-leak trap.** (Confirms and extends `research/28` Q7 + the SDS finding.)

### Part A: surfacing prompt text from a manual span (unchanged from prior run)

1. **Routing header `dd-otlp-source=llmobs`** (or the Collector/Agent equivalent). Direct OTLP intake
   needs `OTEL_EXPORTER_OTLP_TRACES_HEADERS=dd-api-key=<KEY>,dd-otlp-source=llmobs` over
   `http/protobuf`. This header is what routes a span into **LLM (Agent) Observability** rather than plain
   APM. For THIS stack the spans go through the contrib `datadog` exporter in the Collector. `research/28`
   Q7 flags that the Collector→LLM-Obs routing is the one under-documented seam (verify live; fall back to
   a dedicated OTLP exporter with the `dd-otlp-source=llmobs` header). That gap is unchanged here.
   Sources: https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ ;
   https://www.datadoghq.com/blog/llm-otel-semantic-convention/
2. **`gen_ai.operation.name` to classify the span kind.** Datadog uses `gen_ai.operation.name` to
   determine the Agent Observability `span.kind`; values `generate_content`, `chat`, `text_completion`,
   `completion` resolve to **`span.kind = llm`** (the kind whose Input/Output renders as messages).
   [CORRECTED 2026-06-23: the current Datadog otel_instrumentation doc lists `generate_content, chat,
   text_completion, completion` for `llm`; the earlier example value `chat_completion` is NOT in that
   list. Use one of the documented values.] For the proxy's
   forward/sanitize span to be treated as an LLM-kind span (and thus show the prompt as input messages),
   set `gen_ai.operation.name` accordingly. If you leave it as a generic proxy span, the content maps to
   the non-LLM input/output value form instead (see #3). **OTel `SpanKind` (CLIENT/SERVER/INTERNAL) is
   NOT the same thing.** Datadog's LLM `span.kind` is driven by `gen_ai.operation.name`, not by the OTel
   span kind; set both deliberately.
   Source: https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/
3. **Content attribute names (and the event fallback).** Datadog extracts Input/Output **in priority
   order**: (1) the **attributes** `gen_ai.input.messages` / `gen_ai.output.messages`; then (2) a **span
   event** named **`gen_ai.client.inference.operation.details`**. It maps
   `gen_ai.input.messages` → `meta.input.messages` (LLM spans) or `meta.input.value` (other span kinds),
   and `gen_ai.output.messages` → `meta.output.messages` / `meta.output.value`. `gen_ai.system_instructions`
   is also read. So either carrier (attribute JSON, or the event) surfaces the text, which is exactly why
   the Q1/Q3 `SPAN_ONLY` vs `EVENT_ONLY` choice both work in Datadog.
   Source: https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/
4. **Semconv version + opt-in.** Datadog's native mapping requires **OTel GenAI semconv v1.37+**; older
   emitters must set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` (per `research/28` Q1/Q3).
   For hand-written proxy spans this matters only insofar as you emit the v1.37 attribute *names*
   (`gen_ai.input.messages`, not `gen_ai.prompt`). There is no instrumentation library to "opt in," so
   just use the current names. **Supported site:** commercial Datadog sites only; GovCloud
   (`app.ddog-gov.com`, `us2.ddog-gov.com`) is unsupported for LLM Observability (the repo default
   `DD_SITE=datadoghq.com` is fine).
   Sources: https://www.datadoghq.com/blog/llm-otel-semantic-convention/ ;
   https://docs.datadoghq.com/llm_observability/instrumentation/
5. **No org feature flag / plan toggle is documented** beyond a supported site + API key + the routing
   header (confirmed `research/28` Q7). Custom `witb.*` before/after attributes surface as
   `@meta.metadata.<key>` automatically, no Datadog-side registration needed.
   Source: https://docs.datadoghq.com/llm_observability/monitoring/querying/

**Net for Part A:** to make the manually-captured prompt show up as the span's Input in LLM Obs, the
proxy's content span must (a) reach LLM Obs via `dd-otlp-source=llmobs` routing, (b) carry
`gen_ai.operation.name` so it classifies as an `llm` span, and (c) put the messages in
`gen_ai.input.messages`/`gen_ai.output.messages` (JSON) or the
`gen_ai.client.inference.operation.details` event, with capture gated by the Q3 toggle (default
`NO_CONTENT`).

### Part B: built-in Sensitive Data Scanner vs Collector-side symmetric redaction (Whitney's #12 update)

**The question:** Datadog's Agent Observability includes a built-in **Sensitive Data Scanner (SDS)**
for PII redaction. Does that built-in redaction apply to the **manually instrumented** guard-proxy spans,
OR is **Collector-side symmetric redaction** still the right path for the re-leak trap, where we
deliberately need the *before* text (containing the secret) to appear in the trace for the narrative,
then confirm it was sanitized?

**Verdict: three findings, in the order that decides the demo:**

**B1. SDS DOES apply to manually instrumented spans; it scans by content/pattern, not by
instrumentation method.** SDS for Agent Observability "can scan Agent Observability traces, **including
inputs and outputs from LLM applications**," and matches via **scanning rules**: a predefined library
(emails, credit-card numbers, **API keys, authorization tokens**, network/device info) plus **custom
regex rules**. Nothing in the SDS model keys off *how* the span was produced; it inspects the span's
`gen_ai.input.messages` / `gen_ai.output.messages` / metadata **content** once that content is in the
Agent-Obs dataset. So a secret the proxy puts in `gen_ai.input.messages` (or in the custom
`witb.input.messages.original` attribute) via hand-written `set_attribute` is **just as scannable** as
one emitted by the Datadog SDK or ADK. There is **no "manual spans are exempt"** clause. So the literal
answer to "does the built-in redaction apply to manually instrumented spans" is **YES**, by content.
Available actions for Agent-Obs: **Redact** (replace with a chosen token, e.g. `[sensitive_data]`),
**Partially redact**, **Hash** (Mask is logs-only, not available for Agent-Obs traces).
Sources: https://docs.datadoghq.com/security/sensitive_data_scanner/ ;
https://docs.datadoghq.com/security/sensitive_data_scanner/scanning_rules/

**B2. BUT SDS acts SERVER-SIDE, AFTER the span reaches Datadog; it cannot keep the "before" secret off
the wire.** SDS for Agent Observability "uses a **managed configuration model**"; the managed scanning
group "is automatically created for your organization **when you first access the Agent Observability
Settings page**," and you "cannot create additional scanning groups or delete the managed group." SDS is a
**Datadog platform-side** scanner that operates on telemetry **once it is in Datadog** (it classifies/
redacts before events are *indexed*, i.e. on the ingest side of the Datadog boundary, after the span has
left your network). [CORRECTED 2026-06-23: the SDS doc does not state verbatim that Agent-Obs scanning is
"after ingest"; it states telemetry is "redacted before events are indexed" and is silent on the exact
Agent-Obs timing. The server-side-of-the-network-boundary characterization is sound (SDS is a managed
Datadog-side feature, not a network-egress redactor) but is treated as CONFIRMED-WITH-NUANCE, not
verbatim.] Datadog's data-security stance draws the line explicitly: the **OTel Collector** is what lets
teams "preserve governance" and redact "**before telemetry data leaves your network**," whereas SDS is
framed in the Agent-Obs data-security doc as "**an additional layer of security**" alongside
application-level span processors and RBAC. So SDS will redact the secret **in the Datadog UI / stored
data**, but the raw secret has **already traversed the network and been ingested** by the time SDS runs.
For a secret-exfil lesson, that is the wrong side of the boundary: the secret leaves the cluster regardless.
[CORRECTED 2026-06-23: the "before telemetry data leaves your network" phrasing is Datadog's
OTel/Collector governance framing (Datadog OTel-for-LLM-Obs material), NOT the `data_security_and_rbac`
doc. That doc does not mention the Collector or that phrase. The `data_security_and_rbac` doc supplies
the "additional layer of security" framing and the span-processor "before it is sent to Datadog" wording.]
Sources: https://docs.datadoghq.com/security/sensitive_data_scanner/ ;
https://docs.datadoghq.com/llm_observability/data_security_and_rbac/ (additional-layer + span-processor framing) ;
https://www.datadoghq.com/blog/llm-otel-semantic-convention/ (Collector "before telemetry data leaves your network" governance framing)

**B3. Datadog SDK "span processors," the pre-egress, in-app redactor, do NOT exist on the OTLP path
the proxy uses.** Datadog documents a second redaction mechanism: **span processors** that "redact or
modify sensitive data **at the application level before it is sent to Datadog**" and can "conditionally
modify input and output data on spans, or prevent spans from being emitted entirely." This is the
pre-egress option, but it is a feature of the **Datadog Agent Observability SDK** (the Python `ddtrace`
`LLMObs` SDK; `def redact_processor(span: LLMObsSpan) -> LLMObsSpan`). The proxy is **not** instrumented
with the Datadog SDK; per `research/28`/`research/29` it emits **OTLP** `gen_ai.*` spans with no
`dd-trace`. The Datadog SDK reference documents span processors **only** in the `ddtrace`/`LLMObs`
context; there is **no documented span-processor hook for OTLP-ingested spans**. So the in-app,
pre-egress Datadog redactor is **unavailable** for the hand-written proxy span, leaving SDS (post-ingest)
as the only *Datadog-native* redaction for this path.
Sources: https://docs.datadoghq.com/llm_observability/data_security_and_rbac/ ;
https://docs.datadoghq.com/llm_observability/instrumentation/sdk/

**Therefore, for the re-leak trap specifically: Collector-side symmetric redaction is still the right
path.** The re-leak-trap narrative needs three things in sequence: (1) the **before** text, the prompt
*containing the secret*, to appear in the trace so the audience sees the leak; (2) a redaction step the
audience can point at; (3) confirmation the secret was sanitized **before it leaves the boundary**.
- **SDS cannot satisfy (3) at the network boundary:** it redacts post-ingest, so the secret has already
  left the cluster and reached Datadog. SDS also can't show a clean "before → after at THIS hop" moment
  in a trace; it changes what the *stored* value renders as, not what crosses the wire.
- **The OTel Collector CAN** do symmetric, deterministic redaction at the egress hop, "**before telemetry
  data leaves your network**" (Datadog's own OTel/Collector governance framing), via the contrib
  **redaction processor** (delete/mask attributes by
  allow/block list) or the **transform processor (OTTL)** for fine-grained / partial redaction of a
  specific attribute value. This is exactly the `research/12` symmetric-redaction mechanism, and it sits
  on the **same Collector** the stack already runs (`research/28`). It is also where the demo can keep the
  *before* value visible (e.g. the proxy emits `witb.input.messages.original` with the secret; the
  Collector redacts it on export, or routes the un-redacted copy only to a local/Tempo sink while the
  Datadog export is scrubbed) and then show the sanitized `gen_ai.input.messages` going onward.
- **SDS is the defense-in-depth backstop, narrated as "even if a secret slips past the Collector, the
  platform catches and redacts it in the UI"**: a real second layer, but explicitly *after* the
  network boundary, not a replacement for the egress redaction.
Sources: https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/redactionprocessor/README.md ;
https://opentelemetry.io/docs/security/handling-sensitive-data/ ;
https://docs.datadoghq.com/llm_observability/data_security_and_rbac/

**Net for Part B (the answer to Whitney's #12 update):** Datadog's built-in SDS **does** apply to
manually instrumented spans (it scans by content, instrumentation-agnostic) and is a real,
configurable redaction layer, but it runs **server-side after ingest**, and the Datadog **SDK span
processors** (the pre-egress in-app redactor) are **not available on the OTLP path** the proxy uses. For
the re-leak trap, where the *before* text must appear in the trace and then be confirmed sanitized at
the network boundary, **Collector-side symmetric redaction remains the correct path**; SDS is the
post-ingest defense-in-depth backstop, not a substitute. (This research only; do NOT edit `proxy.py`,
the Collector config, or any manifest.)

**Net for the proxy:** to make the manually-captured prompt show up as the span's Input in LLM Obs, the
proxy's content span must (a) reach LLM Obs via `dd-otlp-source=llmobs` routing, (b) carry
`gen_ai.operation.name` so it classifies as an `llm` span, and (c) put the messages in
`gen_ai.input.messages`/`gen_ai.output.messages` (JSON) or the
`gen_ai.client.inference.operation.details` event, with capture gated by the Q3 toggle (default
`NO_CONTENT`); and (d) any deliberate-leak redaction for the re-leak trap is done **Collector-side**
(redaction/transform processor) at the egress hop, with **SDS** as the post-ingest backstop in the UI.

**Confidence: HIGH** on attribute names, the operation-name→span-kind classification, the event fallback,
the routing header, and the no-org-gate finding; **HIGH** that SDS scans by content (so applies to manual
spans), acts server-side post-ingest, and that the Datadog SDK span processors are SDK-only (not on the
OTLP path) → Collector-side redaction is the correct re-leak-trap path; **MEDIUM** only on the
Collector→LLM-Obs routing seam (inherited open item from `research/28` Q7) and on whether the contrib
`datadog` exporter preserves a Collector OTTL redaction before the LLM-Obs hop (verify live).

---

## Recommended approach (synthesis; research only, do NOT implement here)

1. **Keep the proxy SAFE by default.** Default `NO_CONTENT`; the before/after capture is the deliberate
   re-leak-trap beat (BUILD-SPEC §4), flipped on for that segment only.
2. **One span, two attributes (Q2 Option A) for the clean lesson:** `gen_ai.input.messages` = sanitized,
   `witb.input.messages.original` = original, plus `witb.input.sanitized`/`witb.input.blocklist_hit`.
   Optionally promote to a dedicated `sanitize_input` child span (Q2 Option C) if the on-stage waterfall
   wants a visible sanitize step (then that span's own Input-vs-Output is the literal before/after).
3. **Gate capture by reading the env var yourself (Q3 Option 1).** Do NOT expect
   `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` to govern hand-written spans automatically.
   Honor the enum; treat `=true` as "no capture" (matching the ADK trap discipline).
4. **Set `gen_ai.operation.name`** on the content span so Datadog classifies it as `llm` and renders the
   text as messages (Q5 Part A).
5. **Inherit the propagation + SDK bootstrap from `research/29` Q6** (`inject()` so the agent's `gen_ai.*`
   spans share the trace).
6. **For the re-leak-trap redaction, use the OTel Collector (redaction / transform-OTTL processor) at the
   egress hop, NOT Datadog SDS as the boundary redactor** (Q5 Part B). SDS *does* scan manual spans by
   content, but only **server-side after ingest** (secret already left the network), and the Datadog SDK
   **span processors** (the in-app pre-egress redactor) are **not available on the OTLP path** the proxy
   uses. Keep SDS configured as the post-ingest defense-in-depth backstop ("the platform also caught it").
7. **Verify-at-build, live in the Datadog UI:** (a) Collector→LLM-Obs routing of these spans
   (`research/28` Q7 gap); (b) that the original-vs-sanitized layout reads as intended in the trace panel;
   (c) that custom `witb.input.messages.original` surfaces under `@meta.metadata.*`; (d) that a Collector
   redaction/OTTL transform on the `witb.*`/`gen_ai.input.messages` value survives the contrib `datadog`
   exporter hop into LLM-Obs (i.e. the redaction lands before LLM-Obs ingest), and that SDS then redacts
   any residual secret in the Agent-Obs UI.

---

## Sources (distinct citations)

1. https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md: canonical GenAI spans spec: `gen_ai.input.messages`/`output.messages`/`system_instructions` (Opt-In, Development); "SHOULD NOT capture by default, but SHOULD provide an option to opt in"; structured content preferred on events, JSON-string fallback on span attributes; three usage patterns; message JSON schema; spec does NOT define the capture env var/enum.
2. https://pypi.org/project/opentelemetry-util-genai/: the capture env var is **library-specific**, "only affects applications using this package … not the base SDK"; enum `NO_CONTENT`/`SPAN_ONLY`/`EVENT_ONLY`/`SPAN_AND_EVENT` (default `NO_CONTENT`); `OTEL_INSTRUMENTATION_GENAI_EMIT_EVENT`; `TelemetryHandler` manual API; v0.4b0, released 2026-05-01.
3. https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/: Datadog input/output extraction priority (attributes then `gen_ai.client.inference.operation.details` event); `gen_ai.input.messages`→`meta.input.messages`/`meta.input.value`; `gen_ai.operation.name`→Agent-Obs `span.kind` (`chat`/`chat_completion`/`text_completion`→`llm`); `dd-otlp-source=llmobs` header; direct-OTLP config.
4. https://www.datadoghq.com/blog/llm-otel-semantic-convention/: native OTLP GenAI ingest, no dd-trace SDK; semconv v1.37+; three ingestion paths; gen_ai attribute auto-mapping (model/tokens/cost); side-by-side logic-vs-data framing.
5. https://docs.datadoghq.com/llm_observability/terms/: span definition; LLM/tool/workflow span kinds; spans carry inputs/outputs (LLM prompts/completions).
6. https://www.datadoghq.com/blog/datadog-llm-observability/: drill into a trace, prompts sent and model replies "all in one view."
7. https://www.datadoghq.com/blog/openai-agents-llm-observability/: "viewing each step … side by side with the input and output data."
8. https://docs.datadoghq.com/llm_observability/monitoring/querying/: custom metadata/attributes surface under `@meta.metadata.<key>`.
9. https://docs.datadoghq.com/llm_observability/instrumentation/: supported sites; GovCloud unsupported for LLM Observability.
10. https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk: (cross-ref via research/28/29) the `EVENT_ONLY`-valid / `=true`-invalid behavior holds **for the ADK/util-genai path**, not for raw SDK code.
11. https://opentelemetry.io/blog/2026/genai-observability/: content capture disabled by default for sensitivity; current convention uses structured message attributes; no manual-code-specific capture switch in the SDK.
12. https://docs.datadoghq.com/security/sensitive_data_scanner/: (Q5 Part B) SDS "can scan Agent Observability traces, including inputs and outputs from LLM applications"; managed configuration model; one managed scanning group auto-created on first Agent-Obs Settings visit (cannot add/delete); predefined rule library (emails, credit cards, **API keys, authorization tokens**, network/device) + custom regex; actions Redact / Partially redact / Hash (Mask is logs-only); scans **by content**, instrumentation-agnostic; runs **after ingest** (server-side).
13. https://docs.datadoghq.com/llm_observability/data_security_and_rbac/: (Q5 Part B) redaction mechanisms on this page: **span processors** redact "at the application level **before it is sent to Datadog**" and can prevent spans from being emitted; **Sensitive Data Scanner** as "**an additional layer of security**"; and Data Access Control / RBAC. [NOTE 2026-06-23: this page does NOT mention the OTel Collector or the phrase "before telemetry data leaves your network"; that Collector governance framing is sourced separately from the Datadog OTel-for-LLM-Obs blog, citation 4.]
14. https://docs.datadoghq.com/llm_observability/instrumentation/sdk/: (Q5 Part B) span processors are a feature of the **Datadog Agent Observability SDK** (`ddtrace` `LLMObs`, `def redact_processor(span: LLMObsSpan) -> LLMObsSpan`); documented only in the SDK context, **no OTLP-ingested-span span-processor hook**.
15. https://docs.datadoghq.com/security/sensitive_data_scanner/scanning_rules/: (Q5 Part B) SDS scanning rules are regex/library patterns over field/attribute content.
16. https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/redactionprocessor/README.md: (Q5 Part B) Collector **redaction processor**: deletes span attributes not on an allow-list, masks values matching a block-list; the egress-hop symmetric redactor.
17. https://opentelemetry.io/docs/security/handling-sensitive-data/: (Q5 Part B) OTel guidance: handle/redact sensitive data in the Collector pipeline before export (transform/OTTL, attributes, redaction processors).

(17 distinct external citations; builds on in-repo `research/05`, `research/28` (Issue #9), and
`research/29` (Issue #10) as instructed, and on `proxy.py` + `BUILD-SPEC.md` §4 read this session.)

---

## Validation pass (adversarial, 2026-06-23)

Consolidated record of two adversarial validation passes (the original run and the #12-Q5 re-run for
Whitney's Sensitive-Data-Scanner update). Every verdict is from a live fetch of the current (2026)
official primary source. Default posture: a claim not backed by a current official source is UNVERIFIED.

**Q1: content as a span event vs a span attribute; opt-in / off-by-default.** CONFIRMED. The canonical
GenAI spans spec marks `gen_ai.input.messages` / `gen_ai.output.messages` / `gen_ai.system_instructions`
as `Opt-In`, stability `Development`, with the sensitive/PII warning, and states content is recorded in
structured form on events and MAY be a JSON string on spans when structured form is unsupported. The spec
does NOT define a content-capture env var. Source: semantic-conventions-genai `gen-ai-spans.md` (citation 1).

**Q3: `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` scope (the central correction).** CONFIRMED on
substance. The env var belongs to `opentelemetry-util-genai` (enum `NO_CONTENT` default / `SPAN_ONLY` /
`EVENT_ONLY` / `SPAN_AND_EVENT`), not the base SDK, and the spec does not define it, so raw hand-written
proxy spans do not honor it unless the code reads it or uses the library. Citation fix applied inline: the
phrase the draft quoted ("only affects applications using this package… not the base SDK") is not verbatim
on the current PyPI page; the conclusion is unchanged because the SDK has no such switch. Sources:
`opentelemetry-util-genai` PyPI (citation 2); `gen-ai-spans.md` (citation 1).

**Q4 / Q5 Part A: Datadog extraction, classification, routing.** CONFIRMED. Datadog reads
`gen_ai.input.messages` / `output.messages` / `system_instructions` (attributes first, then the
`gen_ai.client.inference.operation.details` span event) and maps them to `meta.input/output.messages`;
`gen_ai.operation.name` sets `span.kind = llm` for `generate_content, chat, text_completion, completion`
(value-list fix applied inline: the draft's `chat_completion` example is not in the list); routing is the
`dd-otlp-source=llmobs` header; semconv v1.37+ / `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`;
custom attributes surface as `@meta.metadata.<key>`; LLM Observability is unsupported on GovCloud sites. No
org feature-flag / plan gate was found beyond a supported site + API key + routing header (UNVERIFIED, not
refuted; absence of evidence). Sources: Datadog `otel_instrumentation` doc (citation 3); querying doc
(citation 8); instrumentation index (citation 9); GenAI-OTel blog (citation 4).

**Product rename to "Agent Observability."** CONFIRMED, and surface-only: the docs landing and product
pages use "Agent Observability," but the `/llm_observability/` URL paths, the `dd-otlp-source=llmobs`
header, and native `gen_ai.*` OTLP ingest are unchanged. Sources: the Agent Observability docs landing
page https://docs.datadoghq.com/llm_observability/ plus citations 3, 12, 13.

**Q5 Part B: built-in Sensitive Data Scanner (SDS) vs Collector-side redaction (Whitney's #12 update).**
- **B1: SDS scans manual / OTLP-ingested spans by content (instrumentation-agnostic).** CONFIRMED. SDS
  "can scan Agent Observability traces, including inputs and outputs from LLM applications" via rules
  (predefined library incl. API keys + authorization tokens, plus custom regex); a managed scanning group
  is auto-created on first Agent-Obs Settings visit and cannot be deleted; actions are Redact / Partially
  redact / Hash (Mask is logs-only). No clause exempts manually-instrumented spans. Sources: citations 12, 15.
- **B2: SDS is a Datadog-platform-side scanner, not a network-egress redactor.** CONFIRMED-WITH-NUANCE.
  The SDS doc says data is "redacted before events are indexed" and is silent on exact Agent-Obs timing, so
  "after ingest" is an inference, not a verbatim quote; either way SDS cannot keep the secret off the wire.
  Citation fix applied inline: the phrase "before telemetry data leaves your network" was mis-attributed to
  `data_security_and_rbac` (which does not contain it and does not mention the Collector), re-sourced to
  the Datadog OTel-for-LLM-Obs material (citation 4). Sources: citations 12, 13, 4.
- **B3: Datadog SDK span processors are SDK-only, absent on the OTLP path.** CONFIRMED. The span-processor
  redactor ("redact… at the application level before it is sent to Datadog") is documented only as an Agent
  Observability SDK feature (`ddtrace` `LLMObs`, `redact_processor(span: LLMObsSpan)`); there is no
  span-processor hook for OTLP-ingested spans, so the OTLP-emitting proxy cannot use it. Sources: citations 14, 13.
- **B-conclusion: Collector-side symmetric redaction remains the correct re-leak-trap path.** CONFIRMED.
  The contrib redaction processor (allow/block-list delete + mask) and transform/OTTL run in the Collector
  pipeline before export, satisfying the trap's need to show the *before* secret, redact at the boundary,
  and confirm sanitization. SDS applies to manual spans but only platform-side, so it is the defense-in-depth
  backstop, not the mechanism for this beat. Sources: citations 16, 17, 13.

**UNVERIFIED / OPEN (carried forward; agreed, not refuted):**
- **Collector → Agent/LLM-Obs routing** of `gen_ai.*` spans via the contrib `datadog` exporter (inherited
  `research/28` Q7 seam); verify live; deterministic fallback is a dedicated OTLP exporter with
  `dd-otlp-source=llmobs`.
- Whether a Collector OTTL/redaction transform on `gen_ai.input.messages` / `witb.input.messages.original`
  is preserved through the `datadog` exporter into Agent/LLM-Obs (not just the APM/Tempo copy); verify live.
- Rendered original-vs-sanitized trace-panel layout (no documented two-value diff widget); verify live.

**Net:** no load-bearing claim was refuted across either pass. Fixes applied inline were accuracy-level: a
non-verbatim PyPI quote (Q3), the `chat_completion` example value (Q5), the Collector-phrase attribution
(B2), and the SDS "after ingest" nuance. The spike's central findings stand: the capture env var does not
govern hand-written SDK spans; SDS scans manual spans by content but only platform-side; Datadog SDK span
processors are not on the OTLP path; Collector-side symmetric redaction is the re-leak-trap mechanism with
SDS as the post-ingest backstop.
