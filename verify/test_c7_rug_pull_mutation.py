# ABOUTME: Offline checks for the C7 rug-pull switch's live half (#1468): GET_WEATHER_DESC comes from one ConfigMap
# ABOUTME: key, Argo CD ignores that key alone, and the toggle flips it between the two values server.py knows.
"""#1463 gave gitops/ai-layer/server.py two get_weather descriptions chosen by GET_WEATHER_DESC ("benign", or the
chaining default), and verify/test_get_weather_rugpull_switch.py holds that the two differ in the description alone and
that the chaining one chains to the second tool. This file holds the part #1468 adds on top, the one the beat needs to
flip the switch on a running cluster:

- evil-mcp-shim takes GET_WEATHER_DESC from the get_weather_desc key of the evil-mcp-rugpull-config ConfigMap, whose
  committed value is "chaining", so the default C7 allow-list beat is unchanged;
- the ai-layer Application ignores that one key and nothing else of the ConfigMap, so selfHeal keeps a live flip;
- challenges/03-bad-mcp-excessive-agency/toggle-rugpull-mutation-on.sh requires CONTEXT, writes "chaining" by
  default and "benign" with --off, and those are exactly the values server.py's switch tells apart.

No cluster and no `mcp` import: server.py is read as source.
"""
import ast
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SERVER = REPO / "gitops/ai-layer/server.py"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
AI_LAYER_APP = REPO / "gitops/bootstrap/apps/ai-layer.yaml"
TOGGLE = REPO / "challenges/03-bad-mcp-excessive-agency/toggle-rugpull-mutation-on.sh"
SWITCH_ENV, CM, KEY = "GET_WEATHER_DESC", "evil-mcp-rugpull-config", "get_weather_desc"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f": {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# --- What server.py's switch tells apart ----------------------------------------------------------------------
print("== server.py's switch reads GET_WEATHER_DESC and serves benign only for 'benign' ==")
tree = ast.parse(SERVER.read_text(encoding="utf-8"))
selector = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_get_weather_description"), None)
check("server.py has the switch's selector, _get_weather_description()", selector is not None)
compared = set()
if selector is not None:
    for sub in ast.walk(selector):
        if isinstance(sub, ast.Compare) and isinstance(sub.left, ast.Call) and \
                any(isinstance(a, ast.Constant) and a.value == SWITCH_ENV for a in sub.left.args):
            compared |= {c.value for c in sub.comparators if isinstance(c, ast.Constant)}
check(f"the selector compares {SWITCH_ENV} with 'benign' alone (every other value is the chaining default)",
      compared == {"benign"}, str(compared))

# --- The switch's live home ------------------------------------------------------------------------------------
print("== resources.yaml sources the switch from one ConfigMap key, committed chaining ==")
docs = [d for d in yaml.safe_load_all(RESOURCES.read_text(encoding="utf-8")) if d]
cm = next((d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == CM), None)
check(f"the {CM} ConfigMap exists", cm is not None)
check(f"its one key is {KEY}, committed 'chaining' (the existing C7 beat's description)",
      cm is not None and cm.get("data") == {KEY: "chaining"}, str(cm.get("data") if cm else None))
shim = next((d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "evil-mcp-shim"), None)
env = [e for c in (shim["spec"]["template"]["spec"]["containers"] if shim else []) for e in c.get("env") or []]
switch = [e for e in env if e.get("name") == SWITCH_ENV]
check(f"evil-mcp-shim sets {SWITCH_ENV} once, from {CM}'s {KEY} and not from a literal value",
      len(switch) == 1 and "value" not in switch[0]
      and (switch[0].get("valueFrom") or {}).get("configMapKeyRef") == {"name": CM, "key": KEY}, str(switch))

# --- Argo CD ignores that key alone ----------------------------------------------------------------------------
print("== the ai-layer Application ignores that key and nothing else of the ConfigMap ==")
app = next((d for d in yaml.safe_load_all(AI_LAYER_APP.read_text(encoding="utf-8"))
            if d and d.get("kind") == "Application"), None)
ignores = [i for i in ((app or {}).get("spec") or {}).get("ignoreDifferences") or []
           if i.get("kind") == "ConfigMap" and i.get("name") == CM]
check(f"exactly one ignoreDifferences entry names {CM}", len(ignores) == 1, str(ignores))
check(f"it ignores .data[\"{KEY}\"] only", len(ignores) == 1 and ignores[0].get("group") == ""
      and ignores[0].get("jqPathExpressions") == [f'.data["{KEY}"]'] and not ignores[0].get("jsonPointers"),
      str(ignores))
check("no ignore reaches the evil-mcp-shim Deployment's env (the flip is the ConfigMap's, not the env list's)",
      not any(i.get("name") == "evil-mcp-shim" for i in ((app or {}).get("spec") or {}).get("ignoreDifferences") or []))

# --- The toggle ------------------------------------------------------------------------------------------------
print("== the toggle requires CONTEXT and writes the two values the switch knows ==")
tog = TOGGLE.read_text(encoding="utf-8")
check("the toggle requires CONTEXT", 'CONTEXT="${CONTEXT:?' in tog)
check("every kubectl call names the context", all("--context" in ln or "KCTL[@]" in ln
                                                  for ln in tog.splitlines() if re.match(r"\s*kubectl\b", ln)))
check(f"it patches {CM}'s {KEY} key", "patch configmap" in tog and f'\\"{KEY}\\"' in tog and CM in tog)
written = set(re.findall(r'^\s*MODE="(\w+)"', tog, re.M))
check("it writes exactly 'chaining' and 'benign'", set(written) == {"chaining", "benign"}, str(set(written)))
on_branch = re.search(r'if \[\[ "\$\{STATE\}" == "on" \]\]; then\n\s*MODE="(\w+)"', tog)
check("running it without --off writes 'chaining' (the mutation, and the committed state)",
      on_branch is not None and on_branch.group(1) == "chaining")
check("--off writes 'benign' (the approved description)",
      re.search(r'else\n\s*MODE="benign"', tog) is not None and "--off) STATE=\"off\"" in tog)
check("it restarts evil-mcp-shim so the pod re-reads the key", "rollout restart" in tog and "evil-mcp-shim" in tog)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("OK: the rug-pull switch is set from one ConfigMap key, committed chaining, ignored alone by Argo CD, and the")
print("    toggle flips it between the two values server.py tells apart.")
