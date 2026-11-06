# ABOUTME: Live failover of attackme between the two KubeCon clusters, from an attendee's phone-sized browser (#986): the
# ABOUTME: witch name and session survive, the same page chats on the standby with no refresh, and the composer returns.
# SUITE: e2e (needs COMMUNITY_CONTEXT and PRIVATE_CONTEXT, uv, a Chromium the pinned Playwright can run, and the pinned caddy)
"""Runs verify/failover_drill.py twice, once each way between the community cluster (kubecon-community) and the private
cluster (kubecon-private), and holds each drill to failover_drill.judge:

  - backups.py's Watcher promotes the standby and every one of attackme's routing rows moves to it;
  - the first chat is answered by the primary and, after the switch, the same page's next chat by the standby;
  - the page is never reloaded; the witch name in its header, its wib_witch cookie, and the witch name and session
    the chats carry are the same before and after;
  - the composer comes back by itself within 15 s of the promotion and stays on, the no-burritos screen never
    shows, and the whole wait is under 3 minutes;
  - a refresh afterwards keeps the witch name, the cookie and the session.

Each direction is a KubeCon cluster taking attackme from another: community -> private, and private -> community,
where the cluster taking over is a kubecon-community cluster, the profile a community standby (backups.tsv's
watch-it-burn-community-bNN) is built with. No cluster is created, changed or torn down, and the live router on
Railway is not touched: the router is a local Caddy running its cluster leg (failover_drill.py's docstring). Each
drill takes about two minutes and sends five chats carrying backups.py's probe marker, so none reaches the prompt wall.

Usage: COMMUNITY_CONTEXT=watch-it-burn-community PRIVATE_CONTEXT=watch-it-burn-private \\
       python3 verify/test_kubecon_failover_attendee_live.py      (after bash verify/fetch-e2e-tools.sh)
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
from playwright_browsers import UV, ensure  # noqa: E402
import failover_drill as drill  # noqa: E402

CADDY = VERIFY / ".tools/bin/caddy"
CADDY_VERSION = "v2.11.4"

problems = []
contexts = {k: os.environ.get(k, "") for k in ("COMMUNITY_CONTEXT", "PRIVATE_CONTEXT")}
problems += [f"{k} is not set: name the kube-context of the {k.split('_')[0].lower()} cluster" for k, v in contexts.items()
             if not v]
for tool in ("uv", "kubectl", "bash"):
    if shutil.which(tool) is None:
        problems.append(f"{tool} is not on PATH")
if not os.access(CADDY, os.X_OK):
    problems.append(f"no caddy at {CADDY}: run bash verify/fetch-e2e-tools.sh")
else:
    v = subprocess.run([str(CADDY), "version"], capture_output=True, text=True, timeout=30).stdout.split()
    if not v or v[0] != CADDY_VERSION:
        problems.append(f"{CADDY} is {v[0] if v else 'unknown'}, not the router's {CADDY_VERSION}")
if not problems:
    problems += ensure()
for k, ctx in contexts.items():
    if ctx and not problems:
        r = subprocess.run(["kubectl", "--context", ctx, "--request-timeout=15s", "get", "--raw", "/readyz"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            problems.append(f"{k} '{ctx}' is not reachable: {r.stderr.strip()[-200:]}")
if problems:
    print("FAILED: the failover drill cannot run; this is a failure, not a skip:\n" + "\n".join(f"  - {p}" for p in problems))
    sys.exit(1)

failures: list[str] = []
community, private = contexts["COMMUNITY_CONTEXT"], contexts["PRIVATE_CONTEXT"]
with tempfile.TemporaryDirectory(prefix="failover-live-") as d:
    for primary, standby in ((community, private), (private, community)):
        print(f"== attackme fails over from {primary} to {standby} ==")
        out = pathlib.Path(d) / f"{primary}-to-{standby}.json"
        r = subprocess.run([*UV, "python", str(VERIFY / "failover_drill.py"), "--primary", primary, "--standby", standby,
                            "--caddy", str(CADDY), "--out", str(out)], capture_output=True, text=True, timeout=1200)
        if r.returncode != 0 or not out.exists():
            print(f"  FAIL  the drill exited {r.returncode}: {r.stderr.strip()[-1500:]}")
            failures.append(f"{primary} -> {standby}: the drill did not finish")
            continue
        report = json.loads(out.read_text())
        for line in drill.summary(report):
            print(f"  {line}")
        for name, ok, detail in drill.judge(report):
            print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  -> {detail}"))
            if not ok:
                failures.append(f"{primary} -> {standby}: {name}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s):\n" + "\n".join(f"  - {f}" for f in failures))
    sys.exit(1)
print("\nALL KUBECON FAILOVER ATTENDEE CHECKS PASSED")
