# ABOUTME: The on-topic guard in the running path (#504, from #455): the pinned proxy.py, on its deployed settings,
# ABOUTME: refuses every off-topic ask and passes every on-topic one once guard-topic-on flips it, on /chat and on A2A.
"""BurritoBot ends selling burritos only, checked against guard-proxy itself rather than the test's own rule.

verify/test_topic_guard.py holds the deployed phrase lists to verify/topic_cases.py's copy of the rule. This file
runs the real thing: proxy.py from the gitops/ai-layer/guard-proxy submodule pin, with the guard-proxy
Deployment's env from gitops/ai-layer/resources.yaml, served on localhost. Its two upstreams are stand-ins: an
A2A agent that answers every ask and records what reached it, and an LLM Guard whose BanTopics refuses the
off-topic paraphrases the phrase step leaves to it. The real classifier's scores are judged by
verify/test_topic_classifier.py (E2E suite); what is judged here is that the proxy asks it, asks it alone, and
acts on its answer.

The guard is flipped the way the room sees it flipped: the web terminal's own guard-topic-on and guard-topic-off,
taken from web-terminal/entrypoint.sh, with a stub kubectl whose `exec deploy/guard-proxy` runs the helper's
python against this proxy. No cluster, no model.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import topic_cases as tc  # noqa: E402

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
REFUSAL = deployed["TOPIC_REFUSAL"]
OFF = tc.split_list(deployed["TOPIC_OFF_LIST"])
ON = tc.split_list(deployed["TOPIC_ON_LIST"])
# The off-topic paraphrases no phrase catches: the deployed proxy hands these to BanTopics.
TO_CLASSIFIER = {a for a in tc.OFF_TOPIC if tc.phrase_verdict(a, OFF, ON) is None}
TOKEN = "witb-topic-test-token"


class _Server(ThreadingHTTPServer):
    daemon_threads = True


def serve(handler) -> tuple[ThreadingHTTPServer, str]:
    srv = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


AGENT_REPLY = "The carnitas burrito is slow-braised pork with Cilantro-Slime Rice."
agent_seen: list[str] = []
guard_seen: list[dict] = []
guard_state = {"fail": False}
lock = threading.Lock()


class FakeAgent(BaseHTTPRequestHandler):
    """Answers anything, the way the wide-open bot does, and records each ask that reached the model."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        text = " ".join(p.get("text", "") for p in body["params"]["message"]["parts"])
        with lock:
            agent_seen.append(text)
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": {
            "artifacts": [{"parts": [{"kind": "text", "text": AGENT_REPLY}]}],
            "metadata": {"kagent_usage_metadata": {"promptTokenCount": 120, "candidatesTokenCount": 40,
                                                    "totalTokenCount": 160}}}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class FakeLLMGuard(BaseHTTPRequestHandler):
    """/analyze/prompt with BanTopics as the only live scanner: invalid for an off-topic paraphrase, valid otherwise."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        with lock:
            guard_seen.append({"path": self.path, "auth": self.headers.get("Authorization"), **body})
        if guard_state["fail"]:
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        bans = "BanTopics" not in (body.get("scanners_suppress") or [])
        valid = not (bans and body.get("prompt") in TO_CLASSIFIER)
        out = json.dumps({"is_valid": valid, "scanners": {"BanTopics": 0.0 if valid else 0.97}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


_, AGENT_URL = serve(FakeAgent)
_, GUARD_URL = serve(FakeLLMGuard)

# The proxy reads its settings at import, so its environment is the Deployment's, with the two upstreams and the
# token swapped for the stand-ins'. No OTel exporter is configured, so it sends no telemetry anywhere.
for k in [k for k in os.environ if k.startswith("OTEL_")]:
    del os.environ[k]
os.environ.update({k: v for k, v in deployed.items() if not k.startswith("OTEL_")})
os.environ.update({"AGENT_URL": AGENT_URL, "LLM_GUARD_URL": GUARD_URL, "LLM_GUARD_TOKEN": TOKEN,
                   "PROXY_TIMEOUT": "5"})
# Its guard-decision log lines are kept for the checks rather than printed: proxy.py adds its own stream handler
# only to a logger that has none.
events: list[dict] = []


class _Events(logging.Handler):
    def emit(self, record):
        with lock:
            events.append({"event": getattr(record, "event", None), "step": getattr(record, "step", None)})


_log = logging.getLogger("guard-proxy")
_log.addHandler(_Events())
_log.setLevel(logging.INFO)
_log.propagate = False
spec = importlib.util.spec_from_file_location("guard_proxy_topic", AI / "guard-proxy/proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)
_, PROXY = serve(proxy.Handler)


def post(path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(PROXY + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def guards() -> dict:
    with urllib.request.urlopen(PROXY + "/guards", timeout=10) as r:
        return json.loads(r.read())


def turn(prompt: str) -> tuple[dict, list[str], list[dict]]:
    """One storefront turn: the /chat answer, then what reached the agent and LLM Guard because of it."""
    with lock:
        a0, g0, e0 = len(agent_seen), len(guard_seen), len(events)
    _, reply = post("/chat", {"prompt": prompt})
    with lock:
        reply["_topic_events"] = [e for e in events[e0:] if e["event"] == "topic_guard_block"]
        return reply, agent_seen[a0:], guard_seen[g0:]


def a2a(prompt: str) -> tuple[int, dict, list[str]]:
    with lock:
        a0 = len(agent_seen)
    code, body = post("/", {"jsonrpc": "2.0", "id": "t1", "method": "message/send", "params": {"message": {
        "role": "user", "messageId": "m1", "parts": [{"kind": "text", "text": prompt}]}}})
    with lock:
        return code, body, agent_seen[a0:]


# The terminal helpers, as entrypoint.sh writes them, against a kubectl that runs `exec deploy/guard-proxy`'s
# python here, pointed at this proxy instead of the pod's localhost:8080.
terminal = (AI / "web-terminal/entrypoint.sh").read_text()


def heredoc(name: str) -> str:
    return terminal.split(f'cat > "$HOME/{name}" <<\'EOS\'\n', 1)[1].split("\nEOS\n", 1)[0] + "\n"


work = pathlib.Path(tempfile.mkdtemp(prefix="topic-guard-"))
(work / "bin").mkdir()
for name in (".guardlib", "guard-topic-on", "guard-topic-off"):
    (work / name).write_text(heredoc(name))
(work / "bin/kubectl").write_text(f"""#!{sys.executable}
import subprocess, sys
a = sys.argv[1:]
if a[:4] != ["-n", "agent", "exec", "deploy/guard-proxy"] or a[4:7] != ["--", "python3", "-c"]:
    sys.exit("stub kubectl: only exec deploy/guard-proxy -- python3 -c is answered here: " + " ".join(a))
sys.exit(subprocess.call([sys.executable, "-c", a[7].replace("http://localhost:8080", {PROXY!r})]))
""")
(work / "bin/kubectl").chmod(0o755)


def helper(name: str) -> subprocess.CompletedProcess:
    env = {"PATH": f"{work / 'bin'}:{os.environ['PATH']}", "HOME": str(work)}
    return subprocess.run(["bash", str(work / name)], env=env, capture_output=True, text=True, timeout=30)


print("== the wide-open start: the guard is off and BurritoBot answers anything ==")
check("guard-proxy starts with the on-topic guard off", guards().get("topic") is False, json.dumps(guards()))
for ask in tc.CANONICAL_OFF:
    reply, to_agent, _ = turn(ask)
    check(f"guard off: the off-topic ask reaches the model: {ask!r}",
          to_agent == [ask] and reply.get("reply") == AGENT_REPLY and reply.get("guarded") is False, json.dumps(reply))

print("== guard-topic-on flips the proxy's guard ==")
on = helper("guard-topic-on")
check("guard-topic-on succeeds against this proxy", on.returncode == 0, on.stdout + on.stderr)
check("and says the on-topic guard is on", "On-topic guard ON" in on.stdout, on.stdout)
check("the proxy now reports the on-topic guard on", guards().get("topic") is True, json.dumps(guards()))

print("== /chat refuses every off-topic ask, before the model ==")
for ask in tc.OFF_TOPIC:
    reply, to_agent, to_guard = turn(ask)
    check(f"refused with the deployed TOPIC_REFUSAL: {ask!r}",
          reply.get("reply") == REFUSAL and reply.get("guarded") is True, json.dumps(reply))
    check(f"  and it spends no tokens and never reaches the model: {ask!r}",
          to_agent == [] and reply.get("input_tokens") == 0 and reply.get("output_tokens") == 0, f"agent saw {to_agent}")
    if ask in TO_CLASSIFIER:
        check(f"  decided by BanTopics alone, with the injection scanner suppressed: {ask!r}",
              len(to_guard) == 1 and to_guard[0]["path"] == "/analyze/prompt" and to_guard[0].get("prompt") == ask
              and to_guard[0].get("scanners_suppress") == ["PromptInjection"]
              and to_guard[0].get("auth") == f"Bearer {TOKEN}", json.dumps(to_guard))
    else:
        check(f"  decided on an off phrase, with no classifier call: {ask!r}", to_guard == [], json.dumps(to_guard))
    step = "classifier" if ask in TO_CLASSIFIER else "off_phrase"
    check(f"  logged as topic_guard_block with step {step}: {ask!r}",
          reply["_topic_events"] == [{"event": "topic_guard_block", "step": step}], json.dumps(reply["_topic_events"]))
for ask in tc.CANONICAL_OFF:
    check(f"the canonical off-topic ask never depends on a model score: {ask!r}", ask not in TO_CLASSIFIER)
check("some refusals came from the classifier step, so the proxy's classifier path was exercised",
      len(TO_CLASSIFIER) >= 5, f"{len(TO_CLASSIFIER)} asks reached it")

print("== /chat passes every on-topic ask to the model ==")
for ask in tc.ON_TOPIC:
    reply, to_agent, to_guard = turn(ask)
    check(f"answered by the model on a phrase, no classifier call: {ask!r}",
          to_agent == [ask] and reply.get("reply") == AGENT_REPLY and reply.get("guarded") is False
          and to_guard == [] and reply["_topic_events"] == [], json.dumps(reply))
for ask in tc.VAGUE_ON_TOPIC:
    reply, to_agent, to_guard = turn(ask)
    check(f"a vague ask the classifier passes reaches the model: {ask!r}",
          to_agent == [ask] and reply.get("reply") == AGENT_REPLY and len(to_guard) == 1, json.dumps(reply))

print("== the A2A path holds the same line ==")
code, body, to_agent = a2a(tc.CANONICAL_OFF[0])
check("an off-topic A2A message is refused 403 with the deployed TOPIC_REFUSAL, before the model",
      code == 403 and body.get("error", {}).get("message") == REFUSAL and to_agent == [], f"{code} {json.dumps(body)}")
code, body, to_agent = a2a(tc.CANONICAL_ON[0])
check("an on-topic A2A message is forwarded to the model", code == 200 and to_agent == [tc.CANONICAL_ON[0]],
      f"{code} {json.dumps(body)}")

print("== a classifier outage fails closed, as the Deployment sets ==")
check("the Deployment sets PROXY_FAIL_CLOSED=true", deployed.get("PROXY_FAIL_CLOSED") == "true")
guard_state["fail"] = True
ask = sorted(TO_CLASSIFIER)[0]
reply, to_agent, _ = turn(ask)
check(f"with LLM Guard answering 500, an ask left to the classifier is refused: {ask!r}",
      reply.get("reply") == REFUSAL and to_agent == [], json.dumps(reply))
reply, to_agent, _ = turn(tc.CANONICAL_ON[0])
check("and an on-topic ask still passes on its phrase", to_agent == [tc.CANONICAL_ON[0]], json.dumps(reply))
guard_state["fail"] = False

print("== guard-topic-off opens it again ==")
off = helper("guard-topic-off")
check("guard-topic-off succeeds and says the guard is off", off.returncode == 0 and "On-topic guard OFF" in off.stdout,
      off.stdout + off.stderr)
check("the proxy reports the on-topic guard off", guards().get("topic") is False, json.dumps(guards()))
reply, to_agent, _ = turn(tc.CANONICAL_OFF[0])
check("an off-topic ask reaches the model again", to_agent == [tc.CANONICAL_OFF[0]], json.dumps(reply))

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nguard-proxy sells burritos only once the on-topic guard is on")
