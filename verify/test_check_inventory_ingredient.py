# ABOUTME: check_inventory takes the ingredient it is asked about (#902): its signature declares the argument FastMCP
# ABOUTME: builds the input schema from, and a named ingredient gets its own stock level, not the whole inventory.
"""On watch-it-burn-private on 2026-10-31 and 2026-11-05 every check_inventory call workshop-agent made logged
tool_input {} in workshop-mcp, even when the prompt named an ingredient per step (guard-proxy-agenticburn#29). The
tool's live tools/list entry read `"inputSchema": {"properties": {}}`: check_inventory() took no argument, so the
model had nothing to fill and every call answered the same 278-character inventory.

FastMCP builds a tool's input schema from its Python signature, so the offline half holds the signature and the
answers. The schema mcp 1.29.1 itself builds and a call through the real server are
verify/test_check_inventory_schema_e2e.py, in the tools tier. The server is loaded with a stand-in for tool_audit,
as test_deploy_app_errors.py loads it.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import pathlib
import sys
import tempfile
import types

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


descriptions: dict[str, str] = {}


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def tool(self, *a, **kw):
        def register(f):
            descriptions[f.__name__] = kw.get("description", "")
            return f
        return register


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp_check_inventory", AI / "workshop-mcp-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
# The seeded data directory is the pod's /tmp/burrito-data; here it is a directory of the test's own.
server._DATA = tempfile.mkdtemp(prefix="check-inventory-")

print("== the signature declares the ingredient (FastMCP's input schema is built from it) ==")
params = inspect.signature(server.check_inventory).parameters
p = params.get("ingredient")
check("check_inventory takes an `ingredient` argument", p is not None, str(list(params)))
check("it is a string that defaults to empty, so a call with no arguments still works",
      p is not None and p.annotation in (str, "str") and p.default == "", str(p))
check("and it is the only argument", list(params) == ["ingredient"], str(list(params)))
desc = descriptions.get("check_inventory", "")
check("the tool description tells the model to give the ingredient", "ingredient you are asking about" in desc, desc)

print("== no ingredient: the whole inventory, as before ==")
for label, args in (("no argument", ()), ("an empty string", ("",)), ("blank", ("   ",))):
    out = server.check_inventory(*args)
    check(f"{label} answers every ingredient", json.loads(out) == server._INVENTORY, out[:120])
check("that answer is still the 278-character inventory", len(server.check_inventory()) == 278,
      str(len(server.check_inventory())))

print("== a named ingredient: its own level ==")
for asked, expected in (
        ("ghost_pepper", {"ghost_pepper": 12}),
        ("ghost pepper", {"ghost_pepper": 12}),
        ("Ghost Peppers", {"ghost_pepper": 12}),
        ("Kelpie Queso", {"kelpie_queso": 9}),
        ("queso", {"kelpie_queso": 9}),
        ("Toe-Fu", {"toe_fu": 40}),
        ("Ogre Snot Guac", {"ogre_snot_guac": 7}),
        ("Toad-illa Chips", {"toad_illa_chips": 120}),
        ("Bogbacoa burrito", {"bogbacoa": 18}),
        ("ghost pepper and witch hazel", {"ghost_pepper": 12, "witch_hazel": 4})):
    out = server.check_inventory(asked)
    try:
        got = json.loads(out)
    except ValueError:
        got = out
    check(f"{asked!r} answers {expected}", got == expected, out[:160])

print("== an ingredient the cantina does not stock ==")
out = server.check_inventory("Dragon's Blood salsa")
check("says it is not in the inventory, naming what was asked", out.startswith("no ingredient matching")
      and "Dragon's Blood salsa" in out, out[:160])
check("and lists what is stocked, so the model can ask again", all(k in out for k in server._INVENTORY), out[:300])

print("== it reads the inventory on disk, which run_shell sees, when there is one ==")
(pathlib.Path(server._DATA) / "inventory.json").write_text(json.dumps({**server._INVENTORY, "ghost_pepper": 3}))
out = server.check_inventory("ghost pepper")
check("a level changed on disk is the level it answers", out == json.dumps({"ghost_pepper": 3}), out)
(pathlib.Path(server._DATA) / "inventory.json").write_text("not json")
out = server.check_inventory("ghost pepper")
check("an unreadable file falls back to the seeded levels", out == json.dumps({"ghost_pepper": 12}), out)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All check_inventory ingredient checks passed.")
