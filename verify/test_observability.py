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
check("dashboard graphs gen_ai cost (gen_ai namespace, derived from token usage)",
      "gen_ai_client_cost" in exprs)
check("no custom witb_* metrics in the dashboard (use the gen_ai semconv namespace)",
      not any(m in exprs for m in ("witb_cost_usd", "witb_tokens_total", "witb_requests_total")))
check("dashboard has a Tempo traces panel for gen_ai spans",
      any(p.get("type") == "traces" for p in dashboard["panels"])
      and any("gen_ai" in t.get("query", "") for p in dashboard["panels"] for t in p.get("targets", [])))

# Span metrics connector: generated metrics must carry UST resource attributes for DD correlation.
# Key is `span_metrics` (current semconv name; `spanmetrics` is the deprecated alias).
conns = cfg.get("connectors", {})
check("collector has a span_metrics connector", "span_metrics" in conns)
check("span_metrics propagates resource attributes (UST) onto generated metrics",
      conns.get("span_metrics", {}).get("add_resource_attributes") is True)
check("span_metrics wired into traces exporters", "span_metrics" in cfg["service"]["pipelines"]["traces"]["exporters"])
check("span_metrics wired into metrics receivers", "span_metrics" in cfg["service"]["pipelines"]["metrics"]["receivers"])

# datadog/connector (PRD #13 M2): APM trace.* metrics, required since otelcol-contrib v0.95.0.
check("collector has a datadog/connector", "datadog/connector" in conns)
check("datadog/connector computes stats by span kind",
      conns.get("datadog/connector", {}).get("traces", {}).get("compute_stats_by_span_kind") is True)
check("datadog/connector wired into traces exporters", "datadog/connector" in cfg["service"]["pipelines"]["traces"]["exporters"])
check("datadog/connector wired into metrics receivers", "datadog/connector" in cfg["service"]["pipelines"]["metrics"]["receivers"])


# Unified Service Tagging on the AI-layer pods (service.name + env via OTEL_RESOURCE_ATTRIBUTES).
# Assert against the canonical deployed copies under gitops/ai-layer/ (agent/gateway/ is the synced
# source mirror). resources.yaml holds many Deployments, so select the target Deployment by name.
def _container_env(path, name):
    docs = [d for d in yaml.safe_load_all((REPO / path).read_text()) if d]
    dep = next(d for d in docs if d.get("kind") == "Deployment" and d.get("metadata", {}).get("name") == name)
    c = dep["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e.get("value", "") for e in c.get("env", [])}


# Locked UST vocabulary (PRD #13): deployment.environment.name=production (the SDLC env, NOT the project
# name), and service.version is the component's real software version (NOT a model-tier label). The model
# dimension for the cost race comes from gen_ai.request.model (M2), not service.version.
def _kagent_env():
    docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]
    agent = next(d for d in docs if d.get("kind") == "Agent")
    env = agent["spec"]["declarative"]["deployment"]["env"]
    return {e["name"]: e.get("value", "") for e in env}


# Deployments (containers[0] env) for three components; kagent is an Agent CRD handled separately.
_UST = {
    "guard-proxy": ("gitops/ai-layer/resources.yaml", "service.name=guard-proxy", "service.version=1.0.0"),
    "evil-mcp-shim": ("gitops/ai-layer/resources.yaml", "service.name=evil-mcp-shim", "service.version=1.0.0"),
    "agentgateway": ("gitops/ai-layer/agentgateway.yaml", "service.name=agentgateway", "service.version=v1.3.0"),
}
_ust_targets = [(n, _container_env(p, n).get("OTEL_RESOURCE_ATTRIBUTES", ""), s, v) for n, (p, s, v) in _UST.items()]
_ust_targets.append(("kagent", _kagent_env().get("OTEL_RESOURCE_ATTRIBUTES", ""), "service.name=kagent", "service.version=v0.9.9"))
for _name, _ust, _svc, _ver in _ust_targets:
    check(f"{_name} carries locked UST (service.name + real service.version + env=production)",
          _svc in _ust and _ver in _ust and "deployment.environment.name=production" in _ust
          and "CLUSTER_TIER" not in _ust and "deployment.environment.name=watch-it-burn" not in _ust)

# Falcosidekick forwards Falco alerts to Datadog, key from a BYO secret, Talon path preserved.
fvals = yaml.safe_load((REPO / "gitops" / "apps" / "falcosidekick.yaml").read_text())["spec"]["source"]["helm"]["valuesObject"]
check("falcosidekick has a Datadog output", "datadog" in fvals["config"])
# falcosidekick chart 0.14.0 reads env from config.extraEnv (NOT top-level extraEnv) — see
# PRD #23 M2 fix (commit c7f4e7b). Assert against that path.
fenv = {e["name"]: e for e in fvals.get("config", {}).get("extraEnv", [])}
check("falcosidekick DATADOG_APIKEY from a BYO secret (not hardcoded)",
      "secretKeyRef" in fenv.get("DATADOG_APIKEY", {}).get("valueFrom", {}))
check("falcosidekick still feeds Talon (Datadog is additive/swappable)", "talon" in fvals["config"])

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll observability (P4) checks passed.")
