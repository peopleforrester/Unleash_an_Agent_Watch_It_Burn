---
created: 2026-06-25
topic: datadog-community-dashboards
status: fresh
issue: 24
gates: prds/7-observability-meta.md M7
validation: triple-validated 2026-06-25 (initial pass + 2 adversarial web fact-checks + live-cluster ground truth)
---

# Datadog dashboards for Kyverno, Istio ztunnel, ESO, cert-manager (2026-06-25)

Research spike for issue #24, the M7 (Dashboard Layer) prerequisite gate. The question was framed as
"what **Datadog community** dashboard JSON exists to import," but triple-validation showed the real
question is broader and more useful: **for each component, is there an importable Datadog dashboard at
all (official OOTB or community), and does OUR wiring actually feed it?** Datadog only. No Grafana
imports.

Grounded against the live cluster `watch-it-burn-attendee-001` (PRD #26 Agent + integrations deployed),
so metric presence/absence is observed, not inferred. Findings were adversarially fact-checked; the
corrections from that pass are folded in below.

## TL;DR

| Component | Importable Datadog dashboard? | Renders on OUR wiring? | M7 action |
|---|---|---|---|
| **cert-manager** | **Yes, official OOTB** (`certmanager_overview.json`, "Cert Manager Overview") | **Yes** | **Import the OOTB dashboard.** `cert_manager.*` metrics confirmed flowing. Done. |
| **Istio ambient (ztunnel)** | Yes, official OOTB (`istio_overview.json`) **but it is legacy sidecar** | **No** (mostly empty) | **Build a small custom ztunnel dashboard.** OOTB queries L7 `istio.mesh.*`; ztunnel emits L4 (`tcp.*`/`dns.*`/`xds.*`/`active_proxy_count`). |
| **Kyverno** | **Yes, official OOTB** | **Yes (RESOLVED 2026-06-25)** | **Import the OOTB dashboard.** Native OTLP was unfixable (gRPC-Go #7625); switched to the Agent openmetrics check, which emits the `kyverno.*` names the OOTB dashboard expects. See Kyverno section. |
| **ESO** | **No** (no Datadog integration exists) | n/a (no metrics flowing) | **Build custom**, and wire an Agent OpenMetrics scrape of ESO first. |

**Correction to the spike's premise (caught in validation):** there is no useful *community* dashboard
JSON for any of the four. `DataDog/community-lab` (the canonical community repo) was **archived
2024-08-27** and only covers akamai, aws, core, gcp, k8s, network, squid, sso. A second community repo,
`DataDog/effective-dashboards`, was archived 2024-10-07. Both are read-only with no entries for any of
these four components, and Datadog has no active replacement. But three of the four (**cert-manager,
Kyverno, Istio**) have **official OOTB** dashboards in `DataDog/integrations-core`. So M7 is not "import
community vs build"; it is "OOTB-and-it-works vs OOTB-but-our-wiring-doesn't-feed-it vs build from scratch."

The Datadog Marketplace is a commercial ecosystem of paid integrations — not a free dashboard gallery.

---

## Per-component findings

### cert-manager: import the OOTB dashboard (works as-is)

Official integration (`cert_manager` Agent check, bundled in the Agent) ships
`cert_manager/assets/dashboards/certmanager_overview.json` ("Cert Manager Overview", days-to-expiration
widget since v2.2.0). Live: the `cert_manager` check is `[OK]` and `cert_manager.certificate.expiration_timestamp`,
`cert_manager.certificate.ready_status`, `cert_manager.controller.sync_call.count`,
`cert_manager.http_acme_client.*` are in Datadog now. The OOTB dashboard queries exactly these. **Import
it. Nothing custom.**

Note: the dashboard queries `cert_manager.certificate.expiration_timestamp` (no `_seconds` suffix). PRD
#26's `rename_labels` handles this normalization from the raw Prometheus metric.

Metrics covered: certificate expiration timestamps, clock time (drift detection), ready status, HTTP ACME
client requests and durations, controller sync calls.

### Istio ambient / ztunnel: OOTB dashboard exists but is legacy sidecar; build custom

The Istio integration **does** support ambient (`istio_mode: ambient`, `ztunnel_endpoint` /
`waypoint_endpoint` / `istiod_endpoint`); ambient-metrics support landed via integrations-core issue
#19166, **closed Completed 2026-06-04** (freshly GA). But the OOTB dashboard (`istio_overview.json`) is
built for **L7 sidecar/Envoy** metrics (`istio.mesh.request.*`, `istio.mesh.response.*`) and even still
references **Mixer and Galley**, components Istio removed years ago. ztunnel is L4-only: its metrics map
to `tcp.*` / `dns.*` / `xds.*` / `active_proxy_count` (e.g. `istio_tcp_connections_opened_total` ->
`tcp.connections_opened.total`), not `istio.mesh.*`. Live confirmation: what is in Datadog is
`ztunnel_connected`, `istio_build`, `istio_cni_install_ready`, `istiod_managed_clusters`,
`istiod_uptime_seconds`, i.e. control plane + ztunnel L4 only, none of the OOTB dashboard's L7 request metrics.
So the OOTB Istio dashboard renders mostly empty for our ztunnel-only ambient deployment. **Build a
small custom dashboard on the `ztunnel_*` (tcp/dns/xds/active_proxy) + `istiod_*` metrics.** (If a
waypoint proxy is ever added per issue #25, waypoints DO emit `istio.*`-style L7 metrics and more of the
OOTB dashboard would light up.)

### Kyverno: OOTB dashboard exists but does not fit our path, AND the OTLP export is currently broken

Two distinct problems, both confirmed live:

1. **Name mismatch (by design).** The official Kyverno integration (Agent >= 7.56.0) is an **Agent
   OpenMetrics check** (`openmetrics_endpoint`, Kyverno `/metrics` on :8000) and submits metrics under
   the `kyverno.*` namespace (e.g. `kyverno.policy.results.count`, `kyverno.admission.requests.count`).
   The OOTB Kyverno dashboard is built for those names. **Our wiring is OTLP** (meta-PRD M5 D9:
   `--otelConfig=grpc`, no Agent Kyverno check, to avoid duplicate metrics). Kyverno's native OTLP
   instrument names use underscores (`kyverno_policy_results`, `kyverno_admission_requests`,
   `kyverno_admission_review_duration_seconds`, etc. from `kyverno/pkg/metrics`). The Datadog Exporter
   does not normalize application metric names — only `system.*` and `process.*` get special treatment.
   Underscore names arrive in Datadog unchanged and do not match the OOTB dashboard's dot-format queries.

2. **The OTLP export is failing right now (a live #26 M3 bug, not lag).** Kyverno's admission controller
   logs repeat: `failed to upload metrics: exporter export timeout: rpc error: code = Unavailable desc =
   name resolver error: produced zero addresses` against
   `otel-collector-opentelemetry-collector.monitoring.svc.cluster.local:4317`. That FQDN resolves fine
   from other pods (172.20.181.163, :4317 present), so the cause is on the kyverno side: most likely a
   default-deny **NetworkPolicy** blocking kyverno egress to the collector / kube-dns, or a gRPC
   resolver-format issue. Net: **zero kyverno metrics reach Datadog** (confirmed: no `kyverno*` in the
   org's 1337 metrics). This must be fixed before any Kyverno dashboard, OOTB or custom, can show data.

**RESOLVED 2026-06-25 (revises M5 D9 + this row):** the OTLP failure was not a NetworkPolicy. Kyverno's
bundled gRPC/OTel exporter fails with `produced zero addresses` even against a literal ClusterIP, a
gRPC-Go #7625 regression baked into the kyverno binary, so OTLP is unfixable here. Kyverno was switched
to the **Datadog Agent openmetrics check** (same pattern as cert-manager/falco/istio): Kyverno serves
Prometheus on :8000 and the Agent scrapes it via an `ad.datadoghq.com/kyverno.checks` annotation. This
emits the `kyverno.*` names, so **the official Datadog Kyverno OOTB dashboard now works** (import it, no
custom build). The M5 D9 "no Agent check, avoid duplicate metrics" rationale is moot because the OTLP
path produced zero metrics. See `gitops/apps/kyverno.yaml`. So Kyverno moves to the cert-manager bucket:
import OOTB.

**Reference query names for the custom dashboard** (expected underscore format once OTLP is fixed):
- `kyverno_policy_results` (replaces `kyverno.policy.results.count`)
- `kyverno_policy_changes` (replaces `kyverno.policy.changes.count`)
- `kyverno_admission_requests` (replaces `kyverno.admission.requests.count`)
- `kyverno_admission_review_duration_seconds` (distribution, replaces `.sum`/`.count` pair)
- `kyverno_policy_execution_duration_seconds` (distribution)
- `kyverno_controller_requeue`, `kyverno_controller_drop`, `kyverno_controller_reconcile`
- `kyverno_client_queries`
- `kyverno_http_requests`
- `kyverno_policy_rule_info`

Verify actual arriving names in Datadog after fixing the OTLP export — they are Collector/exporter-config
dependent and should be confirmed from observation, not assumed.

### ESO (External Secrets Operator): no Datadog path; build custom

No official Datadog integration (`integrations-core/external_secrets` is a 404; no Agent check). ESO
exposes Prometheus `externalsecret_*` metrics on `/metrics`. An upstream Grafana dashboard exists (Grafana.com
ID 21640) but **we are not using it — this stack uses Datadog only.** Live: zero `externalsecret*` metrics
in Datadog (ESO is not scraped; PRD #26 wired four named integrations and ESO was not one). **Build a
custom Datadog dashboard from `externalsecret_*`, and first wire an Agent OpenMetrics scrape of the ESO
controller.**

Relevant ESO metric names: `externalsecret_sync_calls_total`, `externalsecret_status_condition`,
`controller_runtime_reconcile_total`, `controller_runtime_reconcile_errors_total`.

---

## M7 recommendation table

| Component | Use OOTB dashboard | Build custom | Prerequisite before it shows data |
|---|---|---|---|
| cert-manager | Yes (Cert Manager Overview) | No | none (metrics flowing) |
| Istio ambient | No (legacy sidecar, mostly empty) | Yes (ztunnel L4: tcp/dns/xds/active_proxy + istiod) | none (ztunnel metrics flowing) |
| Kyverno | Yes (OOTB, via the Agent openmetrics check) | No | none (RESOLVED: switched OTLP->Agent check; `kyverno.*` flowing) |
| ESO | No (no integration) | Yes (externalsecret_* via Agent OpenMetrics) | Wire Agent OpenMetrics scrape of ESO first |

---

## Datadog community dashboard infrastructure status

| Resource | Status | Notes |
|---|---|---|
| `DataDog/community-lab` | Archived 2024-08-27 | Was empty for all four components before archival |
| `DataDog/effective-dashboards` | Archived 2024-10-07 | Design best practices, no component dashboards |
| OOTB integration dashboards | Active (via integrations-core) | Auto-installs with Agent check |
| Datadog Marketplace | Active | Commercial paid integrations only; no free dashboard gallery |
| Dashboard Gallery / template store | Does not exist | No public browsable dashboard catalog in Datadog |

---

## Sources

- [DataDog/integrations-core — kyverno/assets/dashboards/overview.json](https://github.com/DataDog/integrations-core/blob/master/kyverno/assets/dashboards/overview.json) — OOTB Kyverno dashboard, dot-format metric names
- [DataDog/integrations-core — cert_manager/assets/dashboards/certmanager_overview.json](https://github.com/DataDog/integrations-core/blob/master/cert_manager/assets/dashboards/certmanager_overview.json) — OOTB cert-manager dashboard
- [DataDog/integrations-core — istio/assets/dashboards/](https://github.com/DataDog/integrations-core/tree/master/istio/assets/dashboards) — 4 OOTB Istio dashboards
- [DataDog/integrations-core — istio issue #19166](https://github.com/DataDog/integrations-core/issues/19166) — ambient metrics support landed 2026-06-04
- [DataDog/community-lab GitHub](https://github.com/DataDog/community-lab) — Archived 2024-08-27
- [DataDog/effective-dashboards GitHub](https://github.com/DataDog/effective-dashboards) — Archived 2024-10-07
- [Datadog Marketplace blog post](https://www.datadoghq.com/blog/datadog-marketplace/) — Commercial paid integrations ecosystem
- [Kyverno pkg/metrics/metrics.go](https://github.com/kyverno/kyverno/blob/main/pkg/metrics/metrics.go) — OTel SDK instrument name definitions confirming underscore format
