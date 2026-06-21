# ABOUTME: The "good" workshop MCP server: the legit tools the scoped agent is allowed to use
# ABOUTME: (list_pods, apply_manifest, get_secret). Synthetic demo data only; counterpart to evil-mcp-shim.

# This is the trusted MCP the agent normally uses. Beat 3 contrasts it with evil-mcp-shim (the rogue
# server whose poisoned tool descriptions the MCP-authz allowlist blocks). The tool NAMES here must
# match the agent's toolNames allowlist in resources.yaml (list_pods / apply_manifest / get_secret).
# Everything returned is obviously synthetic; this server reaches nothing real.

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("workshop-mcp", host="0.0.0.0", port=8000)


@mcp.tool(description="List the pods in the attendee's namespace.")
def list_pods() -> str:
    """Returns a synthetic pod listing (demo data; reaches nothing real)."""
    return (
        "NAME                     READY   STATUS    RESTARTS\n"
        "workshop-agent-0         1/1     Running   0\n"
        "guard-proxy              1/1     Running   0\n"
        "llm-guard                1/1     Running   0"
    )


@mcp.tool(description="Apply a Kubernetes manifest to the attendee's namespace. Mutating; requires approval.")
def apply_manifest(manifest: str = "") -> str:
    """The one mutating tool, gated by the agent's requireApproval (HITL). Demo ack only; applies nothing."""
    return "manifest accepted (synthetic demo: nothing was actually applied)."


@mcp.tool(description="Read a non-sensitive workshop configuration value by name.")
def get_secret(name: str = "") -> str:
    """Returns a synthetic, obviously-fake value (no real secret is ever exposed)."""
    return f"{name or 'value'}=FAKE-WORKSHOP-CONFIG-synthetic"


if __name__ == "__main__":
    # Streamable HTTP so agentgateway / kagent can front the server over the network in-cluster.
    mcp.run(transport="streamable-http")
