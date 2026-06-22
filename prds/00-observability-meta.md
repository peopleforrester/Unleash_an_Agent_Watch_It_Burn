# Observability PRD Suite — Meta-PRD

**Status:** In Progress  
**Owner:** Whitney  
**Last updated:** 2026-06-22

---

## Problem Statement

The Watch It Burn workshop needs a full observability stack wired into Datadog before the event.
The architecture decision is settled (Path 2 hybrid: OTel Collector for OTLP + Datadog Agent DaemonSet
for EKS infra). What remains is translating that decision into 8 executable PRDs, each covering a
distinct area of the observability strategy. Each PRD requires design conversations with Whitney
before it can be written — the implementation decisions within each area have not yet been made.

## Goal

Produce 8 child PRDs in dependency order, each grounded in explicit design decisions made with
Whitney. This meta-PRD is complete when all 8 child PRDs exist, are ordered correctly in
`docs/ROADMAP.md`, and are ready for implementation.

## Background Reading

These documents provide the settled strategic context. Read them before any milestone:

- `docs/BUILD-SPEC.md` — demo beats, user experience, and attendee journey
- `docs/BUILD-PLAN.md` — current build state and priorities
- `PROJECT_STATE.md` — current implementation status
- `docs/DESIGN-DECISIONS.md` — previously settled decisions
- `docs/transcripts/observability-planning.md` — planning session notes and confirmed facts
- `docs/transcripts/observability-architecture-paths.md` — Path 1/2/3 comparison; Path 2 chosen

**Key settled decisions** (do not re-litigate these):
- Architecture: Path 2 hybrid — OTel Collector for OTLP + Datadog Agent DaemonSet for EKS infra
- TypeScript rewrite of guard-proxy: NOT happening. All Python apps stay Python.
- `spanmetricsconnector` with `add_resource_attributes: true` is already wired
- Falcosidekick → Datadog native output is already wired
- UST tags via `OTEL_RESOURCE_ATTRIBUTES` are already set on guard-proxy, agentgateway, kagent

---

## Living Context Document: `docs/observability-priorities.md`

This file tracks must-have vs. nice-to-have observability for the workshop. It is created during
Milestone 1 and updated at the end of every subsequent milestone if design conversations shifted
any priorities.

**Read this file at the start of every milestone after milestone 1.**

Whitney's known must-haves going in:
- Service map view in Datadog (requires UST done correctly across all workloads)
- LLM call waterfall visible in APM traces
- Tool call visibility (rogue MCP tool chain as trace waterfall — Beat 3)
- Cost counter accumulating in real time
- Before/after sanitization visible in traces (re-leak trap beat)
- Falco runtime alerts surfacing in Datadog when exfil is attempted

---

## Milestone Template

Every milestone follows this sequence. Do NOT skip steps or reorder them.

### Step 0: Establish context

1. Read the background documents listed above under "Background Reading."
2. Read `docs/observability-priorities.md` (skip only if you are working on Milestone 1 and the file does not yet exist).
3. Read the milestone-specific files listed under the milestone's "Step 0 additions."
4. Read the planning docs and PRDs from all prior milestones.
5. Read the codebase files listed under the milestone's "Relevant codebase files." Read only those files — do NOT read the entire codebase.

### Step 1: Understand the problem

Write 3–5 sentences answering: What observability gap does this PRD close? Which workshop beats does it serve? What breaks if this PRD is skipped?

Do NOT proceed to Step 2 if you cannot articulate a clear answer.

### Step 2: Identify design decisions

List every decision that must be made before the PRD can be written. For each decision:
- State the options
- Note what research (if any) is needed to evaluate the options
- Note whether it depends on a decision from a prior milestone

Do NOT proceed to Step 3 until the list is complete.

### Step 3: Design conversations with Whitney

For each design decision from Step 2:
1. If a research spike is needed first, conduct it and save it to `research/` using the next available number (e.g., `research/28-<topic>-2026.md`). Do NOT present a decision to Whitney until you have the information needed to present real options.
2. Present the decision to Whitney with options and tradeoffs. Present **one decision at a time** — do NOT bundle multiple decisions in one message.
3. Wait for Whitney's response before moving to the next decision.
4. Record the decision and the reasoning in `docs/planning/<milestone-slug>.md`. Create this file if it doesn't exist.

Do NOT create the child PRD until all design decisions are settled.

### Step 4: Create the PRD and update tracking

Run these in order — do NOT skip any step:
1. Create `docs/observability-priorities.md` if it doesn't exist, or update it if any design decisions changed the must-have/nice-to-have list.
2. Invoke `/prd-create` to create the child PRD in `prds/`. Name the file using the slug from the milestone (e.g., `prds/01-per-component-telemetry-survey.md`). Name the companion planning doc `docs/planning/<slug>.md` using the same slug.
3. Run `/prd-update-progress` to commit the planning doc, updated priorities doc, and child PRD together, then push. This is the commit step — do NOT commit or push manually.
4. Add the new PRD to `docs/ROADMAP.md` in the correct implementation order. Think carefully about which PRDs it depends on and which will depend on it.
5. Run `/prd-update-progress` again to commit the ROADMAP change and record progress on this meta-PRD, then push.
6. Clear context and run `/prd-next` to begin the next milestone.

---

## Milestone Slugs and File Naming

Use these slugs consistently for child PRD files, planning docs, and ROADMAP entries:

| # | Slug | Child PRD file | Planning doc |
|---|------|---------------|--------------|
| 1 | `per-component-telemetry-survey` | `prds/01-per-component-telemetry-survey.md` | `docs/planning/per-component-telemetry-survey.md` |
| 2 | `otel-collector-config` | `prds/02-otel-collector-config.md` | `docs/planning/otel-collector-config.md` |
| 3 | `datadog-deployment` | `prds/03-datadog-deployment.md` | `docs/planning/datadog-deployment.md` |
| 4 | `ust-strategy` | `prds/04-ust-strategy.md` | `docs/planning/ust-strategy.md` |
| 5 | `log-metric-trace-correlation` | `prds/05-log-metric-trace-correlation.md` | `docs/planning/log-metric-trace-correlation.md` |
| 6 | `genai-semconv-llm-observability` | `prds/06-genai-semconv-llm-observability.md` | `docs/planning/genai-semconv-llm-observability.md` |
| 7 | `custom-dashboards` | `prds/07-custom-dashboards.md` | `docs/planning/custom-dashboards.md` |
| 8 | `attendee-accounts` | `prds/08-attendee-accounts.md` | `docs/planning/attendee-accounts.md` |

**Research spike numbering:** The highest existing research spike is `research/27-*`. New spikes created during any milestone should be numbered starting from 28 (e.g., `research/28-<topic>-2026.md`). Increment sequentially.

---

## Milestones

### Milestone 1: Per-component telemetry survey PRD

**What this PRD covers:** For each platform component in the IDP — ArgoCD, Kyverno, Falco,
KubeArmor, Istio ambient, ESO, cert-manager, Backstage, kagent, agentgateway, guard-proxy,
evil-mcp-shim — document: what telemetry it natively emits, whether a Datadog named integration
exists and what it provides, whether it has an OOTB Datadog dashboard, how UST applies to it,
and any technology-specific gotchas. Much of this has already been researched; the PRD synthesizes
it into actionable decisions per component.

**Step 0 additions — research to read:**
- `research/05-otel-genai-observability.md`
- `research/06-cncf-stack.md`
- `research/18-datadog-integrations-stack-2026.md`
- `research/23-observability-decision-points-2026.md`
- `research/24-datadog-hybrid-impl-sizing-2026.md`

**Step 0 additions — relevant codebase files:**
- `gitops/apps/` — all YAML files (understand what components are deployed and their versions)
- `gitops/ai-layer/resources.yaml` — AI layer component configs and OTEL_RESOURCE_ATTRIBUTES
- `agent/gateway/agentgateway.yaml` — agentgateway config
- `agent/gateway/guard-proxy/guard-proxy.yaml` — guard-proxy config
- `beats/` — all beat directories (understand what each beat uses and what telemetry it requires)

**First action in Step 4:** Before invoking `/prd-create`, create `docs/observability-priorities.md`
and populate it with the must-have vs. nice-to-have list as clarified by the design conversations
in this milestone.

**Acceptance criteria for the child PRD:**
- [ ] Every IDP component has an entry covering: what it natively emits, Datadog integration status, OOTB dashboard availability, UST applicability, gotchas
- [ ] "Skip" decisions are documented with reasoning (not just omitted)
- [ ] The per-component table from `research/18` is updated to reflect any changes since it was written
- [ ] `docs/observability-priorities.md` exists and is populated

---

### Milestone 2: OTel Collector config and telemetry collection strategy PRD

**What this PRD covers:** The authoritative spec for the OTel Collector pipeline. What receivers,
processors, connectors, and exporters are configured and why. Covers: DDOT vs. otelcol-contrib
decision, `spanmetrics` connector, `datadog` connector (required for Trace Metrics since
otelcol-contrib v0.95.0), resource processors, and the `datadog.prometheusScrape.enabled`
coexistence rule. Also covers whether Prometheus scraping belongs in the Collector or the Datadog
Agent for each component category.

**Step 0 additions — research to read:**
- `research/18-datadog-integrations-stack-2026.md`
- `research/19-datadog-otel-ust-correlation-2026.md`
- `research/23-observability-decision-points-2026.md`
- `research/24-datadog-hybrid-impl-sizing-2026.md`
- `docs/planning/per-component-telemetry-survey.md` (from Milestone 1)
- `prds/<per-component-telemetry-survey>.md` (from Milestone 1)

**Step 0 additions — relevant codebase files:**
- `gitops/apps/otel-collector.yaml` — the current Collector config (read in full)

**Key design decisions to surface in Step 2** (do not skip these):
- DDOT (Agent-embedded Collector, requires Agent v7.65+) vs. otelcol-contrib as a separate
  DaemonSet — the paths doc says "evaluate at build time"; this milestone resolves it
- Whether `datadog/connector` needs to be added (required for Trace Metrics since v0.95.0)
- `datadog.prometheusScrape.enabled`: confirm it stays off; document why (double metrics + billing)
- Which components send OTLP to the Collector vs. being scraped by the Agent

---

### Milestone 3: Datadog deployment and configuration PRD

**What this PRD covers:** Deploying the Datadog Agent DaemonSet (or DDOT per Milestone 2 decision),
enabling named integrations per the component survey, and verifying each integration appears
correctly in the Datadog UI. Covers: Helm values, pod annotations, `datadog-secret` management
per cluster, which integrations to wire vs. skip, and what "working" looks like in the UI for
each integration.

**Step 0 additions — research to read:**
- `research/18-datadog-integrations-stack-2026.md`
- `research/23-observability-decision-points-2026.md`
- `research/24-datadog-hybrid-impl-sizing-2026.md`
- `docs/planning/per-component-telemetry-survey.md`
- `docs/planning/otel-collector-config.md`
- `prds/<per-component-telemetry-survey>.md`
- `prds/<otel-collector-config>.md`

**Step 0 additions — relevant codebase files:**
- `gitops/apps/` — existing component manifests (check for any existing Datadog Agent config)

**Key design decisions to surface in Step 2:**
- DDOT vs. two DaemonSets (carry forward the Milestone 2 decision if not already resolved there)
- For each named integration identified in Milestone 1: wire it or skip it? One at a time with Whitney.
- UI verification checklist: what does "working" look like for each integration in the Datadog UI?
- Hostname alignment between Agent and Collector: both must use `k8s.node.name`

---

### Milestone 4: UST strategy and implementation PRD

**What this PRD covers:** The complete Unified Service Tagging vocabulary across all workloads.
How `OTEL_RESOURCE_ATTRIBUTES` is set per component. How the Datadog Agent and OTel Exporter
carry the same tags so Datadog correlates them. Whether the Weaver schema should encode the UST
vocabulary now (before app-level traces are wired) for CI validation. Includes the service map
view as a first-class requirement.

**Step 0 additions — research to read:**
- `research/19-datadog-otel-ust-correlation-2026.md`
- `research/23-observability-decision-points-2026.md` (Decision 5)
- `docs/planning/per-component-telemetry-survey.md`
- `docs/planning/otel-collector-config.md`
- `docs/planning/datadog-deployment.md`
- All prior PRDs

**Step 0 additions — relevant codebase files:**
- `gitops/ai-layer/resources.yaml` — current OTEL_RESOURCE_ATTRIBUTES settings
- `agent/gateway/agentgateway.yaml`
- `agent/gateway/guard-proxy/guard-proxy.yaml`
- `gitops/apps/` — all workload manifests (check which have UST labels set vs. missing)

**Key design decisions to surface in Step 2:**
- `service.version` value: cluster tier string (`cluster-1/2/3`) vs. model name (`haiku/sonnet/opus`)
  — affects how model-tier cost comparison panels work; one decision, not the same thing
- Whether to encode UST vocabulary in a Weaver schema now (before app-level traces) for CI validation
- `deployment.environment.name` Agent version requirement (≥7.58.0 or Datadog Exporter ≥v0.110.0) — confirm met
- Complete tag inventory: which workloads currently have UST labels, which are missing

---

### Milestone 5: Log, metric, and trace correlation PRD

**What this PRD covers:** How logs, metrics, and traces correlate in the Datadog UI — specifically
the "View related logs" pivot from a trace, and the "View Trace in APM" pivot from logs. Whether
UST tags alone provide correlation, or whether explicit `trace_id`/`span_id` injection in log JSON
is also required for Python apps. A research spike is likely needed to verify end-to-end on
OTLP-only (no Agent for traces).

**Step 0 additions — research to read:**
- `research/19-datadog-otel-ust-correlation-2026.md`
- `docs/planning/ust.md` (from Milestone 4)
- All prior PRDs

**Step 0 additions — relevant codebase files:**
- `agent/gateway/guard-proxy/` — full directory (Python app producing logs; understand current log output format)
- `gitops/apps/otel-collector.yaml`

**Key design decisions to surface in Step 2:**
- Do UST tags alone provide "View related logs" in Datadog, or does `trace_id`/`span_id` also
  need to appear in log JSON for Python apps? (May need a live-cluster research spike to confirm)
- OTLP pipeline vs. file/stdout scraping: which path are Python app logs on? This determines
  whether the Agent auto-injects trace context or whether logs need explicit fields
- If `trace_id`/`span_id` injection is needed in guard-proxy logs: how? (Python OTel SDK log bridge
  vs. manual extraction from active span context)

---

### Milestone 6: GenAI semconv and LLM Observability PRD

**What this PRD covers:** Capturing `gen_ai.*` spans correctly from the AI layer — prompts and
responses to/from agents and tools, before/after sanitization at the guard-proxy level, tool call
visibility as a trace waterfall (Beat 3), and cost counter accuracy. Whether Datadog's LLM
Observability product surfaces from pure OTel `gen_ai.*` spans. The `adk_usage_metadata` vs.
`kagent_usage_metadata` bug fix (cost counter currently reports zero tokens silently).

Note: Manual Python OTel SDK instrumentation of guard-proxy is likely required here — the
TypeScript rewrite is not happening, so spiny-orb cannot be used.

**Step 0 additions — research to read:**
- `research/05-otel-genai-observability.md`
- `research/12-mechanism-verification-2026.md`
- `research/14-verify-at-build-sweep-2026.md`
- `research/19-datadog-otel-ust-correlation-2026.md`
- `research/23-observability-decision-points-2026.md`
- `docs/transcripts/observability-planning.md`
- All prior PRDs and planning docs

**Step 0 additions — relevant codebase files:**
- `agent/gateway/guard-proxy/` — full directory: sanitization logic, `record_usage()`, cost counter, current span output
- `agent/gateway/agentgateway.yaml`
- `gitops/ai-layer/resources.yaml`
- `beats/` — all beat directories (understand what telemetry each beat requires to tell its story)

**Key design decisions to surface in Step 2:**
- Does Datadog's LLM Observability product surface from pure OTel `gen_ai.*` spans, or does it
  require dd-trace? (Research spike required before presenting this decision to Whitney)
- `adk_usage_metadata` vs. `kagent_usage_metadata`: which key does the live kagent ADK agent
  actually use? (Needs live-cluster verification — may be a pre-PRD spike)
- `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`: where is this set, what are the
  security/privacy implications for the workshop?
- Python OTel SDK instrumentation plan for guard-proxy: which spans to emit manually vs. relying
  on kagent/agentgateway built-in OTel output?
- agentgateway v1.3.0 field path verification: the repo has v1.2.1 pins; docs may have changed
  — verify before finalizing the PRD

---

### Milestone 7: Custom dashboards PRD

**What this PRD covers:** Whether to build custom dashboards, which ones to build, what data source
each requires, and what workshop story each tells. Candidate dashboards: Wasted Tokens Over Time,
Model Tier Cost Race, Tool Call Heatmap, KubeArmor Enforcement, Guardrail Toggle Timeline.
Also covers whether dashboard JSON is committed to the repo as code.

**Step 0 additions — research to read:**
- `research/24-datadog-hybrid-impl-sizing-2026.md`
- `docs/transcripts/observability-architecture-paths.md` (Path 3 section — candidate dashboard list)
- All prior PRDs and planning docs

**Step 0 additions — relevant codebase files:**
- `agent/gateway/guard-proxy/` — to confirm metric names: `witb_cost_usd`, `witb_tokens_total`, `witb_requests_total`
- `beats/` — understand the demo flow each dashboard would support

**Key design decisions to surface in Step 2:**
- Which dashboards are must-have vs. nice-to-have? (One per dashboard, with Whitney)
- For each must-have dashboard: is the required data confirmed flowing before we commit to building it?
- Dashboard JSON as code (committed to repo) vs. UI-built (not version-controlled)?

---

### Milestone 8: Attendee accounts, credentials, and K8s secrets PRD

**What this PRD covers:** Provisioning 60–70 per-attendee Datadog trial orgs, surfacing API keys
and app keys to attendees during the workshop, storing keys as Kubernetes secrets per cluster, and
the ESO or alternative mechanism for secret distribution. Attendee account provisioning is still
an open design question as of 2026-06-22.

**Step 0 additions — research to read:**
- `research/25-eks-quotas-shared-vpc-topology-2026.md`
- `research/26-aiewf-2026-logistics-2026.md`
- `research/27-conference-demo-resilience-2026.md`
- All prior PRDs and planning docs

**Step 0 additions — relevant codebase files:**
- `gitops/apps/` — ESO config and existing secret management patterns
- `docs/BUILD-SPEC.md` — attendee experience section

**Key design decisions to surface in Step 2:**
- How do 60–70 Datadog trial orgs get provisioned? (Manual, Datadog API, Terraform, other?)
- How are API and app keys surfaced to attendees during the workshop? (Printed card, QR code, projected, other?)
- How do per-attendee keys reach their cluster's Kubernetes secrets? (ESO, init container, CI pipeline, other?)
- Credential rotation and expiry strategy for trial accounts

---

## Acceptance Criteria

- [ ] All 8 child PRDs exist in `prds/`
- [ ] Each child PRD has a companion planning doc in `docs/planning/`
- [ ] `docs/observability-priorities.md` reflects the final must-have/nice-to-have list
- [ ] `docs/ROADMAP.md` lists all 8 child PRDs in implementation order
- [ ] `PROGRESS.md` updated to reflect meta-PRD creation

## Decision Log

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-06-22 | Architecture: Path 2 hybrid | OTel Collector for OTLP, Datadog Agent DaemonSet for EKS infra; see observability-architecture-paths.md |
| 2026-06-22 | TypeScript rewrite not happening | All Python apps stay Python; spiny-orb off the table |
| 2026-06-22 | 8 child PRDs in dependency order | Per-component survey → Collector → Datadog deploy → UST → Correlation → GenAI → Dashboards → Accounts |
| 2026-06-22 | Accounts/credentials/secrets consolidated into one PRD | Distributing trial accounts, surfacing usernames/passwords to users, and storing API+app keys as K8s secrets are tightly coupled — splitting them would require the same design conversations twice |
| 2026-06-22 | UST and log/metric/trace correlation kept as separate PRDs | UST is the mechanism; correlation is the verification. Keeping them separate forces explicit confirmation that correlation actually works end-to-end, which likely needs a live-cluster research spike |
| 2026-06-22 | /prd-update-progress includes push after each commit | Michael needs visibility into planning progress; push keeps the remote current |
