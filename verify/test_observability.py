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

# Span metrics connector: generated metrics must carry UST resource attributes for DD correlation.
conns = cfg.get("connectors", {})
check("collector has a spanmetrics connector", "spanmetrics" in conns)
check("spanmetrics propagates resource attributes (UST) onto generated metrics",
      conns.get("spanmetrics", {}).get("add_resource_attributes") is True)
check("spanmetrics wired into traces exporters", "spanmetrics" in cfg["service"]["pipelines"]["traces"]["exporters"])
check("spanmetrics wired into metrics receivers", "spanmetrics" in cfg["service"]["pipelines"]["metrics"]["receivers"])


# Unified Service Tagging on the AI-layer pods (service.name + env via OTEL_RESOURCE_ATTRIBUTES).
def _container_env(path):
    docs = [d for d in yaml.safe_load_all((REPO / path).read_text()) if d]
    dep = next(d for d in docs if d.get("kind") == "Deployment")
    c = dep["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e.get("value", "") for e in c.get("env", [])}


gp_ust = _container_env("agent/gateway/guard-proxy/guard-proxy.yaml").get("OTEL_RESOURCE_ATTRIBUTES", "")
check("guard-proxy carries UST (service.name + env) via OTEL_RESOURCE_ATTRIBUTES",
      "service.name=guard-proxy" in gp_ust and "deployment.environment.name=watch-it-burn" in gp_ust)
ag_ust = _container_env("agent/gateway/agentgateway.yaml").get("OTEL_RESOURCE_ATTRIBUTES", "")
check("agentgateway carries UST (service.name) via OTEL_RESOURCE_ATTRIBUTES",
      "service.name=agentgateway" in ag_ust)

# Falcosidekick forwards Falco alerts to Datadog, key from a BYO secret, Talon path preserved.
fvals = yaml.safe_load((REPO / "gitops" / "apps" / "falcosidekick.yaml").read_text())["spec"]["source"]["helm"]["valuesObject"]
check("falcosidekick has a Datadog output", "datadog" in fvals["config"])
fenv = {e["name"]: e for e in fvals.get("extraEnv", [])}
check("falcosidekick DATADOG_APIKEY from a BYO secret (not hardcoded)",
      "secretKeyRef" in fenv.get("DATADOG_APIKEY", {}).get("valueFrom", {}))
check("falcosidekick still feeds Talon (Datadog is additive/swappable)", "talon" in fvals["config"])

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll observability (P4) checks passed.")
