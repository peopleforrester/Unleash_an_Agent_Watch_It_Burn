# ABOUTME: Live half of #452: sends the KubeCon prompt set's smoke prompt to a real cluster's public /chat with
# ABOUTME: scripts/replay-prompts.py, over the internet the way a presenter laptop on a hotspot would.
# SUITE: e2e
"""Needs kubectl, CONTEXT naming a cluster whose public host is published, and the public internet. Every
missing prerequisite is a failure with the reason, never a skip.

The offline suite (test_replay_prompts.py) proves the replay stops on each of guard-proxy's refusals. This
proves the other half: through the real router, TLS and console nginx, one replayed prompt reaches the bot
and comes back as a reply. One Bedrock call. The host is read from the cluster's cluster-identity ConfigMap,
not guessed; REPLAY_TARGET overrides it to aim at a named site (the Night Before uses attackme).

Usage: CONTEXT=<kube-context> python3 verify/test_replay_prompts_live.py
       REPLAY_TARGET=https://attackme.burritobot.co python3 verify/test_replay_prompts_live.py
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
CONTEXT = os.environ.get("CONTEXT", "")
TARGET = os.environ.get("REPLAY_TARGET", "")


def fail(why: str) -> None:
    print(f"  FAIL  {why}")
    sys.exit(1)


print("== prerequisites ==")
if not TARGET:
    if not CONTEXT:
        fail("neither REPLAY_TARGET nor CONTEXT is set: name the site, or the kube-context to read its host from")
    if not shutil.which("kubectl"):
        fail("kubectl is not on PATH, and REPLAY_TARGET is not set")
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    r = subprocess.run(["kubectl", "--context", CONTEXT, "--request-timeout=20s", "-n", "agent", "get", "configmap",
                        "cluster-identity", "-o", "jsonpath={.data.public-host}"], capture_output=True, text=True)
    host = r.stdout.strip()
    if not host:
        fail(f"the cluster for {CONTEXT} records no public host (cluster-identity public-host): "
             f"{r.stderr.strip() or 'infra/datadog-cluster-identity.sh writes it at bootstrap'}")
    TARGET = f"https://{host}"
print(f"  PASS  target {TARGET}")

print("== one replayed prompt reaches the bot ==")
r = subprocess.run([sys.executable, str(REPO / "scripts/replay-prompts.py"), "--target", TARGET, "--tag", "smoke"],
                   capture_output=True, text=True, timeout=300)
print(r.stdout.rstrip())
if r.returncode != 0:
    print(r.stderr.rstrip(), file=sys.stderr)
    fail(f"replay-prompts.py exited {r.returncode}: the smoke prompt did not come back as a bot reply")
if "DONE: 1 of 1 delivered" not in r.stdout:
    fail("replay-prompts.py exited 0 without reporting the smoke prompt delivered")
print("  PASS  the smoke prompt was delivered and answered")
print("All live replay checks passed.")
