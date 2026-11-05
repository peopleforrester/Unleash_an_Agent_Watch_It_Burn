# ABOUTME: Live check of #861's DNS lock and egress proxy on a real cluster, in a scratch namespace it creates and deletes:
# ABOUTME: stage 2 holds 443 while a name still leaves; the lock stops the name; Bedrock, cluster names and weather work.
# SUITE: e2e
"""Needs kubectl and CONTEXT naming an EKS cluster built from this repo (Kyverno 1.19 running, VPC-CNI enforcing
NetworkPolicy). Every missing prerequisite is a failure, never a skip.

What it proves, with the repo's own bytes. It builds the option B pieces in a namespace of its own,
c1-dns-lock-check-<pid>, so the agent namespace, its pods and its policies are never touched:

- agent-dns from gitops/agent-dns/resolver.yaml (the Corefile as committed), and egress-proxy from
  gitops/egress-proxy/egress_proxy.py with the Deployment's ALLOWED_HOSTS;
- agent-dns-resolver from gitops/agent-dns/agent-dns-resolver.yaml, renamed and scoped to the scratch namespace, with
  the scratch resolver's address in place of 172.20.0.53, so a pod created there is pointed at it by the live
  Kyverno engine, as an agent pod is;
- the policies of challenge-fixes' c1-network-policy.yaml (stage 2), then its c1-dns-lock.yaml (the fix), with the
  namespace rewritten.

Then, from a pod that runs the workshop-mcp image, as run_shell does:

1. Stage 2. A direct HTTPS request to the beacon's host fails (the L3/L4 allowlist holds). A never-seen name under
   example.com comes back NXDOMAIN or NODATA, an answer only example.com's servers on the internet can give, so the query left
   the cluster: the door stage 2b uses. (NODATA, the same proof, is what example.com gave on 2026-11-05.) The DNS collector (#726) is not built yet; this NXDOMAIN stands in for its
   record. The collector's own view is the owed check named in decisions.md.
2. The lock. The same kind of name now fails without an answer (SERVFAIL or timeout), a direct query to kube-dns or
   to the VPC resolver goes unanswered, and nothing reaches example.com.
3. Under the lock, the Bedrock runtime name resolves to an in-VPC address and answers HTTPS, kubernetes.default
   resolves, and Open-Meteo answers through egress-proxy while the beacon's host gets 403 from it.

Leaves the cluster as found: the MutatingPolicy and the namespace are deleted in a finally block.

Usage: CONTEXT=<kube-context> python3 verify/test_c1_dns_lock_live.py
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import uuid

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
CONTEXT = os.environ.get("CONTEXT", "")
NS = f"c1-dns-lock-check-{os.getpid()}"
MP_NAME = f"agent-dns-resolver-check-{os.getpid()}"
RES = [d for d in yaml.safe_load_all((REPO / "gitops/egress-proxy/egress-proxy.yaml").read_text()) if isinstance(d, dict)]
DNS = [d for d in yaml.safe_load_all((REPO / "gitops/agent-dns/resolver.yaml").read_text()) if d]
MP = yaml.safe_load((REPO / "gitops/agent-dns/agent-dns-resolver.yaml").read_text())
FIXES = next(d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text())
             if isinstance(d, dict) and d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "challenge-fixes")["data"]
LIMITS = {"requests": {"cpu": "10m", "memory": "32Mi"}, "limits": {"cpu": "200m", "memory": "128Mi"}}
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""), flush=True)
    if not cond:
        failures.append(name)


def kubectl(*args: str, stdin: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", CONTEXT, *args], input=stdin, capture_output=True, text=True,
                          timeout=timeout)


def apply(docs: list[dict]) -> None:
    r = kubectl("apply", "-f", "-", stdin=yaml.safe_dump_all(docs))
    if r.returncode != 0:
        raise RuntimeError(f"kubectl apply failed: {r.stderr.strip()}")


def one(docs: list[dict], kind: str, name: str) -> dict:
    return copy.deepcopy(next(d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name))


def into_scratch(d: dict) -> dict:
    d = copy.deepcopy(d)
    d["metadata"]["namespace"] = NS
    return d


def policies(text: str) -> list[dict]:
    return [into_scratch(d) for d in yaml.safe_load_all(text) if d and d.get("kind") == "NetworkPolicy"]


PROBE = r'''
import json, socket, sys, os, random, struct
out = {}
for name in sys.argv[1:]:
    try:
        out[name] = "ok:" + socket.getaddrinfo(name, 443, socket.AF_INET)[0][4][0]
    except socket.gaierror as e:
        out[name] = {socket.EAI_NONAME: "nxdomain", socket.EAI_NODATA: "nodata",
                     socket.EAI_AGAIN: "noanswer"}.get(e.errno, f"err:{e.errno}")
def raw(server, name):
    q = struct.pack(">HHHHHH", random.randrange(65536), 0x0100, 1, 0, 0, 0)
    q += b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(4)
    try:
        s.sendto(q, (server, 53)); s.recv(512); return "answered"
    except OSError:
        return "timeout"
for server in os.environ.get("RAW", "").split():
    out["raw:" + server] = raw(server, "example.com")
print(json.dumps(out))
'''


def probe(*names: str, raw: str = "") -> dict:
    r = kubectl("exec", "-n", NS, "tool", "--", "env", f"RAW={raw}", "python3", "-c", PROBE, *names, timeout=180)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"__error__": (r.stdout + r.stderr)[-400:]}


def curl(*args: str) -> tuple[int, str]:
    r = kubectl("exec", "-n", NS, "tool", "--", "curl", "-sS", "-o", "/dev/null", *args, timeout=120)
    return r.returncode, r.stdout.strip() + r.stderr.strip()


def wait_ready(selector: str, timeout: int = 240) -> bool:
    r = kubectl("wait", "-n", NS, "--for=condition=Ready", "pod", "-l", selector, f"--timeout={timeout}s",
                timeout=timeout + 30)
    return r.returncode == 0


missing = []
if not CONTEXT:
    missing.append("CONTEXT is not set: name the kube-context of the cluster to run against")
if shutil.which("kubectl") is None:
    missing.append("kubectl is not on PATH")
if missing:
    print("FAILED: " + "; ".join(missing))
    sys.exit(1)
if kubectl("get", "--raw", "/readyz", timeout=30).returncode != 0:
    print(f"FAILED: cluster for context {CONTEXT!r} is not reachable")
    sys.exit(1)
kube_dns = kubectl("-n", "kube-system", "get", "svc", "kube-dns", "-o", "jsonpath={.spec.clusterIP}").stdout.strip()
print(f"== scratch namespace {NS} on {CONTEXT} (kube-dns {kube_dns}) ==", flush=True)

try:
    apply([{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NS}}])

    # The resolver, as committed, with one replica and an address the cluster assigns.
    cm, dep, svc = (into_scratch(one(DNS, k, "agent-dns")) for k in ("ConfigMap", "Deployment", "Service"))
    dep["spec"]["replicas"] = 1
    del svc["spec"]["clusterIP"]
    # The proxy, as committed, from its source file.
    proxy = into_scratch(one(RES, "Deployment", "egress-proxy"))
    proxy_svc = into_scratch(one(RES, "Service", "egress-proxy"))
    proxy_src = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "egress-proxy-src", "namespace": NS},
                 "data": {"egress_proxy.py": (REPO / "gitops/egress-proxy/egress_proxy.py").read_text()}}
    apply([cm, dep, svc, proxy_src, proxy, proxy_svc])
    resolver_ip = kubectl("-n", NS, "get", "svc", "agent-dns", "-o", "jsonpath={.spec.clusterIP}").stdout.strip()
    check("the resolver's Service has an address", bool(resolver_ip), resolver_ip)

    # The mutation, scoped to the scratch namespace and pointed at the scratch resolver.
    mp = copy.deepcopy(MP)
    mp["metadata"]["name"] = MP_NAME
    mp["spec"]["matchConstraints"]["namespaceSelector"]["matchExpressions"][0]["values"] = [NS]
    expr = mp["spec"]["mutations"][0]["jsonPatch"]["expression"]
    mp["spec"]["mutations"][0]["jsonPatch"]["expression"] = expr.replace("172.20.0.53", resolver_ip).replace(
        '"agent.svc.cluster.local"', f'"{NS}.svc.cluster.local"')
    apply([mp])

    check("the resolver is Ready (the committed Corefile loads)", wait_ready("app.kubernetes.io/name=agent-dns"))
    check("egress-proxy is Ready", wait_ready("app.kubernetes.io/name=egress-proxy"))

    print("== the live Kyverno engine points a new pod at the resolver ==", flush=True)
    tool = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "tool", "namespace": NS, "labels": {"app": "workshop-mcp"}},
            "spec": {"containers": [{"name": "tool", "image": proxy["spec"]["template"]["spec"]["containers"][0]["image"],
                                     "command": ["sleep", "3600"], "resources": LIMITS}],
                     "automountServiceAccountToken": False, "terminationGracePeriodSeconds": 1}}
    dns_cfg = {}
    for _ in range(12):  # the webhook for a new MutatingPolicy registers within a few seconds
        apply([tool])
        spec = json.loads(kubectl("-n", NS, "get", "pod", "tool", "-o", "json").stdout)["spec"]
        dns_cfg = spec.get("dnsConfig") or {}
        if dns_cfg.get("nameservers") == [resolver_ip]:
            break
        kubectl("-n", NS, "delete", "pod", "tool", "--wait=true", "--grace-period=1")
        time.sleep(5)
    check("the pod's resolv.conf is the resolver alone, set at admission", dns_cfg.get("nameservers") == [resolver_ip],
          repr(dns_cfg))
    check("the tool pod is Ready", wait_ready("app=workshop-mcp"))

    print("== stage 2: c1-network-policy.yaml applied ==", flush=True)
    apply(policies(FIXES["c1-network-policy.yaml"]))
    time.sleep(15)
    rc, out = curl("-m", "8", "https://agenticburn.com/")
    check("a direct HTTPS request to the beacon's host fails (the L3/L4 allowlist holds it)", rc != 0, out)
    leak = f"c1-861-{uuid.uuid4().hex[:12]}.example.com"
    got = probe(leak)
    # NXDOMAIN or NODATA: either is an authoritative answer from example.com's servers (measured 2026-11-05: NODATA).
    check("a never-seen name under example.com gets an authoritative answer: the query reached the internet",
          got.get(leak) in ("nxdomain", "nodata"), repr(got))

    print("== the fix: c1-dns-lock.yaml applied ==", flush=True)
    apply(policies(FIXES["c1-dns-lock.yaml"]))
    time.sleep(20)
    leak2 = f"c1-861-{uuid.uuid4().hex[:12]}.example.com"
    got = probe(leak2, "example.com", raw=f"{kube_dns} 169.254.169.253")
    check("a never-seen name gets no answer: it stopped inside the cluster", got.get(leak2) == "noanswer", repr(got))
    check("example.com does not resolve either", not str(got.get("example.com", "")).startswith("ok:"), repr(got))
    check("a query sent straight to kube-dns goes unanswered", got.get(f"raw:{kube_dns}") == "timeout", repr(got))
    check("a query sent straight to the VPC resolver goes unanswered", got.get("raw:169.254.169.253") == "timeout",
          repr(got))

    print("== under the lock, what the lab needs still works ==", flush=True)
    bedrock = "bedrock-runtime.us-west-2.amazonaws.com"
    got = probe(bedrock, "kubernetes.default.svc.cluster.local", f"egress-proxy.{NS}.svc.cluster.local")
    check("the Bedrock runtime name resolves to an in-VPC address", str(got.get(bedrock, "")).startswith("ok:10."),
          repr(got))
    check("kubernetes.default resolves", str(got.get("kubernetes.default.svc.cluster.local", "")).startswith("ok:172.20."),
          repr(got))
    check("the proxy's Service name resolves", str(got.get(f"egress-proxy.{NS}.svc.cluster.local", "")).startswith("ok:"),
          repr(got))
    rc, code = curl("-m", "15", "-w", "%{http_code}", f"https://{bedrock}/")
    check("Bedrock's endpoint answers HTTPS in-VPC", code[:3].isdigit() and code[:3] != "000", f"rc {rc}: {code}")
    rc, code = curl("-m", "30", "-x", "http://egress-proxy:3128", "-w", "%{http_code}",
                    "https://api.open-meteo.com/v1/forecast?latitude=40.76&longitude=-111.89&current=temperature_2m")
    check("Open-Meteo answers 200 through egress-proxy", code.endswith("200"), f"rc {rc}: {code}")
    rc, code = curl("-m", "15", "-x", "http://egress-proxy:3128", "-w", "%{http_connect}", "https://agenticburn.com/")
    check("the beacon's host gets 403 from egress-proxy", "403" in code, f"rc {rc}: {code}")
    logs = kubectl("-n", NS, "logs", "-l", "app.kubernetes.io/name=agent-dns", "--tail=200").stdout
    check("the resolver logged the refused name, so the room can see what was asked", leak2 in logs)
finally:
    kubectl("delete", "mutatingpolicy", MP_NAME, "--ignore-not-found", "--wait=true")
    kubectl("delete", "namespace", NS, "--ignore-not-found", "--wait=true", timeout=300)
    left = kubectl("get", "namespace", NS, "--ignore-not-found", "-o", "name").stdout.strip()
    check("the scratch namespace and the MutatingPolicy are gone", not left
          and not kubectl("get", "mutatingpolicy", MP_NAME, "--ignore-not-found", "-o", "name").stdout.strip())

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All live C1 DNS lock checks passed.")
