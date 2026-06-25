# PRD #20 M7: Build Verification (live cluster)

Live verification of the OTel gen_ai semconv chain on `watch-it-burn-attendee-001`
(EKS 1.35, us-west-2), dry run 2026-06-25. Verified against Tempo (the Collector's
secondary trace sink, identical spans to the Datadog leg) and the proxy `/metrics`
endpoint, since only the Datadog ingest API key is in-cluster (no Datadog Application
key for the query API).

| # | Item | Result | Evidence |
|---|------|--------|----------|
| 1 | Traces arrive at the Collector | **PASS (kagent)** / agentgateway deferred | kagent spans reach the Collector and export to Tempo + Datadog. agentgateway is staged but intentionally not deployed (5 verify-at-build blockers), so its trace leg is out of scope for this run. |
| 2 | kagent/ADK gen_ai waterfall | **PASS** | Trace `58258a10cbf7811e95a6b071fe338020`: `invoke_agent workshop_agent → call_llm → chat → execute_tool list_pods` with `gen_ai.tool.name=list_pods`. |
| 3 | Datadog LLM-Observability routing | **Instructor UI check** | Spans reach Datadog via the contrib `datadog` exporter (primary traces exporter) carrying `gen_ai.operation.name=chat`, the classification LLM-Obs needs. Programmatic confirmation needs a Datadog App key (not in-cluster); the panel render is the facilitator's manual check on Whitney's org. Fallback if it does not route: dedicated OTLP exporter with `dd-otlp-source=llmobs` header (research/28 Q7). |
| 4 | `gen_ai.request.model` on spans | **PASS** | `call_llm`, `chat`, and `generate_content` spans all carry `gen_ai.request.model = us.anthropic.claude-haiku-4-5-20251001-v1:0`. |
| 5 | `witb_cost_usd{model=...}` in metrics | **Shaped correctly; scrape path UNWIRED (decision needed)** | The proxy exposes `witb_cost_usd{model="haiku"} 0.011353` (model label present, no tier label) and is annotated `prometheus.io/scrape=true`. But kube-prometheus-stack scrapes via ServiceMonitor/PodMonitor CRDs, not pod annotations, and there is no ServiceMonitor for guard-proxy, so Prometheus has 0 series and Datadog never receives it. The PRIMARY cost visual (the web console polling `/cost`) works live (`usd:0.0113` over 6 requests); only the secondary Grafana panel (`sum by (model) (witb_cost_usd)`) is empty. See "Item 5 decision" below. |
| 6 | Content capture on spans | **PASS** | Act 1 trace `97d2eef4003e3eba4adf56cdd59433e`: `gen_ai.input.messages` / `gen_ai.output.messages` carried the prompt. NO_CONTENT teardown trace `69565ab1ba496b78c1d13ad6ba2e5741`: op=`chat`, no content attributes. (guard-proxy armed with SPAN_ONLY; kagent uses EVENT_ONLY per resources.yaml; both enable capture.) |
| 7 | Weaver `live-check` on emitted spans | **PASS** | Real guard-proxy SERVER + `sanitize` spans pulled from Tempo and checked against `weaver/registry/`: no violations, only the expected `stability: development` improvement advisories. `http.response.status_code` validates as int once OTLP/JSON int64-as-string is coerced (see docs/weaver-live-check.md gotcha). |

## Item 5 decision (open)

`witb_cost_usd` is correctly migrated (PRD #20 M5: `model` label, no `tier`) and exposed on the
proxy, but nothing scrapes it into Prometheus or Datadog. Two valid wirings, and the choice affects
which sink gets the metric:

- **ServiceMonitor for guard-proxy** (Prometheus picks it up via the already-enabled
  `serviceMonitorSelectorNilUsesHelmValues: false`). Feeds the existing Grafana cost panel. Does not
  reach Datadog by itself.
- **Collector `prometheus` receiver scrape_config** targeting the proxy (honoring its
  `prometheus.io/scrape` annotation). Routes `witb_cost_usd` to Datadog (and Prometheus via remote
  write). Matches the annotation already on the proxy Service, which implies annotation-scrape was the
  original intent.

This is not wired in either direction yet. The demo's primary cost visual does not depend on it (the
web console reads `/cost` directly). Recommend the Collector scrape_config if `witb_cost_usd` should
appear in Datadog metrics; recommend (or also add) the ServiceMonitor if the Grafana panel must be
populated. Deferred pending Michael's call, since it is an architecture choice, not a defect.

## Net

5 of 7 items pass outright (1 partial: agentgateway deferred). Item 3 is the facilitator's Datadog-UI
confirmation. Item 5 is shaped correctly but needs a scrape-wiring decision. The gen_ai semconv chain
(model dimension, content capture, tool-call waterfall, Weaver conformance) is verified live.
