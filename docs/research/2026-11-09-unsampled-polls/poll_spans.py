# ABOUTME: Reads, out of Tempo on an admin cluster, each /chat turn's trace in a time window and counts the tasks/get
# ABOUTME: poll spans in it (#1225): guard-proxy's urllib POSTs under agent.forward after the message/send, and their hops.
"""Usage: python3 poll_spans.py --context <kube-context> --since <unix seconds> [--until <unix seconds>]

Run a blocked run_shell turn first (verify/c1-exfil-block.sh burritobot-private watch-it-burn-private accen-dev, which
takes the guard lock, applies the Challenge 1 policies, sends the resend prompt and puts the cluster back), note the
time before it, and pass that as --since. This reads every trace in the window whose root is guard-proxy's
POST /chat (service burritobot), and for each one with an `execute_tool run_shell` span prints:

- guard-proxy's CLIENT spans under `agent.forward`, in start order: the first is the message/send, every later one a
  tasks/get poll (run 17501, #877: a poll is the same POST with its own traceparent);
- the gateway's SERVER spans under those, and the agent's server spans under the gateway's outbound spans;
- whether the agent's `invocation` and `execute_tool run_shell` still hang under the message/send hop.

It exits 0 when every such trace has one guard-proxy CLIENT span under agent.forward, one gateway SERVER span under
it, the agent's spans under that, and no poll spans; 1 otherwise, and 1 when no trace with run_shell is found, so a
read that finds nothing is never a pass.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

GATEWAY = ("burritobot-gateway", "agentgateway")
SERVER, CLIENT = (2, "SPAN_KIND_SERVER"), (3, "SPAN_KIND_CLIENT")


def hex_id(v: str) -> str:
    if re.fullmatch(r"[0-9a-f]{16}|[0-9a-f]{32}", v or ""):
        return v
    return base64.b64decode(v).hex() if v else ""


def spans_of(doc) -> list[dict]:
    out = []

    def walk(node, svc):
        if isinstance(node, dict):
            res = node.get("resource")
            if isinstance(res, dict):
                svc = next((a["value"].get("stringValue") for a in res.get("attributes", [])
                            if a.get("key") == "service.name"), svc)
            if "spanId" in node and "name" in node:
                out.append({"service": svc, "name": node["name"], "kind": node.get("kind"),
                            "id": hex_id(node["spanId"]), "parent": hex_id(node.get("parentSpanId", "")),
                            "start": int(node.get("startTimeUnixNano", 0))})
                return
            for v in node.values():
                walk(v, svc)
        elif isinstance(node, list):
            for v in node:
                walk(v, svc)

    walk(doc, None)
    return out


def get(local: int, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{local}{path}", timeout=30) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", required=True)
    ap.add_argument("--since", type=int, required=True)
    ap.add_argument("--until", type=int, default=0)
    a = ap.parse_args()
    until = a.until or int(time.time()) + 60
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        local = s.getsockname()[1]
    pf = subprocess.Popen(["kubectl", "--context", a.context, "-n", "monitoring", "port-forward", "service/tempo",
                           f"{local}:3200"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    bad, seen = 0, 0
    try:
        time.sleep(4)
        q = '{resource.service.name="burritobot" && name="POST /chat"}'
        found = get(local, "/api/search?" + urllib.parse.urlencode(
            {"q": q, "start": a.since, "end": until, "limit": 50}))
        ids = [t["traceID"] for t in found.get("traces", [])]
        print(f"{len(ids)} /chat trace(s) between {a.since} and {until}")
        for tid in ids:
            spans = spans_of(get(local, f"/api/v2/traces/{tid}"))
            if not any(s["name"] == "execute_tool run_shell" for s in spans):
                continue
            seen += 1
            fwd = [s for s in spans if s["service"] == "burritobot" and s["name"] == "agent.forward"]
            fwd_ids = {s["id"] for s in fwd}
            hops = sorted((s for s in spans if s["service"] == "burritobot" and s["kind"] in CLIENT
                           and s["parent"] in fwd_ids), key=lambda s: s["start"])
            hop_ids = [h["id"] for h in hops]
            gw = [s for s in spans if s["service"] in GATEWAY and s["kind"] in SERVER and s["parent"] in hop_ids]
            out_ids = {s["id"] for s in spans if s["service"] in GATEWAY and s["kind"] in CLIENT
                       and s["parent"] in {g["id"] for g in gw}}
            agent = [s for s in spans if s["service"] == "burritobot-agent" and s["kind"] in SERVER
                     and s["parent"] in out_ids]
            send = hop_ids[:1]
            send_gw = {g["id"] for g in gw if g["parent"] in send}
            send_out = {s["id"] for s in spans if s["service"] in GATEWAY and s["kind"] in CLIENT
                        and s["parent"] in send_gw}
            under_send = {s["id"] for s in agent if s["parent"] in send_out}
            by_id = {s["id"]: s for s in spans}

            def below(span, roots):
                seen_ids = set()
                while span and span["id"] not in seen_ids:
                    if span["id"] in roots:
                        return True
                    seen_ids.add(span["id"])
                    span = by_id.get(span["parent"])
                return False

            inv = [s for s in spans if s["name"] == "invocation"]
            tool = [s for s in spans if s["name"] == "execute_tool run_shell"]
            polls = len(hops[1:])
            poll_gw = len([g for g in gw if g["parent"] in hop_ids[1:]])
            poll_agent = len([s for s in agent if s["id"] not in under_send])
            ok = (len(hops) == 1 and len(send_gw) == 1 and polls == 0 and poll_gw == 0 and poll_agent == 0
                  and bool(under_send) and all(below(s, under_send) for s in inv + tool) and bool(inv))
            bad += 0 if ok else 1
            print(f"trace {tid}: {len(spans)} spans; guard-proxy hops under agent.forward {len(hops)} "
                  f"(message/send 1, tasks/get polls {polls}); gateway SERVER under them {len(gw)} "
                  f"(under polls {poll_gw}); agent server spans {len(agent)} (outside message/send {poll_agent}); "
                  f"invocation {len(inv)} and execute_tool run_shell {len(tool)} under message/send "
                  f"{all(below(s, under_send) for s in inv + tool) and bool(under_send)}: {'PASS' if ok else 'FAIL'}")
    finally:
        pf.terminate()
        pf.wait(timeout=15)
    if not seen:
        print("FAIL: no /chat trace with execute_tool run_shell in the window")
        return 1
    print(f"{seen} run_shell trace(s), {bad} with poll spans or a missing message/send hop")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
