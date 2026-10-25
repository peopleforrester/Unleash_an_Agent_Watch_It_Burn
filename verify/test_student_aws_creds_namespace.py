# ABOUTME: Holds the attendee's AWS key out of namespace agent (#584): it lives in student-creds, the web terminal
# ABOUTME: reads it there at boot, no agent identity can read that namespace, and the lab no longer says C8 dumps it.
"""The attendee key is out of the agent's reach (#584).

fleet.sh's bootstrap_student_aws used to push the attendee's IAM key into the student-aws-creds Secret in namespace
agent, and the web terminal mounted it with envFrom. That key holds EKS cluster-admin on its cluster
(aws_eks_access_policy_association.attendee_admin in infra/terraform/aws/cluster/main.tf). Under the broad
workshop-agent Role, the state Challenge 8 starts in, run_shell in workshop-mcp could read it with its own token,
presign an EKS token with no AWS call and reach the API server as cluster-admin. That identity is not an
agent-namespace ServiceAccount, so restrict-agent-spawned-workloads did not match it, and it could start a pod as
agent-sa, which has Bedrock credentials.

The key now lives in namespace student-creds. These checks hold every piece of that in place:

* the namespace is declared, and fleet.sh and the terminal's entrypoint name the same one;
* nothing in the AI layer mounts or references student-aws-creds from `agent`;
* no agent identity can read Secrets outside `agent`: the agent's Role is bound by a RoleBinding only, and no
  ClusterRoleBinding gives an agent-namespace account other than the terminal any read on Secrets;
* the agent may not start a pod as the terminal's ServiceAccount, the one account that can read the key;
* the C8 lab text no longer tells the student the Secret dump includes the AWS keys.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
NS = "student-creds"
SECRET = "student-aws-creds"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def docs(rel: str) -> list[dict]:
    return [d for d in yaml.safe_load_all((REPO / rel).read_text(encoding="utf-8")) if isinstance(d, dict)]


def live(text: str) -> str:
    """The text without its comment lines, so a comment explaining the old shape is not read as the shape."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


print("== the key's namespace is declared, and every piece names the same one ==")
ns_names = [d["metadata"]["name"] for d in docs("gitops/namespaces/namespaces.yaml") if d.get("kind") == "Namespace"]
check(f"gitops/namespaces declares {NS}", NS in ns_names, f"namespaces: {ns_names}")
fleet = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
check(f"fleet.sh pushes the key to {NS}", f'readonly STUDENT_AWS_NS="{NS}"' in fleet)
check("and passes that namespace to the push script", '--namespace "${STUDENT_AWS_NS}"' in fleet)
ENTRYPOINTS = ("gitops/ai-layer/web-terminal/entrypoint.sh", "images/web-terminal/entrypoint.sh")
for rel in ENTRYPOINTS:
    ep = live((REPO / rel).read_text(encoding="utf-8"))
    check(f"{rel} reads {SECRET} from {NS}",
          f"STUDENT_AWS_NS={NS}" in ep and f'kubectl -n "$STUDENT_AWS_NS" get secret {SECRET}' in ep)
    # The old shape: the key arrived as container env from a Secret in `agent`.
    check(f"{rel} no longer takes the key from its environment",
          "${AWS_ACCESS_KEY_ID" not in ep and "${AWS_SECRET_ACCESS_KEY" not in ep)

print(f"== nothing in the AI layer mounts {SECRET} from agent ==")
AI_FILES = sorted((REPO / "gitops/ai-layer").glob("*.yaml"))
mentions = [str(p.relative_to(REPO)) for p in AI_FILES if SECRET in live(p.read_text(encoding="utf-8"))]
check(f"no AI-layer manifest names {SECRET} outside a comment", not mentions, f"{mentions}")
AI = [d for p in AI_FILES for d in yaml.safe_load_all(p.read_text(encoding="utf-8")) if isinstance(d, dict)]
term = next((d for d in AI if d.get("kind") == "Deployment" and d["metadata"].get("name") == "web-terminal"), None)
check("the web-terminal Deployment is found", term is not None)
if term:
    pod = term["spec"]["template"]["spec"]
    refs = [r.get("secretRef", {}).get("name") for c in pod.get("containers", []) for r in c.get("envFrom", [])]
    refs += [e.get("valueFrom", {}).get("secretKeyRef", {}).get("name")
             for c in pod.get("containers", []) for e in c.get("env", [])]
    refs += [v.get("secret", {}).get("secretName") for v in pod.get("volumes", [])]
    check(f"the terminal mounts no {SECRET}", SECRET not in refs, f"secret refs: {refs}")
    check("the terminal still runs as web-terminal, the account that reads the key",
          pod.get("serviceAccountName") == "web-terminal")

print("== no agent identity can read Secrets outside agent ==")
kust = yaml.safe_load((REPO / "gitops/ai-layer/kustomization.yaml").read_text(encoding="utf-8"))
check("the AI layer lands in namespace agent", kust.get("namespace") == "agent")
bindings = [d for d in AI if d.get("kind") == "RoleBinding" and d["metadata"].get("name") == "workshop-agent"]
check("the agent's Role is bound by a RoleBinding, which reaches its own namespace only",
      len(bindings) == 1 and bindings[0]["roleRef"]["kind"] == "Role")
check("no ClusterRoleBinding binds the workshop-agent Role",
      not any(d.get("kind") == "ClusterRoleBinding" and d["roleRef"]["name"] == "workshop-agent" for d in AI))
cluster_roles = {d["metadata"]["name"]: d for d in AI if d.get("kind") == "ClusterRole"}


def reads_secrets(role: dict) -> bool:
    for r in role.get("rules", []):
        if ("" in r.get("apiGroups", []) or "*" in r.get("apiGroups", [])) \
                and ({"secrets", "*"} & set(r.get("resources", []))) \
                and ({"get", "list", "watch", "*"} & set(r.get("verbs", []))):
            return True
    return False


readers = []
for crb in (d for d in AI if d.get("kind") == "ClusterRoleBinding"):
    role = cluster_roles.get(crb["roleRef"]["name"])
    for s in crb.get("subjects", []):
        # Kustomize fills in namespace agent for a ServiceAccount subject that names none.
        if s.get("kind") == "ServiceAccount" and s.get("namespace", "agent") == "agent" \
                and s["name"] != "web-terminal" and (role is None or reads_secrets(role)):
            readers.append(f"{crb['metadata']['name']} -> {s['name']}")
check("no ClusterRoleBinding gives an agent-namespace account but the terminal any read on Secrets",
      not readers, f"{readers}")
check("the terminal's ClusterRole does read Secrets, so its entrypoint can fetch the key",
      "console-terminal" in cluster_roles and reads_secrets(cluster_roles["console-terminal"]))
in_ns = [str(p.relative_to(REPO)) for root in ("gitops", "policies") for p in sorted((REPO / root).rglob("*.yaml"))
         if re.search(rf"(?m)^\s*namespace:\s*{NS}\s*$", live(p.read_text(encoding="utf-8")))]
check(f"no manifest puts a Role, RoleBinding or anything else in {NS}", not in_ns, f"{in_ns}")

print("== the agent may not start a pod as the terminal's account ==")
pol = yaml.safe_load((REPO / "policies/kyverno/restrict-agent-spawned-workloads.yaml").read_text(encoding="utf-8"))
ids = {v["name"]: v["expression"] for v in pol["spec"]["variables"]}.get("modelIdentities", "")
check("restrict-agent-spawned-workloads refuses agent pods that run as web-terminal", "'web-terminal'" in ids, ids)
check("and it denies, rather than audits", pol["spec"].get("validationActions") == ["Deny"])

print("== Challenge 8 no longer says the Secret dump includes the AWS keys ==")
lab = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
m = re.search(r"Challenge 8:.*?(?=Challenge 9:)", lab, re.S)
c8 = " ".join(m.group(0).split()) if m else ""
check("C8 section found", bool(c8))
check("no C8 line names the AWS keys or creds among the Secrets", not re.search(r"(?i)AWS (keys|creds)", c8),
      ", ".join(re.findall(r"(?i)[^.]*AWS (?:keys|creds)[^.]*", c8)))
check("the terminal password is still named as part of the dump", "including the terminal password" in c8)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All student-aws-creds namespace checks passed.")
