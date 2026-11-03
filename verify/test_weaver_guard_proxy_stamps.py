# ABOUTME: weaver/registry declares every attribute guard-proxy's proxy.py _stamp()s on its HTTP SERVER span, and
# ABOUTME: witb.guard.decision's enum members are exactly the values proxy.py stamps, both ways (#710).
"""weaver/registry/guard-proxy-spans.yaml says it is the source of truth for what proxy.py emits and must stay in
lockstep with its set_attribute calls. guard-proxy-agenticburn#8 added `_stamp`, which sets attributes on the POST
server span (span.witb.guard_proxy.http): session.id, OTel semconv, and witb.guard.decision, a custom enum. Neither
was declared. This reads the stamps out of the pinned submodule's proxy.py and holds the registry to them offline;
`weaver registry check` (.github/workflows/weaver-registry-check.yml) resolves the refs against semconv v1.41.1 (#784).
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


groups = [g for f in sorted(REG.glob("*.yaml")) if f.name != "manifest.yaml"
          for g in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("groups", [])]
by_id = {g["id"]: g for g in groups}
defined = {a["id"]: a for g in groups for a in g.get("attributes", []) if "id" in a}

stamps = re.findall(r'self\._stamp\("([^"]+)",\s*("([^"]*)"|[A-Za-z_][\w.]*)\)', PROXY)
keys = sorted({k for k, _, _ in stamps})
check("proxy.py stamps session.id and witb.guard.decision on its server span",
      {"session.id", "witb.guard.decision"} <= set(keys), str(keys))

server = by_id.get("span.witb.guard_proxy.http", {})
on_server = {a.get("ref") or a.get("id"): a for a in server.get("attributes", [])}
print("== every stamped attribute is on span.witb.guard_proxy.http ==")
for key in keys:
    check(f"{key} is declared on the server span", key in on_server, str(sorted(on_server)))
    if key.startswith("witb."):
        check(f"{key} is defined locally in an attribute_group (it is not upstream semconv)",
              key in defined and any(g.get("type") == "attribute_group" and key in
                                     [a.get("id") for a in g.get("attributes", [])] for g in groups))
    else:
        check(f"{key} is a ref to upstream semconv, not a local redefinition", key not in defined
              and "ref" in on_server.get(key, {}))
    level = on_server.get(key, {}).get("requirement_level")
    check(f"{key} is not required: proxy.py stamps it only on some turns",
          level is not None and level != "required", str(level))

print("== witb.guard.decision's members are the values proxy.py stamps ==")
stamped = {v for k, _, v in stamps if k == "witb.guard.decision"}
check("every witb.guard.decision stamp is a string literal",
      all(lit.startswith('"') for k, lit, _ in stamps if k == "witb.guard.decision"))
members = (((defined.get("witb.guard.decision") or {}).get("type") or {}).get("members")) or []
values = {m.get("value") for m in members}
check("the enum's member values equal the stamped values, both ways", values == stamped,
      f"registry {sorted(v for v in values if v)}, proxy.py {sorted(stamped)}")
check("each member's id is its value, and each has a brief",
      bool(members) and all(m.get("id") == m.get("value") and m.get("brief") for m in members))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    raise SystemExit(1)
print("The Weaver registry declares every attribute guard-proxy stamps on its server span.")
