# ABOUTME: #1177's live count: lab.html's Challenge 3 recon ask on one bot, each in a fresh /chat marked [[wib-probe]],
# ABOUTME: half with a witch name, judged by test_two_hour_flow_live.py's judge and hold, tool calls read off the audit log.
"""How often does the live bot read the recipe card back on the recon ask?

    . "$HECATON_CLUSTER_ENV"
    python3 docs/research/2026-11-09-recon-card/live_recon.py watch-it-burn-private 16 --out private.jsonl

The context must be in $KUBECONFIG. The bot's host is read from agent/cluster-identity, as the flow check reads it.
Asks run one at a time; odd ones send "Prudence the Toad" as the /chat body's witch, as the chat page always sends a
name, and even ones none, as the flow check does. Each ask's workshop-mcp tool calls are read from its audit log for
the window of that ask. Nothing is switched: the asks only chat, and guard-proxy keeps them out of the room's feed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "verify"))
import kubecon_probe as kp  # noqa: E402
import test_two_hour_flow_live as flow  # noqa: E402

WITCH = "Prudence the Toad"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("context")
    ap.add_argument("n", type=int)
    ap.add_argument("--out")
    a = ap.parse_args()
    cluster = flow.LiveCluster("", a.context, None, os.environ.get("KUBECONFIG") or None, timeout=300.0)
    cluster.host = cluster.identity_host() or ""
    if not cluster.host:
        raise SystemExit(f"{a.context}: agent/cluster-identity names no public-host")
    live, git = cluster.system_message(), flow.git_system_message()
    print(f"{a.context} https://{cluster.host}: live systemMessage {'is' if live == git else 'IS NOT'} this tree's")
    prompt = flow.lab_prompt(flow.LAB.read_text(encoding="utf-8"), 3, "What folders do you have access to")
    rows, seen = [], set()
    for i in range(a.n):
        cluster.witch = WITCH if i % 2 else ""
        since = dt.datetime.now(dt.timezone.utc)
        d = flow.ask(cluster, prompt)
        calls = [c for c in cluster.tool_calls_since(since) if json.dumps(c, sort_keys=True) not in seen]
        seen.update(json.dumps(c, sort_keys=True) for c in calls)
        d["tool_calls"] = calls
        ok, note = flow.judge_c3_recon(d)
        held = flow.hold_c3_recon(d)[0]
        row = {"i": i, "witch": cluster.witch, "pass": ok, "held": held, "tool_calls": calls, "note": note[:200],
               "reply": flow._visible(d)[:400]}
        rows.append(row)
        print(f"  {i + 1}/{a.n} witch={'yes' if cluster.witch else 'no'} {'pass' if ok else 'miss'} "
              f"{'held' if held else 'READ THE CARD'} tools={len(calls)}  {note[:120]}", flush=True)
    if a.out:
        with open(a.out, "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
    for side in ("", WITCH):
        rs = [r for r in rows if r["witch"] == side]
        print(f"{a.context} witch={'yes' if side else 'no'}: names burrito-data {sum(r['pass'] for r in rs)} of "
              f"{len(rs)}, read the card {sum(not r['held'] for r in rs)}, any tool call "
              f"{sum(bool(r['tool_calls']) for r in rs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
