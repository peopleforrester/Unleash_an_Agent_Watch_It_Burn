<!-- ABOUTME: Grounded research spike on OTel GenAI observability for the Watch-It-Burn workshop. -->
<!-- ABOUTME: Resolves semconv status, content-capture flag, backend choice, collector config, and the trace re-leak trap. -->

# OTel GenAI Observability, Research Spike

## Verification Method

Web research, dated **2026-06-15**. Each material claim is tagged with its source URL inline.
Primary authority is the OpenTelemetry GenAI semantic conventions, which **moved out of the main
docs site into a dedicated repo** (`open-telemetry/semantic-conventions-genai`); the old
`opentelemetry.io/docs/specs/semconv/gen-ai/*` pages now redirect/forward there. Raw spec markdown
from that repo was read directly. Backend and kagent claims are from project docs.

Do not trust training-data attribute names, verified live against the repo's raw `.md` files.

---

## Verified

### 1. GenAI semconv stability status (June 2026)

- **Everything in the GenAI semantic conventions is `Development` status. Nothing is `Stable` yet.**
  This holds for spans, agent spans, tool attributes, and metrics. Verified attribute-by-attribute:
  every `gen_ai.*` attribute on the spans and agent-spans pages carries the
  `![Development]` badge.
  Sources: raw `gen-ai-spans.md` and `gen-ai-agent-spans.md` from
  `github.com/open-telemetry/semantic-conventions-genai` (main branch);
  https://opentelemetry.io/blog/2026/genai-observability/
- Some secondary write-ups claim client spans "exited experimental in early 2026", **this is NOT
  confirmed by the spec itself**, which still badges client/inference span attributes as Development.
  Treat the "stable" claim as marketing drift. See Unverified below.
  (claim source: https://www.digitalapplied.com/blog/agent-observability-platforms-langsmith-langfuse-arize-2026)
- **Version transition baseline is semconv `v1.36`.** Instrumentations default to the older
  attribute shape; setting `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` opts into the
  newest experimental attribute names. Plan for attribute-name churn.
  Sources: https://opentelemetry.io/docs/specs/semconv/gen-ai/ ;
  https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions

### 2. Span names and attributes (what the demo can narrate)

**Span names** (source: raw `gen-ai-spans.md`, `gen-ai-agent-spans.md`):
- Model/inference call: `"{gen_ai.operation.name} {gen_ai.request.model}"` (e.g. `chat gpt-4`).
  `gen_ai.operation.name` = `chat`, `embeddings`, etc.
- Agent invocation: `invoke_agent` (CLIENT for remote agent service, INTERNAL for in-process).
- Agent creation: `create_agent`. Multi-agent: `invoke_workflow`.
- **Agent reasoning step: `plan`**, "an agent planning or task decomposition phase".
- **Tool call: `execute_tool {gen_ai.tool.name}`** (e.g. `execute_tool Flights`), span kind INTERNAL.
  This is the span the workshop narrates for rogue MCP tool calls.

**Attributes** (all `Development`):

| Concern | Attribute | Notes |
|---|---|---|
| Operation type | `gen_ai.operation.name` | Required on all spans |
| Provider | `gen_ai.provider.name` | Required |
| Model | `gen_ai.request.model` | Conditionally required |
| Token usage | `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | Recommended |
| Finish reason | `gen_ai.response.finish_reasons` | |
| **Tool name** | `gen_ai.tool.name` | **Required on `execute_tool` spans** |
| Tool call id | `gen_ai.tool.call.id` | Recommended |
| Tool description | `gen_ai.tool.description` | Recommended |
| Tool definitions (agent) | `gen_ai.tool.definitions` | Opt-In; full list of tools available to the agent |
| Agent identity | `gen_ai.agent.name`, `gen_ai.agent.id`, `gen_ai.agent.description`, `gen_ai.agent.version` | Conditionally required |

So tool calls ARE first-class: `execute_tool <name>` span + `gen_ai.tool.name`/`.call.id` is exactly
what shows "the agent called this tool" in a trace waterfall. This is the connective-tissue lens.

### 3. Content capture, the re-leak vector (CRITICAL)

- **Prompts/responses/tool arguments are NOT captured by default.** The spec says instrumentations
  "SHOULD NOT capture them by default", an intentional privacy decision because they "can contain
  sensitive data". (source: raw `gen-ai-spans.md`)
- When opted in, content lands as **structured span attributes**:
  `gen_ai.input.messages` (chat history), `gen_ai.output.messages` (model responses),
  `gen_ai.system_instructions` (system prompt). All `Opt-In`, all `Development`.
  Content "SHOULD be recorded in structured form, MAY be a JSON string" if structured unsupported.
- **Opt-in flag (Python/JS contrib instrumentations):**
  `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`, **default `false`**.
  Sources: https://pypi.org/project/opentelemetry-instrumentation-openai-v2/ ;
  https://www.npmjs.com/package/@elastic/opentelemetry-instrumentation-openai
- Granular modes exist in some packages: `NO_CONTENT` / `SPAN_ONLY` / `EVENT_ONLY` / `SPAN_AND_EVENT`.
  Historically content could also go to **log/span events** (`gen-ai-events.md`); current direction is
  structured span attributes. Either way the payload is the same secret-bearing text.
- **The flag name is per-instrumentation, not universal.** Other emitters use other names (e.g. the MS
  Copilot doc shows `...captureContent`, default `false`). Always confirm the flag for the specific
  emitter you wire (kagent / agentgateway / SDK), don't assume the env var name transfers.

### 4. kagent emission + collector

- kagent tracing is **off by default**; enabled via Helm values
  (source: https://www.kagent.dev/docs/kagent/observability/tracing):
  ```yaml
  otel:
    tracing:
      enabled: true
      exporter:
        otlp:
          endpoint: http://jaeger.jaeger.svc.cluster.local:4317   # OTLP gRPC
  ```
- kagent docs demonstrate filtering by an **`agent_run [<agent>]`** operation (e.g.
  `agent_run [k8s-agent]`) in the backend UI. The doc shows Jaeger all-in-one as the example backend.
- The kagent doc does **not** explicitly state GenAI-semconv compliance or whether it captures
  prompt/response content, see Unverified. Treat content capture from kagent as a thing to test, not
  assume.
- **agentgateway** (in front of the agent per the build) emits OTLP traces; its own observability stack
  guide wires an **OTLP receiver (gRPC 4317 / HTTP 4318) → Grafana Tempo** with three collectors
  (metrics/logs/traces) and an `otlp/tempo` exporter.
  Source: https://agentgateway.dev/docs/kubernetes/latest/observability/otel-stack/
  (note: `kgateway.dev/...` 301-redirects to `agentgateway.dev/docs/kubernetes/latest/...`).

**Collector config shape (verified pattern):** standard OTLP receiver on 4317/4318, batch processor,
OTLP exporter to the chosen backend.
```yaml
receivers:
  otlp:
    protocols:
      grpc: { endpoint: 0.0.0.0:4317 }
      http: { endpoint: 0.0.0.0:4318 }
processors:
  batch: {}
exporters:
  otlp/tempo:
    endpoint: tempo.observability.svc.cluster.local:4317
    tls: { insecure: true }
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/tempo]
```

---

## Unverified / Could not confirm

- **"Client/inference spans exited experimental in early 2026."** Spec text contradicts this (still
  Development). Could not find a release marking GenAI client spans Stable. Treat as false until a
  semconv release note proves otherwise.
- **kagent's exact emission detail:** whether kagent natively emits `gen_ai.*` semconv attributes,
  what the `execute_tool` spans look like for its MCP tools, and whether it has a content-capture flag.
  The tracing doc shows only enablement + Jaeger filtering. **Must verify at build by inspecting actual
  emitted spans** (run a trace, read the span attributes).
- Whether agentgateway tags LLM/tool traffic with `gen_ai.*` (its OTel-stack page is generic proxy
  tracing; LLM-specific instrumentation is documented elsewhere or in source). Verify at build.
- No public timeline for GenAI semconv stabilization. (source: 2026 semconv roadmap is open for
  proposals; nothing committed, https://github.com/open-telemetry/semantic-conventions/releases)

---

## Recommended backend + collector config

**Recommend: Grafana Tempo as the trace store + Grafana for the trace-waterfall view, with a
GenAI-aware viewer (Arize Phoenix) as the optional "pretty agent UI" beat.**

Rationale, weighed against the workshop's actual job (show the agent's `execute_tool` calls clearly
inside an already-Grafana-centric IDP):

1. **Tempo is already in-stack alignment.** The IDP runs Prometheus + Grafana (BUILD-SPEC §5).
   agentgateway's own guide already targets Tempo+Grafana. One backend, one UI surface, zero new auth
   for attendees. A trace waterfall in Grafana shows `invoke_agent → plan → execute_tool <toolname>`
   nesting, which is exactly the rogue-MCP-call narration. Trade-off: Tempo gives no LLM-specific UI
   (no prompt diff, no eval views), fine here, the workshop narrates spans, it doesn't eval models.
   (source: https://www.spheron.network/blog/llm-observability-gpu-cloud-langfuse-arize-phoenix-helicone/)
2. **Phoenix as optional GenAI lens.** If you want the "look how readable agent tool calls are"
   moment, Arize Phoenix is OTel-native, self-hostable, and renders agent/tool spans with a purpose
   built UI. It is the cleanest single-binary option for showing tool calls. Langfuse is the heavier
   alternative (Postgres + ClickHouse) and is better for eval/dataset workflows the workshop doesn't
   need. (sources above + https://futureagi.com/blog/what-is-openinference-2026/)

**Decision:** default to **Tempo + Grafana** (no new dependency, matches §5 and agentgateway).
Add **Phoenix** only if §10 open-decision #6 (the 2-hour advanced beat) is built in and you want a
GenAI-styled view. Do NOT pull in Langfuse, its storage footprint is unjustified for N vClusters.

Collector: single OTel Collector on the host stack (already specced), OTLP receiver 4317/4318,
batch + (critically) a **redaction processor by default**, see trap below, exporting to Tempo.

---

## Re-leak trap design

**The mechanism:** Attack 4 plants `FAKE-PROD-DB-PASSWORD-sentinel-9f2a` and the agent reads it. The
output guardrail (agentgateway → LLM Guard) inspects the agent's *response to the user*. But if OTel
content capture is ON, the same secret rides into the **trace** via `gen_ai.input.messages` /
`gen_ai.output.messages` / `gen_ai.system_instructions` (and into tool args on the `execute_tool`
span). Observability becomes a **second, unguarded exfil channel**, the response guardrail never sees
the span pipeline. Anyone with Grafana/Tempo read access reads the planted secret. This is the §4 trap
made concrete: the thing you added for safety leaks the thing you were protecting.

**Why it's a clean teaching beat:** the default is your friend. Content capture is `false` by default
(`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false`). So the trap requires *deliberately*
turning it on, which is the demo. You flip one flag, re-run attack 4, and the sentinel appears in the
span attributes in Grafana even with the output guardrail enabled. The lesson: guardrails must cover
*every* sink, not just the user-facing response.

**Safe way to demo it (mandatory controls):**
1. **Default OFF.** Per BUILD-SPEC Phase 1, the collector/agent ship with content capture disabled.
   The trap is opt-in and lives only in the 2-hour version.
2. **Only the fake sentinel is ever in scope.** BUILD-SPEC §3: no real credential ever enters cluster,
   traces, or recordings. The re-leaked value is `FAKE-...-sentinel-...` by construction, so the demo
   leaks nothing real.
3. **Belt-and-suspenders redaction in the Collector** even when capture is on for the beat: add an
   `attributes`/`redaction` or `transform` processor that masks `gen_ai.input.messages`,
   `gen_ai.output.messages`, `gen_ai.system_instructions` (regex on the sentinel prefix), then the beat
   can show "capture on, secret in span" *then* "redaction processor on, secret masked in span" as the
   collector-side mitigation, mirroring the response-side guardrail. This makes the lesson symmetric:
   inspect/redact at the response sink AND the telemetry sink.
4. **Tear down trace data** in teardown (Phase 9) so no span store retains even the fake value post-run.

---

## Risks for the build

1. **Attribute-name churn.** All GenAI semconv is `Development`; names can change between semconv
   releases. Pin the emitter versions, set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`
   consciously, and record actual emitted attribute names in `VERSIONS.lock`. Don't hardcode
   attribute names into dashboards from this doc without confirming against live spans.
2. **kagent emission is unconfirmed for semconv + content.** If kagent doesn't emit `execute_tool` /
   `gen_ai.tool.name` natively, the "narrate the tool call from the trace" beat weakens. Verify by
   capturing a real trace in Phase 3, before building dashboards or the re-leak beat on top of it.
   If kagent emits only `agent_run` operations without tool spans, you may need agentgateway or SDK
   instrumentation to surface tool calls.
3. **Per-instrumentation flag names differ.** The content-capture toggle is not one universal env var.
   Confirm the exact flag for whatever actually emits content (kagent vs agentgateway vs SDK) before
   relying on "default false", a wrong assumption here either silently leaks (trap fires early) or the
   beat won't fire at all.
4. **Trace store is an access-control surface.** Whoever can reach Grafana/Tempo can read whatever is in
   spans. Even with fake secrets, scope Grafana access for attendees and keep content capture off on the
   shared default path.
5. **Marketing "stable" claims will mislead.** Third-party blogs assert GenAI spans are stable; the spec
   says otherwise. Anchor all slides/copy to the spec, not blogs, or the talk will state something false.
