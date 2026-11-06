# ABOUTME: Live half of #471 and #980: on a cluster with Istio, the console, guard-proxy and the weather feed are captured
# ABOUTME: by ambient, the console-to-guard-proxy hop is logged by ztunnel as mutual TLS, and the feed still answers.
# SUITE: e2e
"""Needs kubectl and CONTEXT naming an attendee, admin or full cluster (the burn profile has no Istio). Every
missing prerequisite is a failure, never a skip.

Why (#471). The mesh used to enrol nothing while the pages said it encrypted traffic. Now the console and
guard-proxy pod templates carry istio.io/dataplane-mode=ambient, and since #980 the weather feed's does too, so the
C1 stage-2b egress waypoint can hold it (verify/test_mesh_enrollment.py holds the manifests). This proves a cluster
agrees: istio-cni redirected those pods, they are still Ready (their probes pass under the mesh), the console
still reaches guard-proxy, ztunnel recorded that connection with both workload identities, the line the tour
tells students to look for, and the weather feed still answers evil-mcp-shim, its caller from outside the mesh.

Read-only. The requests it drives are GET /guards, which reads the guard state, and the weather feed's GET
/healthz, which calls nothing; neither changes anything.

Usage: CONTEXT=<kube-context> python3 verify/test_mesh_live.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

CONTEXT = os.environ.get("CONTEXT", "")
NS = "agent"
LABEL = "istio.io/dataplane-mode"
REDIRECTED = "ambient.istio.io/redirection"
ENROLLED = ("console", "guard-proxy", "weather-feed")
NOT_ENROLLED = ("agentgateway", "workshop-agent")  # behind port-exact Ingress rules (chat-path-ingress.yaml)
SRC_ID = 'src.identity="spiffe://cluster.local/ns/agent/sa/default"'  # the console runs as default
DST_ID = 'dst.identity="spiffe://cluster.local/ns/agent/sa/guard-proxy-reader"'

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All live mesh checks passed.")


def kubectl(*args: str) -> subprocess.CompletedProcess:
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    return subprocess.run(["kubectl", "--context", CONTEXT, "--request-timeout=30s", *args],
                          capture_output=True, text=True)


if not CONTEXT:
    check("CONTEXT names the cluster to check", False, "CONTEXT=<kube-context> python3 verify/test_mesh_live.py")
    finish()
if not shutil.which("kubectl"):
    check("kubectl is on PATH", False)
    finish()

# The issue's own command: enrolment is per pod, so no namespace carries the label.
ns = kubectl("get", "ns", "-L", LABEL)
print(ns.stdout)
check("kubectl get ns answers", ns.returncode == 0, ns.stderr.strip())
labelled = kubectl("get", "ns", "-l", LABEL, "-o", "name")
check("no namespace is enrolled as a whole", labelled.returncode == 0 and not labelled.stdout.strip(),
      labelled.stdout.strip() or labelled.stderr.strip())

ds = kubectl("-n", "istio-system", "get", "daemonset", "ztunnel", "-o", "json")
check("ztunnel runs in istio-system", ds.returncode == 0, ds.stderr.strip() or "this profile has no Istio")
if ds.returncode == 0:
    st = json.loads(ds.stdout).get("status", {})
    check("every ztunnel pod is ready", st.get("desiredNumberScheduled", 0) > 0
          and st.get("numberReady") == st.get("desiredNumberScheduled"), f"{st}")

pods = kubectl("-n", NS, "get", "pods", "-o", "json")
check("agent pods are readable", pods.returncode == 0, pods.stderr.strip())
items = json.loads(pods.stdout).get("items", []) if pods.returncode == 0 else []


def of(app: str) -> list[dict]:
    return [p for p in items if p["metadata"].get("labels", {}).get("app.kubernetes.io/name") == app
            and p.get("status", {}).get("phase") == "Running"]


def ready(p: dict) -> bool:
    return any(c.get("type") == "Ready" and c.get("status") == "True" for c in p["status"].get("conditions", []))


for app in ENROLLED:
    running = of(app)
    check(f"{app} is running", bool(running))
    for p in running:
        meta = p["metadata"]
        check(f"{meta['name']} carries {LABEL}=ambient", meta.get("labels", {}).get(LABEL) == "ambient")
        check(f"{meta['name']} was redirected by istio-cni",
              meta.get("annotations", {}).get(REDIRECTED) == "enabled", f"annotations={meta.get('annotations')}")
        check(f"{meta['name']} is Ready, so its probes pass under the mesh", ready(p))
for app in NOT_ENROLLED:
    for p in of(app):
        check(f"{p['metadata']['name']} is not redirected",
              p["metadata"].get("annotations", {}).get(REDIRECTED) != "enabled")

# Drive one connection over the hop, then find it in ztunnel's access log.
hop = kubectl("-n", NS, "exec", "deploy/console", "-c", "nginx", "--",
              "wget", "-qO-", "-T", "10", "http://guard-proxy:8080/guards")
check("the console reaches guard-proxy through the mesh", hop.returncode == 0 and hop.stdout.strip().startswith("{"),
      (hop.stderr or hop.stdout).strip()[:300])
# The weather feed's one caller, evil-mcp-shim, is not enrolled; PERMISSIVE admits its plain text (#980).
feed = kubectl("-n", NS, "exec", "deploy/evil-mcp-shim", "-c", "shim", "--", "python", "-c",
               "import urllib.request; print(urllib.request.urlopen('http://weather-feed:8080/healthz', timeout=10).read().decode())")
check("evil-mcp-shim, outside the mesh, still reaches the enrolled weather feed",
      feed.returncode == 0 and '"ok": true' in feed.stdout, (feed.stderr or feed.stdout).strip()[:300])
logs = kubectl("-n", "istio-system", "logs", "-l", "app=ztunnel", "--tail=5000", "--max-log-requests=20")
check("ztunnel logs are readable", logs.returncode == 0, logs.stderr.strip())
lines = [ln for ln in logs.stdout.splitlines() if "connection complete" in ln and SRC_ID in ln and DST_ID in ln]
check("ztunnel logged the console-to-guard-proxy connection with both SPIFFE identities", bool(lines),
      f"no 'connection complete' line with {SRC_ID} and {DST_ID}")
if lines:
    print(f"\n  {lines[-1]}")
finish()
