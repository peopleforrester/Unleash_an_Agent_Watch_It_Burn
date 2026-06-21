<!-- ABOUTME: Observability decision-points alignment doc for the Watch-It-Burn workshop. -->
<!-- ABOUTME: Surfaces open observability/runtime decisions to Whitney + Michael with pros, cons, and recommendations. -->

# 23. Observability Decision Points (Whitney + Michael alignment)

## Verification Method

- **Approach:** Working/alignment doc, dated 2026-06-21. Repo-context facts (OTel Collector
  config, exporters, guard-proxy metrics, kagent/agentgateway versions, Falco/Talon,
  podPidsLimit, model tiers, Istio ambient) were read directly from the live repo at
  `/home/michael/repos/events/Unleash_an_Agent_Watch_It_Burn` and are treated as CONFIRMED
  in-repo. External, load-bearing claims (DDOT recommendation, Datadog Istio ambient
  autodiscovery behavior, the spanmetrics `add_resource_attributes` field, Datadog service map
  from pure OTLP) were verified against primary sources cited inline. Items that need a live
  cluster to confirm are marked UNCERTAIN.
- **Companion spikes referenced:** `research/05-otel-genai-observability.md` (GenAI semconv,
  content-capture re-leak trap), `research/16-typescript-agent-spiny-weaver-2026.md` (spiny-orb
  / TS agent), `research/17-kubearmor-forkbomb-2026.md` (KubeArmor vs fork bomb). The brief
  referenced spikes 18/19/20/21/22 by number; those numbered files do not exist yet. Their
  subject matter (UST/correlation wiring, the spanmetrics connector fix, Falcosidekick ->
  Datadog/OTLP, the KubeArmor/Tetragon runtime decision) is folded into Decisions 3, 5, and 8
  below and should become numbered spikes if deeper work is needed.
- **In-repo facts taken as given:** OTel Collector (contrib `0.158.2`, DaemonSet) at
  `gitops/apps/otel-collector.yaml` with `datadog` exporter primary plus `prometheusremotewrite`
  and `otlp/tempo` fallback, metrics + traces pipelines, a `resource` processor adding
  `cluster.name=watch-it-burn`, and **no `connectors:` block**; guard-proxy `/metrics`
  (`witb_cost_usd`, `witb_tokens_total`, `witb_requests_total`, `tier` label) at
  `agent/gateway/guard-proxy/proxy.py`; kagent Python agent (ADK, A2A) primary;
  agentgateway v1.3.0; Falco 0.44.1 + Talon; podPidsLimit as the fork-bomb block; cost-counter
  parses `adk_usage_metadata`; model tiers Haiku/Sonnet/Opus selected per cluster via
  `MODEL_TIER`. CONFIRMED from files.

## Stated design principle (Datadog-required, Datadog-independent-capable)

For THIS workshop, **Datadog is REQUIRED and primary** for the observability story. It is what
validates the co-presenter (Whitney, a Datadog advocate) and her engagement, so the on-stage
narrative runs on Datadog. Prometheus / Grafana / Tempo are the **fallback**.

At the same time, the architecture must stay **Datadog-independent-capable**: Michael must be
able to run the whole stack later, without any Datadog access, and still have a working
observability story. These two requirements are reconciled by one rule that shapes every
recommendation below:

- **OpenTelemetry is the neutral instrumentation layer.** All app/agent telemetry is emitted as
  OTLP against OTel (GenAI) semantic conventions. No component is instrumented with a
  Datadog-proprietary SDK as its only path.
- **Datadog is the primary EXPORTER sink for this event**, configured alongside the OSS sinks in
  the same Collector. Removing the `datadog` exporter must leave a functioning pipeline.
- **The OSS path (OTel -> Prometheus/Grafana/Tempo) stays a working, swappable fallback.** It is
  exercised, not aspirational: the same spans/metrics already fan out to
  `prometheusremotewrite` + `otlp/tempo` today.
- **Datadog is additive, never load-bearing for the stack to function.** Correlation tags,
  resource attributes, and service identity are driven by **OTel-neutral mechanisms**
  (`OTEL_RESOURCE_ATTRIBUTES`, the `resource` processor), not by `DD_*` env vars, so the OSS
  backends get the same dimensions Datadog does.

Where a decision below has a "more Datadog-native" option and a "more portable" option, the tie
is broken in favor of preserving the swappable OSS fallback, unless the Datadog-native option is
additive and does not break the fallback.

---

## Decision 1: Observability path (pure OTel vs hybrid vs full Datadog)

**Decision.** Which telemetry topology runs on stage: (A) pure OTel Collector -> Datadog
exporter (current repo state), (B) hybrid OTel Collector + Datadog Agent / DDOT DaemonSet, or
(C) full Datadog (Datadog Agent does the collecting, OTel minimized).

**Options, pros/cons.**

- **A. Pure OTel Collector -> Datadog exporter (current state). CONFIRMED in repo.**
  - Pros: Maximum portability and the cleanest fit to the design principle: one Collector,
    Datadog is just one exporter among three, removing it leaves Prometheus + Tempo working.
    No second agent, lowest per-node footprint (matters at ~60-70 attendee clusters). Vendor
    -neutral instrumentation end to end.
  - Cons: Some Datadog features assume the Datadog Agent or DDOT (host/process/network metrics,
    certain integration autodiscovery, live container view). The Datadog exporter covers
    metrics/traces/logs mapping but is not 100% feature-parity with the Agent. The service-map
    -from-pure-OTLP question (Decision 8) is unverified in the UI.
- **B. Hybrid: OTel Collector + Datadog Agent or DDOT DaemonSet.**
  - Datadog itself now recommends **DDOT** (the Datadog Distribution of the OTel Collector,
    embedded in Datadog Agent v7.65+) as "the recommended way to integrate OTel with Datadog,"
    deployable as a DaemonSet (Datadog docs, 2026). DDOT collapses "two DaemonSets" into one
    Agent that embeds a curated OTel Collector.
  - Pros: Full Datadog feature surface (infra metrics, live containers, integration
    autodiscovery, the inferred service map) plus OTLP ingest. Co-presenter analysis leans this
    way because it gives the richest Datadog demo. DDOT avoids the literal two-DaemonSet cost of
    "OTel Collector next to a separate Datadog Agent."
  - Cons: DDOT is a Datadog-distributed binary; standing the stack up on DDOT makes the *node
    agent* Datadog-specific. That is acceptable ONLY if the neutral OTel pipeline still exists
    underneath as the portable path. Running DDOT *and* the existing contrib Collector is two
    collectors; running *only* DDOT means "remove Datadog" is no longer a one-line exporter
    delete. Heavier per-node footprint than option A at attendee scale.
- **C. Full Datadog (Agent collects, OTel minimized).**
  - Pros: Simplest "best Datadog demo," everything in one vendor's model.
  - Cons: Directly violates the Datadog-independent-capable principle. Ripping Datadog out later
    means re-instrumenting. Rejected on principle.

**Recommendation.** Keep **A (pure OTel Collector -> Datadog exporter) as the default and
shipped path** because it is the only topology that satisfies the swappable-fallback principle
out of the box and scales cleanly to ~60-70 clusters. Treat **DDOT (B) as an optional,
feature-flagged enrichment** layered on top *for the live event only*, if and where Datadog's
Agent-only features (live container view, inferred service map, integration autodiscovery) are
needed for Whitney's narration. The portable OTel pipeline stays the source of truth; DDOT is
additive. Do **not** adopt full Datadog (C).

What stays OSS-portable: the entire instrumentation layer (OTLP + GenAI semconv), the
`prometheusremotewrite` and `otlp/tempo` exporters, the guard-proxy `/metrics` Prometheus
endpoint, and all resource attributes / UST tags (Decision 5). Removing the `datadog` exporter
(and DDOT if used) leaves Prometheus + Grafana + Tempo fully functional.

**Reversible?** Reversible. Exporter choice is config; adding/removing DDOT is an opt-in deploy.
No data-model lock-in as long as instrumentation stays OTel-neutral.

Sources: [Datadog DDOT Collector](https://docs.datadoghq.com/opentelemetry/setup/ddot_collector/),
[Install DDOT as a DaemonSet](https://docs.datadoghq.com/opentelemetry/setup/ddot_collector/install/kubernetes_daemonset/),
[Migrate to DDOT](https://docs.datadoghq.com/opentelemetry/migrate/ddot_collector/).

---

## Decision 2: Datadog dependency boundary (keep Datadog additive, not baked in)

**Decision.** How far Datadog is allowed to penetrate the stack, so that "run without Datadog"
stays a config change, not a re-architecture.

**Options, pros/cons.**

- **Additive boundary (recommended).** Datadog enters at exactly two seams: (1) the `datadog`
  exporter in the Collector, alongside `prometheusremotewrite` + `otlp/tempo`; (2) an optional,
  feature-flagged Datadog Agent / DDOT. Correlation identity is OTel-neutral:
  `OTEL_RESOURCE_ATTRIBUTES` (not `DD_ENV` / `DD_SERVICE` / `DD_VERSION`) drives UST-equivalent
  tags; Datadog maps `service.name` / `service.version` / `deployment.environment.name` to its
  `service` / `version` / `env` automatically, and the OSS backends get the same attributes.
  - Pros: One-line removal of the Datadog exporter (and the flag) leaves a working stack.
    Tags are identical across Datadog and Prometheus/Tempo, so dashboards translate. Matches the
    design principle exactly.
  - Cons: Slightly less "Datadog-idiomatic" than setting `DD_*` directly; relies on Datadog's
    OTel resource-attribute mapping (CONFIRMED supported, but verify the exact mapping in the UI
    at build).
- **Baked-in (rejected).** Use `DD_*` env vars on every pod, the Datadog Agent as the only
  collector, Datadog-proprietary tags. Best Datadog ergonomics, but removing Datadog breaks
  correlation and forces re-instrumentation. Violates the principle.

**Recommendation.** Adopt the **additive boundary**. Concretely: drive Universal Service Tagging
via `OTEL_RESOURCE_ATTRIBUTES` (Decision 5), keep the `datadog` exporter as one sink of three,
and gate any Datadog Agent / DDOT behind a feature flag (e.g. an ArgoCD app toggle or Helm value
`datadog.agent.enabled`). Never set `DD_API_KEY` anywhere except the Collector exporter and the
optional Agent; never make a workload pod depend on a `DD_*` variable to be correlated.

**Reversible?** Reversible by construction; this decision exists precisely to keep removal cheap.

---

## Decision 3: Runtime enforcement scope (keep podPidsLimit + Falco/Talon; add Tetragon or KubeArmor for OTHER attacks?)

**Decision.** Leave the fork-bomb defense as-is (podPidsLimit is the inline block, Falco 0.44.1
+ Talon the detect-and-respond theater) and decide whether to ADD a CNCF-native inline-prevention
tool (Tetragon or KubeArmor) for *non-fork* attacks (forbidden binary exec, secret-file reads,
unexpected egress).

**Options, pros/cons.**

- **Keep current stack only (podPidsLimit + Falco/Talon).**
  - Pros: Already verified, clean narrative ("the bomb fizzles, the node survives" + "Falco
    detects, Talon kills"). Lowest footprint at attendee scale. Nothing new to verify.
  - Cons: Falco only detects; podPidsLimit only caps PIDs. No CNCF-native *inline prevention*
    for "the agent ran a binary / read a secret it should not."
- **Add KubeArmor (v1.7.3) for other attacks.** Per `research/17`: KubeArmor enforces
  allow/deny of exec/file/net/capabilities inline via BPF-LSM, but has **no process-count or
  fork-rate field**, so it is NOT a fork-bomb control. Its value is inline blocking of forbidden
  binary exec, secret-file reads, and egress.
  - Pros: True inline prevention ("prevent, do not just detect"), a clean counterpoint to the
    Falco detect-and-respond station; CNCF project; least-privilege allow-list posture.
  - Cons: CNCF **Sandbox** maturity; enforcement depends on BPF-LSM being present and enforcing
    on the EKS AL2023 nodes (plausible but MUST be verified via `/sys/kernel/security/lsm`
    containing `bpf` and `karmor probe`, else it degrades to audit-only). Two eBPF agents
    (KubeArmor + Falco) add per-node load. New CRDs and policy authoring.
- **Add Tetragon for other attacks.** Tetragon (CNCF Incubating, from the Cilium project) is an
  eBPF runtime-security observability + enforcement tool that can do inline enforcement via
  in-kernel `SIGKILL`/override actions on `TracingPolicy` matches (exec, file, network).
  - Pros: More mature than KubeArmor (Incubating vs Sandbox); strong eBPF lineage; expressive
    policies for exec/file/network; good visibility story that pairs with the observability
    theme. (UNCERTAIN: exact 2026 enforcement guarantees and AL2023 behavior must be verified
    live; this doc did not deep-research Tetragon's current release.)
  - Cons: Enforcement model (kill/override on match) is a kernel-action response, not a pure
    pre-operation LSM deny like KubeArmor; policy semantics differ. Still a second eBPF agent
    alongside Falco. Needs its own build-time verification.

**Recommendation.** **Keep podPidsLimit + Falco/Talon as the fork-bomb story unchanged.** For a
non-fork inline-prevention beat, prefer **KubeArmor** *if* the demo wants a clean
"pre-operation kernel deny" allow-list story (block exec of an attacker-dropped binary, block
reading mounted secrets), accepting Sandbox maturity and the BPF-LSM verification gate. Prefer
**Tetragon** if the team values higher project maturity and a tighter fit with the eBPF
observability narrative. Either is an *addition* for OTHER attacks, never a fork-bomb control.
Given workshop time and the ~60-70-cluster footprint, the safe default is to **add at most one**
(not both) and only if an inline-prevention beat is actually on the run sheet; otherwise keep the
current two-tool stack. This is an open companion-spike item: write a dedicated Tetragon spike
before committing, mirroring `research/17` for KubeArmor.

**Reversible?** Reversible (additive DaemonSet + policies), but adoption carries a build-time
verification cost on AL2023 nodes that must be paid before the event.

---

## Decision 4: Optional TypeScript agent (spiny-orb instrumentation target)

**Decision.** Keep the kagent Python agent as primary/fallback, and add an OPTIONAL TypeScript
agent as a kagent BYO A2A backend so Whitney's `spiny-orb` (spinybacked-orbweaver) can instrument
it. Sub-decisions: TS framework (Mastra vs Vercel AI SDK), which Weaver semconv registry, and how
spiny-orb runs on stage (CLI / MCP / GitHub Action). Full detail in `research/16`.

**Why a TS agent is a real requirement, not cosmetic.** `spiny-orb` instruments **JS/TS only**;
it cannot instrument the Python kagent/ADK agent or the Python guard-proxy (`research/16`). So
for Whitney to "hook spiny-orb in," there must be JS/TS code on stage for it to run against.

**Options, pros/cons.**

- **Framework: Mastra (recommended) vs Vercel AI SDK.**
  - Mastra: built-in A2A (port 9000), MCP, Bedrock/Claude, and OTel instrumentation out of the
    box (`research/16`) - the tightest fit to slot behind kagent's A2A path. Con: more
    opinionated.
  - Vercel AI SDK (`@ai-sdk/amazon-bedrock` + `@ai-sdk/mcp`, MCP stable in AI SDK 6): lighter,
    broadest provider coverage, but needs a hand-written A2A adapter. Good fallback.
- **Weaver semconv registry.** Ship a registry that includes the **OTel GenAI semantic
  conventions** so `weaver registry live-check` validates `gen_ai.*` attributes
  (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.operation.name`, etc.). NOTE
  (`research/16`): typed-TS-attribute codegen from Weaver is NOT a confirmed Weaver target as of
  mid-2026 (Go/Java/Markdown are); do not promise TS codegen on stage without verifying a JS
  template. The solid, demoable Weaver fit is **CI live-check**, which is language-agnostic.
- **How spiny-orb runs on stage.** CLI (`spiny-orb instrument src/`) is the most predictable
  live; the MCP server (`npx spiny-orb mcp`) fits an "agent instruments an agent" framing; the
  GitHub Action fits a GitOps/PR narrative but is slower live.

**Recommendation.** Add the **optional TS agent as a `type: BYO` kagent A2A backend** using
**Mastra** (Vercel AI SDK as fallback), keeping agentgateway + MCP allowlist + HITL + LLM Guard
in front of it (smallest blast radius, Option B in `research/16`). Ship a `spiny-orb.yaml`, a
GenAI-inclusive Weaver registry, and an OTel SDK init file in the TS component so
`spiny-orb instrument` works out of the box and its generated spans flow through the existing
Collector to Datadog (and Tempo). Run spiny-orb via **CLI** on stage; keep the MCP-server framing
as the "look, an agent instrumenting an agent" flourish if time allows. Position Weaver as
**CI live-check validation**, not TS codegen.

Two gating live verifications before relying on this on stage (`research/16`): (1) a BYO TS agent
does NOT emit `adk_usage_metadata`, so either it populates that key itself or the guard-proxy is
taught the TS agent's usage key (else `witb_cost_usd` breaks); (2) confirm `requireApproval` HITL
and the agentgateway MCP `toolNames` allowlist still apply to a `type: BYO` agent.

**Reversible?** Reversible - the TS agent is additive and optional; the Python kagent agent
remains primary/fallback. The one-way-ish risk is the cost-counter usage-key wiring, which must
be resolved before the TS path is demoed.

---

## Decision 5: UST and correlation wiring (path-independent wins)

**Decision.** Adopt OTel-neutral Universal Service Tagging and fix the correlation gaps so the
same identity flows to Datadog and the OSS backends. These are wins regardless of Decision 1.

**What to wire (each is path-independent).**

- **`OTEL_RESOURCE_ATTRIBUTES` across AI-layer pods.** Set `service.name` per component
  (e.g. `workshop-agent`, `guard-proxy`, `agentgateway`, `workshop-mcp`),
  `service.version` = cluster tier (e.g. `haiku` / `sonnet` / `opus`), and
  `deployment.environment.name=watch-it-burn`. Datadog maps these to `service` / `version` /
  `env` (UST) automatically; Prometheus/Tempo get the same labels via the Collector. This keeps
  identity OTel-neutral (Decision 2) instead of `DD_*`.
- **spanmetrics connector with `add_resource_attributes: true`.** The Collector currently has
  **no `connectors:` block** (CONFIRMED). Adding a `spanmetrics` connector generates RED metrics
  from spans; the **`add_resource_attributes` field is real and defaults to `false`** in the
  contrib spanmetrics connector - set it `true` so the generated span metrics carry the resource
  attributes (service.name/version/env) and thus correlate with traces. NOTE: do not confuse it
  with `resource_metrics_key_attributes`, which only builds the grouping hash key and does NOT
  copy attributes onto the metrics. Verify the exact field against the connector version pinned
  in the Collector chart (`0.158.2`).
- **Falcosidekick -> Datadog / OTLP wiring.** Falcosidekick currently forwards only to Talon
  (CONFIRMED at `gitops/apps/falcosidekick.yaml`) and exposes Prometheus metrics; it does NOT
  forward security events to Datadog or OTLP. To put Falco events on the same observability
  surface as the rest of the telemetry, enable Falcosidekick's Datadog output for the event
  (additive) and/or its OTLP output so events also reach Tempo/Grafana - keeping the
  Datadog-additive principle (OTLP path is the portable one).
- **Add the missing `connectors:` block.** Tied to spanmetrics above; this is the structural gap
  to close.

**Recommendation.** Do all four. They are low-risk, path-independent, and improve the demo on
both Datadog and OSS backends simultaneously. Sequence: (1) `OTEL_RESOURCE_ATTRIBUTES` on
AI-layer pods; (2) add `connectors:` + `spanmetrics` with `add_resource_attributes: true` and
wire it into the traces->metrics pipelines; (3) enable Falcosidekick OTLP output (portable) plus
Datadog output (additive, event-only). Verify emitted attribute names against live spans before
building dashboards (GenAI semconv is still Development, names can churn - `research/05`).

**Reversible?** Fully reversible (Collector + pod config). These should become a numbered
companion spike (the brief's intended "18/19") if the wiring needs its own verification record.

Source: [spanmetrics connector README](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/connector/spanmetricsconnector/README.md)
(confirms `add_resource_attributes`, default `false`).

---

## Decision 6: Istio ambient observability gap (waypoint for L7, or accept L4-only)

**Decision.** The stack runs Istio **ambient** (1.30.1, ztunnel, no sidecars - CONFIRMED at
`gitops/apps/istio.yaml`). In ambient, ztunnel reports **L4 only and generates no traces**; L7
telemetry and traces come only from **waypoint proxies** (Istio/Datadog docs, 2026). Datadog's
Istio autodiscovery in ambient is correspondingly L4-only unless a per-namespace waypoint is
deployed. Decide: deploy waypoint(s) for L7, or accept L4-only and narrate it.

**Options, pros/cons.**

- **Deploy a waypoint per relevant namespace (L7).**
  - Pros: L7 HTTP/gRPC metrics and **mesh-generated traces** appear; Datadog ambient
    autodiscovery can scrape `waypoint.<ns>.svc:15020/stats/prometheus` for L7; richer service
    map and request-level visibility for Whitney's narration.
  - Cons: Each waypoint is an extra proxy Deployment per namespace - non-trivial at ~60-70
    attendee clusters/namespaces (footprint + provisioning). More to configure and verify.
- **Accept L4-only and narrate it.**
  - Pros: Zero extra proxies; matches sidecarless ambient's whole point; lowest footprint at
    scale. The app/agent already emits its own L7 + GenAI spans via OTel directly (independent of
    the mesh), so the *agent* trace story does not depend on a waypoint.
  - Cons: No mesh-level L7 spans/metrics; Datadog Istio integration shows L4 only; "the mesh
    traces requests" claim is not available without waypoints.

**Recommendation.** **Accept L4-only on the default at-scale path and narrate it honestly**
("ambient ztunnel gives us zero-trust L4 mTLS identity; L7 request tracing comes from the
application's own OTel spans, not the mesh"). The agent's GenAI/tool spans come from OTel
instrumentation, not Istio, so the core observability beat is intact. **Optionally deploy a
single waypoint in the agent namespace on the demo/driver cluster only** (not all 60-70) if
Whitney wants a live mesh-L7 / Datadog-Istio-autodiscovery moment. Configure Datadog with
`istio_mode: ambient` and point it at ztunnel (L4) plus the waypoint endpoint where one exists.

**Reversible?** Reversible (waypoints are additive per namespace). Choosing L4-only does not
preclude adding a waypoint later.

Sources: [Datadog Istio integration](https://docs.datadoghq.com/integrations/istio/),
[Istio dataplane modes](https://istio.io/latest/docs/overview/dataplane-modes/),
[Ambient tracing (waypoint-only)](https://ambientmesh.io/docs/observability/tracing/).

---

## Decision 7: Attendee Datadog accounts at scale (~60-70 orgs, key provisioning)

**Decision.** With ~60-70 per-attendee Datadog orgs, how do per-attendee API keys get
provisioned into each attendee's cluster automatically so the `datadog` exporter (and optional
DDOT) authenticate to the right org. This is an **open design question** - no in-repo mechanism
exists yet (the Collector reads `DD_API_KEY` from a `datadog-secret` that is BYO).

**Options, pros/cons.**

- **One shared Datadog org, one key, per-attendee `env` / tags.**
  - Pros: One key to provision; trivial. Per-attendee separation via
    `deployment.environment.name` / a per-attendee tag.
  - Cons: All attendees share one org's data and quota; no real isolation; one attendee's noise
    is everyone's. Weak for a "your own org" story.
- **Per-attendee org + key, provisioned via automation (recommended to design).**
  - Pros: True isolation; each attendee sees only their data; matches "per-attendee org." Best
    workshop experience.
  - Cons: Requires generating/distributing 60-70 keys and injecting each into the right cluster.
    Open mechanism: a provisioning step (script / GitOps templating / External Secrets pulling
    from a per-attendee secret store) that writes `datadog-secret` into each attendee namespace
    at cluster bring-up. Must avoid putting keys in git (use a secrets manager + External
    Secrets, or an init job seeded from a control-plane list). Per the design principle, the
    cluster must still come up and be observable on the OSS path if a key is missing - so key
    provisioning failure should NOT break the stack (Datadog exporter absent -> Prometheus/Tempo
    still work).
- **No per-attendee Datadog; attendees use the OSS path; Datadog only on the presenter cluster.**
  - Pros: Zero key-provisioning at scale; Datadog story told from the stage cluster only.
  - Cons: Attendees do not get the Datadog experience themselves.

**Recommendation.** Design for **per-attendee org + key via automated secret injection**
(External Secrets / secrets manager pulling a per-attendee key into each cluster's
`datadog-secret`), because it best serves Whitney's Datadog-centric workshop. Build it so a
missing/failed key degrades to the OSS path rather than breaking the cluster (design principle).
This is genuinely open and needs an owner and a spike before the event; if the provisioning
automation is not ready in time, fall back to "Datadog on the presenter cluster + OSS for
attendees."

**Reversible?** The choice is reversible, but at 60-70 clusters the provisioning mechanism is
effort-heavy and should be decided early - late changes here are expensive.

---

## Decision 8: Service map via pure OTel exporter, no Agent for traces (verify or de-risk)

**Decision.** The Datadog **service map** (APM Catalog -> Map, inferred service relationships) is
expected to populate from the pure OTel Collector -> `datadog` exporter path with no Datadog
Agent for traces. This is **UNVERIFIED in the Datadog UI** and needs live-cluster confirmation.
Decide: rely on the pure-OTel service map, or use the hybrid/DDOT path (Decision 1B) to de-risk
it for the live demo.

**Options, pros/cons.**

- **Rely on pure-OTel service map (current path).**
  - Pros: No Agent; keeps the portable single-Collector topology. Datadog docs indicate inferred
    services / peer-service aggregation work from OTLP (peer-service aggregation defaults on),
    and the service map renders from APM data.
  - Cons: UNCERTAIN whether the map renders *as cleanly* from pure OTLP as from the Agent. Peer
    -service inference may need `peer.service` / the right span attributes set; without the Agent,
    some inferred edges or the live-container correlation may be thinner. A blank or sparse map
    on stage would undercut Whitney's narration.
- **Use hybrid / DDOT to de-risk (Decision 1B).**
  - Pros: Datadog's own Agent/DDOT path is the best-supported route to the inferred service map;
    lowest risk of an empty map live.
  - Cons: Adds the Datadog Agent/DDOT to the demo cluster (acceptable as additive per Decision 1,
    but a heavier node footprint; only worth it on the presenter cluster).

**Recommendation.** **Verify the pure-OTel service map on a live cluster before the event** -
emit traces with proper `service.name` and `peer.service`/client-span attributes, confirm the
map renders with the expected edges in the Datadog UI, and confirm peer-service aggregation is
on. If it renders cleanly, **rely on it** (keeps the portable path). If it is sparse or empty,
**enable DDOT on the presenter cluster only** (Decision 1B) to de-risk the map for the live demo,
while attendee clusters keep the pure-OTel path. Either way, set `peer.service` and correct span
kinds so inference has what it needs.

**Reversible?** Reversible (exporter/Agent config). The risk is a poor live demo if relied upon
unverified - so the verification itself is the gate, not a code change.

Sources: [OpenTelemetry in Datadog](https://docs.datadoghq.com/opentelemetry/),
[Datadog OTLP ingest](https://docs.datadoghq.com/opentelemetry/setup/otlp_ingest/).

---

## Decisions needing Whitney + Michael sign-off

- [ ] **D1 Observability path.** Confirm: pure OTel -> Datadog exporter is the default/shipped
      path, with optional DDOT as additive enrichment on the presenter cluster only. (Reversible.)
- [ ] **D2 Dependency boundary.** Confirm Datadog stays additive: `OTEL_RESOURCE_ATTRIBUTES` (not
      `DD_*`) for UST, Datadog exporter as one sink of three, Agent/DDOT feature-flagged.
      (Reversible.)
- [ ] **D3 Runtime enforcement.** Confirm fork-bomb story stays podPidsLimit + Falco/Talon
      unchanged. Decide whether to add ONE of KubeArmor or Tetragon for non-fork inline
      prevention, and whether that beat is even on the run sheet. (Needs a Tetragon spike +
      AL2023 BPF-LSM verification if pursued.)
- [ ] **D4 TS agent.** Confirm the optional TS BYO agent (Mastra, fallback Vercel AI SDK), the
      GenAI Weaver registry, and spiny-orb run mode (CLI). Resolve the cost-counter usage-key and
      HITL/MCP-allowlist gating on a live BYO deploy before demoing.
- [ ] **D5 UST + correlation wiring.** Approve the path-independent wins:
      `OTEL_RESOURCE_ATTRIBUTES`, the missing `connectors:` block + `spanmetrics`
      (`add_resource_attributes: true`), and Falcosidekick OTLP (+ optional Datadog) output.
- [ ] **D6 Istio ambient L7.** Confirm: accept L4-only at scale and narrate it; optionally one
      waypoint in the agent namespace on the demo cluster for a Datadog-Istio L7 moment.
- [ ] **D7 Attendee Datadog keys.** Decide per-attendee org + automated key injection vs shared
      org vs Datadog-on-presenter-only. Assign an owner; design so a missing key degrades to the
      OSS path. Decide early (60-70 clusters).
- [ ] **D8 Service map.** Owner to live-verify the pure-OTel service map in the Datadog UI; if
      sparse, enable DDOT on the presenter cluster to de-risk.

Cross-cutting verification (per `research/05` and `research/14`): GenAI semconv is still
Development - pin emitter versions, set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`
deliberately, record actual emitted attribute names, and keep content capture
(`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`) OFF on the shared path (the trace re-leak
trap).
