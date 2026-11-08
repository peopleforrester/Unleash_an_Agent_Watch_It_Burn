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
- The input guards see the prompt only, never the name, and the /prompts feed's `prompts` list is the prompt alone.
- Since guard-proxy-agenticburn#59 (92fd19f, #1048) the feed carries each prompt's witch name in a `witches` list
  at the same index, for the prompt wall (#921); a pin before it has no `witches`. A turn with no usable name
  (none, empty, blank, null, not a string, or not shaped <First> the <Creature>) lands in the feed as its prompt
  with "" at that index.
- Since guard-proxy-agenticburn#64 (5a48d25, #995) the message/send of a named turn carries the name as an
  X-Witch-Name header too, which kagent copies onto workshop-mcp's calls; a turn with no name carries none, and a
  pin before it sends none.
- A /chat with no witch field, an empty or blank one, a non-string one or a misshaped one reaches the agent as the
  prompt alone.

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
WITCHES_FEED = "92fd19f599b4df53c51b0f0ac6a70d857dcd084c"  # guard-proxy-agenticburn#59: /prompts carries `witches`
WITCH_HEADER = "5a48d250e7021f54c17fd3403aed8dc123d176a6"  # guard-proxy-agenticburn#64: X-Witch-Name on the forward
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


def pin_contains(sha: str) -> bool:
    """Whether the pinned guard-proxy holds the commit. A commit the clone does not have fails the test rather
    than reading as an older pin."""
    has = subprocess.run(["git", "-C", str(SUB), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True)
    if has.returncode != 0:
        print(f"FAILED: guard-proxy commit {sha[:7]} is not in {SUB}; fetch it (git -C {SUB} fetch origin)")
        sys.exit(1)
    return subprocess.run(["git", "-C", str(SUB), "merge-base", "--is-ancestor", sha, pin_sha or "HEAD"],
                          capture_output=True).returncode == 0


has_witches_feed, has_witch_header = pin_contains(WITCHES_FEED), pin_contains(WITCH_HEADER)
print(f"  the pin {'holds' if has_witches_feed else 'predates'} #59's witches feed and "
      f"{'holds' if has_witch_header else 'predates'} #64's X-Witch-Name header")

first, creatures = js_array("WITCH_FIRST"), js_array("WITCH_CREATURES")
check(f"burritbot.html's witch vocabulary reads ({len(first)} first names, {len(creatures)} creatures)",
      bool(first) and bool(creatures))
check("the storefront still sends the name as the /chat body's witch field",
      "body:JSON.stringify({prompt:v,session:getSession(),witch:WITCH_NAME})" in PAGE)


class Agent(BaseHTTPRequestHandler):
    """Answers message/send with a finished task, as kagent does for a short turn, and keeps every message."""
    messages: list[dict] = []
    headers: list[dict] = []  # each message/send's request headers, at the same index as messages

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if body.get("method") != "message/send":
            self.send_response(400)
            self.end_headers()
            return
        Agent.messages.append(body["params"]["message"])
        Agent.headers.append({k.lower(): v for k, v in self.headers.items()})
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


def chat(body: dict) -> tuple[int, dict, dict | None, dict]:
    """POST one /chat turn, each under its own session (the Deployment's 10/min per conversation stays out of it).
    Returns the status, the reply, the message the agent received (None when none reached it) and its headers."""
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
    reached = len(Agent.messages) > before
    return status, reply, (Agent.messages[before] if reached else None), (Agent.headers[before] if reached else {})


def texts(message: dict | None) -> list[tuple[str, str]]:
    return [(p.get("kind"), p.get("text")) for p in (message or {}).get("parts", [])]


print("== a /chat with the storefront's witch name ==")
names = [f"{first[i % len(first)]} the {creatures[i % len(creatures)]}" for i in range(max(len(first), len(creatures)))]
sent = {}
for name in names:
    sent[name] = chat({"prompt": PROMPT, "witch": name})
status, reply, message, _ = sent[names[0]]
parts = texts(message)
check(f"{names[0]!r}: the visitor gets the agent's reply", status == 200 and reply.get("reply") == REPLY,
      f"got {status} {reply}")
check(f"{names[0]!r}: the agent receives two text parts", len(parts) == 2 and all(k == "text" for k, _ in parts),
      f"parts {parts}")
check(f"{names[0]!r}: the first part is the prompt as typed", parts[:1] == [("text", PROMPT)], f"parts {parts}")
check(f"{names[0]!r}: the second part carries the name", len(parts) == 2 and names[0] in (parts[1][1] or ""),
      f"parts {parts}")
dropped = [n for n, (_, _, m, _) in sent.items()
           if texts(m)[:1] != [("text", PROMPT)] or len(texts(m)) != 2 or n not in (texts(m)[1][1] or "")]
check(f"every first name and creature the storefront assigns is forwarded ({len(names)} names, "
      f"{len(dropped)} not)", not dropped, f"not forwarded: {dropped[:5]}")
check("no input guard scans the name, each scans the prompt",
      bool(scanned) and all(t == PROMPT for t in scanned), f"scanned {sorted(set(scanned))[:5]}")
if has_witch_header:
    wrong = [n for n, (_, _, _, h) in sent.items() if h.get("x-witch-name") != n]
    check(f"each named turn's message/send carries X-Witch-Name equal to its name ({len(wrong)} of {len(names)} not)",
          not wrong, f"not carried: {wrong[:5]}")
else:
    carried = [n for n, (_, _, _, h) in sent.items() if "x-witch-name" in h]
    check("a pin before #64 sends no X-Witch-Name header", not carried, f"carried: {carried[:5]}")
with urllib.request.urlopen(f"{BASE}/prompts", timeout=10) as r:
    raw_feed = r.read().decode("utf-8", "replace")
try:
    feed = json.loads(raw_feed)
except ValueError:
    feed = {}
prompts = feed.get("prompts") or []
check("the /prompts feed shows the prompt", any("bean burrito" in str(t) for t in prompts), raw_feed[:200])
check("the /prompts feed's prompts carry no witch name",
      all(isinstance(t, str) for t in prompts) and not any(n in t for n in names for t in prompts), raw_feed[:200])
if has_witches_feed:
    witches = feed.get("witches")
    check(f"the feed's witches list is as long as its prompts ({len(witches or [])} and {len(prompts)})",
          isinstance(witches, list) and len(witches) == len(prompts), raw_feed[:200])
    check(f"the feed names each of the {len(names)} turns' witch at its prompt's index",
          isinstance(witches, list) and witches[-len(names):] == names, f"witches {(witches or [])[-5:]}")
else:
    check("a pin before #59 has no witches list in the feed", "witches" not in feed, raw_feed[:200])

print("== a /chat with no witch name reaches the agent as the prompt alone ==")
NO_NAME = [("no witch field", {"prompt": PROMPT}),
           ("an empty witch", {"prompt": PROMPT, "witch": ""}),
           ("a blank witch", {"prompt": PROMPT, "witch": "   "}),
           ("a null witch", {"prompt": PROMPT, "witch": None}),
           ("a non-string witch", {"prompt": PROMPT, "witch": {"name": names[0]}}),
           ("a witch not shaped <First> the <Creature>", {"prompt": PROMPT, "witch": "Bob"})]
for label, body in NO_NAME:
    status, reply, message, headers = chat(body)
    check(f"{label}: the visitor gets the agent's reply", status == 200 and reply.get("reply") == REPLY,
          f"got {status} {reply}")
    check(f"{label}: the agent receives exactly the prompt", texts(message) == [("text", PROMPT)],
          f"parts {texts(message)}")
    check(f"{label}: the message/send carries no X-Witch-Name header", "x-witch-name" not in headers,
          f"headers {headers}")

if has_witches_feed:
    # #921's no-name case: the wall shows "someone who gave no name" for a "" entry, so each of these turns has to
    # land in the feed as its prompt with "" at the same index, never as a stale or neighbouring name. A shaped
    # name that moderation would mask is the last of them: it still reaches the agent, but the projected wall
    # drops it whole. The name is checked against the pinned moderator first, so a changed wordlist reads as that.
    MASKED = "Bastard the Ghoul"
    check(f"the pinned moderator masks {MASKED!r} and the shape check passes it",
          proxy.moderate(MASKED) != MASKED and bool(proxy._WITCH_NAME_RE.fullmatch(MASKED)),
          f"moderate gave {proxy.moderate(MASKED)!r}")
    status, _, message, _ = chat({"prompt": PROMPT, "witch": MASKED})
    check(f"{MASKED!r}: the agent still receives the name", status == 200 and len(texts(message)) == 2,
          f"got {status}, parts {texts(message)}")
    NO_NAME.append(("a name moderation would mask", {"prompt": PROMPT, "witch": MASKED}))
    with urllib.request.urlopen(f"{BASE}/prompts", timeout=10) as r:
        raw_feed = r.read().decode("utf-8", "replace")
    try:
        feed = json.loads(raw_feed)
    except ValueError:
        feed = {}
    prompts, witches = feed.get("prompts") or [], feed.get("witches")
    n = len(NO_NAME)
    check(f"after the {n} turns with no usable name, the witches list is still as long as the prompts",
          isinstance(witches, list) and len(witches) == len(prompts), raw_feed[:200])
    check(f"the feed keeps each of the {n} no-name turns' prompt as typed", prompts[-n:] == [PROMPT] * n,
          f"prompts {prompts[-n:]}")
    check(f"the feed gives each of the {n} no-name turns \"\" as its witch name",
          isinstance(witches, list) and witches[-n:] == [""] * n, f"witches {(witches or [])[-n:]}")
    check("the named turns before them keep their names in the feed",
          isinstance(witches, list) and witches[-n - len(names):-n] == names,
          f"witches {(witches or [])[-n - 3:-n]}")

proxy_srv.shutdown()
agent_srv.shutdown()
if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll /chat witch-name forwarding checks passed.")
