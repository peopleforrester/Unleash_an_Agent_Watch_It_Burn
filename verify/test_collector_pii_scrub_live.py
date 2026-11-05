# ABOUTME: Live check of #647's trace scrub on the community cluster: its collector runs it, a span sent in comes back
# ABOUTME: from Datadog APM and Agent Observability scrubbed, and nothing stored for burritobot-public holds raw PII.
# SUITE: e2e (needs kubectl, COMMUNITY_CONTEXT naming the community cluster, AWS access to watch-it-burn/datadog, and Datadog)
"""The live half of verify/test_collector_pii_scrub.py and test_collector_pii_scrub_e2e.py. pii_scrub_live.py says
what each of its three parts checks and why; test_pii_scrub_live_logic.py runs them against fakes.

COMMUNITY_CONTEXT names the kube-context of the community cluster (attackme, the room's bot, burritobot-public in
Datadog), as test_kubecon_c3_live.py reads it. Datadog is read with the read pair in watch-it-burn/datadog as
WIB_DEFAULT_ACCOUNT (default accen-dev) in WIB_REGION (default us-west-2); a dispatched run sources
$HECATON_CLUSTER_ENV first. WIB_PII_SCAN_HOURS (default 168) is the stored-span scan's window, WIB_PII_WAIT (default
600) how long the sent span is waited for in each Datadog product.

What it spends: no model call. One span goes into Whitney's org under burritobot-public, deleted by the post-talk
purge. It reads the collector's ConfigMaps and opens one port-forward; nothing on the cluster changes.

It fails, never skips: no kubectl or aws, no COMMUNITY_CONTEXT, an unreadable secret, a Datadog refusal, a span that
does not arrive, or one raw match are each a FAIL with the reason.

Usage: COMMUNITY_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] python3 verify/test_collector_pii_scrub_live.py
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "infra/datadog-fleet"))
import pii_scrub_live as live  # noqa: E402

missing = [f"{t} is not on PATH" for t in ("kubectl", "aws") if shutil.which(t) is None]
context = os.environ.get("COMMUNITY_CONTEXT", "")
if not context:
    missing.append("COMMUNITY_CONTEXT is not set: name the kube-context of the community cluster (attackme)")
if missing:
    print("FAIL: the live scrub check cannot run; this is a failure, not a skip:\n" + "\n".join(f"  - {m}" for m in missing))
    sys.exit(1)

KUBECTL = ["kubectl", "--context", context]


def kubectl(args: list[str]) -> str:
    r = subprocess.run([*KUBECTL, *args], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"kubectl --context {context} {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


profile = os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev")
region = os.environ.get("WIB_REGION", "us-west-2")
hours = int(os.environ.get("WIB_PII_SCAN_HOURS", "168"))
wait = float(os.environ.get("WIB_PII_WAIT", "600"))
try:
    import fleet_monitors as fm
except ImportError as e:
    print(f"FAIL: infra/datadog-fleet/fleet_monitors.py cannot be imported: {e}")
    sys.exit(1)
try:
    api, app, site = fm.read_keys(profile, region)
    dd = fm.Datadog(site, api, app)
    checks = live.run(KUBECTL, kubectl, dd, hours, wait)
except (RuntimeError, OSError) as e:
    print(f"FAIL: {e}")
    sys.exit(1)

failures = [name for name, ok, _ in checks if not ok]
for name, ok, why in checks:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {why}" if why and not ok else ""))
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print(f"The community cluster's collector scrubs attendee PII before Datadog: the sent span came back scrubbed from "
      f"APM and Agent Observability, and {hours}h of stored {live.CLUSTER} spans hold no raw match.")
