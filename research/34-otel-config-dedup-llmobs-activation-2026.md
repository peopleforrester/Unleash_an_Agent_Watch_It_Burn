<!-- ABOUTME: Per-component OTel export config, OTel/Prometheus dedup strategy, Datadog Agent-Obs UI activation, and the apm.enabled:false APM-path confirmation. -->
<!-- ABOUTME: Wires each built-in OTLP exporter at the Collector, refutes Datadog cross-source metric dedup, and confirms the Collector->datadog-exporter APM path. -->

# 34. OTel Export Config, Prometheus/OTel Dedup, LLM-Obs Activation, APM-with-apm.enabled:false

**Date:** 2026-06-24
**Issue:** #17 (OTel export configuration, Prometheus/OTel deduplication, Datadog LLM Observability UI activation, APM path under `spec.features.apm.enabled: false`)
**Scope:** Four questions. Q1 points each component's built-in OTLP exporter at the Collector. Q2 classifies the dual-signal components for double-bill risk and prescribes a remedy per component. Q3 establishes what makes the Datadog LLM Observability ("Agent Observability") UI appear. Q4 confirms the locked `spec.features.apm.enabled: false` decision is safe for APM Traces, Service Map, and trace metrics.

## Verification Method

- **Approach:** Research spike dated 2026-06-24. Every non-obvious, time-sensitive claim is checked against current (2026) official primary sources (docs.datadoghq.com, opentelemetry.io / semconv, and each component's own docs) with an inline source URL. In-repo wiring facts were read directly from the manifests this session and are treated as CONFIRMED. Claims resolvable only by running the live stack are flagged `verify-at-build`.
- **Builds on (NOT re-researched):**
  - `prds/7-observability-meta.md` Decision Log (2026-06-24): Datadog Agent installs via the Datadog Operator (DatadogAgent CR, `spec.features.*`); `spec.features.prometheusScrape.enabled: TRUE`; `spec.features.apm.enabled: FALSE`; the OTel Operator IS deployed; custom apps carry only `opentelemetry-api`, SDK injected by the Operator; the OTel Collector is a standalone `otelcol-contrib 0.158.2` DaemonSet with a `datadog` exporter (primary) on metrics+traces plus `prometheusremotewrite` + `otlp/tempo` (OSS fallback) and the `spanmetrics` + `datadog/connector` connectors.
  - `research/28` (Datadog LLM-Obs OTLP ingestion path, the `dd-otlp-source=llmobs` header, the Collector -> LLM-Obs routing gap, the product rename to "Agent Observability").
  - `research/30` (per-component telemetry inventory: ArgoCD Prometheus-only, cert-manager Prometheus-only, Kyverno both, Istio ambient both, agentgateway both, Backstage nothing-until-SDK; kagent/ADK `gen_ai.*` emission).
  - `research/32` + `research/33` CORRECTIONS at top (Datadog Agent install via Operator; OTel Operator deployed).
  - `research/29` (Python AI-layer instrumentation: agentgateway config-file path, guard-proxy proxy-span design).
  - `docs/observability-priorities.md` (Kyverno policy-decision traces are a Milestone-5 nice-to-have).

> **Naming:** Datadog renamed the product surface to "Agent Observability" (research/28). The `/llm_observability/` doc URLs and the `dd-otlp-source=llmobs` header are unchanged. This document uses "LLM Observability" and "Agent Observability" interchangeably, matching Datadog's own usage.

## Stack summary table

| Component | Built-in OTLP? | Dual-signal in this stack? | Double-bill risk today | Dedup remedy (Q2) |
|---|---|---|---|---|
| **kagent / ADK** (Python) | Yes (native, GenAI semconv) | No (OTLP traces only; center-stage) | None | n/a (single OTLP path) |
| **agentgateway** (Rust v1.3.0) | Yes (GenAI semconv, config-file path) | Yes (OTel built-in + Prometheus `:15020`/`:9092`) | Real if Agent scrapes its pod | Option B: per-pod disable Agent Prometheus scrape; keep OTel |
| **Istio** (ambient) | Yes (Telemetry API; inert without waypoint) | Yes (ztunnel Prometheus + optional Telemetry-API OTLP) | Low today (OTel side not wired) | Option D: pick one, default Prometheus-only |
| **ArgoCD** (Go) | Yes (trace exporter, gRPC only) | No (Prometheus-only for metrics; no OTLP metrics) | None | Option C: accept the single Prometheus path |
| **Kyverno** (Go) | Yes (native OTLP, metrics+traces) | Yes (OpenMetrics `:8000` + native `otelConfig=grpc`) | Real if both enabled | Option B: choose native OTLP, exclude `:8000` (or inverse) |
| **Backstage** (Node.js) | No (SDK must be added) | No (emits nothing today) | None | Option D: no action; not dual-signal |
| **cert-manager** (Go) | No (Prometheus-only) | No (single Prometheus path) | None | Option C: accept the single Prometheus path |
| **OTel Collector self-telemetry** | Prometheus `:8888` | Conditionally (`:8888` scrape + self-pipe) | Low today | Option B: scrape `:8888` once, do not self-pipe |

---

## Q1. Per-component OTel export configuration (point each built-in OTLP exporter at the Collector)

**Target endpoint (as stated in issue #17 / this question):** `http://otel-collector.observability.svc.cluster.local` (gRPC 4317, HTTP 4318).

**Port note (HTTP vs gRPC).** The issue states the endpoint as `:4318` (HTTP). The per-component examples below standardize on `:4317` (gRPC) because five of the seven components (agentgateway, ArgoCD, Kyverno, plus Istio's gRPC provider variant, with kagent set explicitly) support only or default to gRPC for OTLP, and the Collector exposes both 4317 and 4318 (confirmed from `gitops/apps/otel-collector.yaml`: OTLP receivers on both ports). Components that prefer HTTP (Backstage's Node SDK, and the Python SDK if configured for `http/protobuf`) may use `:4318`. The protocol choice is per-component; the Service-name/namespace reconciliation below is the load-bearing question, not the port.

**Endpoint-name discrepancy (verify-at-build).** The question's stated endpoint uses Service `otel-collector` in namespace `observability`. The repo manifests today point at a different Service name and namespace: `agent/gateway/agentgateway.yaml` sets `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector-opentelemetry-collector.monitoring.svc.cluster.local:4317`, and `research/30` cites the Collector as `otel-collector...monitoring.svc:4317`. The actual in-cluster Collector Service name (chart-generated: `otel-collector-opentelemetry-collector`) and namespace (`monitoring` per current manifests, vs `observability` in the issue text) MUST be reconciled to one value before wiring any component below. All endpoint literals in this answer use the question's `otel-collector.observability.svc.cluster.local` form; substitute the real resolved Service/namespace at build. This is a naming reconciliation, not a protocol question.

### Scope correction (read first)

The question's component list asserts seven components "with built-in OTel." Two of those assertions are wrong against current (2026) official docs and the settled `research/30` synthesis, and one is heavily caveated:

- **cert-manager (Go): NO native OTLP exporter.** cert-manager emits Prometheus only (`/metrics` on `:9402`, `certmanager_*`). It has no `traceparent`, no OTLP exporter, no `enable-tracing` flag. The only way its telemetry reaches the Collector is the Datadog Agent prometheusScrape (which is ON per the locked decision) or the Collector's Prometheus receiver. cert-manager does NOT belong in a "point its built-in OTLP exporter at the Collector" list. ([cert-manager Prometheus metrics](https://cert-manager.io/docs/devops-tips/prometheus-metrics/); [Datadog cert-manager integration](https://docs.datadoghq.com/integrations/cert-manager/); `research/30` section 7.)
- **ArgoCD (Go): built-in OTLP tracing exists, but it is gRPC-only and not GenAI-semconv.** ArgoCD's metrics are Prometheus; its OTLP path is the `--otlp-*` tracing exporter (internal ArgoCD operation spans), not `gen_ai.*`. It is a legitimate built-in OTLP exporter and is documented below. (`research/30` section 1 classified ArgoCD as "Prometheus only" for metrics; the built-in trace exporter is a separate, real capability.)
- **agentgateway / Istio / Kyverno / Backstage / kagent (ADK)** do have built-in OTLP trace export and are the substantive answers.

Skipped per instructions (Prometheus-only, handled by the Datadog Agent `prometheusScrape`): ESO, Falco, Falcosidekick. cert-manager joins this Prometheus-only group in practice (see above).

### Per-component subsections

#### 1. kagent / Google ADK (Python)

- **Configuration mechanism:** kagent Helm value `otel.tracing.enabled: true` (off by default) plus the standard OTel SDK environment variables on the agent pod. The exporter is the upstream OTel Python SDK driven by `OTEL_*` env vars; ADK at or above 1.17.0 emits GenAI semconv natively, and kagent v0.9.9 bundles `google-adk>=1.28.1` (locked, M2 Decision Log 2026-06-23).
- **Exact value/format:**
  ```yaml
  # kagent Helm values
  otel:
    tracing:
      enabled: true
  # agent pod env (deployment.env)
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://otel-collector.observability.svc.cluster.local:4317"
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: "grpc"            # or "http/protobuf" for 4318
  - name: OTEL_SEMCONV_STABILITY_OPT_IN
    value: "gen_ai_latest_experimental"   # Datadog needs semconv v1.37+
  - name: OTEL_RESOURCE_ATTRIBUTES
    value: "service.name=kagent,service.version=v0.9.9,deployment.environment.name=production"
  ```
  (UST values are pre-locked in the M1 Decision Log; do not re-decide.)
- **Protocol:** both. OTel Python SDK supports gRPC (4317, used when `OTEL_EXPORTER_OTLP_PROTOCOL=grpc`) and HTTP/protobuf (4318). The spec default for `OTEL_EXPORTER_OTLP_PROTOCOL` is SDK-dependent ("typically either `http/protobuf` or `grpc`"), not guaranteed gRPC, so set it explicitly rather than relying on a default. ([OTLP exporter SDK config](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/))
- **W3C TraceContext:** `traceparent` is the OTel SDK default propagator, and ADK "automatically passes trace context across process boundaries" via the `traceparent` header. Default, no extra config. ([Instrument ADK with OpenTelemetry, Google Cloud](https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk))
- **Auth/headers:** none for the in-cluster Collector (plaintext OTLP, no API key on the SDK to Collector hop; the Datadog API key lives on the Collector's exporter, not here).
- **Verification:** the `invoke_agent` -> `call_llm` -> `execute_tool {gen_ai.tool.name}` span waterfall with `gen_ai.request.model` and `gen_ai.usage.input_tokens`/`output_tokens` arriving at the Collector; surfaces in Datadog Agent Observability (the rebranded LLM Observability). Confirm in the Collector's own debug/`zpages` or the Agent-Obs traces UI. (`research/28`, `research/30` section 9.)

#### 2. agentgateway (Rust, OSS standalone v1.3.0)

- **Configuration mechanism:** config-file key `frontendPolicies.tracing.otlpEndpoint` in the agentgateway config YAML (the `config.yaml` ConfigMap mounted at `/etc/agentgateway/config.yaml`). The OSS standalone docs document the config-file path; they do NOT document the `OTEL_EXPORTER_OTLP_ENDPOINT` env var (that env var is documented only for the Kubernetes/Helm deployment path, not the standalone binary the repo runs). The repo currently sets the endpoint via the env var only, which is likely inert for the standalone path. ([agentgateway standalone OpenTelemetry doc](https://agentgateway.dev/docs/standalone/main/integrations/observability/opentelemetry/); `research/29` Q2, `research/30` section 10.)
- **Exact value/format:**
  ```yaml
  # /etc/agentgateway/config.yaml (the agentgateway-config ConfigMap)
  frontendPolicies:
    tracing:
      otlpEndpoint: http://otel-collector.observability.svc.cluster.local:4317
      randomSampling: true     # capture all traces for the demo
  ```
- **Protocol:** gRPC (4317) per the standalone docs ("The OTLP gRPC endpoint, e.g. http://localhost:4317"). HTTP/4318 is NOT documented for the standalone OTLP exporter. Prometheus metrics are a separate `/metrics` surface, not OTLP.
- **W3C TraceContext:** not stated in the standalone observability doc. agentgateway emits GenAI-semconv spans; whether it injects/propagates `traceparent` downstream to the kagent A2A backend is verify-at-build. (`research/30` section 10 already flags full `gen_ai.*` enrichment for the kagent A2A/JSON-RPC backend as verify-at-build.)
- **Auth/headers:** none documented for the OTLP endpoint in the standalone path.
- **Verification:** an MCP/LLM span (a second, independent witness to the rogue `execute_tool` call, alongside the agent's own span) arriving at the Collector with `gen_ai.request.model` / `gen_ai.usage.input_tokens`. Confirm the config-file path is honored (not the env var) by checking a trace actually appears after moving the endpoint into `frontendPolicies.tracing`. **verify-at-build** (config-file vs env-var path is the load-bearing correction from `research/29`).

#### 3. Istio (ambient, Envoy OTel provider, 1.30.1)

- **Configuration mechanism:** two pieces. (a) `meshConfig.extensionProviders[]` of type `opentelemetry` (set via the istiod Helm `meshConfig`, i.e. `gitops/apps/istio.yaml` istiod values, or the mesh-config app under `security/istio`). (b) a `Telemetry` API resource (`telemetry.istio.io/v1`) selecting that provider and setting the sampling rate.
- **Exact value/format:**
  ```yaml
  # istiod meshConfig (extensionProviders)
  meshConfig:
    enableTracing: true
    extensionProviders:
    - name: otel-tracing
      opentelemetry:
        service: otel-collector.observability.svc.cluster.local
        port: 4317
        resource_detectors:
          environment: {}
  ---
  # Telemetry resource
  apiVersion: telemetry.istio.io/v1
  kind: Telemetry
  metadata:
    name: mesh-otel
    namespace: istio-system
  spec:
    tracing:
    - providers:
      - name: otel-tracing
      randomSamplingPercentage: 100   # demo: capture all
  ```
  ([Istio OpenTelemetry tracing task](https://istio.io/latest/docs/tasks/observability/distributed-tracing/opentelemetry/))
- **Protocol:** both. gRPC on `port: 4317`; HTTP on `port: 4318` with an additional `http:` sub-field (path/headers/timeout) under the `opentelemetry` provider. Only one exporter at a time.
- **W3C TraceContext:** when the OpenTelemetry provider is used, Envoy generates `traceparent`/`tracestate` (W3C) rather than B3. The mesh-wide default propagation is otherwise B3 (`USE_B3`); the OTel provider produces W3C headers. So with this provider, `traceparent` is what flows, which is what Datadog correlation wants. ([Envoy/Istio OTel features](https://opentelemetry.io/blog/2024/new-otel-features-envoy-istio/); [Istio distributed tracing overview](https://istio.io/latest/docs/tasks/observability/distributed-tracing/overview/))
- **Auth/headers:** the HTTP provider variant supports a `headers` field; the gRPC variant as documented does not require headers for an in-cluster plaintext Collector.
- **Verification:** **ambient caveat (load-bearing).** This stack runs ambient with no waypoints and no sidecars (`gitops/apps/istio.yaml`, profile `ambient`). ztunnel handles L4 only and does not generate L7 distributed-trace spans; Istio distributed tracing requires a waypoint proxy (the L7 processing layer) per namespace. So with the current sidecarless/waypointless topology, the Telemetry tracing config produces nothing until a waypoint is deployed. The ztunnel-is-L4-only / waypoint-is-L7 split is from the Istio ambient data-plane docs; the Datadog Istio integration doc corroborates the L4-vs-L7 metric split. The agent's own GenAI spans come from the OTel SDK directly, not the mesh, so the observability headline does not depend on Istio traces. **verify-at-build:** if mesh L7 traces are wanted, deploy a waypoint; otherwise Istio tracing config is inert in ambient. ([Istio ambient data plane](https://istio.io/latest/docs/ambient/architecture/data-plane/); [Datadog Istio integration](https://docs.datadoghq.com/integrations/istio/))

#### 4. ArgoCD (Go), built-in OTLP trace exporter

- **Configuration mechanism:** the `--otlp-*` flags on each ArgoCD component (argocd-server, argocd-repo-server, argocd-application-controller), most cleanly set via the `argocd-cmd-params-cm` ConfigMap keys (`otlp.address`, `otlp.insecure`, `otlp.headers`, `otlp.attrs`) or per-component env vars (`ARGOCD_SERVER_OTLP_ADDRESS`, `ARGOCD_APPLICATION_CONTROLLER_OTLP_ADDRESS`, `ARGOCD_REPO_SERVER_OTLP_ADDRESS`). In this repo ArgoCD is configured via `gitops/argocd/values.yaml` (`configs.params` maps to `argocd-cmd-params-cm`).
- **Exact value/format:**
  ```yaml
  # argocd-cmd-params-cm  (configs.params in gitops/argocd/values.yaml)
  otlp.address: "otel-collector.observability.svc.cluster.local:4317"
  otlp.insecure: "true"
  # optional extra headers / attrs:
  # otlp.headers: "key1=value1,key2=value2"
  # otlp.attrs: "key:value"
  ```
  Flag form: `--otlp-address otel-collector.observability.svc.cluster.local:4317 --otlp-insecure`. ([argocd-application-controller command reference](https://argo-cd.readthedocs.io/en/stable/operator-manual/server-commands/argocd-application-controller/); [argocd-server command reference](https://argo-cd.readthedocs.io/en/latest/operator-manual/server-commands/argocd-server/))
- **Protocol:** gRPC only. `--otlp-address` is the OTLP/gRPC exporter; address format is bare `host:port` (no scheme), port 4317. No documented HTTP/4318 variant for the built-in exporter. ([oneuptime ArgoCD distributed tracing](https://oneuptime.com/blog/post/2026-02-26-argocd-distributed-tracing/view))
- **W3C TraceContext:** uses the OTel Go SDK exporter; `traceparent` is the SDK default. Not explicitly documented by ArgoCD; treat as SDK-default W3C.
- **Auth/headers:** none required for an in-cluster plaintext Collector (`otlp.insecure: "true"`); `otlp.headers` available if needed.
- **Verification:** ArgoCD operation spans (app reconcile/sync, repo-server git/manifest, gRPC) arriving at the Collector. ArgoCD is a CNCF-wall toggle component (drift beat) but its metrics (`argocd_app_*`) are the demo-relevant signal via the Datadog ArgoCD integration + OOTB dashboard, NOT these internal traces; wiring the trace exporter is optional. **verify-at-build:** GitHub issue argoproj/argo-cd#25735 reports cases where `--otlp-address` does not enable tracing as expected; confirm spans actually flow on the pinned chart (argo-cd 9.x / ArgoCD 3.2+). ([argo-cd#25735](https://github.com/argoproj/argo-cd/issues/25735))

#### 5. Kyverno (Go)

- **Configuration mechanism:** Helm value `tracing.enabled` is NOT the OTLP switch; the OTLP switch is `otelConfig` (a top-level container flag exposed as a Helm value): set `otelConfig: grpc` (default `prometheus`) plus `otelCollector` (collector service address, default `opentelemetrycollector.kyverno.svc.cluster.local`) and `metricsPort` (the port Kyverno connects to on that collector). Both metrics AND traces are exported to the same OTLP/gRPC endpoint when `otelConfig=grpc`.
- **Exact value/format:**
  ```yaml
  # Kyverno Helm valuesObject (each controller honors these)
  otelConfig: grpc
  otelCollector: otel-collector.observability.svc.cluster.local
  metricsPort: 4317        # Kyverno dials the collector on this port; align to the OTLP gRPC port
  # secure variant: transportCreds: <secret-name-with-ca.pem>
  ```
  Kyverno's docs example uses port 8000 for a Kyverno-namespace collector; point `otelCollector`+`metricsPort` at the shared Collector's gRPC port (4317). ([Kyverno OpenTelemetry monitoring doc](https://kyverno.io/docs/monitoring/opentelemetry/); [Kyverno monitoring](https://kyverno.io/docs/monitoring/))
- **Protocol:** gRPC only (`otelConfig=grpc`). No documented HTTP/4318 OTLP option; the alternative is Prometheus (`otelConfig=prometheus`). Kyverno is the stack's only platform component with native OTLP for both metrics and traces.
- **W3C TraceContext:** not documented by Kyverno; OTel Go SDK default is `traceparent`. Treat as SDK-default W3C.
- **Auth/headers:** none for plaintext; TLS via `transportCreds` (a Secret containing `ca.pem`) for a secure collector. No bearer/API-key headers documented.
- **Verification:** `kyverno_policy_results_total` / `kyverno_admission_requests_total` metrics and policy-decision traces arriving at the Collector via OTLP. Kyverno is center-stage (Audit -> Enforce, Beat 1); the native-OTLP path keeps policy traces in the same span tree. **verify-at-build:** confirm `otelConfig=grpc` exports against chart 3.8.1 and that flipping it off Prometheus does not break the Datadog Kyverno integration (which uses the OpenMetrics `/metrics:8000` path). ([Datadog Kyverno integration](https://docs.datadoghq.com/integrations/kyverno/))

#### 6. Backstage (Node.js)

- **Configuration mechanism:** there is no built-in OTLP exporter; Backstage emits nothing until the OTel Node SDK is wired into the backend. Once the SDK is added (`@opentelemetry/sdk-node`, `@opentelemetry/auto-instrumentations-node`, `@opentelemetry/exporter-trace-otlp-http` or `-grpc`), the exporter is configured by the standard `OTEL_*` env vars (the `instrumentation.js` reads them; no need to hardcode the endpoint). Per the locked custom-app pattern (Decision Log 2026-06-24), Backstage is a future Node.js app that follows OTel-API-in-image + Operator-injected-SDK; alternatively the SDK is baked into the custom image (`images/watch-it-burn-backstage/`).
- **Exact value/format:**
  ```yaml
  # backstage pod env (Helm extraEnvVars in gitops/apps/backstage.yaml)
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://otel-collector.observability.svc.cluster.local:4318"   # Node OTLP-HTTP default
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: "http/protobuf"      # or "grpc" for 4317
  - name: OTEL_RESOURCE_ATTRIBUTES
    value: "service.name=backstage,service.version=<chart-app-version>,deployment.environment.name=production"
  ```
  The Backstage tutorial's `instrumentation.js` default is `OTLPTraceExporter` -> `localhost:4318/v1/traces` (HTTP). ([Backstage Setup OpenTelemetry](https://backstage.io/docs/tutorials/setup-opentelemetry/); [OTLP exporter SDK config](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/))
- **Protocol:** both, selected by SDK exporter package / `OTEL_EXPORTER_OTLP_PROTOCOL`. The tutorial defaults to HTTP/protobuf (4318).
- **W3C TraceContext:** OTel JS SDK default propagator is W3C `traceparent` (+ `baggage`). Default, no config.
- **Auth/headers:** none for the in-cluster Collector; `OTEL_EXPORTER_OTLP_HEADERS` available if a header is ever needed.
- **Verification:** generic HTTP-server/process spans (Express/HTTP auto-instrumentation), NOT GenAI semconv (Backstage is the developer portal, not an LLM component). **verify-at-build:** the scaffolded image currently has no SDK wired, so it emits nothing until the SDK is added; Backstage is a BUILD-SPEC nice-to-have/background component, so this exporter may stay unwired. (`research/30` section 8.)

#### 7. cert-manager (Go)

Listed in issue #17's seven-component set, so addressed field-by-field rather than dropped. The conclusion is that cert-manager has no native OTLP exporter (Prometheus-only), so each field resolves to n/a. Treated symmetrically with ArgoCD above, which received the same field-by-field rehabilitation.

- **Configuration mechanism:** n/a, no native OTLP exporter. cert-manager exposes Prometheus metrics on `/metrics:9402` (`certmanager_*`) and has no `enable-tracing` flag, no OTLP exporter, no `--otlp-*` style config. Capture is via the Datadog Agent `prometheusScrape` (locked ON) or a Collector Prometheus receiver. ([cert-manager Prometheus metrics](https://cert-manager.io/docs/devops-tips/prometheus-metrics/))
- **Exact value/format:** n/a, no OTLP endpoint to set. The only telemetry surface is `/metrics` on `:9402`.
- **Protocol:** n/a, no OTLP. Prometheus scrape only.
- **W3C TraceContext:** n/a, cert-manager emits no traces, no `traceparent`.
- **Auth/headers:** n/a.
- **Verification:** `certmanager_*` metrics arriving via the Agent prometheusScrape path (apply the `rename_labels` `name`->`cert_name` mapping to avoid a tag collision, `research/30` row 7); there are no OTLP spans to verify. ([Datadog cert-manager integration](https://docs.datadoghq.com/integrations/cert-manager/); `research/30` section 7.)

### Q1 summary table

| Component | Built-in OTLP? | Mechanism (key) | Exact endpoint value | Protocol | W3C `traceparent` | Auth/headers | Verify confirmation |
|---|---|---|---|---|---|---|---|
| **kagent / ADK** (Python) | Yes (native, GenAI semconv) | Helm `otel.tracing.enabled: true` + `OTEL_EXPORTER_OTLP_ENDPOINT` env | `http://otel-collector.observability.svc.cluster.local:4317` | both (grpc default / http via `OTEL_EXPORTER_OTLP_PROTOCOL`) | default (ADK propagates `traceparent`) | none (in-cluster plaintext) | `invoke_agent->call_llm->execute_tool` waterfall with `gen_ai.*` at Collector |
| **agentgateway** (Rust v1.3.0) | Yes (GenAI semconv) | config-file `frontendPolicies.tracing.otlpEndpoint` (NOT the env var) | `http://otel-collector.observability.svc.cluster.local:4317` | gRPC 4317 only (docs) | not documented, **verify-at-build** | none documented | second `gen_ai.*` witness span on MCP/LLM traffic |
| **Istio** (ambient, Envoy OTel) | Yes (Telemetry API) | `meshConfig.extensionProviders[].opentelemetry` + `Telemetry` CR | service `otel-collector.observability.svc.cluster.local`, `port: 4317` | both (4317 grpc / 4318 http) | W3C when OTel provider used (Envoy emits `traceparent`) | `headers` field on HTTP variant | **ztunnel emits no traces; needs a waypoint**, inert in current sidecarless/waypointless topology |
| **ArgoCD** (Go) | Yes (trace exporter) | `argocd-cmd-params-cm` `otlp.address`/`otlp.insecure` (or `--otlp-*` flags) | `otel-collector.observability.svc.cluster.local:4317` (bare host:port) | gRPC only | SDK default (W3C) | none (`otlp.insecure: true`); `otlp.headers` optional | ArgoCD op spans at Collector; metrics path is the demo signal, traces optional (argo-cd#25735 verify) |
| **Kyverno** (Go) | Yes (native OTLP, metrics+traces) | Helm `otelConfig: grpc` + `otelCollector` + `metricsPort` | `otelCollector: otel-collector.observability.svc.cluster.local`, port 4317 | gRPC only | SDK default (W3C) | none plaintext; TLS via `transportCreds` (`ca.pem` Secret) | `kyverno_*` metrics + policy traces at Collector |
| **Backstage** (Node.js) | No (SDK must be added) | OTel Node SDK in backend, configured by `OTEL_*` env | `http://otel-collector.observability.svc.cluster.local:4318` | both (http default 4318) | JS SDK default (W3C) | none; `OTEL_EXPORTER_OTLP_HEADERS` optional | generic HTTP/process spans (not GenAI); unwired today |
| **cert-manager** (Go) | **No** (Prometheus-only) | n/a, no OTLP exporter; captured via Datadog Agent `prometheusScrape` / Collector Prometheus receiver | n/a (`/metrics:9402`) | n/a | n/a | n/a | `certmanager_*` metrics only; NOT an OTLP component |

### Q1 cross-cutting notes for the build

- **The Datadog API key is NOT on any of these exporters.** Every component above ships OTLP to the in-cluster Collector in plaintext; the Datadog API key lives only on the Collector's `datadog` exporter. None of these components need auth headers for the Collector hop.
- **gRPC is the common denominator.** kagent, agentgateway, Istio, ArgoCD, and Kyverno all do gRPC/4317; only Istio and the Node/Python SDKs (kagent, Backstage) also do HTTP/4318. Standardizing every component on 4317 minimizes per-component protocol drift.
- **UST is already locked.** For kagent/agentgateway/guard-proxy/evil-mcp-shim do not re-decide `service.name`/`service.version`/`deployment.environment.name` (M1 Decision Log 2026-06-23). For platform components (ArgoCD, Kyverno, Istio, Backstage, cert-manager) use the component's natural lowercase name as `service.name` and its real software version as `service.version`.
- **Two components are effectively no-ops to "wire" today:** Istio (no waypoint -> ztunnel emits no traces) and Backstage (no SDK in the scaffolded image). Both are background; wiring them is optional and gated by the M5 wire-or-skip conversation.

---

## Q2. OTel + Prometheus deduplication strategy

**Scope of this answer:** the seven dual-signal candidate components named in the question (agentgateway, Istio, ArgoCD, Kyverno, Backstage, cert-manager, OTel Collector self-telemetry). For each: (Step 1) is the Prometheus data the SAME data as the OTel data (double-count / double-bill risk) or COMPLEMENTARY; (Step 2) if same data, the recommended remedy.

### Locked context this answer is built on (do not reopen)

- Datadog Agent installs via the Datadog Operator (DatadogAgent CR, `spec.features.*`). `spec.features.prometheusScrape.enabled: TRUE` is locked ON because cert-manager, ESO, Falco, and Falcosidekick are Prometheus-only and would otherwise emit nothing (meta-PRD #7 Decision Log 2026-06-24).
- `spec.features.apm.enabled: FALSE`, OTel traces reach Datadog APM through the Collector's Datadog exporter, not through the Agent's APM port (meta-PRD #7 Decision Log 2026-06-24).
- The OTel Collector is a standalone `otelcol-contrib 0.158.2` DaemonSet. Its `datadog` exporter is the primary sink on both the metrics and traces pipelines; `prometheusremotewrite` + `otlp/tempo` are the OSS fallback. The Collector's own `datadog.prometheusScrape` exporter config stays OFF (this is distinct from the Agent's `prometheusScrape` feature; meta-PRD #7 Decision Log 2026-06-23). Confirmed from `gitops/apps/otel-collector.yaml`: the Collector has OTLP receivers only (4317/4318), no Prometheus receiver block, so today it does NOT scrape any component.
- Per-component telemetry posture is locked in `research/30`: ArgoCD = Prometheus-only; cert-manager = Prometheus-only; Kyverno = both (Prometheus + native OTLP); Istio ambient = both; agentgateway = both (OTel GenAI built-in + Prometheus); Backstage = nothing until an SDK is wired.

### The Datadog billing model (grounding the "double-bill" question)

The deduplication question only matters because of how Datadog bills. Three facts decide every row below, all from current (2026) official pricing/billing docs:

1. **A custom metric is uniquely defined by metric name + tag-value combination, including the host tag.** Each distinct (name, tag-set) pair is one billable timeseries; billing is the hourly count of distinct timeseries averaged over the month. ([Custom Metrics Billing](https://docs.datadoghq.com/account_management/billing/custom_metrics/))
2. **Prometheus / OpenMetrics-scraped metrics are billed as custom metrics.** "By default, all metrics retrieved by the generic Prometheus check are considered custom metrics," and the same is true of the OpenMetrics check and the Agent's `prometheusScrape` feature. Enabling `prometheusScrape` broadly "can cause a significant increase in custom metrics, which can lead to billing implications." ([Kubernetes Prometheus and OpenMetrics metrics collection](https://docs.datadoghq.com/containers/kubernetes/prometheus/); [OpenMetrics](https://docs.datadoghq.com/integrations/openmetrics/))
3. **OTLP metrics through the Collector's Datadog exporter are billed under standard metrics billing.** The automatic OTel-to-Datadog name mapping itself "does not affect Datadog billing," but the resulting timeseries are billed like any other custom metric. ([OpenTelemetry metric mapping / OTLP ingestion](https://docs.datadoghq.com/opentelemetry/mapping/metrics_mapping/); [OTLP ingestion in the Agent](https://docs.datadoghq.com/opentelemetry/setup/otlp_ingest_in_the_agent/))

**The decisive consequence: Datadog does NOT dedup across sources.** There is no server-side merge of two timeseries that arrive from two different pipelines. Two timeseries collapse into one billable series only if they are byte-identical in both metric name and every tag, including the host tag. In this hybrid that almost never happens, because:

- The OTel path lands metrics keyed on `k8s.node.name`-derived host plus the OTel resource attributes; the Agent's `prometheusScrape` path lands them keyed on the Agent's own host/pod tags and Datadog-normalized Prometheus names. The names diverge (OTel dot-notation resource-attribute-decorated names vs the Prometheus check's `<namespace>.<metric>` rendering) and the tag sets diverge.
- Therefore two emissions of the same underlying measurement through two pipelines produce two distinct billable timeseries, not one. This refutes Option C ("accept both, Datadog dedups, no billing impact") as a general remedy. Option C is only safe when a component is single-signal (one pipeline) to begin with.

**APM/traces billing** is separate: ingested-span volume (GB, 15-minute live window) plus indexed-span count (retention filters, 1M/host default). ([APM Billing](https://docs.datadoghq.com/account_management/billing/apm_tracing_profiler/)). Span double-counting would only occur if the same span were exported to Datadog twice. In this stack every trace travels exactly one path (app OTLP -> Collector -> Datadog exporter), so there is no trace double-count for any component. The trace column is "complementary / single-path" everywhere below; the live question is metrics.

### Per-component classification + recommended action

| # | Component | Prometheus in this stack? | OTel in this stack? | Same data or complementary? | Double-bill risk today | Recommended action |
|---|---|---|---|---|---|---|
| 1 | **agentgateway** | Yes (`:15020` + `:9092`, `research/30` row 10 / `research/18`) | Yes (native GenAI-semconv traces + OTel metrics via `frontendPolicies.tracing.otlpEndpoint`) | **Potentially same** for request/throughput counters if both the Agent scrapes its Prometheus port AND its OTel metrics flow to the Collector | Real, if `prometheusScrape` autodiscovers its pod | **Option B (per-component disable Prometheus scrape for this pod).** Center-stage component; its value is the OTel GenAI trace + metric path through the Collector. Do not let the Agent's `prometheusScrape` also pick up its `:15020/:9092` Prometheus endpoints. Exclude via autodiscovery (omit the scrape annotation / scope `prometheusScrape` away from this pod). Keep the OTel path. |
| 2 | **Istio (ambient, ztunnel)** | Yes (ztunnel L4 Prometheus; L7 only with a waypoint) | Optionally (OTel via Telemetry API; not wired today, and ztunnel emits no traces) | **Same data** if you ever enable both the Telemetry-API OTel export and a Prometheus scrape of the same `istio_tcp_*` series | Low today (OTel side not wired; Agent autodiscovery does not auto-detect ambient anyway, `research/30` row 5) | **Option D: pick one path, default to Prometheus-only via the Agent.** Istio is background (the workshop value is SPIFFE/mTLS identity, not mesh L7). Scrape ztunnel L4 with the Agent's `istio` check configured manually (`istio_mode: ambient`), and do NOT also enable Telemetry-API OTLP for the same metrics. One signal, no dedup problem. ([Datadog Istio integration](https://docs.datadoghq.com/integrations/istio/)) |
| 3 | **ArgoCD** | Yes (`:8082/:8083/:8084`, Prometheus-only; no native OTel) | **No** (no OTLP emission) | **Complementary by absence**, there is only one signal | **None** | **Option C (accept the single Prometheus path).** ArgoCD is single-signal. Let the Agent's `prometheusScrape` (or the named `argocd` check) collect it. No dedup decision exists because there is no OTel emission to collide with. ([Datadog ArgoCD integration](https://docs.datadoghq.com/integrations/argocd/)) |
| 4 | **Kyverno** | Yes (OpenMetrics `:8000`) | Yes (native `otelConfig=grpc` pushes metrics and traces to the Collector) | **Same data** for the metrics if both the Prometheus `:8000` endpoint is scraped AND `otelConfig=grpc` exports the same `kyverno_*` counters | Real, only if both are enabled at once | **Option B (choose the native OTLP path; do not also scrape `:8000`).** Kyverno is the one platform component with native OTLP. Enabling `otelConfig=grpc` to the in-cluster Collector puts Kyverno metrics and policy-decision traces in the same span tree (a nice-to-have per `observability-priorities.md`). When that path is on, exclude Kyverno's `:8000` Prometheus port from the Agent's `prometheusScrape` so the same counters are not billed twice. If `otelConfig=grpc` is left OFF (the conservative default), the inverse holds: scrape `:8000` only. Never both. ([Kyverno monitoring](https://kyverno.io/docs/monitoring/); [Datadog Kyverno integration](https://docs.datadoghq.com/integrations/kyverno/)) |
| 5 | **Backstage** | **No** (emits nothing by default) | **No** until an OTel SDK is wired into the backend | **Neither**, no data on either path today | **None** | **Option D: no action; not dual-signal.** Backstage is a BUILD-SPEC nice-to-have that currently emits zero telemetry (`research/30` row 8). There is nothing to dedup. If it is ever instrumented, it would emit generic HTTP/process OTel semconv (not GenAI) on a single OTLP path; there is no Prometheus competitor, so it stays single-signal. ([Backstage OTel setup](https://backstage.io/docs/tutorials/setup-opentelemetry/)) |
| 6 | **cert-manager** | Yes (`:9402`, Prometheus-only; no native OTLP) | **No** | **Complementary by absence**, single signal | **None** | **Option C (accept the single Prometheus path).** This is exactly why `spec.features.prometheusScrape.enabled` is locked ON: cert-manager has no other way in. Use the named `cert_manager` check (or `prometheusScrape`) and apply the `rename_labels` `name`->`cert_name` mapping to avoid a tag collision (`research/30` row 7). No OTel emission means no double-count. ([Datadog cert-manager integration](https://docs.datadoghq.com/integrations/cert-manager/)) |
| 7 | **OTel Collector self-telemetry** | Yes (Prometheus `:8888`, set in `otel-collector.yaml` `service.telemetry.metrics.address: 0.0.0.0:8888`) | The Collector's own internal metrics are Prometheus-format on `:8888`; they are NOT re-emitted through its own OTLP pipeline | **Same data** only if the Agent's `prometheusScrape` scrapes `:8888` AND you also configure the Collector to self-export its internal metrics through the `datadog` exporter | Low today (the Collector is not configured to push its own internal telemetry to the Datadog exporter; `:8888` is the only path) | **Option B / single-path: scrape `:8888` once, do not also self-pipe.** Pick the Agent's `prometheusScrape` of `:8888` as the single source of Collector health metrics (queue length, dropped spans, exporter failures, memory_limiter activity). Do NOT additionally route the Collector's internal `service.telemetry` metrics into its own `datadog` exporter, which would create a second copy under different names/tags. Collector self-telemetry is operationally important (it is how you see the Collector dropping data on the day), so keep exactly one path, not zero. |

### Reasoning summary (why these and not the alternatives)

**Three of the seven are not actually dual-signal in this stack** (ArgoCD, cert-manager are Prometheus-only; Backstage emits nothing), so for them the question collapses to "leave the single path alone." That is Option C/D with no risk. The locked `prometheusScrape: true` exists precisely to serve the Prometheus-only set, and these ride that decision correctly.

**The genuine double-bill candidates are the components that can emit the same metric on two paths at once:** agentgateway, Kyverno, Istio, and (conditionally) the Collector's own `:8888`. For all four, the recommended remedy is per-component path selection (Option B / Option D pick-one), not a Collector-level drop and not "accept both."

**Why not Option A (Collector-level drop) anywhere:** Option A suppresses a Prometheus scrape inside the Collector pipeline. It is inapplicable here because the Collector has no Prometheus receiver in `otel-collector.yaml` today. The competing Prometheus scrape, when it exists, is the Datadog Agent's `prometheusScrape` feature, not a Collector scrape. You cannot drop in the Collector something the Collector never ingested. The lever that actually exists is Datadog Agent autodiscovery scoping (exclude a pod/port from `prometheusScrape`), which is Option B.

**Why not Option C as a default for the dual-emit four:** Option C assumes Datadog merges duplicate timeseries. It does not. Custom-metric uniqueness is (name + tags + host); the OTel path and the Agent `prometheusScrape` path produce different names and different host/pod tags for the same underlying measurement, so they bill as two timeseries. With roughly 60 to 70 per-attendee trial orgs, an avoidable doubling of a component's timeseries multiplies across every org. Option C is reserved for the genuinely single-signal components (rows 3, 5, 6).

**Net rule for M5 Decision 4:** keep `spec.features.prometheusScrape.enabled: true` (locked) but scope it so it does not scrape the Prometheus ports of any component that also reaches Datadog via the OTel Collector. Concretely: exclude agentgateway (`:15020`/`:9092`) and, if `otelConfig=grpc` is enabled, Kyverno (`:8000`) from Agent autodiscovery; choose one path for Istio ztunnel L4 (default Prometheus) and one path for Collector `:8888` (default Prometheus). cert-manager, ArgoCD, ESO, Falco, Falcosidekick stay on the Agent's Prometheus path because that is their only path. No traces double-count anywhere because every span travels a single OTLP -> Collector -> Datadog route.

### Q2 adversarial validation note (2026-06-24)

Independent skeptical re-check of the load-bearing, time-sensitive claims against current (2026) official primary sources.

| # | Claim | Verdict | Source |
|---|---|---|---|
| 1 | A custom metric = metric name + tag-value combination (incl. host tag); billed as monthly-averaged distinct-timeseries count | **CONFIRMED** | [docs.datadoghq.com/account_management/billing/custom_metrics/](https://docs.datadoghq.com/account_management/billing/custom_metrics/) |
| 2 | Prometheus/OpenMetrics-scraped metrics (incl. the Agent `prometheusScrape` feature) are billed as custom metrics; broad scraping inflates the bill | **CONFIRMED** | [docs.datadoghq.com/containers/kubernetes/prometheus/](https://docs.datadoghq.com/containers/kubernetes/prometheus/); [docs.datadoghq.com/integrations/openmetrics/](https://docs.datadoghq.com/integrations/openmetrics/) |
| 3 | OTLP metrics via the Collector's Datadog exporter are billed under standard metrics billing; the auto-mapping step itself does not add charges | **CONFIRMED** | [docs.datadoghq.com/opentelemetry/mapping/metrics_mapping/](https://docs.datadoghq.com/opentelemetry/mapping/metrics_mapping/); [docs.datadoghq.com/opentelemetry/setup/otlp_ingest_in_the_agent/](https://docs.datadoghq.com/opentelemetry/setup/otlp_ingest_in_the_agent/) |
| 4 | Datadog does NOT merge two timeseries from two sources unless name + every tag (incl. host) are identical; i.e. no cross-source dedup | **CONFIRMED by inference from the uniqueness definition** (claim 1). The custom-metrics doc defines uniqueness solely by (name, tag values); it documents no cross-source merge. No doc claims duplicate-source collapse. This is the basis for refuting Option C as a general remedy. | [docs.datadoghq.com/account_management/billing/custom_metrics/](https://docs.datadoghq.com/account_management/billing/custom_metrics/) |
| 5 | APM is billed on ingested-span GB (15-min live) + indexed-span count (retention filters); separate from custom metrics | **CONFIRMED** | [docs.datadoghq.com/account_management/billing/apm_tracing_profiler/](https://docs.datadoghq.com/account_management/billing/apm_tracing_profiler/) |
| 6 | The OTel Collector in this stack has no Prometheus receiver (OTLP receivers 4317/4318 only); `service.telemetry.metrics.address: 0.0.0.0:8888` exposes Collector self-metrics in Prometheus format | **CONFIRMED from source** (`gitops/apps/otel-collector.yaml`, read this session) | in-repo |
| 7 | Per-component signal posture (ArgoCD Prom-only, cert-manager Prom-only, Kyverno both incl. native OTLP, Istio ambient both, agentgateway both, Backstage nothing) | **CONFIRMED** (carried from `research/30`, itself re-verified against integration docs 2026-06-23) | `research/30`; [docs.datadoghq.com/integrations/kyverno/](https://docs.datadoghq.com/integrations/kyverno/); [docs.datadoghq.com/integrations/istio/](https://docs.datadoghq.com/integrations/istio/) |

**One nuance flagged, not a refutation:** Datadog's published OTel-to-Datadog metric name mapping examples (e.g. `apache.cpu.load` -> `apache.performance.cpu_load`) apply to Datadog's integration receivers, not to the generic OTLP receiver path our apps use. For generic OTLP, OTel metric names are preserved with light normalization, so they will not coincidentally equal the Datadog Agent's Prometheus-check rendering of the same component's metric. This strengthens (does not weaken) the "no accidental dedup" conclusion: the names diverge, so the two paths bill separately. The precise generic-OTLP name rendering is best confirmed live.

---

## Q3. Datadog LLM Observability ("Agent Observability") UI activation

**Scope:** What makes the LLM Observability product UI appear (the nav entry, token/cost widgets, model-breakdown tables, the LLM trace list) for the Watch-It-Burn stack, given research/28 already confirmed `gen_ai.*` OTLP spans flow to Datadog and correlate. This spike answers the activation question only; it does not re-derive the ingestion path (research/28) or the per-component telemetry (research/30).

**Builds on (NOT re-researched):** research/28 (native `gen_ai.*` OTLP ingest at semconv v1.37+, three ingestion paths, the `dd-otlp-source=llmobs` header, the Collector -> LLM-Obs routing gap, the product rename to "Agent Observability"), research/30 (kagent/ADK emits `invoke_agent -> call_llm -> execute_tool` with `gen_ai.usage.*` / `gen_ai.request.model`), the M1 UST lock (`service.name` per component, `deployment.environment.name=production`), and the locked decisions (Datadog Operator + `spec.features.apm.enabled: false`; OTel traces reach Datadog via Collector -> `datadog` exporter).

### Q3 TL;DR per sub-question

| # | Sub-question | Verdict |
|---|---|---|
| a | Org feature flag / product trial / plan tier to make the UI appear? | **No documented org feature flag or manual "Enable" toggle.** The UI populates automatically once a span with `ml_app` arrives. A supported (commercial, non-GovCloud) site is the only hard gate; plan tier (Free vs Pro) affects span volume/retention, not whether the UI appears. **verify-at-build** on the live trial org. |
| b | A `DatadogAgent` CR key (e.g. `spec.features.llmObservability.enabled: true`) required? | **No.** There is no `spec.features.llmObservability` key in the DatadogAgent CR for this OTLP path. Our stack does not route LLM-Obs through the Agent at all (Collector -> `datadog` exporter). `spec.features.apm.enabled: false` is correct and does not affect LLM-Obs. |
| c | An OTel Collector exporter setting that routes `gen_ai.*` to LLM-Obs vs generic APM? | **This is the one real gap (same as research/28 Q7).** The documented deterministic control is the `dd-otlp-source=llmobs` header on a direct OTLP export, which the contrib `datadog` exporter does not emit. Whether `gen_ai.*` through the contrib `datadog` exporter auto-populates LLM-Obs is not documented. **verify-at-build**, with a documented header-based fallback. |
| d | A required resource attribute / `ddtags` value on the span (`ml_app`, `dd.llmobs.*`)? | **`ml_app` is load-bearing but auto-derived.** On the OTLP path, `ml_app` is automatically set to the root span's `service` attribute (i.e. our locked UST `service.name`). No `dd.llmobs.*` tags are required. The `dd-ml-app` header is an optional override. |
| e | Minimum span shape for the LLM trace list to render a row | **`gen_ai.operation.name` is the load-bearing attribute**: it maps to the Agent-Obs `span.kind`. With a recognized value (`chat`/`generate_content`/`execute_tool`/`invoke_agent`/...) plus `service.name` (-> `ml_app`) and semconv v1.37+ shape, the span renders. No mandated span name or OTel SpanKind; classification is driven by `gen_ai.operation.name`, not the span name. |

### (a) Org-level feature flag, product trial enrollment, or plan-tier requirement?

**No documented org-level feature flag, and no manual "Enable LLM Observability" toggle, gates the UI for the OTLP path.** Across the LLM-Obs instrumentation doc, the launch blog, and the setup/quickstart pages, the only hard requirement stated for ingest is a Datadog API key plus a supported site; the traces "automatically appear in the Agent Observability Traces page." There is no "turn on the product" org switch documented for getting OTLP `gen_ai.*` data to land. ([OTel instrumentation doc](https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/); [LLM OTel semconv blog](https://www.datadoghq.com/blog/llm-otel-semantic-convention/))

What does gate it:

- **Site.** LLM Observability is not supported on GovCloud sites `app.ddog-gov.com` and `us2.ddog-gov.com`. The workshop's `DD_SITE=datadoghq.com` (US1, hardcoded in `gitops/apps/otel-collector.yaml`, locked in the M1 Decision Log 2026-06-23) is a supported commercial site, so this gate is satisfied. ([OTel instrumentation doc](https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/))
- **Plan tier exists but does not gate UI appearance.** Datadog documents a Free tier ("for individuals and smaller teams getting started with tracing, experiments, evals, and prompt iteration") and a Pro tier ("for teams running in production with additional LLM span volume... and retention add-ons"). The tier affects span volume and retention, not whether the nav entry / trace list appears. ([Agent Observability product page](https://www.datadoghq.com/products/ai/agent-observability/))
- **In-app onboarding flow exists but is optional.** Datadog offers an "in-app onboarding flow for an interactive quickstart experience." It is a guided setup, not a prerequisite switch; it walks you through SDK instrumentation for the dd-trace path, which is not our path. ([LLM-Obs instrumentation landing](https://docs.datadoghq.com/llm_observability/instrumentation/))

**verify-at-build (live org only):** Whether a brand-new trial org surfaces the "Agent Observability" / "LLM Observability" left-nav entry before the first span arrives, or only after, is a live-UI behavior the docs do not pin down. The safe assumption is "send one valid span, then look." Confirm on the actual trial org during Milestone 2. This is the same class of UI-confirmation gate research/28 and research/30 already flag.

### (b) Is a `DatadogAgent` CR key (e.g. `spec.features.llmObservability.enabled: true`) required?

**No. There is no `spec.features.llmObservability` key required for this stack's path, and none is documented as the activation mechanism for OTLP-delivered `gen_ai.*` spans.**

- The activation controls Datadog documents are per-application, not per-Agent: SDK env vars (`DD_LLMOBS_ENABLED=1`, `DD_LLMOBS_ML_APP=<name>`) for the dd-trace SDK path, or the `dd-otlp-source=llmobs` header for the OTLP path. Neither is a DatadogAgent CR `spec.features.*` toggle. ([OTel instrumentation doc](https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/))
- This stack does not route LLM-Obs through the Datadog Agent at all. Per the locked architecture, the AI layer emits OTLP into the standalone `otelcol-contrib 0.158.2` Collector, whose `datadog` exporter is the sink (`gitops/apps/otel-collector.yaml`; meta-PRD locked decisions). The Datadog Agent (Operator-installed) handles EKS infra/logs, not traces.
- The locked `spec.features.apm.enabled: false` (meta-PRD Decision Log 2026-06-24) is therefore correct and orthogonal: that flag opens the Agent's port 8126 for dd-trace-format traces, which no app here uses. It does not affect OTel/OTLP trace ingestion, the APM UI, or LLM Observability. Confirmed by research/28: the LLM-Obs / APM ingestion is the Collector -> `datadog` exporter path, independent of the Agent's APM feature.

**Net:** do not add any `spec.features.llmObservability.*` key to the DatadogAgent CR. None exists for this path; activation is span-driven, not Agent-config-driven.

### (c) An OTel Collector exporter setting that routes `gen_ai.*` to LLM-Obs vs generic APM traces?

**This is the single genuine activation gap, and it is the same one research/28 Q7 flagged. It is NOT closed by new sources.**

- The only documented deterministic routing control is the `dd-otlp-source=llmobs` header on a direct OTLP export to Datadog's OTLP intake endpoint:
  ```
  OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf
  OTEL_EXPORTER_OTLP_TRACES_HEADERS=dd-api-key=<KEY>,dd-otlp-source=llmobs
  ```
  This header is what tells Datadog "treat these as LLM Observability traces." ([OTel instrumentation doc](https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/))
- The repo's Collector uses the contrib `datadog` exporter (verified in `gitops/apps/otel-collector.yaml`: a `datadog` exporter on both the metrics and traces pipelines, reading `DD_API_KEY`/`DD_SITE` from `datadog-secret`). The contrib `datadog` exporter has no documented `dd-otlp-source` / LLM-Obs option; it targets Datadog's APM trace intake. The doc page for OTLP instrumentation details only the direct-OTLP header path; it gives no Collector exporter config for LLM-Obs.
- The launch blog asserts the Collector path works ("export OTel GenAI spans via your existing OTel Collector pipeline... analyze GenAI spans directly in LLM Observability, with no code changes required") and notes the Collector lets you "apply processors for redaction, sampling, enrichment, and routing... before telemetry data leaves your network," but it gives no exporter-level config showing how a `gen_ai.*` span sent through the contrib `datadog` exporter is classified into LLM-Obs vs plain APM. ([LLM OTel semconv blog](https://www.datadoghq.com/blog/llm-otel-semantic-convention/))

**verify-at-build (live stack only), resolution order:**
1. Once the AI layer emits `gen_ai.*` v1.37 spans through the existing Collector `datadog` exporter, watch the Agent Observability Traces page (not just APM Traces) on the live trial org and confirm the `invoke_agent -> call_llm -> execute_tool` waterfall renders. If it appears with no extra config, done.
2. If it does not appear, add the documented header path: a dedicated OTLP exporter in the Collector pointed at Datadog's OTLP intake endpoint with `dd-otlp-source=llmobs` (and `dd-api-key`) in the headers, sending the AI-layer spans down that exporter. This is the header-deterministic fallback and preserves the Datadog-additive principle (the OSS `prometheusremotewrite` + `otlp/tempo` exporters stay intact).
3. Either way, keep the OTel Collector's `datadog.prometheusScrape` exporter config OFF (meta-PRD 2026-06-23 entry), unrelated to LLM-Obs but a standing Collector-side requirement.

### (d) Required resource attribute / `ddtags` value (`ml_app`, `dd.llmobs.*`)?

**`ml_app` is the load-bearing grouping tag, but on the OTLP path it is auto-derived; no `dd.llmobs.*` span tags are required.**

- **`ml_app` is auto-set from `service.name`.** Datadog's OTLP doc: "use the `ml_app` attribute, which is automatically set to the value of your OpenTelemetry root span's `service` attribute." The mapping is `resource.attributes.service.name` -> `ml_app` (and `tags.service`). So `ml_app` is populated from the locked UST `service.name` (M1 Decision Log: `guard-proxy`, `agentgateway`, `kagent`, `evil-mcp-shim`). No separate `ml_app` attribute needs to be set on the spans. ([OTel instrumentation doc](https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/))
- **`dd-ml-app` header is an optional override.** The OpenLLMetry example in the doc sets it explicitly:
  ```python
  headers={
      "dd-api-key": "<YOUR_DATADOG_API_KEY>",
      "dd-ml-app": "simple-openllmetry-test",
      "dd-otlp-source": "llmobs",
  }
  ```
  Set `dd-ml-app` only when you want the application grouping to differ from `service.name`. For this stack, relying on `service.name` is the simpler, already-locked choice; an explicit `dd-ml-app` would only be needed if all AI-layer spans should group under one `ml_app` (e.g. `watch-it-burn-agent`) rather than per-service. That is a deliberate UX choice for Milestone 2, not a requirement. ([OTel instrumentation doc](https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/))
- **No `dd.llmobs.*` resource attributes are required** for OTLP-native ingest. The SDK-path env vars (`DD_LLMOBS_ENABLED`, `DD_LLMOBS_ML_APP`) are dd-trace-specific and do not apply to our pure-OTLP path. ([LLM-Obs instrumentation landing](https://docs.datadoghq.com/llm_observability/instrumentation/))

**Precision on `ml_app` (the historically load-bearing tag):** if `service.name` is missing or inconsistent on the AI-layer root span, `ml_app` will be empty or fragmented and the trace list grouping/search breaks. UST `service.name` is already locked in M1 for all four AI-layer components, so this is satisfied by design, but it makes getting UST `service.name` onto the root span a hard prerequisite for the LLM-Obs UI, not just for the Service Map. Confirm the AI-layer root span (the agent's `invoke_agent`) carries `service.name=kagent` at build.

### (e) Minimum span shape for the LLM trace list to render a row

**The load-bearing attribute is `gen_ai.operation.name`. It determines the Agent-Obs `span.kind`, which is what classifies a span into the LLM trace list. There is no mandated span name or OTel SpanKind.**

Datadog's documented mapping (verbatim from the [OTLP instrumentation doc](https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/)):

| `gen_ai.operation.name` | Agent Observability `span.kind` |
|---|---|
| `generate_content`, `chat`, `text_completion`, `completion` | `llm` |
| `embeddings`, `embedding` | `embedding` |
| `execute_tool` | `tool` |
| `invoke_agent`, `create_agent` | `agent` |
| `rerank`, `unknown`, *(default)* | `workflow` |

Attribute mapping into the LLM-Obs schema (verbatim):

- `gen_ai.operation.name` -> `meta.span.kind`
- `gen_ai.provider.name` -> `meta.model_provider`
- `gen_ai.response.model` (preferred) or `gen_ai.request.model` (fallback when `response.model` is absent) -> `meta.model_name`
- `gen_ai.usage.input_tokens` -> `metrics.input_tokens`
- `gen_ai.usage.output_tokens` -> `metrics.output_tokens`
- `gen_ai.usage.prompt_tokens` -> `metrics.prompt_tokens`
- `gen_ai.usage.completion_tokens` -> `metrics.completion_tokens`

**Minimum to render a row in the LLM trace list:**
1. **Reach LLM-Obs at all**, the span must be routed there: `dd-otlp-source=llmobs` (direct/dedicated OTLP exporter) or the Collector `datadog` exporter auto-routing (sub-question c, verify-at-build).
2. **`service.name` on the root span**, auto-derives `ml_app` (sub-question d). Without it the trace cannot be grouped/searched.
3. **`gen_ai.operation.name` with a recognized value**, classifies the span kind. A value not in the table falls through to `workflow` (still renders, but as a generic workflow span, not as an `llm`/`tool`/`agent` row). This is the single attribute that most directly governs whether the row shows up as the right kind of LLM span.
4. **semconv v1.37+ shape**, Datadog's native mapping is pinned to "OpenTelemetry 1.37+ semantic conventions for generative AI"; set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` on emitters defaulting to older specs (research/28 Q3).

**What is NOT required:** a specific span name string (the OTel form `invoke_agent {gen_ai.agent.name}` etc. is a name convention, but classification is driven by `gen_ai.operation.name`, not the name) and a specific OTel `SpanKind` (CLIENT/SERVER/INTERNAL). Token/cost widgets and model-breakdown tables populate from `gen_ai.usage.*` and `gen_ai.request.model`, which research/30 confirmed kagent/ADK emits natively, so those widgets are data-driven, not separately activated.

**For this stack specifically:** kagent/ADK emits `invoke_agent` (-> `agent`), `call_llm`/`chat` (-> `llm`), and `execute_tool` (-> `tool`) with `gen_ai.request.model` and `gen_ai.usage.*` (research/28 Q6, research/30). That set already satisfies (2) to (4) for the agent waterfall, the model-breakdown table, and the token/cost widgets. The only thing left to prove is (1), the routing into LLM-Obs (sub-question c).

### Q3 cross-cutting build notes (carry into Milestone 2)

- **No DatadogAgent CR change** for LLM-Obs. `spec.features.apm.enabled: false` stays; do not invent a `spec.features.llmObservability` key.
- **`ml_app` rides on locked UST `service.name`**, confirm `service.name=kagent` lands on the agent root span. This makes LLM-Obs grouping a second reason UST must be correct (the first is the Service Map).
- **The activation work is span shape + routing**, not an org switch: (i) emit `gen_ai.*` v1.37 spans with a recognized `gen_ai.operation.name`, (ii) opt into latest semconv, (iii) ensure the Collector -> LLM-Obs hop routes those spans (verify live; `dd-otlp-source=llmobs` dedicated OTLP exporter as the deterministic fallback).
- **Site is fine**, US1 `datadoghq.com` is supported.

### Q3 could-not-fully-resolve (explicitly flagged)

1. **Collector (contrib `datadog` exporter) -> LLM-Obs auto-routing** (sub-question c). No reachable doc states whether `gen_ai.*` spans through the contrib `datadog` exporter auto-populate LLM Observability or require the `dd-otlp-source=llmobs` header path. **verify-at-build** on the live trial org; documented fallback is a dedicated OTLP exporter with the header. (Same gap as research/28 Q7; not closed by new sources.)
2. **Whether the LLM-Obs nav entry appears on a fresh trial org before the first span** (sub-question a). UI behavior not pinned in docs; **verify-at-build**.

### Q3 validation pass (adversarial, 2026-06-24)

Independent skeptical re-check of the load-bearing, time-sensitive claims against current (2026) official Datadog primary sources. In-repo facts (`gitops/apps/otel-collector.yaml` contents, locked decisions) were read directly this session.

| Claim | Verdict | Source checked |
|---|---|---|
| No documented org feature flag / manual "Enable" toggle gates the OTLP LLM-Obs path; UI populates on data arrival | **CONFIRMED** (doc states traces "automatically appear in the Agent Observability Traces page"; no org switch documented) | https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ |
| GovCloud sites `app.ddog-gov.com` / `us2.ddog-gov.com` unsupported; commercial sites OK | **CONFIRMED** (verbatim unsupported-site list) | https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ |
| Free vs Pro tier affects volume/retention, not UI appearance | **CONFIRMED** (tier descriptions; no UI-gating language) | https://www.datadoghq.com/products/ai/agent-observability/ |
| No `spec.features.llmObservability` DatadogAgent CR key; activation is span/header-driven, not Agent-config-driven; `apm.enabled:false` orthogonal | **CONFIRMED** (activation controls documented are per-app env vars `DD_LLMOBS_ENABLED`/`DD_LLMOBS_ML_APP` for SDK path and `dd-otlp-source=llmobs` header for OTLP path; no Agent CR toggle) | https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ ; https://docs.datadoghq.com/llm_observability/instrumentation/ |
| `ml_app` auto-set from root span `service.name` (`resource.attributes.service.name` -> `ml_app`/`tags.service`) | **CONFIRMED** (verbatim) | https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ |
| `dd-ml-app` header is an optional override (OpenLLMetry example) | **CONFIRMED** (verbatim headers dict with `dd-ml-app`) | https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ |
| `gen_ai.operation.name` -> `span.kind` mapping table (`chat`/`generate_content`->`llm`, `execute_tool`->`tool`, `invoke_agent`/`create_agent`->`agent`, default->`workflow`) | **CONFIRMED** (verbatim table) | https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ |
| `gen_ai.*` attribute -> LLM-Obs schema mapping (model name/provider, input/output/prompt/completion tokens); `meta.model_name` maps from `gen_ai.response.model` (preferred) or `gen_ai.request.model` (fallback) | **CONFIRMED** (verbatim mapping list; draft corrected this pass to show both source attributes, response preferred) | https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ |
| Collector path asserted to work but no exporter-level LLM-Obs routing config documented (the gap) | **CONFIRMED as a gap** (blog asserts Collector path + redaction/routing processors; no contrib `datadog` exporter LLM-Obs option documented) | https://www.datadoghq.com/blog/llm-otel-semantic-convention/ ; https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ |

**Net:** every load-bearing documented claim CONFIRMED. Two items remain genuinely doc-unresolvable and are flagged verify-at-build (Collector exporter routing; fresh-org nav appearance). The historically load-bearing `ml_app` tag is satisfied for this stack by the already-locked UST `service.name`, provided it lands on the agent root span.

---

## Q4. APM path confirmation with `spec.features.apm.enabled: false`

**Verdict: GO. `spec.features.apm.enabled: false` is SAFE for this stack.** OTel traces sent through the OTel Collector's `datadog` exporter reach Datadog APM (Traces UI and Service Map) over a path that does not touch the Datadog Agent at all. The Agent's `apm` feature governs only the Agent pod's own local trace intake (the dd-trace socket / port 8126, and the Agent's OTLP ingest), which no component in this stack uses. The one capability genuinely lost is the Datadog Continuous Profiler, and that loss is caused by OTel-SDK instrumentation, not by the `apm` flag, so flipping `apm.enabled` to `true` would not recover it. APM trace metrics (`trace.*`) are produced by the `datadog/connector` on the Collector side, independent of the Agent APM intake.

### What `spec.features.apm.enabled` actually controls (sub-question 3)

`spec.features.apm.enabled` on the DatadogAgent CR turns on the Agent pod's local trace-agent / APM intake. Enabling it makes the Agent create and listen on the trace socket (documented default `/var/run/datadog/apm.socket`, configurable via `features.apm.unixDomainSocketConfig.path`) and, with `hostPort: 8126`, the TCP dd-trace intake port 8126, so that application tracing libraries running on the node submit traces to the local Agent ([Kubernetes APM, docs.datadoghq.com](https://docs.datadoghq.com/containers/kubernetes/apm/)). The exact socket path is non-load-bearing here: no app in the stack uses the Agent-local intake at all. It is "strictly about the Agent accepting traces locally from containerized applications," separate from how telemetry is forwarded onward to the Datadog backend. The Agent's separate OTLP ingest receiver (gRPC 4317 / HTTP 4318 on the Agent pod) is governed by `spec.features.otlp.receiver.protocols`, and when OTLP ingest is enabled metrics and traces are enabled by default ([OTLP Ingestion by the Datadog Agent](https://docs.datadoghq.com/opentelemetry/setup/otlp_ingest_in_the_agent/); [Configure the Datadog Operator](https://docs.datadoghq.com/containers/datadog_operator/configuration/)).

So `apm.enabled: false` disables ONLY the Agent-pod-local trace intake (the dd-trace socket / 8126 path, and Agent-side APM stats on that intake). It does not disable anything on the Collector. This stack instruments apps with the OTel SDK (Operator-injected) and exports via the standalone `otelcol-contrib 0.158.2` Collector's `datadog` exporter straight to the Datadog backend API. No app in the stack sends dd-trace to a local Agent, so the Agent APM intake would sit idle if enabled. The decision-log rationale ("opening an unused port adds overhead without benefit") is correct.

### Do traces appear in the APM Traces UI? (sub-question 1)

Yes. The "OpenTelemetry Collector with Datadog Exporter" is a documented, supported, standalone path that does NOT require the Datadog Agent, offering "complete vendor neutrality for sending OpenTelemetry data to Datadog" ([OpenTelemetry in Datadog](https://docs.datadoghq.com/opentelemetry/)). The contrib `datadog` exporter sends traces to Datadog APM; research/28 already established (and the repo Collector config confirms) that this exporter maps to APM intake. Traces ingested this way land on the APM Traces page on attribute/resource detection; this is the same path research/28 Q7 flags as the verify-at-build seam for whether `gen_ai.*` spans ALSO surface in Agent Observability (LLM Obs), but plain APM trace visibility on the Collector path is the documented default.

### Do they appear in the Service Map? (sub-question 2)

Yes. The Service Map is built from APM span data and renders for the OTel-SDK + OSS-Collector path: "go to APM > Catalog and select Map to see how the services are connected" ([Datadog and OpenTelemetry Compatibility](https://docs.datadoghq.com/opentelemetry/compatibility/)). The map is independent of `apm.enabled` on the Agent. Note the separate prerequisite already tracked elsewhere in PRD #7 (research/23 Decision 8, M6): the pure-OTel Service Map infers edges from `peer.service` and correct span kinds, so the map's completeness depends on UST + `peer.service` + span-kind correctness, not on the Agent APM flag. M6 already owns live-verifying the full map renders on the pure-OTLP path; that is a UST/span-shape gate, not an `apm.enabled` gate.

### APM trace metrics and the `datadog/connector` (the connector covers it without Agent APM)

The repo added `datadog/connector` to the Collector (decision log 2026-06-23) precisely for APM trace metrics (`trace.*`). This is correct and sufficient on the Collector side:

- Since OTel Collector contrib v0.95.0, the `datadog` exporter no longer computes APM Trace Metrics by default; that computation moved to the `datadog` connector ([Migrate to OpenTelemetry Collector 0.95.0+](https://docs.datadoghq.com/opentelemetry/migrate/collector_0_95_0/); [datadogexporter README](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/exporter/datadogexporter/README.md): "The Datadog Exporter now skips APM stats computation by default. It is recommended to only use the Datadog Connector in order to compute APM stats.").
- "To send APM stats such as hits, errors, and duration, set up the Datadog Connector" ([Trace Metrics](https://docs.datadoghq.com/opentelemetry/integrations/trace_metrics/)). The connector generates the `trace.*` hits/errors/duration metrics. Wiring: add `datadog/connector` to the traces pipeline `exporters` and to the metrics pipeline `receivers`, alongside the existing `spanmetrics` connector. The exact key nesting is `connectors.datadog/connector.traces.compute_stats_by_span_kind: true`, confirmed verbatim against the connector README ([datadogconnector README](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/connector/datadogconnector/README.md)). Matches the repo's locked wiring intent.
- `compute_stats_by_span_kind` enables APM stats based on `span.kind` (server/consumer/client/producer); Datadog recommends enabling it especially when working with peer tags ([Trace Metrics](https://docs.datadoghq.com/opentelemetry/integrations/trace_metrics/)).

None of this requires the Agent's APM intake: the connector runs inside the Collector and the metrics ship via the `datadog` exporter. The Agent APM stats computation (on the Agent's local 8126/UDS intake) is a parallel, unused mechanism here.

### Q4 per-feature breakdown: what needs `apm.enabled: true`?

| APM feature | Available on Collector -> datadog exporter path with `apm.enabled: false`? | Source / note |
|---|---|---|
| APM Traces UI (`/apm/traces`) | YES | OTel Collector + datadog exporter is a standalone supported path, no Agent required ([OpenTelemetry in Datadog](https://docs.datadoghq.com/opentelemetry/)) |
| Service Map (`/apm/map`) | YES | APM > Catalog > Map renders for OTel SDK + OSS Collector ([Compatibility](https://docs.datadoghq.com/opentelemetry/compatibility/)); completeness gated by `peer.service`/span-kind (research/23 D8, M6), not by the Agent flag |
| APM trace metrics (`trace.*`, hits/errors/duration) | YES, via `datadog/connector` on the Collector | Connector computes APM stats since contrib v0.95.0; not the Agent ([Trace Metrics](https://docs.datadoghq.com/opentelemetry/integrations/trace_metrics/), [Migrate 0.95.0+](https://docs.datadoghq.com/opentelemetry/migrate/collector_0_95_0/)) |
| Tail-based sampling | YES, Collector-side | Listed as a Collector-path capability ("flexible configuration options like tail-based sampling") ([OpenTelemetry in Datadog](https://docs.datadoghq.com/opentelemetry/)); a Collector processor, unrelated to Agent APM |
| Runtime metrics | YES, via OTel SDK MeterProvider -> Collector -> datadog exporter | OTel collects compatible runtime metrics sent through the OTel SDKs; available on the OSS Collector path ([Runtime Metrics](https://docs.datadoghq.com/opentelemetry/integrations/runtime_metrics/), [Compatibility](https://docs.datadoghq.com/opentelemetry/compatibility/)). Requires a configured MeterProvider + metric exporter on the apps; not the Agent APM flag |
| Log-trace correlation ("View related logs" / "View Trace in APM") | YES (separately gated) | Supported on OSS Collector path ("Correlated Traces, Metrics, Logs"); the real prerequisite is matching UST + trace_id/span_id injection (research/19, M6), not the Agent APM flag |
| Continuous Profiler correlation | NO, and `apm.enabled: true` would NOT fix it | OTel-SDK-instrumented apps cannot use Datadog proprietary products including Continuous Profiler ([Compatibility](https://docs.datadoghq.com/opentelemetry/compatibility/)). The loss is from OTel-SDK instrumentation, not the Agent APM flag, so it is not a reason to enable `apm` |

**Conclusion: GO.** Nothing this stack needs requires `spec.features.apm.enabled: true`. APM Traces UI, Service Map, APM trace metrics (`trace.*`), tail-based sampling, runtime metrics, and log-trace correlation all work on the OTel Collector -> `datadog` exporter path with the Agent APM intake disabled. The `datadog/connector` on the Collector covers APM trace metrics without the Agent. The only feature gated off (Continuous Profiler correlation) is gated by the choice of OTel-SDK instrumentation, not by the `apm` flag, so enabling `apm` would buy nothing while opening an idle intake. The locked decision stands.

**Residual gate to keep visible (not an `apm.enabled` risk):** whether `gen_ai.*` spans on the Collector `datadog`-exporter path auto-surface in Datadog Agent Observability / LLM Observability (vs only plain APM) is the same verify-at-build seam already flagged in research/28 Q7 (fallback: a dedicated OTLP exporter with the `dd-otlp-source=llmobs` header). That seam is about LLM-Obs routing, NOT about plain APM/Service-Map visibility, and it is unaffected by `apm.enabled`. The Service-Map edge-completeness prerequisite (`peer.service` + span kinds, research/23 D8) is M6 scope and likewise independent of the Agent APM flag.

---

## Consolidated verify-at-build list

These items are resolvable only by running the live stack. Carry them into the relevant milestone.

**Q1 (per-component OTel export):**
1. Reconcile the Collector Service name + namespace: the question says `otel-collector.observability.svc.cluster.local`, but `agentgateway.yaml` and `research/30` use `otel-collector-opentelemetry-collector.monitoring.svc.cluster.local:4317`. Confirm the actual chart-generated Service name and namespace on the live cluster before substituting into any component config.
2. agentgateway v1.3.0: confirm the config-file path `frontendPolicies.tracing.otlpEndpoint` is honored (NOT the `OTEL_EXPORTER_OTLP_ENDPOINT` env var the repo currently sets) on the OSS standalone binary, and that it injects/propagates W3C `traceparent` downstream to the kagent A2A (JSON-RPC) backend so spans correlate.
3. Istio ambient: confirm that with NO waypoint deployed (current sidecarless topology), the Telemetry tracing config produces zero spans (ztunnel is L4-only, emits no traces). If mesh L7 traces are wanted, a per-namespace waypoint must be deployed first.
4. ArgoCD: confirm `--otlp-address` / `otlp.address` actually enables trace export on the pinned argo-cd 9.x chart (argoproj/argo-cd#25735 reports cases where it silently does not), and that spans reach the Collector over gRPC.
5. kagent chart 0.9.9: confirm the pod honors `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` and `OTEL_EXPORTER_OTLP_PROTOCOL`, and that `otel.tracing.enabled` + `OTEL_EXPORTER_OTLP_ENDPOINT` together route `gen_ai.*` spans to the Collector.
6. Kyverno chart 3.8.1: confirm `otelConfig=grpc` + `otelCollector` + `metricsPort` export both metrics and traces to the shared Collector on 4317, and that turning off the Prometheus path does not break the Datadog Kyverno OpenMetrics integration (port 8000).
7. Backstage: the scaffolded image currently has no OTel SDK; confirm whether Backstage telemetry is in scope at all (BUILD-SPEC nice-to-have) before adding the SDK or Operator injection.
8. cert-manager: confirm it is captured purely via the Datadog Agent `prometheusScrape` (ON) or the Collector Prometheus receiver; it has no OTLP exporter to point anywhere.

**Q2 (dedup):**
9. Confirm the Datadog Agent's `prometheusScrape` autodiscovery actually picks up agentgateway (`:15020`/`:9092`), Kyverno (`:8000`), Istio ztunnel, and the OTel Collector (`:8888`) on the live cluster, so the exclusions in this plan target the pods/ports really being scraped (`enableServiceEndpoints` can scrape more than expected).
10. Confirm the exact rendered Datadog metric NAMES and TAG SETS for a dual-emit component (e.g. agentgateway) on both paths (OTel Collector Datadog exporter vs Agent `prometheusScrape`) to prove they are distinct timeseries (and therefore double-billed if both run). Inspect the Metrics Summary for series cardinality with one path vs both.
11. Decide and confirm whether Kyverno's `otelConfig=grpc` is enabled. The dedup remedy flips on this: if ON, exclude `:8000` from the Agent; if OFF, scrape `:8000` only. This is an open M5 wire-or-skip call.
12. Confirm the per-pod exclusion mechanism for `spec.features.prometheusScrape` in the DatadogAgent Operator CR (annotation-based opt-out vs `additionalConfigs` autodiscovery rules) removes a pod/port from scraping without disabling `prometheusScrape` globally (which must stay ON for cert-manager/ESO/Falco/Falcosidekick).
13. Confirm host-tag divergence in practice: that OTel-path metrics (keyed via `k8s.node.name` / `cluster.name=watch-it-burn` upsert) and Agent `prometheusScrape` metrics for the same component carry different host tags, since identical host tags + identical names are the only condition under which the two would collapse to one billable series.
14. Confirm whether the OTel Collector's own internal `service.telemetry` metrics (`:8888`) are routed anywhere besides the `:8888` Prometheus endpoint; ensure they are not additionally self-piped through the `datadog` exporter, which would double-count Collector health metrics.

**Q3 (LLM-Obs activation):**
15. Collector contrib `datadog` exporter -> LLM-Obs auto-routing: confirm whether `gen_ai.*` spans sent through the existing Collector `datadog` exporter auto-populate the Agent Observability Traces page, or require a dedicated OTLP exporter with the `dd-otlp-source=llmobs` header. Watch the live trial org's LLM-Obs Traces page for the `invoke_agent -> call_llm -> execute_tool` waterfall; fall back to the header path if absent.
16. Fresh-org nav appearance: confirm whether the "Agent Observability" / "LLM Observability" left-nav entry appears on a brand-new trial org before vs only after the first `ml_app`-bearing span arrives.
17. `ml_app` population: confirm the agent root span (`invoke_agent`) actually carries UST `service.name=kagent` on the live cluster, so `ml_app` is non-empty and the trace list groups/searches correctly.
18. `gen_ai.operation.name` values: capture a live kagent/ADK trace and confirm the emitted `gen_ai.operation.name` values are recognized table values (e.g. `chat`/`generate_content` for the model span, `execute_tool`, `invoke_agent`) rather than falling through to the `workflow` default.
19. Trial-org plan tier: confirm the per-attendee trial org's tier (Free/Pro) provides sufficient LLM span volume/retention for the workshop run; this affects data persistence, not UI appearance.

**Q4 (APM with `apm.enabled: false`):**
20. Live-verify in the Datadog APM UI (`/apm/traces`) that traces exported via the Collector `datadog` exporter appear with `apm.enabled:false` on the DatadogAgent CR (the documented default; confirm no Agent-side dependency in practice).
21. Live-verify the Service Map (`/apm/map`, APM > Catalog > Map) renders the guard-proxy -> agentgateway -> kagent -> Bedrock edges from the pure-OTLP path; this depends on `peer.service` + correct span kinds (research/23 D8, M6 scope), not on `apm.enabled`.
22. Verify the `datadog/connector` is wired into the live Collector config (traces-pipeline exporter + metrics-pipeline receiver, `compute_stats_by_span_kind:true`) and that `trace.*` APM trace metrics appear in Datadog with `apm.enabled:false`; the live `otel-collector.yaml` currently shows only the `spanmetrics` connector, so the `datadog/connector` add is a pending build item.

---

## Adversarial validation

Three independent lenses re-checked this document against current (2026) official primary sources and the in-repo manifests. All three returned GO. Their findings and the material corrections applied to this final version are below.

### Lens counts (final)

| Lens | Focus | Verdict | Confirmed | Refuted | Unverified (verify-at-build) |
|---|---|---|---|---|---|
| A | Official-docs accuracy (Datadog / OTel / component docs) | GO | 18 | 0 | 2 |
| B | Config-schema / version / YAML literal correctness | GO | 9 | 0 | 2 |
| C | Completeness vs the issue #17 acceptance criteria | GO | 9 | 0 | 2 |

Totals: 36 confirmed, 0 refuted, 6 unverified. The 6 unverified items are live-stack UI/behavior checks already captured in the consolidated verify-at-build list (Collector exporter LLM-Obs routing, fresh-org nav appearance, the dual-emit billing-cardinality proof, and the connector key-path build-time confirmation); none is a doc error.

### Material corrections applied this pass

1. **Q3 model-name mapping (Lens A1, confirmed and fixed).** The draft mapped only `gen_ai.request.model -> meta.model_name`. The OTLP instrumentation doc maps `meta.model_name` from `gen_ai.response.model` (preferred) with `gen_ai.request.model` as the fallback when the response model is absent. Corrected verbatim. Verified at https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ this pass.
2. **Q1 OTLP protocol default (Lens A2, confirmed and fixed).** The draft framed gRPC as the SDK default. The SDK-configuration spec states the `OTEL_EXPORTER_OTLP_PROTOCOL` default is SDK-dependent ("typically either `http/protobuf` or `grpc`"). The kagent subsection now qualifies gRPC as "used when `OTEL_EXPORTER_OTLP_PROTOCOL=grpc`" and notes the spec default is SDK-dependent, with a recommendation to set it explicitly. Verified at https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/ this pass.
3. **Q1 Istio ztunnel/waypoint citation (Lens A3, claim confirmed, citation fixed).** The ztunnel-L4-only / waypoint-needed-for-traces claim is correct but had been leaning on the sidecar-oriented OTel tracing task page. Citation now points at the Istio ambient data-plane docs (https://istio.io/latest/docs/ambient/architecture/data-plane/) with the Datadog Istio integration doc as corroboration. The claim itself stands.
4. **Q4 APM socket path (Lens B1, confirmed and fixed).** The draft used `/var/run/datadog/apm/apm.socket`. The documented default is `/var/run/datadog/apm.socket` (no nested `apm/` directory). Corrected, and the path is now explicitly noted as non-load-bearing because no app in the stack uses the Agent-local intake. Verified at https://docs.datadoghq.com/containers/kubernetes/apm/ this pass.
5. **Q4 datadog connector key-path citation (Lens B2, confirmed and cited).** The `compute_stats_by_span_kind` key nesting is `connectors.datadog/connector.traces.compute_stats_by_span_kind: true`, now cited directly against the connector README (https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/connector/datadogconnector/README.md) and confirmed verbatim this pass. Live wiring remains verify-at-build (consolidated item 22).
6. **Q1 cert-manager six-field block (Lens C1, scope correction applied).** cert-manager is one of the seven components issue #17 lists. The draft had demoted it to a summary-table row. A full six-field subsection (#7) now resolves each field to "n/a, no native OTLP exporter" with sources, symmetric to the ArgoCD rehabilitation, so an auditor sees the component was addressed field-by-field, not silently dropped. The conclusion (Prometheus-only, no OTLP) is unchanged.
7. **Q1 endpoint port deviation (Lens C2, completeness gap closed).** Issue #17 states the target endpoint as `:4318` (HTTP); the per-component examples standardize on `:4317` (gRPC). A "Port note" now states this deviation explicitly and its rationale (five of seven components are gRPC-only or gRPC-default; the Collector exposes both ports), so the apparent port mismatch is addressed rather than silent.

### Locked decisions checked, not contradicted

The Datadog Operator install method, `spec.features.prometheusScrape.enabled: true`, `spec.features.apm.enabled: false`, the OTel Operator being deployed, the OTel-API-in-image + Operator-injected-SDK custom-app pattern, and the standalone `otelcol-contrib 0.158.2` DaemonSet with the `datadog` exporter (primary) plus `prometheusremotewrite` + `otlp/tempo` (OSS fallback) and the `spanmetrics` + `datadog/connector` connectors were all treated as inputs and none was reopened or contradicted. The Q4 verdict (GO on `apm.enabled: false`) and the Q2 conclusion (no cross-source dedup; keep `prometheusScrape` ON but scope it) reinforce the locked decisions rather than challenging them.

---

## Sources

- https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/
- https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk
- https://agentgateway.dev/docs/standalone/main/integrations/observability/opentelemetry/
- https://istio.io/latest/docs/tasks/observability/distributed-tracing/opentelemetry/
- https://istio.io/latest/docs/tasks/observability/distributed-tracing/overview/
- https://istio.io/latest/docs/ambient/architecture/data-plane/
- https://opentelemetry.io/blog/2024/new-otel-features-envoy-istio/
- https://docs.datadoghq.com/integrations/istio/
- https://argo-cd.readthedocs.io/en/stable/operator-manual/server-commands/argocd-application-controller/
- https://argo-cd.readthedocs.io/en/latest/operator-manual/server-commands/argocd-server/
- https://github.com/argoproj/argo-cd/issues/25735
- https://oneuptime.com/blog/post/2026-02-26-argocd-distributed-tracing/view
- https://kyverno.io/docs/monitoring/opentelemetry/
- https://kyverno.io/docs/monitoring/
- https://docs.datadoghq.com/integrations/kyverno/
- https://backstage.io/docs/tutorials/setup-opentelemetry/
- https://cert-manager.io/docs/devops-tips/prometheus-metrics/
- https://docs.datadoghq.com/integrations/cert-manager/
- https://docs.datadoghq.com/integrations/argocd/
- https://docs.datadoghq.com/account_management/billing/custom_metrics/
- https://docs.datadoghq.com/containers/kubernetes/prometheus/
- https://docs.datadoghq.com/integrations/openmetrics/
- https://docs.datadoghq.com/opentelemetry/mapping/metrics_mapping/
- https://docs.datadoghq.com/opentelemetry/setup/otlp_ingest_in_the_agent/
- https://docs.datadoghq.com/account_management/billing/apm_tracing_profiler/
- https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/
- https://www.datadoghq.com/blog/llm-otel-semantic-convention/
- https://www.datadoghq.com/products/ai/agent-observability/
- https://docs.datadoghq.com/llm_observability/instrumentation/
- https://docs.datadoghq.com/llm_observability/
- https://docs.datadoghq.com/opentelemetry/
- https://docs.datadoghq.com/opentelemetry/compatibility/
- https://docs.datadoghq.com/opentelemetry/integrations/trace_metrics/
- https://docs.datadoghq.com/opentelemetry/migrate/collector_0_95_0/
- https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/exporter/datadogexporter/README.md
- https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/connector/datadogconnector/README.md
- https://docs.datadoghq.com/containers/kubernetes/apm/
- https://docs.datadoghq.com/containers/datadog_operator/configuration/
- https://docs.datadoghq.com/opentelemetry/integrations/runtime_metrics/
- research/28-datadog-llm-obs-otlp-2026.md (in-repo)
- research/30-per-component-telemetry-synthesis-2026.md (in-repo)
- gitops/apps/otel-collector.yaml (in-repo)
- prds/7-observability-meta.md Decision Log (in-repo)
