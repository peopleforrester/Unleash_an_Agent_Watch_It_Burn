# ABOUTME: Live half of question 657 (#394): on a local-inference cluster the vLLM is Ready, and one chat call through
# ABOUTME: agentgateway's :3002/local route reaches it and comes back a completion. Reports the pod's live footprint.
"""Needs kubectl and CONTEXT naming a cluster built with `infra/deploy-full-idp.sh local-inference`. Every missing
prerequisite is a failure with the reason, never a skip.

Not a test_*.py on purpose: run-e2e.sh runs every `# SUITE: e2e` test against a fresh attendee cluster, which has no
vLLM, so this would fail there by design. It is run by hand against the one local-inference cluster it is for.

Why. verify/test_local_inference.py proves offline that the server, the route and the ModelConfig agree on a host, a
port and a model name. Only a cluster shows that the 4.95 GB image pulls, that the model loads on CPU beside the rest
of the platform on one t3.2xlarge, and that agentgateway's /local backend speaks to it. The call is made from the
workshop-agent pod, the one peer chat-path-ingress admits to :3002 (#552), and asks for at most 5 tokens. The pod's
start and Ready times are printed so the cold build's cost can go into platform-baseline.yaml's vllm entry.

Usage: CONTEXT=<kube-context> [NAMESPACE=agent] python3 verify/local-inference-live.py
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys

CONTEXT = os.environ.get("CONTEXT", "")
NS = os.environ.get("NAMESPACE", "agent")
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
    print("\nPASS: the local-inference vLLM answers through agentgateway's /local route")
    sys.exit(0)


def kubectl(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    return subprocess.run([KUBECTL, "--context", CONTEXT, *args], capture_output=True, text=True, timeout=timeout)


def kjson(*args: str) -> dict | None:
    r = kubectl(*args, "-o", "json")
    return json.loads(r.stdout) if r.returncode == 0 else None


def when(stamp: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


print("== prerequisites ==")
check("kubectl is on PATH", KUBECTL is not None)
check("CONTEXT names the cluster to run against", bool(CONTEXT))
if failures:
    finish()
r = kubectl("--request-timeout=15s", "get", "--raw", "/readyz")
check(f"cluster for context {CONTEXT!r} is reachable", r.returncode == 0, r.stderr.strip())
if failures:
    finish()

print("== the root is the local-inference profile and the vLLM is Ready ==")
root = kjson("-n", "argocd", "get", "application", "lab-bootstrap") or {}
check("lab-bootstrap is labelled lab-platform/profile=local-inference",
      (root.get("metadata") or {}).get("labels", {}).get("lab-platform/profile") == "local-inference")
app = kjson("-n", "argocd", "get", "application", "vllm-qwen3") or {}
status = app.get("status") or {}
check("the vllm-qwen3 Application is Synced and Healthy",
      status.get("sync", {}).get("status") == "Synced" and status.get("health", {}).get("status") == "Healthy",
      f"sync {status.get('sync', {}).get('status')}, health {status.get('health', {}).get('status')}")
pods = (kjson("-n", NS, "get", "pods", "-l", "app.kubernetes.io/name=vllm-qwen3") or {"items": []})["items"]
ready = [p for p in pods if any(c.get("type") == "Ready" and c.get("status") == "True"
                                for c in (p.get("status") or {}).get("conditions") or [])]
check("vllm-qwen3 has one Ready pod", len(ready) == 1, f"{len(pods)} pod(s), {len(ready)} Ready")
for p in ready:
    conds = {c["type"]: c.get("lastTransitionTime") for c in p["status"].get("conditions") or []}
    created = p["metadata"]["creationTimestamp"]
    if conds.get("Ready"):
        secs = int((when(conds["Ready"]) - when(created)).total_seconds())
        print(f"        {p['metadata']['name']} on {p['spec'].get('nodeName')}: created {created}, Ready {conds['Ready']}"
              f" ({secs} s from creation to Ready)")
    restarts = sum(c.get("restartCount", 0) for c in p["status"].get("containerStatuses") or [])
    check(f"{p['metadata']['name']} has not restarted (an OOMKill shows here first)", restarts == 0, f"{restarts} restarts")
top = kubectl("-n", NS, "top", "pod", "-l", "app.kubernetes.io/name=vllm-qwen3", "--no-headers")
print(f"        live footprint (kubectl top): {top.stdout.strip() or top.stderr.strip()}")
if failures:
    finish()

print("== a chat call through agentgateway :3002/local reaches it ==")
# The OpenAI wire format kagent speaks to the gateway (gateway-local-qwen3); the gateway names qwen3-1.7b to vLLM.
CALL = (
    "import json,sys,urllib.request,urllib.error\n"
    "body=json.dumps({'model':'local-qwen3','max_tokens':5,"
    "'messages':[{'role':'user','content':'Reply with the single word OK.'}]}).encode()\n"
    "req=urllib.request.Request(sys.argv[1],data=body,headers={'content-type':'application/json'})\n"
    "try:\n"
    "    r=urllib.request.urlopen(req,timeout=120); print(r.status); print(r.read().decode()[:400])\n"
    "except urllib.error.HTTPError as e:\n"
    "    print(e.code); print(e.read().decode()[:400])\n"
)
url = f"http://agentgateway.{NS}.svc.cluster.local:3002/local/v1/chat/completions"
r = kubectl("-n", NS, "exec", "deploy/workshop-agent", "--", "python3", "-c", CALL, url, timeout=180)
lines = r.stdout.splitlines()
code, reply = (lines[0] if lines else ""), "\n".join(lines[1:])
check("the call ran from the workshop-agent pod", r.returncode == 0, " ".join(r.stderr.split()))
check(f"the gateway answered 200 from vLLM (got {code or 'nothing'})", code == "200", reply)
try:
    body = json.loads(reply) if code == "200" else {}
except json.JSONDecodeError:
    body = {}
check("the reply is a chat completion with a choice", bool(body.get("choices")), reply)
check(f"vLLM answered as qwen3-1.7b (model {body.get('model')!r})", body.get("model") == "qwen3-1.7b", reply)
finish()
