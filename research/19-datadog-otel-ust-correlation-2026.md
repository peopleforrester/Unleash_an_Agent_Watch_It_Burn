# Spike B: Datadog Log-Trace and Metrics-to-Logs Correlation via Pure OTel

*Research spike, 2026-06-21.*
*Synthesized from spinybacked-orbweaver research: `otel-to-datadog-forwarding.md`,*
*`datadog-log-trace-correlation.md`, `otel-vs-native-logs-correlation.md`,*
*`otel-vs-native-metrics-logs-ui-parity.md`, `datadog-metrics-logs-correlation.md`,*
*`otel-resource-attributes-metrics-logs.md`*

**Question:** Does Datadog LLM Observability — log-trace pivots, metrics-to-logs pivots, "View
Trace in APM," "View related logs" — work on pure OTel gen_ai.* spans sent via the Datadog
Exporter? Or does it require dd-trace?

**Answer: Yes, it works. No dd-trace required.**

---

## Log-Trace Correlation

### What works on the pure OTel path

- "View Trace in APM" from a log entry
- The Logs tab inside an APM trace view
- The Trace tab in Logs Explorer
- All standard APM-to-logs and logs-to-APM pivots in the Datadog UI

These work because Datadog auto-detects `trace_id` and `span_id` fields in either the
dd-trace convention (`dd.trace_id`, `dd.span_id`) **or** the OTel standard convention
(`trace_id`, `span_id`). The platform supports both.

Source: Datadog docs — "Datadog automatically detects the `dd.trace_id` and `dd.span_id`
convention used by Datadog SDKs, as well as the OpenTelemetry standards `trace_id` and
`span_id`."

### Required format — no conversion needed

| Field | Required format |
|---|---|
| `trace_id` | 32-character lowercase hex, no `0x` prefix |
| `span_id` | 16-character lowercase hex, no `0x` prefix |

The OTel JS SDK returns `span.spanContext().traceId` and `span.spanContext().spanId` in exactly
this format already. No decimal conversion, no padding, no manipulation.

**Gotcha:** Training data commonly teaches converting OTel 128-bit trace IDs to a 64-bit decimal
`dd.trace_id` field. This is a dd-trace convention only. For OTel SDK users it is unnecessary
and incorrect.

### OTLP pipeline vs. file/stdout pipeline

**OTLP log path** (OTel SDK bridge → OTLP exporter → Datadog Agent or Collector): The Agent
automatically injects `trace_id` values present in the LogRecord. No extra field config.
Supported for winston, pino, bunyan via their OTel instrumentation packages.

**File/stdout log path** (Agent `filelog` receiver scraping pod logs): `trace_id` and `span_id`
must be explicitly present in the JSON log output. The pipeline does not inject them.

For this workshop, the AI layer components (guard-proxy, agentgateway, kagent) log to stdout.
The fields must be in the JSON output.

### `service.name` is NOT auto-remapped for log tags

The Datadog Exporter maps `service.name` → `service` for traces automatically. It does **not**
do the same for logs ingested via the Agent log pipeline. Logs get the `service` tag only when
using the OTLP log ingestion path or when the Agent's "Preprocessing for JSON logs" is
configured.

For the workshop, use `OTEL_RESOURCE_ATTRIBUTES=service.name=<component>` on pods — the Agent
picks this up from the pod environment and auto-tags logs with the correct `service` value when
using container log collection.

---

## Metrics-to-Logs Correlation

### How it works

Purely tag-based. If a metric data point carries `service=guard-proxy env=watch-it-burn` and a
log entry carries those same tags, Datadog's "View related logs" link in Metrics Explorer and
Dashboard widgets opens a pre-filtered log query. No extra configuration beyond matching
Unified Service Tagging (UST) tags.

Three UI entry points:
1. Metrics Explorer → hover metric → "View related logs"
2. Dashboard timeseries widget → hover point → "View related logs"
3. Log Explorer → "Correlated metrics" panel

### UST is the key

Set `OTEL_RESOURCE_ATTRIBUTES` on every AI layer pod:
```bash
OTEL_RESOURCE_ATTRIBUTES=service.name=<component>,service.version=<cluster-tier>,deployment.environment.name=watch-it-burn
```

The Datadog Exporter maps `deployment.environment.name` → `env` (requires Exporter v0.110.0+
or Agent 7.58.0+; see gotcha below). When `service`, `env`, and `version` tags match across
traces, metrics, and logs, all correlation pivots work automatically.

---

## Critical Gotcha: spanmetricsconnector Drops UST Tags by Default

The `spanmetricsconnector` does **not** propagate resource attributes (`deployment.environment.name`,
`service.version`) to generated metrics by default. `add_resource_attributes` defaults to `false`.
Without it:

- Span-derived metrics have no `env` or `version` tags
- "View related logs" in Metrics Explorer silently finds nothing (no tag overlap)
- Metrics-to-logs correlation is broken for any metric produced by the spanmetrics connector

**Fix — required in the OTel Collector config:**

```yaml
connectors:
  spanmetrics:
    add_resource_attributes: true
```

This option re-enables the pre-feature-gate behavior that propagates resource attributes to the
generated metrics' resource scope, where the Datadog Exporter can then read them for UST tag
mapping.

This applies to the YAML key `spanmetrics` (deprecated) or `span_metrics` (current). Verify
the key against the collector-contrib version in use (see global rule `otel-span-metrics-connector-gotchas.md`).

---

## `deployment.environment.name` vs `deployment.environment`

OTel semconv v1.27.0 deprecated `deployment.environment` in favor of `deployment.environment.name`.

- Use `deployment.environment.name` — the current attribute
- Requires Datadog Agent ≥ 7.58.0 **or** Datadog Exporter ≥ v0.110.0 to map to `env` tag
- Datadog Exporter handles the mapping automatically; no pipeline config needed

The OTel JS constant `ATTR_DEPLOYMENT_ENVIRONMENT_NAME` is in `/incubating` due to promotion
lag. Define it locally: `const ATTR_DEPLOYMENT_ENVIRONMENT_NAME = 'deployment.environment.name'`

---

## OTel Collector: Dual Export Architecture

For this workshop, the OTel Collector routes traces through the Datadog Exporter as the primary
sink. Direct OTLP trace ingestion to Datadog (bypassing the Exporter) is still Preview-only as
of mid-2026 — do not rely on it.

The existing `prometheusremotewrite` and `otlp/tempo` exporters are secondary fallbacks to the
local kube-prometheus-stack and Grafana/Tempo stack. They are not paths to Datadog.

The Datadog Exporter handles approximately 40 OTel resource attribute mappings automatically.
Attributes not in that set (custom span attributes, custom resource attributes) are dropped
unless explicitly surfaced via span tags or metric dimensions.

---

## UI Parity Summary

| Datadog UI feature | dd-trace only | OTel path | Notes |
|---|---|---|---|
| "View Trace in APM" from log | No | ✅ | trace_id must be in log JSON |
| Logs tab in APM trace view | No | ✅ | log pipeline must tag `service`/`env` |
| Trace tab in Logs Explorer | No | ✅ | |
| "View related logs" in Metrics Explorer | No | ✅ | requires UST tags to match |
| Service map | No | ✅ | UST tags + Exporter; verify at live cluster |
| dd.trace_id decimal conversion required | N/A | ❌ Not needed | OTel SDK hex format accepted natively |

---

## Confidence Ratings

| Finding | Confidence | Source |
|---|---|---|
| trace_id hex format accepted natively | High | Datadog docs, spinybacked-orbweaver verification |
| "View Trace in APM" works on OTel path | High | Datadog compat matrix, docs |
| spanmetricsconnector drops UST by default | High | OTel Collector contrib README, confirmed gotcha |
| service.name not auto-remapped for Agent log pipeline | High | Datadog blog, spinybacked-orbweaver |
| Service map appears via OTel Exporter | Medium | Docs confirm UST mapping; live cluster not yet verified |
