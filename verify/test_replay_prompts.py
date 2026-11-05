# ABOUTME: Offline checks for the KubeCon recorded fallback (#452): the prompt set, the replay script driven against the
# ABOUTME: real guard-proxy /chat handler on loopback, the asset checker, the deck, the capture script and the run-of-show.
"""No cluster and no internet: everything here listens on 127.0.0.1.

The replay's whole job is to stop at the first prompt that did not reach the bot. Most of the ways that
happens come back from guard-proxy as an HTTP 200 with a canned reply (its rate limit, its cost cap), so a
replay that only checked the status code would carry on through a full window and report success. These
checks run guard-proxy's own Handler (gitops/ai-layer/guard-proxy/proxy.py, the code the clusters run) in
front of a stub agent, provoke each refusal for real, and check the replay stops on it. If proxy.py's words
change, this fails here and not in the ballroom.
"""
from __future__ import annotations

import html
import importlib.util
import json
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
FALLBACK = REPO / "facilitation/kubecon-na-2026/fallback"
REPLAY_PY = REPO / "scripts/replay-prompts.py"
ASSETS_PY = REPO / "scripts/check-fallback-assets.py"
CAPTURE_PY = REPO / "scripts/capture-fallback-screenshots.py"
RUN_OF_SHOW = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
KUBECON = (REPO / "gitops/ai-layer/web/kubecon.html").read_text(encoding="utf-8")
RESOURCES = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
CONSOLE_CONF = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses look their module up here while the class is being built
    spec.loader.exec_module(mod)
    return mod


rp = load_module("replay_prompts", REPLAY_PY)
cfa = load_module("check_fallback_assets", ASSETS_PY)
proxy = load_module("gp_replay", REPO / "gitops/ai-layer/guard-proxy/proxy.py")
cap = load_module("capture_fallback", CAPTURE_PY)


def room_prompts() -> list[tuple[int, str]]:
    """(segment, prompt) for every prompt on /kubecon, the page the presenters drive from, in page order."""
    beats = re.findall(r'<article class="beat" data-beat="[^"]+" data-segment="(\d)">(.*?)</article>', KUBECON, re.S)
    if not beats:
        print(f"FAILED: no <article class=\"beat\" data-segment=...> blocks in {REPO / 'gitops/ai-layer/web/kubecon.html'}")
        sys.exit(1)
    return [(int(seg), html.unescape(text))
            for seg, body in beats
            for text in re.findall(r'<div class="prompt" onclick="cp\(this\)">(.*?)<button', body, re.S)]


# ---------------------------------------------------------------------------------------------------------
print("the prompt set")
prompts = rp.load_prompts(rp.DEFAULT_PROMPTS)
by_tag = {t: [p for p in prompts if t in p.tags] for t in rp.TAGS}
check("prompts.yaml loads under the replay's own rules", len(prompts) >= 8, f"{len(prompts)} prompts")
for tag in sorted(rp.TAGS):
    check(f"at least one prompt is tagged {tag}", bool(by_tag[tag]))
check("the smoke selection is exactly one prompt (the E2E check sends only it)", len(by_tag["smoke"]) == 1)
check("the smoke prompt is on-topic, so it proves the bot answers as the chain",
      all("on-topic" in p.tags for p in by_tag["smoke"]))
page = room_prompts()
page_pairs = {(seg, text) for seg, text in page}
set_pairs = {(seg, p.prompt) for p in prompts for seg in p.segments}
check("every room prompt on /kubecon is in the set, under the segment the page shows it in",
      page_pairs <= set_pairs, f"missing {sorted(page_pairs - set_pairs)}")
check("every prompt in the set is on /kubecon, word for word, in each segment it claims",
      set_pairs <= page_pairs, f"not on the page {sorted(set_pairs - page_pairs)}")
for seg in sorted(rp.SEGMENTS):
    check(f"segment {seg} has prompts to replay", any(seg in p.segments for p in prompts))
check("segment 1's replay is the order and the off-topic asks: nothing in it reads a Secret or deploys",
      all(set(p.tags) <= {"on-topic", "off-topic", "smoke"} for p in rp.select(prompts, [], [], [1])))
check("segment 6 re-sends segment 1's off-topic asks, for the on-topic guard",
      [p.id for p in rp.select(prompts, [], [], [6])] == [p.id for p in rp.select(prompts, ["off-topic"], [], [1])])
for p in prompts:
    if p.marker:
        m = re.search(r'data-beat="[^"]+" data-segment="\d">(?:(?!</article>).)*?' + re.escape(html.escape(p.prompt, quote=False))
                      + r'(.*?)</article>', KUBECON, re.S)
        check(f"{p.id}'s marker is the success marker /kubecon gives for it",
              bool(m) and p.marker in html.unescape(m.group(1)))
threads = {}
for p in prompts:
    if p.thread:
        threads.setdefault(p.thread, []).append(p.id)
check("Challenge 2's Tron ask and its follow-up are one thread, in that order",
      threads.get("c2") == ["c2-tron", "c2-tron-public-image"], str(threads))
check("the replay's witch name is one guard-proxy keeps", bool(proxy._WITCH_NAME_RE.fullmatch(rp.DEFAULT_WITCH)))
check("the replay's witch-name rule is guard-proxy's", rp.WITCH_NAME_RE == proxy._WITCH_NAME_RE.pattern)


def rejects(body: str, fragment: str) -> bool:
    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / "p.yaml"
        path.write_text(body, encoding="utf-8")
        try:
            rp.load_prompts(path)
        except rp.PromptSetError as exc:
            return fragment in str(exc)
    return False


GOOD = "  - {id: a, segments: [1], tags: [on-topic], prompt: hello, expect: a reply}\n"
HEAD = "version: 1\nprompts:\n"
check("a duplicate id is refused", rejects(HEAD + GOOD + GOOD, "duplicate id"))
check("an unknown tag is refused", rejects(HEAD + "  - {id: a, segments: [1], tags: [spicy], prompt: x, expect: y}\n", "tags must"))
check("a prompt with no segments is refused", rejects(HEAD + "  - {id: a, tags: [smoke], prompt: x, expect: y}\n", "segments must"))
check("a segment the run-of-show does not have is refused",
      rejects(HEAD + "  - {id: a, segments: [7], tags: [smoke], prompt: x, expect: y}\n", "segments must"))
check("a prompt with no expect is refused", rejects(HEAD + "  - {id: a, segments: [1], tags: [smoke], prompt: x}\n", "expect is empty"))
check("an unknown field is refused (a typo'd marker would otherwise vanish)",
      rejects(HEAD + "  - {id: a, segments: [1], tags: [smoke], prompt: x, expect: y, markr: z}\n", "unknown field"))
check("a thread that is not a lower-case word is refused",
      rejects(HEAD + "  - {id: a, segments: [1], tags: [smoke], prompt: x, expect: y, thread: 'Two Words'}\n", "thread"))
check("a file without version: 1 is refused", rejects("prompts: []\n", "version: 1"))
try:
    rp.select(prompts, [], ["no-such-id"])
    check("--only with an unknown id is refused", False)
except rp.PromptSetError:
    check("--only with an unknown id is refused", True)
check("--tag selects any-of, in file order",
      [p.id for p in rp.select(prompts, ["smoke", "attack"], [])] == [p.id for p in prompts if {"smoke", "attack"} & set(p.tags)])
check("--segment selects the prompts the room sends in that segment, in file order",
      [p.id for p in rp.select(prompts, [], [], [3])] == [p.id for p in prompts if 3 in p.segments])

# ---------------------------------------------------------------------------------------------------------
print("targets and pacing")
check("a site root becomes its /chat", rp.chat_url("https://attackme.burritobot.co") == "https://attackme.burritobot.co/chat")
check("a /chat target is kept", rp.chat_url("https://attackme.burritobot.co/chat/") == "https://attackme.burritobot.co/chat")
for bad in ("attackme.burritobot.co", "ftp://x/chat", "https://x/a2a/"):
    try:
        rp.chat_url(bad)
        check(f"target {bad!r} is refused", False)
    except ValueError:
        check(f"target {bad!r} is refused", True)
m = re.search(r'name: RATE_LIMIT_RPM, value: "(\d+)"', RESOURCES)
check("the replay paces under the RATE_LIMIT_RPM guard-proxy is deployed with",
      bool(m) and int(m.group(1)) == rp.GUARD_PROXY_RPM, f"resources.yaml says {m.group(1) if m else 'nothing'}")
check("the default interval keeps the replay under a tenth of that window",
      60.0 / rp.DEFAULT_INTERVAL_S <= rp.GUARD_PROXY_RPM / 10)
m = re.search(r"location = /chat \{[^}]*proxy_read_timeout (\d+)s", (REPO / "gitops/ai-layer/console.conf").read_text())
check("the reply timeout outlasts console nginx's /chat read timeout, so nginx's 504 is what gets reported",
      bool(m) and rp.DEFAULT_TIMEOUT_S > int(m.group(1)))


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(round(s, 6))
        self.t += s


fc = FakeClock()
durations = iter([1.0, 10.0, 2.0, 0.5])
sent: list[str] = []


def fake_send(url, p, session, timeout):
    sent.append(session)
    fc.t += next(durations)
    return rp.Outcome(True, 200, reply="ok")


n, stopped = rp.replay(prompts[:4], "http://x/chat", interval=6.0, timeout=5, run_id="r",
                       send=fake_send, sleep=fc.sleep, clock=fc.clock, out=lambda s: None)
check("pacing waits out the interval from the last send's start, and not after a slow reply",
      fc.sleeps == [5.0, 4.0], f"slept {fc.sleeps}")
check("every prompt gets its own session, as separate phones would", len(set(sent)) == 4 and all(s.startswith("sess-replay-r-") for s in sent))
sent.clear()
durations = iter([1.0] * 3)
c2 = rp.select(prompts, [], [], [3])[:3]
rp.replay(c2, "http://x/chat", interval=6.0, timeout=5, run_id="r", send=fake_send, sleep=fc.sleep, clock=fc.clock,
          out=lambda s: None)
check("a thread's prompts share one session, and the next prompt gets its own",
      sent[0] == sent[1] != sent[2] and [p.thread for p in c2[:2]] == ["c2", "c2"], str(sent))

# ---------------------------------------------------------------------------------------------------------
print("against the real guard-proxy /chat handler, on loopback")


class StubAgent(BaseHTTPRequestHandler):
    """Answers A2A message/send like kagent does. A prompt containing [[empty]] gets an empty reply."""
    calls: list[dict] = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msg = body["params"]["message"]
        StubAgent.calls.append(msg)
        text = msg["parts"][0]["text"]
        reply = "" if "[[empty]]" in text else f"Hex & Cauldron here. You said: {text}"
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": {
            "artifacts": [{"parts": [{"kind": "text", "text": reply}]}] if reply else [],
            "metadata": {"kagent_usage_metadata": {"promptTokenCount": 120, "candidatesTokenCount": 30}}}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def serve(handler) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


agent = serve(StubAgent)
gp = serve(proxy.Handler)
AGENT = f"http://127.0.0.1:{agent.server_address[1]}"
TARGET = rp.chat_url(f"http://127.0.0.1:{gp.server_address[1]}")
P = rp.Prompt


def reset(**over):
    proxy.AGENT_URL = AGENT
    proxy.RATE_LIMIT_RPM = 0
    proxy.RATE_LIMIT_SESSION_RPM = 0
    proxy.COST_CAP_USD = 0.0
    proxy._cost_cap["usd"] = 0.0
    proxy._req_times.clear()
    proxy._session_times.clear()
    proxy._cost["usd"] = 0.0
    proxy._session_cost.clear()
    for k in proxy.GUARDS:
        proxy.GUARDS[k] = False
    for k, v in over.items():
        setattr(proxy, k, v)
    StubAgent.calls.clear()


def run(ps):
    log: list[str] = []
    n, stopped = rp.replay(ps, TARGET, interval=1.0, timeout=10, run_id="t", sleep=lambda s: None, out=log.append)
    return n, stopped, log


three = [P(f"p{i}", ("on-topic",), f"prompt number {i}", "x") for i in range(1, 4)]

reset()
n, stopped, log = run(three)
check("a healthy bot: every prompt delivered, none stopped", n == 3 and stopped is None, "\n".join(log))
check("the bot got each prompt's exact text, under its own contextId",
      [c["parts"][0]["text"] for c in StubAgent.calls] == [p.prompt for p in three]
      and len({c.get("contextId") for c in StubAgent.calls}) == 3)
check("each prompt carries the replay's witch name, as the storefront's do",
      all(len(c["parts"]) == 2 and c["parts"][1]["text"] == proxy.witch_context(rp.DEFAULT_WITCH)
          for c in StubAgent.calls), str([c["parts"] for c in StubAgent.calls]))
check("the replayed turns climb the cluster's cost counter like typed ones", proxy._cost["usd"] > 0)

reset(RATE_LIMIT_RPM=2)
n, stopped, log = run(three)
check("guard-proxy's rate limit (an HTTP 200 'Slow down') stops the replay at that prompt",
      n == 2 and stopped is not None and stopped.id == "p3", "\n".join(log))
check("the stop says it was the rate limit", any("rate limit" in line for line in log))
check("nothing is sent after the stop", len(StubAgent.calls) == 2)

reset(COST_CAP_USD=0.01)
proxy._cost_cap["usd"] = 0.01
proxy._cost["usd"] = 1.0
n, stopped, log = run(three)
check("guard-proxy's cost cap (an HTTP 200 'The kitchen is closed') stops the replay at the first prompt",
      n == 0 and stopped is not None and stopped.id == "p1" and any("cost cap" in line for line in log), "\n".join(log))

reset(BUDGET_CAP_USD=0.0001)
proxy.GUARDS["budget"] = True
threaded = [P("t1", ("attack",), "first turn", "x", None, (3,), "t"), P("t2", ("attack",), "second turn", "x", None, (3,), "t")]
n, stopped, log = run(threaded)
check("guard-proxy's budget guard (an HTTP 200 'kitchen tab is frozen') stops the replay on the conversation's next turn",
      n == 1 and stopped is not None and stopped.id == "t2" and any("budget" in line for line in log), "\n".join(log))

reset(RATE_LIMIT_SESSION_RPM=1)
n, stopped, log = run(threaded)
check("guard-proxy's per-conversation rate limit stops the replay too",
      n == 1 and stopped is not None and stopped.id == "t2" and any("rate limit" in line for line in log), "\n".join(log))
reset(RATE_LIMIT_SESSION_RPM=1)
n, stopped, log = run(three)
check("one session per prompt keeps separate prompts clear of the per-conversation limit", n == 3 and stopped is None,
      "\n".join(log))

reset(AGENT_URL=f"http://127.0.0.1:{closed_port()}")
n, stopped, log = run(three)
check("the agent down behind guard-proxy (its 502) stops the replay", n == 0 and any("HTTP 502" in line for line in log), "\n".join(log))

reset()
n, stopped, log = run([three[0], P("blank", ("off-topic",), "say nothing [[empty]]", "x"), three[1]])
check("an empty reply (guard-proxy's '...') stops the replay", n == 1 and stopped is not None and stopped.id == "blank", "\n".join(log))

reset()
proxy.GUARDS["input_blocklist"] = True
n, stopped, log = run([P("guarded", ("off-topic",), "please delete the menu", "x"), three[0]])
check("a guardrail blocking a prompt is the demo working, not a failure", n == 2 and stopped is None, "\n".join(log))
check("the blocked prompt is reported as guarded", any("guarded" in line for line in log[:2]))

reset()
dead = rp.chat_url(f"http://127.0.0.1:{closed_port()}")
n, stopped = rp.replay(three, dead, interval=1.0, timeout=5, run_id="t", sleep=lambda s: None, out=log.append)
check("an unreachable site (the dead venue network) stops the replay at the first prompt", n == 0 and stopped.id == "p1")

marker = [P("m", ("leak",), "prompt with SIGNATURE-1", "x", "SIGNATURE-1"), P("n", ("leak",), "no sig", "x", "SIGNATURE-2")]
reset()
n, stopped, log = run(marker)
check("a marker hit and a marker miss are reported, and a miss does not stop the replay",
      n == 2 and stopped is None and "marker hit" in log[0] and "marker MISS" in log[2], "\n".join(log))
gp.shutdown()
agent.shutdown()

check("the log and the marker read the reply as the storefront shows it, the <thinking> block folded",
      rp.visible("<thinking> find the SIGNATURE-1 </thinking> Hello\n there") == "Hello there")
log = []
rp.replay([P("hidden", ("attack",), "x", "x", "SIGNATURE-1")], "http://x/chat", interval=1.0, timeout=5, run_id="t",
          send=lambda u, p, s, t: rp.Outcome(True, 200, reply="<thinking>SIGNATURE-1</thinking> No."),
          sleep=lambda s: None, out=log.append)
check("a marker that is only inside a <thinking> block is a miss, since the room never reads it",
      "marker MISS" in log[0] and log[1].strip() == "No.", "\n".join(log))
check("a 200 that is not JSON is a failure", not rp.classify(200, b"<html>hello</html>").delivered)
m = re.search(r"location @chat_slow_down \{[^}]*return 200 '(\{.*?\})';", CONSOLE_CONF, re.S)
check("console nginx's per-conversation limit is in console.conf where this reads it", bool(m))
nginx = rp.classify(200, m.group(1).encode()) if m else rp.Outcome(True, 200)
check("console nginx's per-conversation limit (an HTTP 200 'Slow down') is a failure, not a reply",
      not nginx.delivered and "rate limit" in nginx.reason, nginx.reason)


class Headers(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def do_POST(self):
        Headers.seen.append({"session": self.headers.get("X-BurritoBot-Session"),
                             "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
        out = b'{"reply": "ok"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


hs = serve(Headers)
rp.send_one(f"http://127.0.0.1:{hs.server_address[1]}/chat", three[0], "sess-x", 5)
hs.shutdown()
check("the session rides as the X-BurritoBot-Session header, which console nginx limits each conversation by",
      Headers.seen and Headers.seen[0]["session"] == "sess-x" and Headers.seen[0]["body"]["session"] == "sess-x",
      str(Headers.seen))
m = re.search(r"limit_req_zone \$http_x_burritobot_session ", CONSOLE_CONF)
check("console nginx keys its per-conversation limit on that header", bool(m))
check("a 200 JSON without a reply is a failure (not BurritoBot's /chat)", not rp.classify(200, b'{"ok": true}').delivered)

# ---------------------------------------------------------------------------------------------------------
print("the command line")


def cli(*args):
    return subprocess.run([sys.executable, str(REPLAY_PY), *args], capture_output=True, text=True, timeout=60)


r = cli("--target", f"http://127.0.0.1:{closed_port()}", "--dry-run")
check("--dry-run lists every prompt and sends nothing", r.returncode == 0 and "DRY RUN: nothing sent" in r.stdout
      and all(p.id in r.stdout for p in prompts), r.stderr)
r = cli("--dry-run")
check("no --target is a usage error: the replay never guesses its cluster", r.returncode == 2)
r = cli("--target", "https://attackme.burritobot.co", "--interval", "0.5", "--dry-run")
check("an interval that would take over half guard-proxy's window is refused", r.returncode == 2 and "half" in r.stderr)
r = cli("--target", "https://attackme.burritobot.co", "--only", "nope", "--dry-run")
check("an unknown --only id is exit 2", r.returncode == 2)
r = cli("--target", f"http://127.0.0.1:{closed_port()}", "--tag", "smoke")
check("a real run against a dead address exits 1 and says STOPPED", r.returncode == 1 and "STOPPED" in r.stdout, r.stdout)
r = cli("--target", "https://attackme.burritobot.co", "--witch", "replay raven", "--dry-run")
check("a witch name guard-proxy would drop is refused", r.returncode == 2 and "Creature" in r.stderr, r.stderr)
r = cli("--target", "https://attackme.burritobot.co", "--segment", "7", "--dry-run")
check("a segment the run-of-show does not have is a usage error", r.returncode == 2)

# ---------------------------------------------------------------------------------------------------------
print("the recorded assets")
assets = yaml.safe_load((FALLBACK / "assets.yaml").read_text(encoding="utf-8"))
check("one title per segment of the run-of-show, 1 to 6", [v["segment"] for v in assets["segments"]] == [1, 2, 3, 4, 5, 6])
check("no segment videos are listed: they left this repo with M4 on 2026-11-01 (#613)", "videos" not in assets)
check("every segment has at least one screenshot", {s["segment"] for s in assets["screenshots"]} == {1, 2, 3, 4, 5, 6})
check("every screenshot is a PNG under screenshots/, named for its segment",
      all(re.fullmatch(rf"screenshots/0{s['segment']}-\d-[a-z0-9-]+\.png", s["file"]) for s in assets["screenshots"]))
check("the shots are in segment order", [s["segment"] for s in assets["screenshots"]] == sorted(s["segment"] for s in assets["screenshots"]))
headings = dict(re.findall(r"^### Segment (\d): (.+?) \(\d+ min\)", RUN_OF_SHOW, re.M))
check("the run-of-show has six segment headings where this reads them", sorted(headings) == list("123456"), str(headings))
for v in assets["segments"]:
    check(f"segment {v['segment']} is titled as the run-of-show heads it", headings.get(str(v["segment"])) == v["title"],
          f"{v['title']!r} vs {headings.get(str(v['segment']))!r}")
ids = {p.id for p in prompts}
for s_ in assets["screenshots"]:
    c = s_["capture"]
    if "chat" in c:
        check(f"{s_['file']} sends a prompt that is in prompts.yaml", c["chat"] in ids)
deck = (FALLBACK / assets["deck"]).read_text(encoding="utf-8")
segs, shots = cfa.deck_lists(cfa.load(FALLBACK / "assets.yaml"))
check("the deck page's shot list is the one in assets.yaml", cfa.embedded(deck, "shots") == shots)
check("the deck page's segment titles are the manifest's", cfa.embedded(deck, "segments") == segs)
check("the deck loads nothing from the network (it is for when the network is gone)",
      not re.search(r'(src|href)="https?://', deck))
ig = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", str(FALLBACK / assets["screenshots"][0]["file"])])
check("the screenshots are not ignored: the deck is stored in the repo", ig.returncode == 1)
for s_ in assets["screenshots"]:
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "--error-unmatch", str(FALLBACK / s_["file"])],
                             capture_output=True)
    check(f"{s_['file']} is committed", tracked.returncode == 0, tracked.stderr.decode())
    check(f"{s_['file']} is a real PNG", (FALLBACK / s_["file"]).is_file()
          and (FALLBACK / s_["file"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n")

for bad, why in (({"chat": "order"}, "cluster"), ({"chat": "order", "cluster": "community"}, "controls"),
                 ({"chat": "order", "cluster": "community", "controls": {"topic": True}}, "controls"),
                 ({"chat": "order", "cluster": "community", "controls": {"ai.topic": True}, "toggle": "guard-topic-on"}, "private"),
                 ({"page": "http://prompts.burritobot.co"}, "https"), ({"page": "https://x", "by_hand": "y"}, "exactly one"),
                 (None, "exactly one")):
    got = cfa.check_capture(bad)
    check(f"a capture of {bad!r} is refused, saying {why}", why in got, got)
check("a well-formed private chat capture passes",
      cfa.check_capture({"chat": "order", "cluster": "private", "controls": {"ai.topic": True}, "toggle": "guard-topic-on"}) == "")

problems = dict(cfa.check(FALLBACK / "assets.yaml"))
check("the checker finds the committed deck page", assets["deck"] not in problems)
check("the checker finds every committed shot: the Night Before check passes on a clean clone", problems == {}, str(problems))
CAP = {"by_hand": "taken at the rehearsal"}
with tempfile.TemporaryDirectory() as td:
    base = pathlib.Path(td)
    (base / "screenshots").mkdir()
    (base / "assets.yaml").write_text(yaml.safe_dump({
        "version": 1, "deck": "screenshots/deck.html",
        "segments": [{"segment": 1, "title": "One"}, {"segment": 2, "title": "Two"}, {"segment": 3, "title": "Three"}],
        "screenshots": [{"segment": 1, "file": "screenshots/a.png", "caption": "c", "capture": CAP},
                        {"segment": 2, "file": "screenshots/b.png", "caption": "d", "capture": CAP},
                        {"segment": 3, "file": "screenshots/c.png", "caption": "e", "capture": CAP},
                        {"segment": 3, "file": "screenshots/d.png", "caption": "f", "capture": CAP}]}))
    (base / "screenshots/deck.html").write_text(
        '<html>\n<script type="application/json" id="segments">\n{}\n</script>\n'
        '<script type="application/json" id="shots">\n[]\n</script>\n</html>\n')
    (base / "screenshots/a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    (base / "screenshots/b.png").write_bytes(b"<html>a saved web page, not a PNG</html>")
    (base / "screenshots/c.png").write_bytes(b"")
    got = dict(cfa.check(base / "assets.yaml"))
    check("the checker passes a real PNG and the deck page", "screenshots/a.png" not in got and "screenshots/deck.html" not in got, str(got))
    check("the checker fails a file that is not the type it is named as", "not a PNG" in got.get("screenshots/b.png", ""), str(got))
    check("the checker fails an empty shot", got.get("screenshots/c.png") == "empty", str(got))
    check("the checker fails a missing shot", got.get("screenshots/d.png") == "missing", str(got))
    r = subprocess.run([sys.executable, str(ASSETS_PY), "--manifest", str(base / "assets.yaml")], capture_output=True, text=True)
    check("the checker exits 1 and says NOT READY while anything is missing", r.returncode == 1 and "NOT READY" in r.stderr)
    r = subprocess.run([sys.executable, str(ASSETS_PY), "--manifest", str(base / "assets.yaml"), "--write-deck"],
                       capture_output=True, text=True)
    written = (base / "screenshots/deck.html").read_text()
    check("--write-deck writes the manifest's titles and shots into the deck page",
          cfa.embedded(written, "segments") == {"1": "One", "2": "Two", "3": "Three"}
          and [s_["file"] for s_ in cfa.embedded(written, "shots")] == [f"screenshots/{x}.png" for x in "abcd"], r.stderr)
    (base / "screenshots/deck.html").write_text("<html></html>")
    r = subprocess.run([sys.executable, str(ASSETS_PY), "--manifest", str(base / "assets.yaml"), "--write-deck"],
                       capture_output=True, text=True)
    check("--write-deck refuses a deck page that lost its lists, naming the block", r.returncode == 2 and "segments" in r.stderr, r.stderr)

# ---------------------------------------------------------------------------------------------------------
print("the capture script, offline")
CONTROLS = {"ai": {"topic": False, "input_classifier": True}, "infra": {"rbac_scoped": False}}
check("a shot whose controls read as listed has no mismatch", cap.controls_mismatch(CONTROLS, {"ai.topic": False}) == [])
check("a shot that needs a guard on is refused while it is off, naming the control",
      cap.controls_mismatch(CONTROLS, {"ai.topic": True}) == ["ai.topic is false, the shot needs true"])
check("a control /controls does not report is a mismatch, not a pass",
      cap.controls_mismatch(CONTROLS, {"infra.kyverno": False}) == ["infra.kyverno is null, the shot needs false"])
check("a threaded shot sends the thread up to its prompt",
      [p.id for p in cap.thread_upto(prompts, "c2-tron-public-image")] == ["c2-tron", "c2-tron-public-image"])
check("an unthreaded shot sends its prompt alone", [p.id for p in cap.thread_upto(prompts, "order")] == ["order"])
for reply, want in (("Slow down, hungry traveler. (150/min cap on this cluster.)", "rate limit"),
                    ("The kitchen is closed: this cluster hit its $25.00 spend cap", "cost cap"),
                    ("…", "empty"), ("BurritoBot's kitchen isn't answering. Try again in a moment.", "did not answer"),
                    ("Welcome to Hex & Cauldron! Pick a base first.", "")):
    got = cap.refused(reply)
    check(f"a storefront reply {reply[:40]!r} is judged {want or 'an answer'}", (want in got) if want else got == "", got)
r = subprocess.run([sys.executable, str(CAPTURE_PY), "--private", "https://burritobot-private.burritobot.co", "--list"],
                   capture_output=True, text=True)
check("the capture script needs both sites named: it never guesses a cluster", r.returncode == 2)
r = subprocess.run([sys.executable, str(CAPTURE_PY), "--community", "https://a.example", "--private", "https://b.example", "--list"],
                   capture_output=True, text=True)
check("--list names every shot and how it is captured, touching no network",
      r.returncode == 0 and all(s_["file"] in r.stdout for s_ in assets["screenshots"]), r.stdout + r.stderr)
r = subprocess.run([sys.executable, str(CAPTURE_PY), "--community", "https://a.example", "--private", "https://b.example",
                    "--shot", "no-such-shot"], capture_output=True, text=True)
check("an unknown --shot is a usage error", r.returncode == 2)

# ---------------------------------------------------------------------------------------------------------
print("the run-of-show names it")


def section(title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", RUN_OF_SHOW, re.S | re.M)
    return m.group(1) if m else ""


night, rollback = section("Night Before"), section("Rollback on the day")
step3 = re.search(r"^3\. (.*?)(?=^\d\. |\Z)", rollback, re.S | re.M)
step3 = step3.group(1) if step3 else ""
check("Rollback step 3 names the screenshots deck by path", f"facilitation/kubecon-na-2026/fallback/{assets['deck']}" in step3)
check("Rollback step 3 sends no one to segment videos this repo does not hold (#613)", "videos/" not in step3 and ".mp4" not in step3)
check("Night Before runs the replay once, segment 1's prompts to the public bot",
      "python3 scripts/replay-prompts.py --target https://attackme.burritobot.co --segment 1" in night)
check("Night Before runs the asset check", "python3 scripts/check-fallback-assets.py" in night)
for path in sorted(set(re.findall(r"`((?:scripts|facilitation)/[^`* ]+)`", night + rollback))):
    check(f"the path {path} it names exists", (REPO / path).exists())
check("nothing still says the fallback paths are not built", "not built yet" not in night + rollback)

if failures:
    print(f"\nFAILED: {len(failures)}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll recorded-fallback checks passed.")
