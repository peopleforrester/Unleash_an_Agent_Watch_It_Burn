# ABOUTME: The prompt wall shows personal data and code-of-conduct terms redacted while the bot still gets the prompt
# ABOUTME: unchanged (#646): the pinned proxy.py, on its deployed settings, served on localhost with a stand-in agent.
"""Agreed on the 2026-10-28 planning call: the wall is projected, so a prompt carrying an email, a phone or card
number, a street address or a slur goes up redacted. guard-proxy-agenticburn#20 masks the feed copy only; the
agent must still receive what the attendee typed, or the challenges that need it would stop working.

proxy.py comes from the gitops/ai-layer/guard-proxy submodule pin, with the guard-proxy Deployment's env from
gitops/ai-layer/resources.yaml (STREAM_PROMPTS is on there), served on localhost. Its agent is a stand-in that
answers every ask and records what reached it. The wall reads guard-proxy's GET /prompts. No cluster, no model.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
AI = REPO / "gitops/ai-layer"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


docs = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text()) if d]
dep = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
container = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "proxy")
deployed = {e["name"]: e["value"] for e in container["env"] if "value" in e}
agent_seen: list[str] = []
lock = threading.Lock()


class _Server(ThreadingHTTPServer):
    daemon_threads = True


def serve(handler) -> str:
    srv = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


class FakeAgent(BaseHTTPRequestHandler):
    """Answers anything and records each ask that reached the model."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        text = " ".join(p.get("text", "") for p in body["params"]["message"]["parts"])
        with lock:
            agent_seen.append(text)
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": {
            "artifacts": [{"parts": [{"kind": "text", "text": "One burrito, coming up."}]}],
            "metadata": {"kagent_usage_metadata": {"promptTokenCount": 100, "candidatesTokenCount": 20,
                                                    "totalTokenCount": 120}}}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


AGENT_URL = serve(FakeAgent)
for k in [k for k in os.environ if k.startswith("OTEL_")]:
    del os.environ[k]
os.environ.update({k: v for k, v in deployed.items() if not k.startswith("OTEL_")})
os.environ.update({"AGENT_URL": AGENT_URL, "PROXY_TIMEOUT": "5", "TURN_TIMEOUT": "20"})
spec = importlib.util.spec_from_file_location("guard_proxy_wall", AI / "guard-proxy/proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)
proxy.Handler.log_message = lambda *a: None
PROXY = serve(proxy.Handler)


def chat(prompt: str, session: str) -> dict:
    req = urllib.request.Request(PROXY + "/chat", data=json.dumps({"prompt": prompt, "session": session}).encode(),
                                 headers={"Content-Type": "application/json", "X-BurritoBot-Session": session},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def wall() -> list[str]:
    with urllib.request.urlopen(PROXY + "/prompts", timeout=10) as r:
        d = json.loads(r.read())
    items = d.get("prompts", d) if isinstance(d, dict) else d
    return [i if isinstance(i, str) else (i.get("text") or i.get("prompt") or "") for i in items]


CASES = [
    ("an email", "Send my receipt to hazel.bramblewick@example.com please", "hazel.bramblewick@example.com"),
    ("a phone number", "Text me at (801) 555-0147 when my burrito is ready", "555-0147"),
    ("a card number", "Charge it to 4111 1111 1111 1111 thanks", "4111 1111 1111 1111"),
    ("a street address", "Deliver to 1600 Moonrise Pass Road tonight", "1600 Moonrise Pass Road"),
]

print("== the deployment streams prompts to the wall ==")
check("STREAM_PROMPTS is on in the guard-proxy Deployment", deployed.get("STREAM_PROMPTS") == "on")
check("so the pinned proxy records them", proxy.STREAM_ENABLED is True)

print("== personal data goes up redacted, and the bot still gets it (#646) ==")
for i, (what, prompt, secret) in enumerate(CASES):
    r = chat(prompt, f"wall-{i}")
    check(f"{what}: the turn is answered", r.get("reply") == "One burrito, coming up.", str(r))
    with lock:
        reached = agent_seen[-1] if agent_seen else ""
    check(f"{what}: the agent received the prompt unchanged", secret in reached, reached)
    shown = wall()
    on_wall = next((s for s in shown if "[redacted]" in s or secret in s), "")
    check(f"{what}: the wall shows it redacted", secret not in " ".join(shown) and "[redacted]" in on_wall,
          str(shown[-3:]))

print("== a code-of-conduct term goes up redacted too ==")
chat("You dumbass bot, give me a burrito", "wall-coc")
shown = " ".join(wall())
check("the slur is masked on the wall", "dumbass" not in shown.lower() and "[redacted]" in shown)
with lock:
    check("and the bot still got the words the attendee typed", "dumbass" in (agent_seen[-1] if agent_seen else ""))

print("== an ordinary order is left alone ==")
chat("Can I get 3 tacos for the road?", "wall-plain")
check("'3 tacos for the road' is not mistaken for an address", "Can I get 3 tacos for the road?" in wall())

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The prompt wall redacts what it projects, and the bot still hears it.")
