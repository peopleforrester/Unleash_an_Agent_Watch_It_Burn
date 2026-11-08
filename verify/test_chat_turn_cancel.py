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
- The 502 is written before the tasks/cancel reaches the agent, held by order and not by a wall clock (#1054). The
  fake agent holds its tasks/cancel answer until the 502 is written, so a 502 that waited on the cancel round trip
  would leave the proxy's cancel to time out, and the agent would see the cancel before the 502.

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
CANCEL_HOLD_CEILING = 10.0  # seconds the fake agent holds tasks/cancel for the 502; a guard on a hang, not a bound
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


# Set once guard-proxy has written the room's 502 to the client's socket (#1054). The fake agent holds its
# tasks/cancel answer on it, so the check is about order, which host load cannot change. Run 17768 failed a 2.5 s
# bound on this turn at 4.98 s, and the theory that the 502 waited on the cancel was wrong: proxy.py writes the 502,
# then starts the cancel on its own thread (guard-proxy-agenticburn#60). The client, proxy.py and this agent share
# one process on a shared host, so a starved client reads an answer already in its socket late.
# The issue suggested setting this once the client has read the 502. The release is tied to the write instead: the
# proxy's own tasks/cancel waits the scaled PROXY_TIMEOUT (1 s) for an answer, so a hold until a starved client
# reads would turn host load into task_cancel_failed, the same flake in another check. A proxy that cancelled before
# its 502 still fails here: the cancel reaches the agent with the event unset, the agent holds its answer, the
# proxy's cancel times out, and only then is the 502 written.
written_502 = threading.Event()


class RunawayAgent(BaseHTTPRequestHandler):
    """Accepts the turn as a task and works on it until tasks/cancel, as the 2026-10-31 turn did. It answers
    tasks/cancel only once the room's 502 is written, and records whether the 502 was written when the cancel came."""
    calls: list[dict] = []
    cancel_after_502: list[bool] = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        RunawayAgent.calls.append(body)
        if body.get("method") == "tasks/cancel":
            RunawayAgent.cancel_after_502.append(written_502.is_set())
            written_502.wait(CANCEL_HOLD_CEILING)
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
# _send is proxy.py's single response path for POST; the event marks the moment its 502 is on the client's socket.
check("the pinned proxy.py answers POST through Handler._send", callable(getattr(proxy.Handler, "_send", None)),
      "proxy.Handler has no _send, so this test cannot see when the 502 is written")
_proxy_send = proxy.Handler._send


def _send_and_mark(self, code, *args, **kwargs):
    _proxy_send(self, code, *args, **kwargs)
    if code == 502:
        written_502.set()


proxy.Handler._send = _send_and_mark

events: list[str] = []
messages: dict[str, str] = {}


class Events(logging.Handler):
    def emit(self, record):
        events.append(getattr(record, "event", ""))
        messages.setdefault(getattr(record, "event", ""), record.getMessage())


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
# Which limit ended the turn is read from the proxy's own forward_error line, not from the wall clock. A bound of
# PROXY_TIMEOUT + 1.5 s went red in run 17905's suite at 3.12 s on a host at load 18, and passed at 1.01 s on three
# reruns (#974): the poll's sleep and the handler thread run late on a loaded host, so no tight wall-clock bound
# holds there. The proxy names the limit it hit, "(PROXY_TIMEOUT)" or "(TURN_TIMEOUT)", in that line, which load
# cannot change. The wall clock is kept only as a bound on a hang, far under the client's own 30 s.
forward_msg = messages.get("forward_error", "")
check("the turn ends at PROXY_TIMEOUT, not at TURN_TIMEOUT",
      "forward deadline (PROXY_TIMEOUT) passed" in forward_msg and "TURN_TIMEOUT" not in forward_msg,
      f"forward_error said {forward_msg!r}")
check(f"the turn does not hang ({took:.2f}s, the client waits 30s)", took < 15)

deadline = time.monotonic() + 5
while time.monotonic() < deadline and not any(c.get("method") == "tasks/cancel" for c in RunawayAgent.calls):
    time.sleep(0.05)
cancels = [c for c in RunawayAgent.calls if c.get("method") == "tasks/cancel"]
check("the agent receives one tasks/cancel", len(cancels) == 1, f"methods {[c.get('method') for c in RunawayAgent.calls]}")
check("the cancel names the turn's task", bool(cancels) and cancels[0].get("params") == {"id": TASK},
      f"got {cancels[:1]}")
check("the 502 is written before the tasks/cancel reaches the agent",
      RunawayAgent.cancel_after_502 == [True],
      f"502 already written when each cancel came: {RunawayAgent.cancel_after_502}")
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
