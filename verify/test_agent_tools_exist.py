# ABOUTME: Every tool the Agent CR declares must exist in the MCP server that serves it, and the Argo
# ABOUTME: ignore must be narrow enough that our own changes to the tool list still reach a cluster.
"""Guards the agent's tool list against renames and against a too-broad ignore (#349).

`get_recipe` was renamed to `get_vault_entry`. The manifest was updated correctly and every test passed.
Challenge 5 was still impossible on every live cluster, because `ignoreDifferences` covered
`.spec.declarative.tools` wholesale, so Argo never reconciled the field and reported Synced and Healthy the
whole time. The agent asked for a tool that no longer existed, fell back to a shell with no kubectl in it,
and a student could not win a challenge that the repo said was fine.

Two checks, because the bug had two halves and either alone would have let it through:

1. Every declared tool exists in the server that serves it. Catches a rename or a typo at build time.
2. The Argo ignore is scoped to the ONE list Challenge 7 patches. Catches the ignore widening back out,
   which is what turned a caught-at-build problem into a silent live one.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
RES = list(yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")))
APP = (REPO / "gitops/apps/ai-layer.yaml").read_text(encoding="utf-8")

# The tools each server actually defines, read from the source the container runs.
SERVERS = {
    "workshop-mcp": REPO / "gitops/ai-layer/workshop-mcp-server.py",
    "evil-mcp": REPO / "gitops/ai-layer/server.py",
}

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


agent = next((d for d in RES if d and d.get("kind") == "Agent"), None)
check("the Agent CR is in the manifest", agent is not None)
if agent is None:
    sys.exit(1)

declared = {}
for entry in agent["spec"]["declarative"]["tools"]:
    srv = entry.get("mcpServer") or {}
    declared[srv.get("name")] = list(srv.get("toolNames") or [])

print("== every declared tool exists in the server that serves it ==")
for server, path in SERVERS.items():
    src = path.read_text(encoding="utf-8")
    served = set(re.findall(r"^def ([a-z][a-z0-9_]*)\(", src, re.M))
    names = declared.get(server)
    check(f"{server} is declared on the agent", names is not None)
    for tool in names or []:
        check(f"{server}.{tool} exists in {path.name}", tool in served)

print("== the rename that caused this cannot come back ==")
check("get_recipe is declared nowhere", all("get_recipe" not in v for v in declared.values()))
check("get_vault_entry IS declared, since Challenge 5 needs it",
      "get_vault_entry" in declared.get("workshop-mcp", []))

print("== the Argo ignore is narrow enough that our own changes still land ==")
# The wholesale ignore is what made the rename invisible. Only C7's list may be ignored.
check("the whole tools array is NOT ignored",
      "- '.spec.declarative.tools'" not in APP)
check("only evil-mcp's toolNames is ignored",
      'select(.mcpServer.name == "evil-mcp") | .mcpServer.toolNames' in APP)
# Selecting by name rather than array index survives a reordering of the tool servers.
check("the ignore selects by server name, not array index",
      ".spec.declarative.tools[1]" not in APP and "tools/1/" not in APP)
check("the comment records why it was narrowed", "Challenge 5 was" in APP and "Synced and Healthy" in APP)

print("== Challenge 7 still patches the list the ignore protects ==")
TOGGLE = (REPO / "challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh").read_text(encoding="utf-8")
check("C7's toggle targets evil-mcp's toolNames", "toolNames" in TOGGLE)
check("evil-mcp is the second server, which is what C7's JSON pointer assumes",
      list(declared.keys())[1] == "evil-mcp")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All agent-tool checks passed.")
