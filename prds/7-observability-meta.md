# PRD #7 — Observability Suite (Meta-PRD)

**GitHub Issue:** [#7](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7)
**Status:** In Progress
**Priority:** High
**Last updated:** 2026-06-22

---

## How To Use This Meta-PRD (read first)

This is a **meta-PRD**: its milestones do not implement observability directly. Each milestone is a
design conversation with Whitney that produces a **child PRD** (via `/prd-create`) implementing one
**vertical slice** of the observability strategy — a thin end-to-end increment that is verifiable in
the Datadog UI on its own.

**Walking-skeleton ordering.** Slice 1 is a minimal end-to-end MVP: real telemetry visible in one
Datadog trial account. Each later slice adds exactly one capability that can be verified in the
Datadog UI before the next begins. We do NOT build horizontal layers that show nothing until several
are done.

**Design order = build order, pipelined.** Michael's build system implements each child PRD as soon
as it is written. Therefore **every child PRD must be buildable on only what earlier slices already
built — never on a later slice.** This is the `prd-dependency-management` rule: each PRD is mergeable
on top of `main` as it exists. We design Slice N, hand it off, and design Slice N+1 while Slice N is
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
  highest existing spike is `research/27-*`; the next new spike is `research/28-…`. Increment
  sequentially. Research spikes always live in `research/`, never elsewhere.
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
- `docs/transcripts/observability-architecture-paths.md` — Path 1/2/3 comparison; **Path 2 chosen**
- `docs/observability-priorities.md` — living must-have vs. nice-to-have list (created in Slice 1)

**Settled decisions — do NOT re-litigate:**
- **Architecture: Path 2 hybrid** — OTel Collector for OTLP/GenAI + Datadog Agent DaemonSet for EKS infra. Deployment shape settled in `research/24` §1.1: standalone otelcol-contrib Collector (pinned `0.158.2`) as the fleet collector + standalone Datadog Agent DaemonSet for infra only; do NOT make DDOT the fleet collector (DDOT optional on the instructor cluster only).
- **TypeScript rewrite of guard-proxy is NOT happening.** All Python apps stay Python. spiny-orb is off the table. AI-layer instrumentation uses the Python OTel SDK directly, or kagent/agentgateway built-in OTel output.
- **Already wired:** `spanmetricsconnector` with `add_resource_attributes: true`; UST tags via `OTEL_RESOURCE_ATTRIBUTES` on guard-proxy/agentgateway/kagent; `cluster.name=watch-it-burn` upserted by the Collector `resource` processor; OTel Collector pinned at contrib `0.158.2`.
- **Falcosidekick → Datadog:** wired in commit `6c6a81d`, but `research/23` (predates the commit) observed Falcosidekick forwarding only to Talon. Verify-at-build in Slice 4; not a confirmed-working fact.
- **Cost-counter key (live-resolved):** live validation (kagent 0.9.9) found the key is `result.metadata.kagent_usage_metadata`, NOT `adk_usage_metadata` (`research/14` was wrong); `record_usage()` already accepts both, kagent-first. Verify it still holds; not an open bug.
- **Attendee Datadog model:** **per-attendee trial orgs** (confirmed 2026-06-22). The MVP (Slice 1) uses ONE trial account; per-attendee scale-out is Slice 8. `PROJECT_STATE.md`'s "one shared org" line is stale — corrected in Slice 8.
- **Division of labor:** Whitney owns Datadog accounts/keys/Agent install/dashboards. Michael owns OTel-side wiring + manifest annotations + `datadog-secret` consumption.

---

## Living Document: `docs/observability-priorities.md`

Created in Slice 1, updated at the end of every later slice if design conversations shifted
priorities. **Read it in Step 0 of every slice after Slice 1.**

Known must-haves going in:
- **Service Map renders in the Datadog UI** (`guard-proxy → agentgateway → kagent → Bedrock`, each node health-indicated) — requires UST done correctly (Slice 6)
- LLM call waterfall visible in APM traces (Slice 2)
- Rogue MCP tool-call chain visible as a trace waterfall — Beat 3 (Slice 3)
- Cost counter accumulating in real time (Slice 1 proves it; refined later)
- Before/after sanitization visible in traces — re-leak trap beat (Slice 3)
- Falco runtime alerts surfacing in Datadog when exfil is attempted (Slice 4)

---

## Cross-Cutting Decisions — locked in Slice 1

These, if decided late, force rework of earlier slices. Slice 1 settles them even though their full
payoff arrives later:
- **Collector pipeline shape** — confirm standalone contrib `0.158.2`; whether `datadog/connector` is added (Trace Metrics since otelcol-contrib v0.95.0); `datadog.prometheusScrape.enabled` stays **off** (double metrics + billing).
- **UST tag vocabulary** — exact `service.name` per component and, critically, **`service.version` semantics**: cluster-tier (`cluster-1/2/3`) vs. model name (`haiku/sonnet/opus`). The corpus contains BOTH answers (`research/23` says model-name; planning transcript, `research/18`, `research/19`, `TECH-STATUS.md` say cluster-tier) — resolve explicitly.
- **Account model for MVP** — one trial account now; per-attendee scale-out deferred to Slice 8.
- **Weaver schema** — decide whether a Weaver registry encoding the OTel GenAI semconv (to `weaver registry live-check` `gen_ai.*` in CI) is worthwhile. If yes, **start the registry in Slice 1** so later slices validate against it from the first traces.

---

## Milestones (Vertical Slices)

> Every slice is self-contained: it lists its own reads, problem framing, decisions, and child-PRD
> creation steps. Follow the steps written in your slice; do not look to a shared template.

---

### Slice 1 — MVP walking skeleton: data in one Datadog account, visible in the UI

**End-state goal:** A single Datadog trial account shows the AI layer's existing telemetry — the
guard-proxy `witb_cost_usd` / `witb_tokens_total` / `witb_requests_total` metrics and whatever traces
flow today — arriving through the existing Collector + Datadog exporter and **visible in the Datadog
UI**, with the cost counter reading non-zero. This is the smallest end-to-end proof that the pipeline
works. It also locks the Cross-Cutting Decisions above.

**Step 0 — Read:**
- This meta-PRD's top matter (conventions, settled decisions, cross-cutting decisions)
- `research/18-datadog-integrations-stack-2026.md`, `research/19-datadog-otel-ust-correlation-2026.md`, `research/23-…`, `research/24-…`
- `research/05-otel-genai-observability.md` (for the Weaver/GenAI semconv decision), `research/16-typescript-agent-spiny-weaver-2026.md` (Weaver CI live-check context; ignore the spiny-orb/TS parts — superseded)
- Codebase: `gitops/apps/otel-collector.yaml` in full; `agent/gateway/guard-proxy/guard-proxy.yaml` and the guard-proxy `/metrics` output; `gitops/ai-layer/resources.yaml` (current `OTEL_RESOURCE_ATTRIBUTES`)

**Step 1 — Problem (write 3-5 sentences):** What is the minimal set of telemetry already emitted, and
what is the shortest path to seeing it in one Datadog account's UI? What cross-cutting decisions must
be locked now to avoid reworking later slices?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Collector pipeline shape** — confirm standalone contrib `0.158.2`; decide `datadog/connector` (Trace Metrics); confirm `datadog.prometheusScrape.enabled` off with reasoning.
2. **UST tag vocabulary + `service.version` semantics** — resolve cluster-tier vs. model-name (corpus conflict above); define `service.name` per component. Note: `DD_SERVICE`/`DD_ENV`/`DD_VERSION` env vars do NOT work on the OTel path — UST flows via `OTEL_RESOURCE_ATTRIBUTES`; `deployment.environment.name`→`env` needs Agent ≥7.58.0 or Datadog Exporter ≥v0.110.0.
3. **MVP account** — confirm one trial account for the MVP; how its `datadog-secret` is supplied for the slice (manual is fine for one account).
4. **Cost-counter verify** — confirm `record_usage()` reads `kagent_usage_metadata` (live-resolved) and the MVP shows non-zero spend.
5. **Weaver schema worthwhile?** — decide. If yes, start a Weaver registry encoding the OTel GenAI semconv for CI `live-check`; if no, record why.

**Step 3 — Produce the child PRD:**
1. Create `docs/observability-priorities.md` and populate must-have/nice-to-have (seed from "Known must-haves").
2. Run `/prd-create` for a child PRD implementing the MVP per decisions 1-5, acceptance including "AI-layer metrics + traces visible in one Datadog trial account's UI; cost counter non-zero" (`/prd-update-decisions` for the Decision Log).
3. Add to `docs/ROADMAP.md` as `- MVP: telemetry in one Datadog account (PRD #[issue-id])`, first in build order.
4. Run `/prd-update-progress` to commit + push.
5. Clear context; run `/prd-next` for Slice 2.

**Done when:**
- [ ] Cross-cutting decisions (collector shape, UST vocabulary incl. `service.version`, MVP account, Weaver) recorded in the child PRD's Decision Log with reasoning
- [ ] `docs/observability-priorities.md` exists and lists the Service Map as a must-have
- [ ] A child PRD issue exists whose acceptance includes telemetry visible in one account's UI + non-zero cost counter
- [ ] ROADMAP updated, MVP first in build order

---

### Slice 2 — LLM call waterfall + tool-call visibility

**End-state goal:** The Datadog APM trace view shows the `invoke_agent → plan → execute_tool`
waterfall for the AI layer, with `gen_ai.*` attributes (model, token counts) and `execute_tool` spans
naming tools — visible in the UI on the same account from Slice 1.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- The MVP child PRD + its Decision Log (Slice 1) — **gates this slice**
- `research/05-otel-genai-observability.md`, `research/14-verify-at-build-sweep-2026.md`, `research/23-…`
- Codebase: `agent/gateway/guard-proxy/` (current span output), `agent/gateway/agentgateway.yaml`, `gitops/ai-layer/resources.yaml`; `beats/` directories that depend on the trace waterfall

**Step 1 — Problem (write 3-5 sentences):** Which demo beats need the LLM/tool waterfall, and what is
emitted today vs. missing?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Does Datadog LLM Observability surface from pure OTel `gen_ai.*` spans, or does it require dd-trace?** No existing spike answers this (`research/05` names it a gap). Run a net-new `/research` spike before presenting.
2. **GenAI semconv stability / opt-in** — all `gen_ai.*` is Development; names churned v1.36→v1.37; `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` must be set deliberately (`research/05`, `research/06`). Pin a version; decide the opt-in. If Weaver was started in Slice 1, validate against the registry.
3. **Python OTel SDK instrumentation plan for guard-proxy** — which spans to emit manually vs. relying on kagent/agentgateway built-in OTel output (kagent tracing is off by default — `otel.tracing.enabled: true`).
4. **agentgateway v1.3.0 field-path verification** — repo has v1.2.1 pins; verify field paths against v1.3.0 GA before finalizing.

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` for a child PRD per decisions 1-4, acceptance including "LLM/tool-call waterfall visible in APM" (`/prd-update-decisions`).
3. Add to `docs/ROADMAP.md` as `- LLM call & tool-call waterfall (PRD #[issue-id])`, after the MVP.
4. Run `/prd-update-progress` to commit + push.
5. Clear context; run `/prd-next` for Slice 3.

**Done when:**
- [ ] Decisions 1-4 recorded with reasoning
- [ ] A net-new research spike for Datadog LLM Observability from pure OTel gen_ai.* spans exists in `research/`
- [ ] A child PRD issue exists whose acceptance includes the waterfall visible in APM
- [ ] ROADMAP updated

---

### Slice 3 — Security beats: before/after sanitization + rogue MCP tool chain

**End-state goal:** The Datadog trace view shows the re-leak-trap story (before vs. after
sanitization at the guard-proxy) and Beat 3's rogue MCP tool-call chain as a trace waterfall —
visible in the UI.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- The LLM-waterfall child PRD + its Decision Log (Slice 2) — **gates this slice**
- `research/05-otel-genai-observability.md` (re-leak trap design), `research/12-mechanism-verification-2026.md` (collector-side symmetric redaction), `research/04-mcp-security.md`
- Codebase: `agent/gateway/guard-proxy/` (sanitization logic, before/after text held in memory), `beats/03-bad-mcp-excessive-agency/` and its `evil-mcp-shim/server.py`

**Step 1 — Problem (write 3-5 sentences):** What must a trace show to land the re-leak trap and the
rogue-tool beat, and what is the re-leak risk if content capture is naive?

**Step 2 — Resolve with Whitney (one at a time):**
1. **`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`** — where it's set; content capture is load-bearing for the re-leak trap but must be redacted symmetrically in the Collector (`research/12`). Decide the capture + redaction design.
2. **Rogue MCP tool-call representation** — confirm the `execute_tool {gen_ai.tool.name}` span names the bad tool so Beat 3 reads as a waterfall.
3. **Re-leak-trap trace teardown** — ensure trace data is torn down so no span store retains even the fake sentinel post-run (`research/05` re-leak control #4).

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` for a child PRD per decisions 1-3, acceptance including "before/after sanitization and rogue MCP chain visible in traces" (`/prd-update-decisions`).
3. Add to `docs/ROADMAP.md` as `- Security-beat traces (PRD #[issue-id])`, after Slice 2.
4. Run `/prd-update-progress` to commit + push.
5. Clear context; run `/prd-next` for Slice 4.

**Done when:**
- [ ] Decisions 1-3 recorded with reasoning
- [ ] A child PRD issue exists whose acceptance includes both security-beat views in traces
- [ ] ROADMAP updated

---

### Slice 4 — Falco runtime alerts into Datadog

**End-state goal:** When exfil/abuse is attempted, the Falco alert is visible in Datadog (OOTB Falco
dashboard or events), confirmed live.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- Prior slice child PRDs + Decision Logs — **gate this slice**
- `research/06-cncf-stack.md` (Falco/Falcosidekick), `research/18-…` (Falco integration row), `research/23-…`
- Codebase: Falco + Falcosidekick manifests in `gitops/apps/`, `gitops/ai-layer/resources.yaml`

**Step 1 — Problem (write 3-5 sentences):** Which beats need Falco alerts in Datadog, and is the
Falcosidekick→Datadog path actually live?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Falcosidekick → Datadog (verify-at-build)** — confirm Falcosidekick forwards security events to Datadog, not only to Talon. Commit `6c6a81d` wired it but `research/23` observed Talon-only; confirm on a live cluster.
2. **Falco integration vs. Falcosidekick native output** — decide which path surfaces alerts (named integration Agent 7.59.1+ has an OOTB dashboard; Falcosidekick has native Datadog output). Note the Agent integration depends on Slice 5; if Slice 5 isn't built yet, use Falcosidekick native output so this slice stays buildable.
3. **Which alerts/rules** must be visible for the demo.

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` for a child PRD per decisions 1-3, acceptance including "Falco alert visible in Datadog on a live exfil attempt" (`/prd-update-decisions`).
3. Add to `docs/ROADMAP.md` as `- Falco alerts in Datadog (PRD #[issue-id])`, after Slice 3.
4. Run `/prd-update-progress` to commit + push.
5. Clear context; run `/prd-next` for Slice 5.

**Done when:**
- [ ] Decisions 1-3 recorded with reasoning
- [ ] Falcosidekick→Datadog path live-verified (or the Falcosidekick-native fallback chosen)
- [ ] A child PRD issue exists whose acceptance includes a Falco alert visible in Datadog
- [ ] ROADMAP updated

---

### Slice 5 — EKS infrastructure + named integrations ("Datadog sees everything")

**End-state goal:** The Datadog Agent DaemonSet is deployed; EKS nodes/pods/containers and the chosen
named integrations are visible and correct in the Datadog UI.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- Prior slice child PRDs + Decision Logs — **gate this slice**
- `research/05-…`, `research/06-…`, `research/18-…`, `research/23-…`, `research/24-…`
- Codebase: every YAML in `gitops/apps/`, `gitops/ai-layer/resources.yaml`; `beats/` (what each beat's component needs)

**Step 1 — Problem (write 3-5 sentences):** Which infra signals and named integrations earn their
setup cost for the workshop, and what does "working" look like in the UI for each?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Per-component telemetry synthesis (research deliverable)** — produce `research/28-per-component-telemetry-synthesis-2026.md`: per IDP component (ArgoCD, Kyverno, Falco, KubeArmor, Istio ambient, ESO, cert-manager, Backstage, kagent, agentgateway, guard-proxy, evil-mcp-shim, customer-stream generator) — what it emits, Datadog integration status, OOTB dashboard, UST applicability, gotcha, and **wire-or-skip with reasoning**. Run `/research <specific question>` for any unverified component; include full output.
2. **DDOT vs. contrib** — `research/24` §1.1 already confirmed: keep standalone contrib `0.158.2` as fleet collector; standalone Agent for infra only; DDOT optional on instructor cluster. Confirm, do not re-open without new info.
3. **Wire-or-skip per named integration** — one component at a time. For each integration wired, define its **UI-verification checklist**: which dashboard, which metric, and which view proves it works in the Datadog UI.
4. **Hostname alignment** — Datadog computes host as `<k8s.node.name>-<cluster name>`; `cluster.name` already upserted; confirm `k8s.node.name` on host telemetry + matching `DD_CLUSTER_NAME` on the Agent (`research/24` §1.2).
5. **Istio ambient: L7 or L4-only?** — accept L4-only ztunnel metrics, or deploy a per-namespace waypoint for L7 (`research/23` Decision 6, `research/18`).
6. **EKS + CloudWatch cross-account integration scope** — in scope at all, and almost certainly NOT per-attendee (`research/24` §1.4)? Facilitator-only vs. skip.
7. **Agent resource footprint** — carry sizing from `research/24` §2 (node Agent 200m/256Mi, Process Agent 100m/200Mi, Cluster Agent 200m/256Mi; APM + System Probe OFF) into the child PRD.
8. **Kyverno native OTLP opt-in** (`otelConfig=grpc`) — enable to put policy-decision traces in the same span tree? (`research/18`).

**Step 3 — Produce the child PRD:**
1. Write `research/28-…` (decision 1 deliverable).
2. Update `docs/observability-priorities.md` if priorities shifted.
3. Run `/prd-create` for a child PRD per decisions 2-8, acceptance including a per-integration UI verification checklist (`/prd-update-decisions`).
4. Add to `docs/ROADMAP.md` as `- EKS infra & named integrations (PRD #[issue-id])`, after Slice 4.
5. Run `/prd-update-progress` to commit + push.
6. Clear context; run `/prd-next` for Slice 6.

**Done when:**
- [ ] `research/28-…` exists with a wire-or-skip decision (+ reasoning) per component
- [ ] Decisions 2-8 recorded with reasoning
- [ ] A child PRD issue exists whose acceptance includes a per-integration UI verification checklist
- [ ] ROADMAP updated

---

### Slice 6 — UST at full fidelity + Service Map + correlation pivots

**End-state goal:** The Datadog **Service Map renders** (`guard-proxy → agentgateway → kagent →
Bedrock`, each node health-indicated), and "View related logs" pivots from a trace and "View Trace in
APM" pivots from a log — confirmed end-to-end on the live cluster. Token-cost panels can split by
model tier.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- Prior slice child PRDs + Decision Logs (esp. Slice 1's UST vocabulary, Slice 5's Agent deploy) — **gate this slice**
- `research/19-datadog-otel-ust-correlation-2026.md`, `research/23-…` (Decisions 5, 8)
- Codebase: `gitops/ai-layer/resources.yaml`, `agent/gateway/agentgateway.yaml`, `agent/gateway/guard-proxy/` (log output format), every workload manifest in `gitops/apps/` (UST-label inventory), `gitops/apps/otel-collector.yaml`

**Step 1 — Problem (write 3-5 sentences):** What correlation and Service-Map gaps remain after the
earlier slices, given UST vocabulary was locked in Slice 1?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Full UST rollout + gap inventory** — apply the Slice 1 vocabulary to every workload; list which workloads still lack UST labels.
2. **Same-tag mechanism for correlation** — how the Agent (logs) and OTel Exporter (traces/metrics) carry identical `service`/`env`/`version`.
3. **`peer.service` + span-kind prerequisite** — the pure-OTel Service Map infers edges from `peer.service` and correct span kinds (`research/23` Decision 8); decide where these are set.
4. **Log-trace correlation for Python apps** — first determine **which pipeline the Python logs are on: OTLP vs. file/stdout scraping**. On the OTLP pipeline the Agent auto-injects trace context; on file/stdout the `trace_id`/`span_id` fields must be explicit in the log JSON (`research/19`). Then decide: does UST alone suffice, or is explicit injection required? If injection is needed: Python OTel SDK log bridge vs. manual extraction from the active span context. This likely needs a live-cluster `/research` check — run it before presenting the decision.
5. **Service Map from pure OTLP (live-verify)** — whether the full map renders without the Agent handling traces (`research/19` flags this Medium-confidence). This needs a **live-cluster check**.

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` (Service Map is a must-have).
2. Run `/prd-create` for a child PRD per decisions 1-5, acceptance including "Service Map renders in the UI" and both correlation pivots working (`/prd-update-decisions`).
3. Add to `docs/ROADMAP.md` as `- UST, Service Map & correlation (PRD #[issue-id])`, after Slice 5.
4. Run `/prd-update-progress` to commit + push.
5. Clear context; run `/prd-next` for Slice 7.

**Done when:**
- [ ] Decisions 1-5 recorded with reasoning
- [ ] A child PRD issue exists whose acceptance includes the Service Map rendering + both pivots
- [ ] ROADMAP updated

---

### Slice 7 — Custom workshop dashboards

**End-state goal:** The agreed must-have workshop dashboards exist as committed definitions, each
backed by data confirmed already flowing from earlier slices.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- All prior slice child PRDs + Decision Logs — **gate this slice** (a dashboard can't be built on absent data)
- `research/24-…`, `docs/transcripts/observability-architecture-paths.md` (Path 3 candidate dashboard list)
- Codebase: `agent/gateway/guard-proxy/` (confirm `witb_cost_usd`/`witb_tokens_total`/`witb_requests_total`), `beats/`

**Step 1 — Problem (write 3-5 sentences):** Which dashboards tell the workshop story, and is each
one's data confirmed flowing before we commit to building it?

**Step 2 — Resolve with Whitney (one at a time):**
1. For each candidate (Wasted Tokens Over Time, Model Tier Cost Race, Tool Call Heatmap, KubeArmor Enforcement, Guardrail Toggle Timeline): **must-have or nice-to-have?**
2. For each must-have: **is its data source confirmed flowing?** If not, defer — do not build on absent data.
3. **Dashboard JSON as code (committed)** vs. UI-built?

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` for a child PRD per decisions 1-3 (`/prd-update-decisions`).
3. Add to `docs/ROADMAP.md` as `- Custom dashboards (PRD #[issue-id])`, after Slice 6.
4. Run `/prd-update-progress` to commit + push.
5. Clear context; run `/prd-next` for Slice 8.

**Done when:**
- [ ] Must-have/nice-to-have decided per dashboard with reasoning
- [ ] Each must-have dashboard's data source is confirmed flowing (or explicitly deferred)
- [ ] A child PRD issue exists for the chosen dashboards
- [ ] ROADMAP updated

---

### Slice 8 — Scale-out: per-attendee accounts, credential store & distribution

**End-state goal:** A workable mechanism to provision 60-70 per-attendee Datadog trial orgs, store
their sensitive credentials as a source of truth the build service reads and Whitney shares with
Michael, surface each attendee's credentials during the workshop, and land each org's keys as
Kubernetes secrets in that attendee's cluster.

Confirmed model: **per-attendee trial orgs**. `PROJECT_STATE.md`'s "one shared org" line is
stale/superseded — corrected as part of this slice.

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

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- All prior slice child PRDs + Decision Logs — **gate this slice** (scale-out multiplies the single-account MVP across attendees)
- `research/24-…` (§3 secret injection), `research/25-eks-quotas-shared-vpc-topology-2026.md`, `research/26-aiewf-2026-logistics-2026.md`, `research/27-conference-demo-resilience-2026.md`
- Codebase: `gitops/apps/` (ESO config and existing secret patterns), `docs/BUILD-SPEC.md` (attendee experience), `PROJECT_STATE.md` (stale shared-org line to correct)

**Step 1 — Problem (write 3-5 sentences):** What is unresolved about provisioning and distributing
per-attendee Datadog access at workshop scale, and what is the blast radius if it fails on the day?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Provisioning (NET-NEW RESEARCH REQUIRED)** — how do 60-70 trial orgs get created? No doc addresses this; riskiest unsupported scope. Run a net-new `/research` spike before presenting options (Manual, Datadog API, Terraform, other).
2. **Master credential store** — where the full pool (the JSON above, ×60-70) lives as source of truth, such that (a) the build service can read it to inject per-cluster and (b) Whitney can share it with Michael. Holds API keys, app keys, passwords — never committed. Candidate: AWS Secrets Manager (same source ESO reads in decision 5), one secret for the pool or one per attendee keyed by `userId`; share with Michael via IAM grant. Resolve store + access-control + sharing.
3. **Surfacing credentials** — how attendees receive access, and what's in each bundle (org URL, API key, app key?, password, kubeconfig, chat-UI token). `research/27` §1.9 settles "pre-generate bundles + claim mechanism" but leaves mechanism/contents open.
4. **Are app keys (`datadogAppKey`) needed at all?** — only for dashboard/monitor API automation, not ingest (`research/24` §3.2).
5. **Keys into the cluster** — `research/24` §3.3 Option A: `datadog-secret` in `monitoring`, `security`, and (if Agent enabled) `datadog` namespaces via one ESO `ExternalSecret` per namespace from the master store. Confirm/revise. (Independent per-student clusters, no hub — `research/25`.)
6. **Rotation/expiry** — schema carries `expiration`; no doc addresses the rotation flow.

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted. Correct `PROJECT_STATE.md`'s stale "one shared org" line to per-attendee orgs as part of this slice.
2. Run `/prd-create` for a child PRD per decisions 1-6 (`/prd-update-decisions`).
3. Add to `docs/ROADMAP.md` as `- Attendee accounts & credentials (PRD #[issue-id])`, last in build order.
4. Run `/prd-update-progress` to commit + push.
5. Final slice — when its child PRD exists, mark this meta-PRD complete and run `/prd-done` for issue #7.

**Done when:**
- [ ] Decisions 1-6 recorded with reasoning
- [ ] A net-new research spike for org provisioning (decision 1) exists in `research/`
- [ ] A child PRD issue exists for provisioning + credential store + distribution + injection
- [ ] ROADMAP updated
- [ ] All 8 slices complete → this meta-PRD closed

---

## Acceptance Criteria (this meta-PRD)

- [ ] 8 child PRDs exist (Slices 1-8), each issue-backed and labeled "PRD"
- [ ] `research/28-…` per-component synthesis exists (produced in Slice 5)
- [ ] `docs/observability-priorities.md` reflects the final must-have/nice-to-have list
- [ ] `docs/ROADMAP.md` lists all child PRDs in build order, each as `- [desc] (PRD #[issue-id])`
- [ ] `PROGRESS.md` updated to reflect meta-PRD creation and completion

## Decision Log

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-06-22 | Architecture: Path 2 hybrid | OTel Collector for OTLP, Datadog Agent DaemonSet for EKS infra; see observability-architecture-paths.md |
| 2026-06-22 | TypeScript rewrite not happening | All Python apps stay Python; spiny-orb off the table; AI-layer instrumentation uses Python OTel SDK / built-in kagent+agentgateway OTel |
| 2026-06-22 | Decisions documented in PRDs, not separate planning docs | `/prd-create` + `/prd-update-decisions` capture decisions in each child PRD's Decision Log; a parallel `docs/planning/` would drift |
| 2026-06-22 | Accounts/credentials/secrets consolidated into one slice (Slice 8) | Tightly coupled; splitting would repeat the same design conversations |
| 2026-06-22 | `/prd-update-progress` pushes after committing | Michael needs visibility into planning progress |
| 2026-06-22 | Attendee Datadog model: per-attendee trial orgs (confirmed) | Whitney confirmed per-attendee over shared org; `PROJECT_STATE.md`'s "one shared org" line is stale, corrected in Slice 8. Org provisioning has no research backing — Slice 8 needs a net-new spike |
| 2026-06-22 | Cost-counter key live-resolved to `kagent_usage_metadata` | Live validation (kagent 0.9.9) showed `research/14` was wrong; `record_usage()` already accepts both, kagent-first. MVP verifies, does not "fix a bug" |
| 2026-06-22 | DDOT-vs-contrib not a blank slate | `research/24` §1.1 confirmed: standalone contrib `0.158.2` as fleet collector, DDOT optional on instructor cluster only |
| 2026-06-22 | Master credential store is a distinct Slice 8 decision | Storing the sensitive trial-org pool (API/app keys + passwords) as a source of truth the build service reads and Whitney shares with Michael is separate from per-cluster ESO injection; org schema embedded for the implementer |
| 2026-06-22 | Restructured from horizontal layers to MVP-first vertical slices | Michael's build system builds each child PRD as it is written; vertical slices are verifiable in the Datadog UI per slice, and design order = build order. Cross-cutting decisions (collector shape, UST vocabulary, account model, Weaver) locked in Slice 1 to bound rework |
| 2026-06-22 | Weaver schema decision moved to Slice 1 (MVP) | Encoding GenAI semconv for CI `live-check` is cross-cutting; if worthwhile, the registry must exist from the first traces so later slices validate against it |
| 2026-06-22 | Per-component synthesis (`research/28`) feeds the infra/integration slice rather than standing alone | A survey alone implements nothing; in the vertical structure it is produced inside Slice 5 and consumed in the same slice, so its findings directly drive wire/skip decisions instead of becoming a research dead-end |
| 2026-06-22 | Meta-PRD content was reconciled from research 14/18/23/24/25/27 + PROJECT_STATE via a read-only audit | Provenance: a reconciliation agent surfaced settled decisions and unrepresented open questions from prior docs; they were folded into the slices. A second audit agent verified the horizontal→vertical restructure dropped no substantive item |
| 2026-06-22 | `PROJECT_STATE.md` stale "one shared org" line corrected in Slice 8, not now | The shared-org→per-attendee correction lands when the work lands, so the state doc changes alongside implementation rather than ahead of it |
