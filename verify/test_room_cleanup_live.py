# ABOUTME: Live check of #990 on the community cluster: remove-untrusted-room-workloads is installed as git writes it,
# ABOUTME: Kyverno's cleanup controller may delete, and a room-labelled public-image Deployment goes only when armed.
# SUITE: e2e
"""Needs kubectl and COMMUNITY_CONTEXT naming the kube-context of the community cluster (attackme, where the room
deploys). Every missing prerequisite is a failure, never a skip.

In order, this:

1. holds the live DeletingPolicy remove-untrusted-room-workloads to git's spec, and its last pass to have no error;
2. holds kyverno:cleanup-controller, the aggregated ClusterRole, to carry delete on Deployments and get on
   deny-external-registries, the grant remove-untrusted-room-workloads-rbac.yaml adds;
3. reads deny-external-registries' validationActions, and does not change them: the switch is the stage's, and other
   checks (test_recipe_block_live.py) flip it;
4. creates two Deployments of zero replicas in agent, each labelled burritobot.co/workload as deploy_app labels the
   room's: one on a public.ecr.aws image, one on registry.burritobot.co. They run no pod. As the admin, not an agent
   identity, deny-external-registries does not judge them;
5. waits for two of the policy's passes after both exist. With the policy at Deny, the public one must be gone and the
   internal one still there; at Audit, both must still be there;
6. reads validationActions again and fails, naming it, when they changed while it waited, since the verdict then
   says nothing;
7. always deletes what it created, so the cluster is left as it was found.

It takes about 10 minutes from a busy host, where each kubectl call took about 15 seconds (run 17969).

Usage: COMMUNITY_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] python3 verify/test_room_cleanup_live.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
POLICY = REPO / "policies/kyverno-breakout/remove-untrusted-room-workloads.yaml"
PUBLIC = "public.ecr.aws/docker/library/nginx:1.29-alpine"
INTERNAL = "registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0"
GONE, KEPT = "wib-990-room-public", "wib-990-room-internal"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


context = os.environ.get("COMMUNITY_CONTEXT", "")
missing = []
if not context:
    missing.append("COMMUNITY_CONTEXT is not set: name the kube-context of the community cluster (attackme)")
if not shutil.which("kubectl"):
    missing.append("kubectl is not on PATH")
if missing:
    for m in missing:
        print(f"FAIL: {m}", file=sys.stderr)
    sys.exit(1)


def kubectl(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", context, *args], input=stdin, capture_output=True, text=True,
                          timeout=120)


def get_json(*args: str) -> dict:
    r = kubectl("get", *args, "-o", "json")
    return json.loads(r.stdout) if r.returncode == 0 else {}


def actions() -> list[str]:
    return get_json("validatingpolicy", "deny-external-registries").get("spec", {}).get("validationActions", [])


def deployment(name: str, image: str) -> dict:
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name, "namespace": "agent"},
            "spec": {"replicas": 0, "selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": {"app": name, "burritobot.co/workload": name}},
                                  "spec": {"containers": [{"name": "c", "image": image,
                                                           "resources": {"limits": {"cpu": "50m", "memory": "64Mi"}}}]}}}}


print(f"== remove-untrusted-room-workloads on {context} ==")
live = get_json("deletingpolicy", "remove-untrusted-room-workloads")
want = yaml.safe_load(POLICY.read_text(encoding="utf-8"))["spec"]
check("the DeletingPolicy is installed as git writes it",
      bool(live) and {k: live["spec"].get(k) for k in want} == want, json.dumps(live.get("spec"))[:300])
check("its last pass reported no error", bool(live) and not live.get("status", {}).get("conditionStatus", {}).get("message"),
      json.dumps(live.get("status")))
rules = get_json("clusterrole", "kyverno:cleanup-controller").get("rules", [])
check("the cleanup controller may delete Deployments",
      any("apps" in r.get("apiGroups", []) and "deployments" in r.get("resources", []) and "delete" in r.get("verbs", [])
          for r in rules))
check("and may read deny-external-registries",
      any("validatingpolicies" in r.get("resources", []) and "get" in r.get("verbs", [])
          and "deny-external-registries" in (r.get("resourceNames") or ["deny-external-registries"]) for r in rules))

before = actions()
check("deny-external-registries reads Deny or Audit", before in (["Deny"], ["Audit"]), str(before))
armed = before == ["Deny"]
print(f"  ..    deny-external-registries is at {before}: the public Deployment should {'go' if armed else 'stay'}")
try:
    made = kubectl("apply", "-f", "-", stdin="\n---\n".join(json.dumps(deployment(n, i))
                                                          for n, i in ((GONE, PUBLIC), (KEPT, INTERNAL))))
    check("both probe Deployments are created", made.returncode == 0, made.stderr.strip())
    # Two passes after both exist: the policy runs on each minute, so wait to the second minute boundary and a margin.
    now = dt.datetime.now(dt.timezone.utc)
    time.sleep(120 - now.second - now.microsecond / 1e6 + 20)
    names = {d["metadata"]["name"] for d in get_json("deployment", "-n", "agent").get("items", [])}
    after = actions()
    check("deny-external-registries did not change while the check waited", after == before,
          f"it read {before} at the start and {after} at the end, so this run's verdict says nothing; run it again")
    if armed:
        check("armed: the room's public-image Deployment was deleted", GONE not in names)
    else:
        check("at Audit: the room's public-image Deployment is still there", GONE in names)
    check("the room's registry.burritobot.co Deployment is still there", KEPT in names)
    check("every platform Deployment in agent is still there",
          {"agentgateway", "guard-proxy", "workshop-agent", "workshop-mcp", "web-terminal"} <= names, str(sorted(names)))
finally:
    kubectl("delete", "deployment", "-n", "agent", GONE, KEPT, "--ignore-not-found", "--wait=true")
    left = {d["metadata"]["name"] for d in get_json("deployment", "-n", "agent").get("items", [])} & {GONE, KEPT}
    check("the probe Deployments are gone again, the cluster as it was found", not left, str(left))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ROOM CLEANUP LIVE CHECK GREEN")
