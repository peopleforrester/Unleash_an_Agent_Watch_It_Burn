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
# The Agent and its ignores are the workshop-agent Application's since #707, out of ai-layer.
AGENT_DOCS = list(yaml.safe_load_all((REPO / "gitops/workshop-agent/agent.yaml").read_text(encoding="utf-8")))
APP = (REPO / "gitops/bootstrap/apps/workshop-agent.yaml").read_text(encoding="utf-8")
AI_LAYER_APP = (REPO / "gitops/bootstrap/apps/ai-layer.yaml").read_text(encoding="utf-8")

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


agent = next((d for d in AGENT_DOCS if d and d.get("kind") == "Agent"), None)
check("the Agent CR is in gitops/workshop-agent/agent.yaml", agent is not None)
check("and not in ai-layer's bundle any more (#707)", not any(d and d.get("kind") == "Agent" for d in RES))
if agent is None:
    sys.exit(1)

declared = {}
for entry in agent["spec"]["declarative"]["tools"]:
    srv = entry.get("mcpServer") or {}
    declared[srv.get("name")] = list(srv.get("toolNames") or [])

print("== every declared tool exists in the server that serves it ==")
for server, path in SERVERS.items():
    src = path.read_text(encoding="utf-8")
    served = set(re.findall(r"^(?:async )?def ([a-z][a-z0-9_]*)\(", src, re.M))
    names = declared.get(server)
    check(f"{server} is declared on the agent", names is not None)
    for tool in names or []:
        check(f"{server}.{tool} exists in {path.name}", tool in served)

print("== the RemoteMCPServer description names only tools its server serves ==")
# kagent shows this description beside the server. It listed list_pods, apply_manifest and get_secret long
# after those tools were retired (#465), so a reader tracing the tool path read the wrong toolset.
served_by = {s: set(re.findall(r"^(?:async )?def ([a-z][a-z0-9_]*)\(", p.read_text(encoding="utf-8"), re.M))
             for s, p in SERVERS.items()}
described = {d["metadata"]["name"]: set(re.findall(r"\b[a-z]+(?:_[a-z0-9]+)+\b", d["spec"].get("description", "")))
             for d in RES if d and d.get("kind") == "RemoteMCPServer"}
for name, named in described.items():
    stale = sorted(named - served_by.get(name, set()))
    check(f"{name}'s description names no tool {name} does not serve (stale: {stale})", not stale)
missing = sorted(set(declared.get("workshop-mcp", [])) - described.get("workshop-mcp", set()))
check(f"workshop-mcp's description names every tool the agent declares on it (missing: {missing})", not missing)

print("== the recreation spec describes the toolset the agent declares ==")
# MASTER-RECREATION-SPEC is what a rebuild reads. It went on listing list_pods, apply_manifest (HITL) and
# get_secret, with the defended list as the committed default, after both had changed (#542). Its
# Components row for each server, and recreation step 6, must name the tools as declared here.
SPEC = (REPO / "docs/MASTER-RECREATION-SPEC.md").read_text(encoding="utf-8").splitlines()
TOOL = re.compile(r"`([a-z]+(?:_[a-z0-9]+)+)`")
for server, label in (("workshop-mcp", "| workshop-mcp (good) |"), ("evil-mcp", "| evil-mcp-shim (rogue) |")):
    row = next((l for l in SPEC if l.startswith(label)), "")
    check(f"the spec has a Components row for {server}", bool(row))
    named = set(TOOL.findall(row))
    stale = sorted(named - served_by[server])
    check(f"the spec's {server} row names no tool {server} does not serve (stale: {stale})", not stale)
    missing = sorted(set(declared.get(server, [])) - named)
    check(f"the spec's {server} row names every tool the agent declares on it (missing: {missing})", not missing)
step6 = next((l for l in SPEC if l.startswith("6. The Agent's committed")), "")
check("the spec has recreation step 6 on the Agent's committed tool config", bool(step6))
named = set(TOOL.findall(step6))
all_declared = {t for names in declared.values() for t in names}
check(f"step 6 names every declared tool (missing: {sorted(all_declared - named)})", all_declared <= named)
check(f"step 6 names no undeclared tool (stale: {sorted(named - all_declared)})", named <= all_declared)
check("step 6 keeps the vulnerable default, as the manifest does", "vulnerable default" in step6
      and "defended" not in step6)
approve = [e["mcpServer"].get("requireApproval") for e in agent["spec"]["declarative"]["tools"] if e.get("mcpServer")]
check("step 6 says no requireApproval, and the manifest sets none",
      "no `requireApproval`" in step6 and not any(approve))

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
check("ai-layer ignores nothing on the Agent, which is not in its bundle (#707)",
      not [i for i in yaml.safe_load(AI_LAYER_APP)["spec"].get("ignoreDifferences") or [] if i.get("kind") == "Agent"])

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
