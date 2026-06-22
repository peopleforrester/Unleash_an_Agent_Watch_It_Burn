# PRD #7 — Observability Suite (Meta-PRD)

**GitHub Issue:** [#7](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7)
**Status:** In Progress
**Priority:** High
**Last updated:** 2026-06-22

---

## How To Use This Meta-PRD (read first)

This is a **meta-PRD**: its milestones do not implement observability directly. Each milestone
either produces a **research synthesis** or creates a **child PRD** (via `/prd-create`) that
implements one area of the observability strategy. This meta-PRD is complete when every child
PRD exists and is ordered in `docs/ROADMAP.md`. The child PRDs are then implemented through their
own `/prd-start` → `/prd-done` lifecycles.

**Each milestone is executed by a fresh AI instance with no memory of prior milestones.** Every
milestone therefore lists exactly what to read in its Step 0. Do not assume context carries over.
If a milestone's instruction is unclear without conversation history, that is a bug in this
document — fix it, do not guess.

**Milestone order ≠ implementation order.** Milestones below are ordered by the sequence in which
we hold the design conversations and create the PRDs (dependency-informed). `docs/ROADMAP.md`
holds the *implementation* order, which can differ — e.g. UST is planned early but cannot be
*validated* until telemetry collection exists, so it implements after the Collector and Datadog
deployment PRDs.

**Decisions are documented in the PRDs themselves.** There are no separate `docs/planning/` files.
Record every design decision in the relevant child PRD's Decision Log via `/prd-update-decisions`.
Record meta-level decisions in this file's Decision Log.

**Branch model.** This meta-PRD is worked via `/prd-start 7`, which creates one working branch. Every
milestone commits to that same branch — `/prd-update-progress` commits and pushes it (this is how
Michael sees progress). Do NOT commit to main and do NOT open a branch per milestone. `/prd-done`
opens the single PR when all milestones are complete. (Child PRDs that touch real config/code get
their own working branch via their own `/prd-start` when they are later implemented — separate from
this meta-PRD's branch.)

---

## Repository Conventions (the implementing AI MUST follow these)

Before creating any file, read sibling files in the target directory and match their structure,
naming, and style. Specifically:

- **Research spikes:** `research/NN-topic-2026.md`, where `NN` continues the existing sequence.
  The highest existing spike is `research/27-*`; the next new spike is `research/28-…`. Increment
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

Settled strategic context — read before any milestone:

- `docs/BUILD-SPEC.md` — demo beats, attendee journey, the user experience the workshop sells
- `docs/BUILD-PLAN.md` — current build state and priorities
- `PROJECT_STATE.md` — current implementation status
- `docs/DESIGN-DECISIONS.md` — previously settled decisions
- `docs/transcripts/observability-planning.md` — planning session notes and confirmed facts
- `docs/transcripts/observability-architecture-paths.md` — Path 1/2/3 comparison; **Path 2 chosen**
- `docs/observability-priorities.md` — living must-have vs. nice-to-have list (created in Milestone 1)

**Settled decisions — do NOT re-litigate:**
- **Architecture: Path 2 hybrid** — OTel Collector for OTLP/GenAI + Datadog Agent DaemonSet for EKS infra. The deployment shape is settled in `research/24` §1.1: standalone otelcol-contrib Collector + standalone Datadog Agent DaemonSet for infra only; do NOT make DDOT the fleet collector (DDOT optional on the instructor cluster only).
- **TypeScript rewrite of guard-proxy is NOT happening.** All Python apps stay Python. spiny-orb is off the table. AI-layer instrumentation uses the Python OTel SDK directly, or kagent/agentgateway built-in OTel output.
- **Already wired:** `spanmetricsconnector` with `add_resource_attributes: true`; UST tags via `OTEL_RESOURCE_ATTRIBUTES` on guard-proxy/agentgateway/kagent; `cluster.name=watch-it-burn` upserted by the Collector `resource` processor; OTel Collector pinned at contrib `0.158.2`.
- **Falcosidekick → Datadog:** wired in commit `6c6a81d`, but `research/23` (which predates the commit) observed Falcosidekick forwarding only to Talon. Treat as a **verify-at-build item in Milestone 3**, not a confirmed-working fact.
- **Cost-counter key (live-resolved):** `PROJECT_STATE.md` live validation (kagent 0.9.9) found the key is `result.metadata.kagent_usage_metadata`, NOT `adk_usage_metadata` — `research/14` was wrong. `record_usage()` now accepts both, kagent-first. Milestone 6 verifies this still holds; it is not an open bug.
- **Attendee Datadog model:** **per-attendee trial orgs** (confirmed 2026-06-22). `PROJECT_STATE.md`'s "one shared org" line is **stale/superseded** — see Milestone 8.
- **Division of labor:** Whitney owns Datadog accounts/keys/Agent install/dashboards. Michael owns OTel-side wiring + manifest annotations + `datadog-secret` consumption.

---

## Living Document: `docs/observability-priorities.md`

Created in Milestone 1, updated at the end of every later milestone if design conversations shifted
priorities. **Read it in Step 0 of every milestone after Milestone 1.**

Known must-haves going in:
- **Service Map renders in the Datadog UI** (`guard-proxy → agentgateway → kagent → Bedrock`, each node health-indicated) — requires UST done correctly
- LLM call waterfall visible in APM traces
- Rogue MCP tool-call chain visible as a trace waterfall (Beat 3)
- Cost counter accumulating in real time
- Before/after sanitization visible in traces (re-leak trap beat)
- Falco runtime alerts surfacing in Datadog when exfil is attempted

---

## Milestones

> Every milestone below is self-contained: it lists its own reads, problem framing, decisions, and
> production steps. Do not look to a shared template — follow the steps written in your milestone.
>
> **Scope guard (applies to every milestone): do NOT implement the observability change itself in a
> meta-PRD milestone.** Your only deliverable is the research synthesis (Milestone 1) or the child
> PRD (Milestones 2-8). Do not edit `otel-collector.yaml`, manifests, app code, or Datadog config
> here — that work belongs to the child PRD's own `/prd-start` → `/prd-done` lifecycle. If you find
> yourself editing implementation files, stop: you have left this milestone's scope.

---

### Milestone 1 — Per-component telemetry synthesis (research spike, not a child PRD)

**Deliverable:** `research/28-per-component-telemetry-synthesis-2026.md` — one actionable per-component
table consolidating existing research, plus a gap list of items needing live-cluster verification.
This is a **research synthesis**, not an implementable PRD: a survey alone implements nothing. Its
value is that Milestones 2 (Collector) and 3 (Datadog deployment) consume it directly — those PRDs
do the wiring. This milestone is done only when its output is positioned to feed them.

**Step 0 — Read:**
- This meta-PRD's top matter (conventions, settled decisions, background reading)
- `research/05-otel-genai-observability.md`, `research/06-cncf-stack.md`, `research/18-datadog-integrations-stack-2026.md`, `research/23-observability-decision-points-2026.md`, `research/24-datadog-hybrid-impl-sizing-2026.md`
- Codebase: every YAML in `gitops/apps/`, `gitops/ai-layer/resources.yaml`, `agent/gateway/agentgateway.yaml`, `agent/gateway/guard-proxy/guard-proxy.yaml`, and every directory in `beats/` (to learn what telemetry each beat's story requires)

**Step 1 — Problem (write 3-5 sentences):** Why does the team need one consolidated per-component
table before writing the Collector and Datadog PRDs? What goes wrong if those PRDs are written
without it?

**Step 2 — Resolve with Whitney (one decision at a time; do not bundle):**
For each IDP component — ArgoCD, Kyverno, Falco, KubeArmor, Istio ambient, ESO, cert-manager,
Backstage, kagent, agentgateway, guard-proxy, evil-mcp-shim, customer-stream generator — confirm:
what it natively emits, whether a Datadog named integration exists and what it provides, whether it
has an OOTB dashboard, how UST applies, and any gotcha. Then decide **per component: capture it or
skip it for the workshop**, with reasoning. Run `/research <specific question>` for any component
whose current emission/integration status is unverified — include the full `/research` output, do
not summarize it.

**Step 3 — Produce the deliverable:**
1. Write `research/28-per-component-telemetry-synthesis-2026.md` with the per-component table, the capture/skip decisions, and the live-verification gap list.
2. Create `docs/observability-priorities.md` and populate the must-have/nice-to-have list (seed from the "Known must-haves" above, adjusted by this conversation).
3. Run `/prd-update-progress` to commit this milestone's output and push (so Michael sees it).
4. Clear context; run `/prd-next` to pick up Milestone 2.

**Done when:**
- [ ] `research/28-…` exists with an entry per component (emits / DD integration / OOTB dashboard / UST applicability / gotcha / capture-or-skip + reasoning)
- [ ] Skip decisions are documented with reasoning, not omitted
- [ ] A live-verification gap list exists for items that need a real cluster to confirm
- [ ] `docs/observability-priorities.md` exists and lists the Service Map as a must-have
- [ ] Milestones 2 and 3 below reference `research/28-…` in their Step 0 (verify the references are present)

---

### Milestone 2 — OTel Collector config & telemetry collection strategy PRD

**End-state goal:** A single authoritative, committed OTel Collector config whose pipeline is fully
explained — every receiver, processor, connector, and exporter justified — and which is confirmed
to deliver traces and metrics into Datadog from the AI layer.

**Step 0 — Read:**
- This meta-PRD's top matter
- `research/28-per-component-telemetry-synthesis-2026.md` (Milestone 1 output — **must exist; Milestone 1 gates this milestone**)
- `research/18-…`, `research/19-datadog-otel-ust-correlation-2026.md`, `research/23-…`, `research/24-…`
- Codebase: `gitops/apps/otel-collector.yaml` in full

**Step 1 — Problem (write 3-5 sentences):** What is intentional vs. accidental in the current
Collector config? What must the pipeline guarantee for the demo to work?

**Step 2 — Resolve with Whitney (one at a time):**
1. **DDOT vs. otelcol-contrib** — `research/24` §1.1 already made this a CONFIRMED choice: keep the standalone contrib DaemonSet (pinned `0.158.2`) as the fleet collector; do NOT make DDOT the fleet collector; DDOT optional on the instructor cluster only. Confirm this with Whitney rather than re-opening it; only revisit if new info contradicts research/24.
2. **`datadog/connector`** — add it? (Required for Trace Metrics since otelcol-contrib v0.95.0; the Datadog Exporter no longer computes them.)
3. **`datadog.prometheusScrape.enabled`** — confirm it stays **off**; document why (double metrics + double billing).
4. **Prometheus scraping ownership** — for each component category, decide whether the Collector scrapes it or the Datadog Agent does.
Run `/research <specific question>` for any version/behavior not already confirmed in research 18/24.

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` to create a child PRD that implements the Collector config per decisions 1-4. Bake the resolved decisions into the child PRD's milestones and Decision Log (use `/prd-update-decisions`).
3. Add it to `docs/ROADMAP.md` as `- OTel Collector config (PRD #[issue-id])`, placed first in implementation order.
4. Run `/prd-update-progress` to commit + push.
5. Clear context; run `/prd-next` for Milestone 3.

**Done when:**
- [ ] Decisions 1-4 recorded in the child PRD's Decision Log with reasoning
- [ ] A child PRD issue exists whose acceptance includes "traces and metrics confirmed arriving in Datadog from the AI layer"
- [ ] ROADMAP updated with the child PRD as the first implementation step

---

### Milestone 3 — Datadog deployment & configuration PRD

**End-state goal:** The Datadog Agent (or DDOT per Milestone 2) is deployed, the chosen named
integrations are wired, and **each integration is confirmed visible and correct in the Datadog UI** —
not merely configured.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- `research/28-…` (Milestone 1), the Collector child PRD + its Decision Log (Milestone 2) — **both gate this milestone**
- `research/18-…`, `research/23-…`, `research/24-…`
- Codebase: `gitops/apps/` (check for any existing Datadog Agent config)

**Step 1 — Problem (write 3-5 sentences):** Which integrations earn their setup cost for the
workshop story, and what does "working" look like in the UI for each?

**Step 2 — Resolve with Whitney (one at a time):**
1. Carry forward the DDOT vs. two-DaemonSets decision from Milestone 2 (confirm, do not re-open unless new info).
2. For each named integration in `research/28-…`: **wire it or skip it** for the workshop — one component at a time.
3. **UI verification checklist** — define what proves each wired integration works (which dashboard, which metric, which view).
4. **Hostname alignment** — Datadog computes the host as `<k8s.node.name>-<cluster name>`. `cluster.name=watch-it-burn` is already upserted by the Collector; the missing pieces are `k8s.node.name` on host-identifying telemetry and a matching `DD_CLUSTER_NAME` on the Agent (`research/24` §1.2). Confirm both.
5. **Falcosidekick → Datadog (verify-at-build)** — confirm Falcosidekick actually forwards security events to Datadog, not only to Talon. Commit `6c6a81d` wired it but `research/23` observed Talon-only; this can only be confirmed on a live cluster.
6. **Istio ambient: L7 or L4-only?** — accept L4-only ztunnel metrics and narrate it, or deploy a per-namespace waypoint for L7/mesh traces (`research/23` Decision 6, `research/18` Istio rows). One decision.
7. **EKS + CloudWatch cross-account integration scope** — is it in scope at all, and almost certainly NOT per-attendee (`research/24` §1.4)? Decide facilitator-only vs. skip.
8. **Datadog Agent resource footprint** — carry the sizing from `research/24` §2 (node Agent 200m/256Mi, Process Agent 100m/200Mi, Cluster Agent 200m/256Mi; APM + System Probe OFF) into the child PRD.

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` for a child PRD implementing the Agent deploy + integrations + UI verification per decisions 1-8 (`/prd-update-decisions` for the Decision Log).
3. Add to `docs/ROADMAP.md` as `- Datadog deployment & integrations (PRD #[issue-id])`, after the Collector PRD.
4. Run `/prd-update-progress` to commit + push.
5. Clear context; run `/prd-next` for Milestone 4.

**Done when:**
- [ ] Wire/skip decision recorded per integration with reasoning
- [ ] A child PRD issue exists whose acceptance includes a per-integration UI verification checklist
- [ ] ROADMAP updated, placed after the Collector PRD

---

### Milestone 4 — UST strategy & implementation PRD

**End-state goal:** The Datadog **Service Map renders** showing `guard-proxy → agentgateway → kagent
→ Bedrock`, each node health-indicated with one-click pivot to its traces/logs/metrics, and token-cost
panels can be split by model tier. If the Service Map does not draw, this is not done.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- `research/19-datadog-otel-ust-correlation-2026.md`, `research/23-…` (Decision 5)
- The Collector and Datadog-deployment child PRDs + their Decision Logs (Milestones 2-3) — **gate this milestone**
- Codebase: `gitops/ai-layer/resources.yaml`, `agent/gateway/agentgateway.yaml`, `agent/gateway/guard-proxy/guard-proxy.yaml`, and every workload manifest in `gitops/apps/` — to inventory which already carry UST labels and which do not

**Step 1 — Problem (write 3-5 sentences):** What correlation breaks without complete UST? Which
beats depend on the Service Map?

**Step 2 — Resolve with Whitney (one at a time):**
1. **`service.version` semantics** — cluster-tier string (`cluster-1/2/3`) vs. model name (`haiku/sonnet/opus`). Determines whether the model-tier cost-race panel works. NOTE: the corpus already contains BOTH answers — `research/23` picked model-name, while the planning transcript, `research/18`, `research/19`, and `TECH-STATUS.md` say cluster-tier. Resolve the conflict explicitly; do not assume.
2. **Complete tag vocabulary + gap inventory** — the exact `service.name` per component and the list of workloads missing UST labels today.
3. **Same-tag mechanism for correlation** — how the Agent (logs) and OTel Exporter (traces/metrics) are made to carry identical `service`/`env`/`version`.
4. **`peer.service` + span-kind prerequisite** — the pure-OTel Service Map infers edges from `peer.service` and correct span kinds (`research/23` Decision 8). Decide where these are set so the map can draw `guard-proxy → agentgateway → kagent → Bedrock`.
5. **Weaver schema now?** — encode the UST vocabulary in a Weaver registry for CI validation before app-level traces exist, or defer. (`/research` if the CI value is unclear.)
6. **Version prerequisite** — confirm Agent ≥7.58.0 or Datadog Exporter ≥v0.110.0 so `deployment.environment.name` maps to `env`.
   Note: `DD_SERVICE`/`DD_ENV`/`DD_VERSION` env vars do NOT work on the OTel path — UST must flow via `OTEL_RESOURCE_ATTRIBUTES`.
   Open risk to resolve here: whether the full Service Map renders from pure OTLP export without the Agent handling traces (research/19 flags this Medium-confidence/unverified) — this needs a **live-cluster check**, not just `/research`.

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` (Service Map is a must-have).
2. Run `/prd-create` for a child PRD implementing UST per decisions 1-6, acceptance including "Service Map renders in the Datadog UI" (`/prd-update-decisions` for the Decision Log).
3. Add to `docs/ROADMAP.md` as `- UST strategy (PRD #[issue-id])`, placed **after** the Datadog-deployment PRD (UST can only be validated once collection exists).
4. Run `/prd-update-progress` to commit + push.
5. Clear context; run `/prd-next` for Milestone 5.

**Done when:**
- [ ] Decisions 1-5 recorded in the child PRD's Decision Log with reasoning
- [ ] A child PRD issue exists whose acceptance includes the Service Map rendering in the UI
- [ ] ROADMAP updated, placed after the Datadog-deployment PRD

---

### Milestone 5 — Log / metric / trace correlation PRD

**End-state goal:** In the Datadog UI, "View related logs" pivots from a trace and "View Trace in
APM" pivots from a log — confirmed working end-to-end for the Python AI-layer apps.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- `research/19-datadog-otel-ust-correlation-2026.md`
- The UST child PRD + its Decision Log (Milestone 4) — **gates this milestone**
- Codebase: `agent/gateway/guard-proxy/` in full (current log output format), `gitops/apps/otel-collector.yaml`

**Step 1 — Problem (write 3-5 sentences):** Does UST alone deliver correlation, or do Python app
logs need explicit `trace_id`/`span_id` fields? What pivot breaks if they don't?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Is UST sufficient, or is `trace_id`/`span_id` injection in log JSON also required** for the Python apps? (Likely needs a live-cluster `/research` spike — run it before presenting this decision.)
2. **OTLP pipeline vs. file/stdout scraping** — which path are the Python logs on? This determines whether the Agent auto-injects trace context or whether explicit fields are needed.
3. **If injection is needed** — Python OTel SDK log bridge vs. manual extraction from the active span context.

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` for a child PRD implementing correlation per decisions 1-3, acceptance including both UI pivots working (`/prd-update-decisions` for the Decision Log).
3. Add to `docs/ROADMAP.md` as `- Log/metric/trace correlation (PRD #[issue-id])`, after the UST PRD.
4. Run `/prd-update-progress` to commit + push.
5. Clear context; run `/prd-next` for Milestone 6.

**Done when:**
- [ ] Decisions 1-3 recorded in the child PRD's Decision Log with reasoning
- [ ] Any required correlation research spike exists in `research/` (next number in sequence)
- [ ] A child PRD issue exists whose acceptance includes both UI pivots working
- [ ] ROADMAP updated, placed after the UST PRD

---

### Milestone 6 — GenAI semconv & LLM Observability PRD

**End-state goal:** The AI layer emits correct `gen_ai.*` spans so the demo shows: the LLM call
waterfall, the rogue MCP tool-call chain (Beat 3), before/after sanitization (re-leak trap), and an
accurate cost counter. Confirmed visible in Datadog.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- `research/05-otel-genai-observability.md`, `research/12-mechanism-verification-2026.md`, `research/14-verify-at-build-sweep-2026.md`, `research/19-…`, `research/23-…`
- `docs/transcripts/observability-planning.md`
- The Collector child PRD (Milestone 2) — **gates this milestone**
- Codebase: `agent/gateway/guard-proxy/` in full (sanitization logic, `record_usage()`, cost counter, current span output), `agent/gateway/agentgateway.yaml`, `gitops/ai-layer/resources.yaml`, every directory in `beats/`

**Step 1 — Problem (write 3-5 sentences):** Which demo beats depend on `gen_ai.*` telemetry, and
what is missing today?

**Step 2 — Resolve with Whitney (one at a time):**
1. **Does Datadog LLM Observability surface from pure OTel `gen_ai.*` spans, or does it require dd-trace?** No existing spike answers this (`research/05` names it a gap; `research/19` covers correlation, not the LLM Observability product). Run a net-new `/research` spike before presenting this.
2. **Cost-counter key — already live-resolved; verify it still holds.** `PROJECT_STATE.md` live validation (kagent 0.9.9) found the key is `kagent_usage_metadata`, NOT `adk_usage_metadata` (`research/14` was wrong); `record_usage()` already accepts both, kagent-first. This is NOT an open bug — confirm the live key still holds on the workshop cluster and that the fallback remains.
3. **`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`** — where it's set and the security/privacy implications for the workshop (content capture is load-bearing for the re-leak trap, but must be redacted symmetrically — see research/12).
4. **GenAI semconv stability / opt-in.** All `gen_ai.*` semconv is Development status; names churned v1.36→v1.37; `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` must be set deliberately (`research/05`, `research/06`). Decide which semconv version to pin and whether to set the opt-in.
5. **Python OTel SDK instrumentation plan for guard-proxy** — which spans to emit manually vs. relying on kagent/agentgateway built-in OTel output. (No spiny-orb — Python only.)
6. **agentgateway v1.3.0 field-path verification** — the repo has v1.2.1 pins; verify field paths against v1.3.0 before finalizing.
7. **Re-leak-trap trace teardown** — ensure trace data is torn down in teardown so no span store retains even the fake sentinel post-run (`research/05` re-leak control #4).

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` for a child PRD implementing GenAI telemetry per decisions 1-7, acceptance including the four demo views above visible in Datadog and the cost counter reporting non-zero (`/prd-update-decisions` for the Decision Log).
3. Add to `docs/ROADMAP.md` as `- GenAI semconv & LLM Observability (PRD #[issue-id])`.
4. Run `/prd-update-progress` to commit + push.
5. Clear context; run `/prd-next` for Milestone 7.

**Done when:**
- [ ] Decisions 1-7 recorded in the child PRD's Decision Log with reasoning
- [ ] A net-new research spike for decision 1 (Datadog LLM Observability from pure OTel gen_ai.* spans) exists in `research/`
- [ ] A child PRD issue exists whose acceptance includes the four demo views + accurate cost counter
- [ ] ROADMAP updated

---

### Milestone 7 — Custom dashboards PRD

**End-state goal:** The agreed must-have workshop dashboards exist as committed dashboard
definitions, each backed by data confirmed already flowing.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- `research/24-datadog-hybrid-impl-sizing-2026.md`, `docs/transcripts/observability-architecture-paths.md` (Path 3 candidate dashboard list)
- The Collector, Datadog-deployment, UST, and GenAI child PRDs + their Decision Logs — **gate this milestone** (a dashboard cannot be built on data that isn't flowing)
- Codebase: `agent/gateway/guard-proxy/` (confirm metric names `witb_cost_usd`, `witb_tokens_total`, `witb_requests_total`), every directory in `beats/`

**Step 1 — Problem (write 3-5 sentences):** Which dashboards tell the workshop story, and is the
data for each confirmed flowing before we commit to building it?

**Step 2 — Resolve with Whitney (one at a time):**
1. For each candidate (Wasted Tokens Over Time, Model Tier Cost Race, Tool Call Heatmap, KubeArmor Enforcement, Guardrail Toggle Timeline): **must-have or nice-to-have?**
2. For each must-have: **is its data source confirmed flowing?** (If not, defer to the relevant upstream PRD, do not build a dashboard on absent data.)
3. **Dashboard JSON as code (committed)** vs. UI-built (not version-controlled)?

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted.
2. Run `/prd-create` for a child PRD implementing the chosen dashboards per decisions 1-3 (`/prd-update-decisions` for the Decision Log).
3. Add to `docs/ROADMAP.md` as `- Custom dashboards (PRD #[issue-id])`, after the data-source PRDs.
4. Run `/prd-update-progress` to commit + push.
5. Clear context; run `/prd-next` for Milestone 8.

**Done when:**
- [ ] Must-have/nice-to-have decided per dashboard with reasoning
- [ ] Each must-have dashboard's data source is confirmed flowing (or explicitly deferred)
- [ ] A child PRD issue exists for the chosen dashboards
- [ ] ROADMAP updated

---

### Milestone 8 — Attendee accounts, credentials & K8s secrets PRD

**End-state goal:** A workable mechanism to provision 60-70 per-attendee Datadog trial orgs,
surface each attendee's credentials to them during the workshop, and land each org's API + app keys
as Kubernetes secrets in that attendee's cluster.

**Step 0 — Read:**
- This meta-PRD's top matter and `docs/observability-priorities.md`
- `research/25-eks-quotas-shared-vpc-topology-2026.md`, `research/26-aiewf-2026-logistics-2026.md`, `research/27-conference-demo-resilience-2026.md`
- Codebase: `gitops/apps/` (ESO config and existing secret patterns), `docs/BUILD-SPEC.md` (attendee experience section)

Confirmed model: **per-attendee trial orgs** (2026-06-22). `PROJECT_STATE.md`'s "one shared org +
per-cluster-filtered dashboard link" line is **stale/superseded** — do not design around it.

**Step 1 — Problem (write 3-5 sentences):** What is unresolved about provisioning and distributing
per-attendee Datadog access at workshop scale, and what is the blast radius if it fails on the day?

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

**Step 2 — Resolve with Whitney (one at a time):**
1. **Provisioning (NET-NEW RESEARCH REQUIRED)** — how do 60-70 Datadog trial orgs get created? No doc in the repo addresses this; it is the riskiest unsupported scope. Run a net-new `/research` spike before presenting options (Manual, Datadog API, Terraform, other).
2. **Master credential store** — where the full pool of trial-org credentials (the JSON above, ×60-70) lives as the source of truth, such that: (a) the build/provisioning service can read it to inject per-cluster, and (b) Whitney can share it with Michael. It holds API keys, app keys, and passwords — must never be committed. Candidate: AWS Secrets Manager (the same source ESO already reads in decision 5), one secret holding the pool or one per attendee keyed by `userId`; sharing with Michael via IAM grant. Resolve the store + access-control + sharing mechanism.
3. **Surfacing credentials** — how do attendees receive their access during the workshop, and what is in each bundle (org URL, API key, app key?, password, kubeconfig, chat-UI token)? `research/27` §1.9 settles "pre-generate per-attendee bundles + a claim mechanism (code on a card / per-seat URL)" but leaves the mechanism and bundle contents open.
4. **Are app keys (`datadogAppKey`) needed at all?** App keys are only for dashboard/monitor API automation, not ingest (`research/24` §3.2). Decide whether attendees need them or whether API key + site suffices.
5. **Keys into the cluster** — `research/24` §3.3 Option A is the recommended approach: `datadog-secret` in `monitoring`, `security`, and (if Agent enabled) `datadog` namespaces, materialized via one ESO `ExternalSecret` per namespace from the master credential store (decision 2). Confirm or revise. (Topology is independent per-student standalone clusters, no hub — `research/25`.)
6. **Rotation/expiry** — how is trial-account expiry handled? The schema carries `expiration`; no doc addresses the rotation flow.

**Step 3 — Produce the child PRD:**
1. Update `docs/observability-priorities.md` if priorities shifted. Also update `PROJECT_STATE.md` here — its stale "one shared org" line is corrected to per-attendee orgs as part of this milestone's implementation.
2. Run `/prd-create` for a child PRD implementing account provisioning + credential storage + distribution + secret injection per decisions 1-6 (`/prd-update-decisions` for the Decision Log).
3. Add to `docs/ROADMAP.md` as `- Attendee accounts & credentials (PRD #[issue-id])`.
4. Run `/prd-update-progress` to commit + push.
5. This is the final milestone — when its child PRD exists, mark this meta-PRD complete and run `/prd-done` for issue #7.

**Done when:**
- [ ] Decisions 1-6 recorded in the child PRD's Decision Log with reasoning
- [ ] A net-new research spike for org provisioning (decision 1) exists in `research/`
- [ ] A child PRD issue exists for provisioning + distribution + secret storage
- [ ] ROADMAP updated
- [ ] All 8 milestones complete → this meta-PRD closed

---

## Acceptance Criteria (this meta-PRD)

- [ ] `research/28-…` synthesis exists (Milestone 1)
- [ ] 7 child PRDs exist (Milestones 2-8), each issue-backed and labeled "PRD"
- [ ] `docs/observability-priorities.md` reflects the final must-have/nice-to-have list
- [ ] `docs/ROADMAP.md` lists all child PRDs in implementation order, each as `- [desc] (PRD #[issue-id])`
- [ ] `PROGRESS.md` updated to reflect meta-PRD creation and completion

## Decision Log

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-06-22 | Architecture: Path 2 hybrid | OTel Collector for OTLP, Datadog Agent DaemonSet for EKS infra; see observability-architecture-paths.md |
| 2026-06-22 | TypeScript rewrite not happening | All Python apps stay Python; spiny-orb off the table; AI-layer instrumentation uses Python OTel SDK / built-in kagent+agentgateway OTel |
| 2026-06-22 | 8 milestones; Milestone 1 is a research synthesis, not a child PRD | A survey alone implements nothing; its findings feed the Collector + Datadog-deployment PRDs, avoiding a research dead-end |
| 2026-06-22 | Decisions documented in PRDs, not separate planning docs | `/prd-create` + `/prd-update-decisions` capture decisions in each child PRD's Decision Log; a parallel `docs/planning/` would be a second source of truth that drifts |
| 2026-06-22 | Milestone order ≠ ROADMAP order | Milestones are creation/conversation order; ROADMAP is implementation order. UST is planned early but implements after collection exists (Service Map can't be validated sooner) |
| 2026-06-22 | Accounts/credentials/secrets consolidated into one PRD (Milestone 8) | Tightly coupled; splitting would repeat the same design conversations |
| 2026-06-22 | UST and correlation kept as separate PRDs (Milestones 4, 5) | UST is the mechanism; correlation is the verification. Separation forces explicit confirmation that correlation works end-to-end |
| 2026-06-22 | `/prd-update-progress` pushes after committing | Michael needs visibility into planning progress |
| 2026-06-22 | Attendee Datadog model: per-attendee trial orgs (confirmed) | Whitney confirmed per-attendee orgs over shared org; `PROJECT_STATE.md`'s "one shared org" line is stale and must be updated. Org provisioning has no research backing — Milestone 8 needs a net-new spike |
| 2026-06-22 | Cost-counter key live-resolved to `kagent_usage_metadata` | Live validation (kagent 0.9.9) showed `research/14` was wrong; `record_usage()` already accepts both keys, kagent-first. Milestone 6 verifies, does not "fix a bug" |
| 2026-06-22 | DDOT-vs-contrib not a blank slate | `research/24` §1.1 already confirmed: standalone contrib `0.158.2` as fleet collector, DDOT optional on instructor cluster only. Milestone 2 confirms rather than re-decides |
| 2026-06-22 | Reconciliation pass folded research 14/18/23/24/25/27 + PROJECT_STATE findings into milestones | A read-only audit agent reconciled prior docs against this meta-PRD; settled decisions and unrepresented open questions were absorbed into the relevant milestones |
| 2026-06-22 | `PROJECT_STATE.md` stale org line corrected in Milestone 8, not now | The shared-org→per-attendee correction lands when the work lands, so the state doc changes alongside implementation rather than ahead of it |
| 2026-06-22 | Added master-credential-store decision to Milestone 8 | Storing the sensitive trial-org pool (API/app keys + passwords) as a source of truth the build service reads and Whitney shares with Michael is distinct from per-cluster ESO injection; the org schema is embedded for the implementer |
