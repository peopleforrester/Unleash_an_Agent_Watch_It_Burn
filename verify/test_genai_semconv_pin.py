# ABOUTME: The GenAI semconv move of #784: weaver pins v1.41.1, guard-proxy's chat span declares its token counts, the
# ABOUTME: collector maps tool definitions, and nothing adopts the v1.38-v1.41 changes Datadog does not document.
"""#784 moved the weaver registry's pin from OpenTelemetry semantic conventions v1.37.0 to v1.41.1, the last release
that carries the GenAI conventions (from v1.42.0 they live in open-telemetry/semantic-conventions-genai, which has no
tagged release yet), and adopted the newer conventions only where Datadog's Agent Observability documents a mapping
(docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation, read 2026-11-03):

  - gen_ai.usage.input_tokens / gen_ai.usage.output_tokens, declared on guard-proxy's /chat `chat` span
    (span.witb.guard_proxy.chat), which Datadog reads as metrics.input_tokens / metrics.output_tokens;
  - gen_ai.tool.definitions (new in v1.38), which Datadog maps to meta.tool_definitions, written by the collector's
    transform/adk_model_content from kagent's model request (verify/test_adk_model_content_e2e.py runs it).

It left out what Datadog does not document: the cache and reasoning token attributes (v1.40, v1.41), MCP's own
attributes and spans (v1.39), gen_ai.agent.version (v1.40), and the invoke_agent client/internal split (v1.41).
This holds those choices offline. `weaver registry check` (.github/workflows/weaver-registry-check.yml) resolves the
registry against the pin.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
REG = REPO / "weaver/registry"
PIN = "v1.41.1"
PROXY = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text(encoding="utf-8")
VALUES = (REPO / "gitops/otel-collector/values.yaml").read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== the pin ==")
manifest = yaml.safe_load((REG / "manifest.yaml").read_text(encoding="utf-8"))
deps = manifest.get("dependencies") or []
check(f"weaver/registry depends on exactly one upstream registry, semantic-conventions {PIN}",
      len(deps) == 1 and deps[0].get("registry_path") ==
      f"https://github.com/open-telemetry/semantic-conventions/archive/refs/tags/{PIN}.zip[model]", str(deps))
for rel in ("weaver/registry/manifest.yaml", "weaver/registry/guard-proxy-spans.yaml",
            ".github/workflows/weaver-registry-check.yml", "docs/weaver-live-check.md"):
    text = (REPO / rel).read_text(encoding="utf-8")
    stale = [line.strip() for line in text.splitlines() if "v1.37.0" in line and "until #784" not in line
             and "from v1.37.0" not in line]
    check(f"{rel} names {PIN}, and v1.37.0 only as the pin it moved from", PIN in text and not stale, str(stale))

groups = [g for f in sorted(REG.glob("*.yaml")) if f.name != "manifest.yaml"
          for g in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("groups", [])]
chat = next((g for g in groups if g.get("id") == "span.witb.guard_proxy.chat"), {})
on_chat = {a.get("ref"): a for a in chat.get("attributes", [])}

print("== guard-proxy's /chat chat span ==")
check("span.witb.guard_proxy.chat is declared, an internal span",
      chat.get("type") == "span" and chat.get("span_kind") == "internal")
check("proxy.py opens an INTERNAL span named chat", 'start_as_current_span("chat", kind=SpanKind.INTERNAL)' in PROXY)
set_on_chat = sorted(set(re.findall(r'chat_span\.set_attribute\("([^"]+)"', PROXY)))
check("every attribute proxy.py sets on chat_span is declared on the group",
      set_on_chat and all(k in on_chat for k in set_on_chat), f"proxy.py {set_on_chat}, registry {sorted(on_chat)}")
must = sorted(k for k, a in on_chat.items() if a.get("requirement_level") in ("required", "opt_in"))
check("every required or opt-in attribute on the group is one proxy.py sets on chat_span",
      all(k in set_on_chat for k in must), f"declared {must}, set {set_on_chat}")
check("gen_ai.operation.name is required, so Datadog keeps and classifies the span",
      on_chat.get("gen_ai.operation.name", {}).get("requirement_level") == "required")
for key in ("gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens"):
    level = on_chat.get(key, {}).get("requirement_level")
    check(f"{key} is declared recommended: a turn whose forward fails ends without it "
          "(verify/test_chat_span_token_counts.py holds that every answered turn carries it)", level == "recommended", str(level))

print("== the token counts never count twice in Agent Observability ==")
check("filter/llmobs_one_root still drops guard-proxy's chat span from Agent Observability's copy (#746)",
      """'resource.attributes["service.name"] == "burritobot" and name == "chat" and kind == SPAN_KIND_INTERNAL'"""
      in VALUES)

print("== gen_ai.tool.definitions, the one v1.38+ attribute the collector writes ==")
check("transform/adk_model_content writes gen_ai.tool.definitions from the model request's function declarations",
      'set(attributes["gen_ai.tool.definitions"]' in VALUES and 'cache["adk_fns"][0]["functionDeclarations"]' in VALUES)

print("== nothing adopts what Datadog does not document ==")
NOT_ADOPTED = ("gen_ai.usage.cache_creation.input_tokens", "gen_ai.usage.cache_read.input_tokens",
               "gen_ai.usage.reasoning.output_tokens", "gen_ai.agent.version", "mcp.")
collector = "\n".join(p.read_text(encoding="utf-8") for p in sorted((REPO / "gitops/otel-collector").glob("*.yaml")))
refs = [a.get("ref") or a.get("id") or "" for g in groups for a in g.get("attributes", [])]
for name in NOT_ADOPTED:
    check(f"{name} is in no registry group", not [r for r in refs if r.startswith(name)])
    check(f"and no collector config writes it", f'attributes["{name}' not in collector)
check("no collector rule names an invoke_agent span kind other than the 1.37 shape (no client/internal split)",
      not re.search(r'invoke_agent.{0,80}SPAN_KIND_CLIENT|SPAN_KIND_CLIENT.{0,80}invoke_agent', collector))
check("no registry group declares an invoke_agent span (the v1.41 client/internal split is not adopted)",
      not [g.get("id") for g in groups if "invoke_agent" in str(g.get("id", "")) + str(g.get("name", ""))])
# v1.39's MCP conventions define their own spans as well as the mcp.* attributes; neither is declared here (#949).
mcp_groups = [g.get("id") for g in groups if re.search(r'(^|[._])mcp([._]|$)', str(g.get("id", "")).lower())
              or re.search(r'(^|[._])mcp([._]|$)', str(g.get("name", "")).lower())]
check("no registry group declares an MCP span (v1.39's MCP spans are not adopted)", not mcp_groups, str(mcp_groups))
check("no collector rule renames a span to MCP's span shape or sets mcp.method.name",
      "mcp.method.name" not in collector and not re.search(r'set\(\s*name\s*,[^)]*mcp', collector, re.I))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All GenAI semconv pin checks passed.")
