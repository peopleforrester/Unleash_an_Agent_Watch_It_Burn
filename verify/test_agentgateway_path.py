# ABOUTME: Render gate for which traffic agentgateway actually carries: the A2A hop and workshop-mcp go
# ABOUTME: through it, evil-mcp (C7's rogue tools) and the default model calls do not (#239).
"""Why this exists (#239).

Three documents disagreed about what routes through agentgateway. #239 said nothing did. A code comment
said the agent dials workshop-mcp directly. The #236 audit said every model call does. Each was read off
a different file at a different time, and all three were wrong about something.

The evaluation in docs/research/2026-10-24-agentgateway-evaluation.md rests on the table below. Its
conclusion for C7 depends on one row in particular: the rogue tools live on evil-mcp, the agent reaches
evil-mcp without the gateway, so a gateway policy cannot be C7's control and the kagent toolNames list
is. If any row here changes, the evaluation's table and that conclusion need re-reading with it.
"""
from __future__ import annotations

import pathlib
import sys
from urllib.parse import urlparse

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
RESOURCES = list(yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()))
GATEWAY = list(yaml.safe_load_all((REPO / "gitops/ai-layer/agentgateway.yaml").read_text()))
EVALUATION = "docs/research/2026-10-24-agentgateway-evaluation.md"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


def one(docs: list, kind: str, name: str) -> dict:
    found = [d for d in docs if d and d.get("kind") == kind and d.get("metadata", {}).get("name") == name]
    check(f"{kind}/{name} is declared exactly once", len(found) == 1)
    return found[0] if found else {}


def via_gateway(url: str, port: int) -> bool:
    u = urlparse(url)
    return (u.hostname or "").split(".")[0] == "agentgateway" and u.port == port


config = yaml.safe_load(one(GATEWAY, "ConfigMap", "agentgateway-config").get("data", {}).get("config.yaml", "{}"))
binds = {b["port"]: b for b in config.get("binds", [])}


def bind_routes(port: int) -> list:
    return [r for l in binds.get(port, {}).get("listeners", []) for r in l.get("routes", [])]


# --- port 3000: every chat message (guard-proxy -> agentgateway -> workshop-agent, A2A) -------------
proxy = one(RESOURCES, "Deployment", "guard-proxy")
env = {e["name"]: e.get("value") for c in proxy.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
       for e in c.get("env", [])}
check("guard-proxy forwards to agentgateway :3000", via_gateway(env.get("AGENT_URL") or "", 3000),
      f"AGENT_URL={env.get('AGENT_URL')!r}")
a2a_hosts = [b.get("host", "") for r in bind_routes(3000) for b in r.get("backends", [])]
check("agentgateway :3000 proxies to workshop-agent:8080",
      any(h.startswith("workshop-agent.") and h.endswith(":8080") for h in a2a_hosts), f"{a2a_hosts}")

# --- port 3001: every workshop-mcp tool call -----------------------------------------------------------
workshop = one(RESOURCES, "RemoteMCPServer", "workshop-mcp").get("spec", {})
check("workshop-mcp RemoteMCPServer is dialled through agentgateway :3001",
      via_gateway(workshop.get("url", ""), 3001), f"url={workshop.get('url')!r}")
mcp_targets = [t.get("mcp", {}).get("host", "") for r in bind_routes(3001) for b in r.get("backends", [])
               for t in b.get("mcp", {}).get("targets", [])]
check("agentgateway :3001 targets workshop-mcp:8000/mcp",
      any(urlparse(h).hostname and urlparse(h).hostname.startswith("workshop-mcp.") and urlparse(h).port == 8000
          and urlparse(h).path == "/mcp" for h in mcp_targets), f"{mcp_targets}")

# --- C7's server: the agent dials evil-mcp directly -----------------------------------------------------
evil = one(RESOURCES, "RemoteMCPServer", "evil-mcp").get("spec", {})
check("evil-mcp RemoteMCPServer is NOT routed through agentgateway",
      (urlparse(evil.get("url", "")).hostname or "").split(".")[0] == "evil-mcp-shim",
      f"url={evil.get('url')!r}; if this now goes through the gateway, re-read {EVALUATION}")
check("no agentgateway MCP target serves evil-mcp", not any("evil-mcp" in h for h in mcp_targets), f"{mcp_targets}")

# --- port 3002: model calls go through it only when the Agent is switched to a gateway-* ModelConfig ----
agent = one(RESOURCES, "Agent", "workshop-agent").get("spec", {}).get("declarative", {})
bound = one(RESOURCES, "ModelConfig", agent.get("modelConfig", "")).get("spec", {})
bound_url = bound.get("openAI", {}).get("baseUrl", "")
check("the agent's committed ModelConfig calls its provider directly, not agentgateway :3002",
      not via_gateway(bound_url, 3002),
      f"modelConfig={agent.get('modelConfig')!r} baseUrl={bound_url!r}; update the table in {EVALUATION}")
for name in ("gateway-bedrock-nova", "gateway-local-qwen3"):
    url = one(RESOURCES, "ModelConfig", name).get("spec", {}).get("openAI", {}).get("baseUrl", "")
    check(f"ModelConfig {name} is the opt-in route through agentgateway :3002", via_gateway(url, 3002), url)

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("\nPASS: agentgateway carries the A2A hop and workshop-mcp; evil-mcp and default inference bypass it")
