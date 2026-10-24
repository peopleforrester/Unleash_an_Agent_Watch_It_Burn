# ABOUTME: Render gate for C7's live gateway rule (#496, #515, #516): the terminal's real toggles against a fake kubectl,
# ABOUTME: and the Argo CD ignore, block-argocd-drift exemption and RBAC that let its edit of agentgateway-c7-config stick.
"""Why this exists (#515, part of #496).

On an admin cluster (the KubeCon breakout) C7 is to be stopped at agentgateway: the web terminal rewrites the
`# c7-rule` line of agentgateway-c7-config and the agentgateway-c7 container reloads it. Two platform
guardrails would undo or refuse that edit, and each failing looks the same on stage, a guard that says ON
and lets the sentinel out:
  - Argo CD selfHeal reverts it, unless ai-layer ignores that ConfigMap's config.yaml, and only that one;
  - Kyverno's block-argocd-drift denies it, unless the terminal, and only the terminal, may UPDATE it;
  - the terminal's RBAC has to let it read Argo CD applications, patch the ConfigMap and touch the pod.

This reads the manifests. The CEL itself is evaluated by the Kyverno CLI in test_kyverno_cel_policies.py
(E2E suite). The toggles (#516) are executed, not grepped: their heredocs are cut out of the entrypoint and run
with a kubectl on PATH that serves the committed ConfigMap and records every call. A workshop cluster keeps the
toolNames toggle; an admin cluster narrows the gateway rule and leaves toolNames full; when the cluster cannot be
told apart, or the ConfigMap moved under the toggle, it fails and touches neither control.
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
GATEWAY = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/agentgateway.yaml").read_text()) if d]
RESOURCES = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]
APP = yaml.safe_load((REPO / "gitops/apps/ai-layer.yaml").read_text())
DRIFT = yaml.safe_load((REPO / "policies/kyverno/block-argocd-drift.yaml").read_text())
TERMINAL_SA = "system:serviceaccount:agent:web-terminal"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


def find(docs: list, kind: str, name: str) -> dict:
    return next((d for d in docs if d.get("kind") == kind and d.get("metadata", {}).get("name") == name), {})


print("== the ConfigMap the terminal edits is the one ai-layer ships ==")
c7_cm = find(GATEWAY, "ConfigMap", "agentgateway-c7-config")
check("gitops/ai-layer/agentgateway.yaml declares agentgateway-c7-config", bool(c7_cm))
check("it lands in agent, the namespace the exemption names",
      c7_cm.get("metadata", {}).get("namespace", APP["spec"]["destination"]["namespace"]) == "agent")
check("its config.yaml carries exactly one `# c7-rule` line",
      sum(l.rstrip().endswith("# c7-rule") for l in c7_cm.get("data", {}).get("config.yaml", "").splitlines()) == 1)

print("== Argo CD ignores drift on that one ConfigMap, and on no other gateway config ==")
ignores = APP["spec"].get("ignoreDifferences", [])
c7_ignore = [i for i in ignores if i.get("kind") == "ConfigMap" and i.get("name") == "agentgateway-c7-config"]
check("ai-layer ignores .data[\"config.yaml\"] on agentgateway-c7-config, and nothing else of it",
      len(c7_ignore) == 1 and c7_ignore[0].get("group") == "" and not c7_ignore[0].get("jsonPointers")
      and c7_ignore[0].get("jqPathExpressions") == ['.data["config.yaml"]'], f"{c7_ignore}")
check("every ConfigMap ignore is named agentgateway-c7-config (an unnamed one would cover agentgateway-config)",
      all(i.get("name") == "agentgateway-c7-config" for i in ignores if i.get("kind") == "ConfigMap"),
      f"{[i for i in ignores if i.get('kind') == 'ConfigMap']}")
check("nothing is ignored on agentgateway-config",
      not any(i.get("name") == "agentgateway-config" for i in ignores))
check("nothing is ignored on the agentgateway Deployment (every Deployment ignore is named, none agentgateway)",
      all(i.get("name") and i.get("name") != "agentgateway" for i in ignores if i.get("kind") == "Deployment"),
      f"{[i for i in ignores if i.get('kind') == 'Deployment']}")
check("RespectIgnoreDifferences is on, so a sync does not revert the edit either",
      "RespectIgnoreDifferences=true" in APP["spec"]["syncPolicy"]["syncOptions"])

print("== block-argocd-drift lets the terminal, and only the terminal, UPDATE it ==")
conds = {c["name"]: c["expression"] for c in DRIFT["spec"]["matchConditions"]}
exempt = conds.get("not-terminal-c7-rule", "")
check("there is a not-terminal-c7-rule matchCondition", bool(exempt))
check("scoped to the terminal's ServiceAccount", f"request.userInfo.username == '{TERMINAL_SA}'" in exempt, exempt)
check("and to an UPDATE of the one ConfigMap, by kind, namespace and name, read optionally (a DELETE's object is empty)",
      "request.operation == 'UPDATE'" in exempt and "object.?kind.orValue('') == 'ConfigMap'" in exempt
      and "object.?metadata.?namespace.orValue('') == 'agent'" in exempt
      and "object.?metadata.?name.orValue('') == 'agentgateway-c7-config'" in exempt, exempt)
check("the exemption is a negated conjunction (it never widens to any of those alone)",
      exempt.strip().startswith("!(") and exempt.strip().endswith(")") and "||" not in exempt
      and exempt.count("&&") == 4, exempt)
check("DELETE is in no exemption", "DELETE" not in " ".join(conds.values()))
check("agent-sa is named in no exemption, so the agent cannot switch off its own C7 guard",
      "agent-sa" not in " ".join(conds.values()))
check("agentgateway-config is named in no exemption", "agentgateway-config'" not in " ".join(conds.values()))
check("the policy still denies ConfigMap UPDATE and DELETE",
      any("configmaps" in r.get("resources", []) and set(r.get("operations", [])) == {"UPDATE", "DELETE"}
          for r in DRIFT["spec"]["matchConstraints"]["resourceRules"]))

print("== RBAC: console-terminal already covers the toggle, and was not widened for it ==")
role = find(RESOURCES, "ClusterRole", "console-terminal")
rules = role.get("rules", [])
binding = find(RESOURCES, "ClusterRoleBinding", "console-terminal")
check("console-terminal is bound to the terminal's ServiceAccount, agent/web-terminal",
      binding.get("roleRef", {}).get("name") == "console-terminal"
      and {"kind": "ServiceAccount", "name": "web-terminal", "namespace": "agent"} in binding.get("subjects", []))


def grants(group: str, resource: str, verb: str, name: str | None = None) -> bool:
    return any((group in r.get("apiGroups", []) or "*" in r.get("apiGroups", []))
               and (resource in r.get("resources", []) or "*" in r.get("resources", []))
               and verb in r.get("verbs", []) and (not r.get("resourceNames") or name in r["resourceNames"])
               for r in rules)


check("console-terminal may get Argo CD applications (the admin-cluster test)",
      grants("argoproj.io", "applications", "get", "app-of-apps-admin"))
check("console-terminal may get configmaps", grants("", "configmaps", "get", "agentgateway-c7-config"))
check("console-terminal may patch configmaps", grants("", "configmaps", "patch", "agentgateway-c7-config"))
check("console-terminal may patch pods (the kubelet nudge)", grants("", "pods", "patch"))
check("no console-terminal rule names agentgateway-c7-config: the existing core-resource rule covers it",
      not any("agentgateway-c7-config" in r.get("resourceNames", []) for r in rules))
check("console-terminal still cannot write Argo CD applications",
      not any(grants("argoproj.io", "applications", v) for v in ("create", "update", "patch", "delete")))

# --- the toggles, executed (#516) ---------------------------------------------------------------------
ENTRYPOINT = (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_text(encoding="utf-8")
COMMITTED = c7_cm.get("data", {}).get("config.yaml", "")
ALL = ["get_weather", "read_internal_config", "apply_optimization"]
ON_RULE = 'mcp.tool.name == "get_weather"'

FAKE_KUBECTL = r"""#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["FAKE_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
state["calls"].append(args)
def done(rc=0):
    json.dump(state, open(state_path, "w")); sys.exit(rc)
if "get" in args and "application" in args:
    if state["cluster"] == "unreachable":
        done(1)
    if state["cluster"] == "admin":
        print("application.argoproj.io/app-of-apps-admin")
    done()
if "get" in args and "configmap" in args:
    print(json.dumps({"metadata": {"name": "agentgateway-c7-config", "resourceVersion": str(state["rv"])},
                      "data": {"config.yaml": state["config"]}}))
    done()
if "patch" in args and "configmap" in args:
    if state["race"]:
        state["rv"] += 1  # somebody else wrote the ConfigMap between the toggle's read and its patch
    ops = json.loads(args[args.index("-p") + 1])
    for op in ops:
        if op["op"] == "test" and op["path"] == "/metadata/resourceVersion" and op["value"] != str(state["rv"]):
            done(1)
    for op in ops:
        if op["op"] == "replace" and op["path"] == "/data/config.yaml":
            state["config"] = op["value"]
    state["rv"] += 1
    done()
if "patch" in args and "workshop-agent" in args:
    state["toolNames"] = json.loads(args[args.index("-p") + 1])[0]["value"]
    done()
done()
"""


def heredocs() -> dict:
    return dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', ENTRYPOINT, re.S))


def rules_of(text: str) -> list:
    cfg = yaml.safe_load(text) or {}
    return [x for b in cfg.get("binds", []) for li in b.get("listeners", []) for r in li.get("routes", [])
            for x in r.get("policies", {}).get("mcpAuthorization", {}).get("rules", [])]


def run(cluster: str, *commands: str, race: bool = False) -> tuple[dict, list[subprocess.CompletedProcess]]:
    """Run the named toggles in order, in a HOME the entrypoint's heredocs were written to, against the fake.
    toolNames starts as None, so 'never touched' is distinguishable from 'set to what it already was'."""
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


def gateway_pod_left_running(state: dict) -> bool:
    """No delete, restart or rollout of anything: the only pod write is the annotate that nudges the kubelet."""
    return not any(set(c) & {"delete", "rollout", "restart", "scale", "replace"} for c in state["calls"])


TOGGLES = ("guard-mcp-on", "guard-mcp-off", "guards-on", "guards-off")

print("== the toggles exist where the entrypoint writes them, in both copies ==")
docs = heredocs()
for name in (".guardlib", ".c7rule.py", *TOGGLES):
    check(f"the entrypoint writes ~/{name}", name in docs)
check("images/web-terminal/entrypoint.sh is byte-identical to gitops/ai-layer/web-terminal/entrypoint.sh",
      (REPO / "images/web-terminal/entrypoint.sh").read_bytes()
      == (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_bytes())

print("== admin cluster: guard-mcp-on narrows the gateway rule and leaves the allow-list full ==")
state, (on,) = run("admin", "guard-mcp-on")
check("guard-mcp-on exits 0", on.returncode == 0, on.stdout + on.stderr)
check("and says the guard is on at the gateway", "ON, at the gateway" in on.stdout, on.stdout)
check(f"the rule is now {ON_RULE!r}", rules_of(state["config"]) == [ON_RULE], f"{rules_of(state['config'])}")
check("only the `# c7-rule` line changed",
      [l for l in state["config"].split("\n") if not l.rstrip().endswith("# c7-rule")]
      == [l for l in COMMITTED.split("\n") if not l.rstrip().endswith("# c7-rule")])
check("evil-mcp's toolNames is the full list, so the rogue call reaches the gateway", state["toolNames"] == ALL,
      f"{state['toolNames']}")
check("the gateway pod is annotated so the kubelet refreshes the volume now",
      any("annotate" in c and "app.kubernetes.io/name=agentgateway" in c for c in state["calls"]))
check("and the gateway pod is not deleted, restarted or rolled out", gateway_pod_left_running(state),
      f"{state['calls']}")
cm_patch = next((c for c in state["calls"] if "patch" in c and "configmap" in c), [])
check("the ConfigMap write is a JSON patch", "--type=json" in cm_patch, f"{cm_patch}")
ops = json.loads(cm_patch[cm_patch.index("-p") + 1]) if "-p" in cm_patch else []
check("that tests the resourceVersion it read before replacing config.yaml",
      [o["op"] for o in ops] == ["test", "replace"]
      and ops[0] == {"op": "test", "path": "/metadata/resourceVersion", "value": "7"}
      and ops[1]["path"] == "/data/config.yaml", f"{ops}")

print("== admin cluster: guard-mcp-off opens it again, back to the committed file byte for byte ==")
state, (on, off) = run("admin", "guard-mcp-on", "guard-mcp-off")
check("guard-mcp-off exits 0 and says it is off at the gateway",
      off.returncode == 0 and "OFF, at the gateway" in off.stdout, off.stdout + off.stderr)
check("the rule is 'true' again", rules_of(state["config"]) == ["true"], f"{rules_of(state['config'])}")
check("and the config is the committed one exactly", state["config"] == COMMITTED)
check("toolNames stays full", state["toolNames"] == ALL, f"{state['toolNames']}")
check("nothing deleted, restarted or rolled out the gateway pod", gateway_pod_left_running(state))

print("== admin cluster: guards-on and guards-off flip the gateway rule too ==")
state, (gon,) = run("admin", "guards-on")
check("guards-on exits 0 and narrows the gateway rule", gon.returncode == 0 and rules_of(state["config"]) == [ON_RULE],
      gon.stdout + gon.stderr)
check("guards-on leaves toolNames full", state["toolNames"] == ALL, f"{state['toolNames']}")
check("guards-on leaves the on-topic guard alone (#455)", not any("topic" in " ".join(c) for c in state["calls"]))
check("guards-on reports no C7 failure", "did not switch" not in gon.stdout, gon.stdout)
state, (_, goff) = run("admin", "guards-on", "guards-off")
check("guards-off exits 0 and puts the committed config back byte for byte",
      goff.returncode == 0 and state["config"] == COMMITTED, goff.stdout + goff.stderr)
check("guards-off leaves toolNames full", state["toolNames"] == ALL, f"{state['toolNames']}")
check("neither deleted, restarted or rolled out the gateway pod", gateway_pod_left_running(state))

print("== workshop cluster: the toolNames toggle, unchanged, and the gateway ConfigMap never edited ==")
state, (on,) = run("attendee", "guard-mcp-on")
check("guard-mcp-on exits 0 and narrows toolNames to get_weather",
      on.returncode == 0 and state["toolNames"] == ["get_weather"], f"{state['toolNames']} {on.stdout}")
check("and says the rogue tools left the allow-list", "removed from the agent's allow-list" in on.stdout, on.stdout)
state, (_, off) = run("attendee", "guard-mcp-on", "guard-mcp-off")
check("guard-mcp-off exits 0 and restores the full toolNames list",
      off.returncode == 0 and state["toolNames"] == ALL, f"{state['toolNames']} {off.stdout}")
state, (gon,) = run("attendee", "guards-on")
check("guards-on narrows toolNames", gon.returncode == 0 and state["toolNames"] == ["get_weather"],
      f"{state['toolNames']} {gon.stdout}")
state, (_, goff) = run("attendee", "guards-on", "guards-off")
check("guards-off restores the full toolNames list", goff.returncode == 0 and state["toolNames"] == ALL,
      f"{state['toolNames']} {goff.stdout}")
state, _ = run("attendee", *TOGGLES)
check("none of the four toggles reads or edits the gateway ConfigMap on a workshop cluster",
      not patched_cm(state) and not any("configmap" in c for c in state["calls"]), f"{state['calls']}")

print("== when Argo CD cannot be asked, nothing is guessed ==")
for name in TOGGLES:
    state, (r,) = run("unreachable", name)
    direction = name.rsplit("-", 1)[1]
    check(f"{name} exits non-zero and says C7 did not switch {direction}",
          r.returncode != 0 and f"(C7) did not switch {direction}" in r.stdout, r.stdout + r.stderr)
    check(f"and {name} touched neither control", state["toolNames"] is None and not patched_cm(state),
          f"{state['toolNames']}")

print("== a stale read is refused, not written over ==")
for name in TOGGLES:
    state, (r,) = run("admin", name, race=True)
    direction = name.rsplit("-", 1)[1]
    check(f"{name} exits non-zero and says C7 did not switch {direction} when the ConfigMap changed under it",
          r.returncode != 0 and f"(C7) did not switch {direction}" in r.stdout, r.stdout + r.stderr)
    check(f"and {name} left the other writer's config and the allow-list as they were",
          state["config"] == COMMITTED and state["toolNames"] is None, f"{state['toolNames']}")

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

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("\nPASS: C7's gateway rule flips live on an admin cluster, only the web terminal may edit it, and Argo CD leaves"
      " the edit alone; a workshop cluster keeps its toolNames toggle")
