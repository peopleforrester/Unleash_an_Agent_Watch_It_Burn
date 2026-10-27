# ABOUTME: Render-gate check for P4 observability: collector traces->Tempo, slimmed Prometheus,
# ABOUTME: and the agent-observability dashboard (cost + token + gen_ai trace panels) is valid JSON.
import json
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collector_render import collector_config  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]

otel = yaml.safe_load((REPO / "gitops" / "bootstrap" / "apps" / "otel-collector.yaml").read_text())
prom = yaml.safe_load((REPO / "gitops" / "bootstrap" / "apps" / "prometheus.yaml").read_text())
dash_cm = yaml.safe_load((REPO / "observability-idp" / "grafana" / "dashboards" / "agent-observability.yaml").read_text())
dashboard = json.loads(dash_cm["data"]["agent-observability.json"])

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# Collector: OTLP in, traces pipeline exports to Tempo.

def _app_values(app):
    """The Helm valuesObject of an Application, single- or multi-source, and the repo value files it layers.

    otel-collector became multi-source in #242 (chart source + a `ref: values` source pointing at this
    repo), so `spec.source` no longer exists on it. This resolves both shapes and merges the repo value
    files the chart source lists, which is where the collector config now lives.
    """
    src = app["spec"].get("source") or app["spec"]["sources"][0]
    helm = src.get("helm", {}) or {}
    vals = dict(helm.get("valuesObject") or {})
    for vf in helm.get("valueFiles", []):
        path = REPO / vf.replace("$values/", "")
        if path.exists():
            layer = yaml.safe_load(path.read_text()) or {}
            for k, v in layer.items():
                if isinstance(v, dict) and isinstance(vals.get(k), dict):
                    vals[k] = {**vals[k], **v}
                else:
                    vals[k] = v
    return vals

_otel_vals = _app_values(otel)
cfg = _otel_vals["config"]
check("collector has an otlp receiver", "otlp" in cfg["receivers"])
check("instructor collector traces pipeline exports to Tempo", "otlp_grpc/tempo" in cfg["service"]["pipelines"]["traces"]["exporters"])
check("collector cluster.name is not the stale KubeAuto value",
      all(a.get("value") != "kubeauto-ai-day" for a in cfg["processors"]["resource"]["attributes"]))

# Datadog is the PRIMARY sink when datadog-secret exists; Grafana/Tempo/Prometheus are the secondary fallback.
# Since #500 the Datadog half is the overlay the datadog-gate loads as a second config, so these read the
# config the collector runs WITH the secret (test_collector_no_datadog.py covers the run without it).
dd_cfg = collector_config("instructor", datadog_secret=True)
check("Datadog is the primary traces exporter", dd_cfg["service"]["pipelines"]["traces"]["exporters"][0] == "datadog")
check("Datadog is the primary metrics exporter", dd_cfg["service"]["pipelines"]["metrics"]["exporters"][0] == "datadog")
check("instructor: Grafana/Tempo kept as the secondary traces fallback", "otlp_grpc/tempo" in dd_cfg["service"]["pipelines"]["traces"]["exporters"])
# The attendee profile installs no Tempo (#475): its collector names no Tempo exporter in any trace list, with
# the Datadog overlay loaded (how an attendee collector always runs) or without it (relay.yaml alone).
for _secret in (True, False):
    _att = collector_config("attendee", datadog_secret=_secret)
    check(f"attendee collector exports no traces to Tempo ({'with' if _secret else 'without'} the Datadog overlay)",
          "otlp_grpc/tempo" not in _att["service"]["pipelines"]["traces"]["exporters"])
check("Datadog API key is NOT hardcoded (env reference)", dd_cfg["exporters"]["datadog"]["api"]["key"].startswith("${env:"))
_vals = _otel_vals
_ddenv = {e["name"]: e for e in _vals.get("extraEnvs", [])}
check("DD_API_KEY sourced from a BYO secret (not in repo)", "secretKeyRef" in _ddenv.get("DD_API_KEY", {}).get("valueFrom", {}))

# Prometheus: slimmed (alertmanager off) + a single alertmanager key + short retention.
pvals = _app_values(prom)
check("alertmanager disabled (slim the per-attendee node)", pvals["alertmanager"]["enabled"] is False)
check("prometheus retention trimmed to hours", pvals["prometheus"]["prometheusSpec"]["retention"].endswith("h"))
ds = {d["name"]: d for d in pvals["grafana"].get("additionalDataSources", [])}
check("prometheus.yaml carries no Loki datasource: no cluster runs Loki (#474)",
      "Loki" not in ds and all(d.get("uid") != "loki" for d in ds.values()))
# The Tempo data source ships with Tempo (#475), so a profile without the tempo app has no data source for it:
# a sidecar-labelled ConfigMap in gitops/tempo/, which the tempo Application deploys beside the chart.
check("prometheus.yaml no longer carries the Tempo datasource", "Tempo" not in ds and all(d.get("uid") != "tempo" for d in ds.values()))
tempo_app = yaml.safe_load((REPO / "gitops" / "bootstrap" / "apps" / "tempo.yaml").read_text())
_tempo_paths = [s.get("path") for s in tempo_app["spec"].get("sources", [])]
check("the tempo Application deploys gitops/tempo beside its chart",
      "gitops/tempo" in _tempo_paths and any(s.get("chart") == "tempo" for s in tempo_app["spec"].get("sources", [])))
_ds_cm = yaml.safe_load((REPO / "gitops" / "tempo" / "grafana-datasource.yaml").read_text())
check("the Tempo datasource ConfigMap is in Grafana's namespace with the sidecar's label",
      _ds_cm["metadata"].get("namespace") == "monitoring"
      and (_ds_cm["metadata"].get("labels") or {}).get(pvals["grafana"]["sidecar"].get("datasources", {}).get("label", "grafana_datasource")) == "1"
      and pvals["grafana"]["sidecar"]["datasources"].get("enabled") is True)
_tds = {d["uid"]: d for f in _ds_cm["data"].values() for d in (yaml.safe_load(f) or {}).get("datasources", [])}
check("Tempo datasource pinned with uid 'tempo', at the Tempo service",
      _tds.get("tempo", {}).get("type") == "tempo" and _tds["tempo"].get("url") == "http://tempo.monitoring:3100")
check("Tempo's data source links traces to no Loki, which no cluster runs (#474)", "loki" not in json.dumps(_tds).lower())

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

# datadog/connector (PRD #13 M2): APM trace.* metrics, required since otelcol-contrib v0.95.0. It lives in the
# Datadog overlay with the exporter it feeds, so it is checked on the config the collector runs with the secret.
dd_conns = dd_cfg.get("connectors", {})
check("collector has a datadog/connector", "datadog/connector" in dd_conns)
check("datadog/connector computes stats by span kind",
      dd_conns.get("datadog/connector", {}).get("traces", {}).get("compute_stats_by_span_kind") is True)
check("datadog/connector wired into traces exporters", "datadog/connector" in dd_cfg["service"]["pipelines"]["traces"]["exporters"])
check("datadog/connector wired into metrics receivers", "datadog/connector" in dd_cfg["service"]["pipelines"]["metrics"]["receivers"])


# Unified Service Tagging on the AI-layer pods (service.name + env via OTEL_RESOURCE_ATTRIBUTES).
# Assert against the canonical deployed copies under gitops/ai-layer/. resources.yaml holds many Deployments, so select the target Deployment by name.
def _container_env(path, name):
    docs = [d for d in yaml.safe_load_all((REPO / path).read_text()) if d]
    dep = next(d for d in docs if d.get("kind") == "Deployment" and d.get("metadata", {}).get("name") == name)
    c = dep["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e.get("value", "") for e in c.get("env", [])}


# Datadog env for the KubeCon delivery (#629): Whitney's sandbox org holds other projects, and this env tag is
# what keeps BurritoBot's data separate there. It replaced PRD #13's production. service.version is the component's real software version (NOT a model-tier label). The model
# dimension for the cost race comes from gen_ai.request.model (M2), not service.version.
DD_ENV = "burritobot-kubecon-na-26"


def _kagent_env():
    docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]
    agent = next(d for d in docs if d.get("kind") == "Agent")
    env = agent["spec"]["declarative"]["deployment"]["env"]
    return {e["name"]: e.get("value", "") for e in env}


# Deployments (containers[0] env) for three components; kagent is an Agent CRD handled separately.
_UST = {
    "guard-proxy": ("gitops/ai-layer/resources.yaml", "service.name=burritobot,", "service.version=1.0.0"),
    "evil-mcp-shim": ("gitops/ai-layer/resources.yaml", "service.name=burritobot-evil-mcp", "service.version=1.0.0"),
    "agentgateway": ("gitops/ai-layer/agentgateway.yaml", "service.name=burritobot-gateway", "service.version=v1.5.0"),
}
_ust_targets = [(n, _container_env(p, n).get("OTEL_RESOURCE_ATTRIBUTES", ""), s, v) for n, (p, s, v) in _UST.items()]
# kagent's span version follows the chart the cluster runs, read from the Application rather than written
# here: the chart went 0.9.9 -> 0.10.1 on 2026-09-10 while the span version stayed v0.9.9 (#586), the same
# drift #495 fixed for agentgateway by deriving its version from the image tag.
_kagent_chart = str(yaml.safe_load((REPO / "gitops/bootstrap/apps/kagent.yaml").read_text())["spec"]["source"]["targetRevision"])
_kagent_ver = f"v{_kagent_chart}"
_kagent_attrs = dict(kv.split("=", 1) for kv in _kagent_env().get("OTEL_RESOURCE_ATTRIBUTES", "").split(",") if "=" in kv)
check(f"kagent spans carry service.version={_kagent_ver}, the chart gitops/bootstrap/apps/kagent.yaml pins "
      f"(found {_kagent_attrs.get('service.version')})", _kagent_attrs.get("service.version") == _kagent_ver)
_ust_targets.append(("kagent", _kagent_env().get("OTEL_RESOURCE_ATTRIBUTES", ""), "service.name=burritobot-agent", f"service.version={_kagent_ver}"))
for _name, _ust, _svc, _ver in _ust_targets:
    check(f"{_name} carries UST (service.name + real service.version + env={DD_ENV})",
          _svc in _ust and _ver in _ust and f"deployment.environment.name={DD_ENV}" in _ust
          and "CLUSTER_TIER" not in _ust and "deployment.environment.name=watch-it-burn" not in _ust)


# Platform-component Unified Service Tagging (PRD #28): the five platform controls carry the Datadog
# UST pod annotations (tags.datadoghq.com/{service,env,version}) so they appear on the Service Catalog /
# Service Map as first-class components. Unlike the AI layer (OTEL_RESOURCE_ATTRIBUTES env), these are
# Helm-values podAnnotations on the Datadog-Agent-scraped pods. env is DD_ENV, and each service starts with
# burritobot- so it cannot collide with another project's in the shared org (#629); version is
# the real deployed software version (NOT a chart version where they differ, e.g. falco app 0.45.1).
def _pod_annotations(path, *navkeys, doc_name=None):
    """Return the podAnnotations dict at valuesObject + navkeys for a manifest.

    For an ArgoCD Application manifest the values live under spec.source.helm.valuesObject; for the
    bootstrap argocd-values.yaml they are at the document root. doc_name selects one Application from a
    multi-document istio manifest by metadata.name.
    """
    docs = [d for d in yaml.safe_load_all((REPO / path).read_text()) if d]
    if doc_name is not None:
        node = next(d for d in docs if d.get("metadata", {}).get("name") == doc_name)
    else:
        node = docs[0]
    if node.get("kind") == "Application":
        node = _app_values(node)
    for k in navkeys:
        node = node[k]
    return node.get("podAnnotations", {})


# (component, service, version, podAnnotations) — istio has two pods (control plane + data plane).
_PLATFORM_UST = [
    ("cert-manager", "burritobot-cert-manager", "v1.20.2", _pod_annotations("gitops/bootstrap/apps/cert-manager.yaml")),
    ("falco", "burritobot-falco", "0.45.1", _pod_annotations("gitops/bootstrap/apps/falco.yaml")),
    ("kyverno", "burritobot-kyverno", "v1.19.1", _pod_annotations("gitops/bootstrap/apps/kyverno.yaml", "admissionController")),
    ("argocd", "burritobot-argocd", "v3.4.4", _pod_annotations("infra/argocd-values.yaml", "server")),
    ("istio-ztunnel", "burritobot-istio", "1.30.1", _pod_annotations("gitops/bootstrap/apps/istio.yaml", doc_name="ztunnel")),
    ("istiod", "burritobot-istio", "1.30.1", _pod_annotations("gitops/bootstrap/apps/istio.yaml", "pilot", doc_name="istiod")),
]
for _name, _svc, _ver, _ann in _PLATFORM_UST:
    check(f"{_name} carries platform UST (tags.datadoghq.com service={_svc} env={DD_ENV} version={_ver})",
          _ann.get("tags.datadoghq.com/service") == _svc
          and _ann.get("tags.datadoghq.com/env") == DD_ENV
          and str(_ann.get("tags.datadoghq.com/version")) == _ver)

# Falcosidekick forwards Falco alerts to Datadog, key from a BYO secret, Talon path preserved.
fvals = _app_values(yaml.safe_load((REPO / "gitops" / "bootstrap" / "apps" / "falcosidekick.yaml").read_text()))
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
