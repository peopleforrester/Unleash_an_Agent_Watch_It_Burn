# 16. TypeScript agent rewrite: "Spiny", "Weaver", and the framework landscape (2026)

## CORRECTION (2026-06-21): Spiny/Weaver identified from the primary source

Michael supplied the actual source: **https://github.com/wiggitywhitney/spinybacked-orbweaver**.
This SUPERSEDES the speculative "Spiny = Pixie" / "Weaver = standalone OTel Weaver" identification
further down (sections 1 and 2 below were guesses made before the repo link was available).

The real facts (from the repo README):

- **"Spiny" = `spiny-orb` (spinybacked-orbweaver)** — Whitney's own AI agent that **automatically
  adds OpenTelemetry instrumentation to JavaScript/TypeScript codebases**. It analyzes JS/Node
  source, generates instrumented code with Claude, validates against a Weaver semconv registry and
  the Instrumentation Score spec, and opens a PR. TypeScript (99.5%), Node >= 24.
- **"Weaver" = OpenTelemetry Weaver**, used BY spiny-orb (Weaver CLI >= 0.21.2) for schema
  validation. So "Spiny or Weaver" is effectively one toolchain: spiny-orb, which uses Weaver.
- **Interfaces:** CLI (`npm i -g spiny-orb`; `spiny-orb instrument src/`), an **MCP server**
  (`npx spiny-orb mcp`, tools `get-cost-ceiling` + `instrument`), and a **GitHub Action**
  (`uses: wiggitywhitney/spinybacked-orbweaver@main`). Per-project config `spiny-orb.yaml`
  (`schemaPath`, `sdkInitFile`, `agentModel`, `targetType`, `dependencyStrategy`); needs
  `ANTHROPIC_API_KEY`. Generated code imports only `@opentelemetry/api`.

**The load-bearing implication (reverses the old Pixie-based conclusion):** spiny-orb instruments
**JS/TS only — it cannot instrument the Python kagent/ADK agent or the Python guard-proxy.** So for
Whitney to "hook spiny-orb in," there must be JavaScript/TypeScript code in the workshop for it to
run against. This makes the TypeScript path a genuine requirement, not cosmetic. The earlier
"language-agnostic, TS buys nothing" note (written under the wrong Pixie assumption) is VOID.

**UPDATE (Michael, 2026-06-21) — ON HOLD:** the optional TypeScript agent is DEFERRED until after
the demo is finished. We are sticking with kagent only for now; adding a second agent framework is
unnecessary complexity before the demo works end to end. A comment to this effect is on one of the
shared Google Docs. The analysis below stays as the record for when/if the TS option is revisited;
do NOT start building the TS agent until Michael reopens it.

**Earlier decision (now superseded by the hold above):** keep the kagent-managed Python agent as
primary/fallback; ADD an OPTIONAL TypeScript agent so spiny-orb can instrument it. Recommended shape
was **Option B** below:
a TS agent (Mastra or Vercel AI SDK) wrapped as a kagent `type: BYO` A2A backend, keeping
agentgateway + MCP + HITL + LLM Guard. Ship a `spiny-orb.yaml` + a Weaver semconv registry +
an OTel SDK init file in the TS component so `spiny-orb instrument` works out of the box and its
generated spans flow through the existing OTel Collector to Datadog. Open items to verify live:
kagent BYO does not emit `adk_usage_metadata` (cost-counter dependency) and whether `requireApproval`
HITL + MCP `toolNames` survive for a BYO agent (see section 5).

---

Research spike for the "Watch It Burn" Kubernetes AI-security workshop. Whitney Lee
(co-presenter) wants the demo agent rewritten in TypeScript so she can "easily hook it
into Spiny or Weaver" and drive the observability story with Datadog. This doc identifies
what Spiny and Weaver most likely are, maps the realistic TypeScript agent options that
integrate with those tools plus Datadog/OpenTelemetry, and ranks concrete rewrite
approaches against the existing in-repo system.

## Verification Method

- **Approach:** Web research only, dated 2026-06-21. No code was written, built, or run.
  No live kagent cluster, npm install, or telemetry capture was performed in this spike.
- **Existing-system facts** (kagent v1alpha2, ADK under the hood, A2A, agentgateway, MCP
  `toolNames`, `requireApproval`, Bedrock Claude, guard-proxy reading `adk_usage_metadata`,
  LLM Guard, OTel Collector -> Datadog with Tempo/Grafana fallback) are taken as given from
  the task brief and prior in-repo research (notably `research/14-verify-at-build-sweep-2026.md`).
  They were not independently re-verified against the live cluster here.
- **Every package name, version, CRD field, and API claim below is attributed to a primary
  or near-primary source URL.** Where a claim could not be confirmed from a primary source
  it is marked UNCERTAIN. Re-verify version numbers and the exact A2A metadata key against a
  live response at build time before the event, per `research/14`.

### Primary sources consulted

- Whitney Lee personal site: https://whitneylee.com/
- Whitney Lee, "Pixie: Instant Kubernetes Visibility with eBPF":
  https://whitneylee.com/2025/11/02/pixie-instant-kubernetes-visibility-with.html
- Whitney Lee LinkedIn (title): https://www.linkedin.com/in/whitneylee/
- SREday Austin 2026 talk listing:
  https://sreday.com/2026-austin-q2/Whitney_Lee_Datadog_Your_Internal_Developer_Platforms_Next_Interface_Is_an_AI_Agent
- Pixie project: https://px.dev/ and https://docs.px.dev/about-pixie/what-is-pixie/
- Pixie OpenTelemetry plugin: https://www.cncf.io/blog/2022/07/06/easy-observability-with-open-standards-introducing-the-pixie-plugin-system/
- OTel Weaver repo: https://github.com/open-telemetry/weaver
- OTel Weaver blog: https://opentelemetry.io/blog/2025/otel-weaver/
- OTel code generation guide: https://opentelemetry.io/docs/specs/semconv/non-normative/code-generation/
- OTel GenAI semconv: https://opentelemetry.io/docs/specs/semconv/gen-ai/ and
  https://opentelemetry.io/blog/2026/genai-observability/
- Datadog "LLM Observability natively supports OpenTelemetry GenAI Semantic Conventions":
  https://www.datadoghq.com/blog/llm-otel-semantic-convention/
- Datadog Node.js auto-instrumentation: https://docs.datadoghq.com/llm_observability/instrumentation/auto_instrumentation/
- Anthropic TS SDK (Bedrock): https://www.npmjs.com/package/@anthropic-ai/bedrock-sdk and
  https://github.com/anthropics/anthropic-sdk-typescript
- Vercel AI SDK Bedrock provider: https://ai-sdk.dev/providers/ai-sdk-providers/amazon-bedrock
- Vercel AI SDK 6 (MCP stable, OTel): https://vercel.com/blog/ai-sdk-6
- Mastra: https://mastra.ai/ , https://github.com/mastra-ai/mastra ,
  https://mastra.ai/guides/deployment/aws-bedrock-agentcore
- LangChain.js MCP adapters: https://www.npmjs.com/package/@langchain/mcp-adapters and
  https://js.langchain.com/docs/integrations/llms/bedrock/
- OpenAI Agents SDK (JS/TS): https://openai.github.io/openai-agents-js/ and
  https://openai.github.io/openai-agents-js/guides/mcp/
- kagent BYO examples index: https://www.kagent.dev/docs/kagent/examples
- kagent BYO A2A doc: https://www.kagent.dev/docs/kagent/examples/a2a-byo

---

## Q1. "Spiny" -- most likely Pixie (eBPF observability), heard phonetically

**CONFIRMED facts:**

- Whitney Lee is **Senior Technical Advocate at Datadog** (LinkedIn title; her site and the
  SREday 2026 listing both put her under Datadog). Her 2026 talk theme is literally
  "Your Internal Developer Platform's Next Interface Is an AI Agent" (SREday Austin 2026),
  which is the same conceptual frame as this workshop's demo agent.
- She actively advocates **Pixie** -- an eBPF-based, zero-instrumentation Kubernetes
  observability tool. She published a dedicated piece, "Pixie: Instant Kubernetes Visibility
  with eBPF" (2025-11-02) and covered it on her "Thunder" video series. Pixie is a CNCF
  project (https://px.dev/, https://docs.px.dev/).
- Pixie captures telemetry from the Linux kernel via eBPF with **no application code
  changes**, and it has an **OpenTelemetry plugin system** that exports traces/metrics to
  OTel-compatible backends including Datadog
  (https://www.cncf.io/blog/2022/07/06/easy-observability-with-open-standards-introducing-the-pixie-plugin-system/).

**ASSESSMENT (high confidence, not 100%): "Spiny" is almost certainly "Pixie."**

- "Pixie" -> "Spiny" is a very plausible voice-transcription / mishearing. The word is
  short, the consonant cluster is unusual, and Pixie is the single tool in Whitney's current
  rotation that (a) she personally champions, (b) is CNCF/Kubernetes-native (fits the
  workshop), and (c) is fundamentally an *observability* tool, which matches the phrasing
  "hook it into Spiny ... drive the observability story with Datadog."
- There is **no Datadog product, OTel tool, or agent framework literally named "Spiny."**
  Searches across Datadog's 2026 AI lineup (Bits AI Agents, Agent Observability, Bits Agent
  Builder, AI Agents Console, AI Guard) return nothing called Spiny. So Spiny is not a
  product name; it is a referent to something Whitney works with.

**What "hooking a TS agent into Pixie" concretely means:** essentially **nothing extra in
the agent code.** Pixie auto-instruments at the kernel via eBPF, so a Node/TS agent's HTTP,
gRPC, and traffic-level telemetry is captured without an SDK. The agent does not "integrate"
with Pixie in the SDK sense; it just runs in a cluster where Pixie is installed, and Pixie's
OTel plugin forwards data to Datadog. The TS rewrite is therefore **largely orthogonal to
Pixie** -- Pixie sees any workload regardless of language. (UNCERTAIN: whether Whitney wants
Pixie's network-level view *or* deeper app spans; eBPF gives wire-level visibility but not
semantic GenAI spans like `gen_ai.usage.input_tokens` -- those still require app-level OTel.)

**Top alternative candidates (lower probability), in case Spiny is something else:**

1. **A Datadog AI feature** (e.g. "Bits") misheard -- possible but no phonetic match to
   "Spiny," and none of Datadog's named products fit. LOW.
2. **SpinKube / Spin** (WebAssembly on Kubernetes, https://www.spinkube.dev/) -- "Spin" is
   phonetically closer than most, and it is CNCF/Kubernetes-native. But it is a Wasm runtime,
   not an observability tool, and does not fit "drive the observability story." LOW-MEDIUM.
3. **Spinnaker / Sapling / Spline** -- no connection to Whitney's current work or to AI agent
   observability. VERY LOW.

**Recommendation for Q1:** Treat Spiny as **Pixie** unless Whitney corrects it. Ask her
directly to confirm (one sentence), because the answer changes nothing about the agent
language choice (Pixie is language-agnostic) but does change what we claim on stage.

---

## Q2. "Weaver" -- OpenTelemetry Weaver (semconv tooling / codegen / live-check)

**CONFIRMED:**

- **OpenTelemetry Weaver** is the official OTel "CLI and automation platform that helps you
  manage, validate, and evolve semantic conventions and observability workflows"
  (https://opentelemetry.io/blog/2025/otel-weaver/, https://github.com/open-telemetry/weaver).
- It does two things relevant here:
  1. **Code generation from a semantic-convention registry** -- "auto-generated constants and
     code in their native language, ensuring no typos or inconsistencies." Per the blog,
     current codegen targets are **Go, Java, and Markdown docs**; type-safe instrumentation
     helpers for more languages are explicitly described as **still in development**
     ("We're also working on more advanced solutions to automatically generate type-safe
     instrumentation helpers (Go, Rust, ...)"). The OTel codegen guide confirms all semconv
     codegen "should be done using weaver," based on YAML semconv definitions, supported from
     semconv **>= 1.26.0** (https://opentelemetry.io/docs/specs/semconv/non-normative/code-generation/).
  2. **Live-check / CI validation** -- `weaver registry live-check` "generates a compliance
     report of the signals emitted by your application against a registry," runnable directly
     in CI/CD. Weaver also supports registry dependency chains (a->b->c, max depth 10), so a
     narrow application registry can depend on the upstream OTel registry.

**Alternatives ruled out:** "Weaviate" (vector DB) and any "Cloudflare Weaver" do not fit
the observability framing or Whitney's OTel-centric work. Given she advocates OpenTelemetry
heavily and pairs it with Datadog, **Weaver = OpenTelemetry Weaver. HIGH confidence.**

**What "hooking a TS agent into Weaver" concretely means:**

- **TypeScript/JavaScript codegen is NOT a confirmed Weaver target as of mid-2026**
  (CONFIRMED gap: the Weaver blog lists Go/Java/Markdown, not TS). So you cannot today
  promise "Weaver generates our typed TS attribute constants" without verifying a JS template
  exists. UNCERTAIN: community Weaver templates may target TS via Jinja templates (Weaver is
  template-driven), but this needs a build-time check against the Weaver examples repo
  (https://github.com/open-telemetry/opentelemetry-weaver-examples) before claiming it.
- The **solid, demoable Weaver fit is CI live-check**: point `weaver registry live-check` at a
  registry that includes the **GenAI semantic conventions** (https://github.com/open-telemetry/semantic-conventions-genai)
  and validate that the agent's emitted spans use the right attributes
  (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.operation.name`, etc.). This
  is **language-agnostic** -- Weaver checks the telemetry, not the source. A TS agent and a
  Python agent are validated identically. So, like Pixie, **Weaver does not require the
  rewrite to be in TS.**

**Net for Q2:** Weaver's value here is "validate our GenAI telemetry against the semconv
registry in CI" (works regardless of agent language). Typed-TS-attribute codegen from Weaver
is speculative and must be verified before it is promised on stage.

---

## Q3. TypeScript agent frameworks (2026): Bedrock + MCP + A2A/HTTP + OTel/Datadog

Requirements scored: (a) AWS Bedrock + Claude, (b) MCP tool calling, (c) A2A-compatible or
HTTP serving endpoint, (d) clean OTel GenAI-semconv + Datadog instrumentation.

### 3.0 The official Anthropic TypeScript SDK + Bedrock (the building block)

- **Package: `@anthropic-ai/sdk`** (core) and **`@anthropic-ai/bedrock-sdk`** for Bedrock,
  both confirmed on npm (https://www.npmjs.com/package/@anthropic-ai/bedrock-sdk) and in the
  monorepo https://github.com/anthropics/anthropic-sdk-typescript (the `bedrock-sdk` package
  lives under `packages/bedrock-sdk`).
- `AnthropicBedrock` extends `BaseAnthropic`, rewrites Anthropic API paths to Bedrock
  endpoints, and applies AWS SigV4 signing. Install: `npm install @anthropic-ai/bedrock-sdk`.
  Runtime: Node.js 18 LTS+ (also Deno >= 1.28, Bun >= 1.0), TypeScript >= 4.5.
- This is the **lowest-level, most certain** path to Claude-on-Bedrock from Node, but it is a
  model client, not an agent framework: you build the tool loop, MCP wiring, and A2A serving
  yourself.

### 3.1 Vercel AI SDK -- strong all-rounder

- **Bedrock + Claude: CONFIRMED.** Provider package **`@ai-sdk/amazon-bedrock`**, used as
  `bedrock('anthropic.claude-3-5-sonnet-20241022-v2:0')` or with a regional inference profile
  id like `'us.anthropic.claude-sonnet-4-5-20250929-v1:0'`; tool usage supported
  (https://ai-sdk.dev/providers/ai-sdk-providers/amazon-bedrock). NOTE: Bedrock's Anthropic
  path uses the native InvokeModel API and does **not** support the Anthropic Files API or the
  server-side MCP Connector -- you use client-side MCP instead.
- **MCP: CONFIRMED stable in AI SDK 6** -- "MCP support is now stable" in package
  **`@ai-sdk/mcp`**, covering OAuth, resources, prompts, elicitation (https://vercel.com/blog/ai-sdk-6).
- **A2A / serving:** No built-in A2A server; you expose your own HTTP route (trivial in
  Next.js/Node). Would need a hand-written A2A adapter to slot into kagent (see Q5).
- **OTel/Datadog: CONFIRMED.** AI SDK emits OpenTelemetry tracing (experimental flag), and
  Datadog explicitly lists it as analyzable; `dd-trace` Node auto-instruments the `ai` package
  (>= 4.0.0) -- see Q4.
- **Maturity:** High; AI SDK 6 is current. Broadest provider coverage. Best "general TS agent"
  default if not constrained to A2A-native serving.

### 3.2 Mastra -- best A2A/Kubernetes fit

- **Bedrock + Claude: CONFIRMED** via the Bedrock AgentCore deployment guide
  (https://mastra.ai/guides/deployment/aws-bedrock-agentcore); Mastra supports any LLM
  including Claude.
- **MCP: CONFIRMED.** Mastra can both consume MCP tools and author/expose MCP servers
  (https://mastra.ai/).
- **A2A: CONFIRMED and notable.** Container deployment "exposes port 8080 (HTTP), port 8000
  (MCP), and port 9000 (A2A), with OpenTelemetry instrumentation included automatically at
  startup" (Bedrock AgentCore guide). A built-in A2A port is the single best match for slotting
  into kagent's A2A serving path.
- **OTel/Datadog: CONFIRMED.** OTel instrumentation built in; integrates with any
  OTel-compatible backend (Datadog included), plus an experimental OTel bridge (as of 2026).
- **Maturity:** Production users cited (Brex, Docker, Elastic, MongoDB, Salesforce, Replit,
  SoftBank). From the ex-Gatsby team. Strong and rising. The A2A + MCP + OTel triad out of the
  box is uniquely aligned with this stack.

### 3.3 LangGraph.js / LangChain.js

- **Bedrock + Claude: CONFIRMED** via `js.langchain.com` Bedrock integration
  (https://js.langchain.com/docs/integrations/llms/bedrock/).
- **MCP: CONFIRMED.** **`@langchain/mcp-adapters`** converts MCP tools to LangChain/LangGraph
  tools across multiple servers, stdio + SSE transports
  (https://www.npmjs.com/package/@langchain/mcp-adapters).
- **A2A / serving:** No first-class A2A; LangGraph is the runtime, serving is yours to build.
  kagent does ship a **BYO LangGraph** example (Q5), which is a meaningful advantage -- there is
  a documented path for a LangGraph (Python) agent; the JS variant would need the same A2A
  wrapper.
- **OTel/Datadog: PARTIAL.** `dd-trace` Node auto-instruments `langchain` (>= 0.1.0). OTel
  GenAI-native span coverage for LangGraph is described upstream as "in progress" (OTel GenAI
  blog), so semconv fidelity should be verified, not assumed.
- **Maturity:** High and widely deployed, heavier abstraction. Good if the team already knows
  LangGraph; otherwise more weight than the demo needs.

### 3.4 OpenAI Agents SDK for TypeScript

- **Package `@openai/agents`** (https://openai.github.io/openai-agents-js/), v0.17.5 as of
  2026-06-11, still pre-1.0.
- **Bedrock + Claude: INDIRECT.** No native Bedrock provider; non-OpenAI models go through the
  LiteLLM extension or a custom `ModelProvider`. Bedrock routing is "best-effort / beta" via
  LiteLLM (https://docs.litellm.ai/docs/tutorials/openai_agents_sdk). Adds a dependency and a
  beta seam right on the model path -- a poor fit when Bedrock is the requirement.
- **MCP: CONFIRMED** (https://openai.github.io/openai-agents-js/guides/mcp/).
- **A2A / serving:** No built-in A2A.
- **OTel/Datadog:** Has its own tracing; OTel/Datadog mapping less direct than AI SDK or Mastra.
- **Maturity:** Pre-1.0; default model is an OpenAI model. **Weakest fit** given the
  Bedrock-Claude hard requirement.

### 3.5 kagent-native (the incumbent)

- kagent's first-class agents are **declarative ADK (Python)**; it also supports **BYO**
  agents in CrewAI, LangGraph, and ADK that speak A2A (Q5). There is **no kagent-native TS
  agent SDK**; kagent-native means "speak A2A and wrap as a BYO Agent CRD," which any TS
  framework can do with an A2A adapter.

### Q3 summary table

| Framework | Bedrock+Claude | MCP | A2A / serving | OTel + Datadog | Maturity | Fit |
|---|---|---|---|---|---|---|
| Anthropic TS SDK (`@anthropic-ai/bedrock-sdk`) | Native, CONFIRMED | DIY | DIY HTTP | dd-trace `@anthropic-ai/sdk` >=0.14 | GA | Building block |
| Vercel AI SDK (`@ai-sdk/amazon-bedrock` + `@ai-sdk/mcp`) | CONFIRMED | Stable (AI SDK 6) | DIY HTTP | CONFIRMED | High | Strong general |
| Mastra | CONFIRMED | CONFIRMED | **Built-in A2A:9000** | CONFIRMED | High | **Best A2A fit** |
| LangGraph.js (`@langchain/mcp-adapters`) | CONFIRMED | CONFIRMED | DIY (BYO-LangGraph exists) | Partial | High | Good |
| OpenAI Agents SDK (`@openai/agents`) | Via LiteLLM beta | CONFIRMED | DIY | Indirect | Pre-1.0 | Weak |

---

## Q4. Datadog + OTel for a Node/TS agent (2026 recommended path)

**CONFIRMED, two supported routes:**

1. **Datadog Node tracer (`dd-trace`) with LLM Observability auto-instrumentation.**
   - npm package **`dd-trace`** (typically >= 5.25.0 for LLM integrations). Initialize with
     LLM Observability config; integrations are **on by default, no app code changes**
     (https://docs.datadoghq.com/llm_observability/instrumentation/auto_instrumentation/).
   - Auto-instrumented Node libraries with minimum versions (CONFIRMED from that page):
     - Amazon Bedrock: **`@aws-sdk/client-bedrock-runtime` >= 3.422.0**
     - Anthropic: **`@anthropic-ai/sdk` >= 0.14.0**
     - OpenAI/Azure: `openai` >= 3.0.0
     - LangChain: `langchain` (+ partner packages) >= 0.1.0
     - Vercel AI SDK: `ai` >= 4.0.0
     - Vertex AI / Google GenAI also listed.
   - This is the **lowest-friction** path: pick any framework above, run with `dd-trace`,
     get LLM spans + token usage + cost in Datadog LLM Observability automatically.

2. **OTel-native -> Datadog (no Datadog SDK required).** Datadog LLM Observability
   **natively ingests OpenTelemetry GenAI spans** following **semconv v1.37+**
   (https://www.datadoghq.com/blog/llm-otel-semantic-convention/). Instrument the TS agent
   with `@opentelemetry/sdk-node` + `@opentelemetry/api` + an OTLP exporter, emit GenAI
   semconv attributes, and send via the existing **OTel Collector -> Datadog** pipeline (or
   the Datadog Agent in OTLP mode). Datadog auto-maps `gen_ai.request.model`,
   `gen_ai.usage.input_tokens`, `gen_ai.provider.name`, `gen_ai.operation.name` to its native
   schema -- **no code changes** beyond standard OTel.

**Important caveat (CONFIRMED):** OTel GenAI + MCP semantic conventions are still in
**Development** status as of mid-2026; v1.36 is the transition baseline and the latest
attribute format requires `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`
(https://opentelemetry.io/blog/2026/genai-observability/). Tool-call-as-first-class-span and
GenAI framework auto-instrumentation in JS are uneven; budget manual span work for tool calls.

**Recommendation for Q4:** Because the repo already runs **OTel Collector -> Datadog**, route 2
(OTel-native, semconv 1.37+) keeps the pipeline unchanged and is vendor-neutral (Tempo/Grafana
fallback keeps working). Route 1 (`dd-trace`) is the fast win for the LLM client spans and live
cost counter. The two compose: `dd-trace` for automatic Bedrock/Anthropic spans, explicit OTel
spans for tool calls and the agent loop, all landing in Datadog.

---

## Q5. kagent interop -- can a hand-written TS agent be a BYO A2A backend?

**CONFIRMED -- yes, via kagent's "Bring Your Own Agent" (BYO) mechanism.**

From https://www.kagent.dev/docs/kagent/examples and the BYO A2A doc
(https://www.kagent.dev/docs/kagent/examples/a2a-byo):

- kagent ships BYO examples for **ADK, CrewAI, and LangGraph** agents. BYO agents "give you
  full control over agent logic," unlike inline declarative agents.
- Registration is a **standard kagent Agent CRD with `type: BYO`** and a `byo.deployment.image`:
  ```yaml
  apiVersion: kagent.dev/v1alpha2
  kind: Agent
  metadata:
    name: basic-agent
  spec:
    type: BYO
    byo:
      deployment:
        image: ghcr.io/my-org:latest
  ```
- The external agent must **implement the A2A protocol**: expose an agent card at
  **`.well-known/agent.json`** (capabilities, input/output modes, skills, streaming) and an
  A2A endpoint, reachable via the kagent controller service on **port 8083**.
- The A2A response carries usage as **`adk_usage_metadata`** (this is ADK's key; the example
  shows `promptTokenCount` / `candidatesTokenCount` / `totalTokenCount` plus
  `promptTokensDetails`/`candidatesTokensDetails` by modality). The guard-proxy's cost counter
  reads exactly this key. **A non-ADK TS agent will NOT emit `adk_usage_metadata` for free** --
  it would have to populate that metadata key itself in its A2A responses, or the guard-proxy
  must be taught to read the TS agent's own usage key. (UNCERTAIN/important: this is the single
  biggest interop gotcha -- re-verify the exact metadata key a TS A2A agent should emit against
  a live response at build, per `research/14`.)

**What a TS A2A agent must implement to slot in (CONFIRMED requirements + reasoned gaps):**

1. Serve the **A2A protocol** over HTTP, including the **`.well-known/agent.json`** agent card.
2. Be packaged as a **container image** referenced by a `type: BYO` Agent CRD (`v1alpha2`).
3. Populate usage metadata in A2A responses so the cost counter works (currently
   `adk_usage_metadata`; confirm the expected key for a non-ADK agent).
4. Honor the HITL/`requireApproval` and MCP `toolNames` flow. **UNCERTAIN:** the BYO doc does
   **not** explicitly confirm that `requireApproval` and the agentgateway MCP `toolNames`
   allowlist apply unchanged to a BYO agent. `requireApproval` and MCP gating in the current
   setup operate at the kagent/agentgateway serving layer in front of the agent, which
   suggests they continue to apply to any A2A backend, but this **must be verified on a live
   BYO deployment** before relying on it for the security demo. If approval/HITL is enforced
   inside the ADK runtime rather than the gateway, a BYO TS agent would lose that gate and it
   would have to be reimplemented in TS.

**Net for Q5:** kagent explicitly supports BYO A2A backends, and there is a clear, documented
slot for a hand-written agent. The Python BYO examples (ADK/CrewAI/LangGraph) prove the path;
a TS A2A agent is not a listed example but is not precluded -- it just needs to speak A2A,
ship the agent card, and emit the right usage metadata. The open risks are (1) usage-metadata
key compatibility and (2) whether HITL + MCP allowlist survive at the gateway for a BYO agent.

---

## Options for the rewrite

Three concrete approaches, ranked. Each lists what it touches in this repo, the
Datadog/Spiny(Pixie)/Weaver fit, effort, and risk.

### Option B (RECOMMENDED): TS agent as a kagent BYO A2A backend, keep gateway + MCP + HITL

Rewrite only the agent brain in TypeScript, package it as a container, and register it with a
`type: BYO` Agent CRD so it sits behind the **same agentgateway, MCP `toolNames` allowlist,
and `requireApproval` HITL machinery**. Best framework: **Mastra** (built-in A2A:9000, MCP,
Bedrock, OTel out of the box) or **Vercel AI SDK** + a thin A2A adapter.

- **Touches:** new `agent/` TS service + Dockerfile; one Agent CRD changed from declarative to
  `type: BYO`; guard-proxy's usage-key parsing (`adk_usage_metadata` -> the TS agent's emitted
  key); leaves agentgateway, MCP allowlist, LLM Guard, and the OTel->Datadog pipeline in place.
- **Datadog/Pixie/Weaver fit:** Excellent. `dd-trace` Node auto-instruments Bedrock/Anthropic;
  OTel-native GenAI spans flow through the existing collector to Datadog; Pixie sees the new
  pod with zero changes; Weaver live-check validates the emitted GenAI semconv in CI.
- **Effort:** Medium. **Risk:** Medium -- the two Q5 unknowns (usage-metadata key; whether
  HITL/MCP gating survives for BYO) must be verified on a live BYO deploy before the event.
- **Why recommended:** It gives Whitney the TS agent she wants and the clean Datadog/Weaver
  story, while preserving the security mechanisms (HITL, MCP allowlist, LLM Guard, gateway)
  that are the whole point of "Watch It Burn." Smallest blast radius.

### Option C (LOWEST RISK): Keep kagent/ADK; add TS only at the instrumentation/edge layer

Do not rewrite the agent. If Whitney's real goal is the Datadog + Pixie + Weaver observability
narrative, that is **language-agnostic**: Pixie auto-instruments via eBPF regardless of
language, Weaver validates emitted telemetry regardless of language, and Datadog ingests OTel
GenAI semconv from the current pipeline. Any TS she wants can live in a small dashboard/edge
shim, not the agent.

- **Touches:** essentially nothing in the agent; possibly OTel semconv attributes + a Weaver
  CI live-check job; optional TS shim for demo UI.
- **Fit:** Excellent on observability, but does **not** deliver "the agent is in TypeScript."
- **Effort:** Low. **Risk:** Low.
- **When to pick:** If, after asking Whitney, "hook into Spiny/Weaver" turns out to mean
  "show it in Pixie and validate with Weaver" rather than "the agent source must be TS."

### Option A (HIGHEST RISK): Full standalone TS agent replacing kagent

Rip out kagent and build a standalone TS agent (Vercel AI SDK or Mastra) that calls Bedrock,
does MCP tool calling, serves its own HTTP/A2A, and reimplements HITL, the MCP allowlist, and
LLM Guard integration itself.

- **Touches:** removes kagent Agent/ModelConfig CRDs, agentgateway fronting, and the
  kagent-mediated MCP/HITL path; reimplements approval gating, tool allowlisting, and guard
  scanning in/around the TS service; rewires OTel.
- **Fit:** Clean greenfield Datadog/OTel/Weaver story; Pixie still free.
- **Effort:** High. **Risk:** High -- you rebuild the exact security mechanisms the workshop
  is meant to showcase, and lose the "declarative kagent on Kubernetes" framing that grounds
  the demo. Not advised unless the workshop narrative deliberately pivots away from kagent.

### Recommendation

**Go with Option B**, with two gating verifications before committing on stage:

1. **Ask Whitney to confirm "Spiny" = Pixie** (and confirm "Weaver" = OTel Weaver). One
   message. Neither tool forces the agent language, so this de-risks the *claims*, not the code.
2. **Live-verify on a BYO deploy** (per `research/14`): (a) the exact usage-metadata key a TS
   A2A agent should emit so the cost counter keeps working, and (b) that `requireApproval`
   HITL and the agentgateway MCP `toolNames` allowlist still apply to a `type: BYO` agent.

Use **Mastra** as the default TS framework (native A2A + MCP + Bedrock + OTel is the tightest
fit to this stack), with **Vercel AI SDK** as the fallback if a lighter, less opinionated
build is preferred. Instrument with `dd-trace` for automatic Bedrock/Anthropic spans plus
explicit OTel GenAI spans for tool calls, all flowing through the existing OTel Collector ->
Datadog pipeline. If it later turns out the TS requirement is soft and the ask is really the
observability story, **fall back to Option C** -- it delivers the Pixie/Weaver/Datadog
narrative with near-zero risk.
