# ABOUTME: Render-gate check for P4 observability: collector traces->Tempo, slimmed Prometheus,
# ABOUTME: and the agent-observability dashboard (cost + token + gen_ai trace panels) is valid JSON.
import json
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]

otel = yaml.safe_load((REPO / "gitops" / "apps" / "otel-collector.yaml").read_text())
prom = yaml.safe_load((REPO / "gitops" / "apps" / "prometheus.yaml").read_text())
dash_cm = yaml.safe_load((REPO / "observability-idp" / "grafana" / "dashboards" / "agent-observability.yaml").read_text())
dashboard = json.loads(dash_cm["data"]["agent-observability.json"])

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# Collector: OTLP in, traces pipeline exports to Tempo.
cfg = otel["spec"]["source"]["helm"]["valuesObject"]["config"]
check("collector has an otlp receiver", "otlp" in cfg["receivers"])
check("collector traces pipeline exports to Tempo", "otlp/tempo" in cfg["service"]["pipelines"]["traces"]["exporters"])
check("collector cluster.name is not the stale KubeAuto value",
      all(a.get("value") != "kubeauto-ai-day" for a in cfg["processors"]["resource"]["attributes"]))

# Datadog is the PRIMARY sink; Grafana/Tempo/Prometheus are the secondary fallback.
check("Datadog is the primary traces exporter", cfg["service"]["pipelines"]["traces"]["exporters"][0] == "datadog")
check("Datadog is the primary metrics exporter", cfg["service"]["pipelines"]["metrics"]["exporters"][0] == "datadog")
check("Grafana/Tempo kept as the secondary traces fallback", "otlp/tempo" in cfg["service"]["pipelines"]["traces"]["exporters"])
check("Datadog API key is NOT hardcoded (env reference)", cfg["exporters"]["datadog"]["api"]["key"].startswith("${env:"))
_vals = otel["spec"]["source"]["helm"]["valuesObject"]
_ddenv = {e["name"]: e for e in _vals.get("extraEnvs", [])}
check("DD_API_KEY sourced from a BYO secret (not in repo)", "secretKeyRef" in _ddenv.get("DD_API_KEY", {}).get("valueFrom", {}))

# Prometheus: slimmed (alertmanager off) + a single alertmanager key + short retention.
pvals = prom["spec"]["source"]["helm"]["valuesObject"]
check("alertmanager disabled (slim the per-attendee node)", pvals["alertmanager"]["enabled"] is False)
check("prometheus retention trimmed to hours", pvals["prometheus"]["prometheusSpec"]["retention"].endswith("h"))
ds = {d["name"]: d for d in pvals["grafana"]["additionalDataSources"]}
check("Tempo datasource pinned with uid 'tempo'", ds.get("Tempo", {}).get("uid") == "tempo")

# Dashboard: valid JSON with the cost + token + gen_ai trace panels.
panels = {p["title"]: p for p in dashboard["panels"]}
exprs = " ".join(t.get("expr", "") for p in dashboard["panels"] for t in p.get("targets", []))
check("dashboard graphs witb_cost_usd", "witb_cost_usd" in exprs)
check("dashboard graphs witb_tokens_total", "witb_tokens_total" in exprs)
check("dashboard has a Tempo traces panel for gen_ai spans",
      any(p.get("type") == "traces" for p in dashboard["panels"])
      and any("gen_ai" in t.get("query", "") for p in dashboard["panels"] for t in p.get("targets", [])))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll observability (P4) checks passed.")
