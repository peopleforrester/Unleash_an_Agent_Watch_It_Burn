# ABOUTME: Holds #803: the pinned guard-proxy forwards the /chat body's witch name to the agent as a second A2A text
# ABOUTME: part after the prompt, and a /chat with no name reaches the agent as the prompt alone. Runs the pinned proxy.py.
"""The chat page sends the visitor's witch name in every /chat POST body ({prompt, session, witch}, #762). On
2026-11-01 a live HC-666 turn on the public cluster deployed `joker-burritobot` rather than the visitor's Joker,
because the deployed guard-proxy dropped the field. guard-proxy-agenticburn#34 (6f2de73) adds the name to the A2A
message as a second text part after the prompt, and aaf1872 forwards it only when it is shaped <First> the
<Creature>. The name stays outside the guards and the prompt feed.

What this holds, offline:
- The pinned guard-proxy contains 6f2de73, so a re-pin cannot drop the forwarding.
- With every value guard-proxy's Deployment sets, the pinned proxy.py, given a /chat with a name the storefront
  can assign, sends the agent exactly two text parts: the prompt as typed, then a sentence that carries the name.
  Every first name and every creature in burritbot.html's vocabulary is sent once, so a shape check the
  storefront's names do not pass cannot drop them.
- The input guards and the /prompts feed see the prompt only, never the name.
- A /chat with no witch field, an empty or blank one, or a non-string one reaches the agent as the prompt alone.

The live half (an HC-666 turn on a cluster that lands joker-<visitor slug>) is not here; see #803's decisions entry.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
SUB = REPO / "gitops/ai-layer/guard-proxy"
WITCH_FIX = "6f2de7310f8ec578b1178d21e88c2256316be7eb"  # guard-proxy-agenticburn#34
PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
PROMPT = "One bean burrito with extra salsa, please"
REPLY = "Coming right up."
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def js_array(name: str) -> list[str]:
    m = re.search(rf"var {name}=(\[.*?\]);", PAGE, flags=re.S)
    return json.loads(m.group(1)) if m else []


print("== the pinned guard-proxy forwards the witch name ==")
pin = subprocess.run(["git", "-C", str(REPO), "ls-tree", "HEAD", "--", "gitops/ai-layer/guard-proxy"],
                     capture_output=True, text=True).stdout.split()
pin_sha = pin[2] if len(pin) >= 3 and pin[0] == "160000" else ""
check("gitops/ai-layer/guard-proxy is a submodule gitlink", bool(pin_sha), f"ls-tree said {pin}")
contains = subprocess.run(["git", "-C", str(SUB), "merge-base", "--is-ancestor", WITCH_FIX, pin_sha or "HEAD"],
                          capture_output=True, text=True)
check(f"the pin {pin_sha[:7]} contains guard-proxy-agenticburn#34's witch-name forwarding {WITCH_FIX[:7]}",
      contains.returncode == 0, contains.stderr.strip())

first, creatures = js_array("WITCH_FIRST"), js_array("WITCH_CREATURES")
check(f"burritbot.html's witch vocabulary reads ({len(first)} first names, {len(creatures)} creatures)",
      bool(first) and bool(creatures))
check("the storefront still sends the name as the /chat body's witch field",
      "body:JSON.stringify({prompt:v,session:getSession(),witch:WITCH_NAME})" in PAGE)


class Agent(BaseHTTPRequestHandler):
    """Answers message/send with a finished task, as kagent does for a short turn, and keeps every message."""
    messages: list[dict] = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if body.get("method") != "message/send":
            self.send_response(400)
            self.end_headers()
            return
        Agent.messages.append(body["params"]["message"])
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id"),
                          "result": {"kind": "task", "id": "task-803", "contextId": "ctx-803",
                                     "status": {"state": "completed"},
                                     "artifacts": [{"parts": [{"kind": "text", "text": REPLY}]}]}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


agent_srv = ThreadingHTTPServer(("127.0.0.1", 0), Agent)
threading.Thread(target=agent_srv.serve_forever, daemon=True).start()

ai_docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")) if d]
deploy = next(d for d in ai_docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
container = next(c for c in deploy["spec"]["template"]["spec"]["containers"] if c["name"] == "proxy")
os.environ.update({e["name"]: e["value"] for e in container["env"] if "value" in e})
os.environ.update({"AGENT_URL": f"http://127.0.0.1:{agent_srv.server_address[1]}", "OTEL_SDK_DISABLED": "true"})
check("guard-proxy's Deployment turns the prompt feed on (STREAM_PROMPTS=on)", os.environ.get("STREAM_PROMPTS") == "on")
sys.path.insert(0, str(SUB))
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("guard_proxy_803", SUB / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)  # safe: the server only starts under __main__
proxy.Handler.log_message = lambda *a: None

# The three input guards are armed and replaced by spies that let every prompt through, so the test sees what
# each one is asked to scan without an LLM Guard to answer. The output guard and the budget stay off: they judge
# the reply and the spend, not the message the agent receives.
scanned: list[str] = []


def _spy(answer):
    def guard(text, *args, **kwargs):
        scanned.append(text)
        return answer
    return guard


proxy.blocklisted = _spy(None)
proxy.input_verdict = _spy((True, []))
proxy.topic_refused = _spy(None)
proxy.GUARDS.update(dict.fromkeys(proxy.GUARDS, False))
proxy.GUARDS.update({"input_blocklist": True, "input_classifier": True, "topic": True})

proxy_srv = ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
threading.Thread(target=proxy_srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{proxy_srv.server_address[1]}"
_turn = 0


def chat(body: dict) -> tuple[int, dict, dict | None]:
    """POST one /chat turn, each under its own session (the Deployment's 10/min per conversation stays out of it).
    Returns the status, the reply and the message the agent received, None when none reached it."""
    global _turn
    _turn += 1
    before = len(Agent.messages)
    req = urllib.request.Request(f"{BASE}/chat", data=json.dumps({"session": f"s-803-{_turn}", **body}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        reply = json.loads(raw)
    except ValueError:
        reply = {}
    return status, reply, (Agent.messages[before] if len(Agent.messages) > before else None)


def texts(message: dict | None) -> list[tuple[str, str]]:
    return [(p.get("kind"), p.get("text")) for p in (message or {}).get("parts", [])]


print("== a /chat with the storefront's witch name ==")
names = [f"{first[i % len(first)]} the {creatures[i % len(creatures)]}" for i in range(max(len(first), len(creatures)))]
sent = {}
for name in names:
    sent[name] = chat({"prompt": PROMPT, "witch": name})
status, reply, message = sent[names[0]]
parts = texts(message)
check(f"{names[0]!r}: the visitor gets the agent's reply", status == 200 and reply.get("reply") == REPLY,
      f"got {status} {reply}")
check(f"{names[0]!r}: the agent receives two text parts", len(parts) == 2 and all(k == "text" for k, _ in parts),
      f"parts {parts}")
check(f"{names[0]!r}: the first part is the prompt as typed", parts[:1] == [("text", PROMPT)], f"parts {parts}")
check(f"{names[0]!r}: the second part carries the name", len(parts) == 2 and names[0] in (parts[1][1] or ""),
      f"parts {parts}")
dropped = [n for n, (_, _, m) in sent.items()
           if texts(m)[:1] != [("text", PROMPT)] or len(texts(m)) != 2 or n not in (texts(m)[1][1] or "")]
check(f"every first name and creature the storefront assigns is forwarded ({len(names)} names, "
      f"{len(dropped)} not)", not dropped, f"not forwarded: {dropped[:5]}")
check("no input guard scans the name, each scans the prompt",
      bool(scanned) and all(t == PROMPT for t in scanned), f"scanned {sorted(set(scanned))[:5]}")
with urllib.request.urlopen(f"{BASE}/prompts", timeout=10) as r:
    feed = r.read().decode("utf-8", "replace")
check("the /prompts feed shows the prompt", "bean burrito" in feed, feed[:200])
check("the /prompts feed shows no witch name", not any(n in feed for n in names), feed[:200])

print("== a /chat with no witch name reaches the agent as the prompt alone ==")
for label, body in [("no witch field", {"prompt": PROMPT}),
                    ("an empty witch", {"prompt": PROMPT, "witch": ""}),
                    ("a blank witch", {"prompt": PROMPT, "witch": "   "}),
                    ("a null witch", {"prompt": PROMPT, "witch": None}),
                    ("a non-string witch", {"prompt": PROMPT, "witch": {"name": names[0]}})]:
    status, reply, message = chat(body)
    check(f"{label}: the visitor gets the agent's reply", status == 200 and reply.get("reply") == REPLY,
          f"got {status} {reply}")
    check(f"{label}: the agent receives exactly the prompt", texts(message) == [("text", PROMPT)],
          f"parts {texts(message)}")

proxy_srv.shutdown()
agent_srv.shutdown()
if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll /chat witch-name forwarding checks passed.")
