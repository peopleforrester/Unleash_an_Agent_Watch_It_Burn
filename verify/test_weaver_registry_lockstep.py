# ABOUTME: Holds weaver/registry/guard-proxy-spans.yaml in lockstep with the HTTP SERVER span attributes proxy.py sets
# ABOUTME: (#710): every key it stamps is declared, and witb.guard.decision's members are exactly the values it stamps.
"""The registry says it is the source of truth for what guard-proxy/proxy.py emits. Since guard-proxy-agenticburn#8,
proxy.py's _stamp puts session.id and witb.guard.decision on the `POST <path>` server span, and the registry missed
both until #710. This reads the pinned submodule's proxy.py, offline, and fails on the next such drift:

  - every key do_POST, _send or _stamp sets on the server span is an attribute of span.witb.guard_proxy.http;
  - every witb.* attribute the registry refs is defined in the registry's own registry.witb.guard group;
  - witb.guard.decision's enum members are the values proxy.py stamps, no more and no fewer, each id its value.

Whether the refs resolve against OTel semconv v1.37.0 is weaver's to say: test_weaver_registry_check.py runs the
pinned weaver on the same registry in the E2E tools tier.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
PROXY = REPO / "gitops/ai-layer/guard-proxy/proxy.py"
SPANS = REPO / "weaver/registry/guard-proxy-spans.yaml"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


proxy = PROXY.read_text()
groups = {g["id"]: g for g in yaml.safe_load(SPANS.read_text())["groups"]}
http = groups.get("span.witb.guard_proxy.http", {})
witb = groups.get("registry.witb.guard", {})
http_attrs = {a.get("ref") or a.get("id"): a for a in http.get("attributes", [])}
local = {a["id"]: a for a in witb.get("attributes", [])}

print("== every attribute proxy.py sets on the HTTP SERVER span is declared on it ==")
# do_POST sets the first two on server_span, _send sets the status through _sp, and _stamp the /chat ones.
server_keys = set(re.findall(r'\bserver_span\.set_attribute\("([^"]+)"', proxy))
server_keys |= set(re.findall(r'\b_sp\.set_attribute\("([^"]+)"', proxy))
server_keys |= set(re.findall(r'\bself\._stamp\("([^"]+)"', proxy))
check(f"proxy.py sets keys on the server span, session.id and witb.guard.decision among them ({sorted(server_keys)})",
      {"http.request.method", "url.path", "http.response.status_code", "session.id",
       "witb.guard.decision"} <= server_keys)
for key in sorted(server_keys):
    check(f"span.witb.guard_proxy.http declares {key}", key in http_attrs, str(sorted(http_attrs)))
for key in ("session.id", "witb.guard.decision"):
    a = http_attrs.get(key, {})
    check(f"{key} is a ref, conditionally required, as _chat_turn sets it only on some turns",
          a.get("ref") == key and isinstance(a.get("requirement_level"), dict)
          and "conditionally_required" in a["requirement_level"], str(a))

print("== the witb.* attributes are defined here, the rest come from OTel semconv ==")
check("registry.witb.guard is an attribute_group", witb.get("type") == "attribute_group", str(witb.get("type")))
refs = {a["ref"] for g in groups.values() for a in g.get("attributes", []) if "ref" in a}
for key in sorted(r for r in refs if r.startswith("witb.")):
    check(f"{key} is defined in registry.witb.guard", key in local, str(sorted(local)))
check("session.id is not defined locally: it is OTel semconv's", "session.id" not in local)

print("== witb.guard.decision's members are the values proxy.py stamps ==")
stamped = set(re.findall(r'\bself\._stamp\("witb\.guard\.decision",\s*"([^"]+)"\)', proxy))
check(f"proxy.py stamps the six guards ({sorted(stamped)})",
      stamped == {"input_blocklist", "input_classifier", "topic", "rate_limit", "budget", "output_redacted"})
decision = local.get("witb.guard.decision", {})
members = (decision.get("type") or {}).get("members", []) if isinstance(decision.get("type"), dict) else []
values = {m.get("value") for m in members}
check(f"the enum's members are exactly those values ({sorted(v for v in values if v)})", values == stamped,
      f"missing {sorted(stamped - values)}, extra {sorted(v for v in values - stamped if v)}")
for m in members:
    check(f"member {m.get('id')}: its id is its value, with a brief and a stability",
          m.get("id") == m.get("value") and bool(m.get("brief")) and bool(m.get("stability")), str(m))
check("witb.guard.decision has a brief, a stability and examples",
      bool(decision.get("brief")) and bool(decision.get("stability")) and bool(decision.get("examples")))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nThe weaver registry is in lockstep with proxy.py's server span.")
