# ABOUTME: weaver/registry declares every attribute proxy.py sets on each of its spans and on the gen_ai.client.cost
# ABOUTME: gauge, under the group for that span, and proxy.py sets every attribute a group makes required (#782).
"""guard-proxy-agenticburn's Go build generates its attribute keys from weaver/registry (its scripts/gen-semconv.sh),
and wrote gen_ai.request.model, error.type and gen_ai.provider.name by hand until the registry declared them (#782).
This reads the pinned submodule's proxy.py offline: which span variable each set_attribute call is on, which span
name and kind each variable is opened with, and the cost gauge's name, unit and attributes, and holds the registry to
all of it. test_weaver_guard_proxy_stamps.py covers the _stamp calls; test_weaver_registry_check.py (E2E tier) runs
weaver itself, which resolves each ref against semconv v1.41.1 (#784).
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
PROXY = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text(encoding="utf-8")
REG = REPO / "weaver/registry"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


groups = {g["id"]: g for f in sorted(REG.glob("*.yaml")) if f.name != "manifest.yaml"
          for g in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("groups", [])}


def declared(gid: str) -> dict:
    return {a.get("ref") or a.get("id"): a for a in groups.get(gid, {}).get("attributes", [])}


# Each span proxy.py opens: the variable its attributes are set on, its name and kind, and the group that is its
# contract. _sp is self._server_span, read back in _send and _stamp; _root_span is trace.get_current_span() inside
# the /chat handler, which runs under do_POST's server span, so it is that span too.
SPANS = {
    "server_span": ("span.witb.guard_proxy.http", r'f"POST \{self\.path\}"', "SERVER"),
    "_sp": ("span.witb.guard_proxy.http", None, None),
    "_root_span": ("span.witb.guard_proxy.http", None, None),
    "san_span": ("span.witb.guard_proxy.sanitize", r'"sanitize"', "INTERNAL"),
    "client_span": ("span.witb.guard_proxy.egress", r'"agent\.forward"', "CLIENT"),
    "chat_span": ("span.witb.guard_proxy.chat", r'"chat"', "INTERNAL"),
}

print("== proxy.py's span variables are the ones this test maps to groups ==")
calls = re.findall(r'\b([A-Za-z_]\w*)\.set_attribute\("([^"]+)"', PROXY)
check("proxy.py sets span attributes", bool(calls))
unmapped = sorted({v for v, _ in calls} - set(SPANS))
check("every span variable proxy.py sets a literal attribute on is mapped to a group", not unmapped, str(unmapped))
check("_sp is the server span, read back from self._server_span",
      PROXY.count('_sp = getattr(self, "_server_span", None)') == 2 and "self._server_span = server_span" in PROXY)
check("_root_span is the current span, which on /chat is the POST server span",
      "_root_span = trace.get_current_span()" in PROXY)
for var, (gid, name, kind) in SPANS.items():
    if name is None:
        continue
    # The server span's call carries context=extract(...), so the kind is looked for within the next few lines.
    opened = re.findall(rf'start_as_current_span\(\s*{name},.{{0,160}}?kind=SpanKind\.(\w+)', PROXY, re.S)
    label = re.sub(r"\\(.)", r"\1", name)
    group = groups.get(gid, {})
    check(f"{var} is opened as {label} with kind {kind}", bool(opened) and set(opened) == {kind}, str(opened))
    check(f"{gid} is a span group of kind {kind.lower()}", group.get("type") == "span"
          and group.get("span_kind") == kind.lower(), str({k: group.get(k) for k in ("type", "span_kind")}))
    check(f"{var}'s variable is bound from that span", re.search(
        rf'with \w+ as {var}:', PROXY) is not None)

print("== every attribute proxy.py sets on a span is declared on that span's group ==")
set_on: dict[str, set[str]] = {}
for var, key in calls:
    if var in SPANS:
        set_on.setdefault(SPANS[var][0], set()).add(key)
for gid, keys in sorted(set_on.items()):
    on_group = declared(gid)
    for key in sorted(keys):
        check(f"{key} is declared on {gid}", key in on_group, str(sorted(on_group)))

print("== the attributes #782 declares, where the Go build writes them by hand until regeneration ==")
for gid, key in (("span.witb.guard_proxy.sanitize", "gen_ai.request.model"),
                 ("span.witb.guard_proxy.http", "gen_ai.request.model"),
                 ("span.witb.guard_proxy.chat", "gen_ai.request.model"),
                 ("span.witb.guard_proxy.egress", "error.type")):
    check(f"{key} is on {gid} and proxy.py sets it there", key in declared(gid) and key in set_on.get(gid, set()))
err = declared("span.witb.guard_proxy.egress").get("error.type", {})
check("error.type is conditionally required on the egress span, since proxy.py sets it only when the forward fails",
      isinstance(err.get("requirement_level"), dict) and "conditionally_required" in err["requirement_level"])
for key in ("gen_ai.operation.name", "gen_ai.request.model"):
    level = declared("span.witb.guard_proxy.http").get(key, {}).get("requirement_level")
    check(f"{key} on the server span is conditional: proxy.py sets it on the /chat root only",
          isinstance(level, dict) and "conditionally_required" in level, str(level))

print("== every attribute a span group requires is one proxy.py sets on that span ==")
for gid, group in sorted(groups.items()):
    if group.get("type") != "span":
        continue
    for key, a in sorted(declared(gid).items()):
        if a.get("requirement_level") == "required":
            check(f"{gid} requires {key}, and proxy.py sets it", key in set_on.get(gid, set()))

print("== every attribute ref is to upstream semconv; witb.* are defined locally ==")
for gid, group in sorted(groups.items()):
    for key, a in sorted(declared(gid).items()):
        if key.startswith("witb."):
            continue
        check(f"{gid}: {key} is a ref, not a local redefinition", "ref" in a and "id" not in a)

print("== the gen_ai.client.cost gauge is metric.witb.guard_proxy.cost ==")
gauge = re.search(r'create_observable_gauge\(\s*"([^"]+)".*?unit="([^"]+)"', PROXY, re.S)
# The spend is the first argument: _cost["usd"] at pin 88b9b52, and each model's usd from guard-proxy-agenticburn#38
# (1cfa6d6), which yields one series per model. Either way there is one yield, so the attributes read are all of them.
obs = re.search(r'yield Observation\([^,{]+, \{(.*?)\}\)', PROXY, re.S)
check("proxy.py creates one observable gauge and observes the spend with literal attribute keys",
      bool(gauge) and bool(obs) and PROXY.count("create_observable_gauge(") == 1
      and PROXY.count("yield Observation(") == 1)
observed = dict(re.findall(r'"([^"]+)":\s*("[^"]*"|[A-Za-z_]\w*)', obs.group(1))) if obs else {}
cost = groups.get("metric.witb.guard_proxy.cost", {})
check("the group is a gauge named as proxy.py names it, in its unit",
      bool(gauge) and (cost.get("type"), cost.get("metric_name"), cost.get("instrument"), cost.get("unit"))
      == ("metric", gauge.group(1), "gauge", gauge.group(2)),
      str((cost.get("metric_name"), cost.get("instrument"), cost.get("unit"))))
on_metric = declared("metric.witb.guard_proxy.cost")
check(f"its attributes are exactly the ones proxy.py observes ({sorted(observed)})",
      set(on_metric) == set(observed) and bool(observed), str(sorted(on_metric)))
check('proxy.py observes gen_ai.provider.name as the literal "aws.bedrock"',
      observed.get("gen_ai.provider.name") == '"aws.bedrock"', str(observed.get("gen_ai.provider.name")))
check("both are required on the gauge: every observation carries them",
      all(a.get("requirement_level") == "required" for a in on_metric.values()) and bool(on_metric))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    raise SystemExit(1)
print("The Weaver registry declares every attribute guard-proxy sets on its spans and its cost gauge.")
