# Research: Datadog Integrations + Auto-discovery for Watch It Burn Stack

**Project:** Unleash_an_Agent_Watch_It_Burn
**Last Updated:** 2026-06-21

## Update Log
| Date | Summary |
|------|---------|
| 2026-06-21 | Initial research — per-component Datadog integration + native telemetry survey |

## Findings

### Summary

Nothing in this stack is zero-touch auto-discovered by the Datadog Agent. Every component requires
at minimum a pod annotation or config file, even when a named integration exists. The realistic
split: EKS nodes/containers are nearly free, the CNCF platform tools need annotations but have
integrations, the newer AI-layer tools (kagent, agentgateway, Backstage) need manual OTel wiring.

### Surprises & Gotchas

**Istio ambient mode breaks the Datadog Istio integration's autodiscovery.** 🔴 High confidence
The integration's `auto_conf.yaml` fires on `istio-proxy` sidecar containers — which don't exist
in ambient mode. You get nothing without explicitly setting `istio_mode: ambient` plus configuring
`ztunnel_endpoint`, `waypoint_endpoint`, and `istiod_endpoint`. Worse: ztunnel only emits TCP/L4
metrics. There are no HTTP-level metrics without deploying a waypoint proxy per namespace.
Source: https://docs.datadoghq.com/integrations/istio/

**Backstage emits nothing by default.** 🔴 High confidence
Zero metrics, zero traces out of the box. The "Datadog integration for Backstage" listed at
datadoghq.com/integrations/ is a UI-embedding tool (embed DD dashboards into Backstage), not an
Agent check. Full OTel SDK wiring required before any data flows.
Source: https://backstage.io/docs/tutorials/setup-opentelemetry/

**Datadog recommends DDOT over running Agent + OTel Collector as two DaemonSets.** 🟡 Medium confidence
Side-by-side creates hostname alignment risks (double host billing) and Prometheus duplication if
`prometheusScrape.enabled` ever gets switched on. DDOT (Agent v7.65+, embedded Collector) is the
explicitly recommended 2025/2026 path. See `~/.claude/rules/ddot-gotchas.md` for gotchas.

**kagent Prometheus metrics are unconfirmed.** 🟡 Medium confidence
Docs claim Prometheus metrics but list no metric names or scrape config. OTLP traces are confirmed
and documented. Don't plan a Prometheus pipeline for kagent until inspecting a running pod's
`/metrics` endpoint.

**Grafana integration requires installing a `.whl` package onto the Agent.** 🟡 Medium confidence
It's in `integrations-extras`, not bundled. Needs a custom Agent image or init container for
every cluster.

**EKS etcd metrics are not available via Prometheus scrape.** 🟡 Medium confidence
AWS manages etcd; those metrics only come through CloudWatch `AWS/EKS` namespace.

**Loki high-cardinality risk.** 🟡 Medium confidence
The `tenant` label on many Loki metrics means `"metrics": [".*"]` generates very high custom
metric counts in Datadog. Scope the metrics list deliberately.

**cert-manager `rename_labels` is a non-obvious gotcha.** 🟢 High confidence
Without `rename_labels: {name: cert_name}`, the generic `name` tag collides with `name` tags from
AWS and other integrations. Breaks tag-based filtering in dashboards.
Source: https://docs.datadoghq.com/integrations/cert_manager/

### Per-Component Table

| Component | Named DD Integration | OOTB Dashboards | Agent Auto-discovers | Native Telemetry | Wiring Effort |
|---|---|---|---|---|---|
| **ArgoCD** | Yes (Agent 7.42+) | No | No — pod annotations, 3 ports | Prometheus (8082/8083/8084) | Medium |
| **Kyverno** | Yes (Agent 7.56+) | No | No — per-controller annotations (4 pods) | Prometheus + **OTel/OTLP opt-in** | Medium |
| **Falco** | Yes (Agent 7.59.1+) | **Yes** | No — `falco.yaml` edits + annotations | Prometheus; Falcosidekick adds OTLP fan-out | Medium |
| **Istio ambient** | Yes (Agent 6.1+) | Unconfirmed | **Broken** — sidecar auto_conf doesn't fire in ambient | Prometheus + OTel via Telemetry API; **L4 only without waypoint** | High |
| **ESO** | **No** | No | No | Prometheus only | High (generic openmetrics) |
| **cert-manager** | Yes (Agent 7.22+) | **Yes** | No — single endpoint config | Prometheus (port 9402) | Low |
| **kagent** | No | No | No | OTLP gRPC 4317 (confirmed); Prometheus (unverified) | Low (1 Helm value) |
| **agentgateway** | No | No | No | Prometheus (15020 + 9092) + OTLP traces + OTel logs | Medium |
| **OTel Collector** | Yes (v1.0.0) | **Yes (2)** | No — Collector pushes via datadog exporter | Prometheus port 8888 (`otelcol_` prefix) | Low |
| **kube-prometheus-stack** | No | No | No — pods lack scrape annotation | Prometheus (9090/9093/8080/9100) | Medium |
| **Grafana** | Yes (extras, not bundled) | No | No — `.whl` install required | Prometheus port 3000 | Medium+ |
| **Tempo** | No (Cloud-only AI tool only) | No | No | Prometheus port 3100 | Low (generic annotation) |
| **Loki** | No | No | No | Prometheus port 3100 (high cardinality risk) | Low-Medium |
| **Backstage** | **No** (UI embed only, not Agent check) | No | No | Nothing by default — OTel SDK required | High |
| **AWS EKS** | Yes (composite) | **Yes (3)** | Partial — nodes/containers auto; control plane manual | CloudWatch + Prometheus endpoints | Medium (IAM + Helm) |

### The Free Tier (nearly zero config once Agent DaemonSet is installed)

With just the Datadog Agent DaemonSet installed and EKS IAM granted:
- All node metrics (CPU/memory/disk/network per node)
- All container/pod metrics and live container view
- Kubernetes state (deployment status, pod counts, resource limits)
- CloudWatch EKS metrics (EKS 1.28+, exported by AWS automatically at no extra cost)
- 3 OOTB EKS dashboards

Everything else costs annotation or config work.

### The Kyverno OTel Standout

Kyverno is the only platform component with native OTel/OTLP. It can push both metrics and traces
to an OTel Collector via a single Helm flag: `otelConfig=grpc`. Every other component is
Prometheus-only natively (Falcosidekick aside, which fans out to 50+ destinations including OTLP).

### Agent + OTel Collector Coexistence

**Do NOT enable `datadog.prometheusScrape.enabled: true`** — off by default, and turning it on
while the OTel Collector is also scraping creates double metrics and billing spikes.

Recommended split when running both:

| Responsibility | Owner |
|---|---|
| Node/infra/container metrics | Datadog Agent |
| OTLP app traces/metrics/logs | OTel Collector → Datadog exporter |
| App Prometheus scraping | Pick one — not both |
| kube-state-metrics | OTel Cluster Collector |

Datadog's 2025/2026 recommendation is DDOT (Agent v7.65+ with embedded Collector) to avoid this
entirely. See `~/.claude/rules/ddot-gotchas.md`.

**Hostname alignment required:** Both Agent and Collector must report the same host using
`k8s.node.name`. Mismatched identifiers create duplicate host entries and double billing.

### Workshop Recommendation

For a 2-hour workshop where "Datadog shows you everything" is the payoff:

1. Install the Datadog Agent DaemonSet — gives EKS infra free. Add IRSA/IAM for CloudWatch.
2. Keep the existing OTel Collector with Datadog exporter for OTLP (kagent, agentgateway, Kyverno).
3. Pre-bake the annotations into platform manifests for named integrations (ArgoCD, Kyverno, Falco,
   cert-manager). Attendees get them for free.
4. Accept the gaps: ESO, Grafana, Backstage need more work — narrate as "these need wiring" rather
   than demoing them.
5. Istio ambient: don't promise L7 metrics without deploying a waypoint proxy.

## Sources

- https://docs.datadoghq.com/integrations/argocd/ — ArgoCD integration, annotation config
- https://docs.datadoghq.com/integrations/kyverno/ — Kyverno integration
- https://docs.datadoghq.com/integrations/falco/ — Falco integration, OOTB dashboard confirmed
- https://docs.datadoghq.com/integrations/istio/ — Istio integration, ambient mode config
- https://docs.datadoghq.com/integrations/cert_manager/ — cert-manager integration, rename_labels
- https://docs.datadoghq.com/integrations/otel/ — OTel Collector integration, 2 dashboards confirmed
- https://docs.datadoghq.com/integrations/grafana/ — Grafana extras integration
- https://docs.datadoghq.com/integrations/amazon-eks/ — EKS composite integration
- https://docs.datadoghq.com/containers/kubernetes/prometheus/ — Prometheus autodiscovery warning
- https://backstage.io/docs/tutorials/setup-opentelemetry/ — Backstage OTel SDK setup
- https://external-secrets.io/latest/api/metrics/ — ESO Prometheus metrics
- https://cert-manager.io/docs/devops-tips/prometheus-metrics/ — cert-manager metrics
- https://istio.io/latest/docs/reference/config/metrics/ — Istio ambient metric shapes
- https://falco.org/docs/outputs/ — Falco output destinations
- https://grafana.com/docs/loki/latest/operations/observability/ — Loki metrics + cardinality warning
- https://kyverno.io/docs/monitoring/ — Kyverno OTel/OTLP opt-in
