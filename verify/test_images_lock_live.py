# ABOUTME: Live half of #603's record: every image both KubeCon clusters run has an images.lock row, by its name:tag
# ABOUTME: or the digest it runs at, so an image an operator starts that no file names is recorded and saved too.
# SUITE: e2e
"""Needs kubectl, COMMUNITY_CONTEXT naming the kube-context of watch-it-burn-community and PRIVATE_CONTEXT naming
the kube-context of watch-it-burn-private. Every missing prerequisite is a failure, never a skip.

#603 asks that every image this workshop depends on be recorded by digest and saved. test_images_lock.py holds the
references tracked files name, and test_images_lock_render.py the images the charts render. Neither sees a container
an operator starts at run time: run 17350 found kagent's golang-adk, the Prometheus operator's config reloader and
the Datadog operator's Agent and Cluster Agent running on both clusters with no row, and the AWS Load Balancer
Controller, which infra/deploy-full-idp.sh installs with Helm outside Argo CD. This reads every pod on each cluster
and holds each container to verify/images_live.py's judge; test_images_lock_live_judge.py holds the judge to
fixtures offline. EKS's own add-ons and what the room deploys through the bot are left out, and listed, as that
module says.

This changes nothing: one read-only `kubectl get` per cluster. It passes --show-managed-fields, without which kubectl
leaves out the managedFields the room's deploys are told apart by.

Usage: COMMUNITY_CONTEXT=<kube-context> PRIVATE_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] \\
           python3 verify/test_images_lock_live.py
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from images_live import uncovered  # noqa: E402

CLUSTERS = (("watch-it-burn-community", "COMMUNITY_CONTEXT"), ("watch-it-burn-private", "PRIVATE_CONTEXT"))
KINDS = "pods,replicasets,deployments,statefulsets,daemonsets,jobs,cronjobs"

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


lock = (REPO / "images.lock").read_text(encoding="utf-8")
check("kubectl is on PATH", shutil.which("kubectl") is not None)
for cluster, env in CLUSTERS:
    print(f"== {cluster} ==")
    ctx = os.environ.get(env, "")
    check(f"{env} names the kube-context of {cluster}", bool(ctx), f"{env} is not set")
    if not ctx or not shutil.which("kubectl"):
        continue
    r = subprocess.run(["kubectl", "--context", ctx, "--request-timeout=60s", "get", KINDS, "-A", "-o", "json",
                        "--show-managed-fields"],
                       capture_output=True, text=True)
    check(f"kubectl --context {ctx} get {KINDS} -A answers", r.returncode == 0, r.stderr.strip()[:300])
    if r.returncode != 0:
        continue
    objects = json.loads(r.stdout).get("items", [])
    pods = sum(1 for o in objects if o.get("kind") == "Pod")
    missing, left_out = uncovered(lock, objects)
    check(f"{cluster} runs pods ({pods})", pods > 0)
    for image, why in sorted(set(left_out)):
        print(f"        left out ({why}): {image}")
    for where, image, image_id in missing:
        print(f"        no row: {image} in {where} (imageID {image_id or '-'})")
    distinct = sorted({image for _, image, _ in missing})
    check(f"every image {cluster} runs has an images.lock row ({len(distinct)} without one)", not distinct)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s). Add a declared row for each image above, at the digest its registry "
          "serves, then run mirror-images.sh save on netcup.")
    sys.exit(1)
print("Every image both clusters run has an images.lock row.")
