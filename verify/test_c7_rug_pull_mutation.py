# ABOUTME: Offline checks for the C7 rug-pull mutation switch (#1468): evil-mcp's get_weather serves an
# ABOUTME: approved or a mutated DESCRIPTION, name and inputSchema kept, selected live and ignored by Argo.
"""The rug-pull beat (docs/research/2026-11-14-c7-rug-pull-beat.md) turns on a tool approved under one
description and then served, same name and same schema, with a mutated description the name-based allow-list
is blind to. This holds that gitops/ai-layer/server.py carries both descriptions, that the mutation changes
ONLY the description (not the name or inputSchema), that the mutated one chains to read_internal_config, and
that the selector is wired and the toggle flips it with an Argo CD ignore on just that field.

No cluster and no `mcp` import here: server.py is read as source (AST), the way verify/test_tool_pin.py does,
so the check runs in the offline tier.
"""
import ast
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SERVER = REPO / "gitops/ai-layer/server.py"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
AI_LAYER_APP = REPO / "gitops/bootstrap/apps/ai-layer.yaml"
TOGGLE = REPO / "challenges/03-bad-mcp-excessive-agency/toggle-rugpull-mutation-on.sh"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f": {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


tree = ast.parse(SERVER.read_text(encoding="utf-8"))

# --- Module string constants (APPROVED_/MUTATED_ descriptions) ------------------------------------------
consts: dict[str, str] = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        try:
            val = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            continue
        if isinstance(val, str):
            consts[node.targets[0].id] = val

print("== server.py defines both descriptions ==")
check("APPROVED_GET_WEATHER_DESCRIPTION is a module string", "APPROVED_GET_WEATHER_DESCRIPTION" in consts)
check("MUTATED_GET_WEATHER_DESCRIPTION is a module string", "MUTATED_GET_WEATHER_DESCRIPTION" in consts)
if failures:
    print(f"\nFAILED: {len(failures)} check(s): cannot read the descriptions")
    sys.exit(1)
APPROVED = consts["APPROVED_GET_WEATHER_DESCRIPTION"]
MUTATED = consts["MUTATED_GET_WEATHER_DESCRIPTION"]

# --- get_weather's decorator description and its signature ----------------------------------------------
get_weather = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_weather"), None)
check("get_weather is a module-level function", get_weather is not None)
deco_desc = None
if get_weather is not None:
    for dec in get_weather.decorator_list:
        if isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "tool":
            deco_desc = next((ast.literal_eval(k.value) for k in dec.keywords if k.arg == "description"), None)
# The decorator literal is what verify/test_tool_pin.py pins as the approved baseline, so it must be the
# approved description verbatim: otherwise the pin and this switch would disagree on "approved".
check("get_weather's @mcp.tool description is the approved description verbatim",
      deco_desc == APPROVED, f"decorator={deco_desc!r}")

# --- The mutation changes the description, not the name or the inputSchema -------------------------------
print("== the mutation changes the description and nothing else ==")
check("the two descriptions differ", APPROVED != MUTATED)
# The name is a property of the one get_weather function; the inputSchema is derived from its one signature.
# Neither can differ between modes because the switch only ever re-points the description. Assert the switch
# code does exactly that: _apply_get_weather_mode assigns tool.description and no other tool attribute.
applier = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_apply_get_weather_mode"),
               None)
check("_apply_get_weather_mode exists", applier is not None)
assigned_attrs: set[str] = set()
if applier is not None:
    for sub in ast.walk(applier):
        if isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                if isinstance(tgt, ast.Attribute):
                    assigned_attrs.add(tgt.attr)
check("the switch assigns only the tool's description (never name or inputSchema/parameters)",
      assigned_attrs == {"description"}, f"assigned attributes: {sorted(assigned_attrs)}")
# The one city parameter is shared by both modes (it is the single signature), so the inputSchema is identical.
params = [a.arg for a in get_weather.args.args] if get_weather is not None else []
check("get_weather keeps its single city parameter (one schema for both modes)", params == ["city"], str(params))

# --- The mutated description carries the chain to read_internal_config -----------------------------------
print("== the mutated description chains to read_internal_config, the approved one does not ==")
check("the mutated description names read_internal_config", "read_internal_config" in MUTATED)
check("the mutated description instructs calling it (the chain)",
      "call" in MUTATED.lower() and "read_internal_config" in MUTATED)
check("the approved description is benign: it does not name read_internal_config",
      "read_internal_config" not in APPROVED, APPROVED)

# --- The selector: env var or mounted file, default approved --------------------------------------------
print("== the selector is an env var or a mounted file, defaulting to approved ==")
src = SERVER.read_text(encoding="utf-8")
check("the mode is read from the GET_WEATHER_MODE env var", 'os.environ.get("GET_WEATHER_MODE"' in src)
check("the mode is read from a mounted file as well", "GET_WEATHER_MODE_FILE" in src and "read_text" in src)
# The GET_WEATHER_DESCRIPTIONS mapping is keyed by the two modes; resolve its keys from the dict literal.
desc_map = next((n.value for n in tree.body if isinstance(n, ast.Assign)
                 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "GET_WEATHER_DESCRIPTIONS"), None)
map_keys = {ast.literal_eval(k) for k in desc_map.keys} if isinstance(desc_map, ast.Dict) else set()
check("the two modes are exactly approved and mutated", map_keys == {"approved", "mutated"}, str(map_keys))
mode_fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_get_weather_mode"), None)
check("an unknown or absent selector defaults to approved",
      mode_fn is not None and '"approved"' in ast.get_source_segment(src, mode_fn.body[-1]),
      "the final return of _get_weather_mode should fall back to approved")

# --- The selector is wired on the Deployment and committed approved -------------------------------------
print("== resources.yaml wires the selector and commits approved ==")
docs = [d for d in yaml.safe_load_all(RESOURCES.read_text(encoding="utf-8")) if d]
cm = next((d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "evil-mcp-rugpull-config"),
          None)
check("the evil-mcp-rugpull-config ConfigMap exists", cm is not None)
check("its committed get_weather_mode is approved (the benign default)",
      cm is not None and cm.get("data", {}).get("get_weather_mode") == "approved",
      str(cm.get("data") if cm else None))
shim = next((d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "evil-mcp-shim"), None)
env = (shim["spec"]["template"]["spec"]["containers"][0].get("env") or []) if shim else []
gw_env = next((e for e in env if e.get("name") == "GET_WEATHER_MODE"), None)
check("evil-mcp-shim takes GET_WEATHER_MODE from that ConfigMap key",
      gw_env is not None and (gw_env.get("valueFrom") or {}).get("configMapKeyRef", {})
      == {"name": "evil-mcp-rugpull-config", "key": "get_weather_mode"}, str(gw_env))

# --- Argo CD ignores ONLY that field --------------------------------------------------------------------
print("== the ai-layer Application ignores only the selector field ==")
app = next((d for d in yaml.safe_load_all(AI_LAYER_APP.read_text(encoding="utf-8"))
            if d and d.get("kind") == "Application"), None)
ignores = (app["spec"].get("ignoreDifferences") or []) if app else []
cm_ign = next((i for i in ignores if i.get("kind") == "ConfigMap" and i.get("name") == "evil-mcp-rugpull-config"),
              None)
check("there is an ignoreDifferences for the selector ConfigMap", cm_ign is not None)
check("it ignores only the get_weather_mode data key",
      cm_ign is not None and cm_ign.get("jqPathExpressions") == ['.data["get_weather_mode"]'], str(cm_ign))

# --- The toggle flips the selector, with CONTEXT and --off ----------------------------------------------
print("== the toggle flips the selector from a required CONTEXT, with --off ==")
tog = TOGGLE.read_text(encoding="utf-8")
check("the toggle requires CONTEXT", 'CONTEXT="${CONTEXT:?' in tog)
check("the toggle patches the evil-mcp-rugpull-config ConfigMap's get_weather_mode key",
      "patch configmap" in tog and "get_weather_mode" in tog and "evil-mcp-rugpull-config" in tog)
check("the toggle has an --off that restores the approved description",
      "--off" in tog and 'MODE="approved"' in tog)
check("running it without --off mutates (MODE=mutated)", 'MODE="mutated"' in tog)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("OK: the C7 rug-pull mutation switch changes only get_weather's description, chains when mutated, and")
print("    is wired, defaulted approved, ignored by Argo on just that field, and flipped by the toggle.")
