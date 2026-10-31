# ABOUTME: Render gate for #203: agent-sa holds ONE cloud credential (Pod Identity, Bedrock invoke on four models),
# ABOUTME: no IRSA annotation and no Kubernetes token, IMDS denied by a readable rule, and the C8 probe that shows it.
"""What the agent's identity is, pinned where it is written down (#203).

The issue asked to prove the agent pod holds no cloud credential. Measured on attendee-001 2026-09-04, that
premise was wrong: the kagent container calls Bedrock and gets a credential for it through EKS Pod Identity.
The claim checked here is Michael's reframe on the issue, narrower and stronger: ONE credential, bound by a Pod
Identity association rather than an annotation, scoped to Bedrock invoke on the four workshop models, with IMDS
closed twice (the node's hop limit, and an Admin-tier deny the lab can show).

What this does not prove, and where that is proven: that AWS accepts the policy and that it allows Nova Pro and
nothing wider is test_iam_policy_aws.py (Access Analyzer and the policy simulator over infra/org/effect-tests.yaml);
that the probe Job is admitted is test_cloud_credential_probe_admission.py; that the credential on a real cluster
reaches Nova Pro and nothing else, and that IMDS does not answer, is test_agent_cloud_credential_live.py.
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
RES = [d for d in yaml.safe_load_all(RES_TEXT) if isinstance(d, dict)]
# The Agent is the workshop-agent Application's since #707, in its own bundle.
AGENT_DOCS = [d for d in yaml.safe_load_all((REPO / "gitops/workshop-agent/agent.yaml").read_text(encoding="utf-8"))
              if isinstance(d, dict)]
TF = (REPO / "infra/terraform/aws/cluster/main.tf").read_text(encoding="utf-8")
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
CNP_DIR = REPO / "policies/cluster-network-policies"
BOOT = REPO / "gitops/bootstrap"
IMDS = ipaddress.ip_address("169.254.169.254")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def find(kind: str, name: str) -> dict:
    hits = [d for d in RES + AGENT_DOCS if d.get("kind") == kind and (d.get("metadata") or {}).get("name") == name]
    return hits[0] if hits else {}


def pod_spec(doc: dict) -> dict:
    spec = doc.get("spec") or {}
    if doc.get("kind") == "CronJob":
        spec = (spec.get("jobTemplate") or {}).get("spec") or {}
    return ((spec.get("template") or {}).get("spec")) or {}


def profile_apps(profile: str) -> list[str]:
    return (yaml.safe_load((BOOT / f"values-{profile}.yaml").read_text(encoding="utf-8")) or {}).get("apps") or []


print("== agent-sa: no identity annotation, no Kubernetes token ==")
sa = find("ServiceAccount", "agent-sa")
check("agent-sa is defined in the ai-layer bundle", bool(sa))
annotations = (sa.get("metadata") or {}).get("annotations") or {}
check("agent-sa carries no IRSA annotation (eks.amazonaws.com/role-arn)",
      not any(k.startswith("eks.amazonaws.com/") for k in annotations))
check("agent-sa does not automount its Kubernetes token", sa.get("automountServiceAccountToken") is False)
# The stale notes claimed a bootstrap step adds an IRSA annotation. None does, and none may: enable_irsa = false.
stale = [p for p in (REPO / "gitops/ai-layer/resources.yaml", BOOT / "apps/ai-layer.yaml", BOOT / "values-burn.yaml")
         if re.search(r"agent-sa IRSA|adds eks\.amazonaws\.com/role-arn|Bedrock IRSA", p.read_text(encoding="utf-8"))]
check(f"no manifest still says agent-sa gets an IRSA annotation {[p.name for p in stale]}", not stale)
check("the clusters have no IRSA/OIDC provider to annotate against", re.search(r"enable_irsa\s*=\s*false", TF) is not None)

print("== the only pod that runs as agent-sa is BurritoBot's, and it does not take the token back ==")
agent = find("Agent", "workshop-agent")
dep = ((agent.get("spec") or {}).get("declarative") or {}).get("deployment") or {}
check("BurritoBot runs as agent-sa", dep.get("serviceAccountName") == "agent-sa")
check("and does not re-enable the token", "automountServiceAccountToken" not in dep)
WORKLOADS = ("Pod", "Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob")
bundle = [d for f in sorted([*(REPO / "gitops/ai-layer").glob("*.yaml"), *(REPO / "gitops/workshop-agent").glob("*.yaml")])
          for d in yaml.safe_load_all(f.read_text(encoding="utf-8")) if isinstance(d, dict)]
as_agent_sa = [d["metadata"]["name"] for d in bundle if d.get("kind") in WORKLOADS
               and ((d.get("spec") or {}).get("serviceAccountName") == "agent-sa"
                    or pod_spec(d).get("serviceAccountName") == "agent-sa")]
check(f"no Deployment, Job or other workload in gitops/ai-layer or gitops/workshop-agent runs as agent-sa {as_agent_sa}", not as_agent_sa)
mcp = pod_spec(find("Deployment", "workshop-mcp"))
check("the tools that call the API run as workshop-mcp, not agent-sa (#553)", mcp.get("serviceAccountName") == "workshop-mcp")
check("and keep their token (the account does not turn automount off)",
      find("ServiceAccount", "workshop-mcp").get("automountServiceAccountToken") is not False
      and mcp.get("automountServiceAccountToken") is not False)
check("that server really reads the default token path",
      "/var/run/secrets/kubernetes.io/serviceaccount" in
      (REPO / "gitops/ai-layer/workshop-mcp-server.py").read_text(encoding="utf-8"))
rb = find("RoleBinding", "workshop-agent")
check("agent-sa keeps its Role, which Challenge 8 impersonates with no token",
      {"agent-sa", "workshop-mcp"} <= {s.get("name") for s in rb.get("subjects") or []})

print("== the one cloud credential: a Pod Identity association, Bedrock invoke, four models ==")
check("agent:agent-sa is bound by a Pod Identity association",
      re.search(r'namespace\s*=\s*"agent"\s*\n\s*service_account\s*=\s*"agent-sa"', TF) is not None)
tiers = re.search(r"bedrock_tiers\s*=\s*\{(.*?)\}", TF, re.S)
profiles = re.findall(r'=\s*"([^"]+)"', tiers.group(1)) if tiers else []
check("four inference profiles, Nova Pro among them", len(profiles) == 4 and "us.amazon.nova-pro-v1:0" in profiles)
policy = re.search(r'resource "aws_iam_policy" "bedrock_invoke" \{(.*?)\n\}', TF, re.S)
# Comments stripped: the body's own comment records that it WAS Resource = "*" (#138).
body = re.sub(r"#[^\n]*", "", policy.group(1)) if policy else ""
check("bedrock_invoke policy found", bool(body))
check('no Resource is a bare "*"', bool(body) and not re.search(r'Resource\s*=\s*"\*"', body))
ACTIONS = ["bedrock:Converse", "bedrock:ConverseStream", "bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
check("its actions are the four invoke actions and nothing else",
      sorted(set(re.findall(r'"([a-z0-9-]+:[A-Za-z*]+)"', body))) == ACTIONS)
check("it names both the profile ARN and the foundation-model ARN (cross-region needs both)",
      "inference-profile/${p}" in body and "foundation-model/${m}" in body)
check('the stale "agent policy is Resource = *" comment is gone', 'Bedrock policy above, which is Resource = "*"' not in TF)
check("the stale verify-at-build notes on Pod Identity are gone",
      "confirm kagent picks up Pod Identity creds" not in TF and "confirm Pod Identity still resolves at hop=1" not in TF)

print("== the policy the lab shows matches the terraform ==")
fixes = find("ConfigMap", "challenge-fixes").get("data") or {}
shown = json.loads(fixes.get("agent-bedrock-policy.json") or "{}")
stmts = shown.get("Statement") or []
tf_stmts = re.split(r"\}\s*,\s*\{", body)
check("the staged policy has the terraform's two statements", len(stmts) == 2 and len(tf_stmts) == 2)
if len(stmts) == 2 and len(tf_stmts) == 2:
    models = [p.replace("us.", "", 1) for p in profiles]
    expected = ([f"arn:aws:bedrock:*:<account>:inference-profile/{p}" for p in profiles] +
                [f"arn:aws:bedrock:*::foundation-model/{m}" for m in models])
    check("statement 1 lists exactly the terraform's resources, in its order", stmts[0].get("Resource") == expected)
    check("statement 2 is this cluster's tagged application profiles",
          stmts[1].get("Resource") == "arn:aws:bedrock:<region>:<account>:application-inference-profile/*"
          and "application-inference-profile/*" in tf_stmts[1])
    for i, (st, tf) in enumerate(zip(stmts, tf_stmts), 1):
        check(f"statement {i}: Allow, and exactly the terraform's actions",
              st.get("Effect") == "Allow" and sorted(st.get("Action") or []) ==
              sorted(re.findall(r'"(bedrock:[A-Za-z]+)"', tf)))
        tf_keys = re.findall(r'"(aws:[A-Za-z]+/[a-z-]+)"\s*=', tf)
        check(f"statement {i}: exactly the terraform's condition keys {tf_keys}",
              sorted((st.get("Condition") or {}).get("StringEquals", {})) == sorted(tf_keys) and bool(tf_keys))
    cond2 = (stmts[1].get("Condition") or {}).get("StringEquals", {})
    check("the tags it shows are the ones the terraform sets (project watch-it-burn, consumer agent)",
          cond2.get("aws:ResourceTag/project") == "watch-it-burn" and 'project   = "watch-it-burn"' in TF
          and cond2.get("aws:ResourceTag/consumer") == "agent"
          and re.search(r'"aws:ResourceTag/consumer"\s*=\s*"agent"', tf_stmts[1]) is not None)

print("== IMDS: node hop limit, and an explicit deny the lab can show ==")
check("node IMDSv2 required", re.search(r'http_tokens\s*=\s*"required"', TF) is not None)
# The hop limit is a per-cluster variable now (#113): the node group reads var.imds_hop_limit, whose
# DEFAULT is 1 (the control). fleet.sh passes 2 for the community/burn cluster alone, so that one cluster
# leaks node creds for the IMDS theft challenge while admin and every attendee seat keep the control.
check("the node group's hop limit is var.imds_hop_limit (per-cluster)",
      re.search(r"http_put_response_hop_limit\s*=\s*var\.imds_hop_limit\b", TF) is not None)
imds_var = re.search(r'variable "imds_hop_limit"\s*\{[^}]*default\s*=\s*(\d+)', TF)
check("var.imds_hop_limit defaults to 1, so admin and attendee clusters keep node IMDS out of pod reach",
      bool(imds_var) and int(imds_var.group(1)) == 1)
check("the vpc-cni addon enforces network policy (ClusterNetworkPolicy needs it)", 'enableNetworkPolicy = "true"' in TF)
kver = re.search(r'variable "kubernetes_version" \{[^}]*default\s*=\s*"1\.(\d+)"', TF)
check("the clusters run Kubernetes 1.29 or later (ClusterNetworkPolicy needs it)", bool(kver) and int(kver.group(1)) >= 29)
cnps = [d for f in sorted(CNP_DIR.glob("*.yaml")) for d in yaml.safe_load_all(f.read_text(encoding="utf-8")) if d]
deny = next((d for d in cnps if d.get("kind") == "ClusterNetworkPolicy" and d["metadata"]["name"] == "agent-deny-imds"), {})
spec = deny.get("spec") or {}
check("ClusterNetworkPolicy agent-deny-imds exists (networking.k8s.aws/v1alpha1)",
      deny.get("apiVersion") == "networking.k8s.aws/v1alpha1")
check("it is Admin tier, so no NetworkPolicy can override it", spec.get("tier") == "Admin")
check("its subject is the agent namespace",
      spec.get("subject", {}).get("namespaces", {}).get("matchLabels") == {"kubernetes.io/metadata.name": "agent"})
deny_nets = [n for r in spec.get("egress") or [] if r.get("action") == "Deny" for t in r.get("to") or []
             for n in t.get("networks") or []]
check("it denies egress to exactly 169.254.169.254/32", deny_nets == ["169.254.169.254/32"])
check("it has no rule but that one", len(spec.get("egress") or []) == 1 and not spec.get("ingress"))
check("it never touches the Pod Identity agent (169.254.170.23)", "169.254.170.23" not in json.dumps(spec))

app = yaml.safe_load((BOOT / "apps/cluster-network-policies.yaml").read_text(encoding="utf-8"))
check("its own Application syncs policies/cluster-network-policies at the chart's revision",
      app["spec"]["source"]["path"] == "policies/cluster-network-policies"
      and app["spec"]["source"]["targetRevision"] == "{{ .Values.revision }}")
check("it syncs in network-policies' wave, before the ai-layer",
      app["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "-4")
for profile in ("attendee", "full", "admin"):
    check(f"the {profile} profile lists it", "cluster-network-policies" in profile_apps(profile))
check("the attendee profile still leaves network-policies off, so the deny is the only IMDS rule before C1",
      "network-policies" not in profile_apps("attendee"))
check("the burn profile, which defends nothing, does not list it", "cluster-network-policies" not in profile_apps("burn"))


def allows_imds(doc: dict) -> bool:
    """IMDS answers on TCP 80. A rule allows it if its ports include 80 (or are absent) and its peers include
    169.254.169.254 (or are absent: weather-feed's rule opens every address, on 443 only)."""
    for rule in (doc.get("spec") or {}).get("egress") or []:
        ports = rule.get("ports") or []
        if ports and not any(pt.get("protocol", "TCP") == "TCP" and
                             (pt.get("port") is None or pt.get("port") == 80 or
                              (isinstance(pt.get("port"), int) and pt["port"] <= 80 <= pt.get("endPort", pt["port"])))
                             for pt in ports):
            continue
        if not rule.get("to"):
            return True
        for t in rule["to"]:
            cidr = (t.get("ipBlock") or {}).get("cidr")
            if cidr and IMDS in ipaddress.ip_network(cidr) and \
                    not any(IMDS in ipaddress.ip_network(e) for e in t["ipBlock"].get("except", [])):
                return True
    return False


agent_netpols = [d for f in (REPO / "policies/network-policies/per-namespace").glob("agent-*.yaml")
                 for d in yaml.safe_load_all(f.read_text(encoding="utf-8")) if d]
agent_netpols += [d for d in yaml.safe_load_all(fixes.get("c1-network-policy.yaml", "")) if d]
check("no agent NetworkPolicy, platform or the C1 copy, allows IMDS",
      bool(agent_netpols) and not [d["metadata"]["name"] for d in agent_netpols if allows_imds(d)])

print("== the C8 probe: read-only, as agent-sa ==")
check("the probe is staged in ~/challenges", "cloud-credential-probe.yaml" in fixes)
job = yaml.safe_load(fixes.get("cloud-credential-probe.yaml") or "{}") or {}
jpod = pod_spec(job)
check("it is a Job (owned pods get reliable VPC CNI policy enforcement)", job.get("kind") == "Job")
check("in the agent namespace, where the deny applies", job.get("metadata", {}).get("namespace") == "agent")
check("it runs as agent-sa, so it gets exactly the agent's AWS credential", jpod.get("serviceAccountName") == "agent-sa")
check("it mounts no Kubernetes token", jpod.get("automountServiceAccountToken") is False)
term = pod_spec(find("Deployment", "web-terminal")).get("containers", [{}])[0].get("image", "")
probe_c = (jpod.get("containers") or [{}])[0]
check("its image is the web terminal's, pinned by the same digest (signed, already on the node)",
      probe_c.get("image") == term and "@sha256:" in term)
check("it carries CPU and memory limits (require-resource-limits is armed on admin)",
      {"cpu", "memory"} <= set((probe_c.get("resources") or {}).get("limits") or {}))
check("it cannot outlive the lab step", job.get("spec", {}).get("activeDeadlineSeconds", 0) <= 180
      and job.get("spec", {}).get("backoffLimit") == 0)
script = (probe_c.get("args") or [""])[0]
for needle, why in (("sts get-caller-identity", "who am I"),
                    ("--model-id us.amazon.nova-pro-v1:0", "Nova Pro, the allowed call"),
                    ("--model-id us.anthropic.claude-sonnet-5", "a model off the list"),
                    ("s3api list-buckets", "S3"), ("ec2 describe-instances", "EC2"), ("iam list-roles", "IAM"),
                    ("http://169.254.169.254/", "IMDS")):
    check(f"the probe tries {why}", needle in script)
check("the off-list model really is off the list", "us.anthropic.claude-sonnet-5" not in profiles)
check("Nova Pro's reply is capped at five tokens", '"maxTokens":5' in script)
# Every AWS call is `try "<label>" a <service> <operation>`; each operation must only read (converse spends five
# tokens and writes nothing), and nothing may call aws outside try.
calls = re.findall(r'^\s*try "[^"]*" a ([a-z0-9-]+) ([a-z0-9-]+)', script, re.M)
check("the probe calls aws only through try",
      script.count(" aws ") == 1 and len(calls) == len(re.findall(r'\btry "', script)))
READ_ONLY = {("sts", "get-caller-identity"), ("bedrock-runtime", "converse"), ("s3api", "list-buckets"),
             ("ec2", "describe-instances"), ("iam", "list-roles")}
check("every AWS call the probe makes only reads", bool(calls) and set(calls) <= READ_ONLY)

print("== the lab beat ==")
m = re.search(r"Challenge 8:.*?(?=Challenge 9:)", LAB, re.S)
c8 = m.group(0) if m else ""
LAB_CMDS = ("kubectl -n agent get sa agent-sa -o yaml",
            "kubectl -n agent exec deploy/workshop-agent -c kagent -- sh -c 'env | grep ^AWS_; "
            "ls -a ~/.aws /var/run/secrets/kubernetes.io/serviceaccount'",
            "kubectl apply -f ~/challenges/cloud-credential-probe.yaml",
            "kubectl -n agent logs job/cloud-credential-probe",
            "kubectl get clusternetworkpolicy agent-deny-imds -o yaml",
            "cat ~/challenges/agent-bedrock-policy.json")
for cmd in LAB_CMDS:
    check(f"C8 runs: {cmd[:70]}", cmd in c8)
check("the lab does not claim the agent holds no cloud credential", "no cloud credential" not in LAB)
check("the lab no longer says agent-sa's own pod has the token on disk",
      "<code class=\"inl\">agent-sa</code>, with a bearer token projected" not in c8)
check("it names the tool server's account as the one with the token", "as <code class=\"inl\">workshop-mcp</code>" in c8)
for verdict in ("ALLOWED", "DENIED by IAM", "UNREACHABLE", "BLOCKED"):
    check(f"the lab explains the probe's {verdict} rows, which the probe prints", verdict in c8 and verdict in script)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ALL AGENT CLOUD-CREDENTIAL CHECKS PASSED")
