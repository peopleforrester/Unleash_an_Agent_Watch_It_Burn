# ABOUTME: When did each cluster last send a trace? One query to the instructor Datadog org, which every
# ABOUTME: cluster dual-ships to (#242), printed as "<cluster>\t<ISO time>" lines for fleet-walkthrough.sh (#268).
"""Last trace seen, per cluster, for the admin console's health row.

The signal is the one the no-traces fleet monitor uses (infra/datadog-fleet/monitors.yaml):
traces.span.metrics.calls, grouped by kube_cluster_name, in the instructor org. One query covers the whole
fleet, so the walkthrough makes a single Datadog call however many clusters it walks.

A cluster with no span in the window is simply absent from the output. That is data, not an error: an
idle cluster outside a session is a correct cluster. A failed query is an error (exit 1, reason on stderr),
so the walkthrough can say the column is unknown instead of showing every cluster as silent.

Usage:
    python3 verify/last_trace.py --profile accen-dev --region us-west-2 [--hours 24]
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "infra" / "datadog-fleet"))
from fleet_monitors import GROUP_BY, Datadog, read_keys  # noqa: E402

QUERY = ("sum:traces.span.metrics.calls{kube_cluster_name:watch-it-burn-*} "
         "by {kube_cluster_name}.as_count()")


def last_seen(series: list[dict]) -> dict[str, str]:
    """Cluster name -> ISO time of its latest point with a non-zero span count."""
    seen: dict[str, int] = {}
    for s in series:
        name = next((t.split(":", 1)[1] for t in s.get("tag_set") or [] if t.startswith(GROUP_BY + ":")), None)
        if not name:
            continue
        stamps = [p[0] for p in s.get("pointlist") or [] if p and len(p) > 1 and p[1]]
        if stamps:
            seen[name] = max(seen.get(name, 0), int(max(stamps)))
    return {n: dt.datetime.fromtimestamp(ms / 1000, dt.UTC).isoformat(timespec="seconds")
            for n, ms in seen.items()}


def main(argv=None, keys=read_keys, http=None, now=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--region", required=True)
    ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args(argv)
    try:
        api, app, site = keys(args.profile, args.region)
        dd = Datadog(site, api, app, http=http)
        to = int(now if now is not None else time.time())
        q = urllib.parse.urlencode({"from": to - args.hours * 3600, "to": to, "query": QUERY})
        data = dd.call("GET", f"/api/v1/query?{q}")
        if data.get("status") == "error":
            raise RuntimeError(f"query error: {data.get('error', '')[:200]}")
    # No aws CLI, an unreachable Datadog, a malformed secret: each means the column is unknown, said so.
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"last_trace: {e}", file=sys.stderr)
        return 1
    for name, at in sorted(last_seen(data.get("series") or []).items()):
        print(f"{name}\t{at}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
