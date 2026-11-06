# ABOUTME: Live half of #1022 on a cluster: workshop-mcp's presence report reaches the desk, and a landed row is marked
# ABOUTME: removed on the deployments page within a minute of its Deployment being deleted, and not before.
# SUITE: e2e (needs kubectl and CONTEXT naming a cluster that runs the ai-layer at or past #1022)
"""Usage: CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] python3 verify/test_deployments_removed_live.py

In order, this:

1. reads workshop-mcp's log for "presence report: working", the line its presence loop prints once a list and a post
   to the desk both worked, and fails naming the last "presence report failed" line when there is one instead;
2. creates, as the admin, a Deployment of zero replicas in agent, labelled burritobot.co/workload as deploy_app labels
   the room's and on registry.burritobot.co, so remove-untrusted-room-workloads keeps it even with the switch armed;
3. reports it to the desk's /landed through the API server's service proxy, as deploy_app does, with its kind;
4. waits past two presence reports and holds the row on /deployments.json unmarked while the Deployment is there;
5. deletes the Deployment and holds the row marked "removed" within 90 seconds;
6. always deletes the Deployment, so the cluster is left as it was found.

What it leaves: the desk keeps its rows in memory, so the probe's line, "Someone deployed maintenance-shell at <time>,
removed at <time>", stays on that cluster's deployments page until fake-ticket restarts. Do not run it while a room
is watching the page.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import time

CONTEXT = os.environ.get("CONTEXT", "")
IMAGE = "registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0"
PROXY = "/api/v1/namespaces/agent/services/fake-ticket:8080/proxy"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("A deleted app's row stays on the deployments page and is marked removed.")
    sys.exit(0)


if not CONTEXT:
    print("FAILED: CONTEXT is not set; name the kube-context of a cluster that runs the ai-layer")
    sys.exit(1)
if shutil.which("kubectl") is None:
    print("FAILED: kubectl not on PATH")
    sys.exit(1)


def kubectl(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", CONTEXT, *args], input=stdin, capture_output=True, text=True,
                          timeout=120)


def rows() -> list[dict]:
    r = kubectl("get", "--raw", f"{PROXY}/deployments.json")
    return json.loads(r.stdout) if r.returncode == 0 else []


print(f"== workshop-mcp's presence report on {CONTEXT} ==")
log = kubectl("-n", "agent", "logs", "deploy/workshop-mcp", "-c", "shim", "--tail", "2000")
lines = [x for x in log.stdout.splitlines() if x.startswith("presence report")]
check("workshop-mcp's log is read", log.returncode == 0, log.stderr.strip()[-300:])
check("its last presence line says the report is working", bool(lines) and lines[-1] == "presence report: working",
      lines[-1] if lines else "no presence line: workshop-mcp predates #1022 or its loop never ran")
if failures:
    finish()

NAME = f"wib-1022-probe-{secrets.token_hex(3)}"
manifest = {"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": NAME, "namespace": "agent", "labels": {"app.kubernetes.io/name": NAME}},
            "spec": {"replicas": 0, "selector": {"matchLabels": {"app.kubernetes.io/name": NAME}},
                     "template": {"metadata": {"labels": {"app.kubernetes.io/name": NAME,
                                                          "burritobot.co/workload": NAME}},
                                  "spec": {"containers": [{"name": "c", "image": IMAGE, "resources": {
                                      "limits": {"cpu": "20m", "memory": "32Mi"}}}]}}}}
print(f"== a landed row for {NAME} ==")
try:
    made = kubectl("create", "-f", "-", stdin=json.dumps(manifest))
    check("the probe Deployment is created, zero replicas", made.returncode == 0, made.stderr.strip())
    rep = kubectl("create", "--raw", f"{PROXY}/landed", "-f", "-",
                  stdin=json.dumps({"name": NAME, "ok": True, "image": IMAGE, "kind": "Deployment"}))
    check("the desk takes its /landed report through the service proxy", rep.returncode == 0, rep.stderr.strip())
    if failures:
        finish()
    time.sleep(45)  # past the desk's 10 s grace and two 15 s reports
    row = next((r for r in rows() if r["name"] == NAME), None)
    check("its row is on /deployments.json", row is not None)
    check("and not marked removed while the Deployment is there", bool(row) and row.get("removed") == "", str(row))
    gone = kubectl("-n", "agent", "delete", "deployment", NAME, "--wait=true")
    check("the probe Deployment is deleted", gone.returncode == 0, gone.stderr.strip())
    deadline = time.time() + 90
    row = None
    while time.time() < deadline:
        row = next((r for r in rows() if r["name"] == NAME), None)
        if row and row.get("removed"):
            break
        time.sleep(5)
    check("within 90 seconds its row is marked removed, with a time", bool(row) and bool(row.get("removed")), str(row))
    check("and is still listed: the page keeps the record of the ask", row is not None)
finally:
    kubectl("-n", "agent", "delete", "deployment", NAME, "--ignore-not-found", "--wait=false")
    left = kubectl("-n", "agent", "get", "deployment", NAME, "--ignore-not-found", "-o", "name")
    check("the probe Deployment is gone, the cluster as it was found", left.stdout.strip() == "", left.stdout.strip())
finish()
