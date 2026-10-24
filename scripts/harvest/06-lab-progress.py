# ABOUTME: Sixth pass: the lab progress markers (#150) out of the INSTRUCTOR org, per attendee and per challenge:
# ABOUTME: when each challenge was opened, what help was revealed, when the fix was measured on, and who stalled.
"""Turns the witb.lab.calls series into the "did" half of the post-event picture.

The live view is the instructor dashboard (infra/terraform/dashboards/fleet-analytics.json). This is the same
data after the fact, at one-minute resolution, as:

  raw/lab-progress.json   every cluster's timeline, plus the funnel
  lab-progress.csv        one row per attendee cluster, keyed by `alias`, the friendly name the feedback app
                          records as `cluster` (#383). That column is the join. A feedback response marked
                          anonymous carries no cluster and must not be joined back to a row here.
  LAB-PROGRESS.md         aggregate only: the funnel per challenge, time to fix, unused and abandoned clusters

Unlike passes 1 to 3 this does not need the clusters to still be up, only the instructor org's keys:
  WITB_DD_ADMIN_API_KEY, WITB_DD_ADMIN_APP_KEY   the instructor org (the dual-ship destination, #242)
  WITB_DD_ADMIN_SITE                             default datadoghq.com
  WIB_FROM, WIB_TO                               epoch seconds; default the last 12 hours
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import pathlib
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
OUT = REPO / ".harvest" / os.environ.get("WIB_EVENT", "devopsdays-portland")

LAB_QUERY = ("sum:witb.lab.calls{*} by "
             "{kube_cluster_name,witb.lab.alias,span.name,witb.lab.challenge,witb.lab.kind}.as_count().rollup(sum, 60)")
AGENT_QUERY = "max:datadog.agent.running{*} by {kube_cluster_name}.rollup(max, 300)"
# An attendee's cluster, as fleet.sh names them (watch-it-burn-attendee-042). The cluster NAME decides who is an
# attendee, not the witb.lab.role tag: the lab page infers its role from the hostname, and an admin cluster's lab
# opened without ?role= reports itself as a student. The Community cluster, the <owner>-admin clusters and the
# presenters' own <owner>-student clusters are all left out.
STUDENT_CLUSTER = re.compile(r"-attendee-\d+$")
CHALLENGES = [str(n) for n in range(1, 9)]
ABANDON_MINUTES = 10


def tags(series: dict) -> dict:
    out = {}
    for t in series.get("tag_set") or []:
        k, _, v = t.partition(":")
        out[k] = v
    return out


def points(series: dict) -> list[tuple[int, float]]:
    """(epoch seconds, value) for every minute that counted something."""
    return [(int(ms // 1000), v) for ms, v in (series.get("pointlist") or []) if v]


def summarize(lab_series: list[dict], agent_series: list[dict]) -> dict:
    clusters: dict[str, dict] = {}
    for s in lab_series:
        t = tags(s)
        name = t.get("kube_cluster_name")
        pts = points(s)
        if not name or not pts or not STUDENT_CLUSTER.search(name):
            continue
        c = clusters.setdefault(name, {"cluster": name, "alias": "", "seen": set(), "heartbeat": set(), "challenges": {}})
        if t.get("witb.lab.alias"):
            c["alias"] = t["witb.lab.alias"]
        event = t.get("span.name", "")
        ch = t.get("witb.lab.challenge", "")
        for ts, _ in pts:
            c["seen"].add(ts)
        if event == "lab.heartbeat":
            c["heartbeat"].update(ts for ts, _ in pts)
        if ch not in CHALLENGES:
            continue
        r = c["challenges"].setdefault(ch, {"opened_at": None, "opens": 0, "hints": 0, "solutions": 0, "commands": 0,
                                            "fixed_at": None, "removed": 0})
        n = int(sum(v for _, v in pts))
        first = min(ts for ts, _ in pts)
        if event == "lab.step.open":
            r["opens"] += n
            r["opened_at"] = first if r["opened_at"] is None else min(r["opened_at"], first)
        elif event == "lab.hint.open":
            r["solutions" if t.get("witb.lab.kind") == "solution" else "hints"] += n
        elif event == "lab.command.send":
            r["commands"] += n
        elif event == "lab.control.installed":
            r["fixed_at"] = first if r["fixed_at"] is None else min(r["fixed_at"], first)
        elif event == "lab.control.removed":
            r["removed"] += n

    rows = []
    for c in clusters.values():
        seen = sorted(c.pop("seen"))
        beats = c.pop("heartbeat")
        c["first_seen"], c["last_seen"] = seen[0], seen[-1]
        c["active_minutes"] = len(beats)
        fixed = sorted((ch for ch, r in c["challenges"].items() if r["fixed_at"] is not None), key=int)
        for r in c["challenges"].values():
            # Only a fix that followed an open is a time to fix; a fix already on at the first poll is not.
            r["minutes_to_fix"] = (round((r["fixed_at"] - r["opened_at"]) / 60)
                                   if r["fixed_at"] is not None and r["opened_at"] is not None
                                   and r["fixed_at"] >= r["opened_at"] else None)
        c["fixed"] = fixed
        c["furthest_fixed"] = int(fixed[-1]) if fixed else 0
        c["hints_total"] = sum(r["hints"] for r in c["challenges"].values())
        c["solutions_total"] = sum(r["solutions"] for r in c["challenges"].values())
        c["abandoned_early"] = (c["last_seen"] - c["first_seen"]) < ABANDON_MINUTES * 60 and not fixed
        rows.append(c)
    rows.sort(key=lambda r: r["cluster"])

    running = sorted({tags(s).get("kube_cluster_name") for s in agent_series if points(s)} - {None})
    students_running = [n for n in running if STUDENT_CLUSTER.search(n)]
    unused = [n for n in students_running if n not in clusters]

    funnel = []
    for ch in CHALLENGES:
        rs = [r["challenges"][ch] for r in rows if ch in r["challenges"]]
        ttf = [r["minutes_to_fix"] for r in rs if r["minutes_to_fix"] is not None]
        funnel.append({
            "challenge": ch,
            "opened": sum(1 for r in rs if r["opens"]),
            "hint": sum(1 for r in rs if r["hints"]),
            "solution": sum(1 for r in rs if r["solutions"]),
            "fixed": sum(1 for r in rs if r["fixed_at"] is not None),
            "median_minutes_to_fix": statistics.median(ttf) if ttf else None,
        })
    return {"clusters": rows, "running": students_running, "unused": unused, "funnel": funnel}


def iso(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_csv(summary: dict, path: pathlib.Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["alias", "cluster", "first_seen", "last_seen", "active_minutes", "furthest_fixed", "fixed",
                    "hints_total", "solutions_total", "abandoned_early"])
        for r in summary["clusters"]:
            w.writerow([r["alias"], r["cluster"], iso(r["first_seen"]), iso(r["last_seen"]), r["active_minutes"],
                        r["furthest_fixed"], ";".join(r["fixed"]), r["hints_total"], r["solutions_total"],
                        "yes" if r["abandoned_early"] else "no"])


def report(summary: dict) -> str:
    rows = summary["clusters"]
    L = ["# Lab progress: how far attendees got, and where they stalled", "",
         "From the lab page's progress markers (#150) in the instructor org. Aggregate only; the per-cluster rows",
         "are in lab-progress.csv, keyed by the friendly cluster name for the feedback join. A feedback response",
         "marked anonymous carries no cluster and is never joined.", "",
         "| | Clusters |", "|---|---|",
         f"| Student clusters running | {len(summary['running'])} |",
         f"| Opened the lab | {len(rows)} |",
         f"| Never opened the lab (unused) | {len(summary['unused'])} |",
         f"| Left within {ABANDON_MINUTES} minutes with no fix installed | {sum(1 for r in rows if r['abandoned_early'])} |",
         ""]
    active = [r["active_minutes"] for r in rows if r["active_minutes"]]
    if active:
        L += [f"Minutes with the lab tab visible, per cluster: median **{statistics.median(active):.0f}**, "
              f"max {max(active)}.", ""]
    L += ["## Per challenge", "",
          "| Challenge | Opened | Revealed a hint | Revealed the prompt | Fix installed | Median minutes, open to fix |",
          "|---|---|---|---|---|---|"]
    for f in summary["funnel"]:
        m = "" if f["median_minutes_to_fix"] is None else f"{f['median_minutes_to_fix']:.0f}"
        L.append(f"| C{f['challenge']} | {f['opened']} | {f['hint']} | {f['solution']} | {f['fixed']} | {m} |")
    L += ["", "## Furthest fix installed", "", "| Furthest | Clusters |", "|---|---|"]
    for n in range(0, 9):
        k = sum(1 for r in rows if r["furthest_fixed"] == n)
        if k:
            L.append(f"| {'none' if n == 0 else f'C{n}'} | {k} |")
    return "\n".join(L) + "\n"


def query(q: str, frm: int, to: int, hdr: dict, site: str) -> list[dict]:
    url = f"https://api.{site}/api/v1/query?" + urllib.parse.urlencode({"from": frm, "to": to, "query": q})
    with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=60) as r:
        body = json.load(r)
    if body.get("status") == "error":
        raise RuntimeError(f"Datadog rejected {q!r}: {body.get('error')}")
    return body.get("series") or []


def main() -> int:
    api, app = os.environ.get("WITB_DD_ADMIN_API_KEY"), os.environ.get("WITB_DD_ADMIN_APP_KEY")
    if not api or not app:
        print("06-lab-progress: WITB_DD_ADMIN_API_KEY and WITB_DD_ADMIN_APP_KEY (the instructor org) are required",
              file=sys.stderr)
        return 2
    site = os.environ.get("WITB_DD_ADMIN_SITE", "datadoghq.com")
    to = int(os.environ.get("WIB_TO") or time.time())
    frm = int(os.environ.get("WIB_FROM") or to - 12 * 3600)
    hdr = {"DD-API-KEY": api, "DD-APPLICATION-KEY": app}
    lab = query(LAB_QUERY, frm, to, hdr, site)
    agents = query(AGENT_QUERY, frm, to, hdr, site)
    summary = summarize(lab, agents)
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    (OUT / "raw/lab-progress.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_csv(summary, OUT / "lab-progress.csv")
    (OUT / "LAB-PROGRESS.md").write_text(report(summary), encoding="utf-8")
    print(f"lab progress: {len(summary['clusters'])} clusters opened the lab, {len(summary['unused'])} unused; "
          f"wrote LAB-PROGRESS.md and lab-progress.csv", flush=True)
    if not lab:
        print("06-lab-progress: no witb.lab.calls series in the window; wrong org, wrong window, or the lab "
              "markers never shipped", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
