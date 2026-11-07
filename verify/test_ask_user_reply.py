# ABOUTME: Holds #1094 offline: a /chat turn that kagent stops on its ask_user tool reaches the guest as Nova's scratchpad
# ABOUTME: at the pinned guard-proxy, and as the question once guard-proxy-agenticburn takes the committed patch.
"""The guest reads ask_user's question, offline.

On 2026-11-07 (run 18327, #1089) 8 of 30 fresh chats asked "What was the last thing I asked you, word for word as best
you remember?" called kagent's built-in ask_user, and the chat page showed the model's planning text ("The guest is
asking for the exact wording of their previous message. I should recall..."). Run 18353 read why, live. The turn ends
in A2A's input-required state with no artifact: the question sits only in data parts (the ask_user function call and
the adk_request_confirmation status), and the one text part is a <thinking> scratchpad. guard-proxy's /chat reads text
parts alone, finds a reasoning-only reply, sends the message once more in the same contextId, gets a scratchpad again,
and hands the guest the first one untagged (its last resort for a reasoning-only answer).

#1094 named three fixes. The Agent cannot drop ask_user: kagent 0.10.1's Go runtime adds it to every Agent with no
setting (go/adk/pkg/agent/agent.go, buildAgentTools). A persona rule against it cut ask_user on the Bedrock replica and
sent Nova to other tools instead, the weather pair and the customer records among them. So the fix is guard-proxy's:
a task stopped on ask_user is answered with its question. The change is guard-proxy-agenticburn's code, which no run
can push, so it is committed here as docs/research/2026-11-07-ask-user-reply/guard-proxy-ask-user.diff and filed
there. What this holds:

- ask_user is kagent's own tool, not one the Agent lists, and the pinned kagent is the 0.10.1 read, so a kagent bump
  reopens the Agent-side fix;
- the recorded live task (verify/fixtures/ask-user-input-required-2026-11-07.json) is that shape;
- the pinned guard-proxy, behind a stand-in agent answering with the recorded send and retry: until the repin, /chat
  answers the first scratchpad and no part of the question (the gap); once the pin carries the change, the question;
- the patch's proxy.py hunk applied to a copy of the pinned proxy.py answers the scratchpad and then the question, in
  one forward with no retry, so the chat page folds the scratchpad and shows the question.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
AGENT = REPO / "gitops/workshop-agent/agent.yaml"
SHOP_SERVER = REPO / "gitops/ai-layer/workshop-mcp-server.py"
EVIL_SERVER = REPO / "gitops/ai-layer/server.py"
KAGENT_APP = REPO / "gitops/bootstrap/apps/kagent.yaml"
FIXTURE = REPO / "verify/fixtures/ask-user-input-required-2026-11-07.json"
PATCH = REPO / "docs/research/2026-11-07-ask-user-reply/guard-proxy-ask-user.diff"
SUB = REPO / "gitops/ai-layer/guard-proxy"
# The kagent whose Go runtime run 18353 read: ask_user is appended to every Agent's tools, unconditionally.
KAGENT_PIN = "0.10.1"

failures: list[str] = []


def check(name: str, cond: bool, detail: object = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail != "" and not cond else ""))
    if not cond:
        failures.append(name)


def anchored(text: str, anchor: str, where: str) -> None:
    """Exit naming the anchor and the file when the text this test reads is not there (#797)."""
    if anchor not in text:
        print(f"FAIL  anchor {anchor!r} is not in {where}", file=sys.stderr)
        sys.exit(1)


def texts(parts) -> list[str]:
    return [p.get("text", "") for p in parts or [] if isinstance(p, dict) and p.get("kind") == "text"]


def datas(parts) -> list[dict]:
    return [p.get("data") or {} for p in parts or [] if isinstance(p, dict) and p.get("kind") == "data"]


def served(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {f.name for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool" for d in f.decorator_list)}


print("ask_user is kagent's own tool, and the pinned kagent adds it to every Agent")
agent = yaml.safe_load(AGENT.read_text())
listed = [n for t in agent["spec"]["declarative"]["tools"] for n in t.get("mcpServer", {}).get("toolNames", [])]
anchored(" ".join(listed), "run_shell", str(AGENT.relative_to(REPO)))
check("no toolNames list on the Agent carries ask_user", "ask_user" not in listed, listed)
shop, evil = served(SHOP_SERVER), served(EVIL_SERVER)
anchored(" ".join(sorted(shop)), "run_shell", str(SHOP_SERVER.relative_to(REPO)))
anchored(" ".join(sorted(evil)), "get_weather", str(EVIL_SERVER.relative_to(REPO)))
check("neither workshop-mcp nor evil-mcp serves ask_user", "ask_user" not in shop | evil, sorted(shop | evil))
pins = re.findall(r'^\s*targetRevision:\s*"?([^"\s#]+)"?', KAGENT_APP.read_text(), re.M)
check(f"kagent is pinned at {KAGENT_PIN}, whose Go runtime adds ask_user with no setting to drop it (on a bump, read "
      f"go/adk/pkg/agent/agent.go's buildAgentTools again: the Agent dropping ask_user is #1094's other fix)",
      pins == [KAGENT_PIN], pins)
check("the Agent runs the Go runtime", agent["spec"]["declarative"].get("runtime") == "go",
      agent["spec"]["declarative"].get("runtime"))

print("the recorded live turn: input-required, the question only in data parts, the text a scratchpad")
fx = json.loads(FIXTURE.read_text())
send, retry = fx["send"]["result"], fx["retry"]["result"]
check("the send ended in input-required", send["status"]["state"] == "input-required", send["status"].get("state"))
check("with no artifact", not send.get("artifacts"), send.get("artifacts"))
calls = [d for h in send["history"] if h.get("role") == "agent" for d in datas(h["parts"])
         if d.get("name") == "ask_user" and "args" in d]
check("the agent called ask_user once", len(calls) == 1, calls)
question = calls[0]["args"]["questions"][0]["question"] if calls else ""
check("the ask_user call carries a question for the guest", bool(question.strip()), calls)
status_data = datas(send["status"].get("message", {}).get("parts"))
check("the status asks for adk_request_confirmation carrying that ask_user call",
      [d.get("name") for d in status_data] == ["adk_request_confirmation"]
      and status_data[0]["args"]["originalFunctionCall"] == calls[0], status_data)
agent_text = " ".join(t for h in send["history"] if h.get("role") == "agent" for t in texts(h["parts"]))
check("the agent's only text is a <thinking> scratchpad",
      re.fullmatch(r"\s*<thinking>.*</thinking>\s*", agent_text, re.S) is not None, agent_text)
check("the question is in no text part", question not in agent_text)
check("the retry, sent in the same contextId, ended on a scratchpad too",
      retry["contextId"] == send["contextId"]
      and re.fullmatch(r"\s*<thinking>.*</thinking>\s*",
                       " ".join(t for a in retry.get("artifacts") or [] for t in texts(a["parts"])), re.S) is not None,
      retry.get("artifacts"))
# guard-proxy keeps the first answer when the retry is reasoning-only too, so the scratchpad it surfaces is the first.
scratch = re.sub(r"</?thinking>", "", agent_text).strip()

answers = [fx["send"], fx["retry"]]
sent: list[dict] = []


class Agent(BaseHTTPRequestHandler):
    """Answers the first message/send with the recorded send and every later one with the recorded retry."""

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if body.get("method") == "message/send":
            sent.append(body)
            resp = dict(answers[min(len(sent), len(answers)) - 1], id=body.get("id"))
        else:
            resp = {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601, "message": "not modelled"}}
        out = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


agent_srv = ThreadingHTTPServer(("127.0.0.1", 0), Agent)
threading.Thread(target=agent_srv.serve_forever, daemon=True).start()
os.environ.update({"AGENT_URL": f"http://127.0.0.1:{agent_srv.server_address[1]}", "OTEL_SDK_DISABLED": "true",
                   "STREAM_PROMPTS": "off", "INPUT_BLOCKLIST": "off", "INPUT_CLASSIFIER": "off", "OUTPUT_GUARD": "off",
                   "TOPIC_GUARD": "off"})
sys.path.insert(0, str(SUB))
memory_q = texts(send["history"][0]["parts"])[0]


def chat_through(proxy_py: pathlib.Path, name: str) -> tuple[str, list[dict]]:
    """Load proxy_py, serve its Handler on a free port, send the recorded memory question to /chat, and return the
    reply and the message/sends the stand-in agent received for it."""
    spec = importlib.util.spec_from_file_location(name, proxy_py)
    proxy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proxy)  # safe: the server only starts under __main__
    proxy.Handler.log_message = lambda *a: None
    proxy.GUARDS.update(dict.fromkeys(proxy.GUARDS, False))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    sent.clear()
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/chat",
                                 data=json.dumps({"prompt": memory_q, "session": f"s-{name}",
                                                  "witch": "Edgar the Mummy"}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()).get("reply", ""), list(sent)
    finally:
        srv.shutdown()


def holds_the_fix(reply: str, forwards: list[dict], where: str) -> None:
    check(f"{where}: the reply is the scratchpad, then the question", reply == agent_text.strip() + "\n\n" + question,
          repr(reply))
    check(f"{where}: one forward, no thinking-only retry", len(forwards) == 1, len(forwards))


print("the pinned guard-proxy's /chat on that turn, every guard off")
pinned = SUB / "proxy.py"
anchored(pinned.read_text() if pinned.exists() else "", "def chat_reply_text", str(pinned.relative_to(REPO)))
reply, forwards = chat_through(pinned, "guard_proxy_pinned_1094")
print(f"  /chat answered: {reply!r}")
pinned_has_fix = "def pending_questions(" in pinned.read_text()
if pinned_has_fix:
    print("  the pinned proxy.py shows ask_user's question (guard-proxy-agenticburn has taken #1094's change)")
    holds_the_fix(reply, forwards, "the pinned proxy.py")
else:
    print("  the pinned proxy.py reads text parts alone, so the guest gets the scratchpad (the gap #1094 names)")
    check("guard-proxy sent the turn twice, the second its thinking-only retry", len(forwards) == 2, len(forwards))
    check("the retry went to the same contextId",
          len(forwards) == 2 and forwards[0]["params"]["message"].get("contextId")
          == forwards[1]["params"]["message"].get("contextId"),
          [s["params"]["message"].get("contextId") for s in forwards])
    check("the guest reads the first try's scratchpad, untagged", reply == scratch, f"{reply!r} vs {scratch!r}")
    check("the guest reads no part of the question", question not in reply)

    print("the committed guard-proxy patch, applied to a copy of the pinned proxy.py")
    anchored(PATCH.read_text(), "+def pending_questions(result):", str(PATCH.relative_to(REPO)))
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(pinned, pathlib.Path(tmp) / "proxy.py")
        applied = subprocess.run(["git", "apply", "--include=proxy.py", str(PATCH)], cwd=tmp,
                                 capture_output=True, text=True)
        check("the patch's proxy.py hunk applies to the pinned proxy.py", applied.returncode == 0, applied.stderr)
        if applied.returncode == 0:
            reply, forwards = chat_through(pathlib.Path(tmp) / "proxy.py", "guard_proxy_patched_1094")
            print(f"  /chat answered: {reply!r}")
            holds_the_fix(reply, forwards, "the patched proxy.py")
agent_srv.shutdown()

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All #1094 ask_user reply checks passed.")
