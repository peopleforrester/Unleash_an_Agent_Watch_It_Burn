# ABOUTME: Live half of #714: no pod, and no controller's pod template, on either KubeCon cluster names a Docker Hub
# ABOUTME: image, so no node on them pulls from Docker Hub, anonymously and rate-limited, for anything that runs there.
# SUITE: e2e
"""Needs kubectl, COMMUNITY_CONTEXT naming the kube-context of watch-it-burn-community and PRIVATE_CONTEXT naming
the kube-context of watch-it-burn-private. Every missing prerequisite is a failure, never a skip.

#714 removes every Docker Hub pull. test_no_docker_hub.py holds what the repo names and test_no_docker_hub_render.py
what the charts render; neither sees what is running. Run 17238 read every pod on both clusters and found two
leftovers no file named: agent/tron, a Deployment the room's deploy_app made on 2026-11-01 before #773 refused Docker
Hub names, in ImagePullBackOff on trongame/tron:latest for four days, and four KubeArmor pods on the private cluster
still on the Docker Hub images their operator had not yet rolled. This reads every Pod, ReplicaSet, Deployment,
StatefulSet, DaemonSet, Job and CronJob on each cluster and holds each container's spec image to
verify/docker_hub.py's judge (live_hub_images). No namespace or owner is left out, and EKS's add-ons come from its
ECR account. The one thing not judged is what deploy_app made for the room (docker_hub.room_asked: the agent namespace,
pods stamped burritobot.co/workload): since #991 deploy_app applies the image a guest asks for, from Docker Hub too, so
such an image is the room's Challenge 2 ask, not a platform pull. Each is printed. What starts no pod is: a
Deployment's old ReplicaSets, kept at 0 replicas as revision history (on 2026-11-05 both clusters held old demo-app,
kagent, KubeArmor, Grafana and falcosidekick revisions from before #623 and #714), and a finished Job.

A container's status.image is printed as a count but not judged: containerd reports the first name it holds an image
by, so a node that pulled the Docker Hub original before a ghcr.io copy replaced it reports that name with no new pull.
A fresh nodegroup holds no such names; on one, the count printed here is 0.

This changes nothing: one read-only `kubectl get` per cluster.

Usage: COMMUNITY_CONTEXT=<kube-context> PRIVATE_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] \\
           python3 verify/test_no_docker_hub_live.py
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from docker_hub import docker_hub, live_hub_images, room_asked  # noqa: E402

CLUSTERS = (("watch-it-burn-community", "COMMUNITY_CONTEXT"), ("watch-it-burn-private", "PRIVATE_CONTEXT"))
KINDS = "pods,replicasets,deployments,statefulsets,daemonsets,jobs,cronjobs"

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


check("kubectl is on PATH", shutil.which("kubectl") is not None)
for cluster, env in CLUSTERS:
    print(f"== {cluster} ==")
    ctx = os.environ.get(env, "")
    check(f"{env} names the kube-context of {cluster}", bool(ctx), f"{env} is not set")
    if not ctx or not shutil.which("kubectl"):
        continue
    r = subprocess.run(["kubectl", "--context", ctx, "--request-timeout=60s", "get", KINDS, "-A", "-o", "json"],
                       capture_output=True, text=True)
    check(f"kubectl --context {ctx} get {KINDS} -A answers", r.returncode == 0, r.stderr.strip()[:300])
    if r.returncode != 0:
        continue
    objects = json.loads(r.stdout).get("items", [])
    pods = [o for o in objects if o.get("kind") == "Pod"]
    check(f"{cluster} runs pods ({len(pods)})", bool(pods))
    cached = sum(1 for p in pods
                 for s in ((p.get("status") or {}).get("containerStatuses") or [])
                 + ((p.get("status") or {}).get("initContainerStatuses") or [])
                 if "/" in (s.get("image") or "") and docker_hub(s["image"]))
    print(f"        {cached} container status name(s) a node cached from Docker Hub (not judged; see the docstring)")
    asked = live_hub_images([o for o in objects if room_asked(o)])
    for where, image in asked:
        print(f"        the room asked deploy_app for {image} in {where} (#991; not judged)")
    found = live_hub_images([o for o in objects if not room_asked(o)])
    for where, image in found:
        print(f"        Docker Hub: {image} in {where}")
    check(f"no pod or pod template on {cluster} names a Docker Hub image ({len(found)} found)", not found)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s). Point each image above at its ghcr.io copy (lab-platform's mirror/, by "
          "digest), or remove the object if nothing in git deploys it.")
    sys.exit(1)
print("No pod or pod template on either cluster names a Docker Hub image.")
