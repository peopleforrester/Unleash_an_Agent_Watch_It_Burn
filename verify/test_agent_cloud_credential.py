# ABOUTME: Render gate for #203: agent-sa holds ONE cloud credential (Pod Identity, Bedrock invoke on four models),
# ABOUTME: no IRSA annotation and no Kubernetes token by default, IMDS denied by a readable rule, and the C8 probe.
"""What the agent's identity is, pinned where it is written down (#203).

The issue asked to prove the agent pod holds no cloud credential. Measured on attendee-001 2026-09-04, that
premise was wrong: the kagent container calls Bedrock and gets a credential for it through EKS Pod Identity.
The honest claim, and the one checked here, is narrower and stronger: ONE credential, bound by a Pod Identity
association rather than an annotation, scoped to Bedrock invoke on the four workshop models, with IMDS closed
twice (node hop limit, and an Admin-tier deny the lab can show). The live half, that the credential really
reaches Nova Pro and nothing else, is verify/test_agent_cloud_credential_live.py.
"""
from __future__ import annotations

import ipaddress
import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
RES_TEXT = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
RES = [d for d in yaml.safe_load_all(RES_TEXT) if d]
TF = (REPO / "infra/terraform/aws/cluster/main.tf").read_text(encoding="utf-8")
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
CNP_DIR = REPO / "policies/cluster-network-policies"
IMDS = ipaddress.ip_address("169.254.169.254")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def find(kind: str, name: str) -> dict:
    hits = [d for d in RES if d.get("kind") == kind and d["metadata"]["name"] == name]
    return hits[0] if hits else {}


def hcl_list(name: str) -> list[str]:
    """The string items of a `name = [ ... ]` list in main.tf's locals."""
    m = re.search(rf"^\s*{name}\s*=\s*\[(.*?)\]", TF, re.S | re.M)
    return re.findall(r'"([^"]+)"', m.group(1)) if m else []


print("== agent-sa: no identity annotation, no default Kubernetes token ==")
sa = find("ServiceAccount", "agent-sa")
check("agent-sa is defined in the ai-layer bundle", bool(sa))
annotations = (sa.get("metadata") or {}).get("annotations") or {}
check("agent-sa carries no IRSA annotation (eks.amazonaws.com/role-arn)",
      not any(k.startswith("eks.amazonaws.com/") for k in annotations))
check("agent-sa does not automount its Kubernetes token", sa.get("automountServiceAccountToken") is False)
# The stale note claimed a bootstrap step adds an IRSA annotation. None does, and none may: enable_irsa = false.
check("no manifest still says an IRSA annotation is added to agent-sa",
      "verify-at-build: bootstrap adds eks.amazonaws.com/role-arn" not in RES_TEXT
      and "agent-sa IRSA is added" not in (REPO / "gitops/apps/ai-layer.yaml").read_text(encoding="utf-8"))
check("the clusters have no IRSA/OIDC provider to annotate against", re.search(r"enable_irsa\s*=\s*false", TF) is not None)

print("== the token goes only to the pod whose tools call the API ==")
mcp = find("Deployment", "workshop-mcp")
mcp_pod = mcp.get("spec", {}).get("template", {}).get("spec", {})
check("workshop-mcp runs as agent-sa", mcp_pod.get("serviceAccountName") == "agent-sa")
check("workshop-mcp opts back in to the token (its REAL tools call the API)",
      mcp_pod.get("automountServiceAccountToken") is True)
check("and the server really reads the default token path",
      "/var/run/secrets/kubernetes.io/serviceaccount" in
      (REPO / "gitops/ai-layer/workshop-mcp-server.py").read_text(encoding="utf-8"))
agent = find("Agent", "workshop-agent")
dep = agent.get("spec", {}).get("declarative", {}).get("deployment", {})
check("BurritoBot runs as agent-sa and does not re-enable the token",
      dep.get("serviceAccountName") == "agent-sa" and "automountServiceAccountToken" not in dep)
pods_as_agent_sa = [d["metadata"]["name"] for d in RES
                    if d.get("kind") in ("Deployment", "StatefulSet", "DaemonSet", "Job")
                    and d["spec"]["template"]["spec"].get("serviceAccountName") == "agent-sa"]
check("workshop-mcp is the only workload in the bundle that runs as agent-sa", pods_as_agent_sa == ["workshop-mcp"])

print("== the one cloud credential: a Pod Identity association, Bedrock invoke, four models ==")
check("agent:agent-sa is bound by a Pod Identity association",
      re.search(r'namespace\s*=\s*"agent"\s*\n\s*service_account\s*=\s*"agent-sa"', TF) is not None)
profiles = hcl_list("bedrock_profiles")
check("four inference profiles, Nova Pro among them", len(profiles) == 4 and "us.amazon.nova-pro-v1:0" in profiles)
policy = re.search(r'resource "aws_iam_policy" "bedrock_invoke" \{(.*?)\n\}', TF, re.S)
# Comments stripped: the body's own comment records that it WAS Resource = "*" (#138).
body = re.sub(r"#[^\n]*", "", policy.group(1)) if policy else ""
check("bedrock_invoke policy found", bool(body))
check("its Resource is not \"*\"", not re.search(r'Resource\s*=\s*"\*"', body))
check("its actions are the four invoke actions and nothing else",
      sorted(re.findall(r'"(bedrock:[A-Za-z]+)"', body)) ==
      sorted(["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse", "bedrock:ConverseStream"]))
check("it names both the profile ARN and the foundation-model ARN (cross-region needs both)",
      "inference-profile/${p}" in body and "foundation-model/${m}" in body)
check("the stale \"agent policy is Resource = *\" comment is gone", 'Bedrock policy above, which is Resource = "*"' not in TF)

print("== IMDS: node hop limit, and an explicit deny the lab can show ==")
check("node IMDSv2 required", re.search(r'http_tokens\s*=\s*"required"', TF) is not None)
check("node IMDS PUT response hop limit 1", re.search(r"http_put_response_hop_limit\s*=\s*1\b", TF) is not None)
cnps = [d for f in sorted(CNP_DIR.glob("*.yaml")) for d in yaml.safe_load_all(f.read_text(encoding="utf-8")) if d]
deny = next((d for d in cnps if d.get("kind") == "ClusterNetworkPolicy" and d["metadata"]["name"] == "agent-deny-imds"), {})
spec = deny.get("spec", {})
check("ClusterNetworkPolicy agent-deny-imds exists (networking.k8s.aws/v1alpha1)",
      deny.get("apiVersion") == "networking.k8s.aws/v1alpha1")
check("it is Admin tier, so no NetworkPolicy can override it", spec.get("tier") == "Admin")
check("its subject is the agent namespace",
      spec.get("subject", {}).get("namespaces", {}).get("matchLabels") == {"kubernetes.io/metadata.name": "agent"})
deny_nets = [n for r in spec.get("egress", []) if r.get("action") == "Deny" for t in r.get("to", []) for n in t.get("networks", [])]
check("it denies egress to exactly 169.254.169.254/32", deny_nets == ["169.254.169.254/32"])
check("it never touches the Pod Identity agent (169.254.170.23)", "169.254.170.23" not in json.dumps(spec))

app = yaml.safe_load((REPO / "gitops/apps/cluster-network-policies.yaml").read_text(encoding="utf-8"))
check("its own Application syncs policies/cluster-network-policies",
      app["spec"]["source"]["path"] == "policies/cluster-network-policies")
for profile, root in (("attendee", "attendee/app-of-apps-attendee.yaml"), ("full", "full/app-of-apps.yaml"),
                      ("admin", "admin/app-of-apps-admin.yaml")):
    text = (REPO / "gitops/bootstrap" / root).read_text(encoding="utf-8")
    excl = re.search(r"exclude:\s*'([^']*)'", text)
    check(f"the {profile} profile does not exclude it",
          not excl or "cluster-network-policies" not in excl.group(1))


def allows_imds(doc: dict) -> bool:
    for rule in (doc.get("spec", {}).get("egress") or []):
        for t in rule.get("to") or []:
            cidr = t.get("ipBlock", {}).get("cidr")
            if cidr and IMDS in ipaddress.ip_network(cidr) and \
                    not any(IMDS in ipaddress.ip_network(e) for e in t["ipBlock"].get("except", [])):
                return True
    return False


fixes = find("ConfigMap", "challenge-fixes").get("data", {})
agent_netpols = [d for f in (REPO / "policies/network-policies/per-namespace").glob("agent-*.yaml")
                 for d in yaml.safe_load_all(f.read_text(encoding="utf-8")) if d]
agent_netpols += [d for d in yaml.safe_load_all(fixes.get("c1-network-policy.yaml", "")) if d]
check("no agent-namespace NetworkPolicy (platform or C1 copy) allows IMDS", agent_netpols and not any(map(allows_imds, agent_netpols)))

print("== the C8 probe: read-only, as agent-sa, admitted on a sealed cluster ==")
check("the probe is staged in ~/challenges", "cloud-credential-probe.yaml" in fixes)
job = yaml.safe_load(fixes.get("cloud-credential-probe.yaml", "{}")) or {}
jpod = job.get("spec", {}).get("template", {}).get("spec", {})
check("it is a Job (owned pods get reliable VPC CNI policy enforcement)", job.get("kind") == "Job")
check("it runs as agent-sa, so it gets exactly the agent's AWS credential", jpod.get("serviceAccountName") == "agent-sa")
check("it mounts no Kubernetes token", jpod.get("automountServiceAccountToken") is False)
term = find("Deployment", "web-terminal")["spec"]["template"]["spec"]["containers"][0]["image"]
probe_c = (jpod.get("containers") or [{}])[0]
check("its image is the web terminal's, pinned by the same digest (signed, already on the node)",
      probe_c.get("image") == term and "@sha256:" in term)
check("it carries resource limits (require-resource-limits is armed in Round 2)",
      bool(probe_c.get("resources", {}).get("limits")))
script = (probe_c.get("args") or [""])[0]
for needle, why in (("sts get-caller-identity", "who am I"),
                    ("--model-id us.amazon.nova-pro-v1:0", "Nova Pro, the allowed call"),
                    ("--model-id us.anthropic.claude-sonnet-5", "a model off the list"),
                    ("s3api list-buckets", "S3"), ("ec2 describe-instances", "EC2"), ("iam list-roles", "IAM"),
                    ("http://169.254.169.254/", "IMDS")):
    check(f"the probe tries {why}", needle in script)
check("the off-list model really is off the list", "us.anthropic.claude-sonnet-5" not in profiles)
# Every AWS call is `try "<label>" a <service> <operation>`; each operation must be one that only reads
# (converse spends five tokens and writes nothing), and nothing may call aws outside try.
calls = re.findall(r'^\s*try "[^"]*" a ([a-z0-9-]+) ([a-z0-9-]+)', script, re.M)
check("the probe calls aws only through try", script.count(" aws ") == 1 and len(calls) == len(re.findall(r'\btry "', script)))
READ_ONLY = {("sts", "get-caller-identity"), ("bedrock-runtime", "converse"), ("s3api", "list-buckets"),
             ("ec2", "describe-instances"), ("iam", "list-roles")}
check("every AWS call the probe makes only reads", bool(calls) and set(calls) <= READ_ONLY)

print("== the policy the lab shows matches the terraform ==")
shown = json.loads(fixes.get("agent-bedrock-policy.json", "{}") or "{}")
stmt = (shown.get("Statement") or [{}])[0]
models = [p.replace("us.", "", 1) for p in profiles]
expected = ([f"arn:aws:bedrock:*:<account>:inference-profile/{p}" for p in profiles] +
            [f"arn:aws:bedrock:*::foundation-model/{m}" for m in models])
check("the staged policy lists exactly the terraform's resources", stmt.get("Resource") == expected)
check("and exactly its actions", sorted(stmt.get("Action", [])) ==
      sorted(re.findall(r'"(bedrock:[A-Za-z]+)"', body)))

print("== the lab beat ==")
m = re.search(r"Challenge 8:.*?(?=Challenge 9:)", LAB, re.S)
c8 = m.group(0) if m else ""
for cmd in ("kubectl -n agent get sa agent-sa -o yaml",
            "kubectl -n agent exec deploy/workshop-agent -c kagent -- sh -c 'env | grep ^AWS_; ls -a ~/.aws'",
            "kubectl apply -f ~/challenges/cloud-credential-probe.yaml",
            "kubectl -n agent logs job/cloud-credential-probe",
            "kubectl get clusternetworkpolicy agent-deny-imds -o yaml",
            "cat ~/challenges/agent-bedrock-policy.json"):
    check(f"C8 runs: {cmd[:60]}", cmd in c8)
check("the lab does not claim the agent holds no cloud credential", "no cloud credential" not in LAB)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ALL AGENT CLOUD-CREDENTIAL CHECKS PASSED")
