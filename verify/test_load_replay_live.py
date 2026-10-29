# ABOUTME: Live half of #644: two users of scripts/load-replay.py against a real cluster's public /chat, through the
# ABOUTME: router, TLS and console nginx, proving the harness reads a live bot before the 500-user run is spent on it.
# SUITE: e2e
"""Needs kubectl and CONTEXT naming a cluster whose public host is published (or LOAD_TARGET naming the site),
and the public internet. Every missing prerequisite is a failure with the reason, never a skip.

The offline suite (test_load_replay.py) proves the classification against guard-proxy's own handler. This
proves the path: two users, one turn each, from a two-prompt recording written here (the Portland harvest is
not needed, and none of its text is sent), both served, the cluster's /cost read before and after, and the
results written. Up to four Bedrock calls. It does not run the 500-user test; that is a deliberate run,
recorded in facilitation/kubecon-na-2026-load-test.md.

Usage: CONTEXT=<kube-context> python3 verify/test_load_replay_live.py
       LOAD_TARGET=https://<public-host> python3 verify/test_load_replay_live.py
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
CONTEXT = os.environ.get("CONTEXT", "")
TARGET = os.environ.get("LOAD_TARGET", "")


def fail(why: str) -> None:
    print(f"  FAIL  {why}")
    sys.exit(1)


print("== prerequisites ==")
if not TARGET:
    if not CONTEXT:
        fail("neither LOAD_TARGET nor CONTEXT is set: name the site, or the kube-context to read its host from")
    if not shutil.which("kubectl"):
        fail("kubectl is not on PATH, and LOAD_TARGET is not set")
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    r = subprocess.run(["kubectl", "--context", CONTEXT, "--request-timeout=20s", "-n", "agent", "get", "configmap",
                        "cluster-identity", "-o", "jsonpath={.data.public-host}"], capture_output=True, text=True)
    host = r.stdout.strip()
    if not host:
        fail(f"the cluster for {CONTEXT} records no public host (cluster-identity public-host): "
             f"{r.stderr.strip() or 'infra/datadog-cluster-identity.sh writes it at bootstrap'}")
    TARGET = f"https://{host}"
print(f"  PASS  target {TARGET}")

print("== two replayed users are served ==")
work = pathlib.Path(tempfile.mkdtemp(prefix="load-replay-live-"))
(work / "rec/prompts").mkdir(parents=True)
(work / "rec/prompts/live-check.json").write_text(json.dumps([
    {"ts": "1", "user": ["user: What burritos do you have today?"]},
    {"ts": "2", "user": ["user: Which salsa goes with the Sorcerizo?"]},
]))
r = subprocess.run([sys.executable, str(REPO / "scripts/load-replay.py"), "--target", TARGET,
                    "--recording", str(work / "rec"), "--users", "2", "--turns", "1", "--ramp", "0",
                    "--budget-usd", "0.5", "--out", str(work / "out"), "--run-id", "e2e"],
                   capture_output=True, text=True, timeout=600)
print(r.stdout.rstrip())
if r.returncode != 0:
    print(r.stderr.rstrip(), file=sys.stderr)
    fail(f"load-replay.py exited {r.returncode}")
summary = json.loads((work / "out/summary.json").read_text())
if summary["requests"] != 2 or summary["served"] != 2:
    fail(f"expected 2 requests both served, got {summary['requests']} sent, {summary['served']} served: "
         f"{summary['outcomes']}")
print("  PASS  both users' turns were served")
for key in ("cluster_cost_before", "cluster_cost_after"):
    if "error" in summary[key]:
        fail(f"{key}: {summary[key]['error']}")
if summary["cluster_cost_after"]["requests"] <= summary["cluster_cost_before"]["requests"]:
    fail("the cluster's /cost request count did not move: the turns did not reach this cluster's guard-proxy")
print("  PASS  the cluster's own /cost counted the turns")
print("All live load-replay checks passed.")
