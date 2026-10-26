# ABOUTME: Renders the #480 spike's agentgateway config: the committed config plus one evil-mcp bind with the
# ABOUTME: tool-pin processor on its tools/list response. Same function for the local bed and the cluster.
"""The pinned bind, kept in one place so the local bed and the cluster check run the same shape.

    python gateway_bind.py cluster  > agentgateway-config.yaml   # the committed ConfigMap plus bind 3004
    python gateway_bind.py local    > local.yaml                 # the local bed's gateway config

The bind is its own port with one MCP target, so:
  - the target is the only backend, and the tool names reach kagent unprefixed (measured on the local
    bed, see README.md), which keeps get_weather's poisoned description pointing at real tool names;
  - the processor's failClosed only ever refuses this bind's tools/list. The A2A bind (3000) and
    workshop-mcp (3001) do not route through it.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[3]
GATEWAY = REPO / "gitops/ai-layer/agentgateway.yaml"

# 3004 on the cluster: #514 gave :3003 to the agentgateway-c7 container, which shares the pod's network
# namespace, so a 3003 bind here would collide with it. The local bed keeps its own ports (local_config).
PINNED_PORT = 3004
TARGET = "evil-mcp"


def pinned_bind(port: int, target_url: str, processor_host: str, name: str = "evil-mcp-pinned") -> dict:
    # Named, so the gateway's request log says route=default/<name> and a tools/list on this bind can be
    # told from one on another bind; src.addr then says whether kagent's controller or the agent sent it.
    return {
        "port": port,
        "listeners": [{
            "name": name,
            "protocol": "HTTP",
            "routes": [{
                "name": name,
                "policies": {
                    "mcpGuardrails": {
                        "processors": [{
                            "kind": "remote",
                            "host": processor_host,
                            "failureMode": "failClosed",
                            # The list is judged on the way back; a call to a tool the last list did
                            # not approve is refused on the way in (tool_pin.py, check_request).
                            "methods": {"tools/list": "response", "tools/call": "request"},
                        }],
                    },
                },
                "backends": [{"mcp": {"targets": [{"name": TARGET, "mcp": {"host": target_url}}]}}],
            }],
        }],
    }


def committed_config() -> tuple[dict, dict]:
    """(the agentgateway-config ConfigMap, its parsed config.yaml) as committed."""
    for doc in yaml.safe_load_all(GATEWAY.read_text()):
        if doc and doc.get("kind") == "ConfigMap" and doc["metadata"]["name"] == "agentgateway-config":
            return doc, yaml.safe_load(doc["data"]["config.yaml"])
    raise SystemExit(f"no agentgateway-config ConfigMap in {GATEWAY}")


def cluster_config() -> dict:
    cfg = committed_config()[1]
    cfg["binds"].append(pinned_bind(
        PINNED_PORT,
        "http://evil-mcp-shim.agent.svc.cluster.local:8000/mcp",
        "tool-pin.agent.svc.cluster.local:9001",
    ))
    return cfg


def local_config(evil: str, tampered: str, processor: str) -> dict:
    """The local bed: 3001 is evil-mcp with NO processor (the stand-in for an unrelated bind), 3003 the
    pinned evil-mcp, 3004 the same pin in front of a copy whose get_weather description was edited."""
    unguarded = pinned_bind(3001, evil, processor, "unguarded")
    del unguarded["listeners"][0]["routes"][0]["policies"]
    return {"binds": [unguarded, pinned_bind(3003, evil, processor), pinned_bind(3004, tampered, processor, "rug-pulled")]}


def as_configmap(cfg: dict) -> dict:
    cm = committed_config()[0]
    cm["data"]["config.yaml"] = yaml.safe_dump(cfg, sort_keys=False)
    return cm


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    if which == "cluster":
        sys.stdout.write(yaml.safe_dump(as_configmap(cluster_config()), sort_keys=False))
    elif which == "local":
        sys.stdout.write(yaml.safe_dump(local_config(
            "http://127.0.0.1:8000/mcp", "http://127.0.0.1:8010/mcp", "127.0.0.1:9001"), sort_keys=False))
    else:
        raise SystemExit("usage: gateway_bind.py cluster|local")
