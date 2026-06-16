*Purpose: the Grafana trace-waterfall view the facilitator narrates every beat through, and how these dashboards reach the hub Grafana.*

# Grafana Dashboards — Workshop Observability

These dashboards live on the **HUB** cluster's Grafana (the facilitator's, alongside Tempo). The
spoke OTel Collectors forward GenAI traces to the hub Tempo; Grafana renders them. Dashboards are
**provisioned declaratively at build time** (kube-prometheus-stack sidecar `ConfigMap`s labelled
`grafana_dashboard: "1"`, or Grafana provisioning files) — nobody clicks through the UI on the day.

## The narrated view: the GenAI trace waterfall

The one view every beat is narrated through is the **Tempo trace waterfall** in Grafana's Explore
(Tempo data source). It shows the agent's reasoning and tool calls as a nested span tree:

```
invoke_agent                       (agent invocation — CLIENT/INTERNAL)
└─ plan                            (agent reasoning / task-decomposition step)
   └─ execute_tool <gen_ai.tool.name>   (the tool call — INTERNAL span)
```

This nesting is exactly what makes the rogue MCP call in beat 3 visible: the `execute_tool` span
names the tool via `gen_ai.tool.name`, so the audience SEES the agent reach for the tool it should
never call. (Span names and attributes verified against open-telemetry/semantic-conventions-genai;
all `gen_ai.*` attributes are Development status as of 2026-06-15.)  # verify-at-build

What to surface on the waterfall / supporting panels:

- **`invoke_agent` → `plan` → `execute_tool`** nesting — the connective-tissue lens for all beats.
- **`gen_ai.tool.name`** (required on `execute_tool` spans) and `gen_ai.tool.call.id` — which tool,
  which call. The beat-3 rogue tool is identified here.
- **Token usage** — `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens` on the
  model/inference span (`{gen_ai.operation.name} {gen_ai.request.model}`, e.g. `chat <model>`).
- **`gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`** — operation/provider/model.

## Re-leak-trap note (§4, 2-hour beat)

Content attributes (`gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`)
are **OFF by default** and are stripped by the spoke Collector's redaction + transform processors
(see `../otel-collector.yaml`). So the planted `FAKE-...-sentinel` must NOT appear in any span on
these dashboards under normal operation. The trap beat deliberately turns capture on to show the
leak, then shows the collector-side redaction masking it — the dashboards are where both states are
observed.

## Provisioning at build

- Dashboard JSON committed beside this README; provisioned via the kube-prometheus-stack Grafana
  dashboard-sidecar (`ConfigMap` with label `grafana_dashboard: "1"`) on the hub.  # verify-at-build
- Tempo is configured as a Grafana data source on the hub at build time.  # verify-at-build
- kagent's native emission of `execute_tool` / `gen_ai.tool.name` is unconfirmed — capture a real
  span in Phase 3 and pin the actual attribute names before finalizing panel queries.  # verify-at-build
