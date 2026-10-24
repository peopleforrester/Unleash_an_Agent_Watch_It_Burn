# ABOUTME: Render gate for C7's live gateway rule (#496, #515): the Argo CD ignore, the block-argocd-drift exemption
# ABOUTME: and the console-terminal RBAC that let the web terminal's edit of agentgateway-c7-config stick.
"""Why this exists (#515, part of #496).

On an admin cluster (the KubeCon breakout) C7 is to be stopped at agentgateway: the web terminal rewrites the
`# c7-rule` line of agentgateway-c7-config and the agentgateway-c7 container reloads it. Two platform
guardrails would undo or refuse that edit, and each failing looks the same on stage, a guard that says ON
and lets the sentinel out:
  - Argo CD selfHeal reverts it, unless ai-layer ignores that ConfigMap's config.yaml, and only that one;
  - Kyverno's block-argocd-drift denies it, unless the terminal, and only the terminal, may UPDATE it;
  - the terminal's RBAC has to let it read Argo CD applications, patch the ConfigMap and touch the pod.

This reads the manifests. The CEL itself is evaluated by the Kyverno CLI in test_kyverno_cel_policies.py
(E2E suite). The toggle child of #496 extends this file with the toggles themselves.
"""
from __future__ import annotations

import pathlib
import sys

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

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("\nPASS: only the web terminal may edit agentgateway-c7-config live, and Argo CD leaves the edit alone")
