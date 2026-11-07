# ABOUTME: Holds #1094: a turn that ends in kagent's ask_user shows the guest Nova's scratchpad through the pinned
# ABOUTME: guard-proxy, never the question, so BurritoBot's persona says never to call ask_user and to ask in its reply.
"""ask_user's question never reaches the chat page, offline.

On 2026-11-07 (run 18327 on #1089) fresh chats asked "What was the last thing I asked you, word for word as best you
remember?" and on 8 of 30 Nova called kagent's built-in ask_user; the chat page then showed the model's planning text.
Run 18386 read why, live: kagent v0.10.1 ends the turn in input-required, with the question only in DataParts (the
ask_user function call and the adk_request_confirmation in the status message), and the turn's one text part is the
<thinking> scratchpad. guard-proxy reads text parts only, so it sees a reasoning-only reply, asks once more in the same
chat, and when that turn calls ask_user again it hands the guest the scratchpad's contents. kagent adds ask_user to
every Agent with no setting to drop it (go/adk/pkg/agent/agent.go, buildAgentTools), so the persona carries the fix.

What this holds:
- the two tasks recorded live (verify/fixtures/ask-user-input-required-2026-11-07.json) are input-required, carry the
  question only outside text parts, and their only text part is a scratchpad;
- the pinned guard-proxy (gitops/ai-layer/guard-proxy/proxy.py), every guard off, behind a stand-in agent that
  answers the send and the retry with those two tasks, hands the guest the first one's planning text and neither
  question; a later pin that shows the question is named as such and must show it;
- the persona's ask_user rule says never to call ask_user, to write a question as reply text, names no other tool,
  and is the only place the systemMessage names ask_user; it stays in the persona's voice.

Whether Nova keeps the rule is #1094's decisions.md entry, measured on Bedrock with kagent's own ask_user and, after
the change syncs, live.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
AGENT = REPO / "gitops/workshop-agent/agent.yaml"
FIXTURE = REPO / "verify/fixtures/ask-user-input-required-2026-11-07.json"
SUB = REPO / "gitops/ai-layer/guard-proxy"
RULE_START = "Never call ask_user (#1094)."
RULE_END = "a reply that is only a scratchpad tells them nothing."
THINK = re.compile(r"<\s*thinking\s*>(.*?)(?:<\s*/\s*thinking\s*>|$)", re.S | re.I)

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


def flat(s: str) -> str:
    return " ".join(s.split())


def parts_of(task: dict) -> list[dict]:
    out = list(task.get("status", {}).get("message", {}).get("parts") or [])
    for h in task.get("history") or []:
        if h.get("role") == "agent":
            out += h.get("parts") or []
    return out


print("== the two ask_user turns read live (run 18386) ==")
tasks = [t["result"] for t in json.loads(FIXTURE.read_text())["tasks"]]
check("the fixture holds two tasks", len(tasks) == 2, len(tasks))
questions: list[str] = []
scratchpads: list[str] = []
for n, task in enumerate(tasks, 1):
    check(f"task {n} ends input-required", task.get("status", {}).get("state") == "input-required", task.get("status"))
    status_parts = task["status"]["message"]["parts"]
    confirm = [p for p in status_parts if p.get("kind") == "data" and p["data"].get("name") == "adk_request_confirmation"]
    check(f"task {n}'s status asks to confirm an ask_user call",
          len(confirm) == 1 and confirm[0]["data"]["args"]["originalFunctionCall"]["name"] == "ask_user", status_parts)
    asked = [q["question"] for q in confirm[0]["data"]["args"]["originalFunctionCall"]["args"]["questions"]]
    questions += asked
    texts = [p["text"] for p in parts_of(task) if p.get("kind") == "text"]
    check(f"task {n}'s only text part is a scratchpad", len(texts) == 1 and not THINK.sub("", texts[0]).strip(), texts)
    check(f"task {n}'s question is in no text part", not any(q in t for q in asked for t in texts), asked)
    scratchpads.append(" ".join(t.strip() for t in THINK.findall(texts[0])).strip())

print("== the pinned guard-proxy, every guard off, behind a stand-in agent ==")
served: list[dict] = []


class Agent(BaseHTTPRequestHandler):
    """Answers the first message/send with task 1 and the retry with task 2, as live trial 14 went."""

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        served.append(body)
        task = tasks[min(len(served), len(tasks)) - 1]
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": task}).encode()
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
agent_srv.shutdown()
proxy_srv.shutdown()
print(f"  the guest reads: {reply!r}")
sends = [b for b in served if b.get("method") == "message/send"]
check("guard-proxy sent the turn, then asked once more (a reasoning-only reply)", len(sends) == 2,
      [b.get("method") for b in served])
if any(q in reply for q in questions):
    print("  the pinned proxy.py shows ask_user's question to the guest")
    check("and none of the scratchpad", not any(s and s in reply for s in scratchpads), reply)
else:
    print("  the pinned proxy.py drops ask_user's question; the persona rule below is the fix (#1094)")
    check("at this pin the guest reads the first turn's planning text, the gap #1094 names", reply == scratchpads[0],
          f"{reply!r} vs {scratchpads[0]!r}")

print("== the persona's ask_user rule ==")
prompt = flat(yaml.safe_load(AGENT.read_text())["spec"]["declarative"]["systemMessage"])
for a in (RULE_START, RULE_END):
    anchored(prompt, a, str(AGENT.relative_to(REPO)))
rule = RULE_START + prompt.split(RULE_START, 1)[1].split(RULE_END, 1)[0] + RULE_END
check("it says the chat page cannot show ask_user", "The chat page cannot show it" in rule, rule)
check("a question is written as the bot's own reply text, in this reply",
      "a question included" in rule and "you write as your own reply text right after your scratchpad, in this reply"
      in rule, rule)
check("it names asking for a missing ticket number, as the marketing send check does",
      "a missing ticket number" in rule and "playfully ask for the missing piece" in prompt, rule)
named = set(re.findall(r"\b[a-z]+_[a-z_]+\b", rule))
check("it names ask_user and no other tool", named == {"ask_user"}, sorted(named))
outside = prompt.replace(rule, "")
check("no other line of the persona names ask_user", "ask_user" not in outside,
      [m.start() for m in re.finditer("ask_user", outside)])
for word in ("suspicious", "security", "poison", "malicious", "evil", "attack", "unsafe", "forbidden"):
    check(f"the rule does not say {word!r}", word not in rule.lower())

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {failures}")
    sys.exit(1)
print("ALL ASK_USER PERSONA CHECKS GREEN")
