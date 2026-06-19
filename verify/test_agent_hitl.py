# ABOUTME: Render-gate check for P3 HITL + MCP restriction config on the canonical Agent.
# ABOUTME: Asserts toolNames excludes rogue tools, requireApproval gates the mutating tool, and the
# ABOUTME: kagent CEL constraint (requireApproval subset of toolNames) holds. No cluster needed.
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
docs = list(yaml.safe_load_all((REPO / "gitops" / "ai-layer" / "resources.yaml").read_text()))
agent = next(d for d in docs if d and d.get("kind") == "Agent")
tools = agent["spec"]["declarative"]["tools"]
mcp = next(t["mcpServer"] for t in tools if t.get("type") == "McpServer")
allow = set(mcp.get("toolNames", []))
approve = set(mcp.get("requireApproval", []))

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


check("Agent declares an McpServer tool with a toolNames allowlist", bool(allow))
check("rogue exfil tool NOT in allowlist (read_internal_config)", "read_internal_config" not in allow)
check("rogue clown tool NOT in allowlist (apply_optimization)", "apply_optimization" not in allow)
check("mutating tool requires HITL approval (apply_manifest)", "apply_manifest" in approve)
check("kagent CEL constraint holds: requireApproval is a subset of toolNames", approve <= allow)
check("McpServer item carries the required type discriminator",
      all(t.get("type") for t in tools))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll agent HITL/allowlist checks passed.")
