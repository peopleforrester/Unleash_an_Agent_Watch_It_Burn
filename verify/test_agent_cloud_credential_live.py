# ABOUTME: E2E half of #203 on a real attendee cluster: agent-sa's ONE cloud credential reaches Nova Pro and is
# ABOUTME: denied everything else, IMDS is blocked, and the attached policy passes IAM Access Analyzer.
# SUITE: e2e
"""Needs kubectl, the aws CLI, CONTEXT naming an attendee cluster that runs the ai-layer, and AWS_PROFILE for the
account that owns it. Every missing prerequisite is a failure with the reason, never a skip.

CONTEXT is normally the EKS context ARN (arn:aws:eks:<region>:<account>:cluster/<name>), from which the cluster
name and region are read. A context with any other name needs CLUSTER_NAME and AWS_REGION as well.

Live checks, in the order the lab shows them:
1. agent-sa on the cluster has no identity annotation and does not automount its Kubernetes token;
2. the running BurritoBot pod carries the Pod Identity pointer (169.254.170.23), no access key, and no default
   Kubernetes token volume; workshop-mcp, the one pod that opts in, does have it;
3. the Admin-tier ClusterNetworkPolicy agent-deny-imds is on the cluster;
4. the C8 probe Job, applied exactly as the lab applies it, reports Nova Pro ALLOWED, an off-list model DENIED
   by IAM as the ...-bedrock- role, S3/EC2/IAM not ALLOWED, and IMDS BLOCKED;
5. AWS side: agent:agent-sa has exactly one Pod Identity association, its role has exactly one attached policy,
   that policy has no "*" resource, and Access Analyzer validate-policy returns no ERROR or SECURITY_WARNING.

Usage: CONTEXT=<kube-context> AWS_PROFILE=<profile> python3 verify/test_agent_cloud_credential_live.py
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
CONTEXT = os.environ.get("CONTEXT", "")
PROFILE = os.environ.get("AWS_PROFILE", "")
NS = "agent"
m = re.match(r"^arn:aws:eks:([a-z0-9-]+):\d+:cluster/(.+)$", CONTEXT)
REGION = os.environ.get("AWS_REGION") or (m.group(1) if m else "")
CLUSTER = os.environ.get("CLUSTER_NAME") or (m.group(2) if m else "")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All live agent cloud-credential checks passed.")
    sys.exit(0)


def kubectl(*args: str, stdin: str | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", CONTEXT, *args], input=stdin, capture_output=True, text=True,
                          timeout=timeout, env={**os.environ, "AWS_PROFILE": PROFILE})


def aws(*args: str) -> dict:
    r = subprocess.run(["aws", "--region", REGION, "--output", "json", *args], capture_output=True, text=True,
                       timeout=60, env={**os.environ, "AWS_PROFILE": PROFILE})
    if r.returncode != 0:
        print(f"      aws {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
        return {}
    return json.loads(r.stdout or "{}")


print("== prerequisites ==")
for tool in ("kubectl", "aws"):
    check(f"{tool} is on PATH", shutil.which(tool) is not None)
check("CONTEXT is set (the kube-context of the attendee cluster)", bool(CONTEXT))
check("AWS_PROFILE is set (the account that owns the cluster)", bool(PROFILE))
check("cluster name and region are known (CONTEXT is an EKS ARN, or CLUSTER_NAME and AWS_REGION are set)",
      bool(CLUSTER and REGION))
if failures:
    finish()
check(f"cluster for context {CONTEXT} is reachable", kubectl("get", "--raw", "/readyz").returncode == 0)
if failures:
    finish()


def get(kind: str, *names: str) -> dict:
    r = kubectl("-n", NS, "get", kind, *names, "-o", "json")
    return json.loads(r.stdout) if r.returncode == 0 else {}


def pod_of(selector: str) -> dict:
    items = get("pods", "-l", selector).get("items", [])
    running = [p for p in items if p.get("status", {}).get("phase") == "Running"]
    return running[0] if running else {}


print("== 1. agent-sa on the cluster ==")
sa = get("serviceaccount", "agent-sa")
check("agent-sa exists", bool(sa))
check("no eks.amazonaws.com/ annotation",
      not any(k.startswith("eks.amazonaws.com/") for k in (sa.get("metadata", {}).get("annotations") or {})))
check("automountServiceAccountToken is false", sa.get("automountServiceAccountToken") is False)

print("== 2. what the running pods hold ==")
bot = pod_of("app.kubernetes.io/name=workshop-agent")
check("a running BurritoBot (workshop-agent) pod", bool(bot))
kagent = next((c for c in bot.get("spec", {}).get("containers", []) if c["name"] == "kagent"), {})
env = {e["name"]: e.get("value", "") for e in kagent.get("env", [])}
check("kagent container: AWS_CONTAINER_CREDENTIALS_FULL_URI points at the Pod Identity agent",
      env.get("AWS_CONTAINER_CREDENTIALS_FULL_URI", "").startswith("http://169.254.170.23/"))
check("kagent container: no AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY",
      "AWS_ACCESS_KEY_ID" not in env and "AWS_SECRET_ACCESS_KEY" not in env)
bot_mounts = [v["mountPath"] for v in kagent.get("volumeMounts", [])]
check("kagent container: no default Kubernetes token mounted",
      "/var/run/secrets/kubernetes.io/serviceaccount" not in bot_mounts)
mcp = pod_of("app=workshop-mcp")
mcp_mounts = [v["mountPath"] for c in mcp.get("spec", {}).get("containers", []) for v in c.get("volumeMounts", [])]
check("workshop-mcp (the one pod that opts in) does mount the token",
      "/var/run/secrets/kubernetes.io/serviceaccount" in mcp_mounts)

print("== 3. the readable IMDS deny ==")
cnp = kubectl("get", "clusternetworkpolicy", "agent-deny-imds", "-o", "json")
check("ClusterNetworkPolicy agent-deny-imds is on the cluster (VPC CNI >= 1.21 with network policy)",
      cnp.returncode == 0)

print("== 4. the C8 probe, as the lab runs it ==")
docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")) if d]
fixes = next(d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "challenge-fixes")["data"]
kubectl("-n", NS, "delete", "job", "cloud-credential-probe", "--ignore-not-found", "--wait=true")
applied = kubectl("apply", "-f", "-", stdin=fixes["cloud-credential-probe.yaml"])
check("the probe Job is admitted", applied.returncode == 0)
if applied.returncode != 0:
    print(f"      {applied.stderr.strip()[:400]}")
done = kubectl("-n", NS, "wait", "--for=condition=complete", "job/cloud-credential-probe", "--timeout=180s",
               timeout=200)
check("the probe Job completes", done.returncode == 0)
log = kubectl("-n", NS, "logs", "job/cloud-credential-probe").stdout
kubectl("-n", NS, "delete", "job", "cloud-credential-probe", "--ignore-not-found")
print("\n".join(f"      | {line}" for line in log.splitlines()))


def row(label: str) -> str:
    hit = re.search(rf"^\s+{re.escape(label)}\s+(.*)$", log, re.M)
    return hit.group(1) if hit else ""


check("the probe pod holds the Pod Identity pointer", "AWS_CONTAINER_CREDENTIALS_FULL_URI=http://169.254.170.23/" in log)
check("and no static key", "no AWS_ACCESS_KEY_ID, no AWS_SECRET_ACCESS_KEY" in log)
who = row("who am I (sts get-caller-identity)")
check("who am I: the -bedrock- role, or UNREACHABLE behind a Challenge 1 policy",
      (who.startswith("ALLOWED") and f"assumed-role/{CLUSTER}-bedrock-" in who) or who.startswith("UNREACHABLE"))
check("Nova Pro: ALLOWED", row("Bedrock: Nova Pro (on the list)").startswith("ALLOWED"))
check("a model off the list: DENIED by IAM", row("Bedrock: a model NOT on the list").startswith("DENIED by IAM"))
check("the denial names the agent's -bedrock- role", f"assumed-role/{CLUSTER}-bedrock-" in log)
for label in ("S3: list buckets", "EC2: describe instances", "IAM: look up any role or policy"):
    got = row(label)
    check(f"{label}: DENIED or UNREACHABLE, never ALLOWED", got.startswith(("DENIED by IAM", "UNREACHABLE")))
check("IMDS GET: BLOCKED", row("curl -m 2 http://169.254.169.254/").startswith("BLOCKED"))
check("IMDSv2 token request: BLOCKED", row("IMDSv2 token request").startswith("BLOCKED"))

print("== 5. the AWS side ==")
assoc = aws("eks", "list-pod-identity-associations", "--cluster-name", CLUSTER, "--namespace", NS,
            "--service-account", "agent-sa").get("associations", [])
check("agent:agent-sa has exactly one Pod Identity association", len(assoc) == 1)
role_arn = ""
if len(assoc) == 1:
    role_arn = aws("eks", "describe-pod-identity-association", "--cluster-name", CLUSTER, "--association-id",
                   assoc[0]["associationId"]).get("association", {}).get("roleArn", "")
role = role_arn.rsplit("/", 1)[-1]
check(f"its role is the -bedrock- role ({role or 'none'})", role.startswith(f"{CLUSTER}-bedrock-"))
attached = aws("iam", "list-attached-role-policies", "--role-name", role).get("AttachedPolicies", []) if role else []
inline = aws("iam", "list-role-policies", "--role-name", role).get("PolicyNames", ["?"]) if role else ["?"]
check("the role has exactly one attached policy, <cluster>-bedrock-invoke, and no inline policy",
      [p["PolicyName"] for p in attached] == [f"{CLUSTER}-bedrock-invoke"] and inline == [])
document: dict = {}
if len(attached) == 1:
    pol = aws("iam", "get-policy", "--policy-arn", attached[0]["PolicyArn"]).get("Policy", {})
    document = aws("iam", "get-policy-version", "--policy-arn", attached[0]["PolicyArn"], "--version-id",
                   pol.get("DefaultVersionId", "v1")).get("PolicyVersion", {}).get("Document", {})
statements = document.get("Statement", [])
statements = statements if isinstance(statements, list) else [statements]
resources = [r for s in statements for r in (s.get("Resource") if isinstance(s.get("Resource"), list) else [s.get("Resource")])]
check("the policy document was read", bool(statements))
check('no statement has Resource "*"', bool(resources) and "*" not in resources)
check("Nova Pro's profile and foundation model are both in it",
      any(r.endswith(":inference-profile/us.amazon.nova-pro-v1:0") for r in resources)
      and any(r.endswith("::foundation-model/amazon.nova-pro-v1:0") for r in resources))
findings = aws("accessanalyzer", "validate-policy", "--policy-type", "IDENTITY_POLICY", "--policy-document",
               json.dumps(document)) if document else {"findings": [{"findingType": "ERROR", "issueCode": "unread"}]}
bad = [f"{f['findingType']}:{f.get('issueCode', '')}" for f in findings.get("findings", [])
       if f.get("findingType") in ("ERROR", "SECURITY_WARNING")]
check(f"Access Analyzer validate-policy: no ERROR or SECURITY_WARNING ({', '.join(bad) or 'none'})",
      "findings" in findings and not bad)

finish()
