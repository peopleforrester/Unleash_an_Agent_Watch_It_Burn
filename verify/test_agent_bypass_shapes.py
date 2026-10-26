# ABOUTME: Holds restrict-agent-spawned-workloads (#490) to its two sources: the Bedrock Pod Identity associations
# ABOUTME: in namespace agent, and every label a NetworkPolicy there selects pods on. Offline: terraform and YAML.
"""Why (#490). The policy lists the ServiceAccounts that hold Bedrock credentials and the labels a NetworkPolicy
trusts, by hand, because CEL cannot read terraform or another object's spec. A list that falls behind fails open
and silently: a new association in main.tf, or a new `podSelector` allow in the agent namespace, would be a new
bypass the policy does not know about. So each list is read here from where it is decided, and must match.

It also checks the fact the policy's reasoning stands on: the agent egress allowlist selects the whole namespace,
both as the platform ships it and as the student applies it in Challenge 1. If that went back to a label, a pod
without the label would leave by the public internet and none of this would matter.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
from bootstrap_chart import is_template  # noqa: E402
POLICY = REPO / "policies/kyverno/restrict-agent-spawned-workloads.yaml"
TERRAFORM = REPO / "infra/terraform/aws/cluster/main.tf"
NS = "agent"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


policy = yaml.safe_load(POLICY.read_text())
spec = policy["spec"]
variables = {v["name"]: v["expression"] for v in spec.get("variables") or []}
messages = " ".join(" ".join(v["message"].split()) for v in spec["validations"])

print("== the Bedrock identities are the terraform's ==")
tf = TERRAFORM.read_text()
associated = set(re.findall(r'namespace\s*=\s*"agent"\s*\n\s*service_account\s*=\s*"([^"]+)"', tf))
listed = set(re.findall(r"'([^']+)'", variables.get("modelIdentities", "")))
check("main.tf has Pod Identity associations in namespace agent", bool(associated))
check("modelIdentities is every ServiceAccount with a Pod Identity association in agent",
      listed == associated, f"policy lists {sorted(listed)}, main.tf associates {sorted(associated)}")
check("the refusal names each of them", all(sa in messages for sa in associated), messages)

print("== the labels are every label a NetworkPolicy in agent selects on ==")


def network_policies() -> list[tuple[str, dict]]:
    """Every NetworkPolicy that lands in agent: gitops/ (ai-layer's kustomization sets the namespace) and
    policies/, plus the ones a student applies from the challenge-fixes ConfigMap."""
    out = []
    for root in ("gitops", "policies"):
        for f in sorted((REPO / root).rglob("*.y*ml")):
            if is_template(f):  # the root chart's Go templates (#609): a repository Secret, no NetworkPolicy
                continue
            default_ns = NS if f.parent == REPO / "gitops/ai-layer" else None
            for doc in yaml.safe_load_all(f.read_text()):
                if not isinstance(doc, dict):
                    continue
                embedded = []
                if doc.get("kind") == "ConfigMap":
                    for key, text in (doc.get("data") or {}).items():
                        if "kind: NetworkPolicy" in str(text):
                            embedded += [(f"{f.relative_to(REPO)}:{key}", d) for d in yaml.safe_load_all(text) if d]
                for where, d in [(str(f.relative_to(REPO)), doc), *embedded]:
                    if d.get("kind") == "NetworkPolicy" and (d["metadata"].get("namespace") or default_ns) == NS:
                        out.append((where, d))
    return out


def selectors(np: dict) -> list[dict]:
    s = np.get("spec") or {}
    peers = [p for rule in (s.get("ingress") or []) for p in rule.get("from") or []]
    peers += [p for rule in (s.get("egress") or []) for p in rule.get("to") or []]
    return [s.get("podSelector") or {}] + [p["podSelector"] for p in peers if "podSelector" in p]


nps = network_policies()
check("NetworkPolicies in namespace agent were found", len(nps) >= 6, f"found {len(nps)}")
want: dict[str, set[str]] = {}
expressions = []
for where, np in nps:
    for sel in selectors(np):
        if sel.get("matchExpressions"):
            expressions.append(f"{where} {np['metadata']['name']}")
        for k, v in (sel.get("matchLabels") or {}).items():
            want.setdefault(k, set()).add(v)
check("no NetworkPolicy in agent selects with matchExpressions (the policy's list cannot express one)",
      not expressions, repr(expressions))
pairs = re.findall(r"'([^']+)':\s*\[([^\]]*)\]", variables.get("egressLabels", ""))
have = {k: set(re.findall(r"'([^']+)'", vs)) for k, vs in pairs}
check("egressLabels is every label a NetworkPolicy in agent selects pods on", have == want,
      f"policy lists {have}, the NetworkPolicies select on {want}")
check("the refusal names each of them", all(f"{k}={v}" in messages for k, vs in want.items() for v in vs), messages)

print("== the reasoning's footing: the egress allowlist covers the whole namespace ==")
allowlists = [(w, np) for w, np in nps if np["metadata"]["name"] == "agent-egress-allowlist"]
check("agent-egress-allowlist exists as shipped and as the C1 fix", len(allowlists) == 2, repr([w for w, _ in allowlists]))
for where, np in allowlists:
    check(f"{where}: it selects every pod (podSelector: {{}}), not a label a pod may lack",
          np["spec"].get("podSelector") == {}, repr(np["spec"].get("podSelector")))
    check(f"{where}: it is an Egress policy", "Egress" in (np["spec"].get("policyTypes") or []))

print("== the policy refuses, and only the agent's requests ==")
check("it ships Deny (a report of a bypass that already ran is not a control)", spec["validationActions"] == ["Deny"])
check("background evaluation is off (it reads request.userInfo)", spec["evaluation"]["background"]["enabled"] is False)
cond = " ".join(m["expression"] for m in spec.get("matchConditions") or [])
check("it is scoped to requests from agent-namespace ServiceAccounts",
      "startsWith('system:serviceaccount:agent:')" in cond, cond)
check("the attendee's terminal is left out", "'system:serviceaccount:agent:web-terminal'" in cond, cond)
check("autogen is not switched off (a Deployment is refused at the Deployment)",
      (spec.get("autogen") or {}).get("podControllers", {}).get("controllers") != [])

print("== the agent's shell holds no Bedrock identity (#553) ==")
# run_shell is a shell in workshop-mcp. If that pod ran as a Bedrock-bound account, the shell could call the model
# over the in-VPC endpoint with no new pod, and this policy, which judges pod creation, would never see it.
AI = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if isinstance(d, dict)]


def ai(kind: str, name: str) -> dict:
    found = [d for d in AI if d.get("kind") == kind and d["metadata"]["name"] == name]
    return found[0] if len(found) == 1 else {}


mcp_sa = ai("Deployment", "workshop-mcp").get("spec", {}).get("template", {}).get("spec", {})
mcp_sa = mcp_sa.get("serviceAccountName") or mcp_sa.get("serviceAccount") or "default"
check("workshop-mcp runs as its own ServiceAccount, workshop-mcp", mcp_sa == "workshop-mcp", mcp_sa)
check("that ServiceAccount is declared", bool(ai("ServiceAccount", "workshop-mcp")))
check("it has no Pod Identity association in main.tf", mcp_sa not in associated,
      f"main.tf associates {sorted(associated)}")
check("and no IRSA role annotation either",
      "eks.amazonaws.com/role-arn" not in (ai("ServiceAccount", "workshop-mcp").get("metadata", {}).get("annotations") or {}))
binding = ai("RoleBinding", "workshop-agent")
check("it is bound to the agent's Role alongside agent-sa, so C8's token theft and fix still apply to the tool pod",
      binding.get("roleRef", {}).get("name") == "workshop-agent"
      and {s["name"] for s in binding.get("subjects", []) if s.get("kind") == "ServiceAccount"} >= {"agent-sa", mcp_sa},
      repr(binding.get("subjects")))
check("its requests are an agent-namespace identity's, so it may not start a pod as agent-sa either",
      mcp_sa != "web-terminal" and mcp_sa not in listed)
# A token for agent-sa could still be minted or borrowed through the API. The Role the shell carries, as shipped and
# as both C8 files apply it, must not grant either.
fixes = ai("ConfigMap", "challenge-fixes").get("data") or {}
roles = [("shipped", ai("Role", "workshop-agent"))] + [
    (key, yaml.safe_load(fixes[key])) for key in ("c8-broad-role.yaml", "c8-scoped-role.yaml") if key in fixes]
check("the agent's Role is found as shipped and in both C8 files", len(roles) == 3 and all(r for _, r in roles),
      repr([k for k, _ in roles]))
for where, role in roles:
    grants = [(res, verb) for rule in role.get("rules") or [] for res in rule.get("resources") or []
              for verb in rule.get("verbs") or []]
    check(f"{where}: the agent's Role cannot mint or borrow another account's token",
          not any(res in ("serviceaccounts", "serviceaccounts/token", "*") or verb in ("impersonate", "*")
                  for res, verb in grants), repr(grants))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("restrict-agent-spawned-workloads matches its sources.")
