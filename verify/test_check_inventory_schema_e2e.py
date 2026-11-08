# ABOUTME: The schema mcp 1.29.1 publishes for check_inventory declares the ingredient (#902), and a tools/call with one
# ABOUTME: through the real AuditedFastMCP answers that ingredient's level, with the ingredient in the audit line.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: uv for mcp 1.29.1 as the image pins it)
"""The executed half of verify/test_check_inventory_ingredient.py.

On watch-it-burn-private the live tools/list entry for check_inventory read `"inputSchema": {"properties": {}}`, so
the model had no argument to fill and every call logged tool_input {} (#902). Here workshop-mcp-server.py is imported
with mcp==1.29.1, the version images/workshop-mcp pins, with tool_audit.py beside it as the ConfigMap mounts them:

1. tools/list's inputSchema for check_inventory has an `ingredient` string property, and requires nothing.
2. call_tool("check_inventory", {"ingredient": "ghost pepper"}) answers {"ghost_pepper": 12}, and the audit line's
   tool_input carries the ingredient, which is the field the issue found empty.
3. call_tool("check_inventory", {}) still answers the whole seeded inventory.

Needs uv and the network to fetch mcp. A missing uv or a failed fetch is a failure, not a skip.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import package_cache  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("uv") is None:
    print("FAILED: uv not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)

PROBE = r"""
import asyncio, importlib.util, json, sys
sys.path.insert(0, sys.argv[1])
spec = importlib.util.spec_from_file_location("srv", sys.argv[1] + "/workshop-mcp-server.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m._seed_local_data()

def text(result):
    if isinstance(result, tuple):
        result = result[0]
    result = getattr(result, "content", result)
    return "".join(getattr(b, "text", "") or "" for b in result or [])

async def main():
    tools = {t.name: t for t in await m.mcp.list_tools()}
    schema = tools["check_inventory"].inputSchema
    one = text(await m.mcp.call_tool("check_inventory", {"ingredient": "ghost pepper"}))
    every = text(await m.mcp.call_tool("check_inventory", {}))
    print("RESULT " + json.dumps({"schema": schema, "one": one, "every": every}))

asyncio.run(main())
"""

data = tempfile.mkdtemp(prefix="check-inventory-e2e-")
r = subprocess.run([*package_cache.run_cmd("mcp"), "python", "-I", "-c", PROBE, str(AI)],
                   capture_output=True, text=True, cwd="/", timeout=600,
                   env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "WORKSHOP_DATA_DIR": data})
lines = r.stdout.splitlines()
results = [json.loads(line[len("RESULT "):]) for line in lines if line.startswith("RESULT ")]
check("the server imports and answers under mcp 1.29.1", r.returncode == 0 and len(results) == 1,
      (r.stderr.strip() or r.stdout.strip())[-600:])
if not results:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
res = results[0]
audit = [json.loads(line) for line in lines if line.startswith("{")]

print("== tools/list declares the ingredient ==")
props = res["schema"].get("properties") or {}
check("check_inventory's inputSchema has an `ingredient` property", "ingredient" in props, json.dumps(res["schema"]))
check("of type string", (props.get("ingredient") or {}).get("type") == "string", json.dumps(props))
check("and requires nothing, so a call with no arguments is still valid", not res["schema"].get("required"),
      json.dumps(res["schema"]))

print("== a call naming an ingredient ==")
check("answers that ingredient's level", res["one"] == json.dumps({"ghost_pepper": 12}), res["one"][:200])
pre = [a for a in audit if a.get("tool_name") == "check_inventory" and a.get("phase") == "pre"]
check("the audit line's tool_input carries the ingredient (the field #902 found empty)",
      len(pre) == 2 and pre[0].get("tool_input") == {"ingredient": "ghost pepper"}, json.dumps(pre)[:300])

print("== a call naming none ==")
try:
    every = json.loads(res["every"])
except ValueError:
    every = res["every"]
check("answers the whole seeded inventory", isinstance(every, dict) and every.get("ghost_pepper") == 12
      and len(every) == 13, res["every"][:200])
check("with tool_input {} in its audit line", len(pre) == 2 and pre[1].get("tool_input") == {}, json.dumps(pre)[:300])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All check_inventory schema E2E checks passed.")
