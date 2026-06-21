# Datadog + OTel Planning Session

*Captured from conversation on 2026-06-21*

---

## Confirmed facts from this session

- **Michael is rewriting the app (guard-proxy / server.py) into TypeScript.** This means Spiny-orb (spinybacked-orbweaver) can instrument the main agent app directly once the rewrite is done. The Python OTel research spike is not needed — wait for the rewrite before instrumenting the AI layer.
- **Spiny-orb does not support Python.** It targets JavaScript and TypeScript only. The Python apps (evil-mcp-shim, customer-stream generator) either need to wait for rewrites or use the Python OTel SDK separately.

---

## Key framing: must-have vs. nice-to-have telemetry

**Must-have** — directly serves the security story beats and demo flow:
- The agent's LLM calls: prompts (content capture on), token costs, tool calls
- Before/after sanitization visible in traces (the re-leak trap story)
- The rogue MCP tool call chain visible in a trace waterfall (Beat 3)
- Falco runtime alerts when exfil is attempted
- Cost counter — token spend is visible and accumulating ("wasted tokens are the new DoS")

**Nice-to-have** — makes Datadog look cool, shows the platform is observable, not load-bearing for the workshop narrative:
- ArgoCD dashboard
- Kyverno metrics
- Istio mesh traffic in APM
- cert-manager, ESO, Backstage metrics
- Out-of-the-box dashboards per platform component

The nice-to-have items may come for free depending on which architectural path we choose. They don't drive the decision.

---

## The open architectural decision

**Datadog path vs. pure OTel path vs. hybrid — not yet decided.** This is why research spikes are needed before writing PRDs.

**Pure OTel + Datadog Exporter (current state):**
- Philosophically correct for an open-source workshop
- The OTel Collector is already deployed and wired
- Nothing is auto-discovered — everything must be explicitly instrumented
- No Datadog Agent, no auto-magic

**Datadog Agent DaemonSet (added alongside the Collector):**
- Auto-discovers node/pod/container metrics, K8s state, container logs
- Has named integrations for many components — if an integration exists, it may auto-discover and provide OOB dashboards
- Those OOB dashboards are nice-to-have; they come for free if the Agent is installed anyway
- More moving parts in the cluster

**Hybrid path:**
- Keep the existing OTel Collector for the AI layer (guard-proxy, agent spans, gen_ai.* data)
- Add the Datadog Agent DaemonSet for cluster infra auto-discovery
- Both feed into the same Datadog org
- Gets the best of both: pure OTel for the "everything is open source" story, auto-magic for cluster visibility

The answer depends on what the research spikes reveal about what each component natively emits and what Datadog auto-discovers.

---

## What we know about the current state of the repo

- OTel Collector is already deployed as a DaemonSet (`gitops/apps/otel-collector.yaml`)
- Datadog exporter is already wired — just needs a `datadog-secret` per cluster (keys confirmed correct in research 14)
- Prometheus remote write + Tempo are configured as fallback exporters
- `kubernetesAttributes` preset is enabled — auto-enriches spans with pod/namespace/node labels
- OTLP receivers on 4317/4318 are live
- The guard-proxy already exposes Prometheus metrics at `/metrics`: `witb_cost_usd`, `witb_tokens_total`, `witb_requests_total`
- The guard-proxy already holds before/after sanitization text in memory — no OTel instrumentation yet
- The existing OTel Collector config is **missing** a `connectors:` section — no `spanmetrics` or `datadog/connector` — likely why metrics aren't appearing in Datadog from other projects

**Known bug found in research 14:** `proxy.py` parses `kagent_usage_metadata` from the A2A response, but the actual key is `adk_usage_metadata`. This means the cost counter silently tallies zero tokens against a real kagent ADK agent — breaking the "wasted tokens are the new DoS" story. Fix: change the key in `record_usage()`, keep a fallback to `kagent_usage_metadata` only if live capture proves kagent re-keys it.

---

## What existing research covers (and what it does NOT)

### research/05-otel-genai-observability.md (June 15, 2026)
Covers the GenAI OTel story deeply:
- All GenAI semconv is still Development status (not Stable)
- `execute_tool {gen_ai.tool.name}` spans are the right primitive for showing rogue MCP tool calls
- kagent tracing is off by default — enable via Helm: `otel.tracing.enabled: true`
- Content capture (`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`) is false by default — load-bearing for the re-leak trap beat
- The re-leak trap design is fully worked out
- v1.36→v1.37 attribute shape change: `gen_ai.input.messages` / `gen_ai.output.messages` (opt-in via `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`)

**Gap:** Targeted Tempo + Grafana as the backend, not Datadog. Does NOT answer whether Datadog's LLM Observability product surfaces from pure OTel `gen_ai.*` spans.

**Still unverified (need live-cluster verification):**
- Whether kagent actually emits `gen_ai.*` / `execute_tool` spans on a real cluster
- Whether agentgateway tags LLM/tool traffic with `gen_ai.*` vs. generic proxy spans

### research/12-mechanism-verification-2026.md (June 20, 2026)
Confirms the OTel content-capture design: redaction processor in the Collector scrubs sensitive attributes before export. The "content-capture lands the sentinel in a span; symmetric collector-side redaction is the fix" framing is accurate. Content capture must be deliberately enabled — it's off by default.

### research/14-verify-at-build-sweep-2026.md (June 20, 2026)
Key findings relevant to observability:
- Datadog OTel exporter keys in `gitops/apps/otel-collector.yaml` are **CONFIRMED correct** (`datadog.api.key`, `datadog.api.site`, `${env:DD_API_KEY}` syntax)
- `DD_SITE` defaults to `datadoghq.com`; must be set to the real account site at build
- **agentgateway v1.3.0 went GA on 2026-06-17** — all "beta" warnings and v1.2.1 pins in the repo are stale. Docs may have changed; field paths need re-verification against v1.3.0 standalone docs.

### research/06-cncf-stack.md (June 15, 2026)
Covers platform component versions and security mechanisms, not their telemetry emission or Datadog integrations:
- Falco 0.44.1 current (Falcosidekick is the event-forwarding layer, has native Datadog output)
- OTel Collector v0.154.0 current
- Kyverno v1.18.1 / chart 3.8.1 current
- ArgoCD v3.4.3 current

### research/01-kagent.md (June 15, 2026)
Covers kagent v0.9.7 CRD schemas. OTel tracing exists but was not the focus of this spike.

### research/02-agentgateway.md (June 15, 2026)
Written when v1.2.1 was current (now stale — v1.3.0 is GA). Covers guardrail mechanism. Does not cover what agentgateway emits in terms of OTel telemetry.

---

## Open questions / research still needed

### Spike A — Datadog on EKS + what each component natively emits ✅ Complete

Full findings in [`docs/research/datadog-integrations-stack.md`](../docs/research/datadog-integrations-stack.md).

**Architectural decision (answered):** Hybrid path. Keep the existing OTel Collector for OTLP (kagent, agentgateway, Kyverno). Add the Datadog Agent DaemonSet for EKS infra auto-discovery and named integrations. Pre-bake pod annotations into platform manifests. DDOT is the 2025/2026 recommended path over two separate DaemonSets but requires Agent v7.65+; evaluate at build time.

**Key finding:** Nothing auto-discovers without at least a pod annotation. The "free" tier is EKS nodes/containers/K8s state only.

| Component | Natively emits | DD integration? | Auto-discovered? | Notes |
|---|---|---|---|---|
| ArgoCD | Prometheus (3 ports: 8082/8083/8084) | Yes (Agent 7.42+) | No — pod annotations required | Medium effort; no OOTB dashboard |
| Kyverno | Prometheus + OTLP opt-in (`otelConfig=grpc`) | Yes (Agent 7.56+) | No — per-controller annotations (4 pods) | Only platform tool with native OTel |
| Falco | Prometheus; Falcosidekick adds OTLP fan-out | Yes (Agent 7.59.1+) | No — `falco.yaml` edits + annotations | Has OOTB dashboard; detect-only (no blocking) |
| KubeArmor | Prometheus via **separate** `kubearmor-prometheus-exporter` deploy; gRPC log stream; no native OTLP | No | No | Enforcement layer (eBPF/LSM blocks syscalls — fork bomb prevention); complements Falco's detect/alert role; extra exporter deploy required |
| Istio ambient | Prometheus + OTel via Telemetry API; **L4 only** without waypoint proxy | Yes (broken in ambient — sidecar auto_conf doesn't fire) | Broken | Must set `istio_mode: ambient` explicitly; no HTTP metrics without per-namespace waypoint |
| ESO | Prometheus only | No | No | High effort — generic openmetrics check |
| cert-manager | Prometheus (port 9402) | Yes (Agent 7.22+) | No — single endpoint config | Low effort; has OOTB dashboard; `rename_labels: {name: cert_name}` required |
| Backstage | Nothing by default | No (UI embed only, not Agent check) | No | Needs full OTel SDK wiring before any data flows |
| kagent | OTLP gRPC 4317 (confirmed); Prometheus (unverified) | No | No | Low effort: 1 Helm value `otel.tracing.enabled: true` |
| agentgateway | Prometheus (15020 + 9092) + OTLP traces + OTel logs | No | No | Medium effort; v1.3.0 GA 2026-06-17 |

**KubeArmor vs. Falco decision:** Keep both. Falco handles detect/alert and feeds Datadog via its named integration + OOTB dashboard. KubeArmor handles enforcement (actually stops the fork bomb on Cluster 2). Observability story: KubeArmor's `kubearmor_alerts_with_action_total{action="Block"}` counter shows the block happened; Falco's alerts show it was detected. KubeArmor's `kubearmor_alerts_with_operation_total` can be scraped via the separate exporter using the generic openmetrics check.

### Istio ambient enabled dynamically by kagent (insight from 2026-06-21 session)

If Istio is already installed but kagent labels namespaces to enroll them in the ambient mesh at runtime, the Datadog Istio integration is unaffected — it points at static ztunnel/istiod endpoints and keeps working. The mesh enrollment change just shows up as changed traffic volume in `istio_tcp_*` ztunnel metrics, with no per-namespace breakdown.

If kagent installs Istio itself (not just labels namespaces), the `istio_mode: ambient` config must be pre-set in the Datadog Agent check config before the check runs. The check will fail-and-retry until the endpoints come up, but the initial metrics window is lost.

More interesting workshop angle: if the agent SA has `update` on namespace labels, kagent removing `istio.io/dataplane-mode=ambient` from a namespace silently removes mTLS. That shows up as a drop in ztunnel connections — subtle in metrics, but a Falco rule watching for namespace label modifications would catch it explicitly. Worth verifying the agent SA RBAC in `agent/rbac/agent-role.yaml` does not include namespace label update permissions unless the attack is intentional.

### Spike B — Datadog LLM Observability with OTel gen_ai.* spans (blocks AI layer PRD design)
No existing research covers this. Questions:
- Does Datadog's LLM Observability product surface from pure OTel `gen_ai.*` spans sent via the Datadog Exporter — without `ddtrace`?
- What does it actually show? Prompt/response diffs, token cost, tool calls, before/after sanitization?
- Or does "LLM Observability" here just mean APM traces with `gen_ai.*` attributes?
- This determines whether the workshop's telemetry payoff is in a purpose-built Datadog product or just APM.

### Open question — TypeScript rewrite scope
- Confirmed: Michael is rewriting the main app into TypeScript
- Open: Does this include the evil-mcp-shim (`beats/03-bad-mcp-excessive-agency/evil-mcp-shim/server.py`)?
- Open: Does this include the customer-stream fake data generator?
- If those stay Python, need to decide: Python OTel SDK or defer

---

## The vision for what attendees see in Datadog

**Must-have (security story):**
- The agent's LLM calls: prompts, responses, token costs, tool calls — visible as traces
- Before sanitization vs. after sanitization in traces — the re-leak trap
- The rogue MCP tool call chain in a trace waterfall — Beat 3's smoking gun
- Falco runtime alerts when exfil is attempted
- Cost counter accumulating in real time

**Nice-to-have (platform visibility):**
- Whole cluster: nodes, pods, containers
- Platform component dashboards (ArgoCD, Kyverno, Istio, etc.)
- Everything correlated: logs ↔ traces ↔ metrics

---

## Attendee Datadog accounts

Whitney has 7 trial Datadog accounts for testing now, more available next week. At scale the workshop needs 60-70 per-attendee orgs. Each account has: `datadogApiKey`, `datadogAppKey`, `publicOrgId`, `internalOrgId`, and an expiration date. How these get provisioned into clusters automatically is an open design question (part of Spike A).
