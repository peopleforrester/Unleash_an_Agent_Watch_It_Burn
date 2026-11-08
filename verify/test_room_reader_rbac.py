# ABOUTME: Holds #1050's grant: under every Role the guardrails switch and the challenges apply to workshop-mcp, its
# ABOUTME: ServiceAccount may list each kind the room reader reports, through a Role of its own that no swap replaces.
"""Offline RBAC checks for #1050.

workshop-mcp's reader (read_room_workloads in gitops/ai-layer/workshop-mcp-server.py) lists the room's workload kinds
in agent about every 30 s, and any list that fails fails the whole read, so the reader needs list on every kind it
reads under each Role this ServiceAccount can be bound to. The account is bound to the workshop-agent Role, which the
guardrails switch, guard-rbac-on/off, guard-agency-on/off and Challenge 8's fix and reset replace whole with one of the
challenge-fixes ConfigMap's Roles. The reader's list grant is a second Role, workshop-mcp-room-reader, bound to this
account alone, so no swap touches it.

This renders each of those Roles (the shipped one in resources.yaml and every workshop-agent Role in challenge-fixes),
adds the reader's Role beside it as the API server would, and evaluates list on each kind the reader reports.
The tools-tier twin, verify/test_room_reader_rbac_e2e.py, runs the same check on the pinned kubectl's kustomize render.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
import types

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
sys.path.insert(0, str(REPO / "verify"))
import room_reader_rbac as rr  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp_room_reader_rbac", AI / "workshop-mcp-server.py")
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)
READ = rr.read_kinds(mcp.ROOM_READ_KINDS)

docs = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text()) if isinstance(d, dict)]
for d in docs:   # kustomize puts every object of the bundle in agent (kustomization.yaml, namespace: agent)
    d.setdefault("metadata", {}).setdefault("namespace", "agent")
entrypoint = (REPO / "images/web-terminal/entrypoint.sh").read_text()
lab = (REPO / "challenges/LAB-TEXT.md").read_text()
argo = yaml.safe_load((REPO / "gitops/bootstrap/apps/ai-layer.yaml").read_text())

failed = rr.check_all(check, docs, READ, applied_files=rr.applied_role_files(entrypoint, lab))

print("== Argo CD keeps the reader's Role as written ==")
ignored = [d for d in (argo.get("spec") or {}).get("ignoreDifferences") or [] if d.get("kind") in ("Role", "RoleBinding")]
check("ai-layer's ignoreDifferences names no Role or RoleBinding but workshop-agent's Role, so selfHeal restores "
      "workshop-mcp-room-reader and its binding",
      all(d.get("kind") == "Role" and d.get("name") == "workshop-agent" for d in ignored), str(ignored))

print("== the check is not vacuous ==")
without = [d for d in docs if not (d.get("kind") == "RoleBinding" and d["metadata"]["name"] == rr.READER)]
lost = rr.check_all(lambda *a, **k: None, without, READ, applied_files=rr.applied_role_files(entrypoint, lab),
                    say=lambda _: None)
check("with the reader's binding taken out, the check fails: the least-privilege and scoped Roles list no StatefulSet",
      lost > 0, str(lost))
wider = [dict(d, rules=d["rules"] + [{"apiGroups": [""], "resources": ["secrets"], "verbs": ["list"]}])
         if d.get("kind") == "Role" and d["metadata"]["name"] == rr.READER else d for d in docs]
check("a reader Role that grants more than list on the read kinds fails the check",
      rr.check_all(lambda *a, **k: None, wider, READ, applied_files=rr.applied_role_files(entrypoint, lab),
                   say=lambda _: None) > 0)
check("the reader's grant is list alone, in the source too", re.search(
    r"name: workshop-mcp-room-reader\nrules:(\n  - apiGroups: .*\n    resources: .*\n    verbs: \[\"list\"\])+\n---",
    (AI / "resources.yaml").read_text()) is not None)

print()
if failures or failed:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("all room reader RBAC checks passed")
