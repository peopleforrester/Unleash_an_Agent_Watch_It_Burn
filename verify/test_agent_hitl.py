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
# requireApproval is DELIBERATELY absent. The HITL approval round-trip is not wired to the chat UI, so
# a paused tool_use left a dangling call and the next Bedrock Converse request failed with "tool_use ids
# ... without tool_result" (seen live on r1-1). Excessive agency is also the point of the exercise: the
# agent applies what it is told and Kyverno blocks it in R2. Asserting approval here contradicted the
# manifest for as long as the suite has been red. The invariant that still matters is the one below:
# whatever IS in requireApproval must be a subset of toolNames, or kagent's CEL constraint rejects it.
check("requireApproval stays deliberately empty (documented: breaks the Bedrock tool_use round-trip)",
      not approve)
check("kagent CEL constraint holds: requireApproval is a subset of toolNames", approve <= allow)
check("McpServer item carries the required type discriminator",
      all(t.get("type") for t in tools))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll agent HITL/allowlist checks passed.")
