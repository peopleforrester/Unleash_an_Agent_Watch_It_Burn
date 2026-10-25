# ABOUTME: Render gate for which traffic agentgateway actually carries: the A2A hop, workshop-mcp and evil-mcp
# ABOUTME: (C7's rogue tools, on its own bind) go through it; the default model calls do not (#239, #514).
"""Why this exists (#239).

Three documents disagreed about what routes through agentgateway. #239 said nothing did. A code comment
said the agent dials workshop-mcp directly. The #236 audit said every model call does. Each was read off
a different file at a different time, and all three were wrong about something.

The evaluation in docs/research/2026-10-24-agentgateway-evaluation.md rests on the table below. Its C7
row changed with #514: evil-mcp is now dialled through the gateway on its own bind (:3003), served by the
agentgateway-c7 container from its own ConfigMap. A second target on :3001 would have prefixed the tool
names, so this also pins that the bind has exactly one target and workshop-mcp's has no evil-mcp. If any
row here changes, the evaluation's table needs re-reading with it.
"""
from __future__ import annotations

import pathlib
import re
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
c7_config = yaml.safe_load(one(GATEWAY, "ConfigMap", "agentgateway-c7-config").get("data", {}).get("config.yaml", "{}"))
c7_binds = {b["port"]: b for b in c7_config.get("binds", [])}


def bind_routes(port: int, where: dict | None = None) -> list:
    return [r for l in (binds if where is None else where).get(port, {}).get("listeners", [])
            for r in l.get("routes", [])]


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

# --- port 3003: every evil-mcp tool call, C7's rogue server on its own bind (#514) ----------------------
evil = one(RESOURCES, "RemoteMCPServer", "evil-mcp").get("spec", {})
check("evil-mcp RemoteMCPServer is dialled through agentgateway :3003",
      via_gateway(evil.get("url", ""), 3003) and urlparse(evil.get("url", "")).path == "/mcp",
      f"url={evil.get('url')!r}; if this stops going through the gateway, re-read {EVALUATION}")
check("no agentgateway-config bind serves :3003 (it is the agentgateway-c7 container's)", 3003 not in binds,
      f"{sorted(binds)}")
check("agentgateway-c7-config has exactly one bind, :3003", sorted(c7_binds) == [3003], f"{sorted(c7_binds)}")
c7_targets = [t for r in bind_routes(3003, c7_binds) for b in r.get("backends", [])
              for t in b.get("mcp", {}).get("targets", [])]
c7_hosts = [t.get("mcp", {}).get("host", "") for t in c7_targets]
check("agentgateway :3003 has exactly one MCP target, so the tool names are not prefixed", len(c7_targets) == 1,
      f"{c7_hosts}")
check("agentgateway :3003 targets evil-mcp-shim:8000/mcp",
      len(c7_hosts) == 1 and (urlparse(c7_hosts[0]).hostname or "").startswith("evil-mcp-shim.")
      and urlparse(c7_hosts[0]).port == 8000 and urlparse(c7_hosts[0]).path == "/mcp", f"{c7_hosts}")
check("workshop-mcp's :3001 bind carries no evil-mcp target", not any("evil-mcp" in h for h in mcp_targets),
      f"{mcp_targets}")

deployment = one(GATEWAY, "Deployment", "agentgateway").get("spec", {}).get("template", {}).get("spec", {})
containers = {c["name"]: c for c in deployment.get("containers", [])}
c7 = containers.get("agentgateway-c7", {})
volumes = {v["name"]: v for v in deployment.get("volumes", [])}
c7_mounts = {m["mountPath"]: m["name"] for m in c7.get("volumeMounts", [])}
c7_cm_volume = c7_mounts.get("/etc/agentgateway-c7", "")
check("the agentgateway-c7 container reads /etc/agentgateway-c7/config.yaml",
      c7.get("args") == ["-f", "/etc/agentgateway-c7/config.yaml"], f"{c7.get('args')}")
check("which is agentgateway-c7-config, mounted as a directory (a subPath file never sees a ConfigMap change)",
      volumes.get(c7_cm_volume, {}).get("configMap", {}).get("name") == "agentgateway-c7-config"
      and not any(m.get("subPath") for m in c7.get("volumeMounts", [])), f"{c7.get('volumeMounts')}")
c7_ports = {p["name"]: p["containerPort"] for p in c7.get("ports", [])}
service = one(GATEWAY, "Service", "agentgateway").get("spec", {})
svc_ports = {p["port"]: p.get("targetPort") for p in service.get("ports", [])}
check("the agentgateway Service sends :3003 to the agentgateway-c7 container's port 3003",
      c7_ports.get(svc_ports.get(3003)) == 3003, f"service={svc_ports} c7={c7_ports}")

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

# --- the working docs say evil-mcp goes through the gateway ------------------------------------------------
# #514 moved evil-mcp onto :3003 but corrected only its own file list; these six went on describing the old,
# gateway-less hop (#563). A line naming that server may not say it is dialled without the gateway. Dated
# research notes and decisions.md are records and are not checked. #514's own files: test_c7_gateway_reader.py.
ROUTING_DOCS = (
    "verify/test_beat3_mcp.py",
    "challenges/03-bad-mcp-excessive-agency/BUILD-SPIKE.md",
    "agent/GATEWAY-NOTES.md",
    "docs/STACK-WALKTHROUGH.md",
    "docs/KUBECON-ABSTRACT-READINESS.md",
    "docs/READINESS-CHECKLIST.md",
)
for rel in ROUTING_DOCS:
    lines = (REPO / rel).read_text(encoding="utf-8").splitlines()
    stale = [i for i, l in enumerate(lines, 1)
             if "evil-mcp" in l and re.search(r"dial(?:s|led) (?:evil-mcp(?:-shim)? )?direct", l)]
    check(f"{rel} does not say evil-mcp is dialled direct (lines {stale})", not stale)

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("\nPASS: agentgateway carries the A2A hop, workshop-mcp and evil-mcp (:3003); default inference bypasses it")
