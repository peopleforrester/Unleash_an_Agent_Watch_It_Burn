# ABOUTME: Holds #784's promise that guard-proxy's gen_ai.client.cost gauge is unchanged by the chat-span token counts:
# ABOUTME: the name, unit and attribute set it had at the pre-#784 pin, in proxy.py, the Go build, weaver and readers.
"""#784 put gen_ai.usage.input_tokens and gen_ai.usage.output_tokens on guard-proxy's /chat `chat` span
(guard-proxy-agenticburn#49, 96d16214, pinned through c2eb4cf2 by a65f748d and now at 0f0c809). The criterion says
the cost metric beside it is unchanged: the fleet dashboard, the leaderboard's C4 bill, the KubeCon room view and the
Grafana agent-observability board all read `gen_ai.client.cost`, so a renamed metric, a new unit or a changed
attribute set would leave them reading nothing (#949).

The shape is held as literals below, as it was before #784: at guard-proxy 88b9b52, the pin a65f748d replaced, and in
weaver/registry at 0164143d's parent, the commit before #784's semconv move. This holds, offline:
- guard-proxy 88b9b52 (read from the submodule's history) emits that shape, so the literals are the pre-#784 ones;
- the pinned proxy.py and the Go build emit the same name, unit and attribute keys, and weaver's
  metric.witb.guard_proxy.cost declares them, a gauge with both attributes required;
- 96d16214's parent and the pin carry the same gauge code, byte for byte, in proxy.py and in the Go build, so the
  token-count change did not touch it;
- run in this process, the pinned proxy.py's gauge observes, after a kagent reply, exactly that attribute set, and
  the spend it reports is the reply's token counts, the same counts chat_usage_tokens reads for the chat span;
- nothing adds gen_ai.usage.cost (the research comment on #784 explains why the chat span carries no cost);
- every dashboard and leaderboard query on the cost reads gen_ai.client.cost, and the Grafana board groups it by an
  attribute the gauge carries.

verify/test_weaver_guard_proxy_spans.py holds the registry and proxy.py to each other; this holds both to the shape
they had before #784. verify/test_chat_span_token_counts.py holds the token counts themselves.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import subprocess
import sys
import types

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
SUB = REPO / "gitops/ai-layer/guard-proxy"
BEFORE_PIN = "88b9b5229312d785331237474b82bab1d5d31402"  # the guard-proxy pin a65f748d replaced
COUNTS_FIX = "96d162141800f6408c70a4cfc5bc3e9f0bc12ecb"  # guard-proxy-agenticburn#49, the chat-span token counts
NAME, UNIT, INSTRUMENT = "gen_ai.client.cost", "USD", "gauge"
ATTRS = {"gen_ai.request.model", "gen_ai.provider.name"}
PROVIDER = "aws.bedrock"
READERS = ("infra/datadog-fleet/dashboard.yaml", "infra/datadog-fleet/leaderboard.yaml",
           "infra/datadog-room/room_view.yaml")
GRAFANA = "observability-idp/grafana/dashboards/agent-observability.yaml"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def sub_show(rev: str, path: str) -> str:
    r = subprocess.run(["git", "-C", str(SUB), "show", f"{rev}:{path}"], capture_output=True, text=True)
    check(f"guard-proxy {rev[:7]}:{path} is readable from the submodule's history", r.returncode == 0,
          r.stderr.strip())
    return r.stdout


def py_shape(src: str) -> tuple:
    """(name, unit, attribute keys, provider literal) of the one observable gauge a proxy.py creates."""
    gauge = re.search(r'create_observable_gauge\(\s*"([^"]+)".*?unit="([^"]+)"', src, re.S)
    obs = re.search(r'yield Observation\([^,{]+, \{(.*?)\}\)', src, re.S)
    keys = dict(re.findall(r'"([^"]+)":\s*("[^"]*"|[A-Za-z_]\w*)', obs.group(1))) if obs else {}
    return (gauge.group(1) if gauge else None, gauge.group(2) if gauge else None, set(keys),
            keys.get("gen_ai.provider.name", "").strip('"'), src.count("create_observable_gauge("))


def py_block(src: str) -> str:
    """proxy.py's gauge code: from `if _meter is not None:` to the end of create_observable_gauge(...)."""
    m = re.search(r'^if _meter is not None:\n.*?create_observable_gauge\(.*?\)\n', src, re.S | re.M)
    return m.group(0) if m else ""


def go_block(src: str) -> str:
    """The Go build's registerCostGauge function, whole."""
    m = re.search(r'^func \(s \*Server\) registerCostGauge\(\) error \{\n.*?^\}\n', src, re.S | re.M)
    return m.group(0) if m else ""


print("== the shape before #784: guard-proxy 88b9b52 ==")
pin = subprocess.run(["git", "-C", str(REPO), "ls-tree", "HEAD", "--", "gitops/ai-layer/guard-proxy"],
                     capture_output=True, text=True).stdout.split()
pin_sha = pin[2] if len(pin) >= 3 and pin[0] == "160000" else ""
check("gitops/ai-layer/guard-proxy is a submodule gitlink", bool(pin_sha), f"ls-tree said {pin}")
before_has_counts = subprocess.run(["git", "-C", str(SUB), "merge-base", "--is-ancestor", COUNTS_FIX, BEFORE_PIN],
                                   capture_output=True).returncode == 0
check(f"88b9b52 predates the token counts ({COUNTS_FIX[:7]} is not in it), so it is the shape before #784",
      not before_has_counts)
before = py_shape(sub_show(BEFORE_PIN, "proxy.py"))
check(f"88b9b52's proxy.py creates one gauge, {NAME} in {UNIT}, observed with {sorted(ATTRS)} and "
      f"provider {PROVIDER}", before == (NAME, UNIT, ATTRS, PROVIDER, 1), str(before))

print("== the pinned proxy.py emits the same shape ==")
proxy_src = (SUB / "proxy.py").read_text(encoding="utf-8")
now = py_shape(proxy_src)
check(f"the pin {pin_sha[:7]}'s proxy.py creates one gauge, {NAME} in {UNIT}, observed with {sorted(ATTRS)} and "
      f"provider {PROVIDER}", now == (NAME, UNIT, ATTRS, PROVIDER, 1), str(now))
counts_parent = f"{COUNTS_FIX}~1"
check("the token-count commit left proxy.py's gauge code byte for byte as it was",
      bool(py_block(proxy_src)) and py_block(sub_show(counts_parent, "proxy.py")) == py_block(proxy_src))
check("proxy.py sets no gen_ai.usage.cost on any span (#784 leaves cost off the chat span)",
      "gen_ai.usage.cost" not in proxy_src)

print("== the Go build registers the same gauge ==")
go_src = (SUB / "internal/server/telemetry.go").read_text(encoding="utf-8")
go_fn = go_block(go_src)
check(f"registerCostGauge creates a Float64ObservableGauge {NAME} in {UNIT}",
      f'Float64ObservableGauge("{NAME}", metric.WithUnit("{UNIT}")' in go_fn, go_fn[:200])
# The Go build names attributes through constants weaver generates from the registry; resolve them to the strings.
gen = (SUB / "internal/telemetry/semconv/attributes_gen.go").read_text(encoding="utf-8")
keys = dict(re.findall(r'^\s*(\w+Key)\s*=\s*attribute\.Key\("([^"]+)"\)', gen, re.M))
values = dict(re.findall(r'^\s*(\w+)\s*=\s*"([^"]+)"', gen, re.M))
go_attrs = {keys.get(k, k) for k in re.findall(r'semconv\.(\w+Key)\b', go_fn)}
go_provider = [values.get(v) for v in re.findall(r'semconv\.GenAiProviderNameKey\.String\(semconv\.(\w+)\)', go_fn)]
check(f"and observes it with exactly {sorted(ATTRS)}, the provider {PROVIDER}",
      go_attrs == ATTRS and go_provider == [PROVIDER], f"{sorted(go_attrs)}, provider {go_provider}")
check("the token-count commit left registerCostGauge byte for byte as it was",
      bool(go_fn) and go_block(sub_show(counts_parent, "internal/server/telemetry.go")) == go_fn)
check("the Go build sets no gen_ai.usage.cost",
      not [p for p in SUB.rglob("*.go") if "gen_ai.usage.cost" in p.read_text(encoding="utf-8")
           or "GenAiUsageCost" in p.read_text(encoding="utf-8")])

print("== weaver declares the same gauge ==")
groups = {g.get("id"): g for f in sorted((REPO / "weaver/registry").glob("*.yaml")) if f.name != "manifest.yaml"
          for g in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("groups", [])}
cost = groups.get("metric.witb.guard_proxy.cost", {})
check(f"metric.witb.guard_proxy.cost is a {INSTRUMENT} named {NAME} in {UNIT}, as before #784",
      (cost.get("type"), cost.get("metric_name"), cost.get("instrument"), cost.get("unit"))
      == ("metric", NAME, INSTRUMENT, UNIT),
      str((cost.get("metric_name"), cost.get("instrument"), cost.get("unit"))))
declared = {a.get("ref"): a.get("requirement_level") for a in cost.get("attributes", [])}
check(f"its attributes are {sorted(ATTRS)}, both required, as before #784",
      declared == dict.fromkeys(ATTRS, "required"), str(declared))
check("no other registry group declares gen_ai.client.cost or gen_ai.usage.cost",
      not [gid for gid, g in groups.items() if gid != "metric.witb.guard_proxy.cost"
           and (g.get("metric_name") == NAME
                or any((a.get("ref") or a.get("id")) == "gen_ai.usage.cost" for a in g.get("attributes", [])))])


print("== run: the pinned gauge observes that attribute set, priced from the reply's token counts ==")
# A recording stand-in for the parts of the OpenTelemetry API proxy.py imports (the stock image carries no SDK).
GAUGES: list[dict] = []
otel = types.ModuleType("opentelemetry")
otel_trace = types.ModuleType("opentelemetry.trace")
otel_trace.SpanKind = types.SimpleNamespace(SERVER="SERVER", CLIENT="CLIENT", INTERNAL="INTERNAL")
otel_trace.StatusCode = types.SimpleNamespace(ERROR="ERROR", OK="OK", UNSET="UNSET")
otel_trace.Status = lambda code, description=None: (code, description)
otel_trace.get_tracer = lambda *a, **k: types.SimpleNamespace(start_as_current_span=None)
otel_trace.get_current_span = lambda: None
otel_metrics = types.ModuleType("opentelemetry.metrics")
otel_metrics.Observation = lambda value, attributes=None: (value, attributes)
otel_metrics.get_meter = lambda *a, **k: types.SimpleNamespace(
    create_observable_gauge=lambda name, callbacks=None, unit="", description="":
    GAUGES.append({"name": name, "callbacks": callbacks, "unit": unit}))
otel_propagate = types.ModuleType("opentelemetry.propagate")
otel_propagate.extract = lambda carrier: None
otel_propagate.inject = lambda carrier: None
otel.trace, otel.metrics, otel.propagate = otel_trace, otel_metrics, otel_propagate
sys.modules.update({"opentelemetry": otel, "opentelemetry.trace": otel_trace,
                    "opentelemetry.metrics": otel_metrics, "opentelemetry.propagate": otel_propagate})

ai_docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")) if d]
deploy = next(d for d in ai_docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
container = next(c for c in deploy["spec"]["template"]["spec"]["containers"] if c["name"] == "proxy")
os.environ.update({e["name"]: e["value"] for e in container["env"] if "value" in e})
sys.path.insert(0, str(SUB))
spec = importlib.util.spec_from_file_location("guard_proxy_949", SUB / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)  # safe: the server only starts under __main__
# The binding read needs the cluster API; offline it is the Deployment's MODEL_TIER, read without a request.
proxy._k8s_get = lambda path: None

check("proxy.py registered exactly one gauge with the stand-in meter", len(GAUGES) == 1, str(GAUGES))
gauge = GAUGES[0] if GAUGES else {"name": None, "unit": None, "callbacks": []}
check(f"it registered {NAME} in {UNIT}", (gauge["name"], gauge["unit"]) == (NAME, UNIT),
      str((gauge["name"], gauge["unit"])))


def observe() -> list[tuple]:
    return [o for cb in gauge["callbacks"] or [] for o in cb(None)]


idle = observe()
check(f"an idle cluster observes one series at 0, with exactly {sorted(ATTRS)}",
      len(idle) == 1 and idle[0][0] == 0 and set(idle[0][1]) == ATTRS, str(idle))
reply = {"result": {"kind": "task", "metadata": {"kagent_usage_metadata": {
    "promptTokenCount": 1234, "candidatesTokenCount": 56, "totalTokenCount": 1290}}}}
spent = proxy.record_usage(reply, "s-949")
price_in, price_out = proxy.prices_per_1k(proxy.bound_tier())
check("the chat span's counts (chat_usage_tokens) and the spend read the same reply: 1234 in, 56 out",
      proxy.chat_usage_tokens(reply) == (1234, 56))
check("the spend is those counts priced at the bound tier",
      abs(spent - (1234 / 1000.0 * price_in + 56 / 1000.0 * price_out)) < 1e-12 and spent > 0, str(spent))
after = observe()
model = proxy.request_model(proxy.bound_tier())
check(f"after the reply, the gauge observes {spent:.6f} USD for {model}, with exactly {sorted(ATTRS)}",
      len(after) == 1 and abs(after[0][0] - spent) < 1e-12 and set(after[0][1]) == ATTRS
      and after[0][1] == {"gen_ai.request.model": model, "gen_ai.provider.name": PROVIDER}, str(after))

print("== the dashboards and the leaderboard read it ==")
for rel in READERS:
    text = (REPO / rel).read_text(encoding="utf-8")
    queries = re.findall(r'query:\s*"([^"]*cost[^"]*)"', text)
    metrics = sorted({m for q in queries for m in re.findall(r'\b([a-z_]+(?:\.[a-z_]+)+)\{', q) if "cost" in m})
    check(f"{rel}: every cost query reads {NAME}", metrics == [NAME], str(metrics))
grafana = (REPO / GRAFANA).read_text(encoding="utf-8")
by = re.findall(r'sum by \(([a-z_]+)\) \(gen_ai_client_cost\)', grafana)
check(f"{GRAFANA}: the cost panel groups gen_ai_client_cost by an attribute the gauge carries",
      bool(by) and all(b in {a.replace(".", "_") for a in ATTRS} for b in by), str(by))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All gen_ai.client.cost gauge checks passed: the shape is the one it had before #784.")
