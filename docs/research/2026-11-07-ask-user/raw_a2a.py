# ABOUTME: #1094's live read: sends the memory question straight to workshop-agent over A2A (through agentgateway, as
# ABOUTME: guard-proxy does) in fresh contexts, and saves every task whole, so a turn that ends in ask_user can be read.
"""What kagent answers for a turn that ends in ask_user, read off the wire.

Each trial is a new contextId with the question and the witch-name part guard-proxy adds. The task is saved whole;
for one that ends input-required, a second message in the same context shows what the guest's next turn meets.

    kubectl --context watch-it-burn-community -n agent port-forward svc/agentgateway 13000:3000 &
    python3 docs/research/2026-11-07-ask-user/raw_a2a.py --url http://127.0.0.1:13000 --n 20 --out /tmp/raw.jsonl

THIS SPENDS REAL MONEY (about $0.008 a turn on Nova Pro) and bypasses guard-proxy's cost cap, so keep --n small.
"""
from __future__ import annotations

import argparse
import json
import random
import string
import time
import urllib.request

QUESTION = "What was the last thing I asked you, word for word as best you remember?"


def send(url: str, ctx: str, texts: list[str], seq: str) -> dict:
    msg = {"role": "user", "messageId": seq, "contextId": ctx, "parts": [{"kind": "text", "text": t} for t in texts]}
    body = {"jsonrpc": "2.0", "id": "x", "method": "message/send",
            "params": {"message": msg, "configuration": {"blocking": True}}}
    req = urllib.request.Request(url + "/", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--followup", default="Hmm, can you just tell me what you remember?")
    ap.add_argument("--seed", type=int, default=1094)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    with open(a.out, "w") as f:
        for i in range(a.n):
            ctx = "r1094-" + "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(12))
            witch = "The person chatting with you gave their name as Rowena the Witch."
            t0 = time.time()
            resp = send(a.url, ctx, [QUESTION, witch], f"r1094-{i}-a")
            state = ((resp.get("result") or {}).get("status") or {}).get("state")
            row = {"i": i, "ctx": ctx, "state": state, "secs": round(time.time() - t0, 1), "resp": resp}
            if state == "input-required":
                row["next"] = send(a.url, ctx, [a.followup, witch], f"r1094-{i}-b")
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(i, ctx, state, row["secs"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
