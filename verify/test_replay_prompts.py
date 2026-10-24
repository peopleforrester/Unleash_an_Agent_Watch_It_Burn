# ABOUTME: Offline checks for the KubeCon recorded fallback (#452): the prompt set, the replay script driven
# ABOUTME: against the real guard-proxy /chat handler on loopback, the asset checker, the deck, and the run-of-show.
"""No cluster and no internet: everything here listens on 127.0.0.1.

The replay's whole job is to stop at the first prompt that did not reach the bot. Most of the ways that
happens come back from guard-proxy as an HTTP 200 with a canned reply (its rate limit, its cost cap), so a
replay that only checked the status code would carry on through a full window and report success. These
checks run guard-proxy's own Handler (gitops/ai-layer/guard-proxy/proxy.py, the code the clusters run) in
front of a stub agent, provoke each refusal for real, and check the replay stops on it. If proxy.py's words
change, this fails here and not in the ballroom.
"""
from __future__ import annotations

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
RUN_OF_SHOW = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
BRIEF = (REPO / "gitops/ai-layer/web/brief.html").read_text(encoding="utf-8")
RESOURCES = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")

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

# ---------------------------------------------------------------------------------------------------------
print("the prompt set")
prompts = rp.load_prompts(rp.DEFAULT_PROMPTS)
by_tag = {t: [p for p in prompts if t in p.tags] for t in rp.TAGS}
check("prompts.yaml loads under the replay's own rules", len(prompts) >= 8, f"{len(prompts)} prompts")
for tag in sorted(rp.TAGS):
    check(f"at least one prompt is tagged {tag}", bool(by_tag[tag]))
check("the smoke selection is exactly one prompt (the Night Before and E2E send only it)", len(by_tag["smoke"]) == 1)
check("the smoke prompt is on-topic, so it proves the bot answers as the chain",
      all("on-topic" in p.tags for p in by_tag["smoke"]))
check("off-topic asks outnumber the rest: the abstract invites the weirdest off-topic question",
      len(by_tag["off-topic"]) >= 4)
for p in by_tag["leak"]:
    check(f"leak prompt {p.id} is copied verbatim from /brief Phase 1", p.prompt in BRIEF)
    if p.marker:
        check(f"leak prompt {p.id}'s marker is the one /brief says lands", p.marker in BRIEF)
check("the run-of-show's segment 7 asks (salsa-dance, hot-dog-party, karaoke) are in the set",
      {"salsa-dance", "hot-dog-party", "karaoke"} <= {p.id for p in by_tag["off-topic"]})


def rejects(body: str, fragment: str) -> bool:
    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / "p.yaml"
        path.write_text(body, encoding="utf-8")
        try:
            rp.load_prompts(path)
        except rp.PromptSetError as exc:
            return fragment in str(exc)
    return False


GOOD = "  - {id: a, tags: [on-topic], prompt: hello, expect: a reply}\n"
check("a duplicate id is refused", rejects("version: 1\nprompts:\n" + GOOD + GOOD, "duplicate id"))
check("an unknown tag is refused", rejects("version: 1\nprompts:\n  - {id: a, tags: [spicy], prompt: x, expect: y}\n", "tags must"))
check("a prompt longer than the side-screen shows is refused",
      rejects(f"version: 1\nprompts:\n  - {{id: a, tags: [smoke], prompt: '{'x' * 281}', expect: y}}\n", "281 characters"))
check("a prompt with no expect is refused", rejects("version: 1\nprompts:\n  - {id: a, tags: [smoke], prompt: x}\n", "expect is empty"))
check("an unknown field is refused (a typo'd marker would otherwise vanish)",
      rejects("version: 1\nprompts:\n  - {id: a, tags: [smoke], prompt: x, expect: y, markr: z}\n", "unknown field"))
check("a file without version: 1 is refused", rejects("prompts: []\n", "version: 1"))
try:
    rp.select(prompts, [], ["no-such-id"])
    check("--only with an unknown id is refused", False)
except rp.PromptSetError:
    check("--only with an unknown id is refused", True)
check("--tag selects any-of, in file order",
      [p.id for p in rp.select(prompts, ["smoke", "leak"], [])] == [p.id for p in prompts if {"smoke", "leak"} & set(p.tags)])

# ---------------------------------------------------------------------------------------------------------
print("targets and pacing")
check("a site root becomes its /chat", rp.chat_url("https://attackme.agenticburn.com") == "https://attackme.agenticburn.com/chat")
check("a /chat target is kept", rp.chat_url("https://attackme.agenticburn.com/chat/") == "https://attackme.agenticburn.com/chat")
for bad in ("attackme.agenticburn.com", "ftp://x/chat", "https://x/a2a/"):
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
    proxy.COST_CAP_USD = 0.0
    proxy._req_times.clear()
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
check("the replayed turns climb the cluster's cost counter like typed ones", proxy._cost["usd"] > 0)

reset(RATE_LIMIT_RPM=2)
n, stopped, log = run(three)
check("guard-proxy's rate limit (an HTTP 200 'Slow down') stops the replay at that prompt",
      n == 2 and stopped is not None and stopped.id == "p3", "\n".join(log))
check("the stop says it was the rate limit", any("rate limit" in line for line in log))
check("nothing is sent after the stop", len(StubAgent.calls) == 2)

reset(COST_CAP_USD=0.01)
proxy._cost["usd"] = 1.0
n, stopped, log = run(three)
check("guard-proxy's cost cap (an HTTP 200 'kitchen tab is frozen') stops the replay at the first prompt",
      n == 0 and stopped is not None and stopped.id == "p1" and any("cost cap" in line for line in log), "\n".join(log))

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

check("a 200 that is not JSON is a failure", not rp.classify(200, b"<html>hello</html>").delivered)
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
r = cli("--target", "https://attackme.agenticburn.com", "--interval", "0.5", "--dry-run")
check("an interval that would take over half guard-proxy's window is refused", r.returncode == 2 and "half" in r.stderr)
r = cli("--target", "https://attackme.agenticburn.com", "--only", "nope", "--dry-run")
check("an unknown --only id is exit 2", r.returncode == 2)
r = cli("--target", f"http://127.0.0.1:{closed_port()}", "--tag", "smoke")
check("a real run against a dead address exits 1 and says STOPPED", r.returncode == 1 and "STOPPED" in r.stdout, r.stdout)

# ---------------------------------------------------------------------------------------------------------
print("the recorded assets")
assets = yaml.safe_load((FALLBACK / "assets.yaml").read_text(encoding="utf-8"))
check("one video per demo segment of the run-of-show, 2 to 7", sorted(v["segment"] for v in assets["videos"]) == [2, 3, 4, 5, 6, 7])
check("every video is an MP4 under videos/", all(re.fullmatch(r"videos/segment-\d-[a-z0-9-]+\.mp4", v["path"]) for v in assets["videos"]))
check("every demo segment has at least one screenshot", {s["segment"] for s in assets["screenshots"]} == {2, 3, 4, 5, 6, 7})
check("every screenshot is a PNG under screenshots/", all(re.fullmatch(r"screenshots/\d\d-\d-[a-z0-9-]+\.png", s["file"]) for s in assets["screenshots"]))
deck = (FALLBACK / assets["deck"]).read_text(encoding="utf-8")
m = re.search(r'<script type="application/json" id="shots">(.*?)</script>', deck, re.S)
check("the deck page's shot list is the one in assets.yaml", bool(m) and json.loads(m.group(1)) == assets["screenshots"])
seg_titles = dict(re.findall(r'(\d):"([^"]+)"', deck))
check("the deck's segment titles are the videos' titles",
      all(seg_titles.get(str(v["segment"])) == v["title"] for v in assets["videos"]))
for v in assets["videos"]:
    check(f"segment {v['segment']} is titled as in the run-of-show", f"### Segment {v['segment']}: {v['title']}" in RUN_OF_SHOW)
check("the deck loads nothing from the network (it is for when the network is gone)",
      not re.search(r'(src|href)="https?://', deck))
ig = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", str(FALLBACK / assets["videos"][0]["path"])])
check("the segment videos are kept out of git", ig.returncode == 0)
ig = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", str(FALLBACK / assets["screenshots"][0]["file"])])
check("the screenshots are not ignored: the deck is stored in the repo", ig.returncode == 1)

problems = dict(cfa.check(FALLBACK / "assets.yaml"))
check("the checker finds the committed deck page", assets["deck"] not in problems)
with tempfile.TemporaryDirectory() as td:
    base = pathlib.Path(td)
    (base / "screenshots").mkdir()
    (base / "videos").mkdir()
    (base / "assets.yaml").write_text(yaml.safe_dump({
        "version": 1, "deck": "screenshots/deck.html",
        "videos": [{"segment": 2, "title": "t", "path": "videos/a.mp4"}, {"segment": 3, "title": "t", "path": "videos/b.mp4"},
                   {"segment": 4, "title": "t", "path": "videos/c.mp4"}],
        "screenshots": [{"segment": 2, "file": "screenshots/a.png", "caption": "c"},
                        {"segment": 2, "file": "screenshots/b.png", "caption": "c"}]}))
    (base / "screenshots/deck.html").write_text("<html></html>")
    (base / "videos/a.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    (base / "videos/b.mp4").write_bytes(b"")
    (base / "screenshots/a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    (base / "screenshots/b.png").write_bytes(b"<html>a saved web page, not a PNG</html>")
    got = dict(cfa.check(base / "assets.yaml"))
    check("the checker passes a real MP4 and a real PNG", "videos/a.mp4" not in got and "screenshots/a.png" not in got, str(got))
    check("the checker fails an empty video", got.get("videos/b.mp4") == "empty", str(got))
    check("the checker fails a missing video", got.get("videos/c.mp4") == "missing", str(got))
    check("the checker fails a file that is not the type it is named as", "not a PNG" in got.get("screenshots/b.png", ""), str(got))
    r = subprocess.run([sys.executable, str(ASSETS_PY), "--manifest", str(base / "assets.yaml")], capture_output=True, text=True)
    check("the checker exits 1 and says NOT READY while anything is missing", r.returncode == 1 and "NOT READY" in r.stderr)

# ---------------------------------------------------------------------------------------------------------
print("the run-of-show names it")


def section(title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", RUN_OF_SHOW, re.S | re.M)
    return m.group(1) if m else ""


night, rollback = section("Night Before"), section("Rollback on the day")
step3 = re.search(r"^3\. (.*?)(?=^\d\. |\Z)", rollback, re.S | re.M)
step3 = step3.group(1) if step3 else ""
check("Rollback step 3 names the screenshots deck by path", f"facilitation/kubecon-na-2026/fallback/{assets['deck']}" in step3)
check("Rollback step 3 names where the segment videos are", "facilitation/kubecon-na-2026/fallback/videos/" in step3)
check("Night Before runs the replay once", "python3 scripts/replay-prompts.py --target https://attackme.agenticburn.com" in night)
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
