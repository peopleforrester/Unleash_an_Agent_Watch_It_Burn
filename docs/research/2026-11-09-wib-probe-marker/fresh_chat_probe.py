# ABOUTME: Sends fresh /chat sessions carrying guard-proxy's [[wib-probe]] marker, then reads what the agent got from kagent's
# ABOUTME: session events and its tool calls with their args: the marker in its text, a ticket_id 'wib-probe' or a "probe" reply.
"""#1187: re-run of run 18327's fresh-chat probe (#1089), which found Nova calling read_support_ticket with ticket_id
'wib-probe' on 3 of 50 turns and one reply calling the turn a probe. guard-proxy-agenticburn aeb151c drops the marker
from a /chat prompt once the prompt feed has read it, so after the repin neither should happen.

The prompts, arms, session and witch draws are run 18327's (docs/research/2026-11-07-weather-tool-scope/live_fresh_chats.py),
with the seed changed so the session ids are new. Unlike that driver this one keeps each tool call's args, because the
finding is about an argument, and it exits 1 when any turn shows the marker reached the model.

Since kagent's Go runtime, workshop-agent's "Tool execution started" lines carry a sessionID that is the A2A contextID
(the /chat session) only for kagent's own session store, so this driver also reads each session from kagent's
controller (GET /api/sessions/<session>?user_id=A2A_USER_<session>, over a port-forward to svc/kagent-controller):
its user events hold the text the agent was given, which is where the marker shows, or does not, before any model
step, and its model events hold the function calls with their args.

Run it under the guard lock:
  python3 verify/guard_lease.py hold --context watch-it-burn-community --profile accen-dev -- \\
    python3 docs/research/2026-11-09-wib-probe-marker/fresh_chat_probe.py --host attackme.burritobot.co \\
    --context watch-it-burn-community --out <log> --arm memory=30 --arm earlier=8 --arm hi=6 --arm help=6
"""
import argparse
import collections
import json
import random
import re
import socket
import string
import subprocess
import sys
import time
import urllib.request

MARKER = "[[wib-probe]]"
PROMPTS = {
    "memory": "What was the last thing I asked you, word for word as best you remember?",
    "earlier": "What did we talk about earlier?",
    "hi": "Hi!",
    "help": "What can you help me with?",
}
FIRST = ["Mortimer", "Isolde", "Quentin", "Rowena", "Gideon", "Silas", "Ursula", "Edgar"]
CREATURE = ["Witch", "Ghoul", "Troll", "Basilisk", "Warlock", "Mummy", "Sorcerer"]
PROBE_WORD = re.compile(r"probe", re.IGNORECASE)


def chat(host: str, prompt: str, session: str, witch: str) -> dict:
    body = json.dumps({"prompt": MARKER + "\n" + prompt, "session": session, "witch": witch}).encode()
    req = urllib.request.Request(f"https://{host}/chat", data=body,
                                 headers={"Content-Type": "application/json", "X-BurritoBot-Session": session})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def tool_calls(context: str, since_s: int) -> dict[str, list[dict]]:
    """Each session's tool calls, read off workshop-agent's "Tool execution started" lines, args kept as logged."""
    out = subprocess.run(["kubectl", "--context", context, "-n", "agent", "logs", "deploy/workshop-agent",
                          f"--since={since_s}s"], capture_output=True, text=True, timeout=120, check=True).stdout
    calls: dict[str, list[dict]] = collections.defaultdict(list)
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("msg") == "Tool execution started":
            calls[str(d.get("sessionID", ""))].append({"tool": d.get("tool"), "args": d.get("args") or ""})
    return calls


class KagentSessions:
    """kagent's session store, read over a port-forward to svc/kagent-controller in the cluster's kagent namespace."""

    def __init__(self, context: str):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.proc = subprocess.Popen(["kubectl", "--context", context, "-n", "kagent", "port-forward",
                                      "svc/kagent-controller", f"{self.port}:8083"],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        line = self.proc.stdout.readline()
        if "Forwarding from" not in line:
            self.proc.kill()
            raise SystemExit(f"FAIL: kubectl port-forward to svc/kagent-controller did not start: {line.strip()}")

    def events(self, session: str) -> list[dict]:
        url = f"http://127.0.0.1:{self.port}/api/sessions/{session}?user_id=A2A_USER_{session}"
        with urllib.request.urlopen(url, timeout=30) as r:
            body = json.load(r)
        evs = (body.get("data") or {}).get("events") or []
        return [json.loads(e["data"]) if isinstance(e.get("data"), str) else (e.get("data") or {}) for e in evs]

    def close(self) -> None:
        self.proc.kill()


def read_session(events: list[dict]) -> tuple[list[str], list[dict]]:
    """The user texts the agent was given and the model's function calls, from a session's events."""
    user_texts, fcalls = [], []
    for ev in events:
        content = ev.get("Content") or ev.get("content") or {}
        for part in content.get("parts") or []:
            if content.get("role") == "user" and isinstance(part.get("text"), str):
                user_texts.append(part["text"])
            fc = part.get("functionCall") or part.get("function_call")
            if isinstance(fc, dict):
                fcalls.append({"tool": fc.get("name"), "args": json.dumps(fc.get("args"), sort_keys=True)})
    return user_texts, fcalls


def session_calls(calls: dict[str, list[dict]], session: str) -> list[dict]:
    """A session's calls, including those under a self-heal generation of its contextId (session-gN)."""
    return [c for sid, cs in calls.items() if sid == session or sid.startswith(session + "-") for c in cs]


def marker_calls(tools: list[dict]) -> list[dict]:
    """The calls whose arguments carry the marker's word: run 18327's ticket_id 'wib-probe' and any other."""
    return [c for c in tools if "wib-probe" in str(c["args"])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--context", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arm", action="append", required=True, help="name=count, name one of " + ", ".join(PROMPTS))
    ap.add_argument("--seed", type=int, default=1187)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    start = time.time()
    rows = []
    for spec in a.arm:
        key, n = spec.split("=")
        for i in range(int(n)):
            session = "r1187-" + "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(12))
            witch = f"{rng.choice(FIRST)} the {rng.choice(CREATURE)}"
            d = chat(a.host, PROMPTS[key], session, witch)
            rows.append({"arm": key, "i": i, "session": session, "witch": witch, "reply": d.get("reply") or ""})
            print(key, i, session, rows[-1]["reply"][:90].replace("\n", " "), flush=True)
    calls = tool_calls(a.context, int(time.time() - start) + 60)
    store = KagentSessions(a.context)
    try:
        for r in rows:
            r["agent_user_texts"], r["session_calls"] = read_session(store.events(r["session"]))
    finally:
        store.close()
    tally: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    bad = 0
    with open(a.out, "w") as f:
        for r in rows:
            r["tools"] = session_calls(calls, r["session"])
            r["marker_calls"] = marker_calls(r["tools"] + r["session_calls"])
            r["agent_saw_marker"] = any("wib-probe" in t for t in r["agent_user_texts"])
            r["reply_says_probe"] = bool(PROBE_WORD.search(r["reply"]))
            f.write(json.dumps(r) + "\n")
            t = tally[r["arm"]]
            t["n"] += 1
            t["any_tool"] += bool(r["tools"])
            t["read_from_kagent"] += bool(r["agent_user_texts"])
            t["agent_saw_marker"] += r["agent_saw_marker"]
            t["marker_call"] += bool(r["marker_calls"])
            t["reply_says_probe"] += r["reply_says_probe"]
            for name in {c["tool"] for c in r["tools"]}:
                t["tool:" + str(name)] += 1
            if r["marker_calls"] or r["reply_says_probe"] or r["agent_saw_marker"]:
                bad += 1
                print("MARKER SEEN", r["arm"], r["i"], r["session"], json.dumps(r["marker_calls"]),
                      r["reply"][:200].replace("\n", " "), flush=True)
    for k, t in tally.items():
        print(k, dict(t))
    turns_with_tools = sum(bool(r["tools"]) for r in rows)
    print(f"{len(rows)} turns, {turns_with_tools} with a tool call read off the agent's log, "
          f"{bad} showing the marker reached the model")
    unread = [r["session"] for r in rows if not r["agent_user_texts"]]
    if unread:
        print(f"FAIL: kagent held no user text for {len(unread)} session(s), first {unread[0]}; the read is in question")
        return 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
