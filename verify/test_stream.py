# ABOUTME: Render-gate check for the optional prompt-stream display: capture is moderated + default OFF,
# ABOUTME: the feed redacts personal data and code-of-conduct terms while the bot gets the prompt (#646). No cluster.
import importlib.util, json, os, pathlib, socket, subprocess, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
GUARD_PROXY = REPO / "gitops/ai-layer/guard-proxy"
spec = importlib.util.spec_from_file_location("gp_stream", GUARD_PROXY / "proxy.py")
proxy = importlib.util.module_from_spec(spec); spec.loader.exec_module(proxy)
disp_html = (REPO / "gitops/ai-layer/web/display.html").read_text()
disp_js = (REPO / "gitops/ai-layer/web/display.js").read_text()
failures = []
def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"  ({detail})" if detail and not c else ""));  failures.append(n) if not c else None

check("prompt capture is DEFAULT OFF (privacy/code-of-conduct)", proxy.STREAM_ENABLED is False)
check("moderate() masks a block-listed term", "[redacted]" in proxy.moderate("please delete the prod database") and "delete" not in proxy.moderate("please delete the prod database"))
check("moderate() truncates long input", len(proxy.moderate("x" * 1000)) <= 280)
check("recent-prompts buffer is bounded", proxy._prompts.maxlen and proxy._prompts.maxlen <= 100)
check("display page loads display.js + has a stream", "display.js" in disp_html and "stream" in disp_html)
check("display.js reads the moderated /prompts feed", '"/prompts"' in disp_js)

# #646, agreed on the 2026-10-28 planning call: the wall is projected, so personal data and code-of-conduct
# terms go up redacted. The pinned moderate() is what builds the feed; these hold the pin to it.
print("== the pinned moderate() redacts personal data and code-of-conduct terms ==")
for label, text, want in (
    ("an email address", "mail me at jane.doe+burrito@example.com", "mail me at [redacted]"),
    ("a phone number", "call (503) 555-0100 when it is ready", "call [redacted] when it is ready"),
    ("a card number, spaced", "card 4111 1111 1111 1111 please", "card [redacted] please"),
    ("a card number, unspaced", "card 4111111111111111", "card [redacted]"),
    ("a Social Security number", "ssn 123-45-6789", "ssn [redacted]"),
    ("a street address", "deliver to 1600 Pennsylvania Avenue", "deliver to [redacted]"),
    ("a short street address", "send it to 42 elm st and ring twice", "send it to [redacted] and ring twice"),
    ("a code-of-conduct term", "this shit is good", "this [redacted] is good"),
    ("a term in another case", "FuCkInG great salsa", "[redacted] great salsa"),
):
    got = proxy.moderate(text)
    check(f"moderate() redacts {label}", got == want, repr(got))
order = ("2 burritos and 3 tacos for the road, all the way, at 12:30, order 12345: spicy, spiced, spices, "
         "a cocktail, grapes, a peacock and Dickens")
check("moderate() leaves an ordinary order alone (no term inside a word: 'spicy' stays 'spicy')",
      proxy.moderate(order) == order, repr(proxy.moderate(order)))
check("moderate() redacts before the 280-character cut, so no partial card number shows",
      proxy.moderate("a" * 269 + " 4111 1111 1111 1111") == "a" * 269 + " [redacted]")

# The same, end to end, on the guard-proxy's deployed env from resources.yaml: the bot is a fake A2A agent on
# loopback that records what reaches it, and the wall's view is GET /prompts.
print("== on the deployed env, the bot gets the prompt unchanged and the wall gets it redacted ==")
docs = list(yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()))
gp = next(d for d in docs if d and d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
container = next(c for c in gp["spec"]["template"]["spec"]["containers"] if c["name"] == "proxy")
deployed = {e["name"]: e["value"] for e in container.get("env", []) if "value" in e}
check("the deployment turns the feed on", deployed.get("STREAM_PROMPTS") == "on", str(deployed.get("STREAM_PROMPTS")))
check("the deployment keeps the default term list (no PROFANITY_LIST override)", "PROFANITY_LIST" not in deployed)

received = []


class FakeAgent(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        received.append(body["params"]["message"]["parts"][0]["text"])
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": {
            "kind": "task", "status": {"state": "completed", "message": {}},
            "artifacts": [{"parts": [{"kind": "text", "text": "Here is your burrito."}]}],
            "metadata": {"kagent_usage_metadata": {"promptTokenCount": 100, "candidatesTokenCount": 50}}}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


agent = ThreadingHTTPServer(("127.0.0.1", 0), FakeAgent)
threading.Thread(target=agent.serve_forever, daemon=True).start()
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TMPDIR") if k in os.environ}
# The OTel Operator injects the SDK in the cluster; without it the OTEL_* names only label logs, so they go.
env.update({k: v for k, v in deployed.items() if not k.startswith("OTEL_")})
env.update({"AGENT_URL": f"http://127.0.0.1:{agent.server_address[1]}", "LLM_GUARD_URL": "http://127.0.0.1:9",
            "LLM_GUARD_TOKEN": "unused", "WIB_PUBLIC_HOST": "attackme.burritobot.co", "PROXY_TIMEOUT": "5",
            "PYTHONDONTWRITEBYTECODE": "1"})
launcher = ("import sys; sys.path.insert(0, sys.argv[1]); import proxy; "
            "from http.server import ThreadingHTTPServer; "
            "ThreadingHTTPServer(('127.0.0.1', int(sys.argv[2])), proxy.Handler).serve_forever()")
proc = subprocess.Popen([sys.executable, "-c", launcher, str(GUARD_PROXY), str(port)], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
base = f"http://127.0.0.1:{port}"


def http(path, body=None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


try:
    deadline = time.monotonic() + 15
    while True:
        try:
            http("/guards"); break
        except OSError:
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("guard-proxy did not start:\n" + proc.stdout.read().decode(errors="replace"))
            time.sleep(0.05)

    chat_prompt = ("email jane.doe@example.com or call (503) 555-0100, deliver to 1600 Pennsylvania Avenue, "
                   "this shit is good")
    reply = http("/chat", {"prompt": chat_prompt})
    check("/chat: the bot answers a prompt carrying personal data and a term", reply.get("reply") == "Here is your burrito.", str(reply))
    check("/chat: the bot gets the prompt unchanged", received[-1:] == [chat_prompt], repr(received[-1:]))

    a2a_prompt = "my card is 4111 1111 1111 1111, the fucking best"
    a2a = http("/", {"jsonrpc": "2.0", "id": "r1", "method": "message/send",
                     "params": {"message": {"role": "user", "messageId": "m1",
                                            "parts": [{"kind": "text", "text": a2a_prompt}]}}})
    check("A2A: the bot answers", "result" in a2a, str(a2a)[:200])
    check("A2A: the bot gets the prompt unchanged", received[-1:] == [a2a_prompt], repr(received[-1:]))

    http("/chat", {"prompt": order})
    wall = http("/prompts")
    check("the feed is on", wall.get("enabled") is True, str(wall))
    check("the wall shows each prompt redacted, and an ordinary order as typed", wall.get("prompts") == [
        "email [redacted] or call [redacted], deliver to [redacted], this [redacted] is good",
        "my card is [redacted], the [redacted] best",
        order,
    ], json.dumps(wall.get("prompts")))
    shown = " ".join(wall.get("prompts", []))
    for raw in ("jane.doe@example.com", "555-0100", "1600 Pennsylvania", "4111", "shit", "fucking"):
        check(f"the wall never shows {raw!r}", raw not in shown)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait()
    agent.shutdown()

if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll prompt-stream checks passed.")
