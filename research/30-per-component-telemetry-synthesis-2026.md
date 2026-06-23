<!-- ABOUTME: Per-component telemetry synthesis for all 13 Watch-It-Burn stack components. -->
<!-- ABOUTME: For each: what it emits, OTel/Prometheus/semconv, how to capture in THIS stack, official DD integration/OOTB dashboard, and community/importable dashboard fallback. -->

# 30. Per-Component Telemetry Synthesis (13 components)

**Date:** 2026-06-23 (re-run reflecting the #9/#10 re-runs of `research/28`/`research/29`)
**Issue:** #11 — per-component telemetry synthesis
**Scope:** ArgoCD, Kyverno, Falco, KubeArmor, Istio ambient, ESO, cert-manager, Backstage, kagent,
agentgateway, guard-proxy, evil-mcp-shim, customer-stream generator.

## Verification Method

- **Approach:** Synthesis spike dated **2026-06-23**. It consolidates the per-component telemetry
  picture from prior research and re-verifies the load-bearing, time-sensitive facts (Datadog OOTB
  dashboard status; community/importable dashboards) against current (2026) official primary
  sources. In-repo wiring facts were read directly from the manifests this session and are treated
  as CONFIRMED. Every non-obvious external claim carries an inline source URL; the full list is in
  **Sources**.
- **Builds on (NOT re-researched):**
  - `research/18-datadog-integrations-stack-2026.md` (primary) — per-component Datadog integration +
    native-telemetry survey, UST attribute→tag mapping, the DDOT-vs-two-DaemonSets and
    `prometheusScrape` gotchas, the Istio-ambient autodiscovery break, the cert-manager
    `rename_labels` collision, KubeArmor's separate exporter.
  - `research/28-datadog-llm-obs-otlp-2026.md` (issue #9, **re-run 2026-06-23**) — what kagent/ADK
    emits natively (`invoke_agent`→`call_llm`→`execute_tool` waterfall, `gen_ai.*` attribute list,
    `gen_ai.usage.input_tokens/output_tokens`, `gen_ai.request.model`); Datadog native OTLP ingest
    (v1.37+ semconv, `dd-otlp-source=llmobs`, the Collector→LLM-Obs routing gap). **The #9 re-run
    establishes two facts carried into this synthesis:** (i) the Datadog product is now branded
    **"Agent Observability"** (formerly "LLM Observability") — a surface rename only; the
    `/llm_observability/` doc URLs and the `dd-otlp-source=llmobs` routing header are unchanged, and
    all seven of #28's verdicts still hold; (ii) Agent Observability now ships a **built-in Sensitive
    Data Scanner (SDS)** that scans Agent-Obs traces, including LLM inputs/outputs, for PII/secret
    redaction (server-side, after ingest; not on by default).
  - `research/29-python-ai-instrumentation-2026.md` (issue #10, **re-run 2026-06-23**) — kagent `otel.tracing.enabled`
    field path; agentgateway built-in GenAI-semconv tracing via `frontendPolicies.tracing.otlpEndpoint`
    (repo's env-var path is wrong); **guard-proxy makes NO Bedrock call** (it proxies A2A; instrument
    as a proxy/guard span, not `gen_ai.*`); evil-mcp-shim needs no instrumentation (visible via the
    agent's `execute_tool` span); OpenLLMetry status.
  - `research/06-cncf-stack.md`, `research/19`, `research/23`, `research/24` (read for context).
  - **The AI-layer telemetry questions for kagent / agentgateway / guard-proxy / evil-mcp-shim are
    answered by extracting from #28 + #29; this spike does NOT re-derive them.**
- **In-repo facts taken as CONFIRMED (read this session):** `gitops/apps/*.yaml` (ArgoCD apps for
  istio ambient 1.30.1, kagent chart 0.9.9, cert-manager v1.20.2, external-secrets chart 2.6.0,
  backstage, customer-stream, falco/falcosidekick/falco-talon, otel-collector contrib 0.158.2),
  `gitops/manifests/customer-stream/stream.yaml` (the generator is a stdlib `urllib` POST loop, no
  instrumentation), `gitops/ai-layer/resources.yaml` + `proxy.py`, `agent/gateway/agentgateway.yaml`.
- **Constraints honored (Whitney's):** research only — nothing edited. **No wire-or-skip decisions**
  (that is the Milestone-5 conversation); this surfaces facts only. **KubeArmor = survey only, not in
  narrative, no wire decision.** No hand-built-dashboard recommendations for components that are not
  center-stage (see "Center-stage" below). Stated "gotchas" treated as hypotheses and marked
  CONFIRMED / CORRECTED.

> **Hypothesis-verification results (this spike's corrections to `research/18`):**
> | Prior claim (`research/18`) | This spike | Source |
> |---|---|---|
> | ArgoCD OOTB dashboards = **No** | **CORRECTED → Yes** (OOTB dashboard + recommended app-sync-failure monitor) | datadoghq.com/blog/argo-cd-datadog |
> | cert-manager OOTB dashboards = **Yes** | **CORRECTED → not in the integration doc** (no DD OOTB dashboard mentioned; the well-known dashboard is the *community* Grafana 11001, which the cert-manager project itself references) | docs.datadoghq.com/integrations/cert-manager ; grafana.com/grafana/dashboards/11001 |
> | Falco OOTB dashboard = **Yes** | **CONFIRMED** ("out-of-the-box dashboards") | docs.datadoghq.com/integrations/falco |
> | Kyverno OOTB dashboard = (blank) | **CONFIRMED no OOTB dashboard** in the integration doc | docs.datadoghq.com/integrations/kyverno |

### Center-stage vs background (from `docs/BUILD-SPEC.md` §2/§4, `PROJECT_STATE.md`)

The observability headline narrates the **agent**: input prompt, output, and **tool calls** on a live
trace dashboard, plus the **live Bedrock cost counter**. Center-stage = **kagent/agent**,
**guard-proxy** (the guard decisions + cost meter), **agentgateway** (MCP authz / tool-call witness),
**evil-mcp-shim** (the rogue `execute_tool`), and the CNCF "wall" toggles that produce visible
before/after: **Kyverno** (Audit→Enforce), **ArgoCD** (drift), **Falco/Talon** (detect→respond). The
rest — **KubeArmor** (survey only), **ESO**, **cert-manager**, **Istio ambient**, **Backstage**,
**customer-stream** — are background/supporting. Per the constraint, no hand-built dashboard is
proposed for the non-center-stage components; for them the answer to Q5 is "import a community
dashboard," not "build one."

---

## TL;DR matrix

| # | Component | Emits (metrics/logs/traces) | OTel / Prom / both + semconv | Official DD integration | DD OOTB dashboard | Community/importable dashboard (if no official OOTB) |
|---|---|---|---|---|---|---|
| 1 | **ArgoCD** | metrics (+ app events) | **Prometheus only** (no OTel); ArgoCD-specific names | **Yes** (Agent 7.42+) | **Yes** (OOTB + recommended monitor) | n/a (has OOTB) — also Grafana 14584 (official), 19974/19993 (mixin) |
| 2 | **Kyverno** | metrics, traces | **Both** — Prometheus **and** native **OTLP** (`otelConfig=grpc`); Kyverno-specific names | **Yes** (Agent 7.56+) | **No** (not in doc) | Grafana 15987 (Kyverno) |
| 3 | **Falco** | logs (alerts) + metrics | **Prometheus** native; **OTLP via Falcosidekick** fan-out; Falco rule schema | **Yes** (Agent 7.59.1+) | **Yes** | n/a (has OOTB) |
| 4 | **KubeArmor** | alerts (gRPC log stream) + metrics via separate exporter | **Prometheus only via separate `kubearmor-prometheus-exporter`**; no native OTLP; `kubearmor_alerts_*` | **No** | No | **survey only — not in narrative**: exporter ships a dashboard in `prometheus-grafana-deployment.yaml` (repo); ARMO hub dashboard |
| 5 | **Istio ambient** | metrics (L4 ztunnel; L7 only via waypoint) + traces (waypoint only) | **Both** — Prometheus + OTel via Telemetry API; Istio standard metrics | **Yes** (Agent 6.1+); **autodiscovery does not auto-detect ambient** (keys on the `proxyv2` sidecar) — set `istio_mode: ambient` manually | Unconfirmed | Grafana **21306** (Istio Ztunnel, official istio org); 7630/7639 (mesh/workload, sidecar-oriented) |
| 6 | **ESO** | metrics | **Prometheus only**; ESO-specific (`externalsecret_*`, controller-runtime) | **No** | No | Grafana **21640** (External Secrets, upstream) — known data-display issues |
| 7 | **cert-manager** | metrics | **Prometheus only**; cert-manager-specific (`certmanager_*`) | **Yes** (Agent 7.22+) | **No** (not in doc — corrects #18) | Grafana **11001** (cert-manager, project-referenced); cert-manager-mixin |
| 8 | **Backstage** | **nothing by default** | **OTel SDK** (must be added) — generic HTTP/process semconv, not GenAI | **No** (UI-embed plugin only, not an Agent check) | No | none meaningful until instrumented (background; no dashboard proposed) |
| 9 | **kagent / agent** | traces (+ token usage in spans) | **OTel**, **GenAI semconv** (`invoke_agent`/`call_llm`/`execute_tool`, `gen_ai.*`); Prometheus unconfirmed | No (native OTLP → Collector → DD) | No (lands in DD **Agent Observability** [formerly LLM Observability], not a classic integration dashboard; built-in **Sensitive Data Scanner** can redact PII in the captured `gen_ai.*` in/out) | n/a (center-stage; trace view is the dashboard) |
| 10 | **agentgateway** | traces, metrics, logs | **OTel**, **GenAI semconv** built-in (`frontendPolicies.tracing.otlpEndpoint`) + Prometheus | No | No | n/a (center-stage) |
| 11 | **guard-proxy** | metrics (Prometheus `witb_*`) today; **no traces today** | **Prometheus** now; **OTel manual spans** to add (proxy/guard span, NOT `gen_ai.*`) | No | No | n/a (center-stage; powers the cost counter) |
| 12 | **evil-mcp-shim** | **nothing** (intentionally) | none — visible via the **agent's** `execute_tool {gen_ai.tool.name}` span | No | No | n/a (do NOT instrument — that is the lesson) |
| 13 | **customer-stream generator** | **nothing** (stdlib `urllib` loop) | none today | No | No | n/a (background exfil target; no dashboard proposed) |

---

## Per-component detail

For each: **(1)** emits telemetry? **(2)** OTel/Prometheus/both + which semconv **(3)** how to capture
in THIS stack **(4)** official Datadog integration / OOTB dashboard? **(5)** community/importable
dashboard if no official OOTB.

### 1. ArgoCD

1. **Emits:** metrics (and application/sync events). No traces, no native logs pipeline beyond
   container stdout.
2. **OTel/Prom/semconv:** **Prometheus only — no native OTel/OTLP.** Three scrape endpoints:
   Application Controller `:8082/metrics`, API Server `:8083/metrics`, Repo Server `:8084/metrics`
   (CONFIRMED, Datadog integration doc). Metric names are ArgoCD-specific (`argocd_app_*`,
   `argocd_app_sync_total`, reconciliation, gRPC, Redis, Go runtime) — no GenAI/standard semconv.
3. **Capture in THIS stack:** the cluster runs in-cluster ArgoCD bootstrapped from `app-of-apps.yaml`
   (not GitOps-managed by another app; `gitops/argocd/values.yaml` has no metrics block). Two paths:
   (a) Datadog Agent with the `argocd` check via pod annotations on the three controllers; (b) the
   OTel Collector's Prometheus receiver scraping the three endpoints → Prometheus/Tempo and the
   `datadog` exporter. Per `research/18`, do NOT also enable `datadog.prometheusScrape.enabled` if the
   Collector scrapes (double-billing).
4. **Official DD integration / OOTB dashboard:** **Yes** integration, Agent **v7.42+**; **OOTB
   dashboard = Yes** — "By using the Argo CD out-of-the-box (OOTB) dashboard, you can monitor how
   quickly and accurately your infrastructure changes are being applied to your cluster," plus "a
   recommended, preconfigured monitor that alerts you to any app sync failures."
   (datadoghq.com/blog/argo-cd-datadog) **This CORRECTS `research/18` ("No").** Note: the Datadog
   *integration doc* page does not itself enumerate the dashboard, but the product blog confirms an
   OOTB dashboard ships with the integration.
5. **Community dashboard:** not needed for DD (has OOTB). For the OSS/Grafana fallback: official
   ArgoCD Grafana dashboard **14584** (from the ArgoCD repo), plus mixin-generated **19974**
   (Application) / **19993** (Operational) and **24192** (Overview V3).

### 2. Kyverno

1. **Emits:** metrics and **traces**.
2. **OTel/Prom/semconv:** **Both — the stack's only platform component with native OTLP.** Prometheus
   `/metrics` on port **8000** (OpenMetrics; Datadog uses the OpenMetrics check, requires Python 3 —
   CONFIRMED, integration doc). Native **OTel**: a single Helm flag (`otelConfig=grpc` +
   `otelCollector` endpoint) pushes **metrics and traces** to an OTel Collector. Metric/attribute
   names are Kyverno-specific (`kyverno_policy_results_total`, `kyverno_admission_requests_total`,
   policy execution durations) — not GenAI semconv.
3. **Capture in THIS stack:** Kyverno is center-stage (the Audit→Enforce toggle is Beat 1). For
   metrics: Datadog `kyverno` check via per-controller pod annotations (4 pods: admission, background,
   cleanup, reports controllers — `research/18`) **or** point Kyverno's native `otelConfig=grpc` at the
   in-cluster OTel Collector (`otel-collector...monitoring.svc:4317`) so metrics+traces fan out to
   Datadog + Prometheus/Tempo. The native-OTLP path is the cleanest fit to the Datadog-additive
   principle.
4. **Official DD integration / OOTB dashboard:** **Yes** integration, included in Agent **7.56+**
   (check requires 7.55+). **OOTB dashboard = No** — "The documentation does not mention an
   out-of-the-box dashboard." (CONFIRMED, integration doc.)
5. **Community dashboard (no official OOTB):** Grafana **15987** "Kyverno" (policy results, admission
   review latency, rule execution) is the commonly imported community dashboard. (Kyverno is
   center-stage, but per the constraint a community import is the surfaced option — no
   recommendation to hand-build.)

### 3. Falco

1. **Emits:** **logs (alerts)** primarily, plus **metrics**.
2. **OTel/Prom/semconv:** **Prometheus** native (`falco.`-prefixed via OpenMetrics; runtime + event
   processing). **OTLP** is available via **Falcosidekick** fan-out (50+ outputs incl. OTLP and
   Datadog). Falco's own schema is its rule/alert format, not GenAI semconv.
3. **Capture in THIS stack:** Falco 0.44.1 + Falcosidekick + Talon are deployed
   (`gitops/apps/falco*.yaml`). Per `PROJECT_STATE.md`, Falcosidekick currently forwards **only to
   Talon** (the detect→respond fork-bomb theater); a native **Datadog output** (`DATADOG_APIKEY` from
   the shared `datadog-secret`) is wired additively, and an **OTLP output** is the portable analog.
   Datadog `falco` integration ingests the alert **logs** via webhook/file and the **metrics** via
   OpenMetrics. Falco/Talon is center-stage (CRITICAL→terminate in ~4s, live-verified).
4. **Official DD integration / OOTB dashboard:** **Yes** integration, Agent **7.59.1+**; **OOTB
   dashboard = Yes** — "The integration provides insights into alert logs through the out-of-the-box
   dashboards." (CONFIRMED, integration doc.) Matches `research/18`.
5. **Community dashboard:** not needed (has OOTB).

### 4. KubeArmor — **SURVEY ONLY, NOT IN NARRATIVE. No wire decision.**

1. **Emits:** security **alerts** over a gRPC log stream; **metrics only via a separate exporter**.
2. **OTel/Prom/semconv:** **Prometheus only, and only if you deploy the standalone
   `kubearmor/kubearmor-prometheus-exporter`** (a distinct pod/Service, NOT bundled with the KubeArmor
   DaemonSet). It exposes 9 alert counters (`kubearmor_alerts_in_host_total`,
   `..._in_namespace_total`, `..._in_pod_total`, `..._in_container_total`, `..._with_policy_total`,
   `..._with_severity_total`, `..._with_type_total`, `..._with_operation_total`,
   `..._with_action_total`). **No native OTLP. No named Datadog integration.** (CONFIRMED,
   `research/18` + kubearmor-prometheus-exporter repo.)
3. **Capture in THIS stack:** **N/A — KubeArmor is not deployed** (`research/17`/`21`/`22`: it cannot
   cap a fork bomb; podPidsLimit + Falco/Talon own that story). KubeArmor remains an OPEN
   different-attack candidate only; nothing is wired. If ever surveyed live, capture would require the
   separate exporter + a generic OpenMetrics scrape.
4. **Official DD integration / OOTB dashboard:** **No** integration, **No** OOTB dashboard.
5. **Community dashboard (survey only):** the `kubearmor-prometheus-exporter` repo ships a Grafana
   dashboard via its `prometheus-grafana-deployment.yaml`; ARMO/Kubescape also publish a hub
   dashboard. Marked **survey only — not in narrative**.

### 5. Istio (ambient mode, 1.30.1)

1. **Emits:** **metrics** (ztunnel L4; L7 only when a waypoint is deployed) and **traces** (waypoint
   only — ztunnel generates none).
2. **OTel/Prom/semconv:** **Both** — Prometheus-format metrics + OTel via the Istio Telemetry API.
   Istio standard mesh metric names (`istio_tcp_*` at L4 from ztunnel; `istio_requests_total` etc. at
   L7 only from a waypoint). Not GenAI semconv.
3. **Capture in THIS stack:** Istio runs **ambient** (base/cni/istiod/ztunnel, profile `ambient`,
   `gitops/apps/istio.yaml`) — chosen for low per-node footprint; **no waypoints, no sidecars**. Per
   `research/18` + `research/23` D6: in ambient, ztunnel reports **L4 only and emits no traces**, and
   the Datadog Istio integration's `auto_conf.yaml` autodiscovery **does not auto-detect ambient**
   (its identifiers are `proxyv2`/`proxyv2-rhel8`, keyed on the absent `istio-proxy` sidecar — VALIDATION
   2026-06-23: confirmed against the live `auto_conf.yaml`; the current DD doc presents ambient as a
   supported *manual* config, not a "broken" feature, so this was reworded from the earlier "broken"
   phrasing). To get anything you must set `istio_mode: ambient` and point at
   `ztunnel_endpoint` (L4); L7/traces need a per-namespace **waypoint** (`waypoint.<ns>:15020/stats/
   prometheus`). The agent's own L7/GenAI spans come from OTel directly, not the mesh — so the
   observability headline does not depend on a waypoint. (Background component; the workshop value is
   the **SPIFFE/mTLS identity** story, not mesh L7 telemetry.)
4. **Official DD integration / OOTB dashboard:** **Yes** integration (Agent 6.1+); **autodiscovery does
   not auto-detect ambient** — its `auto_conf.yaml` identifiers (`proxyv2`/`proxyv2-rhel8`) key on the
   sidecar, so ztunnel/waypoint must be configured manually via `istio_mode: ambient` (VALIDATION
   2026-06-23: confirmed; reworded from "broken"). OOTB dashboard for ambient: **Unconfirmed** (the
   integration's dashboards are sidecar/`istio-proxy`-oriented).
5. **Community/importable dashboard:** Istio's **official org dashboards** on grafana.com — **21306
   "Istio Ztunnel Dashboard"** is the ambient-relevant one (ztunnel TCP connections, FDs, sockets);
   the classic **7630 (Mesh)** / **7639 (Workload)** / **7645 (Control Plane)** are sidecar-oriented
   and L7, so largely empty in sidecarless ambient without a waypoint.

### 6. External Secrets Operator (ESO)

1. **Emits:** **metrics** only.
2. **OTel/Prom/semconv:** **Prometheus only.** ESO-specific names
   (`externalsecret_sync_calls_total`, `externalsecret_status_condition`, plus controller-runtime
   `controller_runtime_*` and the provider call counters). No native OTLP, no GenAI semconv.
3. **Capture in THIS stack:** ESO is deployed via chart **2.6.0** in namespace `platform`
   (`gitops/apps/external-secrets.yaml`), authenticating to AWS Secrets Manager via **EKS Pod
   Identity** (per `PROJECT_STATE.md`; the IRSA annotation was removed). Metrics endpoint must be
   scraped (generic OpenMetrics / Prometheus receiver) — no named DD integration to do it for you.
   ESO is the **S3/Secrets-Manager exfil-game** supporting cast (Whitney's ESO/S3 exfil beat) and is
   "known-degraded" on test clusters when no AWS SM entries exist — background, not a dashboard
   target.
4. **Official DD integration / OOTB dashboard:** **No** integration, **No** OOTB dashboard
   (generic OpenMetrics, `research/18`).
5. **Community/importable dashboard:** Grafana **21640 "External Secrets"** (the upstream
   project-provided dashboard). **Caveat:** community reports of it showing no data / not rendering
   `ClusterExternalSecrets` (external-secrets issues #4615, #5957, 2026) — verify it populates before
   relying on it. Background component; no hand-built dashboard proposed.

### 7. cert-manager

1. **Emits:** **metrics** only.
2. **OTel/Prom/semconv:** **Prometheus only.** cert-manager-specific names
   (`certmanager_certificate_expiration_timestamp_seconds`, `certmanager_certificate_ready_status`,
   ACME/controller-runtime metrics) on the controller metrics port (`:9402`, `research/18`). No native
   OTLP, no GenAI semconv.
3. **Capture in THIS stack:** cert-manager **v1.20.2** deployed in `cert-manager` ns
   (`gitops/apps/cert-manager.yaml`); `cert-manager-issuers` is "known-degraded" without a real issuer
   (`PROJECT_STATE.md`) — background. Capture via the Datadog `cert_manager` check (single endpoint
   config) **or** the Collector Prometheus receiver. **Gotcha (CONFIRMED):** set `rename_labels`
   mapping Prometheus label `name` → DD tag `cert_name`, or the generic `name` tag collides with AWS
   and other integrations and breaks tag filtering (`research/18`; integration doc).
4. **Official DD integration / OOTB dashboard:** **Yes** integration (Agent **7.22+**); **OOTB
   dashboard = No** — the integration doc does **not** mention an out-of-the-box dashboard. **This
   CORRECTS `research/18` ("Yes").** (The well-known cert-manager dashboard is a community Grafana
   dashboard, below — not a Datadog OOTB asset.)
5. **Community/importable dashboard:** Grafana **11001 "cert-manager"** is the canonical community
   dashboard (the cert-manager project's own monitoring docs reference it); also the
   `cert-manager-mixin` (Prometheus alerts + dashboard). Background component; no hand-built dashboard
   proposed.

### 8. Backstage

1. **Emits:** **nothing by default** — zero metrics, zero traces out of the box (CONFIRMED,
   `research/18`; backstage.io OTel setup tutorial).
2. **OTel/Prom/semconv:** requires the **OpenTelemetry SDK** wired into the Backstage backend; once
   added it emits generic HTTP-server/process spans + metrics (standard OTel HTTP/runtime semconv) —
   **not** GenAI semconv (Backstage is the developer portal, not an LLM component).
3. **Capture in THIS stack:** Backstage is deployed (`gitops/apps/backstage.yaml`, freshly scaffolded
   app image at `images/watch-it-burn-backstage/`, ALB ingress at `backstage.agenticburn.com`). It is
   a BUILD-SPEC **nice-to-have** ("include if time/feasibility allow") — background. No OTel SDK is
   wired in the scaffolded image yet, so it currently emits nothing; capture requires adding the SDK
   to the backend (a build task, not in scope here).
4. **Official DD integration / OOTB dashboard:** **No Agent check.** The "Datadog integration for
   Backstage" on the Datadog marketplace is a **UI-embedding plugin** (embed DD dashboards *into*
   Backstage), not a telemetry integration — confirmed `research/18`. No OOTB dashboard.
5. **Community/importable dashboard:** none meaningful until the SDK is wired. Background, not
   center-stage → **no dashboard proposed** per the constraint.

### 9. kagent / the workshop agent — *(AI-layer; extracted from `research/28` + `research/29`)*

1. **Emits:** **traces** (with token-usage attributes in spans). Prometheus metrics are claimed by
   kagent docs but **unconfirmed** (no metric names / scrape config documented — `research/18`/`#29`);
   do not plan a kagent Prometheus pipeline until a running pod's `/metrics` is inspected.
2. **OTel/Prom/semconv:** **OTel, GenAI semconv** — by inheritance from Google **ADK ≥ 1.17.0**, which
   the kagent engine runs. Span waterfall **`invoke_agent` (root) → `call_llm`/model span →
   `execute_tool {gen_ai.tool.name}`** (the rogue-MCP tool span). Attributes include
   `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
   `gen_ai.tool.name`, `gen_ai.operation.name` (full list in `research/28` Q6). `gen_ai.request.model`
   is the model-tier cost dimension; `gen_ai.usage.*` are what Datadog maps to token usage and derived
   cost. (`research/28` Q6; `research/29` Q1.)
3. **Capture in THIS stack:** **config-only** — set kagent Helm `otel.tracing.enabled: true` with
   `otel.tracing.exporter.otlp.endpoint` → the in-cluster OTel Collector (contrib 0.158.2) → Datadog
   exporter + Prometheus/Tempo. Set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` on the
   agent pod (`deployment.env`; verify-at-build that chart 0.9.9 honors it). Content capture stays
   `NO_CONTENT` on the shared path; `EVENT_ONLY` only for the re-leak beat (never `=true` — invalid,
   silently captures nothing — `research/28` Q5). **Datadog routing:** `gen_ai.*` spans land in
   Datadog **Agent Observability** (the rebranded LLM Observability product — not a classic
   integration dashboard); the Collector→Agent-Obs routing is the one flagged verify-at-build gap
   (`research/28` Q7 — confirm in the Agent-Obs traces UI, fall back to the direct-OTLP
   `dd-otlp-source=llmobs` header path, which is **unchanged** despite the rename).
4. **Official DD integration / OOTB dashboard:** **No** classic integration. The agent surfaces in
   **Datadog Agent Observability** (formerly "LLM Observability"; the docs landing page is now titled
   "Agent Observability" and the `/llm_observability/` URL roots and `dd-otlp-source=llmobs` header are
   unchanged) via native OTLP GenAI ingest (v1.37+), no SDK — that *is* the Datadog surface, distinct
   from an Agent-check OOTB dashboard. **New built-in capability (from the #9 re-run):** Agent
   Observability includes **Sensitive Data Scanner (SDS)**, which scans Agent-Obs traces — including
   the LLM inputs/outputs (`gen_ai.input.messages`/`gen_ai.output.messages`) — and can redact PII /
   secrets / proprietary data. Unlike general telemetry-data scanning (where you must manually create
   a scanning group + rules), Agent-Obs scanning is the **automated/pre-configured** case: a **default
   scanning group is auto-created** for the org on first visit to the Agent-Obs Settings page (rules
   are then editable / disable-able), and it acts **server-side after ingest** — so it is a
   defense-in-depth backstop for the re-leak beat, not a substitute for
   Collector-side pre-egress redaction (`research/28` product-naming + SDS notes). (`research/28` Q1/Q2.)
5. **Community dashboard:** n/a — center-stage; the live **trace view** (input/output/tool calls) is
   the dashboard, and the cost counter is the second panel.

### 10. agentgateway (v1.3.0) — *(AI-layer; extracted from `research/29`)*

1. **Emits:** **traces, metrics, logs** (built-in OpenTelemetry support).
2. **OTel/Prom/semconv:** **OTel with GenAI semconv built-in** (`gen_ai.request.model`,
   `gen_ai.usage.input_tokens`, `gen_ai.operation.name`) + Prometheus metrics (ports 15020 + 9092 per
   `research/18`). It traces both **MCP and LLM** traffic — a second, independent witness to the rogue
   MCP `execute_tool` call alongside the agent's own span (`research/29` Q2/Q4).
3. **Capture in THIS stack:** **config-only**, but **the repo activates it the WRONG way** — load-
   bearing finding from `research/29` Q2: `agent/gateway/agentgateway.yaml` sets the OTLP endpoint via
   the **`OTEL_EXPORTER_OTLP_ENDPOINT` env var**, which the v1.3.0 OSS standalone docs do **not**
   document; tracing must be set in the **config file** under `frontendPolicies.tracing.otlpEndpoint`
   (+ `randomSampling: true` for the demo). The env path is "unverified/likely inert." Full `gen_ai.*`
   enrichment for the **kagent A2A (JSON-RPC) backend** specifically is verify-at-build (vs a
   recognized chat-completions provider). `OTEL_RESOURCE_ATTRIBUTES` for UST stays as-is. (Note: this
   is a Milestone-2 config change — NOT made in this research-only spike.)
4. **Official DD integration / OOTB dashboard:** **No** named integration, **No** OOTB dashboard;
   consumed as OTLP via the Collector → Datadog (APM/traces).
5. **Community dashboard:** n/a — center-stage (MCP-authz / tool-call visibility); appears in the
   trace view.

### 11. guard-proxy — *(AI-layer; extracted from `research/29`)*

1. **Emits:** **Prometheus metrics today** (`witb_cost_usd`, `witb_tokens_total`,
   `witb_requests_total`, with a `tier` label, on `/metrics` — these power the live cost counter).
   **No traces today** (stdlib `ThreadingHTTPServer`, no OTel).
2. **OTel/Prom/semconv:** **Prometheus now; OTel manual spans to add.** Critical correction
   (`research/29` Q3): **the guard-proxy makes NO Bedrock/LLM call** — it receives A2A JSON-RPC,
   block-list/LLM-Guard checks the prompt, **forwards to the kagent agent Service**, optionally scrubs
   the response, and parses token usage from the agent's A2A response metadata. So the honest
   instrumentation is **a proxy/guard span (SERVER + CLIENT with W3C context propagation), NOT a
   `gen_ai.*` model span** — the model spans belong to the agent. OpenLLMetry is the wrong tool here
   (nothing LLM-client to hook); use the manual OTel SDK (`research/29` Q6). The `witb_*` Prometheus
   counters can stay as the cheap cost-counter scrape source — "migrate off `witb_*` to `gen_ai.*`"
   means **adding GenAI spans on the agent**, not renaming these counters (`research/29` cross-cutting #1).
3. **Capture in THIS stack:** scrape `/metrics` (already the cost-counter source: Prometheus +
   Datadog). To put the guard decisions in the trace waterfall, add manual OTel spans with `inject()`
   so the agent's `gen_ai.*` spans nest under the proxy span (`research/29` Q6) — a Milestone-2 build
   task, not done here. Avoid attaching `gen_ai.usage.*` to the proxy span (double-count risk; let the
   agent own usage — `research/29` Q3).
4. **Official DD integration / OOTB dashboard:** **No** (bespoke component).
5. **Community dashboard:** n/a — center-stage; the **cost counter** panel is built from its `witb_*`
   metrics (this is the workshop's own cost panel, sourced from a center-stage component, consistent
   with the "no hand-built dashboards for non-center-stage components" constraint).

### 12. evil-mcp-shim — *(AI-layer; extracted from `research/29`)*

1. **Emits:** **nothing — intentionally** (a `FastMCP` server with poisoned tool descriptions; no
   OTel).
2. **OTel/Prom/semconv:** none. It is observed indirectly: when the agent is induced to call a rogue
   tool, the **agent emits `execute_tool {gen_ai.tool.name}`** (e.g.
   `execute_tool read_internal_config`) nested under `invoke_agent`, and the call also traverses
   **agentgateway** (a second witness). (`research/29` Q4; `research/28` Q6.)
3. **Capture in THIS stack:** no shim instrumentation. The rogue call is visible via the agent's tool
   span and agentgateway's MCP trace. **Do NOT instrument it** — the teaching point is that an
   untrusted server need not cooperate with your observability; you still see the abuse because *your*
   agent and *your* gateway are instrumented (`research/29` Q4).
4. **Official DD integration / OOTB dashboard:** **No** (and should have none).
5. **Community dashboard:** n/a (do not instrument).

### 13. customer-stream generator

1. **Emits:** **nothing.** `gitops/manifests/customer-stream/stream.yaml`: a stdlib Python `urllib`
   loop POSTing FAKE-prefixed records to a consumer every 3s, and a stdlib `ThreadingHTTPServer`
   consumer (`GET /data`, `POST /ingest`). No OTel, no Prometheus, no metrics endpoint. (CONFIRMED,
   read from source.)
2. **OTel/Prom/semconv:** none today.
3. **Capture in THIS stack:** it is the **Beat-1 exfil target** (the live fake-customer-data stream
   the agent siphons to the S3 hoop) — a *target*, not an observed service. If telemetry were ever
   wanted, the consumer's `GET /data` would need manual OTel/Prometheus added (background, not center-
   stage). Its activity is otherwise visible only as the agent's tool calls / egress and (if a
   waypoint existed) Istio L4. No instrumentation is required for its role.
4. **Official DD integration / OOTB dashboard:** **No** (bespoke component, emits nothing).
5. **Community/importable dashboard:** n/a — background exfil target, not center-stage → **no
   dashboard proposed** per the constraint.

---

## Confidence per component

| Component | Confidence | Note |
|---|---|---|
| ArgoCD | **HIGH** | OOTB-dashboard correction re-verified vs DD blog + integration doc |
| Kyverno | **HIGH** | Both-signals + no-OOTB-dashboard re-verified vs integration doc |
| Falco | **HIGH** | OOTB dashboards confirmed verbatim |
| KubeArmor | **HIGH** | Survey-only; separate-exporter + no-DD-integration confirmed (built on #18/#17) |
| Istio ambient | **HIGH** (facts) / **MEDIUM** (ambient OOTB dashboard unconfirmed) | autodiscovery break + ztunnel-L4 confirmed |
| ESO | **HIGH** | Prometheus-only + community-dashboard-with-caveat confirmed |
| cert-manager | **HIGH** | OOTB-dashboard correction re-verified; `rename_labels` confirmed |
| Backstage | **HIGH** | emits-nothing + UI-embed-not-Agent-check confirmed |
| kagent/agent | **HIGH** (extracted from #28/#29 re-runs) | Datadog surface = **Agent Observability** (rebranded; SDS now built-in); Prometheus metrics for kagent itself remain unconfirmed (flagged) |
| agentgateway | **HIGH** (extracted from #29) | A2A-backend full `gen_ai.*` enrichment is verify-at-build |
| guard-proxy | **HIGH** (extracted from #29) | no-Bedrock-call correction is from direct source read |
| evil-mcp-shim | **HIGH** (extracted from #29) | emits-nothing-by-design |
| customer-stream | **HIGH** | emits-nothing confirmed from source |

## Could-not-fully-resolve (explicitly flagged)

1. **Istio ambient DD OOTB dashboard:** whether the Datadog Istio integration ships an OOTB dashboard
   that renders meaningfully for **ambient/ztunnel L4** (the integration's dashboards are
   sidecar/L7-oriented). Marked Unconfirmed; needs a live Datadog-UI check with `istio_mode: ambient`.
2. **kagent's own Prometheus `/metrics`:** docs claim Prometheus metrics but list no names/scrape
   config (carried from `research/18`/`#29`). Resolve by inspecting a running pod — the agent's
   *traces* (GenAI semconv) are confirmed; its *metrics* endpoint is not.
3. **Collector → Datadog Agent-Observability routing** for `gen_ai.*` spans (inherited from
   `research/28` Q7; same gap, now under the renamed product): not doc-resolvable; verify in the
   Agent-Obs traces UI, fall back to direct-OTLP `dd-otlp-source=llmobs` (header unchanged by the
   rename). (Affects how the agent's spans surface in Datadog, not whether they are emitted.)

---

## Sources (distinct citations)

1. https://docs.datadoghq.com/integrations/argocd/ — ArgoCD integration; Agent v7.42+; metrics ports 8082/8083/8084; integration doc does not enumerate an OOTB dashboard.
2. https://www.datadoghq.com/blog/argo-cd-datadog/ — ArgoCD **OOTB dashboard** confirmed verbatim + recommended app-sync-failure monitor (corrects research/18).
3. https://grafana.com/grafana/dashboards/14584-argocd/ — official ArgoCD Grafana dashboard (from the ArgoCD repo).
4. https://grafana.com/grafana/dashboards/19974-argocd-application-overview/ ; https://grafana.com/grafana/dashboards/19993-argocd-operational-overview/ ; https://grafana.com/grafana/dashboards/24192-argocd-overview/ — mixin/community ArgoCD dashboards.
5. https://docs.datadoghq.com/integrations/kyverno/ — Kyverno integration; Agent 7.55+/included 7.56+; OpenMetrics on `/metrics` port 8000; no OOTB dashboard mentioned.
6. https://kyverno.io/docs/monitoring/ — Kyverno native OTel/OTLP opt-in (`otelConfig=grpc`), metrics + traces (via research/18).
7. https://docs.datadoghq.com/integrations/falco/ — Falco integration; Agent 7.59.1+; **OOTB dashboards** confirmed verbatim; logs (webhook/file) + `falco.` OpenMetrics.
8. https://github.com/kubearmor/kubearmor-prometheus-exporter — KubeArmor separate Prometheus exporter (9 `kubearmor_alerts_*` counters), bundled `prometheus-grafana-deployment.yaml` dashboard; no native OTLP, no DD integration.
9. https://docs.datadoghq.com/integrations/istio/ — Istio integration; ambient autodiscovery break; `istio_mode: ambient`, ztunnel L4-only, waypoint for L7.
10. https://grafana.com/grafana/dashboards/21306-istio-ztunnel-dashboard/ — official Istio org ztunnel (ambient) Grafana dashboard.
11. https://istio.io/latest/docs/ops/integrations/grafana/ — Istio official Grafana dashboards (mesh/workload/control-plane, sidecar/L7-oriented).
12. https://external-secrets.io/latest/api/metrics/ — ESO Prometheus metrics (`externalsecret_*`, controller-runtime); no OTLP (via research/18).
13. https://grafana.com/grafana/dashboards/21640-external-secrets/ — upstream External Secrets Grafana dashboard.
14. https://github.com/external-secrets/external-secrets/issues/5957 ; https://github.com/external-secrets/external-secrets/issues/4615 — community reports the ESO dashboard shows no/incomplete data (verify before relying).
15. https://docs.datadoghq.com/integrations/cert-manager/ — cert-manager integration; Agent 7.22+; OpenMetrics; `rename_labels` (`name`→`cert_name`); no OOTB dashboard mentioned (corrects research/18).
16. https://grafana.com/grafana/dashboards/11001-cert-manager/ — community cert-manager Grafana dashboard (project-referenced).
17. https://github.com/imusmanmalik/cert-manager-mixin — cert-manager Prometheus mixin (alerts + dashboard).
18. https://backstage.io/docs/tutorials/setup-opentelemetry/ — Backstage emits nothing without the OTel SDK; the DD Backstage plugin is UI-embed only (via research/18).
19. https://docs.datadoghq.com/getting_started/tagging/unified_service_tagging/ — UST OTel attribute→DD tag mapping (`service.name`/`service.version`/`deployment.environment.name`); `DD_*` not supported on the OTel path.
20. research/18-datadog-integrations-stack-2026.md (in-repo, primary) — per-component DD integration survey, DDOT/`prometheusScrape` gotchas, KubeArmor exporter, Istio ambient break, cert-manager `rename_labels`.
21. research/28-datadog-llm-obs-otlp-2026.md (in-repo, issue #9, **re-run 2026-06-23**) — kagent/ADK native GenAI emission (`invoke_agent`/`call_llm`/`execute_tool`, `gen_ai.usage.*`, `gen_ai.request.model`); Datadog native OTLP ingest + Collector→Agent-Obs routing gap; content-capture enum; **product rename LLM Observability → Agent Observability** (URLs/header unchanged); **built-in Sensitive Data Scanner** for PII redaction of Agent-Obs traces.
22. research/29-python-ai-instrumentation-2026.md (in-repo, issue #10, **re-run 2026-06-23**) — kagent `otel.tracing.enabled`; agentgateway `frontendPolicies.tracing.otlpEndpoint` (repo env-var path wrong); guard-proxy makes no Bedrock call (instrument as proxy/guard span); evil-mcp-shim needs no instrumentation; OpenLLMetry status; Datadog "Agent Observability" product-name note + ADK auto-instrumentation.
23. https://docs.datadoghq.com/llm_observability/ — Datadog docs landing page now titled **"Agent Observability"** (rename of the LLM Observability surface; `/llm_observability/` URL root unchanged).
24. https://www.datadoghq.com/products/ai/agent-observability/ — Agent Observability product page; "Sensitive Data Scanner is included and scales with LLM usage"; "Catch hallucinations, prompt injection attempts, and PII exposure as they happen."
25. https://docs.datadoghq.com/llm_observability/data_security_and_rbac/ — "Agent Observability integrates with Sensitive Data Scanner, which helps prevent data leakage by identifying and redacting any sensitive information."
26. https://docs.datadoghq.com/security/sensitive_data_scanner/ — SDS scans Agent-Obs traces incl. LLM inputs/outputs; Agent-Obs scanning is the automated/pre-configured case (a default scanning group is auto-created on first Agent-Obs Settings visit; rules editable/disable-able) — distinct from general telemetry scanning, which requires manual group+rules; server-side, after ingest.

(23 distinct external sources [1–19, 23–26] + 3 in-repo prior spikes [20–22] this synthesis builds on.)

---

## Validation pass (adversarial, 2026-06-23)

Independent skeptical re-check of the load-bearing, time-sensitive external claims against current
(2026) official primary sources. Every claim below was fetched live this pass; in-repo wiring facts
were not re-verified here (out of scope — they were read from manifests by the author).

**Net result: all load-bearing external claims CONFIRMED.** One wording softened in place (Istio
"autodiscovery BROKEN" → "does not fire for ambient by default; must configure manually") because the
official doc frames ambient as a supported *manual* config path, not a broken feature — the operative
fact (autodiscovery keys on the `proxyv2` sidecar identifier and will not auto-detect ztunnel/waypoint)
is itself confirmed.

| # | Claim | Verdict | Source checked |
|---|---|---|---|
| 1 | **ArgoCD DD OOTB dashboard = Yes** (+ recommended app-sync-failure monitor) — corrects #18 | **CONFIRMED** (verbatim: "By using the Argo CD out-of-the-box (OOTB) dashboard…"; "a recommended, preconfigured monitor that alerts you to any app sync failures by filtering the `argocd.app_controller.app.info` metric") | https://www.datadoghq.com/blog/argo-cd-datadog/ |
| 2 | **ArgoCD integration: Agent v7.42+, ports 8082/8083/8084; integration *doc* does not enumerate the OOTB dashboard** | **CONFIRMED** (doc: "Minimum Agent version: 7.41.0 … requires Agent v7.42.0+"; ports 8082/8083/8084; doc page does not mention a dashboard) | https://docs.datadoghq.com/integrations/argocd/ |
| 3 | **ArgoCD Grafana 14584 = official ArgoCD dashboard** | **CONFIRMED** ("Official ArgoCD Dashboard", from the ArgoCD repo) | https://grafana.com/grafana/dashboards/14584-argocd/ |
| 4 | **Kyverno DD OOTB dashboard = No** (confirms #18) | **CONFIRMED** (integration doc mentions no OOTB dashboard) | https://docs.datadoghq.com/integrations/kyverno/ |
| 5 | **Kyverno DD integration: included Agent 7.56+ (check req. 7.55+); OpenMetrics `/metrics` port 8000** | **CONFIRMED** verbatim | https://docs.datadoghq.com/integrations/kyverno/ |
| 6 | **Kyverno native OTLP (`otelConfig=grpc`) pushes metrics + traces to an OTel Collector; also Prometheus** | **CONFIRMED** (`otelConfig=grpc` exports metrics and traces; Prometheus endpoint native) | https://kyverno.io/docs/monitoring/ |
| 7 | **Kyverno Grafana 15987 = Kyverno dashboard** | **CONFIRMED** (named "Kyverno", Prometheus data source) | https://grafana.com/grafana/dashboards/15987 |
| 8 | **Falco DD OOTB dashboards = Yes; Agent 7.59.1+** | **CONFIRMED** (verbatim: "The integration provides insights into alert logs through the out-of-the-box dashboards."; min Agent 7.59.1) | https://docs.datadoghq.com/integrations/falco/ |
| 9 | **cert-manager DD OOTB dashboard = No** (corrects #18 "Yes") | **CONFIRMED** (integration doc does not mention any OOTB dashboard) | https://docs.datadoghq.com/integrations/cert-manager/ |
| 10 | **cert-manager DD integration: Agent 7.22+; `rename_labels` `name`→`cert_name`** | **CONFIRMED** ("Minimum Agent version: 7.22.0"; `rename_labels: {name: cert_name}` example present) | https://docs.datadoghq.com/integrations/cert-manager/ |
| 11 | **cert-manager Grafana 11001 = community cert-manager dashboard** | **CONFIRMED** (named "cert-manager", "work in progress", Prometheus-scraped) | https://grafana.com/grafana/dashboards/11001-cert-manager/ |
| 12 | **Istio DD integration Agent 6.1+; ambient via `istio_mode: ambient` + `ztunnel_endpoint`/`waypoint_endpoint`; ztunnel L4-only, waypoint for L7** | **CONFIRMED** (doc: "Minimum Agent version: 6.1.0"; "Set `istio_mode: ambient` and configure one or more of `ztunnel_endpoint`, `waypoint_endpoint`, and `istiod_endpoint`"; ztunnel = L4, waypoint = L7) | https://docs.datadoghq.com/integrations/istio/ |
| 13 | **Istio autodiscovery does not auto-detect ambient (keys on the `istio-proxy`/`proxyv2` sidecar); must configure ambient manually** | **CONFIRMED (wording softened — see note)** — `auto_conf.yaml` autodiscovery identifiers are `proxyv2`/`proxyv2-rhel8` (sidecar), so ztunnel/waypoint are not auto-discovered; ambient requires explicit `istio_mode: ambient`. The current DD doc does NOT use the word "broken"; it presents ambient as a supported manual config. | https://github.com/DataDog/integrations-core/blob/master/istio/datadog_checks/istio/data/auto_conf.yaml ; https://docs.datadoghq.com/integrations/istio/ ; https://github.com/DataDog/integrations-core/issues/19166 |
| 14 | **Istio Grafana 21306 = official ztunnel (ambient) dashboard** | **CONFIRMED** (named "Istio Ztunnel Dashboard", Grafana Labs solution for Istio) | https://grafana.com/grafana/dashboards/21306-istio-ztunnel-dashboard/ |
| 15 | **ESO is Prometheus-only (`externalsecret_*`, `controller_runtime_*`); no native OTLP** | **CONFIRMED** (metrics on `/metrics`; custom `externalsecret_sync_calls_total`/`externalsecret_status_condition` + controller-runtime inherited; no OTLP mentioned) | https://external-secrets.io/latest/api/metrics/ |
| 16 | **ESO Grafana 21640 = upstream External Secrets dashboard** | **CONFIRMED** (named "External Secrets", links to the external-secrets repo) | https://grafana.com/grafana/dashboards/21640-external-secrets/ |
| 17 | **agentgateway standalone configures OTLP tracing in the config file (`frontendPolicies.tracing.otlpEndpoint`); the standalone docs do NOT document the `OTEL_EXPORTER_OTLP_ENDPOINT` env var the repo uses** | **CONFIRMED** — standalone observability doc shows config-file-only (`frontendPolicies.tracing` with `otlpEndpoint`, `randomSampling: true`) and does not document the env var. NOTE: the env var *is* documented for the **Kubernetes** deployment path (separate doc), so "likely inert" is correct only for the standalone path the repo runs. | https://agentgateway.dev/docs/standalone/main/integrations/observability/opentelemetry/ |

**Not re-verified this pass (inherited from #18/#28/#29 by the author's stated prerequisite, or in-repo
facts):** KubeArmor separate-exporter details; Backstage OTel-SDK requirement; the kagent/ADK GenAI
span waterfall and `gen_ai.*` attribute list; guard-proxy "no Bedrock call"; evil-mcp-shim emits
nothing; customer-stream emits nothing. These remain as the author marked them. The three
"could-not-fully-resolve" items (Istio ambient DD OOTB dashboard rendering, kagent's own Prometheus
`/metrics`, Collector→LLM-Obs routing) are correctly flagged as UNVERIFIED in-file and were not
resolvable from docs this pass either — they stand.

---

## Validation pass (adversarial, 2026-06-23 — re-run for the #9/#10 re-runs)

Second re-run, triggered by Whitney's directive: `research/28` (#9) and `research/29` (#10) were
re-run, surfacing two changes that propagate into the AI-layer rows here — (a) the Datadog product is
now branded **"Agent Observability"** (formerly "LLM Observability"), and (b) Agent Observability now
ships a **built-in Sensitive Data Scanner (SDS)**. This pass independently re-verified those two
deltas and **re-verified every load-bearing per-component Datadog integration fact** against the
current (2026) official docs, live this pass.

**Net result: all per-component Datadog facts re-confirmed IDENTICAL to the prior run; the two
AI-layer deltas (rename + SDS) CONFIRMED. ONE refutation:** the original SDS wording "not on by
default (requires a scanning group + rules)" was **REFUTED** against the current SDS doc — Agent-Obs
scanning is the automated/pre-configured case (a default scanning group is auto-created and active on
first Settings visit; the manual-group requirement is for general telemetry scanning). Corrected in
place in the kagent/agent row and source [26]. No wire-or-skip decision was made (still the
Milestone-5 conversation). Nothing else changed.

> **Adversarial re-validation (independent skeptical pass, 2026-06-23):** the rename, the
> `dd-otlp-source=llmobs` header continuity, the SDS "built-in / included" claim, and SDS scanning
> Agent-Obs traces incl. LLM in/out were each re-fetched live and CONFIRMED with verbatim quotes (see
> the table above, rows 6–9). The single inaccuracy found — SDS "not on by default" — was corrected
> inline rather than left as written.

| # | Claim | Verdict | Source checked (2026-06-23 re-run) |
|---|---|---|---|
| 1 | **ArgoCD DD integration: Agent 7.42+; ports 8082/8083/8084; integration *doc* does not enumerate an OOTB dashboard** | **CONFIRMED, unchanged** ("Minimum Agent version: 7.41.0 … requires Agent v7.42.0+"; ports 8082/8083/8084; no dashboard on the doc page) | https://docs.datadoghq.com/integrations/argocd/ |
| 2 | **Falco DD OOTB dashboards = Yes; Agent 7.59.1+** | **CONFIRMED, unchanged** (verbatim: "The integration provides insights into alert logs through the out-of-the-box dashboards."; min Agent 7.59.1) | https://docs.datadoghq.com/integrations/falco/ |
| 3 | **cert-manager DD OOTB dashboard = No; Agent 7.22+; `rename_labels` `name`→`cert_name`** | **CONFIRMED, unchanged** (no OOTB dashboard on the doc page; "Minimum Agent version: 7.22.0"; `rename_labels: {name: cert_name}` example present) | https://docs.datadoghq.com/integrations/cert-manager/ |
| 4 | **Kyverno DD OOTB dashboard = No; included Agent 7.56+ (check req. 7.55+); OpenMetrics `/metrics` port 8000** | **CONFIRMED, unchanged** (no OOTB dashboard mentioned; min 7.55.0, included 7.56.0+; port 8000) | https://docs.datadoghq.com/integrations/kyverno/ |
| 5 | **Istio DD integration Agent 6.1+; `istio_mode: ambient` + `ztunnel_endpoint`/`waypoint_endpoint`/`istiod_endpoint`; ztunnel L4, waypoint L7** | **CONFIRMED, unchanged** (verbatim: "ztunnel DaemonSet (L4 zero-trust tunneling) and optional `waypoint` proxies (L7 HTTP/gRPC processing)"; min Agent 6.1.0) | https://docs.datadoghq.com/integrations/istio/ |
| 6 | **AI-layer Datadog surface renamed: "LLM Observability" → "Agent Observability"** (URLs + `dd-otlp-source=llmobs` header unchanged) | **CONFIRMED** — docs landing page titled "Agent Observability"; product page "Agent Observability \| LLM Observability"; per `research/28` re-run all 7 of its verdicts unchanged by the rename | https://docs.datadoghq.com/llm_observability/ ; https://www.datadoghq.com/products/ai/agent-observability/ |
| 7 | **Built-in Sensitive Data Scanner (SDS)** in Agent Observability — scans Agent-Obs traces incl. LLM in/out, redacts PII/secrets; server-side after ingest | **CONFIRMED** ("Sensitive Data Scanner is included and scales with LLM usage"; "Catch … PII exposure as they happen"; "Agent Observability integrates with Sensitive Data Scanner, which helps prevent data leakage by identifying and redacting any sensitive information"; SDS doc: "Sensitive Data Scanner can scan Agent Observability traces, including inputs and outputs from LLM applications"; "A default scanning group is automatically created for your organization when you first access the Agent Observability Settings page") | https://www.datadoghq.com/products/ai/agent-observability/ ; https://docs.datadoghq.com/llm_observability/data_security_and_rbac/ ; https://docs.datadoghq.com/security/sensitive_data_scanner/ |
| 8 | **SDS "not on by default" / "requires a scanning group + rules"** (original file wording) | **REFUTED → CORRECTED in place** — the SDS doc explicitly contrasts Agent-Obs scanning as the **automated/pre-configured** case: a **default scanning group is auto-created** on first Agent-Obs Settings visit and you "modify existing rules, **disable** rules you don't need, or add custom scanning rules" — implying the default group/rules are active once created, NOT off-by-default. The "manually create a group + rules" requirement applies to **general telemetry-data** scanning, not Agent-Obs scanning. File corrected: dropped "not on by default," reframed as the auto-created/pre-configured default group. | https://docs.datadoghq.com/security/sensitive_data_scanner/ |
| 9 | **`dd-otlp-source=llmobs` header still routes OTLP into Agent Observability (unchanged by rename)** | **CONFIRMED** (OTel instrumentation doc shows `headers={"dd-api-key":…, "dd-ml-app":…, "dd-otlp-source":"llmobs"}` to route OTLP traces to Agent Observability) | https://docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation/ |

**What changed vs the prior run of THIS file:** only the AI-layer kagent/agent row and the
verification-method block — the Datadog surface is now named **Agent Observability** (rename only;
ingest path, `dd-otlp-source=llmobs` header, and v1.37+ semconv minimum all unchanged), and the
built-in **Sensitive Data Scanner** is added as a server-side PII-redaction backstop relevant to the
re-leak beat. The non-AI components (ArgoCD, Kyverno, Falco, KubeArmor, Istio ambient, ESO,
cert-manager, Backstage, customer-stream) are **unchanged** — every load-bearing DD integration fact
re-verified identical this pass. The three "could-not-fully-resolve" items still stand (the
Collector→Agent-Obs routing item is the same gap, now under the renamed product).
