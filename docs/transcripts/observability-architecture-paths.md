# Observability Architecture Paths

*Planning synthesis, 2026-06-21. Follows from `observability-planning.md`.*
*Updated same day to reflect decisions made by Michael + Whitney.*

**Decision: Path 2 (hybrid) with OTel-neutral instrumentation.**
OTel Collector is the neutral primary — all OTLP/GenAI semconv instrumentation routes through it,
Datadog stays swappable. Datadog Agent (or DDOT) is additive for EKS infra + named integrations,
gated behind a feature flag. Dropping the `datadog` exporter must leave Prometheus + Grafana + Tempo
functional. See `research/23-observability-decision-points-2026.md` for the full rationale and
`research/24-datadog-hybrid-impl-sizing-2026.md` for the implementation spec.

**Division of labor:** Whitney owns Datadog account/keys/Agent install/dashboards; Michael owns
OTel-side wiring + manifest annotations + datadog-secret consumption.

**Already implemented (commit `6c6a81d`):**
- `spanmetricsconnector` with `add_resource_attributes: true` wired into the Collector
- UST tags via `OTEL_RESOURCE_ATTRIBUTES` on guard-proxy, agentgateway, kagent
- Falcosidekick → Datadog native output via `datadog-secret`

---

## Foundation: What All Three Paths Share

OpenTelemetry is the instrumentation layer in every path. The OTel Collector is already deployed
as a DaemonSet and wired to the Datadog exporter. OTLP receivers are live on 4317/4318.
`kubernetesAttributes` preset auto-enriches spans with pod/namespace/node labels. Prometheus
remote write and Tempo are configured as secondary fallbacks.

Prometheus is part of every path — it is the native wire format for most CNCF platform components
(ArgoCD, Kyverno, Falco, cert-manager, the guard-proxy's own `/metrics` endpoint at
`witb_cost_usd` / `witb_tokens_total` / `witb_requests_total`). The question for each path is
*who scrapes those endpoints and how the data reaches Datadog*, not whether Prometheus is in
the story.

**Note:** The existing `prometheusremotewrite` exporter in `gitops/apps/otel-collector.yaml`
forwards to the local kube-prometheus-stack. It is the secondary fallback, not a path to
Datadog. The `datadog:` exporter is the primary sink.

**Must-have observability** (load-bearing for the workshop narrative):
- Agent's LLM calls: prompts, responses, token costs, tool calls — visible as traces
- Before/after sanitization in traces (the re-leak trap)
- The rogue MCP tool call chain as a trace waterfall (Beat 3's smoking gun)
- Falco runtime alerts when exfil is attempted
- Cost counter accumulating in real time

**Nice-to-have** (platform visibility, "Datadog sees everything"):
- Whole cluster: nodes, pods, containers
- Platform component dashboards (ArgoCD, Kyverno, Istio, etc.)
- Everything correlated: LLM trace → pod logs → Falco alert → Kyverno decision in one UI flow

---

## Path 1: Pure OTel — No Datadog Agent

OTel Collector handles all telemetry collection. Data reaches Datadog exclusively via the
Datadog exporter. No Datadog Agent DaemonSet.

### What the lab user sees

APM traces with the `invoke_agent → plan → execute_tool` waterfall. The gen_ai.* spans are
there — tool names, token counts, model metadata. The rogue MCP tool call in Beat 3 appears as
an `execute_tool` span naming the bad tool. Cost counter metrics arrive via the OTel pipeline.

That is where the experience stops. No infrastructure context. No live containers view. No
Kubernetes service map. When Kyverno blocks an admission request, that event lives only in
Kyverno's Prometheus — nobody is scraping it. Falco alerts go nowhere without Falcosidekick.

The "jump from LLM trace to pod logs" pivot is **available** on this path — but requires explicit
setup. Spike B research (research/19-datadog-otel-ust-correlation-2026.md) confirms "View Trace
in APM" and the Logs tab in APM both work for OTLP-ingested logs. Requirements: `trace_id` /
`span_id` in the log JSON, consistent `service`/`env`/`version` tags. The Datadog Exporter
handles `service.name` → `service` remapping automatically. The Agent simplifies log tag
injection from pod logs but is not the only path.

**Prometheus in this path:** OTel Collector adds a `prometheus` receiver to scrape component
endpoints and forward via the Datadog exporter. Raw scrape configs, no named integration
awareness, no OOTB dashboards.

### Must-haves
| Signal | Status |
|---|---|
| LLM call waterfall | ✅ |
| Tool call visibility | ✅ |
| Cost counter | ✅ |
| Before/after sanitization | ✅ |
| Falco alerts in Datadog | ⚠️ Requires Falcosidekick config (not currently wired) |
| Log-trace-metric correlation | ✅ Confirmed — requires explicit field setup |

### Work and brittleness
Smallest delta from today: Falcosidekick config + `connectors:` block in the Collector. Roughly
half a day. Low brittleness for what it does.

---

## Path 2: Hybrid — OTel Collector for AI Layer + Datadog Agent DaemonSet

Keep the OTel Collector for OTLP. Add the Datadog Agent DaemonSet for cluster infrastructure,
named integrations, and log collection. Both feed the same Datadog org. Conclusion of Spike A.

### What the lab user sees

APM trace waterfall unchanged — still OTel. A live Kubernetes map: nodes, pods, containers.
Agent tails pod logs and injects UST tags. OTel Exporter sends traces with the same tags.
When both sides carry `service=guard-proxy env=watch-it-burn`, Datadog connects them. Click
from an LLM trace into pod logs, into the Falco OOTB dashboard showing the runtime alert — one
UI flow. Reliable, no manual log field injection required.

EKS node metrics free from the Agent. Token cost climbing alongside node CPU — the wasted-token
story in one panel.

**Prometheus in this path:** Agent's named integrations *are* Prometheus scrapers with
Datadog-aware configuration baked in. OTel Collector handles OTLP; Agent handles Prometheus
scraping for named integrations. Kyverno's native OTel opt-in (`otelConfig=grpc`) worth enabling
to put policy decision traces inside the same gen_ai span tree.

**Named integrations that pay off (with annotation work):**

| Component | Integration | OOTB Dashboard | Effort |
|---|---|---|---|
| EKS nodes/containers | Yes (composite) | 3 dashboards | Low (IRSA + Helm) |
| Falco | Yes (Agent 7.59.1+) | Yes | Medium (falco.yaml edits + annotations) |
| cert-manager | Yes (Agent 7.22+) | Yes | Low (single endpoint config) |
| OTel Collector | Yes | 2 dashboards | Low |
| ArgoCD | Yes (Agent 7.42+) | No | Medium (3 ports, per-pod annotations) |
| Kyverno | Yes (Agent 7.56+) | No | Medium (4 controllers, per-pod annotations) |

### Must-haves
All covered. Falco via named integration (cleaner than Falcosidekick alone). Log-trace-metric
correlation reliable via Agent.

### Work and brittleness
2–3 days. One coexistence rule: `datadog.prometheusScrape.enabled` stays off (double metrics
and billing if enabled). Hostname alignment between Agent and Collector via `k8s.node.name`.
Both are known config values, not emergent behavior.

DDOT (Agent v7.65+, embedded Collector) is the Datadog-recommended alternative to two
DaemonSets — evaluate at build time.

---

## Path 3: Full Datadog (Whitney's Inclination)

Path 2 as the foundation, plus UST at full fidelity, custom workshop dashboards, and the
remaining integrations worth wiring.

OTel remains the instrumentation layer throughout. Path 3 adds more of it: Kyverno's OTLP
output in the trace waterfall, agentgateway's OTel logs correlated with traces, the full service
map drawn from UST-tagged OTel data.

### What the lab user sees

The service map draws a line: guard-proxy → agentgateway → kagent → Bedrock. Every hop is a
node with a health indicator. Click any node: traces, logs, error rate, latency, Kubernetes
metadata. One-click pivot from any signal to any other.

For the model-tier comparison: panels showing token cost by `service.version` (which carries
the cluster tier string `cluster-1`, `cluster-2`, `cluster-3`). Attendees watch Opus spending
money faster than Haiku without narration — the cost thesis becomes visual.

Falco + KubeArmor as two visible roles: Falco's OOTB dashboard shows detections; a KubeArmor
panel shows `kubearmor_alerts_with_action_total{action="Block"}` for non-fork attacks (binary
exec blocking, secret file read prevention).

**UST implementation** (do this regardless of path — it is cross-cutting and low cost):

Set `OTEL_RESOURCE_ATTRIBUTES` on all AI layer pods:
- `service.name`: `guard-proxy` / `agentgateway` / `kagent` (per component)
- `service.version`: cluster tier string (`cluster-1`, `cluster-2`, `cluster-3`)
- `deployment.environment.name`: `watch-it-burn`

**Prometheus in this path:** Path 2 named integrations, plus:
- KubeArmor via `kubearmor-prometheus-exporter` (separate deployment, 9 alert counters,
  generic openmetrics check)
- agentgateway's Prometheus endpoints (ports 15020 + 9092)
- kube-prometheus-stack components via Agent annotations

**Critical OTel Collector config for metrics-to-logs correlation:**
The `spanmetricsconnector` drops `env` and `version` resource attributes from generated metrics
by default. Without this, "View related logs" silently fails for span-derived metrics:

```yaml
connectors:
  spanmetrics:
    add_resource_attributes: true
```

See research/19-datadog-otel-ust-correlation-2026.md for the full gotcha.

**Custom workshop dashboards** (all from data already in the pipeline):

| Dashboard | Data Source | Story |
|---|---|---|
| Wasted Tokens Over Time | `witb_tokens_total` by cluster tier | Cluster 1 burning |
| Model Tier Cost Race | token spend/sec per `service.version` | Haiku vs. Sonnet vs. Opus |
| Tool Call Heatmap | `gen_ai.tool.name` frequency | Before vs. after MCP restriction |
| KubeArmor Enforcement | `kubearmor_alerts_with_action_total` by operation | Binary exec / secret reads blocked |
| Guardrail Toggle Timeline | cost counter + trace volume | Counter goes flat at input guard |

**Spike B is resolved:** Datadog log-trace and metrics-to-logs correlation work equivalently on
the pure OTel path as on the dd-trace path. No ddtrace required. See
research/19-datadog-otel-ust-correlation-2026.md.

**What to skip (fragile, not worth it):**

| Component | Why |
|---|---|
| Grafana integration | Custom Agent image required — every Agent version bump is a rebuild |
| Istio ambient integration | Sidecar auto-discovery broken in ambient mode; L4 only without waypoint |
| Backstage OTel wiring | High effort; explicitly nice-to-have per BUILD-SPEC |
| ESO openmetrics | No named integration; low signal for the workshop |
| Loki | High cardinality risk from `tenant` label |

### Work and brittleness
4–5 days (selective). OOTB integrations from Path 2 are stable. Custom dashboard JSON is
tedious to build but stable once committed. Fragile pieces stay out.

---

## Comparison

| | Path 1 | Path 2 | Path 3 |
|---|---|---|---|
| OTel trace waterfall | ✅ | ✅ | ✅ |
| Tool call visibility | ✅ | ✅ | ✅ |
| Cost counter | ✅ | ✅ | ✅ |
| Falco alerts in Datadog | ⚠️ | ✅ | ✅ |
| K8s infrastructure context | ❌ | ✅ | ✅ |
| Log-trace-metric correlation | ✅ (manual setup) | ✅ (Agent simplifies) | ✅ + service map |
| OOTB dashboards | 0 | ~6 | ~6 + custom panels |
| KubeArmor enforcement visible | ❌ | ❌ | ✅ |
| Model-tier cost comparison | ❌ | ❌ | ✅ |
| Setup work | ~0.5 days | ~2–3 days | ~4–5 days (selective) |
| Brittleness | Low | Low-medium | Low-medium if fragile pieces skipped |

---

## Fork Bomb / KubeArmor — Resolved ✅

Live validation session (2026-06-21, commit `f424d45`) confirmed: fork bomb is stopped by
`podPidsLimit`. Falco detects the attempt; Falco Talon responds (kill pod). This pair is
live-validated and shipped.

KubeArmor cannot stop a fork bomb (no process-count/fork-rate field; `syscalls:` is audit-only).
See `research/17-kubearmor-forkbomb-2026.md`, `research/21-kubearmor-claims-verification-2026.md`,
and `research/22-runtime-enforcement-comparison-2026.md` for the full analysis.
KubeArmor's status in the stack is tracked separately.

---

## Remaining Open Questions

1. **Service map (Michael's input needed):** UST tag mapping is confirmed; whether the full
   Datadog service map appears via the OTel Exporter path (no Agent for traces) needs live-cluster
   verification.

2. **KubeArmor attack vector:** See options above.

3. **TypeScript rewrite scope — resolved (2026-06-22):** Rewrite is NOT happening. All Python apps (guard-proxy, evil-mcp-shim, customer-stream generator) stay Python. AI layer OTel instrumentation uses the Python OTel SDK directly, or relies on kagent/agentgateway built-in OTel output.

4. **Attendee Datadog accounts at scale:** 60–70 per-attendee orgs at workshop scale. How do
   API keys get provisioned into per-attendee clusters automatically?
