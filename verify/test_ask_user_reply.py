# ABOUTME: Holds #1094: a /chat turn that ends in kagent's ask_user, replayed from two live tasks through the pinned
# ABOUTME: guard-proxy. At pin 5772a5d the guest reads Nova's scratchpad; any other pin must show the question instead.
"""What the guest reads when Nova calls kagent's ask_user, offline.

On 2026-11-07 (run 18327 on #1089) fresh chats asked "What was the last thing I asked you, word for word as best you
remember?" and on 8 of 30 Nova called kagent's built-in ask_user; the chat page then showed the model's planning text.
Run 18386 read why, live: kagent v0.10.1 ends the turn in input-required, with the question only in DataParts (the
ask_user function call and the adk_request_confirmation in the status message), and the turn's one text part is the
<thinking> scratchpad. guard-proxy at the pin reads text parts only, so it sees a reasoning-only reply, asks once more
in the same chat, and when that turn calls ask_user again it hands the guest the scratchpad's contents.

kagent adds ask_user to every Agent with no setting to drop it, and #889's persona rule ("Never call ask_user") was
live in run 19291 and still left 4 ask_user turns in 38 fresh chats, 2 of them showing planning text. The fix is
guard-proxy's: guard-proxy-agenticburn#72 (commit 2f21fe3, on its main) replies with the ask_user question and cancels
the pending task. It reaches the clusters with the next repin of gitops/ai-layer/guard-proxy, which is Michael's.

What this holds:
- the two tasks recorded live (verify/fixtures/ask-user-input-required-2026-11-07.json) are input-required, carry the
  question only outside text parts, and their only text part is a scratchpad;
- the pinned guard-proxy (gitops/ai-layer/guard-proxy/proxy.py), every guard off, behind a stand-in agent that answers
  the send and any retry with those two tasks: at the pin whose proxy.py is PRE_FIX_SHA256 (5772a5d) it hands the
  guest the first task's planning text after one retry, the gap #1094 names; at any other pin the guest reads task 1's
  question, with no scratchpad, no retry, and a tasks/cancel for task 1. So a repin that drops the fix fails here.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import re
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = REPO / "verify/fixtures/ask-user-input-required-2026-11-07.json"
SUB = REPO / "gitops/ai-layer/guard-proxy"
# proxy.py at guard-proxy 5772a5d, the pin since c51e1851 and the last one before guard-proxy-agenticburn#72's fix.
PRE_FIX_SHA256 = "ddf97ec452c00953c8b741e7891f2636b2fa959b95bd560e7d6cb070aef38ff6"
THINK = re.compile(r"<\s*thinking\s*>(.*?)(?:<\s*/\s*thinking\s*>|$)", re.S | re.I)

failures: list[str] = []


def check(name: str, cond: bool, detail: object = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail != "" and not cond else ""))
    if not cond:
        failures.append(name)


def parts_of(task: dict) -> list[dict]:
    out = list(task.get("status", {}).get("message", {}).get("parts") or [])
    for h in task.get("history") or []:
        if h.get("role") == "agent":
            out += h.get("parts") or []
    return out


if not (SUB / "proxy.py").is_file():
    print(f"FAIL  {SUB / 'proxy.py'} is missing: run bash verify/ensure-submodules.sh", file=sys.stderr)
    sys.exit(1)

print("== the two ask_user turns read live (run 18386) ==")
tasks = [t["result"] for t in json.loads(FIXTURE.read_text())["tasks"]]
check("the fixture holds two tasks", len(tasks) == 2, len(tasks))
questions: list[list[str]] = []
scratchpads: list[str] = []
for n, task in enumerate(tasks, 1):
    check(f"task {n} ends input-required", task.get("status", {}).get("state") == "input-required", task.get("status"))
    status_parts = task["status"]["message"]["parts"]
    confirm = [p for p in status_parts if p.get("kind") == "data" and p["data"].get("name") == "adk_request_confirmation"]
    check(f"task {n}'s status asks to confirm an ask_user call",
          len(confirm) == 1 and confirm[0]["data"]["args"]["originalFunctionCall"]["name"] == "ask_user", status_parts)
    asked = [q["question"] for q in confirm[0]["data"]["args"]["originalFunctionCall"]["args"]["questions"]]
    questions.append(asked)
    texts = [p["text"] for p in parts_of(task) if p.get("kind") == "text"]
    check(f"task {n}'s only text part is a scratchpad", len(texts) == 1 and not THINK.sub("", texts[0]).strip(), texts)
    check(f"task {n}'s question is in no text part", not any(q in t for q in asked for t in texts), asked)
    scratchpads.append(" ".join(t.strip() for t in THINK.findall(texts[0])).strip())

print("== the pinned guard-proxy, every guard off, behind a stand-in agent ==")
served: list[dict] = []


class Agent(BaseHTTPRequestHandler):
    """Answers the first message/send with task 1 and any later send with task 2, as live trial 14 went."""

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        served.append(body)
        sends = sum(1 for b in served if b.get("method") == "message/send")
        if body.get("method") == "tasks/cancel":
            result = dict(tasks[0], status={"state": "canceled"})
        else:
            result = tasks[min(max(sends, 1), len(tasks)) - 1]
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": result}).encode()
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
                   "BUDGET_GUARD": "off", "TOPIC_GUARD": "off"})
sys.path.insert(0, str(SUB))
spec = importlib.util.spec_from_file_location("guard_proxy_1094", SUB / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)  # safe: the server only starts under __main__
proxy.Handler.log_message = lambda *a: None
proxy.GUARDS.update(dict.fromkeys(proxy.GUARDS, False))
proxy_srv = ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
threading.Thread(target=proxy_srv.serve_forever, daemon=True).start()
req = urllib.request.Request(
    f"http://127.0.0.1:{proxy_srv.server_address[1]}/chat", method="POST",
    data=json.dumps({"prompt": "What was the last thing I asked you, word for word as best you remember?",
                     "session": "s-1094", "witch": "Quentin the Ghoul"}).encode(),
    headers={"Content-Type": "application/json", "X-BurritoBot-Session": "s-1094"})
with urllib.request.urlopen(req, timeout=30) as r:
    reply = json.loads(r.read()).get("reply", "")
# guard-proxy sends its tasks/cancel on a thread of its own, after the reply; give it a moment to arrive.
for _ in range(50):
    if any(b.get("method") == "tasks/cancel" for b in served):
        break
    threading.Event().wait(0.1)
agent_srv.shutdown()
proxy_srv.shutdown()
print(f"  the guest reads: {reply!r}")
methods = [b.get("method") for b in served]
sends = methods.count("message/send")
pin_sha = hashlib.sha256((SUB / "proxy.py").read_bytes()).hexdigest()
if pin_sha == PRE_FIX_SHA256:
    print("  the pin is 5772a5d, before guard-proxy-agenticburn#72: the guest reads planning text (#1094)")
    check("guard-proxy sent the turn, then asked once more (a reasoning-only reply)", sends == 2, methods)
    check("the guest reads the first turn's planning text, the gap #1094 names", reply == scratchpads[0],
          f"{reply!r} vs {scratchpads[0]!r}")
else:
    print(f"  the pin's proxy.py is {pin_sha[:12]}, after 5772a5d: it must show ask_user's question (#1094)")
    check("the guest reads task 1's ask_user question", reply.strip() == "\n".join(questions[0]).strip(),
          f"{reply!r} vs {questions[0]!r}")
    check("and none of the scratchpad", not any(s and s in reply for s in scratchpads), reply)
    check("guard-proxy sent the turn once, with no reasoning-only retry", sends == 1, methods)
    cancels = [b for b in served if b.get("method") == "tasks/cancel"]
    check("guard-proxy cancelled task 1, so it is not left pending",
          len(cancels) == 1 and (cancels[0].get("params") or {}).get("id") == tasks[0]["id"], cancels)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {failures}")
    sys.exit(1)
print("ALL ASK_USER REPLY CHECKS GREEN")
