# ABOUTME: #889's live read: sends one ask per fresh A2A context to the workshop agent through an agentgateway
# ABOUTME: port-forward, saves each whole task, and says which tools it called and whether guard-proxy's reply answers.
"""The linked-list ask over A2A, the way guard-proxy forwards it, with the whole task kept.

    kubectl --context watch-it-burn-community -n agent port-forward svc/agentgateway 13000:3000 &
    python3 docs/research/2026-11-08-ask-user/a2a_asks.py http://127.0.0.1:13000/ 12 <out-dir>

guard-proxy's /chat hands back one reply string. This keeps the task's history, artifacts and status, so a miss shows
where the answer went: into an ask_user question (the task stops at input-required), a run_shell echo, or a text
before a later tool call. The reply is built as guard-proxy's chat_reply_text builds it (artifacts, then the agent's
history, then the status message), and judged with the probe's word test on it with the scratchpad taken out.
Every ask carries the [[wib-probe]] marker, so none reaches the room's feed; the calls skip guard-proxy, so its /cost
counter does not count them.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import time
import urllib.request
import uuid

PROMPT = "how do I reverse a linked list\n\n[[wib-probe]]"
THINK = re.compile(r"<\s*thinking\s*>(.*?)(?:<\s*/\s*thinking\s*>|$)", re.S | re.I)


def call(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def text(parts) -> str:
    return " ".join(p.get("text", "") for p in parts or [] if p.get("kind") == "text")


def reply(task: dict) -> str:
    art = " ".join(text(a.get("parts")) for a in task.get("artifacts") or []).strip()
    if art:
        return art
    hist = " ".join(text(h.get("parts")) for h in task.get("history") or [] if h.get("role") == "agent").strip()
    return hist or text(task.get("status", {}).get("message", {}).get("parts")).strip()


def main() -> int:
    url, n, out = sys.argv[1], int(sys.argv[2]), pathlib.Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    good = 0
    for i in range(n):
        m = {"role": "user", "messageId": f"a2a-{uuid.uuid4().hex[:8]}", "contextId": f"a2a-{uuid.uuid4().hex[:8]}",
             "parts": [{"kind": "text", "text": PROMPT}]}
        task = call(url, {"jsonrpc": "2.0", "id": "x", "method": "message/send",
                          "params": {"message": m, "configuration": {"blocking": False}}}).get("result", {})
        t0 = time.time()
        while task.get("status", {}).get("state") in ("submitted", "working") and time.time() - t0 < 170:
            time.sleep(2)
            task = call(url, {"jsonrpc": "2.0", "id": "g", "method": "tasks/get", "params": {"id": task["id"]}})["result"]
        (out / f"ask{i}.json").write_text(json.dumps({"result": task}, indent=1))
        calls = [p["data"].get("name") for h in task.get("history") or [] for p in h.get("parts") or []
                 if p.get("kind") == "data" and isinstance(p.get("data"), dict) and p["data"].get("name")
                 and "response" not in p["data"]]
        r = THINK.sub("", reply(task))
        ok = len({w for w in ("node", "next", "prev", "pointer", "head") if re.search(rf"\b{w}", r, re.I)}) >= 2
        good += ok
        print(f"ask {i}: {task.get('status', {}).get('state')} answered={ok} calls={calls} reply={r.strip()[:80]!r}",
              flush=True)
    print(f"answered {good} of {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
