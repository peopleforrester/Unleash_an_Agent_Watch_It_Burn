<!-- ABOUTME: Research spike on the Datadog LLM Observability OTLP ingestion path for the Watch-It-Burn stack. -->
<!-- ABOUTME: Answers PRD #7 Milestone 2 / Issue #9: native gen_ai OTLP ingest, semconv v1.37, paths, content capture, ADK emission, org config. -->

# 28. Datadog LLM Observability OTLP Ingestion Path for This Stack

## Verification Method

Web research re-run **2026-06-23** against current (2026) official primary sources: the Datadog
Agent Observability (formerly "LLM Observability") OpenTelemetry instrumentation docs, the Agent
Observability landing/product pages, the Datadog Sensitive Data Scanner docs, the Datadog launch blog,
the OpenTelemetry GenAI semantic-conventions repo/spec, the `opentelemetry-util-genai` package, and the
Google ADK + Google Cloud ADK-instrumentation docs. Every material claim carries an inline source URL;
the full list is in **Sources** at the end. Where a vendor doc and a marketing blog disagree on scope,
the doc is treated as authoritative and the gap is flagged.

> **Product-naming update (2026-06-23 re-run):** Datadog has **rebranded the product to "Agent
> Observability."** The docs landing page (`docs.datadoghq.com/llm_observability/`) is now **titled
> "Agent Observability"**, there is a dedicated product page (`.../products/ai/agent-observability/`),
> and the OTel instrumentation doc now refers to the **"Agent Observability SDK"** (formerly the "LLM
> Observability SDK"). The **`/llm_observability/` URL paths and the `dd-otlp-source=llmobs` header are
> unchanged**: only the surface name changed; "LLM Observability" persists as a legacy/encompassed
> term. **All 7 verdicts below are unchanged by the rename.** This spike now uses "Agent Observability
> (LLM Observability)" where the distinction matters.

This spike **builds on** and does not re-derive:
- `research/05-otel-genai-observability.md`: GenAI semconv is all `Development`; span names
  (`invoke_agent`, `execute_tool {gen_ai.tool.name}`, the model/inference span); content capture OFF
  by default; the re-leak trap; kagent tracing enabled via Helm `otel.tracing.enabled`.
- `research/18-datadog-integrations-stack-2026.md`: per-component Datadog integration survey; UST
  attribute→tag mapping (`service.name`/`service.version`/`deployment.environment.name`).
- `research/23-observability-decision-points-2026.md`: Datadog-additive principle; pure-OTel
  Collector → `datadog` exporter is the shipped path; DDOT optional; service-map verification gate.
- PRD #7 Milestone 2 "Preliminary research" block (the seed this spike confirms or corrects).

**Stack under test (from `docs/BUILD-SPEC.md` + `gitops/apps/otel-collector.yaml`):**
guard-proxy (Python → AWS Bedrock) → agentgateway → kagent (Google ADK) → all emit OTLP into a
standalone `otelcol-contrib 0.158.2` (DaemonSet) whose `datadog` exporter is the primary sink
(alongside `prometheusremotewrite` + `otlp/tempo` fallback).


> **Hypothesis-verification stance (Whitney's rule):** the issue's stated "gotchas" are treated as
> hypotheses. Each is marked **CONFIRMED**, **CONFIRMED-WITH-NUANCE**, or **COULD NOT FULLY
> CONFIRM** below.


---

## TL;DR per question

| # | Question | Verdict |
|---|---|---|
| 1 | Native OTel `gen_ai.*` OTLP ingest, no dd-trace/SDK; semconv v1.37+ | **CONFIRMED** |
| 2 | Which OTLP paths work (direct intake / Agent OTLP / Collector) | **CONFIRMED** all three |
| 3 | Correct `OTEL_SEMCONV_STABILITY_OPT_IN` for older-spec frameworks | **CONFIRMED** = `gen_ai_latest_experimental` |
| 4 | OpenLLMetry 0.47+ supported, OpenInference NOT | **CONFIRMED** |
| 5 | `...CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` correct; `=true` invalid, no content | **CONFIRMED-WITH-NUANCE** |
| 6 | What kagent/ADK emits natively (spans/attrs/hierarchy) | **CONFIRMED** |
| 7 | Datadog-side config / feature flags / org settings | **CONFIRMED-WITH-NUANCE** (one Collector-routing gap, flagged) |
| n/a | **Product name** (was "LLM Observability") | **CHANGED** → now **"Agent Observability"** (URLs/header unchanged) |
| n/a | **Built-in Sensitive Data Scanner (PII redaction)** | **CONFIRMED**: included, scans Agent-Obs traces incl. LLM in/out; not on by default (default scanning group auto-created on first Settings visit) |

---

## Note on product naming (Whitney's #9 update, 2026-06-23)

**The product is now "Agent Observability."** Verified against three Datadog surfaces:

- The docs landing page at `docs.datadoghq.com/llm_observability/` is **titled "Agent
  Observability."** (https://docs.datadoghq.com/llm_observability/)
- There is a dedicated **product page**: "Agent Observability | LLM Observability | Datadog,"
  heading "Ship AI agents faster, with confidence" / "Evaluate, improve, and trace your AI agents."
  (https://www.datadoghq.com/products/ai/agent-observability/)
- The OTel instrumentation doc now says "without requiring the **Agent Observability SDK** or a
  Datadog Agent" (the SDK was the "LLM Observability SDK" in the prior run), and refers to the "Agent
  Observability Traces page."
  (https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/)

**What did NOT change (load-bearing for this stack):**
- The **doc URL paths still use `/llm_observability/`**, so existing links in this spike and in PRD #7
  remain valid.
- The **`dd-otlp-source=llmobs` routing header is unchanged** (still `llmobs`, not `agentobs`).
- **It still natively ingests OTel `gen_ai.*` spans over OTLP** at semconv **v1.37+** with no Datadog
  SDK/Agent, re-confirmed verbatim this run (see Q1).
- "LLM Observability" persists as a legacy/encompassed term; Datadog uses both names interchangeably.

**New capability relevant to this stack: built-in Sensitive Data Scanner (SDS) for PII redaction.**
Agent Observability now **includes Sensitive Data Scanner** ("Sensitive Data Scanner is included and
scales with LLM usage"); the product page lists catching "hallucinations, prompt injection attempts,
and **PII exposure** as they happen."
(https://www.datadoghq.com/products/ai/agent-observability/)
- SDS **scans Agent Observability traces, including the inputs and outputs from LLM applications**. It
  "helps prevent exposing sensitive data like PII, API keys, or proprietary information in prompts,
  completions, and LLM workflow metadata."
  (https://docs.datadoghq.com/security/sensitive_data_scanner/)
- The Agent-Obs data-security doc frames it as **"an additional layer of security"** alongside
  application-level **span processors** (in-app redaction) and **role-based access controls**: "Agent
  Observability integrates with Sensitive Data Scanner, which helps prevent data leakage by identifying
  and redacting any sensitive information (such as personal data, financial details, or proprietary
  information)."
  (https://docs.datadoghq.com/llm_observability/data_security_and_rbac/)
- **Not on by default; it must be configured.** SDS requires a **scanning group** + **scanning rules**;
  for Agent Observability, "a default scanning group is automatically created for your organization when
  you first access the Agent Observability Settings page," and Datadog ships a **predefined rule library**
  (email addresses, credit-card numbers, API keys, authorization tokens, network/device info). Note: it
  classifies/redacts telemetry **after ingest, server-side** at Datadog. It does **not** redact before
  data leaves your network. For pre-egress redaction, use the **Collector** (OTel transform/redaction
  processors) or the in-app **span processors** (see the re-leak-trap note in Q5).
  (https://docs.datadoghq.com/security/sensitive_data_scanner/ ;
  https://docs.datadoghq.com/llm_observability/data_security_and_rbac/)

**Demo relevance (PRD #7 Milestone 3 re-leak trap):** SDS is a *Datadog-side* mitigation that can be
narrated as the "the platform caught the leaked secret" beat. It scans/redacts the `gen_ai.input.messages`
/ `gen_ai.output.messages` content that the `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY`
trap deliberately captures (Q5). But because SDS acts **after** the span reaches Datadog, the
**Collector-side symmetric redaction** (`research/12`) remains the network-egress mitigation; SDS is the
defense-in-depth backstop in the UI, not a replacement for it.

---

## Q1. Does Datadog LLM Observability natively ingest OTel `gen_ai.*` spans over OTLP (no dd-trace/SDK)? Min semconv v1.37+?

**CONFIRMED: yes, natively, no Datadog SDK or `dd-trace`; minimum semconv is v1.37+.**

- Datadog's OTel-instrumentation doc states you can "send LLM traces directly from
  OpenTelemetry-instrumented applications to Datadog **without requiring the Agent Observability SDK
  or a Datadog Agent**." (Re-confirmed verbatim 2026-06-23; the doc now names the **"Agent
  Observability SDK"** where the prior run quoted "LLM Observability SDK", see the product-naming note
  above. The capability is identical.)
  (https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/)
- The minimum is explicit: Agent Observability ingests OpenTelemetry traces "that follow the
  **OpenTelemetry 1.37+ semantic conventions for generative AI**." The launch blog repeats it:
  "OTel GenAI Semantic Conventions (**v1.37 and up**)" and "upgrade to OTel SDK/Collector **v1.37 or
  later**."
  (https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ ;
  https://www.datadoghq.com/blog/llm-otel-semantic-convention/ , published 2025-12-01)
- Datadog "automatically maps GenAI attributes (e.g., `gen_ai.request.model`,
  `gen_ai.usage.input_tokens`, `gen_ai.provider.name`, and `gen_ai.operation.name`) to the native
  LLM Observability schema" for latency, token usage, cost, model/provider, and finish reason, so
  the standard `gen_ai.*` span is enough; no proprietary attributes are required.
  (https://www.datadoghq.com/blog/llm-otel-semantic-convention/)

**So the PRD #7 Milestone 2 seed claim is correct.** The "v1.37+" line is not arbitrary: it is the
semconv version at which Datadog pinned its native mapping. Note the cross-cutting caveat from
`research/05`: all `gen_ai.*` semconv is still **`Development`** status in the OTel spec
(attribute-name churn is a live risk), so pin emitter versions and record actual emitted names.
(https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/ : Inference span still badged
`Development`.)

**Implication for this stack:** the guard-proxy currently emits Michael's custom `witb_*` metrics
(NOT `gen_ai.*` spans); see PRD #7 Milestone 2. Native LLM-Obs ingest depends on the AI layer
actually emitting `gen_ai.*` v1.37 spans. That migration is the Milestone-2 work; this spike confirms
the *target* path is real, not that the stack emits it today.

---

## Q2. Which OTLP ingestion paths work: direct OTLP intake, Agent in OTLP mode, or via the Collector?

**CONFIRMED: all three are officially supported.** The launch blog enumerates them verbatim:

1. **"directly from your OTLP exporter to Datadog's OTLP intake endpoint"** (no Agent, no Collector);
2. **"via the Datadog Agent with OTLP ingest enabled"**;
3. **"through the OpenTelemetry Collector (including the Datadog Distribution of the OpenTelemetry
   Collector)."**
   (https://www.datadoghq.com/blog/llm-otel-semantic-convention/)

The instrumentation **doc page itself only documents path 1** (direct OTLP intake) in detail; it does
NOT walk through the Agent or Collector configs. So paths 2 and 3 are vendor-asserted (blog) but not
step-by-step documented on the LLM-Obs doc page.
(https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/)

**Direct-intake config (path 1, documented verbatim):**
```
OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=<YOUR_OTLP_TRACE_ENDPOINT>
OTEL_EXPORTER_OTLP_TRACES_HEADERS=dd-api-key=<YOUR_API_KEY>,dd-otlp-source=llmobs
```
The load-bearing token is the **`dd-otlp-source=llmobs`** header, which routes the trace to Agent
(LLM) Observability rather than plain APM.
(https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/)

**What this means for OUR stack (the standalone `otelcol-contrib 0.158.2` → `datadog` exporter,
path 3).** This is the genuinely under-documented seam (see **Q7** for the full treatment and the
explicit flag). Short version: the repo's Collector uses the contrib **`datadog`** exporter (which
maps to APM), not the direct-intake `dd-otlp-source=llmobs` header path. Whether `gen_ai.*` spans
arriving via the contrib `datadog` exporter auto-populate LLM Observability, or whether an
equivalent of `dd-otlp-source=llmobs` must be set on the Collector/exporter, is **not stated in the
sources I could reach**. This must be **verified live in the Datadog UI** (LLM Observability traces
page) during Milestone 2. The portable fallback is path 1: point the AI-layer pods' OTLP exporter (or
a dedicated Collector exporter) straight at the intake endpoint with the `dd-otlp-source=llmobs`
header. That path is fully documented and header-deterministic.

---

## Q3. Correct `OTEL_SEMCONV_STABILITY_OPT_IN` value for frameworks on older specs?

**CONFIRMED: `gen_ai_latest_experimental`.**

- Datadog doc: "If your framework previously supported a pre-1.37 OpenTelemetry specification version,
  you also need to set: **`OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`**." The doc names
  **`strands-agents`** explicitly as such a framework. No other framework is named on that page.
  (https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/)
- Google's ADK-instrumentation doc sets the same value: configure OpenTelemetry "to use the most
  recent semantic conventions for generative AI with
  **`OTEL_SEMCONV_STABILITY_OPT_IN='gen_ai_latest_experimental'`**."
  (https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk)
- The OTel GenAI conventions / `opentelemetry-util-genai` use the same opt-in to "enable experimental
  features" (the v1.37 message/content attributes).
  (https://pypi.org/project/opentelemetry-util-genai/)

So this is the correct, cross-vendor-consistent value. It opts the instrumentation into the newest
(`gen_ai_latest_experimental`) attribute shape, which is exactly the v1.37+ shape Datadog's native
mapping expects. **Set it on the kagent/ADK agent pod and on any other AI-layer emitter** that
defaults to a pre-1.37 attribute set. (`research/05` already flagged this as a deliberate, not casual,
setting because of `Development`-status name churn.)

---

## Q4. Datadog supports OpenLLMetry 0.47+ but NOT OpenInference: verify; what does "support" mean operationally?

**CONFIRMED: both halves, verbatim from the Datadog doc:**
- **"OpenLLMetry version 0.47+ is supported."**
- **"OpenInference is not supported."**
  (https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/)

**What "support" means operationally.** OpenLLMetry (Traceloop's OTel-based auto-instrumentation
libraries, the `opentelemetry-instrumentation-*`/Traceloop SDK family) and OpenInference (Arize's
competing OTel-based GenAI instrumentation) are **two different attribute vocabularies** for the same
idea (instrument an LLM/agent and emit spans). "Support" here means **Datadog's ingest understands and
maps that library's span/attribute shape into the LLM Observability schema**:
- OpenLLMetry ≥ 0.47 emits attributes Datadog's mapper recognizes → its spans render correctly in LLM
  Observability with no code changes. (Below 0.47 the attribute shape predates the mapping; upgrade.)
- OpenInference's attribute names are a different convention Datadog's LLM-Obs mapper does **not**
  translate → those spans will not populate LLM Observability correctly. This is a hard
  vocabulary mismatch, not a version gap; there is no "upgrade OpenInference to fix it" path for
  LLM-Obs ingest.

**Operational guidance for this stack:** the AI layer is **Python + Google ADK (kagent) + a custom
guard-proxy**. The lowest-effort route is **native ADK gen_ai emission** (Q6), which already follows
the OTel GenAI conventions Datadog maps, so OpenLLMetry is not strictly required for the agent path.
Where auto-instrumentation *is* wanted on a plain-Python component (e.g. the guard-proxy's Bedrock
call), **use OpenLLMetry ≥ 0.47, never OpenInference.** (PRD #7 Milestone 2 already records
"OpenLLMetry, Datadog-supported; NOT OpenInference"; this spike confirms it against the doc.)

---

## Q5. Content capture: is `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` correct under latest semconv, and is `=true` an invalid config that appears to enable capture but collects nothing?

**CONFIRMED-WITH-NUANCE.** `EVENT_ONLY` is a valid enumerated value and is what Google's ADK doc uses;
`true` is invalid **under the latest (v1.37+) experimental conventions** and produces no data. The
nuance: the variable's value space changed from a boolean to an **enum**, so the precise failure mode
("appears to enable, collects nothing") is version/convention-dependent, not universal.

**The current enum (authoritative, from `opentelemetry-util-genai` + Google ADK doc):**
| Value | Behavior |
|---|---|
| `NO_CONTENT` | Do not capture message content **(default)** |
| `SPAN_ONLY` | Capture message content in spans only |
| `EVENT_ONLY` | Capture message content in events only |
| `SPAN_AND_EVENT` | Capture in both spans and events |
(https://pypi.org/project/opentelemetry-util-genai/ ; values + default quoted verbatim.)

**The `=true` trap (CONFIRMED against Google's ADK doc):** "When you use the most recent semantic
conventions, setting the value of this variable to **`true` results in an invalid configuration**,"
and in that state "log and trace data isn't collected." So `=true` is exactly the silent-failure
config the issue describes: it looks like the old boolean-on switch, but under v1.37+/`gen_ai_latest_
experimental` it is unrecognized and captures nothing.
(https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk)

**Why `true` ever "worked":** older instrumentations (e.g. `opentelemetry-instrumentation-openai-v2`
historically) used a boolean `true/false` for this flag. Once you opt into the latest experimental
conventions (`OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`), the flag is the **enum**
above, and the boolean string is invalid. The two flags are coupled: the enum is in force precisely
when you've also set the stability opt-in. (`research/05` already noted the default is "off"/no-content
and that the flag name/shape is per-instrumentation; this spike pins the enum + the `=true` failure.)

**For this workshop specifically:** content capture is the **re-leak-trap** mechanism
(`research/05` §"Re-leak trap"; PRD #7 Milestone 3). The correct on-switch is
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` (or `SPAN_ONLY`/`SPAN_AND_EVENT` if you
want the secret to land in span attributes specifically), **not `=true`**, which would make the trap
silently fail to fire. Keep it `NO_CONTENT` (default) on the shared path; flip to `EVENT_ONLY` only
for the deliberate trap beat, with the Collector-side symmetric redaction (`research/12`) as the
mitigation half of the lesson. The captured-content attributes (`gen_ai.input.messages`,
`gen_ai.output.messages`, `gen_ai.system_instructions`) are `Opt-In` + `Development`.
(https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/)

---

## Q6. What does kagent/ADK emit natively via gen_ai semconv when `otel.tracing.enabled: true`? Span names, attributes, hierarchy.

**CONFIRMED: kagent's base, Google ADK, natively emits OTel GenAI-semconv spans, and the
`invoke_agent → model-call → execute_tool` waterfall is exactly the workshop's narration target.**

**Enablement (two layers, both true, applied at different surfaces):**
- **kagent layer (the workshop's actual lever):** tracing is **off by default**, enabled via Helm
  `otel.tracing.enabled: true` with an OTLP exporter endpoint (`research/05` §4, from
  https://www.kagent.dev/docs/kagent/observability/tracing). This turns on OTLP export from the kagent
  agent pod.
- **ADK layer (what produces the gen_ai spans underneath):** ADK ≥ **1.17.0** includes built-in OTel
  GenAI-semconv support; it is configured with standard `OTEL_*` env vars
  (`OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`,
  `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`, and the content-capture enum).
  (https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk ;
  https://adk.dev/observability/traces/)
  **Verify-at-build:** confirm that flipping kagent's `otel.tracing.enabled: true` actually propagates
  the `gen_ai_latest_experimental` opt-in down to the embedded ADK runtime (i.e. that kagent passes
  the `OTEL_*` env through, or that you set them on the agent Deployment `.env`). `research/05` already
  flags kagent's exact emission as "verify by capturing a real trace." kagent env support on the
  Agent deployment is itself a verify-at-build item per `PROJECT_STATE.md`.

**Span names ADK emits (verbatim from `adk.dev/observability/traces`):**
- **`invoke_agent`**: "Describes GenAI agent invocation over a remote service or locally."
- **`invoke_workflow`**: "the invocation of a multi-step agentic workflow."
- **`execute_tool`**: "the execution of a specific tool or function call" (this is the rogue-MCP-call
  span the demo narrates; named `execute_tool {gen_ai.tool.name}` per the OTel spec).
- **`generate_content {model.name}`**: "the invocation of the underlying language model." (Google
  Cloud's ADK doc shows the model span surfaced as **`call_llm`** in its UI; both refer to the
  inference call. The OTel spec form is `{gen_ai.operation.name} {gen_ai.request.model}`, e.g.
  `chat <model>`. Expect the concrete name to be ADK-version-specific: **record the actual emitted
  name at build**, do not hardcode from this doc.)
  (https://adk.dev/observability/traces/ ;
  https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk ;
  https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)

**Hierarchy (waterfall):** "an agent run is a root span, which contains child spans for LLM
operations, which may in turn contain child spans for tool executions,"
i.e. `invoke_agent` (root) → model/`call_llm` span → `execute_tool {tool}` (nested under the LLM
turn that requested the tool). This is the clean `invoke_agent → chat → execute_tool` waterfall PRD #7
Milestone 2 wants in Datadog LLM Observability.
(https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk ;
https://adk.dev/observability/traces/)

**Attributes ADK records (verbatim list from `adk.dev/observability/traces`):**
`gen_ai.agent.name`, `gen_ai.system`, `gen_ai.tool.name`, `gen_ai.workflow.name`,
`gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.conversation.id`, `user.id`,
`gen_ai.request.top_p`, `gen_ai.request.max_tokens`, `gen_ai.response.finish_reasons`,
**`gen_ai.usage.input_tokens`**, **`gen_ai.usage.output_tokens`**.
(https://adk.dev/observability/traces/)

The two token-usage attributes are the ones Datadog maps to **token usage and (derived) cost**, and
`gen_ai.request.model` is the **model dimension** PRD #7 Milestone 2 wants for the model-tier cost
comparison (NOT `service.version`, per the meta-PRD decision). So the data the cost story needs is
emitted natively, confirming the seed claim that the lowest-effort path is "enable native
kagent/ADK tracing → OTLP → Datadog," not new Python instrumentation.

**Caveat (carry from `research/05`):** ADK runs *inside* kagent; the doc-level guarantee is ADK's. The
build must capture a live kagent trace and confirm (a) the `gen_ai.*` attributes survive kagent's
export, (b) the `execute_tool` span names the MCP tool, and (c) the model span carries
`gen_ai.request.model`. Do not build dashboards on the attribute names in this doc without that
live check (GenAI semconv is `Development`).

---

## Q7. Datadog-side config requirements (feature flags, org settings) to enable LLM Obs ingestion from OTel?

**CONFIRMED-WITH-NUANCE.** For the **documented direct-OTLP path**, the only Datadog-side requirements
are an **API key** and the **`dd-otlp-source=llmobs` header**: no org feature flag or special plan
toggle is mentioned. For the **Collector path this repo uses**, the routing-into-LLM-Obs detail is a
documented gap and is the one verify-at-build item.

**What the docs DO state (direct OTLP intake path):**
- Requirement is a **Datadog API key**; "**no special org-level enablement is mentioned**." The launch
  blog likewise lists **no org-level feature flags, plan requirements, or settings**, only "upgrade to
  OTel SDK/Collector v1.37 or later."
  (https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ ;
  https://www.datadoghq.com/blog/llm-otel-semantic-convention/)
- The header set is the *only* routing control: `OTEL_EXPORTER_OTLP_TRACES_HEADERS=dd-api-key=<KEY>,
  **dd-otlp-source=llmobs**`, protocol `http/protobuf`. The `dd-otlp-source=llmobs` value is what tells
  Datadog "treat these as LLM Observability traces."
- Unsupported Datadog **sites** for LLM Observability: `app.ddog-gov.com` and `us2.ddog-gov.com` (GovCloud).
  So the org's site must be a supported commercial site (the repo defaults `DD_SITE=datadoghq.com`,
  which is supported).
  (https://docs.datadoghq.com/llm_observability/instrumentation/)

**The nuance / the gap (load-bearing for THIS stack):** the repo exports via the contrib **`datadog`
exporter** in `otelcol-contrib 0.158.2` (→ Datadog APM intake), not via the direct-OTLP
`dd-otlp-source=llmobs` header path. None of the reachable sources state how a `gen_ai.*` span sent
through the **Collector's `datadog` exporter** (or through the **Datadog Agent OTLP ingest**) gets
routed into LLM Observability: whether it is automatic on attribute detection, or whether a Collector
/exporter-side equivalent of `dd-otlp-source=llmobs` is required. The blog asserts the Collector path
works but gives no config. **This is the single item I could NOT fully resolve from docs, and it is flagged.**

**Recommended resolution (in priority order):**
1. **Live-verify the Collector path first** (it's the shipped, portable topology): once the AI layer
   emits `gen_ai.*` v1.37 spans, watch the Datadog **LLM Observability** traces page (not just APM) on
   a live cluster and confirm the `invoke_agent → call_llm → execute_tool` waterfall appears. This is
   the same "verify in the UI" gate `research/23` Decision 8 set for the service map. If it appears
   with no extra config, done.
2. **If it does NOT appear**, add the LLM-Obs routing on the Collector's `datadog` exporter (check the
   contrib `datadog` exporter version pinned in chart `0.158.2` for an LLM-Obs / `dd-otlp-source`
   option), OR add a **dedicated OTLP exporter** in the Collector pointed at Datadog's OTLP intake
   endpoint with `dd-otlp-source=llmobs` in the headers, the documented, header-deterministic path.
   Either keeps the Datadog-additive principle (`research/23` D2): removing it leaves Prometheus +
   Tempo intact.
3. **Keep `datadog.prometheusScrape.enabled` OFF** (PRD #7 / `research/18`): double-scrape with the
   Collector causes duplicate metrics + billing, unrelated to LLM-Obs but a standing Datadog-side
   config requirement for this stack.

**Net:** no org feature-flag/plan gate is documented to "turn on" LLM Observability ingest beyond a
supported site + API key; the real config work is (a) emitting v1.37 `gen_ai.*` spans, (b) the
`gen_ai_latest_experimental` opt-in, and (c) ensuring the **Collector → Datadog** hop routes those
spans to LLM Observability (verify live; fall back to the documented `dd-otlp-source=llmobs` OTLP path
if not automatic).

---

## Cross-cutting build notes (carry into PRD #7 Milestone 2)

- **The stack does not emit `gen_ai.*` today.** guard-proxy emits custom `witb_*` metrics; native
  ingest is contingent on the Milestone-2 migration to OTel GenAI semconv. This spike confirms the
  *target* is sound, not that data flows now.
- **Set on the kagent/ADK agent pod:** `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`,
  `OTEL_SERVICE_NAME=workshop-agent` (UST `service.name`), the OTLP endpoint, and, only for the
  re-leak beat, `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` (never `=true`).
- **Verify-at-build (live trace capture), per `research/05`:** actual emitted span names + attribute
  names (semconv is `Development`); that kagent propagates the ADK `OTEL_*`/opt-in; that
  `gen_ai.request.model` and `gen_ai.usage.*` survive to Datadog; and the Collector → LLM-Obs routing
  (Q7 gap).
- **Site check:** keep `DD_SITE` on a commercial site (default `datadoghq.com` is supported); GovCloud
  sites are unsupported for LLM Observability.
- **`gen_ai.request.model`** is the model-tier cost dimension (meta-PRD decision), not `service.version`.

---

## Could-not-fully-resolve (explicitly flagged)

- **Q7 / Q2, Collector→LLM-Obs routing:** No reachable doc states whether `gen_ai.*` spans sent via
  the contrib **`datadog` exporter** (or Datadog Agent OTLP ingest) auto-route into LLM Observability,
  or require a Collector-side `dd-otlp-source=llmobs` equivalent. The blog asserts the Collector path
  works but provides no config; the doc only details the direct-OTLP header path. **Resolution = a live
  Datadog-UI check on a cluster emitting gen_ai spans**, with the documented direct-OTLP intake +
  `dd-otlp-source=llmobs` as the deterministic fallback.

---

## Sources

- https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ : native OTLP ingest (no SDK/Agent), v1.37+ requirement, `dd-otlp-source=llmobs` header, `gen_ai_latest_experimental` (strands-agents), OpenLLMetry 0.47+ supported / OpenInference not supported, direct-OTLP exporter config.
- https://www.datadoghq.com/blog/llm-otel-semantic-convention/ : launch blog (2025-12-01): three ingestion paths (direct intake / Agent OTLP ingest / Collector incl. DDOT), v1.37 and up, "no code changes required," gen_ai attribute auto-mapping, "alongside existing APM traces."
- https://docs.datadoghq.com/llm_observability/instrumentation/ : instrumentation landing; unsupported GovCloud sites for LLM Observability.
- https://docs.datadoghq.com/llm_observability/ : **docs landing page now titled "Agent Observability"** (the rename); references the "Agent Observability SDK for Python"; "Automatically scan and redact any sensitive data in your AI applications and identify prompt injections."
- https://www.datadoghq.com/products/ai/agent-observability/ : **Agent Observability product page** ("Ship AI agents faster, with confidence"); "Sensitive Data Scanner is included and scales with LLM usage"; "Catch hallucinations, prompt injection attempts, and PII exposure as they happen."
- https://docs.datadoghq.com/llm_observability/data_security_and_rbac/ : Agent Observability data security + RBAC; SDS as "an additional layer of security" alongside span processors + access controls; "integrates with Sensitive Data Scanner, which helps prevent data leakage by identifying and redacting any sensitive information."
- https://docs.datadoghq.com/security/sensitive_data_scanner/ : SDS scans Agent Observability traces incl. LLM inputs/outputs (prompts, completions, workflow metadata); covers logs/APM/RUM/Agent-Obs traces/events/S3; requires scanning group + rules (default group auto-created on first Agent Observability Settings visit); predefined rule library (emails, credit cards, API keys, auth tokens, network/device info).
- https://docs.datadoghq.com/opentelemetry/setup/otlp_ingest/ : Datadog OTLP intake endpoint (general OTLP ingest context).
- https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk : ADK ≥1.17.0 built-in OTel gen_ai support; `OTEL_SERVICE_NAME` / `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` / `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY`; `=true` is an invalid config that collects no data; `call_llm` span; waterfall hierarchy.
- https://adk.dev/observability/traces/ : ADK span names (`invoke_agent`, `invoke_workflow`, `execute_tool`, `generate_content {model.name}`), the full `gen_ai.*` attribute list incl. `gen_ai.usage.input_tokens/output_tokens` and `gen_ai.request.model`, OTel gen_ai semconv compliance, OTLP enablement.
- https://pypi.org/project/opentelemetry-util-genai/ : `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` enum (`NO_CONTENT` default / `SPAN_ONLY` / `EVENT_ONLY` / `SPAN_AND_EVENT`); coupling with `gen_ai_latest_experimental`.
- https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/ : gen_ai spans still `Development`; message-content attributes (`gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`) `Opt-In` + `Development`. **[2026-06-23: this URL now redirects to "moved/no longer maintained"; canonical source is https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md ; facts re-confirmed there.]**
- https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/ : agent/framework span name forms (`invoke_agent {gen_ai.agent.name}`, `execute_tool {gen_ai.tool.name}`, operation-name conventions). **[2026-06-23: moved; canonical source is https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md ; facts re-confirmed there.]**
- https://www.kagent.dev/docs/kagent/observability/tracing : kagent tracing off-by-default, enabled via `otel.tracing.enabled: true` + OTLP exporter (via `research/05`).

---

## Validation pass (adversarial, 2026-06-23 re-run)

An independent adversarial re-check fetched each load-bearing claim against current (2026) official
primary sources and tried to refute it. **Result: every load-bearing claim CONFIRMED; zero refuted.**
The 2026-06-23 re-verification re-fetched, verbatim, all five new/changed surfaces (Agent-Observability
docs landing title + "Agent Observability SDK" naming, the product page's "Sensitive Data Scanner is
included … PII exposure" copy, the data-security/RBAC doc's SDS-as-additional-layer framing, the SDS
doc's "can scan Agent Observability traces, including inputs and outputs from LLM applications" +
auto-created default scanning group, and the unchanged `dd-otlp-source=llmobs` header + v1.37 minimum)
and they hold word-for-word; the SDS doc additionally confirms Redact/Partially-redact/Hash actions
(Mask unavailable for Agent Observability) and that the managed scanning group cannot be deleted.
**This re-run added two findings from Whitney's #9 product-naming update:** (a) the product is now
**"Agent Observability"**, a surface rename only, URLs and the `dd-otlp-source=llmobs` header are
unchanged, all 7 verdicts hold; (b) a **built-in Sensitive Data Scanner** for PII redaction of
Agent-Obs traces is **CONFIRMED** (included, scans LLM inputs/outputs, configured via scanning groups,
acts server-side after ingest). One earlier source-citation correction (stale OTel URLs) is retained
below; no factual claim changed.

| Claim | Verdict | Source checked (2026-06-23) |
|---|---|---|
| Q1: native OTLP `gen_ai.*` ingest "without requiring the Agent Observability SDK or a Datadog Agent" | **CONFIRMED** (verbatim) | https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ |
| Q1: minimum "OpenTelemetry 1.37+ semantic conventions" | **CONFIRMED** (verbatim, doc + blog) | doc above ; https://www.datadoghq.com/blog/llm-otel-semantic-convention/ (Published Dec 1, 2025) |
| Q1: auto-maps `gen_ai.request.model` / `gen_ai.usage.input_tokens` / `gen_ai.provider.name` / `gen_ai.operation.name` | **CONFIRMED** (verbatim) | blog above |
| Q2: three paths (direct intake / Agent OTLP / Collector incl. DDOT) | **CONFIRMED** (verbatim) | blog above |
| Q2: direct-intake config + `dd-otlp-source=llmobs` header, `http/protobuf` | **CONFIRMED** (code block verbatim) | doc above |
| Q3: `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`; `strands-agents` named | **CONFIRMED** | doc above ; https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk ; https://pypi.org/project/opentelemetry-util-genai/ |
| Q4: "OpenLLMetry version 0.47+ is supported." / "OpenInference is not supported." | **CONFIRMED** (verbatim, both halves) | doc above |
| Q5: capture enum `NO_CONTENT` (default) / `SPAN_ONLY` / `EVENT_ONLY` / `SPAN_AND_EVENT` | **CONFIRMED** (verbatim) | https://pypi.org/project/opentelemetry-util-genai/ |
| Q5: `=true` is "an invalid configuration" → "log and trace data isn't collected" under latest semconv | **CONFIRMED** (verbatim: "Don't set the value of this variable to true. When you use the most recent semantic conventions, setting the value of this variable to true results in an invalid configuration. Therefore, log and trace data isn't collected.") | https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk |
| Q5: `EVENT_ONLY` is the value Google's ADK doc uses | **CONFIRMED** (verbatim `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT='EVENT_ONLY'`) | ADK doc above |
| Q6: ADK ≥ 1.17.0 | **CONFIRMED** (verbatim: "ADK framework with version 1.17.0 or higher") | ADK doc above |
| Q6: span names `invoke_agent` / `invoke_workflow` / `execute_tool` / `generate_content {model.name}` | **CONFIRMED** (verbatim descriptions) | https://adk.dev/observability/traces/ |
| Q6: model span surfaced as `call_llm` in Google Cloud UI | **CONFIRMED** (`call_llm` present in ADK doc) | ADK doc above |
| Q6: attribute list incl. `gen_ai.usage.input_tokens` / `output_tokens` / `gen_ai.request.model` | **CONFIRMED** (verbatim list) | adk.dev above |
| Q6: waterfall = agent-run root → LLM op child → tool-exec child | **CONFIRMED** (verbatim: "An agent run is a root span, which contains child spans for LLM operations, which may in turn contain child spans for tool executions.") | adk.dev above |
| Q6: kagent tracing off-by-default, lever `otel.tracing.enabled: true` + OTLP endpoint | **CONFIRMED** (config key verbatim; presented as a non-default upgrade step) | https://www.kagent.dev/docs/kagent/observability/tracing |
| Q7: only API key + `dd-otlp-source=llmobs` header for direct path; no org feature-flag/plan gate documented | **CONFIRMED** (no org gate stated in doc or blog; absence-of-evidence, correctly flagged as such in-file) | doc + blog above |
| Q7: GovCloud sites `app.ddog-gov.com` / `us2.ddog-gov.com` unsupported for LLM Observability | **CONFIRMED** | https://docs.datadoghq.com/llm_observability/instrumentation/ |
| Cross-cut: GenAI inference span is `Development`; `gen_ai.input.messages` / `output.messages` / `system_instructions` are `Opt-In` + `Development` | **CONFIRMED** | new repo (see correction): https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md |
| Cross-cut: agent span-name forms `invoke_agent {gen_ai.agent.name}`, `execute_tool {gen_ai.tool.name}` | **CONFIRMED** (verbatim "Span name SHOULD be `invoke_agent {gen_ai.agent.name}` …") | https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md |
| **Product rename to "Agent Observability"** (docs landing title + product page + "Agent Observability SDK" in OTel doc) | **CONFIRMED** | https://docs.datadoghq.com/llm_observability/ ; https://www.datadoghq.com/products/ai/agent-observability/ ; https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ |
| Rename is surface-only: `/llm_observability/` URLs + `dd-otlp-source=llmobs` header unchanged; native gen_ai OTLP ingest at v1.37+ still holds | **CONFIRMED** | OTel instrumentation doc above (header + v1.37 re-quoted verbatim this run) |
| **Built-in Sensitive Data Scanner** included; scans Agent-Obs traces incl. LLM inputs/outputs; identifies + redacts PII/financial/proprietary | **CONFIRMED** (verbatim) | https://www.datadoghq.com/products/ai/agent-observability/ ; https://docs.datadoghq.com/llm_observability/data_security_and_rbac/ ; https://docs.datadoghq.com/security/sensitive_data_scanner/ |
| SDS not on by default, requires scanning group + rules (default group auto-created on first Agent-Obs Settings visit); predefined rule library; acts server-side after ingest | **CONFIRMED** | https://docs.datadoghq.com/security/sensitive_data_scanner/ |
| Could-not-resolve: Collector (`datadog` exporter) → LLM-Obs auto-routing | **UNVERIFIED (correctly self-flagged)**: no official doc states this; the file's "verify live + `dd-otlp-source=llmobs` fallback" stance is sound | n/a (gap stands) |

**Source-citation correction (no fact changed).** The file cites the GenAI semconv stability/attribute
facts to `https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/` and
`.../gen-ai-agent-spans/`. As of 2026-06-23 those pages return "This page has moved and is no longer
maintained in this repository": the GenAI semconv moved to the **`semantic-conventions-genai`** repo.
The **facts are unchanged and re-confirmed** at the new canonical location:
- https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md (inference span `Development`; message-content attrs `Opt-In`+`Development`)
- https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md (`invoke_agent {gen_ai.agent.name}`, `execute_tool {gen_ai.tool.name}` span-name forms)

Treat the two `opentelemetry.io/docs/specs/semconv/gen-ai/*` URLs in **Sources** as superseded by the
above; the claims they back remain CONFIRMED.
