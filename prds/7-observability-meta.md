# PRD #7 — Observability Suite (Meta-PRD)

**GitHub Issue:** [#7](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7)
**Status:** In Progress
**Priority:** High
**Last updated:** 2026-06-24

---

## How To Use This Meta-PRD (read first)

This is a **meta-PRD**: its milestones do not implement observability directly. Each milestone is a
design conversation with Whitney that produces a **child PRD** (via `/prd-create`) implementing one
**vertical milestone** of the observability strategy — a thin end-to-end increment that is verifiable in
the Datadog UI on its own.

**Walking-skeleton ordering.** Milestone 1 is a minimal end-to-end MVP: real telemetry visible in one
Datadog trial account. Each later milestone adds exactly one capability that can be verified in the
Datadog UI before the next begins. We do NOT build horizontal layers that show nothing until several
are done.

**Design order = build order, pipelined.** Michael's build system implements each child PRD as soon
as it is written. Therefore **every child PRD must be buildable on only what earlier milestones already
built — never on a later milestone.** This is the `prd-dependency-management` rule: each PRD is mergeable
on top of `main` as it exists. We design Milestone N, hand it off, and design Milestone N+1 while Milestone N is
built.

**Each milestone is executed by a fresh AI instance with no memory of prior milestones.** Every
milestone lists exactly what to read in its Step 0. Do not assume context carries over. If a
milestone is unclear without conversation history, that is a bug in this document — fix it, do not
guess.

**Scope guard (every milestone): do NOT implement the observability change itself in a meta-PRD
milestone.** Your only deliverable is the child PRD (and, where noted, a research spike). Do not edit
`otel-collector.yaml`, manifests, app code, or Datadog config here — that work belongs to the child
PRD's own `/prd-start` → `/prd-done` lifecycle. If you find yourself editing implementation files,
stop: you have left this milestone's scope.

**Decisions are documented in the PRDs themselves.** No separate `docs/planning/` files. Record every
design decision in the relevant child PRD's Decision Log via `/prd-update-decisions`. Record
meta-level decisions in this file's Decision Log.

**Branch model.** This meta-PRD is worked via `/prd-start 7`, which creates one working branch. Every
milestone commits to that same branch — `/prd-update-progress` commits and pushes it (this is how
Michael sees progress). Do NOT commit to main and do NOT open a branch per milestone. `/prd-done`
opens the single PR when all milestones are complete. Each child PRD gets its own working branch via
its own `/prd-start` when it is later implemented — separate from this meta-PRD's branch.

---

## Repository Conventions (the implementing AI MUST follow these)

Before creating any file, read sibling files in the target directory and match their structure,
naming, and style. Specifically:

- **Research spikes:** `research/NN-topic-2026.md`, where `NN` continues the existing sequence. The
  highest existing spike is `research/33-*`; use the next sequential number at time of execution.
  Research spikes always live in `research/`, never elsewhere.
- **PRD files:** `prds/[issue-id]-[feature-name].md`, where `[issue-id]` is the real GitHub issue
  number created by `/prd-create`. Do not invent sequential slugs.
- **GitOps manifests:** match the existing layout under `gitops/` and `agent/`. Do not introduce a
  new directory structure without reading what is already there.
- **Docs:** workshop/architecture docs live in `docs/`; transcripts in `docs/transcripts/`.
- **PROGRESS.md / ROADMAP.md:** follow the Keep a Changelog style already in those files.
- When in doubt about where something goes, read the existing tree first and conform to it.

---

## Background Reading (every milestone reads this in Step 0)

- `docs/BUILD-SPEC.md` — demo beats, attendee journey, the user experience the workshop sells
- `docs/BUILD-PLAN.md` — current build state and priorities
- `PROJECT_STATE.md` — current implementation status
- `docs/DESIGN-DECISIONS.md` — previously settled decisions
- `docs/transcripts/observability-planning.md` — planning session notes and confirmed facts
- `docs/transcripts/observability-architecture-paths.md` — background on the options considered (it uses "Path 1/2/3" labels; ignore those labels — the chosen architecture is described under "Settled decisions" below, not by a path number)
- `docs/observability-priorities.md` — living must-have vs. nice-to-have list (created in Milestone 1)

**Settled decisions — do NOT re-litigate:**
- **Architecture (described by capability, not by a path number):**
  - OTel Collector handles all OTLP/GenAI telemetry: standalone otelcol-contrib (pinned `0.158.2`) as the fleet collector. Do NOT make DDOT the fleet collector (DDOT optional on the instructor cluster only) — `research/24` §1.1.
  - Datadog Agent DaemonSet for EKS infrastructure (nodes/pods/containers) and log collection.
  - **Full Universal Service Tagging so the Datadog Service Map renders** — this is a confirmed must-have (Milestone 6).
  - **Out-of-the-box integration dashboards are fine** (they come free with the Agent: EKS, Falco, cert-manager, Collector).
  - **Do NOT build custom dashboards or custom metrics for supporting tech that is never center stage** (e.g. ArgoCD, Kyverno, KubeArmor enforcement panels). Story-related custom dashboards (e.g. the model-tier cost comparison) are **deferred to dress rehearsal** — not built in this PRD sequence.
- **TypeScript rewrite of guard-proxy is NOT happening.** All Python apps stay Python. spiny-orb is off the table. AI-layer instrumentation uses the Python OTel SDK directly, or kagent/agentgateway built-in OTel output.
- **Already wired:** `spanmetricsconnector` with `add_resource_attributes: true`; UST tags via `OTEL_RESOURCE_ATTRIBUTES` on guard-proxy/agentgateway/kagent; `cluster.name=watch-it-burn` upserted by the Collector `resource` processor; OTel Collector pinned at contrib `0.158.2`.
- **Falcosidekick → Datadog:** wired in commit `6c6a81d`, but `research/23` (predates the commit) observed Falcosidekick forwarding only to Talon. Verify-at-build in Milestone 4; not a confirmed-working fact.
- **Cost-counter key (live-resolved):** live validation (kagent 0.9.9) found the key is `result.metadata.kagent_usage_metadata`, NOT `adk_usage_metadata` (`research/14` was wrong); `record_usage()` already accepts both, kagent-first. Verify it still holds; not an open bug.
- **Attendee Datadog model:** **per-attendee trial orgs** (confirmed 2026-06-22). The MVP (Milestone 1) uses ONE trial account; per-attendee scale-out is Milestone 8. `PROJECT_STATE.md`'s "one shared org" line is stale — corrected in Milestone 8.
- **Division of labor:** Whitney owns Datadog accounts/keys/Agent install/dashboards. Michael owns OTel-side wiring + manifest annotations + `datadog-secret` consumption.

---

## Living Document: `docs/observability-priorities.md`

Created in Milestone 1, updated at the end of every later milestone if design conversations shifted
priorities. **Read it in Step 0 of every milestone after Milestone 1.**

Known must-haves going in:
- **Service Map renders in the Datadog UI** (`guard-proxy → agentgateway → kagent → Bedrock`, each node health-indicated) — requires UST done correctly (Milestone 6)
- LLM call waterfall visible in APM traces (Milestone 2)
- Rogue MCP tool-call chain visible as a trace waterfall — Beat 3 (Milestone 3)
- Cost counter accumulating in real time (Milestone 1 proves it; refined later)
- Before/after sanitization visible in traces — re-leak trap beat (Milestone 3)
- Falco runtime alerts surfacing in Datadog when exfil is attempted (Milestone 4)

---

## Cross-Cutting Decisions — locked in Milestone 1

These, if decided late, force rework of earlier milestones. Milestone 1 settles them even though their full
payoff arrives later:
- **Collector pipeline shape** — confirm standalone contrib `0.158.2`; whether `datadog/connector` is added (Trace Metrics since otelcol-contrib v0.95.0); `datadog.prometheusScrape.enabled` stays **off** (double metrics + billing).
- **UST tag vocabulary** — exact `service.name` per component and `service.version` = the component's real **software version** (v1/v2/v3 as releases roll out). `service.version` is NOT a model-tier label. (Prior docs that proposed cluster-tier or model-name for `service.version` are superseded by this decision.) The **model dimension** for cost comparison comes from OTel GenAI semconv (`gen_ai.request.model`), captured in Milestone 2 and surfaced in Datadog LLM Observability — never from `service.version`.
- **Account model for MVP** — one trial account now; per-attendee scale-out deferred to Milestone 8.

(The Weaver-schema decision is NOT a Milestone 1 cross-cutting lock — it validates `gen_ai.*`, which doesn't exist until the Milestone 2 gen_ai migration. It lives in Milestone 2.)

---

## Milestones

> Every milestone is self-contained: it lists its own reads, problem framing, decisions, and child-PRD
> creation steps. Follow the steps written in your milestone; do not look to a shared template.

---

### Milestone 1 — MVP walking skeleton: data in one Datadog account, visible in the UI

**End-state goal:** A single Datadog trial account shows the AI layer's **existing telemetry — Michael's
current custom conventions** (the guard-proxy `witb_cost_usd` / `witb_tokens_total` /
`witb_requests_total` counters, labeled by `tier`, plus whatever traces flow today) — arriving through
the existing Collector + Datadog exporter and **visible in the Datadog UI**, with the cost counter
reading non-zero. No new instrumentation: this proves Datadog is installed and the pipeline works
end-to-end using what already exists. (Migrating these custom conventions to OTel GenAI semconv is
Milestone 2.) It also locks the Cross-Cutting Decisions above.

**Step 0 — Read:**
- This meta-PRD's top matter (conventions, settled decisions, cross-cutting decisions)
- `research/18-datadog-integrations-stack-2026.md`, `research/19-datadog-otel-ust-correlation-2026.md`, `research/23-…`, `research/24-…`
- `research/05-otel-genai-observability.md` (for the Weaver/GenAI semconv decision), `research/16-typescript-agent-spiny-weaver-2026.md` (Weaver CI live-check context; ignore the spiny-orb/TS parts — superseded)
- Codebase: `gitops/apps/otel-collector.yaml` in full; `agent/gateway/guard-proxy/guard-proxy.yaml` and the guard-proxy `/metrics` output; `gitops/ai-layer/resources.yaml` (current `OTEL_RESOURCE_ATTRIBUTES`)

**Step 1 — Problem (write 3-5 sentences):** What is the minimal set of telemetry already emitted, and
what is the shortest path to seeing it in one Datadog account's UI? What cross-cutting decisions must
be locked now to avoid reworking later milestones?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Collector pipeline shape** — confirm standalone contrib `0.158.2`; decide `datadog/connector` (Trace Metrics); confirm `datadog.prometheusScrape.enabled` off with reasoning.
2. **UST tag vocabulary** — define `service.name` per component; `service.version` = each component's real software version (v1/v2/v3), NOT a model-tier label. The model dimension for cost comparison lives in `gen_ai.request.model` (Milestone 2), not UST. Note: `DD_SERVICE`/`DD_ENV`/`DD_VERSION` env vars do NOT work on the OTel path — UST flows via `OTEL_RESOURCE_ATTRIBUTES`; `deployment.environment.name`→`env` needs Agent ≥7.58.0 or Datadog Exporter ≥v0.110.0.
3. **MVP account** — confirm one trial account for the MVP; how its `datadog-secret` is supplied for the milestone (manual is fine for one account).
4. **Cost-counter verify** — confirm `record_usage()` reads `kagent_usage_metadata` (live-resolved) and the MVP shows non-zero spend.
(The Weaver-schema decision moved to Milestone 2 — it validates `gen_ai.*`, which doesn't exist until the gen_ai migration.)

**Step 3 — Produce the child PRD:**
1. Create `docs/observability-priorities.md` and populate must-have/nice-to-have (seed from "Known must-haves").
2. Run `/prd-create` for a child PRD implementing the MVP per decisions 1-4, acceptance including "AI-layer metrics + traces visible in one Datadog trial account's UI; cost counter non-zero" (`/prd-update-decisions` for the Decision Log).
3. Add to `docs/ROADMAP.md` as `- MVP: telemetry in one Datadog account (PRD #[issue-id])`, first in build order.
4. Run `/prd-update-progress` to commit + push.
5. Instruct the user to start a new session, then run `/prd-next` for Milestone 2.

**Done when:**
- [x] Cross-cutting decisions (collector shape, UST vocabulary incl. `service.version`, MVP account) recorded in the child PRD's Decision Log with reasoning
- [x] `docs/observability-priorities.md` exists and lists the Service Map as a must-have
- [x] A child PRD issue exists whose acceptance includes Michael's existing telemetry visible in one account's UI + non-zero cost counter
- [x] ROADMAP updated, MVP first in build order

---

### Milestone 2 — Migrate off Michael's custom conventions to OTel GenAI semantic conventions

**End-state goal:** The AI layer emits **OTel GenAI semantic-convention** telemetry (the
`invoke_agent → chat → execute_tool` waterfall with `gen_ai.request.model`, `gen_ai.usage.*` tokens,
tool names) flowing into **Datadog LLM Observability**, replacing Michael's custom `witb_*`/`tier`
conventions. The LLM call waterfall and per-model token/cost data are visible in the Datadog LLM
Observability UI.

**Preliminary research (seed context only — the full research is pre-completed in issues #9, #10, and #15; read those before the Step 2 design conversation):**
A scoping search on 2026-06-22 found (the full spike in issues #9, #10, and #15 confirms, supersedes, or corrects these):
- **Datadog LLM Observability natively ingests OTel `gen_ai.*` spans (v1.37+) over OTLP — no dd-trace, no Datadog SDK.** Paths: direct OTLP intake, the Datadog Agent (OTLP mode), or the OTel Collector. ([Datadog OTel instrumentation docs](https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/))
- **kagent's base, Google ADK, emits gen_ai semconv natively** (`invoke_agent → chat → execute_tool`), enabled via standard `OTEL_*` env vars. ([Google Cloud: instrument ADK with OpenTelemetry](https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk))
- **Gotchas to confirm:** Datadog supports **OpenLLMetry 0.47+** but **NOT OpenInference**; Datadog requires semconv **v1.37+** (`OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` for frameworks on older specs); ADK content-capture wants `EVENT_ONLY`, and setting it to `true` under latest semconv is an **invalid config that collects no data**.
- **Likely lowest-effort path:** enable native kagent/ADK tracing → OTLP → Datadog, rather than writing new Python instrumentation. Confirm in the spike.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- The MVP child PRD + its Decision Log (Milestone 1) — **gates this milestone**
- `research/05-otel-genai-observability.md`, `research/06-cncf-stack.md`, `research/14-verify-at-build-sweep-2026.md`, `research/23-…`
- Codebase: `agent/gateway/guard-proxy/proxy.py` (the custom `witb_*` conventions to migrate; currently NO OTel), `agent/gateway/agentgateway.yaml`, `gitops/ai-layer/resources.yaml`, the kagent Helm values; `beats/` directories that depend on the trace waterfall
- **evil-mcp-shim untracked work for M2** (issue #18 closed 2026-06-24 — no tracked issue): add `apply_optimization` to `gitops/ai-layer/server.py` using the hardcoded fallback string from the `beats/` OSError branch — no relative file path (it doesn't survive ConfigMap deployment). UST env vars are handled in the MVP PRD (issue #13). **No OTel instrumentation** (shim is intentionally dark — visible as the agent's `execute_tool` spans).
- **Issue #17** — Datadog LLM Observability activation requirements (org flags, DatadogAgent CR keys, minimum span shape) and APM path confirmation with `spec.features.apm.enabled: false`; must be complete before this milestone proceeds

**Step 1 — Problem (write 3-5 sentences):** Which demo beats need the gen_ai waterfall, what does Michael's
custom telemetry emit today, and what must change to move to OTel GenAI semconv in Datadog LLM Observability?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Read the pre-completed research spikes before proceeding** — issues #9, #10, #15, and #17 are prerequisites that must be complete before this design conversation. Get the research file path from the comment on each issue, then read all four files:
   - **Issue #9** — Datadog LLM Observability OTLP ingestion path (native `gen_ai.*` ingestion, semconv version, `OTEL_SEMCONV_STABILITY_OPT_IN`, OpenLLMetry vs. OpenInference, ADK content-capture, Datadog-side config requirements)
   - **Issue #10** — Python AI layer instrumentation per-component approach (kagent/ADK, agentgateway, guard-proxy, evil-mcp-shim; agentgateway v1.3.0 field-path verification)
   - **Issue #15** — OTel SDK delivery strategy for the full cluster stack (OTel Operator vs. per-component; coexistence with standalone Collector; OTEL_* env var configuration; GitOps shape)
   - **Issue #17** — Datadog LLM Observability activation requirements (org flags, DatadogAgent CR keys, minimum span shape for LLM trace list to render) and APM path confirmation with `spec.features.apm.enabled: false` (`research/34-…`)
   If any issue is not yet complete (no file path posted as a comment), stop — this milestone cannot proceed. Do NOT run the spikes yourself; they are executed separately by Michael before this conversation begins.
2. **OTel SDK delivery mechanism (issue #15 prerequisite; Operator deployment pre-decided)** — Confirm issue #15 research is complete and its file path is posted as a comment. **The OTel Operator is deployed (pre-decided 2026-06-24 in meta-PRD Decision Log; overrides research/33's "No Operator" conclusion).** This conversation does not re-open that choice. Resolve: how `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, and `OTEL_RESOURCE_ATTRIBUTES` are configured cluster-wide — specifically, what the Instrumentation CRD looks like for Python pods and whether a single CRD covers all custom Python apps or one per app. Also confirm the custom app instrumentation pattern (OTel API no-op in image; Operator injects SDK at pod startup; manual spans; OTel semantic conventions — pre-decided 2026-06-24). This decision is a prerequisite for Decision 3 and is inherited by M3 for guard-proxy — record it as a compound decision before proceeding.
3. **Instrumentation approach per Python component** — read issue #10's research output and decide, for each of the **two** components with LLM calls (kagent/ADK, agentgateway), which approach produces OTel semconv-compliant spans. Do NOT select OpenInference — Datadog does not support it. The target standard is OTel semantic conventions throughout, specifically OTel GenAI semantic conventions (`gen_ai.*` attributes and span names) for AI operations. Options: native built-in OTel, an auto-instrumentation library (OpenLLMetry has historically provided OTel GenAI semconv auto-instrumentation for Python and is Datadog-supported at 0.47+, but verify its current status — it is being absorbed into the OpenTelemetry project itself), or manual Python OTel SDK spans. Note: kagent/ADK may need nothing (ADK's OTel output is native). **guard-proxy and evil-mcp-shim are excluded from this decision** — guard-proxy proxies requests but makes no LLM calls (its OTel instrumentation is M3 scope); evil-mcp-shim is intentionally left dark (decided 2026-06-24 — no OTel instrumentation; see issue #18 Decision Log). Issue #10 must be complete before this decision is made. Record the per-component decisions in the child PRD's Decision Log.
4. **Enable kagent/ADK gen_ai tracing** — `otel.tracing.enabled: true` (off by default); confirm it emits `gen_ai.*` and the `execute_tool {gen_ai.tool.name}` spans.
5. **Migrate off `witb_*`** — decide the fate of the custom `witb_*`/`tier` counters: retire in favor of `gen_ai.usage.*` + `gen_ai.request.model`, or keep `witb_cost_usd` for the cost lesson (USD is not a standard gen_ai attribute — cost is always derived). Update the four touch-points if renaming: `agent/gateway/guard-proxy/proxy.py`, `gitops/ai-layer/proxy.py`, the Grafana dashboard, `verify/test_observability.py`. **Note:** the only change to proxy.py in M2 is removing/renaming the `witb_*` counters — adding OTel spans to guard-proxy is M3 scope.
6. **GenAI semconv version + opt-in + Weaver** — pin a semconv version; set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` (Datadog needs v1.37+); decide whether a Weaver registry validating `gen_ai.*` in CI `live-check` is worthwhile and, if so, build it here. Implementation approach (Decision 2026-06-23): declare the OTel semconv community registry as a Weaver `dependencies:` entry — `gen_ai.*` definitions live upstream, the local registry references rather than redefines them. No vocab needs to be pre-defined in M1.

   **Attribute inventory pre-decided (2026-06-24, from issues #18 and #19):** All custom-app spans use only OTel community semconv attributes — no local attribute definitions are required in the Weaver registry. When building the Weaver registry for this decision, add the OTel community semconv as a `dependencies:` entry and define `live-check` validation for these span groups (kagent/ADK and agentgateway span attributes are covered by Decision 3, not this decision):
   - **`evil-mcp-shim`** (`service.name=evil-mcp-shim`, issue #18): **emits no spans** (decided 2026-06-24). The rogue tool calls are visible as the ADK agent's `execute_tool {gen_ai.tool.name}` spans; no server-side instrumentation. Weaver live-check does not apply to this service.
   - **`guard-proxy`** (`service.name=guard-proxy`, issue #19): (a) HTTP SERVER spans — `http.request.method`, `url.scheme`, `url.path`, `http.response.status_code`; (b) `sanitize` INTERNAL child spans — `gen_ai.operation.name` (= `"chat"`), `gen_ai.input.messages` (original prompt, before sanitization), `gen_ai.output.messages` (sanitized prompt). `gen_ai.input.messages`/`gen_ai.output.messages` use the OTel GenAI messages schema: `[{"role": "user", "parts": [{"type": "text", "content": "..."}]}]`. `"chat"` is used (not a descriptive custom value) because Datadog classifies spans as `llm` kind — enabling the before/after messages panel in LLM Observability — only for `generate_content`, `chat`, `text_completion`, or `completion` (research/31 Q5); do NOT substitute a custom value such as `"sanitize"` even if semantically accurate, as Datadog will not classify the span as `llm` kind. Weaver live-check will validate `"chat"` as a standard GenAI semconv enum value with no advisory.
7. **agentgateway v1.3.0 field-path verification** — repo has v1.2.1 pins; verify field paths against v1.3.0 GA.
8. **`gen_ai.request.model` capture** — confirm the model identifier is on the spans so the model dimension is available in LLM Observability (this, not `service.version`, is what a deferred model-tier cost comparison groups by).

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` for a child PRD per decisions 2-8, acceptance including "AI layer emits OTel GenAI semconv telemetry visible in Datadog LLM Observability" and "Michael's custom `witb_*` conventions migrated/retired per decision 5" (`/prd-update-decisions`).
3. Add to `docs/ROADMAP.md` as `- Migrate to OTel GenAI semconv (PRD #[issue-id])`, after the MVP.
4. Run `/prd-update-progress` to commit + push.
5. Instruct the user to start a new session, then run `/prd-next` for Milestone 3.

**Done when:**
- [x] Issues #9, #10, #15, and #17 research files confirmed complete (file paths posted as comments on each issue)
- [x] Decisions 2-8 recorded with reasoning in the child PRD's Decision Log
- [x] A child PRD issue exists whose acceptance includes gen_ai semconv telemetry in Datadog LLM Observability and the `witb_*` migration decision
- [x] ROADMAP updated

---

### Milestone 3 — Security beats: before/after sanitization + rogue MCP tool chain

**End-state goal:** The Datadog trace view shows the re-leak-trap story (before vs. after
sanitization at the guard-proxy) and Beat 3's rogue MCP tool-call chain as a trace waterfall —
visible in the UI.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- The gen_ai-semconv-migration child PRD + its Decision Log (Milestone 2) — **gates this milestone**
- `research/05-otel-genai-observability.md` (re-leak trap design), `research/12-mechanism-verification-2026.md` (collector-side symmetric redaction), `research/04-mcp-security.md`
- Codebase: `agent/gateway/guard-proxy/` (sanitization logic, before/after text held in memory) — **guard-proxy is custom software; proxy.py is directly modifiable**, `beats/03-bad-mcp-excessive-agency/` and its `evil-mcp-shim/server.py`
- **Issue #18** — confirm this is closed (done in M2 child PRD: `apply_optimization` added to `gitops/ai-layer/server.py` using hardcoded fallback, UST env vars added to `gitops/ai-layer/resources.yaml`). **No OTel instrumentation** on the shim (decided 2026-06-24 — see issue #18 Decision Log). M3 does not re-implement anything from this issue.
- **Issue #19** — pre-drafted instrumentation spec for guard-proxy (try/except import guard, manual HTTP SERVER span + `sanitize` INTERNAL child span). Sanitization content captured via `gen_ai.input.messages` (original text) and `gen_ai.output.messages` (sanitized text) in OTel messages schema — NOT custom attributes. App-level code fully specified; the M3 child PRD should include this issue as an implementation work item.
- **OTel SDK delivery mechanism is already decided in M2 (issue #15 research + M2 Decision 2)** — read the M2 child PRD's Decision Log for the chosen mechanism (OTel Operator vs. per-component). M3 inherits it for guard-proxy; do not re-decide.

**Step 1 — Problem (write 3-5 sentences):** What must a trace show to land the re-leak trap and the
rogue-tool beat, and what is the re-leak risk if content capture is naive?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Read the pre-completed research spike** (tracked in issue #12) — get the research file path from the comment on that issue, then read the file. It covers: how to capture prompt text in OTel spans for manually instrumented Python, the span structure for before/after sanitization, whether `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` applies to manual code, and how before/after appears in Datadog LLM Observability. If issue #12 is not yet complete (no file path posted as a comment), stop — this milestone cannot proceed. Do NOT run the spike yourself; it is executed separately by Michael before this conversation begins.
2. **Content capture approach for re-leak trap** — Pre-decided (2026-06-24, issue #19 + Decision 2 in this PRD): guard-proxy's `sanitize` span captures `gen_ai.input.messages` (original text) and `gen_ai.output.messages` (sanitized text) as manual span attributes using the OTel GenAI messages schema. Content capture is **gated on `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`**, which `proxy.py` reads explicitly at module load — the env var does NOT govern hand-written spans automatically; the proxy must read and honor it. Default: `NO_CONTENT` (no content on spans). Set to `SPAN_ONLY` for the re-leak-trap beat. `"true"` is not a valid enum value and must NOT enable capture. Datadog SDS is the backstop for real PII in production. This decision does NOT reopen; confirm the M3 child PRD implementation matches.
3. **Rogue MCP tool-call representation** — confirm the `execute_tool {gen_ai.tool.name}` span names the bad tool so Beat 3 reads as a waterfall.
4. **Re-leak-trap trace teardown** — ensure trace data is torn down so no span store retains even the fake sentinel post-run (`research/05` re-leak control #4).

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` for a child PRD per decisions 2-4, acceptance including "before/after sanitization and rogue MCP chain visible in traces" and "Weaver `live-check` passes for guard-proxy HTTP SERVER and `sanitize` INTERNAL span groups added to the M2 registry" (`/prd-update-decisions`). Note: `live-check` is a manual acceptance step only — it is NOT a CI gate (see Weaver CI pattern decision 2026-06-24 in this meta-PRD's Decision Log).
3. Add to `docs/ROADMAP.md` as `- Security-beat traces (PRD #[issue-id])`, after Milestone 2.
4. Run `/prd-update-progress` to commit + push.
5. Instruct the user to start a new session, then run `/prd-next` for Milestone 4.

**Done when:**
- [x] Issue #12 complete (research file path posted as comment on that issue)
- [x] Decisions 2-4 recorded with reasoning in the child PRD's Decision Log
- [x] A child PRD issue exists whose acceptance includes both security-beat views in traces
- [x] ROADMAP updated

---

### Milestone 4 — Falco runtime alerts into Datadog

**End-state goal:** When exfil/abuse is attempted, the Falco alert is visible in Datadog (OOTB Falco
dashboard or events), confirmed live.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- Prior milestone child PRDs + Decision Logs — **gate this milestone**
- `research/06-cncf-stack.md` (Falco/Falcosidekick), `research/18-…` (Falco integration row), `research/23-…`
- Codebase: Falco + Falcosidekick manifests in `gitops/apps/`, `gitops/ai-layer/resources.yaml`

**Step 1 — Problem (write 3-5 sentences):** Which beats need Falco alerts in Datadog, and which specific rules/alerts must be visible for each beat?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Falcosidekick → Datadog (verify-at-build) — Pre-decided (M4 Decision 1, 2026-06-24).** Commit `6c6a81d` already wired the Datadog output block in `gitops/apps/falcosidekick.yaml`; `DATADOG_HOST=https://api.datadoghq.com` is correct for US1. The child PRD must include two verify-at-build tasks for Michael: (a) confirm `datadog-secret` exists in the `security` namespace (not just `monitoring`); (b) confirm events flow on a live cluster. No design conversation needed; record this in the child PRD's Decision Log.
2. **Falco integration vs. Falcosidekick native output — Pre-decided: wire both (M4 Decision 2, 2026-06-24).** Falcosidekick sends individual alerts to the Datadog Event Stream; the Agent named integration sends individual alert logs to Log Explorer + aggregate metrics to the OOTB Falco dashboard. These are different Datadog surfaces — no duplication. Falcosidekick's path is wired in M4 (manifest already configured). The Agent named integration is wired in M5 when the Agent DaemonSet is deployed. Do not re-open this question.
3. **Which alerts/rules must be visible — Pre-decided (M4 Decision 3, 2026-06-24).** Three rules: (1) "Shell or Exec In Workshop Agent Pod" (WARNING) — any exec in the agent pod, fires for both C3 and C4; (2) "Sensitive File Access" (NOTICE) — sentinel credential file read, C3; (3) "Fork Bomb In Workload Container" (CRITICAL) — C4, also routes to Talon. The child PRD must rename the manifest rule currently called "Read Of Planted Fake Secret By Workshop Agent" to "Sensitive File Access" — the current name betrays the workshop illusion and assumes attribution Falco does not have. Do not re-open this question.

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` for a child PRD per decisions 1-3, acceptance including "all three required Falco rules produce visible alerts in the Datadog Event Stream (via Falcosidekick) on a live cluster run" (`/prd-update-decisions`). The child PRD must include: verify-at-build tasks (Decision 1); manifest rename of "Read Of Planted Fake Secret By Workshop Agent" → "Sensitive File Access" in `gitops/apps/falco.yaml` (Decision 3).
3. Add to `docs/ROADMAP.md` as `- Falco alerts in Datadog (PRD #[issue-id])`, after Milestone 3.
4. Run `/prd-update-progress` to commit + push.
5. Instruct the user to start a new session, then run `/prd-next` for Milestone 5.

**Done when:**
- [x] M4 Decisions 1, 2, and 3 recorded in the child PRD's Decision Log (pre-decided here; the child PRD records them as inherited locked decisions)
- [x] Child PRD includes verify-at-build tasks: `datadog-secret` in `security` namespace; events confirmed flowing on a live cluster
- [x] Child PRD includes manifest rename task: "Read Of Planted Fake Secret By Workshop Agent" → "Sensitive File Access" in `gitops/apps/falco.yaml`
- [x] A child PRD issue exists whose acceptance includes all three required rules visible in the Datadog Event Stream (via Falcosidekick) on a live cluster run
- [x] C4 fork-bomb rule also verified to trigger Talon auto-remediation (covered in PRD #23 Milestone 2 Step 3)
- [x] ROADMAP updated

---

### Milestone 5 — EKS infrastructure + named integrations ("Datadog sees everything")

**End-state goal:** The Datadog Agent DaemonSet runs on every workshop cluster, installed via the
**Datadog Operator** (install method pre-decided 2026-06-24 in meta-PRD Decision Log; overrides
research/32 Helm recommendation) and declared as an ArgoCD Application in GitOps. EKS
node/pod/container metrics, container logs, and the chosen named integrations are verified in Datadog
via the per-integration UI checklist. The Agent remains swappable: removing it and the Collector's
datadog exporter leaves the OSS stack fully functional.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- Prior milestone child PRDs + Decision Logs — **gate this milestone**
- `research/05-…`, `research/06-…`, `research/18-…`, `research/23-…`, `research/24-…`
- `research/NN-datadog-agent-install-eks-2026.md` (issue #14 — must be complete before this milestone proceeds; confirm file path posted as a comment on that issue)
- `research/34-…` (issue #17 — per-component OTel export config and Prometheus/OTel deduplication strategy; must be complete before this milestone proceeds; confirm file path posted as a comment on that issue)
- Codebase: every YAML in `gitops/apps/`, `gitops/ai-layer/resources.yaml`; `beats/` (what each beat's component needs)

**Step 1 — Problem (write 3-5 sentences):** Which infra signals and named integrations earn their
setup cost for the workshop, and what does "working" look like in the UI for each?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Agent install method and configuration (issues #14 and #17 prerequisites; install method and key flags pre-decided)** — Confirm issues #14 and #17 research are complete and their file paths are posted as comments. **Pre-decided (meta-PRD Decision Log 2026-06-24, overriding research/32):** (a) install mechanism = Datadog Operator; config uses DatadogAgent CR `spec.features.*` keys, not Helm `datadog.*` keys; (b) `spec.features.prometheusScrape.enabled: true` — ON, because some stack components are Prometheus-only; (c) `spec.features.apm.enabled: false` — OFF, OTel traces reach the APM UI via Collector path without this flag (confirmed by issue #17 research/34). Then resolve: (d) remaining feature flags — log collection, container monitoring, live process collection, remote configuration, autoscaling workload — cross-referenced against `research/24` §2.3 sizing and DatadogAgent CR schema; (e) IAM: IRSA vs EKS Pod Identity vs not required; (f) Cluster Agent: required or optional; (g) GitOps manifest shape: what the Operator + DatadogAgent CR ArgoCD Application(s) look like and where they live in `gitops/`, including sync-wave ordering for CRD before CR. Record as a single compound decision before proceeding.
2. **Per-component telemetry synthesis (research deliverable)** — tracked in issue #11. For each of the 13 stack components (ArgoCD, Kyverno, Falco, KubeArmor, Istio ambient, ESO, cert-manager, Backstage, kagent, agentgateway, guard-proxy, evil-mcp-shim, customer-stream generator), answer: (1) does it emit telemetry? (2) OTel, Prometheus, or both? (if OTel or both, which semantic conventions?) (3) how do we capture it in this stack? (4) official Datadog integration and/or OOTB dashboard? (5) community/importable dashboard if no official one? The four AI-layer components (kagent, agentgateway, guard-proxy, evil-mcp-shim) extract from the issue #9 and #10 research files rather than re-running those spikes. Full output saved to `research/NN-per-component-telemetry-synthesis-2026.md` (at minimum `research/30-…` since 28 and 29 are claimed by the M2 spikes). Wire-or-skip decisions are NOT part of this deliverable — they happen in decision 4 below. KubeArmor: community dashboard survey only; not in narrative. Confirm issue #11 is complete and the file path is posted as a comment before proceeding. **Note:** UST vocabulary for the four AI-layer components is pre-locked in the M1 Decision Log — do NOT re-decide `service.name`, `service.version`, or `deployment.environment.name` values for kagent, agentgateway, guard-proxy, or evil-mcp-shim. The synthesis deliverable for these four components answers telemetry-capture questions only; UST values are already in the M1 Decision Log entries dated 2026-06-23.
3. **DDOT vs. contrib** — `research/24` §1.1 already confirmed: keep standalone contrib `0.158.2` as fleet collector; standalone Agent for infra only; DDOT optional on instructor cluster. Confirm, do not re-open without new info.
4. **Wire-or-skip per named integration** — one component at a time. For each integration wired, define its **UI-verification checklist**: which dashboard, which metric, and which view proves it works in the Datadog UI. **Falco is pre-decided: wire the named integration (Updated per M4 Decision 2, 2026-06-24).** The Agent named integration collects individual alert logs (JSON per alert → Log Explorer) + aggregate Prometheus metrics (→ OOTB Falco dashboard). Falcosidekick's Datadog output (Event Stream) is wired in M4; this decision adds the Agent path in M5. UI verification checklist for Falco (Updated per M4 Decision 3, 2026-06-24): (1) OOTB Falco dashboard renders with rule match counts; (2) after running Challenge C3 (grep Easter-egg secret), both "Shell or Exec In Workshop Agent Pod" (WARNING) and "Sensitive File Access" (NOTICE) appear as log records in Log Explorer; (3) after running Challenge C4 (fork bomb), "Fork Bomb In Workload Container" (CRITICAL) and "Shell or Exec In Workshop Agent Pod" (WARNING) appear in Log Explorer. Do not re-open the wire-or-skip question for Falco.
5. **Hostname alignment** — Datadog computes host as `<k8s.node.name>-<cluster name>`; `cluster.name` already upserted; confirm `k8s.node.name` on host telemetry + matching `DD_CLUSTER_NAME` on the Agent (`research/24` §1.2).
6. **Istio ambient: L7 or L4-only?** — accept L4-only ztunnel metrics, or deploy a per-namespace waypoint for L7 (`research/23` Decision 6, `research/18`).
7. **EKS + CloudWatch cross-account integration scope** — in scope at all, and almost certainly NOT per-attendee (`research/24` §1.4)? Facilitator-only vs. skip.
8. **Agent resource footprint** — carry sizing from `research/24` §2 (node Agent 200m/256Mi, Process Agent 100m/200Mi, Cluster Agent 200m/256Mi; APM + System Probe OFF) into the child PRD.
9. **Kyverno native OTLP opt-in** (`otelConfig=grpc`) — enable to put policy-decision traces in the same span tree? (`research/18`).

**Step 3 — Produce the child PRD:**
1. The synthesis file (`research/NN-per-component-telemetry-synthesis-2026.md`) is produced as part of decision 2 (issue #11) — confirm it is complete and the file path has been posted as a comment on that issue before proceeding.
2. Update `docs/observability-priorities.md` if priorities shifted.
3. Run `/prd-create` for a child PRD per decisions 1-9, acceptance including a per-integration UI verification checklist (`/prd-update-decisions`).
4. Add to `docs/ROADMAP.md` as `- EKS infra & named integrations (PRD #[issue-id])`, after Milestone 4.
5. Run `/prd-update-progress` to commit + push.
6. Instruct the user to start a new session, then run `/prd-next` for Milestone 6.

**Done when:**
- [x] issue #14 research complete and file path posted as comment (gates Step 2 decision 1, Agent install)
- [x] issue #17 research complete and file path posted as comment (gates Step 2 decision 1 APM confirmation, decision 4 wire-or-skip)
- [x] `research/NN-per-component-telemetry-synthesis-2026.md` exists (issue #11 complete, file path posted as comment) covering all 13 components with answers to the 5 telemetry questions
- [x] Decisions 1-9 recorded with reasoning
- [x] A child PRD issue exists whose acceptance includes a per-integration UI verification checklist
- [x] ROADMAP updated

---

### Milestone 6 — UST at full fidelity + Service Map + correlation pivots

**End-state goal:** The Datadog **Service Map renders** (`guard-proxy → agentgateway → kagent →
Bedrock`, each node health-indicated), and "View related logs" pivots from a trace and "View Trace in
APM" pivots from a log — confirmed end-to-end on the live cluster. `service.version` carries each
component's real software version (the model dimension lives in `gen_ai.request.model`, not UST).

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- Prior milestone child PRDs + Decision Logs (esp. Milestone 1's UST vocabulary, Milestone 5's Agent deploy) — **gate this milestone**
- `research/19-datadog-otel-ust-correlation-2026.md`, `research/23-observability-decision-points-2026.md` (Decisions 5, 8)
- Codebase: `gitops/ai-layer/resources.yaml`, `agent/gateway/agentgateway.yaml`, `agent/gateway/guard-proxy/` (log output format), every workload manifest in `gitops/apps/` (UST-label inventory), `gitops/apps/otel-collector.yaml`

**Step 1 — Problem (write 3-5 sentences):** What correlation and Service-Map gaps remain after the
earlier milestones, given UST vocabulary was locked in Milestone 1?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Full UST rollout + gap inventory** — apply the Milestone 1 vocabulary to every workload; list which workloads still lack UST labels. **The vocabulary is pre-locked in M1 Decision Log (2026-06-23 entries) — do not re-decide it here.** Locked values: `deployment.environment.name=production` for all components (use this OTel semconv v1.27.0+ attribute name, NOT the deprecated `deployment.environment`); `service.version` per component as locked in M1 (kagent=`v0.9.9`, agentgateway=`v1.3.0`, guard-proxy=`1.0.0`, evil-mcp-shim=`1.0.0`; platform components use their natural software version); `service.name` = the component's natural lowercase name. M6 Step 2.1 is an inventory and application pass, not a vocabulary decision.
2. ~~**Same-tag mechanism for correlation**~~ — **Pre-resolved (2026-06-25 Decision Log).** `OTEL_RESOURCE_ATTRIBUTES` on each pod env is the mechanism; Agent auto-tags container logs from it; OTel SDK emits it as resource attributes on spans. No new config needed — the only action is fixing agentgateway's stale values (covered in Decision 2.1 scope above).
3. ~~**`peer.service` + span-kind prerequisite**~~ — **Pre-resolved (2026-06-25 Decision Log).** guard-proxy CLIENT span: set `peer.service="agentgateway"` in `proxy.py` at span creation. agentgateway and kagent outbound spans: OTTL transform processor in the Collector as fallback; verify-at-build whether they already set `peer.service` natively (if yes, no OTTL rule needed). Both the CLIENT span code and the Weaver registry entry for that span group are M6 child PRD scope.
4. ~~**Log-trace correlation for Python apps**~~ — **Resolved (2026-06-25 Decision Log).** guard-proxy has zero existing log output (`log_message` returns `None`; no `logging` or `print()` calls in `proxy.py`). Settled approach: stdlib `logging` + JSON formatter to stdout; extract `trace_id`/`span_id` from `opentelemetry.trace.get_current_span().get_span_context()`; Datadog Agent file/stdout pipeline auto-recognizes OTel-standard field names. Log the guard decision events: blocklist hit, classifier block, output scrub fired, agent forward error — these are the observability-interesting moments that enable the "View related logs" pivot.
5. ~~**Service Map from pure OTLP (live-verify)**~~ — **Resolved (2026-06-25 Decision Log).** Acceptance is binary: `GET /api/v1/service_dependencies` must return all 4 expected edges or M6 is not done — no partial pass. Child PRD includes a debug path (check span attributes via `GET /api/v1/traces` or Datadog MCP; confirm `peer.service` and span kind are set correctly on CLIENT spans; re-run map query). No fallback to Agent trace path — if OTLP Service Map fails, fix the OTLP pipeline.

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` (Service Map is a must-have).
2. Run `/prd-create` for a child PRD per decisions 1-5. **Scope: AI layer only** (platform component UST is a separate future PRD — 2026-06-25 Decision Log):
   - Fix agentgateway UST: `service.version` → `v1.3.0`, `deployment.environment.name` → `production` in `agent/gateway/agentgateway.yaml`
   - Add guard-proxy CLIENT span to `proxy.py` with `peer.service="agentgateway"` (2026-06-25 Decision Log)
   - Add OTTL transform processor in `gitops/apps/otel-collector.yaml` for agentgateway and kagent `peer.service` (verify-at-build if already set natively — if yes, skip)
   - Add guard-proxy CLIENT span group to `weaver/registry/`; run `weaver registry check` locally (2026-06-25 Decision Log; `weaver/registry/` is assumed to exist — Decision 600)
   - Add structured JSON logging to guard-proxy: stdlib `logging` + JSON formatter to stdout; inject `trace_id`/`span_id` from active OTel span context at guard decision events (blocklist hit, classifier block, output scrub, forward error) — Decision 4 (2026-06-25)
   - Verify Service Map from pure OTLP: `GET /api/v1/service_dependencies` must return all 4 edges (`guard-proxy→agentgateway→kagent→Bedrock`) — Decision 5 (see Decision Log)
   - Acceptance: `verify/test_datadog_service_map.py` passes via `GET /api/v1/service_dependencies` **and** both log-trace pivot directions pass **and** `weaver live-check` run as terminal step. **No "renders in the UI" browser assertion** — all acceptance is Datadog API-based (2026-06-25 Decision Log). The 4 edges are: (1) guard-proxy→LLM Guard, (2) guard-proxy→agentgateway, (3) agentgateway→kagent, (4) kagent→Bedrock. If Bedrock appears as an external dependency node rather than a named service, 3 internal edges is acceptable — verify-at-build which edges the live cluster actually emits.
   - Run `/prd-update-decisions` inside the child PRD session.
3. Add to `docs/ROADMAP.md` as `- UST, Service Map & correlation (PRD #[issue-id])`, after Milestone 5.
4. Run `/prd-update-progress` to commit + push.
5. Instruct the user to start a new session, then run `/prd-next` for Milestone 7.

**Done when:**
- [x] Decisions 1-5 recorded with reasoning
- [ ] A child PRD issue exists (AI layer only) scoped to: agentgateway UST fix, guard-proxy CLIENT span + `peer.service`, OTTL fallback for third-party `peer.service`, log-trace correlation, Weaver CLIENT span group, Service Map verify
- [ ] Child PRD acceptance criteria: `verify/test_datadog_service_map.py` passes via `GET /api/v1/service_dependencies` (4 edges: guard-proxy→LLM Guard, guard-proxy→agentgateway, agentgateway→kagent, kagent→Bedrock — or 3 internal edges if Bedrock is external-only; verify-at-build) AND both log-trace pivot directions pass AND `weaver registry check` passes AND `weaver live-check` run as terminal acceptance step
- [ ] ROADMAP updated

---

### Milestone 7 — Dashboards: import community dashboards + decide custom/story dashboards

**End-state goal:** The importable community/Grafana dashboards chosen from the Milestone 5 survey are
imported into Datadog for stack components that lack an official Datadog dashboard, and the
custom/story dashboard decisions are made (build now, defer specific ones to dress rehearsal, or skip).

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- The Milestone 5 child PRD + `research/30-per-component-telemetry-synthesis-2026.md` (issue #11 output) — **gates this milestone**
- **New prerequisite gate (Updated per 2026-06-24 Grafana decision):** A Datadog community dashboard research spike must be complete before this milestone proceeds. research/30's "community dashboard" column lists Grafana IDs — those are inapplicable (no Grafana imports; see Decision Log 2026-06-24). The new spike surveys importable Datadog community dashboard JSON files (DataDog/community-lab or similar) for components without OOTB dashboards. The spike is tracked in [issue #24](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/24) — it must be completed and its file path posted as a comment before Step 2 begins.
- All prior milestone child PRDs + Decision Logs — a dashboard can't be built/imported on data that isn't flowing
- `research/24-datadog-hybrid-impl-sizing-2026.md`, `docs/transcripts/observability-architecture-paths.md` (candidate custom-dashboard list)
- Codebase: `agent/gateway/guard-proxy/` (confirm metric names — `witb_cost_usd` retained per M2 Decision 5; `witb_tokens_total`/`witb_requests_total` retired), `beats/`

**Step 1 — Problem (write 3-5 sentences):** Which dashboards tell the workshop story, and which Datadog community dashboards (JSON import via Datadog UI/API/Terraform) fill gaps for components without an official Datadog OOTB dashboard?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Import which Datadog community dashboards?** — for each importable candidate from the Datadog community dashboard research spike ([issue #24](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/24), NOT research/30's Grafana column): import it or skip? One component at a time. **No Grafana imports** (Updated per 2026-06-24 Grafana decision: Whitney works at Datadog; all dashboard imports use Datadog's own community JSON format). For Kyverno: confirm whether the community dashboard's metric names are compatible with the OTLP path (M5 D9) before committing to import.
2. **Custom/story dashboards** — for each candidate (Wasted Tokens Over Time, Model Tier Cost Race [group by `gen_ai.request.model`], Tool Call Heatmap, Guardrail Toggle Timeline): **build now, defer to dress rehearsal, or skip?** Confirm the data source is flowing before committing to build.
3. **Dashboard JSON as code (committed)** vs. UI-built?

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` for a child PRD implementing the chosen community-dashboard imports + any custom dashboards decided to build now (deferring the rest to dress rehearsal) per decisions 1-3 (`/prd-update-decisions`).
3. Add to `docs/ROADMAP.md` as `- Dashboards: community imports + custom (PRD #[issue-id])`, after Milestone 6.
4. Run `/prd-update-progress` to commit + push.
5. Instruct the user to start a new session, then run `/prd-next` for Milestone 8.

**Done when:**
- [ ] Datadog community dashboard research spike ([issue #24](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/24)) complete and file path posted as comment (gates Step 2 Decision 1; **no Grafana imports** — Updated per 2026-06-24 Grafana decision)
- [ ] Import/skip decided per Datadog community dashboard with reasoning; chosen ones imported (Datadog community JSON format only — no Grafana)
- [ ] Build-now/defer/skip decided per custom dashboard, with data-flowing confirmed for any built now
- [ ] A child PRD issue exists for the dashboard imports + custom builds
- [ ] ROADMAP updated

---

### Milestone 8 — Scale-out: per-attendee accounts, credential store & distribution

**End-state goal:** Auto-wire each attendee's per-cluster `datadog-secret` (Kubernetes Secret in
`monitoring`, `security`, and `datadog` namespaces) from the pool of ~60 pre-provisioned trial orgs
so that spawning the fleet requires zero manual credential steps.

**Status as of 2026-06-24:** Michael's half is done. The open work is Whitney's child PRD (Decision 5
— the ESO `ExternalSecret` that reads the master store and injects per-cluster secrets). The "org
fork" question (whose org does each cluster report to?) must be resolved first.

Confirmed model: **per-attendee trial orgs** (~60 manually provisioned). Attendee count: **60**.

Each trial org has this shape (sensitive — contains API key, app key, and a password; **never commit
to the repo**):

```json
{
  "userId": "", "datadogUserId": "", "datadogHandle": "", "datadogOrgName": "",
  "datadogApiKey": "", "datadogAppKey": "", "expiration": 0, "password": "",
  "formattedExpiration": "Account expires in 13 days and 20 hours",
  "publicOrgId": "", "internalOrgId": ""
}
```

**What Michael has already done (substrate ready):**
- Org provisioning: ~60 trial orgs manually provisioned; `pool.csv` is the source of truth
- Distribution: `merge_pool.py` + `pool.csv` + provisioning success page give each attendee their Datadog creds
- 1Password shared vault set up (Whitney/Michael sharing mechanism)
- `datadog-secret` consumers wired: `otel-collector.yaml` and `falcosidekick.yaml` already read from it
- ESO + EKS Pod Identity substrate exists; `datadog-secret` in `security` namespace confirmed needed (see Decision Log M4 Decision 1)
- Teardown: manual trigger via `teardown/teardown.sh` (40-min auto-expiry idea dropped)

**What remains (Whitney's child PRD):**

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- All prior milestone child PRDs + Decision Logs — **gate this milestone**
- `research/24-datadog-hybrid-impl-sizing-2026.md` (§3 secret injection), `research/25-eks-quotas-shared-vpc-topology-2026.md`
- Codebase: `gitops/apps/` (ESO config, existing ExternalSecret patterns), `docs/BUILD-SPEC.md`

**Step 1 — Problem (write 3-5 sentences):** What is unresolved about auto-wiring the per-cluster
`datadog-secret` at fleet spawn time, and what is the blast radius if it fails on the day?

**Step 2 — Resolve with Whitney (one at a time):**
1. ~~**Provisioning**~~ — **DONE (2026-06-24).** Michael manually provisioned ~60 trial orgs; `pool.csv` is the source of truth. No research spike needed.
2. ~~**Master credential store — sharing**~~ — **DONE (2026-06-24).** 1Password shared vault set up between Michael and Whitney. (How `pool.csv` entries are loaded into AWS Secrets Manager so ESO can read them is a sub-question inside Decision 5's child PRD, not a separate design conversation.)
3. ~~**Surfacing credentials**~~ — **DONE (2026-06-24).** `merge_pool.py` + `pool.csv` + provisioning success page. Attendees receive their bundle at provisioning time.
4. ~~**Are app keys (`datadogAppKey`) needed in the cluster secret?**~~ — **Pre-answered by M5 Decision 1(e), 2026-06-24.** Both `api-key` and `app-key` are in `datadog-secret`. The DatadogAgent CR's `spec.global.credentials` block requires both; the app key is used by the Operator/Cluster Agent for Datadog API operations, not only for dashboard/monitor automation. The two-key secret shape is established in M5 via ESO ExternalSecret. No verify-at-build needed on this question; the M5 child PRD validates the full DatadogAgent CR on a live cluster.
5. **Org fork — OPEN, must resolve first:** does each cluster report to (a) the attendee's own trial org from their `pool.csv` row, (b) a single shared org Whitney watches for full cross-fleet visibility, or (c) both? This determines the ExternalSecret shape. Mechanism options: ESO `ExternalSecret` per namespace reading from AWS Secrets Manager (one secret per attendee keyed by `userId`, or one pool secret with a lookup); Terraform var → k8s Secret in the cluster module; fleet driver seeding from `pool.csv` at spawn time.
6. ~~**Rotation/expiry**~~ — **SETTLED (2026-06-24).** Manual teardown via `teardown/teardown.sh`. Trial orgs expire ~14 days after provisioning. No automated rotation; mitigate leaked-cred blast radius via short IAM session lifetimes if needed.

**Step 3 — Produce the child PRD:**
1. Correct `PROJECT_STATE.md`'s stale "one shared org" line to per-attendee orgs.
2. Run `/prd-create` for a child PRD scoped to decisions 4-5 (cluster injection only; provisioning/distribution/sharing are done).
3. Update `docs/ROADMAP.md` ROADMAP entry 8 with the new issue number.
4. Run `/prd-update-progress` to commit + push.
5. Final milestone — when its child PRD exists, mark this meta-PRD complete and run `/prd-done` for issue #7.

**Done when:**
- [x] Decisions 1, 2 (sharing), 3, 6 resolved (Michael's side done 2026-06-24)
- [ ] Decision 4 (app keys in cluster secret?) resolved with Whitney
- [ ] Decision 5 (org fork + ExternalSecret mechanism) resolved with Whitney
- [ ] Child PRD exists for cluster secret injection (scoped to Decision 5)
- [ ] ROADMAP entry 8 has an issue number
- [ ] All 8 milestones complete → this meta-PRD closed

---

## Acceptance Criteria (this meta-PRD)

- [ ] 8 child PRDs exist (Milestones 1-8), each issue-backed and labeled "PRD"
- [ ] `research/NN-per-component-telemetry-synthesis-2026.md` exists (issue #11, produced in Milestone 5)
- [ ] `docs/observability-priorities.md` reflects the final must-have/nice-to-have list
- [ ] `docs/ROADMAP.md` lists all child PRDs in build order, each as `- [desc] (PRD #[issue-id])`
- [ ] `PROGRESS.md` updated to reflect meta-PRD creation and completion

## Decision Log

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-06-22 | Milestone 7 is a real milestone, not deferred | It imports the community/Grafana dashboards chosen in the Milestone 5 survey (for components lacking an official Datadog dashboard) AND decides custom/story dashboards (build now / defer to dress rehearsal / skip). Importing community dashboards is distinct from hand-building custom ones; the latter for never-center-stage tech is still out |
| 2026-06-22 | Add a community-dashboard survey across the whole stack (incl. KubeArmor) to Milestone 5 | For any component lacking an official Datadog dashboard, find an importable community/Grafana dashboard so we import rather than hand-build (skips the "no custom dashboards" rule). Surveying ≠ wiring; KubeArmor stays out of the narrative. Candidates feed the deferred Milestone 7 |
| 2026-06-22 | Renamed "Slice" → "Milestone" throughout | The `/prd-*` skills parse milestone structure; "Slice" headings would confuse `prd-next` / `prd-update-progress`. "Vertical slice" remains only as a concept in the framing intro |
| 2026-06-22 | Milestone 1 proves Datadog works using Michael's EXISTING custom conventions | MVP is the fastest possible pipeline proof with zero new instrumentation: get the `witb_*`/`tier` counters (and any existing traces) into one Datadog account. Migration to OTel GenAI semconv is Milestone 2 |
| 2026-06-22 | Milestone 2 = migrate off Michael's conventions to OTel GenAI semconv | Adopt `gen_ai.*` (waterfall, tokens, model) into Datadog LLM Observability, replacing the custom `witb_*`/`tier` scheme. Seeded with preliminary scoping research (Datadog ingests OTel gen_ai natively v1.37+; ADK emits it natively; OpenLLMetry supported, OpenInference not); the full `/research` spike + the Python manual-vs-auto instrumentation decisions run DURING the milestone. Weaver-schema decision moved here from Milestone 1 (it validates `gen_ai.*`, which doesn't exist until this migration) |
| 2026-06-22 | `service.version` = real software version, not a model-tier label | Whitney: `service.version` is for v1/v2/v3 software releases. The model dimension for cost comparison comes from OTel GenAI semconv `gen_ai.request.model` (captured in Milestone 2, surfaced in LLM Observability), never from UST. Resolves the prior cluster-tier-vs-model-name conflict — it was a false choice |
| 2026-06-22 | KubeArmor is not in the workshop narrative | Whitney: no KubeArmor observability at all. Skip it in the per-component synthesis; no KubeArmor enforcement panel. The fork bomb is handled by `podPidsLimit` + Falco/Talon |
| 2026-06-22 | Architecture chosen by capability, NOT by a "Path" number | Whitney never chose "Path 2"; that label was wrong and is removed so no implementing agent inherits it. Chosen: OTel Collector (contrib 0.158.2) for OTLP/GenAI + Datadog Agent for EKS infra + **full UST so the Service Map renders**. OOTB integration dashboards stay (free with the Agent); NO custom dashboards/metrics for never-center-stage supporting tech; story dashboards deferred to dress rehearsal |
| 2026-06-22 | TypeScript rewrite not happening | All Python apps stay Python; spiny-orb off the table; AI-layer instrumentation uses Python OTel SDK / built-in kagent+agentgateway OTel |
| 2026-06-22 | Decisions documented in PRDs, not separate planning docs | `/prd-create` + `/prd-update-decisions` capture decisions in each child PRD's Decision Log; a parallel `docs/planning/` would drift |
| 2026-06-22 | Accounts/credentials/secrets consolidated into one milestone (Milestone 8) | Tightly coupled; splitting would repeat the same design conversations |
| 2026-06-22 | `/prd-update-progress` pushes after committing | Michael needs visibility into planning progress |
| 2026-06-22 | Attendee Datadog model: per-attendee trial orgs (confirmed) | Whitney confirmed per-attendee over shared org; `PROJECT_STATE.md`'s "one shared org" line is stale, corrected in Milestone 8. Org provisioning has no research backing — Milestone 8 needs a net-new spike |
| 2026-06-22 | Cost-counter key live-resolved to `kagent_usage_metadata` | Live validation (kagent 0.9.9) showed `research/14` was wrong; `record_usage()` already accepts both, kagent-first. MVP verifies, does not "fix a bug" |
| 2026-06-22 | DDOT-vs-contrib not a blank slate | `research/24` §1.1 confirmed: standalone contrib `0.158.2` as fleet collector, DDOT optional on instructor cluster only |
| 2026-06-22 | Master credential store is a distinct Milestone 8 decision | Storing the sensitive trial-org pool (API/app keys + passwords) as a source of truth the build service reads and Whitney shares with Michael is separate from per-cluster ESO injection; org schema embedded for the implementer |
| 2026-06-22 | Restructured from horizontal layers to MVP-first vertical milestones | Michael's build system builds each child PRD as it is written; vertical milestones are verifiable in the Datadog UI per milestone, and design order = build order. Cross-cutting decisions (collector shape, UST vocabulary, account model) locked in Milestone 1 to bound rework (Weaver removed from this list — superseded 2026-06-23, Weaver stays in M2) |
| 2026-06-22 | ~~Weaver schema decision moved to Milestone 1 (MVP)~~ (superseded 2026-06-23 — Weaver stays in M2) | ~~Encoding GenAI semconv for CI `live-check` is cross-cutting; if worthwhile, the registry must exist from the first traces so later milestones validate against it~~ |
| 2026-06-22 | Per-component synthesis feeds the infra/integration milestone rather than standing alone | A survey alone implements nothing; in the vertical structure it is produced inside Milestone 5 and consumed in the same milestone, so its findings directly drive wire/skip decisions instead of becoming a research dead-end. (The spike was assigned `research/30` at execution time — 28 and 29 were taken by the M2 LLM obs and Python instrumentation spikes.) |
| 2026-06-22 | Meta-PRD content was reconciled from research 14/18/23/24/25/27 + PROJECT_STATE via a read-only audit | Provenance: a reconciliation agent surfaced settled decisions and unrepresented open questions from prior docs; they were folded into the milestones. A second audit agent verified the horizontal→vertical restructure dropped no substantive item |
| 2026-06-22 | `PROJECT_STATE.md` stale "one shared org" line corrected in Milestone 8, not now | The shared-org→per-attendee correction lands when the work lands, so the state doc changes alongside implementation rather than ahead of it |
| 2026-06-23 | Weaver stays in Milestone 2; OTel semconv community registry is the upstream dependency (supersedes stale 2026-06-22 "Weaver schema decision moved to Milestone 1" entry) | `gen_ai.*` spans don't exist until the M2 migration, so Weaver can't validate anything in M1 — nothing to check against. The OTel community maintains a semconv registry (including all `gen_ai.*` definitions) that Weaver can pull via a `dependencies:` entry in `registry_manifest.yaml`; the local registry references upstream definitions rather than redefining them. No vocab needs to be pre-defined in M1. M2 Step 5 updated to reflect this implementation approach. |
| 2026-06-23 | Wire-or-skip decisions belong to the M5 design conversation with Whitney, not to the per-component research deliverable (issue #11) | Michael should not make infrastructure investment decisions alone in a research spike. Issue #11 now delivers 5 telemetry-answer questions per component (does it emit? OTel/Prometheus/both? how captured? official Datadog integration/dashboard? community dashboard?); it does not include wire-or-skip or reasoning. Wire-or-skip happens in M5 Step 2.3, informed by the synthesis. M5 Step 2.1 and its "Done when" updated accordingly. |
| 2026-06-23 | Guard-proxy before/after sanitization tracing is a separate research spike (issue #12), not part of issue #10 | Capturing pre/post prompt text in OTel spans from manually instrumented Python is specific to the re-leak trap beat and depends on both issue #9 (Datadog ingestion path) and issue #10 (general Python instrumentation approach) being complete first. Issue #10 establishes the general approach; issue #12 builds on it for the before/after capture pattern specifically. M3 Step 2 Decision 1 now gates on issue #12; M3 "Done when" updated with an issue #12 checkbox. |
| 2026-06-23 | M8 org provisioning spike runs during the milestone, not as a pre-created GitHub issue | The pattern for M2/M3/M5 is that research spikes are pre-created as GitHub issues (#9–#12) and run by Michael before the design conversation. M8's net-new org provisioning spike is intentionally an exception: it is last in build order, has no urgency, and was deliberately left as an in-milestone task. Do NOT create a GitHub issue for it when setting up the other research spikes. |
| 2026-06-23 | M1 resolved: add `datadog/connector` to MVP Collector config | Required since otelcol-contrib v0.95.0 — without it, the Datadog Exporter no longer computes APM Trace Metrics (`trace.*` namespace used by SLOs and monitors). Confirmed working in local spinybacked-orbweaver-eval config (`evaluation/is/otelcol-config.yaml`). Wire: add `datadog/connector` to the `connectors:` block with `traces.compute_stats_by_span_kind: true`; add as exporter in the traces pipeline and receiver in the metrics pipeline, alongside the existing `spanmetrics` connector. `datadog.prometheusScrape.enabled` confirmed off (not present in Collector config; defaults off — turning it on causes double metrics and billing spikes). |
| 2026-06-23 | M1 resolved: UST OTel attribute is `deployment.environment.name`, not deprecated `deployment.environment` | OTel semconv v1.27.0 deprecated `deployment.environment` in favor of `deployment.environment.name`. Datadog Exporter ≥v0.110.0 (or Agent ≥7.58.0) maps `deployment.environment.name` → `env` tag automatically. The Datadog UST docs still show the deprecated name in examples but this stack uses the current attribute. All `OTEL_RESOURCE_ATTRIBUTES` settings across every milestone must use `deployment.environment.name`. `DD_SERVICE`/`DD_ENV`/`DD_VERSION` env vars do NOT work on the OTel path — UST always flows through `OTEL_RESOURCE_ATTRIBUTES`. |
| 2026-06-23 | M1 resolved: `deployment.environment.name=production` for all stack components | Datadog UST docs (confirmed against live docs 2026-06-23) define `env` as an SDLC deployment environment tag (`production`, `staging`, `dev`, etc.), not a project or application name. The canonical Datadog/OTel example is `production`. Prior code comments and research docs used `watch-it-burn` as the env value — that is wrong; it is a project/workshop name, not a deployment stage. Every AI-layer pod and every future milestone that sets UST tags on stack components uses `deployment.environment.name=production`. Corrects `gitops/ai-layer/resources.yaml`. |
| 2026-06-23 | M1 resolved: per-component `service.version` values locked | `service.version` tracks deployable application artifact version (not Python runtime version, not model tier). Locked values for M1: kagent=`v0.9.9` (chart/app v0.9.9 per VERSIONS.lock); agentgateway=`v1.3.0` (GA release per VERSIONS.lock and `agentgateway.yaml`); guard-proxy=`1.0.0` (Michael's unversioned Python script — `python:3.12-slim` is the runtime, not the app version; starts at 1.0.0 and increments with code releases); evil-mcp-shim=`1.0.0` (same pattern — Michael's unversioned Python script). Supersedes the `CLUSTER_TIER` placeholder in `gitops/ai-layer/resources.yaml` comments, which was already ruled out as a version value. Each milestone that wires UST on a new component (M5, M6) must use that component's actual software version, not a generic placeholder. |
| 2026-06-23 | M1 resolved: `service.name` values locked for AI-layer components | guard-proxy=`guard-proxy`, agentgateway=`agentgateway`, kagent=`kagent`, evil-mcp-shim=`evil-mcp-shim`. These are the exact strings that will appear in the Datadog Service Map nodes and Service Catalog. Subsequent milestones that wire UST on platform components (ArgoCD, Kyverno, Falco, cert-manager, etc.) use the component's natural lowercase name as `service.name`. |
| 2026-06-23 | Issue #15 (OTel SDK delivery strategy for the full cluster stack) added as M2 prerequisite spike | The SDK delivery mechanism cannot be decided for evil-mcp-shim alone — the right answer depends on the full stack: bundled-OTel third-party components (kagent/ADK, agentgateway), platform components with varying telemetry postures (Istio, ArgoCD, Kyverno, Falco, cert-manager, ESO, Backstage, customer-stream generator), and the two custom Python pods (evil-mcp-shim in M2, guard-proxy in M3). The OTel Operator may be the right cluster-wide choice precisely because it covers more than just custom Python. Issue #15 is a prerequisite for M2 Decision 2; M3 inherits the decision for guard-proxy without re-deciding. M2 Step 0, Step 2 (new Decision 2), Step 3, and Done when updated accordingly. M3 Step 0 updated to note inheritance. |
| 2026-06-23 | kagent v0.9.9 bundles google-adk>=1.28.1 — ADK gen_ai.* activation is config-only | Live check of `python/packages/kagent-adk/pyproject.toml` on the v0.9.9 tag confirms `google-adk>=1.28.1,<2`. ADK ≥1.17.0 is the threshold for native `gen_ai.*` span emission; 1.28.1 clears it with margin. No custom Python SDK code needed for kagent in M2 — enabling `otel.tracing.enabled: true` in the Helm values is the only required change. |
| 2026-06-23 | guard-proxy is custom software — proxy.py is directly modifiable | proxy.py is a custom Python script written for this project, not a third-party package. It runs in a stock `python:3.12-slim` image mounted via ConfigMap. Unlike kagent and agentgateway, there is no packaging or release constraint preventing direct source edits. This means M3's OTel instrumentation pattern is: add `opentelemetry-api` imports to proxy.py directly; OTel Operator injects the SDK at deploy time (no-op until wired). No research spike needed for SDK delivery. |
| 2026-06-23 | guard-proxy is out of M2 gen_ai.* migration scope | guard-proxy proxies requests but does not make LLM calls. It has no `gen_ai.*` spans to emit in M2. The M2 gen_ai.* migration covers kagent/ADK, agentgateway, and evil-mcp-shim only. proxy.py is still touched in M2 Decision 4 (retire/rename the `witb_*` counters), but no OTel spans are added. Adding OTel spans to proxy.py (manual instrumentation for before/after sanitization content) is M3 scope, gated by issue #12. |
| 2026-06-23 | Issue #14 (Datadog Agent install method and feature flags for EKS) added as M5 prerequisite spike | `research/24` settled architecture shape (standalone Agent DaemonSet alongside OTel Collector, not DDOT) but never chose install mechanism, required feature flags, IAM approach, Cluster Agent requirement, or GitOps manifest shape. These are mutually exclusive implementation choices that determine the entire M5 child PRD structure. M5 Step 0 now gates on the issue #14 research file; M5 Step 2 decision 1 resolves all five sub-questions as a compound decision before the child PRD is designed. |
| 2026-06-23 | M1 resolved: DD_SITE is datadoghq.com (US1); `datadog-secret` does not pre-exist and must be created at implementation time | Workshop is in San Francisco; US1 (`datadoghq.com`) is correct and already hardcoded in `gitops/apps/otel-collector.yaml` — no change needed. `datadog-secret` (API key, app key, password for the trial org) does NOT pre-exist on the cluster. The MVP child PRD must include a step to create it. Mechanism (kubectl create secret vs ESO) is decided at implementation time when Whitney provides the credential access command. **CRITICAL: never print credentials to the terminal.** |
| 2026-06-23 | M1 resolved: MVP telemetry acceptance is "any metric or trace appears in Datadog" — no specific metric required | The MVP is a walking skeleton; acceptance is that the pipeline is live. `record_usage()` reads `kagent_usage_metadata` first (live-verified with kagent 0.9.9 this session), so cost metrics will flow — but the acceptance criterion does not need to name them. |
| 2026-06-24 | Datadog Agent install: Datadog Operator (overrides research/32 Helm recommendation) | The Datadog Operator is the official Datadog-recommended install mechanism for Kubernetes. The per-cluster CRD-ordering concern (CRD before DatadogAgent CR) is standard ArgoCD sync-wave pattern — solved with `argocd.argoproj.io/sync-wave` annotations, not a reason to forgo the official tool. As a Datadog employee demonstrating the stack, using the Operator is the appropriate showcase. **Config schema change:** Agent configuration uses DatadogAgent CR `spec.features.*` keys, not Helm chart `datadog.*` keys. Research/32's Helm recommendation and its illustrative YAML are overridden; a CORRECTIONS section has been added to that file. M5 Step 2 Decision 1 is pre-answered on install method — that conversation now focuses on Operator configuration details (feature flags, IAM, Cluster Agent, GitOps shape). |
| 2026-06-24 | Datadog Agent `spec.features.prometheusScrape.enabled`: ON (overrides research/32 OFF recommendation) | **Note: this is the Datadog Agent's Prometheus scraping feature — distinct from the OTel Collector's `datadog.prometheusScrape` exporter config, which remains OFF per the 2026-06-23 entry.** Several stack components emit only Prometheus (cert-manager, ESO, Falco, Falcosidekick). With the Agent's prometheusScrape OFF, those components produce zero telemetry. Research/32's OFF rationale assumed M5 wire-or-skip decisions (not yet made) would route all Prometheus data through the OTel Collector — that is not confirmed. Per-component deduplication strategy (Collector-level filter or per-component Prometheus disable for components that double-emit both OTel and Prometheus) is M5 Decision 4 scope. Research/32's OFF recommendation is overridden; CORRECTIONS section added. |
| 2026-06-24 | Datadog Agent `spec.features.apm.enabled`: OFF | This stack routes all traces via OTel SDK → OTel Collector → Datadog Exporter → Datadog API. OTel traces appear in the Datadog APM interface, Service Map, and Traces page via this path regardless of the Agent's APM flag. The Agent's APM feature opens port 8126 for dd-trace SDK format; no app in this stack uses dd-trace. The flag does not affect OTel trace ingestion or APM UI visibility. Opening an unused port adds overhead without benefit. |
| 2026-06-24 | OTel Operator: deploy it (overrides research/33 "No Operator" recommendation) | The stack has 2-4 apps requiring Python/Node.js SDK injection: guard-proxy (M3), customer-stream generator (when built), Backstage/Node.js (future). cert-manager is already in the stack, removing research/33's primary "new dependency" objection. The alternative — baking the full OTel SDK including grpcio (~20MB compiled C extension) into custom images — bloats images significantly, confirmed from Whitney's firsthand experience. The Operator init-container injects the SDK into a shared volume at pod startup; app images stay slim. Research/33's finding that auto-instrumentation cannot produce a SERVER span for guard-proxy's stdlib `http.server` is still valid and unchanged — the Operator handles SDK delivery, manual span code handles span creation. The existing 2026-06-23 entry ("guard-proxy is custom software… OTel Operator injects the SDK at deploy time") was already correct; research/33's "No Operator" conclusion contradicted it and is now overridden. CORRECTIONS section added to research/33. |
| 2026-06-24 | Custom app instrumentation pattern: OTel API (no-op) in image + Operator injects SDK + manual spans | All custom Python and Node.js apps in the stack follow this pattern: (1) app image carries only `opentelemetry-api` as a dependency — no SDK, no exporter, no exporter configuration; `opentelemetry-api` alone is a no-op (~100KB) until the Operator injects the SDK; (2) OTel Operator init-container injects the full SDK + exporter at pod startup via a shared volume and PYTHONPATH; (3) all span and metric creation uses manual code against the `opentelemetry-api`; (4) OTel semantic conventions are used for all attribute names. Applies to: guard-proxy (M3), customer-stream generator (when built), Backstage/Node.js (future). Michael must be given a per-app instrumentation spec as a GitHub issue before building any custom app that will emit telemetry. |
| 2026-06-24 | evil-mcp-shim: no OTel instrumentation (overrides original issue #18 spec); issue #18 remaining work untracked | The shim is intentionally left dark. The ADK agent's `execute_tool {gen_ai.tool.name}` spans (nested under `invoke_agent`) already show the full rogue-call story from the caller side — whether or not the MCP server instruments itself. The genuinely interesting data (poisoned tool description, fake credential response) has no standard OTel semconv attribute home: tool descriptions are a separate `tools` API parameter unlikely to land in `gen_ai.input.messages` or `gen_ai.system_instructions` (verify-at-build unknown); tool output has no semconv attribute at all. The only path that would capture tool definitions is botocore instrumentation, which creates double-instrumented model spans and inflated token counts (research/29). Pedagogical reason: the teaching point is that an untrusted server need not cooperate with observability for abuse to be detected — instrumenting the shim implies the attacker helpfully traces themselves. Dedup concern: two `execute_tool read_internal_config` spans (agent + shim) create ambiguity. **Future revisit trigger**: if live cluster testing shows tool descriptions land in ADK spans and the narrative benefit outweighs dedup complexity. Issue #18's two remaining items (reconcile drifted `server.py` copies; UST env vars in `gitops/ai-layer/resources.yaml`) do not need a dedicated tracking issue — UST env vars are already in the MVP PRD (issue #13, Milestone 3), and the `server.py` reconciliation is straightforward enough for Michael to handle as part of the M2 build. |
| 2026-06-24 | Single shared OTel Operator Instrumentation CRD for all custom Python pods (M2 Decision 2) | One CRD (`watch-it-burn-python`, namespace `agent`) covers guard-proxy, evil-mcp-shim, and any future custom Python app. UST env vars (`OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`) go in each workload's Deployment/pod spec — not in the CRD — so the CRD stays reusable without per-component variants. The CRD carries `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` and `OTEL_EXPORTER_OTLP_PROTOCOL=grpc` as cluster-wide defaults. **Build-time gap**: the exporter endpoint service name must be reconciled before M2 goes live (two known candidates: `otel-collector-opentelemetry-collector.monitoring` vs `otel-collector.observability`). M3 inherits this CRD shape for guard-proxy without re-deciding. |
| 2026-06-24 | OpenLLMetry not used — native OTel only for AI component instrumentation (M2 Decision 3) | ADK ≥1.17.0 emits `gen_ai.*` natively; agentgateway emits OTel natively. Adding OpenLLMetry (a supported-at-0.47+ wrapper) would layer a library on top of already-conformant native spans, adding a dependency that is being absorbed into the OpenTelemetry project itself. All AI component tracing uses native framework features (ADK `otel.tracing.enabled: true` in Helm; agentgateway `OTEL_EXPORTER_OTLP_ENDPOINT`) or manual OTel API spans (guard-proxy in M3, customer-stream-generator if built). No Python auto-instrumentation library intermediaries for AI operations. Applies to M3 and all future AI component milestones. |
| 2026-06-24 | Weaver CI pattern: `registry check` in CI; `live-check` as manual acceptance step only — NOT a CI gate (M2 Decision 6) | `registry check` validates the registry schema statically against the OTel semconv dependency — no live stack needed; runs in CI on every push. `live-check` requires a running span stream from a live cluster; it is documented as the human-in-the-loop acceptance step in each milestone's "Done when" criteria but is NOT wired as a CI gate. CI should not depend on a running cluster. Applies from M2 through all subsequent milestones that add new span groups to the registry. |
| 2026-06-24 | `witb_cost_usd` metric retained with `model` label; `witb_tokens_total`, `witb_requests_total`, and `tier` label retired (M2 Decision 5) | USD cost is not a standard OTel GenAI semconv attribute (no `gen_ai.cost.*` exists in the spec as of v1.37+). `witb_cost_usd` is kept in the `witb_` namespace (workshop-appropriate) with a `model` label carrying the `gen_ai.request.model` value, so the cost-per-model story remains visible in the Grafana panel. Token counts and request counts are replaced by `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, and span counts on the OTel spans. The `tier` label is retired; the model dimension now comes from `gen_ai.request.model`. |
| 2026-06-24 | guard-proxy `sanitize` INTERNAL child span uses `gen_ai.operation.name="chat"` — NOT a descriptive value like `"sanitize"` (M3 Decision 2) | Datadog classifies spans as `llm` kind (rendering the Input/Output panel in LLM Observability) only when `gen_ai.operation.name` is one of: `generate_content`, `chat`, `text_completion`, `completion`. A custom or descriptive value (e.g., `"sanitize"`) silently disables the Input/Output panel — the before/after messages would be on the span but invisible in the LLM Observability UI. `"chat"` is accurate (the sanitization step operates on a chat turn) and is confirmed in Datadog's documented list. Locked in PRD #22 Locked Decisions. |
| 2026-06-24 | guard-proxy reads `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` explicitly — `true` is an invalid enum value and must NOT enable capture (M3 Decision 2, content gate) | The env var is specific to `opentelemetry-util-genai` and contrib auto-instrumentation libraries; it does NOT govern raw hand-written OTel SDK spans automatically. guard-proxy must read and honor the env var via explicit code in `proxy.py`. Valid enum values that enable capture: `SPAN_ONLY`, `EVENT_ONLY`, `SPAN_AND_EVENT`. All other values (including `NO_CONTENT`, unset, and the invalid `true`) disable capture. Default `NO_CONTENT` matches the stack's off-by-default discipline (BUILD-SPEC §4: this is an "off by default; advanced beat"). Flip to `SPAN_ONLY` to arm the re-leak-trap beat. Locked in PRD #22 Locked Decisions. |
| 2026-06-24 | Beat 3 rogue tool-call uses ADK-native `execute_tool {gen_ai.tool.name}` spans only; evil-mcp-shim stays dark; tool result capture is verify-at-build (M3 Decision 3) | evil-mcp-shim is intentionally dark (see 2026-06-24 entry above). The kagent/ADK caller-side `execute_tool` span names the bad tool and is sufficient for the Beat 3 waterfall narrative. Adding tool result capture would require a non-semconv custom attribute with no OTel-standard home; it also introduces instrumentation risk without adding material pedagogical value. Whether ADK natively captures tool results in `gen_ai.output.messages` on the `execute_tool` span is a verify-at-build item for the M3 child PRD (PRD #22 Milestone 4). |
| 2026-06-24 | Two-act re-leak-trap beat (Option C): Act 1 leak visible → Act 2 Collector OTTL redaction fix demonstrated (M3 Decision 4) | Option A (env var flip only) violates research/05 re-leak control #4 — the sentinel persists in Datadog after teardown. Option B (Collector redacts before Datadog export) kills the pedagogical narrative — attendees cannot see the leak if it is already redacted before reaching Datadog. Option C is the whole point: show the leak exists (Act 1: `SPAN_ONLY` env var, original prompt visible in Datadog LLM Observability), then show it is preventable at the Collector boundary (Act 2: apply OTTL `transform/redact_sentinel` processor overlay, re-run beat, Datadog shows `[DEMO-REDACTED]`). The Collector uses `transform` processor (value replacement), NOT `redactionprocessor` (which deletes the attribute — demo requires the key to remain present with the placeholder). Act 2 config lives in a separate overlay file (`otel-collector-act2-overlay.yaml`), not in the base `otel-collector.yaml`, so the stack starts in Act 1 state by default. Env var flipped to `NO_CONTENT` after Act 2. Locked in PRD #22 Locked Decisions. |
| 2026-06-24 | M4 Decision 3: Falco rules required in Datadog for C3 and C4 (the two execution Challenges); "any exec fires" is the detection principle | Challenge C3 (grep Easter-egg secret) and Challenge C4 (fork bomb) are the two execution Challenges in the workshop (Rounds + Challenges terminology, adopted 2026-06-24). In a hardened agent pod that should only make HTTP/LLM API calls, ANY `execve` syscall is the anomaly — the command does not need to be recognizably malicious. The Falco rule "Shell or Exec In Workshop Agent Pod" (WARNING) fires for both C3's grep and C4's fork bomb for the same structural reason. Required rules visible in Datadog: (1) "Shell or Exec In Workshop Agent Pod" (WARNING) — fires for any exec in the agent pod, C3 and C4; (2) "Sensitive File Access" (NOTICE) — fires when the sentinel credential file is read; Falco knows a sensitive path was accessed, not who read it or that it is a planted canary; the manifest currently names this rule "Read Of Planted Fake Secret By Workshop Agent" — the child PRD must rename it to "Sensitive File Access" (production-realistic name that does not betray the workshop illusion or assume attribution), C3; (3) "Fork Bomb In Workload Container" (CRITICAL) — fires for C4; routes to Talon for auto-remediation AND to Datadog. The child PRD acceptance criterion is: all three rules produce visible alerts in the Datadog Event Stream (via Falcosidekick) on a live cluster run. The "any exec fires" principle is the explicit teaching point — surface it in the child PRD's beat description. |
| 2026-06-24 | M4 Decision 1: Falcosidekick→Datadog wiring is correct in the manifest; US1 site confirmed; verify-at-build on `datadog-secret` namespace | Commit `6c6a81d` wired Falcosidekick's Datadog output block. `DATADOG_HOST=https://api.datadoghq.com` is correct for US1 (confirmed 2026-06-24). The stale "Talon-only" observation in `research/23` predated the commit; research/23 corrected. Verify-at-build items for Michael's M4 child PRD: (1) `datadog-secret` must exist in the `security` namespace (Falcosidekick's namespace), not just `monitoring`; (2) confirm events flow on a live cluster. No manifest change needed for the Datadog host. |
| 2026-06-24 | M5 Decision 1 (compound): Datadog Agent install, feature flags, IAM, Cluster Agent, GitOps shape — all locked | (a) **Install:** Datadog Operator (pre-decided); two ArgoCD Applications: `gitops/apps/datadog-operator.yaml` (renders `datadog/datadog-operator` Helm chart, sync-wave `"3"`) and `gitops/apps/datadog-agent-cr.yaml` (points to `gitops/manifests/datadog/`, sync-wave `"4"`). `DatadogAgent` CR lives at `gitops/manifests/datadog/datadog-agent.yaml`. Add `datadog` namespace to `gitops/apps/namespaces.yaml`. (b) **Feature flags:** container logs ON (`spec.features.logCollection.enabled: true` + `spec.features.logCollection.containerCollectAll: true`); everything else at default. `prometheusScrape: true` and `apm: false` were pre-decided in prior Decision Log entries (2026-06-24). KISS principle: no research spike on `spec.features` options; add capabilities only when a specific beat or story requires them. (c) **IAM:** no AWS API access needed for the Agent's core function (node/container metrics, logs, named-integration scrapes). If ever needed, use EKS Pod Identity — the repo's established convention (agent, AWS LBC, ESO all use Pod Identity). Default for the workshop: no AWS role on the Agent. (d) **Cluster Agent:** enabled, 1 replica, 200m/256Mi resource requests (required for clean kube-state/events and Autodiscovery dispatch of named-integration pod annotations; budgeted in research/24 §2.3 LOCKED sizing). (e) **`datadog-secret` shape:** one Kubernetes Secret with two keys — `api-key` and `app-key` — not two separate secrets. Both keys are required: the DatadogAgent CR's `spec.global.credentials` block references both; the app key is used by the Operator/Cluster Agent for Datadog API operations (not just dashboard/monitor API automation). Whitney has both keys for her MVP trial org. M5 establishes this two-field secret shape via an ESO ExternalSecret; per-attendee provisioning and credential distribution is M8 scope. The single `datadog-secret` name is consistent with Falcosidekick and OTel Collector references already in the repo. **CRITICAL: never print credentials to the terminal** — the secret contents must not appear in terminal output, commits, or logs at any point during implementation. |
| 2026-06-24 | M5 Decision 2: per-component telemetry synthesis (research/30) confirmed complete; issue #11 closed | `research/30-per-component-telemetry-synthesis-2026.md` covers all 13 stack components with all five telemetry questions answered. Issue #11 is closed with the file path posted as a comment. No further action needed on the synthesis deliverable; wire-or-skip decisions proceed in M5 Decision 4. |
| 2026-06-24 | M5 Decision 3: DDOT vs. otelcol-contrib confirmed — no change | Standalone otelcol-contrib `0.158.2` remains the fleet Collector; Datadog Agent handles infra/logs/named integrations only; DDOT is optional on the instructor cluster only. No new information since research/24 §1.1 settled this. Not reopened. |
| 2026-06-24 | M5 Decision 4 (compound): Wire-or-skip per named integration — all 13 components resolved | **Wire (Agent named integration):** (1) **ArgoCD** — Agent `argocd` check via pod annotations; Prometheus-only; OOTB dashboard included (2) **Kyverno** — via native OTLP only (see D9); Agent `kyverno` Prometheus check SKIPPED — would duplicate metrics; (3) **Falco** — Agent `falco` check → alert logs + Prometheus metrics → OOTB dashboard (pre-decided M4 D2); (4) **Istio ambient** — Agent `istio` check, `istio_mode: ambient`, `ztunnel_endpoint` → L4 TCP metrics; OOTB dashboards are sidecar-oriented and will render sparse for ambient; Datadog community dashboard survey needed (new research issue, M7 prerequisite — see Grafana decision below); (5) **cert-manager** — Agent `cert_manager` check; `rename_labels` mapping `name` → `cert_name` required (research/18 + research/30 gotcha); no OOTB dashboard. **Collector path (no Agent check — already handled by OTel pipeline):** (6) **kagent** — OTel GenAI semconv → Collector → Datadog Agent Observability; (7) **agentgateway** — OTel → Collector → Datadog Agent Observability; (8) **guard-proxy** — Prometheus `witb_cost_usd` scraped by Collector; OTel spans added in M3. (Verify-at-build: confirm the Collector's `prometheus/receiver` has a scrape job configured for guard-proxy's metrics endpoint; add if missing.) **Skip:** (9) **KubeArmor** — not deployed, not in narrative (decided); (10) **ESO** — no official Datadog integration, generic OpenMetrics only, background component; (11) **Backstage** — emits nothing without OTel SDK, out of M5 scope; (12) **evil-mcp-shim** — intentionally dark (decided); (13) **customer-stream generator** — emits nothing (stdlib urllib POST loop). |
| 2026-06-24 | M5 Decision 5: Hostname alignment confirmed | `clusterName: watch-it-burn` goes in the DatadogAgent CR `spec.global.clusterName`. The `k8s.node.name` resource attribute is carried by the Agent automatically on EKS node telemetry — no additional configuration required. Datadog computes the unified host as `<k8s.node.name>-<clusterName>`. |
| 2026-06-24 | M5 Decision 6: Istio ambient L4-only in M5; L7 mTLS exfil story deferred to optional GitHub issue | M5 deploys L4-only ztunnel telemetry (Agent `istio` check, `istio_mode: ambient`). The L7 mTLS story — showing encrypted customer traffic exfiltrated to an external destination but rendered unusable by mTLS at the destination — is a strong narrative (discussed by Whitney + Michael) but time-uncertain. Decision: created optional [issue #25](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/25) "Optional: Add Istio ambient waypoint proxy for L7 mTLS in exfil challenge"; it is explicitly NOT in M5 or M6 scope. If time allows before the workshop, the optional issue can be implemented as a standalone addition. |
| 2026-06-24 | M5 Decision 7: EKS + CloudWatch cross-account integration — skip | No EKS + CloudWatch integration. Not per-attendee; no workshop narrative. |
| 2026-06-24 | M5 Decision 8: Agent resource footprint — carry research/24 §2 LOCKED sizing | Node Agent: 200m CPU / 256Mi memory. Process Agent: 100m / 200Mi. Cluster Agent: 200m / 256Mi (locked in D1(d)). APM feature: OFF. System Probe: OFF. These numbers go directly into the DatadogAgent CR's resource request fields. No guessing or research needed; research/24 §2.3 is the authoritative source. |
| 2026-06-24 | M5 Decision 9: Kyverno native OTLP (`otelConfig=grpc`) — enable; Agent Prometheus check — skip | Enable Kyverno's native OTLP by setting `otelConfig: grpc` and `otelCollector: <in-cluster-otel-collector-endpoint>` in the Kyverno Helm values (`gitops/apps/kyverno.yaml` `helm.valuesObject`). This sends both Prometheus-format **metrics** AND policy-decision **traces** to the Collector (→ Datadog APM + metrics backend). The Agent `kyverno` Prometheus check is skipped — enabling both would duplicate metrics and add billing noise. Rationale: Kyverno is center-stage (Audit→Enforce toggle, Beat 1); native OTLP aligns with the Datadog-additive OTel principle and gives traces that the Agent check cannot provide. The Collector → Datadog routing is already established; this is an additive sender-side config only. |
| 2026-06-24 | No Grafana dashboard imports; Datadog community dashboards require a new research spike (M7 prerequisite) | Whitney works at Datadog. No Grafana dashboard imports at any point in the project. The research/30 "community dashboard" column lists Grafana dashboard IDs throughout — those entries are inapplicable and should not be used as M7 import candidates. Datadog community dashboards are a distinct format: GitHub JSON files (DataDog/community-lab or similar) imported via Datadog UI, API, or Terraform provider. A new research spike is needed before M7 can proceed: survey which importable Datadog community dashboard JSON files exist for stack components without OOTB dashboards (at minimum: Kyverno, Istio ztunnel, ESO, cert-manager). For Kyverno: determine whether any community dashboard's metric names are calibrated to Agent Prometheus check output or raw OTLP output — our path (D9) uses OTLP. This spike is a **M7 prerequisite gate**, not an M5 dependency. Created as [issue #24](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/24). M7 Step 0, Step 2 Decision 1, and "Done when" updated to reflect this. |
| 2026-06-24 | M4 Decision 2: Wire both Falcosidekick native output AND the Datadog Agent named integration — they are additive and feed different Datadog surfaces | The Datadog Falco Agent integration (7.59.1+) collects individual alert **logs** (JSON per alert → Log Explorer) and aggregate **Prometheus metrics** (→ OOTB dashboard). It does NOT require Falcosidekick and does not use the Datadog Events API. Falcosidekick's Datadog output sends individual alerts to the **Event Stream** (Datadog Events API) — a different surface. No duplication: logs vs. events are separate data types in separate Datadog UIs. Wire both: Falcosidekick native output in M4 (already in manifest, no Agent dependency); Agent named integration in M5 when the Agent DaemonSet is deployed. The child PRD for M4 notes M5 adds the second path. Source: https://docs.datadoghq.com/integrations/falco/ verified 2026-06-24. Prior reasoning in this document that described the integration as "metrics-only" was incorrect and has been corrected in research/18 and research/23. |
| 2026-06-24 | M8 Decision 1 (provisioning) resolved: ~60 trial orgs manually provisioned by Michael | Michael manually provisioned the pool of ~60 Datadog trial orgs; `pool.csv` is the source of truth (never committed). No Datadog API / Terraform / scripted provisioning path was needed or built. The net-new research spike originally required for Decision 1 is no longer needed. Attendee count settled at 60 (fleet supports it; EKS quota 100). |
| 2026-06-24 | M8 Decision 3 (surfacing credentials) resolved: distribution done by Michael | Attendees receive their Datadog credential bundle via `merge_pool.py` + `pool.csv` + a success page on the provisioning site. Mechanism and contents settled. |
| 2026-06-24 | M8 Decision 2 (master credential store — sharing) resolved: 1Password shared vault done | 1Password shared vault is set up between Michael and Whitney as the mechanism for Whitney to access the pool. AWS Secrets Manager remains the intended ESO source for per-cluster injection; the path from `pool.csv` → AWS Secrets Manager master store needs confirmation as part of the M8 child PRD. |
| 2026-06-24 | M8 Decision 6 (rotation/expiry) resolved: manual teardown, no automated rotation | Teardown is manual trigger via `teardown/teardown.sh` at end of run (40-minute auto-expiry idea dropped by Michael 2026-06-24). Trial orgs expire ~14 days after provisioning — a separate clock. No automated rotation plan. Blast-radius mitigation for leaked creds is short-lived IAM session lifetimes, not cluster auto-destroy. |
| 2026-06-24 | M8 division of labor clarified: Michael's substrate done; Whitney owns Decision 5 (cluster injection) | Michael's completed: `datadog-secret` consumers wired in `otel-collector.yaml` and `falcosidekick.yaml`; ESO + EKS Pod Identity substrate ready. Whitney's remaining work: resolve Decision 4 (app keys needed in cluster secret?), resolve Decision 5 "org fork" question (attendee's own trial org vs shared org Whitney watches vs both), write the ESO `ExternalSecret` per namespace, create the M8 child PRD. |
| 2026-06-25 | M6 acceptance verification: Datadog API, not Playwright/browser automation | Datadog's Service Map renders as canvas/SVG — browser selectors are brittle and require managing session cookies. The service dependencies API returns the topology graph programmatically, making assertions machine-verifiable and repeatable. The same principle applies to log-trace correlation pivots (query logs by `trace_id`, query APM for associated logs). Playwright/browser automation is not used in M6 or the future platform component UST PRD. |
| 2026-06-25 | M6 Service Map verification asserts connectivity (edges), not just existence | Existence alone (a node appearing in the Service Map) is insufficient — a node with no edges does not validate the workshop story. The assertion is: `guard-proxy` calls `agentgateway`, `agentgateway` calls `kagent`, `kagent` calls `Bedrock`. Uses `GET /api/v1/service_dependencies` response. A service node that appears but has no outbound edges to the expected downstream fails the check. |
| 2026-06-25 | M6 log-trace correlation verification: both pivot directions via API | (a) Forward pivot: query Datadog logs API with `trace_id:<id-from-known-trace>` → assert ≥1 result returned; (b) Reverse pivot: query APM API for that trace → assert associated logs are present. Both directions testable without a browser. The `trace_id` used for the assertion is harvested from a live cluster run during the M6 verify step. |
| 2026-06-25 | M6 verification script location: `verify/test_datadog_service_map.py` | Follows the existing flat-file Python naming convention in `verify/` (`test_tagging.py`, `test_observability.py`). No subdirectory needed. The script uses the Datadog API directly (DD_API_KEY + DD_APP_KEY from environment); it does not depend on a live cluster connection — only on Datadog having received recent telemetry. |
| 2026-06-25 | Platform component UST is a future standalone PRD, not in M6 scope | M6 child PRD covers: (1) fix agentgateway's stale UST values (`service.version=CLUSTER_TIER` → `v1.3.0`; `deployment.environment.name=watch-it-burn` → `production`), (2) `peer.service` placement, (3) log-trace correlation for Python apps, (4) Service Map live-verify via API. Platform component UST (adding `tags.datadoghq.com/*` pod annotations to third-party Helm charts for ArgoCD, Kyverno, Falco, cert-manager, Istio, etc.) is a separate PRD with no bearing on M6's acceptance criteria. |
| 2026-06-25 | Future platform component UST PRD: milestone-per-component + Datadog API verification loop | Each milestone in the future platform component UST PRD follows the same pattern as M6: implement the annotations → run `GET /api/v1/service_dependencies` → assert the component appears with expected edges → iterate until passing. This makes acceptance machine-verifiable without relying on a human to eyeball the Datadog UI. The same `verify/test_datadog_service_map.py` script (or a companion script) can be extended per component. |
| 2026-06-25 | M4 live-verify finding: Falco `in_agent_container` macro must use `k8s.pod.label[kagent]`, not `k8s.pod.label[app]` | The kagent operator labels the agent pod with `kagent=workshop-agent` (not `app=workshop-agent`), so the macro condition `k8s.pod.label[app] = "workshop-agent"` never matched — all C3 and C4 agent-pod rules silently failed to fire on a live cluster. Fixed to `k8s.pod.label[kagent] = "workshop-agent"` (commit 0a37f98 in PRD #23). Any future Falco rule targeting the workshop agent pod must use the `kagent` label key, not `app`. |
| 2026-06-25 | M4 live-verify finding: Falcosidekick chart 0.14.0 reads `extraEnv` at `config.extraEnv`, not root level | The manifest had `DATADOG_APIKEY` under a root-level `extraEnv` key. Chart 0.14.0 expects it at `config.extraEnv`; the root-level key is silently ignored, causing the Datadog output to stay disabled despite the host block being correctly configured. Fixed in commit c7f4e7b (PRD #23). Any future Falcosidekick configuration that sets environment variables must use `config.extraEnv`. |
| 2026-06-25 | M4 Datadog Event Stream confirmation is a manual facilitator check — not automatable from the cluster | Only the Datadog ingest API key (`api-key`) is deployed in the cluster; the Events query API requires an app key (`app-key`), which is not present in the `security` namespace secret. Automated verify scripts cannot query the Event Stream to assert events are visible. The M4 acceptance criterion is satisfied by: (a) `falcosidekick` logs showing `Datadog - POST OK (202)` (confirmed in PRD #23 live run), and (b) the facilitator manually verifying the Datadog UI after the run. This constraint applies to any automated acceptance criterion that queries the Datadog Events API — the app key is not deployed in the cluster, so cluster-aware verify scripts cannot use it. |
| 2026-06-25 | M6 Decision 2 resolved: `OTEL_RESOURCE_ATTRIBUTES` is the same-tag mechanism; no new configuration needed | Both the Datadog Agent (container log pipeline) and the OTel SDK (traces/metrics via OTel Exporter) read `OTEL_RESOURCE_ATTRIBUTES` from the pod environment. The Agent auto-tags container logs with those values; the SDK emits them as resource attributes on spans. The tags are aligned automatically — no extra configuration needed. The only action in M6 is fixing agentgateway's two stale values (`service.version=CLUSTER_TIER` → `v1.3.0`; `deployment.environment.name=watch-it-burn` → `production`). All other AI-layer components are correctly configured. |
| 2026-06-25 | M6 Decision 3 resolved: `peer.service` in guard-proxy code; OTTL Collector transform as fallback for third-party components | guard-proxy's outbound CLIENT span (proxy.py → agentgateway) sets `peer.service="agentgateway"` in code at span creation. Rationale: the attribute travels with the span through any pipeline; no maintenance debt from host-matching rules; it costs one line since the CLIENT span is being written anyway. agentgateway and kagent outbound spans: OTTL transform processor in the Collector as the fallback mechanism, with verify-at-build to check whether they already set `peer.service` natively (if yes, no OTTL rule needed). The guard-proxy CLIENT span code and the corresponding Weaver registry entry both belong to M6's child PRD scope. |
| 2026-06-25 | Weaver registry grows incrementally — every child PRD that introduces span groups extends the registry in the same PR | The registry is not defined upfront. The pattern, universal across all span-adding child PRDs: (1) add the Weaver group definition for every new span group introduced in that PR; (2) run `weaver registry check` locally before merge; (3) run `weaver live-check` as the terminal acceptance step on the live cluster. PRD #22 (M3 child PRD) established this pattern for guard-proxy HTTP SERVER and `sanitize` INTERNAL spans. M6's child PRD follows it for the guard-proxy CLIENT span group. Future PRDs that add new span groups (platform component UST, any new instrumented service) follow the same three-step pattern. The `live-check` surfaces gaps from third-party spans (agentgateway non-`gen_ai.*` spans, if any); those are follow-up items, not M6 blockers. |
| 2026-06-25 | M6 Weaver scope: only the guard-proxy CLIENT span group needs a new local registry entry | `peer.service` is defined in the upstream OTel semconv registry and arrives via the `dependencies:` import in `registry_manifest.yaml` — no local group entry needed. UST attributes (`service.name`, `deployment.environment.name`, `service.version`) are resource attributes on the span, not span group definitions — they are not defined as local Weaver group entries at all. The only new local registry entry required in M6's child PRD is the group definition for guard-proxy's outbound CLIENT span. |
| 2026-06-25 | ~~M6 child PRD must defensively bootstrap `weaver/registry/`~~ **(SUPERSEDED by entry below — design order = build order; assume it exists)** | ~~`weaver/registry/` does not currently exist in the repo. PRD #20 M6 plans to create it, but M6's child PRD cannot rely on that being done first. M6's child PRD must include step 1: check whether `weaver/registry/` exists; if not, create it.~~ |
| 2026-06-25 | M6 child PRD upstream dependency assumption: all upstream milestone child PRDs are complete when M6 starts | M6's child PRD can assume the Weaver registry (`weaver/registry/`) created in PRD #20 M6 exists; guard-proxy SERVER and sanitize spans are already in the registry (PRD #22 M3); the Datadog Agent DaemonSet is deployed (PRD #26); and all other M1–M5 implementation work is done. No defensive "if X doesn't exist, create it" language is needed in M6's child PRD. The meta-PRD's design order = build order principle enforces this sequencing — Michael implements each child PRD before the next design conversation begins. |
| 2026-06-25 | M6 Decision 4 resolved: stdlib JSON logging for guard-proxy log-trace correlation | guard-proxy emits zero existing log output — `log_message` returns `None` (silences BaseHTTPRequestHandler access log); no `logging` module, no `print()`, no `sys.stderr` calls anywhere in `proxy.py`. Approach settled: stdlib `logging` + JSON formatter to stdout; extract `trace_id`/`span_id` from `opentelemetry.trace.get_current_span().get_span_context()` (opentelemetry-api available via Operator injection after M3); Datadog Agent file/stdout pipeline auto-recognizes OTel-standard field names — no remapping needed. Log guard decision events: blocklist hit, classifier block, output scrub fired, agent forward error — these are the observability-interesting moments that enable the "View related logs" pivot. |
| 2026-06-25 | M6 Decision 5 resolved: Service Map from pure OTLP — binary acceptance gate with debug path | Acceptance criterion is binary: `GET /api/v1/service_dependencies` must return the expected edges (`guard-proxy→LLM Guard`, `guard-proxy→agentgateway`, `agentgateway→kagent`, `kagent→Bedrock`) or M6 is not done — no partial pass. If Bedrock appears as external-only in the API response, 3 internal edges is acceptable; verify-at-build which edges the live cluster emits. Child PRD includes a debug path for Michael: if edges are missing, check span attributes (via `GET /api/v1/traces` or Datadog MCP), confirm `peer.service` and span kind are set correctly on CLIENT spans, then re-run the query. No fallback to Agent trace path — if OTLP Service Map fails, fix the OTLP pipeline. |
