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
| **Kyverno** | Yes, official OOTB **but built for the Agent openmetrics check** | **No** (two reasons, below) | **Fix the OTLP export first, then build custom.** OOTB expects `kyverno.*.count` Agent-check names; our OTLP path does not produce them. |
| **ESO** | **No** (no Datadog integration; only an upstream Grafana dashboard) | n/a (no metrics flowing) | **Build custom**, and wire an Agent OpenMetrics scrape of ESO first. |

**Correction to the spike's premise (caught in validation):** there is no useful *community* dashboard
JSON for any of the four. `DataDog/community-lab` (the canonical community repo) was **archived
2024-08-27** and only covers akamai, aws, core, gcp, k8s, network, squid, sso (plus non-component
`_web`/`src`/`.github` dirs). But three of the four (**cert-manager, Kyverno, Istio**) have **official
OOTB** dashboards in `DataDog/integrations-core`. So M7 is not "import community vs build"; it is
"OOTB-and-it-works vs OOTB-but-our-wiring-doesn't-feed-it vs build from scratch."

## Per-component findings

### cert-manager: import the OOTB dashboard (works as-is)

Official integration (`cert_manager` Agent check, bundled in the Agent) ships
`cert_manager/assets/dashboards/certmanager_overview.json` ("Cert Manager Overview", days-to-expiration
widget since v2.2.0). Live: the `cert_manager` check is `[OK]` and `cert_manager.certificate.expiration_timestamp`,
`cert_manager.certificate.ready_status`, `cert_manager.controller.sync_call.count`,
`cert_manager.http_acme_client.*` are in Datadog now. The OOTB dashboard queries exactly these. **Import
it. Nothing custom.**

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
   instrument names are `kyverno_policy_results`, `kyverno_admission_requests`,
   `kyverno_admission_review_duration_seconds`, etc. (`kyverno/pkg/metrics`). Through a Collector to
   Datadog those do not become the Agent check's remapped `kyverno.*.count` names, so the OOTB dashboard
   would show no data even with OTLP working. (Exact arriving name is Collector/exporter-config
   dependent; the conclusion is not.)

2. **The OTLP export is failing right now (a live #26 M3 bug, not lag).** Kyverno's admission controller
   logs repeat: `failed to upload metrics: exporter export timeout: rpc error: code = Unavailable desc =
   name resolver error: produced zero addresses` against
   `otel-collector-opentelemetry-collector.monitoring.svc.cluster.local:4317`. That FQDN resolves fine
   from other pods (172.20.181.163, :4317 present), so the cause is on the kyverno side: most likely a
   default-deny **NetworkPolicy** blocking kyverno egress to the collector / kube-dns, or a gRPC
   resolver-format issue. Net: **zero kyverno metrics reach Datadog** (confirmed: no `kyverno*` in the
   org's 1337 metrics). This must be fixed before any Kyverno dashboard, OOTB or custom, can show data.

**M7 action:** fix the OTLP export (egress NetworkPolicy / endpoint), confirm the exact metric names
Kyverno's OTLP path lands as in Datadog, then build a custom Kyverno dashboard against those observed
names. Do not switch Kyverno to the Agent check just to get the OOTB dashboard (M5 D9 chose OTLP on
purpose).

### ESO (External Secrets Operator): no Datadog path; build custom

No official Datadog integration (`integrations-core/external_secrets` is a 404; no Agent check). ESO
exposes Prometheus `externalsecret_*` metrics on `/metrics`; the only prebuilt dashboard upstream is a
**Grafana** dashboard (Grafana.com ID 21640), which we will not use. (The May-2026 "AWS Secrets Manager
managed external secrets for Datadog" announcement is unrelated; it is about rotating Datadog API keys,
not monitoring ESO.) Live: zero `externalsecret*` metrics in Datadog (ESO is not scraped; PRD #26 wired
four named integrations and ESO was not one). **Build a custom dashboard from `externalsecret_*`, and
first wire an Agent OpenMetrics/Prometheus scrape of the ESO controller.**

## M7 recommendation table

| Component | Use OOTB dashboard | Build custom | Prerequisite before it shows data |
|---|---|---|---|
| cert-manager | Yes (Cert Manager Overview) | No | none (metrics flowing) |
| Istio ambient | No (legacy sidecar, mostly empty) | Yes (ztunnel L4: tcp/dns/xds/active_proxy + istiod) | none (ztunnel metrics flowing) |
| Kyverno | No (Agent-check names; our path is OTLP) | Yes | **fix the failing OTLP export** (NetworkPolicy/endpoint), then confirm OTLP metric names in Datadog |
| ESO | No (no integration; Grafana only) | Yes | wire an Agent OpenMetrics scrape of ESO `externalsecret_*` first |

Net: only **cert-manager** is import-and-done. **Istio ambient** and **ESO** need custom dashboards
(and ESO needs a scrape wired first). **Kyverno** needs a live bug fixed before any dashboard works,
then a custom dashboard.

## Validation notes

Triple pass: (1) initial web + live-cluster research; (2) two independent adversarial web fact-checks
that corrected the framing (cert-manager/Kyverno/Istio all have official OOTB dashboards, not just
cert-manager) and the Kyverno metric name (`kyverno.policy.results.count`); (3) live-cluster ground
truth that found the Kyverno OTLP export is actively failing (not ingestion lag) and that ztunnel/
istiod/cert_manager metrics are present while kyverno/ESO are absent.

## Sources

- [DataDog/community-lab (archived 2024-08-27)](https://github.com/DataDog/community-lab)
- [DataDog/integrations-core cert_manager dashboard](https://github.com/DataDog/integrations-core/tree/master/cert_manager/assets/dashboards)
- [Datadog cert-manager integration](https://docs.datadoghq.com/integrations/cert-manager/)
- [Datadog Kyverno integration (Agent openmetrics check)](https://docs.datadoghq.com/integrations/kyverno/)
- [Kyverno OpenTelemetry / metrics docs](https://kyverno.io/docs/monitoring/opentelemetry/)
- [kyverno/pkg/metrics/metrics.go](https://github.com/kyverno/kyverno/blob/main/pkg/metrics/metrics.go)
- [Datadog Istio integration (ambient support)](https://docs.datadoghq.com/integrations/istio/)
- [integrations-core Istio dashboard (istio_overview.json, sidecar/legacy)](https://github.com/DataDog/integrations-core/blob/master/istio/assets/dashboards/istio_overview.json)
- [integrations-core Istio metrics.py (ztunnel L4 metric map)](https://github.com/DataDog/integrations-core/blob/master/istio/datadog_checks/istio/metrics.py)
- [integrations-core #19166: ambient mode metrics for Istio (Completed 2026-06-04)](https://github.com/DataDog/integrations-core/issues/19166)
- [External Secrets Operator metrics](https://external-secrets.io/latest/api/metrics/)
- [External Secrets upstream Grafana dashboard (ID 21640)](https://grafana.com/grafana/dashboards/21640-external-secrets/)
- Live cluster `watch-it-burn-attendee-001` Datadog metric inventory + kyverno OTLP export logs (2026-06-25).
