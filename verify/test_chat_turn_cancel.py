# ABOUTME: Holds #742's fix: a /chat turn that outlives guard-proxy's forward gets a sentence a phone can read, and
# ABOUTME: the agent's task is cancelled. Runs the pinned proxy.py, with the deployed env, against a runaway fake agent.
"""On 2026-10-31 a /chat turn on burritobot-private ran past PROXY_TIMEOUT (120s). The room got its 502, and the
agent kept going for 9,007s, 613 deploy_app calls, because nothing told it to stop (#742; the Tempo trace is
f7fc16a5debc57b7240a11ccfdebef70). guard-proxy-agenticburn#27 (5fe5a7c) made the forward a non-blocking A2A
message/send polled with tasks/get, which sends tasks/cancel when it gives up, and ef66c77 pinned it here.

What this holds, offline:
- The pinned guard-proxy contains 5fe5a7c, so a re-pin cannot drop the cancel.
- The Agent declares runtime: go. kagent v0.10.1's Python runtime answers tasks/cancel with NotImplementedError
  (guard-proxy-agenticburn#29) and keeps running; the Go runtime stops, measured live on 2026-10-31.
- PROXY_TIMEOUT is under TURN_TIMEOUT, so the forward's own limit is what ends a runaway turn.
- With every value guard-proxy's Deployment sets, its two timeouts scaled down from seconds to a fraction, the
  pinned proxy.py answers a turn whose task never finishes with a 502 that carries a readable reply, and the
  fake agent then receives tasks/cancel for that task.

The live half (the proxy's task_cancel log line after a real runaway turn) is not here; see #742's decisions entry.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
SUB = REPO / "gitops/ai-layer/guard-proxy"
CANCEL_FIX = "5fe5a7c30b03d024c5335b67c22e4953dfa06c4f"  # guard-proxy-agenticburn#27
KITCHEN_DOWN = "BurritoBot's kitchen isn't answering. Try again in a moment."
SCALE = 1 / 120  # PROXY_TIMEOUT 120s -> 1s; TURN_TIMEOUT keeps its ratio to it
TASK = "task-runaway-742"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== the pinned guard-proxy cancels the agent's task ==")
pin = subprocess.run(["git", "-C", str(REPO), "ls-tree", "HEAD", "--", "gitops/ai-layer/guard-proxy"],
                     capture_output=True, text=True).stdout.split()
pin_sha = pin[2] if len(pin) >= 3 and pin[0] == "160000" else ""
check("gitops/ai-layer/guard-proxy is a submodule gitlink", bool(pin_sha), f"ls-tree said {pin}")
contains = subprocess.run(["git", "-C", str(SUB), "merge-base", "--is-ancestor", CANCEL_FIX, pin_sha or "HEAD"],
                          capture_output=True, text=True)
check(f"the pin {pin_sha[:7]} contains guard-proxy-agenticburn#27's cancel {CANCEL_FIX[:7]}",
      contains.returncode == 0, contains.stderr.strip())

print("== the workshop-agent runs the runtime that honours tasks/cancel ==")
docs = [d for d in yaml.safe_load_all((REPO / "gitops/workshop-agent/agent.yaml").read_text(encoding="utf-8")) if d]
agents = [d for d in docs if d.get("kind") == "Agent" and d["metadata"]["name"] == "workshop-agent"]
check("gitops/workshop-agent/agent.yaml has one workshop-agent Agent", len(agents) == 1, f"found {len(agents)}")
runtime = ((agents[0]["spec"].get("declarative") or {}).get("runtime") if agents else None)
check(f"workshop-agent declares spec.declarative.runtime: go (got {runtime!r})", runtime == "go")

print("== the forward's limit ends a runaway turn ==")
ai_docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")) if d]
deploy = next(d for d in ai_docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
container = next(c for c in deploy["spec"]["template"]["spec"]["containers"] if c["name"] == "proxy")
ENV = {e["name"]: e["value"] for e in container["env"] if "value" in e}
proxy_timeout = float(ENV["PROXY_TIMEOUT"])
turn_timeout = float(ENV["TURN_TIMEOUT"])
check(f"PROXY_TIMEOUT {proxy_timeout:g}s is under TURN_TIMEOUT {turn_timeout:g}s",
      0 < proxy_timeout < turn_timeout)


class RunawayAgent(BaseHTTPRequestHandler):
    """Accepts the turn as a task and works on it until tasks/cancel, as the 2026-10-31 turn did."""
    calls: list[dict] = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        RunawayAgent.calls.append(body)
        state = {"message/send": "submitted", "tasks/get": "working", "tasks/cancel": "canceled"}.get(
            body.get("method"))
        if state is None:
            self.send_response(400)
            self.end_headers()
            return
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id"),
                          "result": {"kind": "task", "id": TASK, "contextId": "ctx-742",
                                     "status": {"state": state}}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


agent_srv = ThreadingHTTPServer(("127.0.0.1", 0), RunawayAgent)
threading.Thread(target=agent_srv.serve_forever, daemon=True).start()

os.environ.update(ENV)
os.environ.update({
    "AGENT_URL": f"http://127.0.0.1:{agent_srv.server_address[1]}",
    "PROXY_TIMEOUT": f"{proxy_timeout * SCALE:g}",
    "TURN_TIMEOUT": f"{turn_timeout * SCALE:g}",
    "OTEL_SDK_DISABLED": "true",
})
sys.path.insert(0, str(SUB))
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("guard_proxy_742", SUB / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)  # safe: the server only starts under __main__
proxy.Handler.log_message = lambda *a: None

events: list[str] = []


class Events(logging.Handler):
    def emit(self, record):
        events.append(getattr(record, "event", ""))


logging.getLogger("guard-proxy").addHandler(Events())
proxy_srv = ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
threading.Thread(target=proxy_srv.serve_forever, daemon=True).start()

print(f"== a turn whose task never finishes (PROXY_TIMEOUT {os.environ['PROXY_TIMEOUT']}s, "
      f"TURN_TIMEOUT {os.environ['TURN_TIMEOUT']}s) ==")
req = urllib.request.Request(f"http://127.0.0.1:{proxy_srv.server_address[1]}/chat",
                             data=json.dumps({"prompt": "Deploy my burrito app", "session": "s-742"}).encode(),
                             headers={"Content-Type": "application/json"}, method="POST")
start = time.monotonic()
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        status, raw = r.status, r.read()
except urllib.error.HTTPError as e:
    status, raw = e.code, e.read()
took = time.monotonic() - start
try:
    reply = json.loads(raw)
except ValueError:
    reply = {}
check("the room gets a 502", status == 502, f"got {status} {raw[:200]!r}")
check("the 502 carries a sentence a phone can read, in the /chat shape",
      reply == {"reply": KITCHEN_DOWN, "guarded": False, "input_tokens": 0, "output_tokens": 0}, f"got {reply}")
check(f"the turn ends at PROXY_TIMEOUT, not later ({took:.2f}s)",
      took < proxy_timeout * SCALE + 1.5)

deadline = time.monotonic() + 5
while time.monotonic() < deadline and not any(c.get("method") == "tasks/cancel" for c in RunawayAgent.calls):
    time.sleep(0.05)
cancels = [c for c in RunawayAgent.calls if c.get("method") == "tasks/cancel"]
check("the agent receives one tasks/cancel", len(cancels) == 1, f"methods {[c.get('method') for c in RunawayAgent.calls]}")
check("the cancel names the turn's task", bool(cancels) and cancels[0].get("params") == {"id": TASK},
      f"got {cancels[:1]}")
# The cancel thread logs task_cancel after the agent answers, and its JSON line goes to stderr before the Events
# handler sees it. A fixed 0.2 s sleep went red in run 17835's suite, on a loaded host, with the task_cancel line
# already on stderr: the thread was still in that write. So wait for the event, up to the same 5 s as the cancel.
deadline = time.monotonic() + 5
while time.monotonic() < deadline and "task_cancel" not in events:
    time.sleep(0.05)
check("guard-proxy logs forward_error, then task_cancel",
      "forward_error" in events and "task_cancel" in events
      and events.index("forward_error") < events.index("task_cancel"),
      f"events {[e for e in events if e]}")
methods = [c.get("method") for c in RunawayAgent.calls]
check("nothing reaches the agent after the cancel", methods[-1:] == ["tasks/cancel"], f"methods {methods}")

proxy_srv.shutdown()
agent_srv.shutdown()
if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll /chat turn cancel checks passed.")
