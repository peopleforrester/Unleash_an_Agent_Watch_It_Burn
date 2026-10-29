# ABOUTME: Live half of #203 on a real attendee cluster: agent-sa's ONE cloud credential reaches Nova Pro and is
# ABOUTME: denied everything else, BurritoBot's pod holds no key and no Kubernetes token, and IMDS does not answer.
# SUITE: e2e
"""Needs kubectl and CONTEXT naming an attendee cluster that runs the ai-layer, with the cluster's credentials in
the environment run-e2e.sh is given (KUBECONFIG and the AWS profile its exec plugin uses). Every missing
prerequisite is a failure with the reason, never a skip.

The checks, in the order Challenge 8's beat shows them:
1. agent-sa on the cluster has no identity annotation and does not automount its Kubernetes token;
2. the running BurritoBot pod carries the Pod Identity pointer (169.254.170.23), no access key and no default
   Kubernetes token, and the lab's own exec command, run as written, shows exactly that; workshop-mcp, whose tools
   call the API, does mount its token;
3. the Admin-tier ClusterNetworkPolicy agent-deny-imds is on the cluster, as policies/cluster-network-policies/
   writes it;
4. the probe Job, applied exactly as the lab applies it, reports Nova Pro ALLOWED, an off-list model DENIED by IAM
   as the same ...-bedrock- role who-am-I names, S3, EC2 and IAM never ALLOWED, and IMDS BLOCKED. The plain GET to
   IMDS is the one that tests the deny: with IMDSv2 required the node would answer it 401, and curl would exit 0.

The policy itself is not read back from AWS here. test_iam_policy_aws.py sends the document the terraform writes to
Access Analyzer (no ERROR or SECURITY_WARNING) and runs infra/org/effect-tests.yaml through the policy simulator
(Nova Pro allowed for this cluster's agent namespace; off-menu models, IAM, EKS and S3 denied). Step 4 is what
shows the same boundary holding for the credential the cluster actually hands out.

Usage: CONTEXT=<kube-context> python3 verify/test_agent_cloud_credential_live.py
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
CONTEXT = os.environ.get("CONTEXT", "")
NS = "agent"
TOKEN_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if (detail and not cond) else ""))
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
                          timeout=timeout)


print("== prerequisites ==")
check("kubectl is on PATH", shutil.which("kubectl") is not None)
check("CONTEXT is set (the kube-context of the attendee cluster)", bool(CONTEXT))
if failures:
    finish()
check(f"cluster for context {CONTEXT} is reachable", kubectl("get", "--raw", "/readyz").returncode == 0)
if failures:
    finish()

RES = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8"))
       if isinstance(d, dict)]
FIXES = next(d for d in RES if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "challenge-fixes")["data"]
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")


def get(*args: str) -> dict:
    r = kubectl("-n", NS, "get", *args, "-o", "json")
    return json.loads(r.stdout) if r.returncode == 0 else {}


def running_pod(deploy: str) -> dict:
    sel = get("deployment", deploy).get("spec", {}).get("selector", {}).get("matchLabels", {})
    if not sel:
        return {}
    items = get("pods", "-l", ",".join(f"{k}={v}" for k, v in sel.items())).get("items", [])
    return next((p for p in items if p.get("status", {}).get("phase") == "Running"), {})


print("== 1. agent-sa on the cluster ==")
sa = get("serviceaccount", "agent-sa")
check("agent-sa exists", bool(sa))
check("no eks.amazonaws.com/ annotation",
      not any(k.startswith("eks.amazonaws.com/") for k in (sa.get("metadata", {}).get("annotations") or {})))
check("automountServiceAccountToken is false", sa.get("automountServiceAccountToken") is False)

print("== 2. what the running pods hold ==")
bot = running_pod("workshop-agent")
check("a running BurritoBot (workshop-agent) pod", bool(bot))
check("it runs as agent-sa", bot.get("spec", {}).get("serviceAccountName") == "agent-sa")
kagent = next((c for c in bot.get("spec", {}).get("containers", []) if c["name"] == "kagent"), {})
env = {e["name"]: e.get("value", "") for e in kagent.get("env", [])}
check("kagent container: AWS_CONTAINER_CREDENTIALS_FULL_URI points at the Pod Identity agent",
      env.get("AWS_CONTAINER_CREDENTIALS_FULL_URI", "").startswith("http://169.254.170.23/"), repr(sorted(env)))
check("kagent container: no AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY",
      "AWS_ACCESS_KEY_ID" not in env and "AWS_SECRET_ACCESS_KEY" not in env)
mounts = [v["mountPath"] for c in bot.get("spec", {}).get("containers", []) for v in c.get("volumeMounts", [])]
check("no container in BurritoBot's pod mounts the default Kubernetes token", TOKEN_DIR not in mounts, repr(mounts))

m = re.search(r"Challenge 8:.*?(?=Challenge 9:)", LAB, re.S)
exec_cmd = re.search(r'>(kubectl -n agent exec deploy/workshop-agent -c kagent -- [^<]*)<button', m.group(0) if m else "")
check("the lab's exec command is found", bool(exec_cmd))
if exec_cmd:
    argv = shlex.split(exec_cmd.group(1).replace("&gt;", ">").replace("&amp;", "&"))
    r = kubectl(*argv[1:])
    out = r.stdout + r.stderr
    print("\n".join(f"      | {line}" for line in out.splitlines()))
    check("the lab's exec shows the Pod Identity pointer", "AWS_CONTAINER_CREDENTIALS_FULL_URI=http://169.254.170.23/" in out)
    check("and its token file", "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE=" in out)
    check("and no static key", "AWS_ACCESS_KEY_ID" not in out and "AWS_SECRET_ACCESS_KEY" not in out)
    check("and neither ~/.aws nor the Kubernetes token directory exists",
          out.count("No such file or directory") == 2, out[-300:])
mcp = running_pod("workshop-mcp")
mcp_mounts = [v["mountPath"] for c in mcp.get("spec", {}).get("containers", []) for v in c.get("volumeMounts", [])]
check("workshop-mcp runs as its own account and does mount its token",
      mcp.get("spec", {}).get("serviceAccountName") == "workshop-mcp" and TOKEN_DIR in mcp_mounts)

print("== 3. the readable IMDS deny ==")
want = yaml.safe_load((REPO / "policies/cluster-network-policies/agent-deny-imds.yaml").read_text(encoding="utf-8"))
r = kubectl("get", "clusternetworkpolicy", "agent-deny-imds", "-o", "json")
check("ClusterNetworkPolicy agent-deny-imds is on the cluster (VPC CNI 1.21.1 or later, network policy on)",
      r.returncode == 0, r.stderr.strip()[:300])
live = json.loads(r.stdout).get("spec", {}) if r.returncode == 0 else {}
check("its spec is the one in policies/cluster-network-policies/",
      live.get("tier") == want["spec"]["tier"] and live.get("subject") == want["spec"]["subject"]
      and [(e.get("action"), e.get("to")) for e in live.get("egress", [])] ==
      [(e["action"], e["to"]) for e in want["spec"]["egress"]], json.dumps(live)[:300])

print("== 4. the C8 probe, as the lab runs it ==")
kubectl("-n", NS, "delete", "job", "cloud-credential-probe", "--ignore-not-found", "--wait=true")
applied = kubectl("apply", "-f", "-", stdin=FIXES["cloud-credential-probe.yaml"])
check("the probe Job is admitted", applied.returncode == 0, applied.stderr.strip()[:400])
log = ""
if applied.returncode == 0:
    done = kubectl("-n", NS, "wait", "--for=condition=complete", "job/cloud-credential-probe", "--timeout=180s",
                   timeout=200)
    check("the probe Job completes", done.returncode == 0, done.stderr.strip()[:300])
    log = kubectl("-n", NS, "logs", "job/cloud-credential-probe").stdout
    kubectl("-n", NS, "delete", "job", "cloud-credential-probe", "--ignore-not-found")
print("\n".join(f"      | {line}" for line in log.splitlines()))


def row(label: str) -> str:
    hit = re.search(rf"^\s+{re.escape(label)}\s+(.*)$", log, re.M)
    return hit.group(1) if hit else ""


check("the probe pod holds the Pod Identity pointer", "AWS_CONTAINER_CREDENTIALS_FULL_URI=http://169.254.170.23/" in log)
check("and no static key, no ~/.aws and no Kubernetes token",
      all(s in log for s in ("no AWS_ACCESS_KEY_ID, no AWS_SECRET_ACCESS_KEY", "no ~/.aws/credentials file",
                             "no Kubernetes token mounted")))
who = row("who am I (sts get-caller-identity)")
role = re.search(r"assumed-role/([^/\s]+-bedrock-[^/\s]+)/", log)
check("who am I: an assumed ...-bedrock-... role, or UNREACHABLE behind a Challenge 1 policy",
      (who.startswith("ALLOWED") and "assumed-role/" in who and "-bedrock-" in who) or who.startswith("UNREACHABLE"), who)
check("Nova Pro: ALLOWED", row("Bedrock: Nova Pro (on the list)").startswith("ALLOWED"))
check("a model off the list: DENIED by IAM", row("Bedrock: a model NOT on the list").startswith("DENIED by IAM"))
check("the denial names the agent's -bedrock- role", bool(role))
if role and who.startswith("ALLOWED"):
    check("the same role who-am-I named", f"assumed-role/{role.group(1)}/" in who)
for label in ("S3: list buckets", "EC2: describe instances", "IAM: look up any role or policy"):
    got = row(label)
    check(f"{label}: DENIED or UNREACHABLE, never ALLOWED", got.startswith(("DENIED by IAM", "UNREACHABLE")), got)
check("IMDS GET: BLOCKED (the deny; the node alone would answer 401)",
      row("curl -m 2 http://169.254.169.254/").startswith("BLOCKED"))
check("IMDSv2 token request: BLOCKED", row("IMDSv2 token request").startswith("BLOCKED"))

finish()
