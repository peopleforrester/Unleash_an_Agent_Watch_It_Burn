# ABOUTME: Render gate for C7's live gateway rule (#496): runs the terminal's real guard toggles against a fake
# ABOUTME: kubectl, and checks the Argo CD ignore, the Kyverno exemption and the RBAC that let the flip stick.
"""Why this exists (#496).

On an admin cluster (the KubeCon breakout) C7 is stopped at agentgateway: guard-mcp-on rewrites the
mcpAuthorization rule for evil-mcp's bind, the gateway reloads the file, and the rogue tools/call is refused
before evil-mcp runs it. On a workshop cluster the same command still narrows the kagent toolNames list.

Five things have to agree for that to work, and each one failing looks the same on stage, a guard that
says ON and lets the sentinel out:
  - the toggles pick the right control for the cluster, and fail rather than guess when they cannot tell;
  - the rule rewrite produces exactly the rule the schema test validated, and round-trips to the committed file;
  - Argo CD ignores drift on that ConfigMap, and only that one;
  - block-argocd-drift lets the terminal, and only the terminal, update it;
  - the terminal can patch it and touch the gateway pod, and the badge reader can read it.

The toggles are executed, not grepped: their heredocs are cut out of the entrypoint and run with a kubectl
on PATH that serves the committed ConfigMap and records every call.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
ENTRYPOINT = (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_text(encoding="utf-8")
GATEWAY = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/agentgateway.yaml").read_text()) if d]
RESOURCES = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]
APP = yaml.safe_load((REPO / "gitops/apps/ai-layer.yaml").read_text())
DRIFT = yaml.safe_load((REPO / "policies/kyverno/block-argocd-drift.yaml").read_text())
FALLBACK = (REPO / "challenges/03-bad-mcp-excessive-agency/fallback.curl.sh").read_text(encoding="utf-8")
ALL = ["get_weather", "read_internal_config", "apply_optimization"]
ON_RULE = 'mcp.tool.name == "get_weather"'

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


def find(docs: list, kind: str, name: str) -> dict:
    return next((d for d in docs if d.get("kind") == kind and d.get("metadata", {}).get("name") == name), {})


C7_CM = find(GATEWAY, "ConfigMap", "agentgateway-c7-config")
COMMITTED = C7_CM.get("data", {}).get("config.yaml", "")


def rules_of(text: str) -> list:
    cfg = yaml.safe_load(text) or {}
    return [x for b in cfg.get("binds", []) for l in b.get("listeners", []) for r in l.get("routes", [])
            for x in r.get("policies", {}).get("mcpAuthorization", {}).get("rules", [])]


# --- the fake cluster --------------------------------------------------------------------------------
FAKE_KUBECTL = r'''#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["FAKE_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
state["calls"].append(args)
def save():
    json.dump(state, open(state_path, "w"))
def flag(name):
    return args[args.index(name) + 1] if name in args else None
if "get" in args and "application" in args:
    save()
    if state["cluster"] == "unreachable":
        sys.exit(1)
    if state["cluster"] == "admin":
        print("application.argoproj.io/app-of-apps-admin")
    sys.exit(0)
if "get" in args and "configmap" in args:
    save()
    print(json.dumps({"metadata": {"name": "agentgateway-c7-config", "resourceVersion": str(state["rv"])},
                      "data": {"config.yaml": state["config"]}}))
    sys.exit(0)
if "patch" in args and "configmap" in args:
    if state["race"]:
        state["rv"] += 1  # somebody else wrote the ConfigMap between our read and our patch
    ops = json.loads(flag("-p"))
    for op in ops:
        if op["op"] == "test" and op["path"] == "/metadata/resourceVersion" and op["value"] != str(state["rv"]):
            save(); sys.exit(1)
        if op["op"] == "replace" and op["path"] == "/data/config.yaml":
            state["config"] = op["value"]
    state["rv"] += 1
    save(); sys.exit(0)
if "patch" in args and "agent" in args:
    ops = json.loads(flag("-p"))
    state["toolNames"] = ops[0]["value"]
    save(); sys.exit(0)
save()
sys.exit(0)
'''


def heredocs() -> dict:
    return dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', ENTRYPOINT, re.S))


def run(cluster: str, *commands: str, race: bool = False) -> tuple[dict, list[subprocess.CompletedProcess]]:
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp, "home"); home.mkdir()
        fakebin = pathlib.Path(tmp, "bin"); fakebin.mkdir()
        for name, body in heredocs().items():
            (home / name).write_text(body + "\n")
            (home / name).chmod(0o755)
        (fakebin / "kubectl").write_text(FAKE_KUBECTL)
        (fakebin / "kubectl").chmod(0o755)
        state_path = pathlib.Path(tmp, "state.json")
        state_path.write_text(json.dumps({"cluster": cluster, "config": COMMITTED, "rv": 7, "race": race,
                                          "toolNames": None, "calls": []}))
        env = {**os.environ, "HOME": str(home), "PATH": f"{fakebin}:{os.environ['PATH']}",
               "FAKE_STATE": str(state_path)}
        results = [subprocess.run(["bash", str(home / c)], env=env, capture_output=True, text=True, timeout=60)
                   for c in commands]
        return json.loads(state_path.read_text()), results


def patched_cm(state: dict) -> bool:
    return any("patch" in c and "configmap" in c for c in state["calls"])


print("== the toggles exist where the entrypoint writes them ==")
docs = heredocs()
for name in (".guardlib", ".c7rule.py", "guard-mcp-on", "guard-mcp-off", "guards-on", "guards-off"):
    check(f"the entrypoint writes ~/{name}", name in docs)
check("images/web-terminal/entrypoint.sh is byte-identical to the gitops copy",
      (REPO / "images/web-terminal/entrypoint.sh").read_text(encoding="utf-8") == ENTRYPOINT)

print("== admin cluster: guard-mcp-on narrows the gateway rule and leaves the allow-list full ==")
state, (on,) = run("admin", "guard-mcp-on")
check("guard-mcp-on exits 0", on.returncode == 0, on.stdout + on.stderr)
check("and says the guard is on at the gateway", "ON, at the gateway" in on.stdout, on.stdout)
check(f"the rule is now {ON_RULE!r}", rules_of(state["config"]) == [ON_RULE], f"{rules_of(state['config'])}")
check("only the rule line changed", [l for l in state["config"].splitlines() if "c7-rule" not in l]
      == [l for l in COMMITTED.splitlines() if "c7-rule" not in l])
check("evil-mcp's toolNames is the full list, so the rogue call reaches the gateway", state["toolNames"] == ALL,
      f"{state['toolNames']}")
check("the gateway pod is touched so the kubelet refreshes the volume now",
      any("annotate" in c and "app.kubernetes.io/name=agentgateway" in c for c in state["calls"]))
cm_patch = next((c for c in state["calls"] if "patch" in c and "configmap" in c), [])
ops = json.loads(cm_patch[cm_patch.index("-p") + 1]) if "-p" in cm_patch else []
check("the patch tests the resourceVersion it read before replacing", ops[:1] == [
    {"op": "test", "path": "/metadata/resourceVersion", "value": "7"}], f"{ops[:1]}")

print("== admin cluster: guard-mcp-off opens it again, back to the committed file byte for byte ==")
state, (on, off) = run("admin", "guard-mcp-on", "guard-mcp-off")
check("guard-mcp-off exits 0 and says it is off at the gateway",
      off.returncode == 0 and "OFF, at the gateway" in off.stdout, off.stdout + off.stderr)
check("the rule is 'true' again", rules_of(state["config"]) == ["true"], f"{rules_of(state['config'])}")
check("and the config is the committed one exactly", state["config"] == COMMITTED)
check("toolNames stays full", state["toolNames"] == ALL, f"{state['toolNames']}")

print("== admin cluster: guards-on and guards-off flip the gateway rule too ==")
state, (gon,) = run("admin", "guards-on")
check("guards-on narrows the gateway rule", rules_of(state["config"]) == [ON_RULE] and gon.returncode == 0,
      gon.stdout + gon.stderr)
check("guards-on leaves the on-topic guard alone (#455)", not any("topic" in " ".join(c) for c in state["calls"]))
check("guards-on reports no C7 failure", "did not switch" not in gon.stdout, gon.stdout)
state, (_, goff) = run("admin", "guards-on", "guards-off")
check("guards-off puts the committed rule back", state["config"] == COMMITTED and goff.returncode == 0,
      goff.stdout + goff.stderr)

print("== workshop cluster: the toolNames path, unchanged, and the gateway rule untouched ==")
state, (on,) = run("attendee", "guard-mcp-on")
check("guard-mcp-on narrows toolNames to get_weather", state["toolNames"] == ["get_weather"], f"{state['toolNames']}")
check("and does not edit the gateway ConfigMap", not patched_cm(state))
check("and says the rogue tools left the allow-list", "removed from the agent's allow-list" in on.stdout, on.stdout)
state, (_, off) = run("attendee", "guard-mcp-on", "guard-mcp-off")
check("guard-mcp-off restores the full toolNames list", state["toolNames"] == ALL, f"{state['toolNames']}")
state, (gon,) = run("attendee", "guards-on")
check("guards-on narrows toolNames and leaves the ConfigMap alone",
      state["toolNames"] == ["get_weather"] and not patched_cm(state))

print("== when Argo CD cannot be asked, nothing is guessed ==")
state, (on, gon) = run("unreachable", "guard-mcp-on", "guards-on")
check("guard-mcp-on fails loudly", on.returncode != 0 and "Could not switch the MCP guard on" in on.stdout,
      on.stdout + on.stderr)
check("guards-on says C7 did not switch", "did not switch on" in gon.stdout, gon.stdout)
check("and neither control was touched", state["toolNames"] is None and not patched_cm(state))

print("== a stale read is refused, not written over ==")
state, (on,) = run("admin", "guard-mcp-on", race=True)
check("guard-mcp-on fails when the ConfigMap changed under it", on.returncode != 0
      and "Could not switch the MCP guard on" in on.stdout, on.stdout + on.stderr)
check("and the other writer's version is left as it was", state["config"] == COMMITTED)

print("== the rewrite refuses a file it does not recognise ==")
rewrite = docs.get(".c7rule.py", "")
for label, text in (("no marker", COMMITTED.replace(" # c7-rule", "")),
                    ("two markers", COMMITTED + "    # c7-rule\n")):
    cm = json.dumps({"metadata": {"resourceVersion": "1"}, "data": {"config.yaml": text}})
    r = subprocess.run([sys.executable, "-I", "-c", rewrite, "on"], input=cm, capture_output=True, text=True)
    check(f"{label}: exits non-zero and prints no patch", r.returncode != 0 and not r.stdout.strip())
cm = json.dumps({"metadata": {"resourceVersion": "1"}, "data": {"config.yaml": COMMITTED}})
r = subprocess.run([sys.executable, "-I", "-c", rewrite, "sideways"], input=cm, capture_output=True, text=True)
check("an unknown state exits non-zero", r.returncode != 0 and not r.stdout.strip())

print("== Argo CD ignores drift on that one ConfigMap, and on no other gateway config ==")
ignores = APP["spec"].get("ignoreDifferences", [])
c7_ignore = [i for i in ignores if i.get("kind") == "ConfigMap" and i.get("name") == "agentgateway-c7-config"]
check("ai-layer ignores .data[\"config.yaml\"] on agentgateway-c7-config",
      len(c7_ignore) == 1 and c7_ignore[0].get("jqPathExpressions") == ['.data["config.yaml"]'], f"{c7_ignore}")
check("and nothing on agentgateway-config or the agentgateway Deployment",
      not any(i.get("name") == "agentgateway-config" or i.get("name") == "agentgateway" for i in ignores))
check("RespectIgnoreDifferences is on, so a sync does not revert it either",
      "RespectIgnoreDifferences=true" in APP["spec"]["syncPolicy"]["syncOptions"])

print("== block-argocd-drift lets the terminal, and only the terminal, update it ==")
conds = {c["name"]: c["expression"] for c in DRIFT["spec"]["matchConditions"]}
exempt = conds.get("not-terminal-c7-rule", "")
check("there is a not-terminal-c7-rule matchCondition", bool(exempt))
check("scoped to the terminal's ServiceAccount", "'system:serviceaccount:agent:web-terminal'" in exempt)
check("and to an UPDATE of the one ConfigMap, by kind, namespace and name",
      "request.operation == 'UPDATE'" in exempt and "object.?kind.orValue('') == 'ConfigMap'" in exempt
      and "object.?metadata.?namespace.orValue('') == 'agent'" in exempt
      and "object.?metadata.?name.orValue('') == 'agentgateway-c7-config'" in exempt)
check("the exemption is a negated conjunction (it never widens to any of those alone)",
      exempt.strip().startswith("!(") and "||" not in exempt)
check("agentgateway-config is named in no exemption", "agentgateway-config'" not in " ".join(conds.values()))

print("== RBAC: the terminal can flip it, the badge reader can read it ==")
terminal = find(RESOURCES, "ClusterRole", "console-terminal").get("rules", [])
def grants(rules: list, group: str, resource: str, verb: str, name: str | None = None) -> bool:
    return any(group in r.get("apiGroups", []) and (resource in r.get("resources", []) or "*" in r.get("resources", []))
               and verb in r.get("verbs", []) and (not r.get("resourceNames") or name in r["resourceNames"])
               for r in rules)
check("console-terminal may patch configmaps", grants(terminal, "", "configmaps", "patch", "agentgateway-c7-config"))
check("console-terminal may patch pods (the kubelet nudge)", grants(terminal, "", "pods", "patch"))
check("console-terminal may get Argo CD applications (the admin-cluster test)",
      grants(terminal, "*", "applications", "get") or grants(terminal, "argoproj.io", "applications", "get"))
reader = find(RESOURCES, "Role", "guard-proxy-reader").get("rules", [])
cm_rules = [r for r in reader if "configmaps" in r.get("resources", [])]
check("guard-proxy-reader gets agentgateway-c7-config by name, get only, and no other ConfigMap",
      len(cm_rules) == 1 and cm_rules[0].get("resourceNames") == ["agentgateway-c7-config"]
      and cm_rules[0].get("verbs") == ["get"], f"{cm_rules}")

print("== fallback.curl.sh drives read_internal_config through :3003, allow then deny ==")
check("it requires an explicit CONTEXT", 'CONTEXT="${CONTEXT:?' in FALLBACK)
check("its default tool is read_internal_config", 'TOOL_NAME="${TOOL_NAME:-read_internal_config}"' in FALLBACK)
check("it port-forwards the agentgateway Service's :3003", "port-forward svc/agentgateway" in FALLBACK
      and ':3003"' in FALLBACK)
check("it no longer targets the pre-gitops localhost:8080 endpoint", "localhost:8080" not in FALLBACK)
both = FALLBACK[FALLBACK.index("  both)"):]
check("the default mode flips off, waits for allow, flips on, waits for deny, in that order",
      [m for m in re.findall(r"flip (on|off)|wait_for (allow|deny)", both)]
      == [("off", ""), ("", "allow"), ("on", ""), ("", "deny")])
check("it flips with the terminal's own toggles, as the terminal's ServiceAccount",
      "exec deploy/web-terminal" in FALLBACK and '/home/student/guard-mcp-$1' in FALLBACK)
check("it refuses a non-admin cluster instead of asserting a deny that cannot happen",
      "get application app-of-apps-admin" in FALLBACK)
r = subprocess.run(["bash", "-n", str(REPO / "challenges/03-bad-mcp-excessive-agency/fallback.curl.sh")],
                   capture_output=True, text=True)
check("it parses", r.returncode == 0, r.stderr)
r = subprocess.run(["bash", str(REPO / "challenges/03-bad-mcp-excessive-agency/fallback.curl.sh")],
                   capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "CONTEXT"})
check("without CONTEXT it fails before touching anything", r.returncode != 0 and "CONTEXT" in r.stderr, r.stderr)

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("\nPASS: C7's gateway rule flips live on an admin cluster, and the workshop keeps its toolNames toggle")
