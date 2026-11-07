# ABOUTME: #1094's live read: sends the memory question to workshop-agent over A2A, as guard-proxy's /chat does, from
# ABOUTME: inside the guard-proxy pod, and prints the raw task for every turn that ends in a state other than completed.
"""What kagent hands back when Nova calls ask_user.

Run it inside the guard-proxy pod, which reaches agentgateway, with the standard library only:

    . "$HECATON_CLUSTER_ENV"
    kubectl --context watch-it-burn-community -n agent exec -i deploy/guard-proxy -c proxy -- \\
        python - 20 < docs/research/2026-11-07-ask-user/a2a_raw.py > /tmp/a2a-raw.jsonl

Each trial is a fresh contextId, with the question and the witch-name part /chat adds. It goes straight to the agent,
past every AI guard, so it needs no guard lock, but each turn is a real Nova Pro call (about $0.008).
Every line printed is one JSON object: the trial, the final state, the reply text guard-proxy's chat_reply_text
would read off it, and, for a turn not completed, the whole final task.
"""
import json
import random
import string
import sys
import time
import urllib.request

AGENT = "http://agentgateway.agent.svc.cluster.local:3000/"
QUESTION = "What was the last thing I asked you, word for word as best you remember?"
FIRST = ["Mortimer", "Isolde", "Quentin", "Rowena", "Gideon", "Silas", "Ursula", "Edgar"]
CREATURE = ["Witch", "Ghoul", "Troll", "Basilisk", "Warlock", "Mummy", "Sorcerer"]


def call(body, witch):
    req = urllib.request.Request(AGENT, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Witch-Name": witch})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def text_of(parts):
    return " ".join(p.get("text", "") for p in (parts or []) if isinstance(p, dict) and p.get("kind") == "text")


def chat_reply_text(resp):
    """proxy.py's chat_reply_text at guard-proxy dc78f1c8, copied: artifacts, then agent history, then status."""
    result = resp.get("result") if isinstance(resp, dict) else None
    if not isinstance(result, dict):
        return ""
    art = " ".join(text_of(a.get("parts")) for a in (result.get("artifacts") or [])).strip()
    if art:
        return art
    hist = " ".join(text_of(h.get("parts")) for h in (result.get("history") or []) if h.get("role") == "agent").strip()
    if hist:
        return hist
    return text_of(result.get("status", {}).get("message", {}).get("parts")).strip()


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1094)
    for i in range(n):
        ctx = "r1094-" + "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(12))
        witch = f"{rng.choice(FIRST)} the {rng.choice(CREATURE)}"
        msg = {"role": "user", "messageId": f"r1094-{ctx}", "contextId": ctx,
               "parts": [{"kind": "text", "text": QUESTION},
                         {"kind": "text", "text": f"The person chatting with you gave their name as {witch}."}]}
        resp = call({"jsonrpc": "2.0", "id": "chat", "method": "message/send",
                     "params": {"message": msg, "configuration": {"blocking": False}}}, witch)
        deadline = time.monotonic() + 110
        while (resp.get("result") or {}).get("status", {}).get("state") in ("submitted", "working"):
            if time.monotonic() > deadline:
                break
            time.sleep(0.5)
            resp = call({"jsonrpc": "2.0", "id": "chat", "method": "tasks/get",
                         "params": {"id": resp["result"]["id"]}}, witch)
        state = (resp.get("result") or {}).get("status", {}).get("state")
        row = {"i": i, "context": ctx, "witch": witch, "state": state, "guest_reads": chat_reply_text(resp)}
        if state != "completed":
            row["task"] = resp.get("result")
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
