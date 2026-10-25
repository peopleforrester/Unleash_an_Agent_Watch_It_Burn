# ABOUTME: Live half of #561: agentgateway's bedrock backend runs on this cluster's tagged application profile ARN,
# ABOUTME: and one model call through :3002 succeeds with it, which is what shows Bedrock takes the ARN in the URL path.
# SUITE: e2e
"""Needs kubectl and CONTEXT naming a bootstrapped attendee cluster (fleet.sh has run pin_bedrock_profiles on it).
Every missing prerequisite is a failure with the reason, never a skip.

Why (#561). A system-defined inference profile cannot carry tags, so a model call through one bills untagged. The
gateway-* ModelConfigs go through agentgateway, whose bedrock backend reads its model from the BEDROCK_NOVA_MODEL
env of the agentgateway container. Git commits the system id there; fleet.sh sets the live value to the cluster's
application profile ARN. test_pin_bedrock_profiles.sh proves fleet.sh sets it. This proves it is set on the
cluster, that the running gateway pod carries it, and that a call through the gateway with it succeeds.

The last one is the part only a cluster can show. agentgateway v1.5.0 puts the model into the request path and
escapes the ARN's '/' as %2F (crates/llm/src/bedrock.rs, get_path_for_route); a 200 from Bedrock through that
path is the confirmation that it takes the escaped ARN. The call is made from the workshop-agent pod, the one peer
chat-path-ingress admits to :3002 (#552), and asks for at most 5 tokens.

Usage: CONTEXT=<kube-context> [NAMESPACE=agent] python3 verify/test_gateway_bedrock_tagged_live.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

CONTEXT = os.environ.get("CONTEXT", "")
NS = os.environ.get("NAMESPACE", "agent")
VAR = "BEDROCK_NOVA_MODEL"
ARN = re.compile(r"arn:aws:bedrock:[a-z0-9-]+:\d{12}:application-inference-profile/[a-z0-9]+")
KUBECTL = shutil.which("kubectl")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  -> {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    if failures:
        print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
        sys.exit(1)
    print("\nPASS: agentgateway's bedrock backend calls this cluster's tagged application profile")
    sys.exit(0)


def kubectl(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    return subprocess.run([KUBECTL, "--context", CONTEXT, *args], capture_output=True, text=True, timeout=timeout)


def kjson(*args: str) -> dict | None:
    r = kubectl(*args, "-o", "json")
    return json.loads(r.stdout) if r.returncode == 0 else None


def gateway_env(spec: dict) -> str:
    for c in spec.get("containers", []):
        if c["name"] == "agentgateway":
            return next((e.get("value", "") for e in c.get("env", []) if e["name"] == VAR), "")
    return ""


print("== prerequisites ==")
check("kubectl is on PATH", KUBECTL is not None)
check("CONTEXT names the cluster to run against", bool(CONTEXT))
if failures:
    finish()
r = kubectl("--request-timeout=15s", "get", "--raw", "/readyz")
check(f"cluster for context {CONTEXT!r} is reachable", r.returncode == 0, r.stderr.strip())
if failures:
    finish()

print("== the gateway's bedrock model is this cluster's tagged profile ==")
deploy = kjson("-n", NS, "get", "deployment", "agentgateway")
check(f"the agentgateway Deployment is in {NS}", deploy is not None)
live = gateway_env(deploy["spec"]["template"]["spec"]) if deploy else ""
check(f"its {VAR} is an application inference profile ARN, not the system id (found {live!r})",
      ARN.fullmatch(live) is not None)
pods = (kjson("-n", NS, "get", "pods", "-l", "app.kubernetes.io/name=agentgateway") or {"items": []})["items"]
ready = [p for p in pods if any(c.get("type") == "Ready" and c.get("status") == "True"
                                for c in (p.get("status") or {}).get("conditions") or [])]
check("agentgateway has a Ready pod", bool(ready), f"{len(pods)} pod(s), none Ready")
stale = [p["metadata"]["name"] for p in ready if gateway_env(p["spec"]) != live]
check(f"every Ready gateway pod runs with that {VAR} (the pin has rolled out)", bool(ready) and not stale,
      f"stale: {stale}")
if failures:
    finish()

print("== a model call through agentgateway :3002 succeeds on it ==")
# The OpenAI wire format kagent speaks to the gateway (gateway-bedrock-nova); the gateway replaces the model
# with BEDROCK_NOVA_MODEL and re-speaks Bedrock Converse.
CALL = (
    "import json,sys,urllib.request,urllib.error\n"
    "body=json.dumps({'model':'bedrock-nova','max_tokens':5,"
    "'messages':[{'role':'user','content':'Reply with the single word OK.'}]}).encode()\n"
    "req=urllib.request.Request(sys.argv[1],data=body,headers={'content-type':'application/json'})\n"
    "try:\n"
    "    r=urllib.request.urlopen(req,timeout=60); print(r.status); print(r.read().decode()[:400])\n"
    "except urllib.error.HTTPError as e:\n"
    "    print(e.code); print(e.read().decode()[:400])\n"
)
url = f"http://agentgateway.{NS}.svc.cluster.local:3002/bedrock/v1/chat/completions"
r = kubectl("-n", NS, "exec", "deploy/workshop-agent", "--", "python3", "-c", CALL, url, timeout=120)
lines = r.stdout.splitlines()
status, reply = (lines[0] if lines else ""), "\n".join(lines[1:])
check("the call ran from the workshop-agent pod", r.returncode == 0, " ".join(r.stderr.split()))
check(f"Bedrock answered 200 through the ARN path (got {status or 'nothing'})", status == "200", reply)
try:
    choices = json.loads(reply).get("choices") if status == "200" else None
except json.JSONDecodeError:
    choices = None
check("the reply is a chat completion with a choice", bool(choices), reply)
finish()
