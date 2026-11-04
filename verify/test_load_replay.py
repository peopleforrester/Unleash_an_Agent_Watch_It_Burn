# ABOUTME: Offline checks for verify/load_replay.py (#644): runs the tool as a command against a local fake /chat and
# ABOUTME: /cost on loopback at 500 users, and holds its refusal texts and limits to the pinned guard-proxy and console.conf.
"""Holds the load replay to its contract without a cluster, a model or any money.

The fake server answers each prompt by a keyword the fixture harvest put in it, with the bodies the deployed
components send: the console nginx's own @chat_slow_down body read out of console.conf, guard-proxy's limit and
cost-cap replies, its 502, nginx's 504, a bare 429, an empty reply and a turn slower than the client timeout. It
tallies what it answered, and the tool's JSON report must agree with that tally outcome for outcome.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import load_replay as lr  # noqa: E402

TOOL = HERE / "load_replay.py"
PROXY = REPO / "gitops/ai-layer/guard-proxy/proxy.py"
GO_CHAT = REPO / "gitops/ai-layer/guard-proxy/internal/server/chat.go"
CONSOLE = REPO / "gitops/ai-layer/console.conf"
SECRET = "FIXTURE-TEXT-7f3a"  # in every fixture prompt; must never reach a report

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# --- the replies the deployed components send -----------------------------------------------------------------
_conf = CONSOLE.read_text()
_slow = re.search(r"location @chat_slow_down \{.*?return 200 '(.*?)';", _conf, re.S)
NGINX_SLOW_DOWN = json.loads(_slow.group(1)) if _slow else {}
_proxy = PROXY.read_text()
_go_chat = GO_CHAT.read_text()


def anchor_missing(what: str, path: pathlib.Path) -> None:
    """A reworded or moved anchor in the pinned guard-proxy reads as that, not as a broken check further on."""
    print(f"  FAIL  {what} is not in {path.relative_to(REPO)}; the rate-limit reply checks read it there")
    sys.exit(1)


def proxy_limit_replies(source: str, limits: dict) -> dict[str, str]:
    """proxy.py's /chat per-conversation and per-cluster rate-limit replies as _chat_turn sends them: the "reply" of
    the _send under `if session_rate_limited(session):` and `if rate_limited():`, read from the syntax tree so the
    implicit string concatenation is joined, with {RATE_LIMIT_SESSION_RPM} and {RATE_LIMIT_RPM} filled in from the
    deployed env."""
    rpm = {"RATE_LIMIT_SESSION_RPM": limits["proxy_session_rpm"], "RATE_LIMIT_RPM": limits["proxy_cluster_rpm"]}
    turn = next((n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == "_chat_turn"),
                None)
    if turn is None:
        anchor_missing("def _chat_turn", PROXY)

    def render(value: ast.expr) -> str:
        parts = value.values if isinstance(value, ast.JoinedStr) else [value]
        out = ""
        for part in parts:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out += part.value
            elif (isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name)
                  and part.value.id in rpm and part.format_spec is None and part.conversion == -1):
                out += str(rpm[part.value.id])
            else:
                anchor_missing(f"a reply built from text and {sorted(rpm)} alone (found {ast.unparse(part)})", PROXY)
        return out

    replies: dict[str, str] = {}
    for node in ast.walk(turn):
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.Call) and isinstance(node.test.func, ast.Name)):
            continue
        key = {"session_rate_limited": "session", "rate_limited": "cluster"}.get(node.test.func.id)
        if key is None or key in replies:
            continue
        for call in (c for stmt in node.body for c in ast.walk(stmt)):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "_send"
                    and len(call.args) == 2 and isinstance(call.args[1], ast.Dict)):
                for k, v in zip(call.args[1].keys, call.args[1].values):
                    if isinstance(k, ast.Constant) and k.value == "reply":
                        replies[key] = render(v)
    for key, test in (("session", "if session_rate_limited(session):"), ("cluster", "if rate_limited():")):
        if key not in replies:
            anchor_missing(f'a self._send(200, {{"reply": ...}}) under `{test}` in _chat_turn', PROXY)
    return replies


def go_limit_replies(source: str, limits: dict) -> dict[str, str]:
    """The Go build's same two replies: the fmt.Sprintf under `if s.limiter.Session(session) {` and
    `if s.limiter.Cluster() {` in internal/server/chat.go, with its one %d filled in from the deployed env."""
    replies: dict[str, str] = {}
    for key, guard, getter, n in (("session", "s.limiter.Session(session)", "s.limiter.SessionRPM()",
                                   limits["proxy_session_rpm"]),
                                  ("cluster", "s.limiter.Cluster()", "s.limiter.ClusterRPM()",
                                   limits["proxy_cluster_rpm"])):
        block = re.search(r"if " + re.escape(guard) + r" \{\n(.*?)\n\t\}", source, re.S)
        if block is None:
            anchor_missing(f"`if {guard} {{`", GO_CHAT)
        fmt = re.search(r'fmt\.Sprintf\("((?:[^"\\]|\\.)*)", ' + re.escape(getter) + r"\)", block.group(1))
        if fmt is None or fmt.group(1).count("%") != 1 or "%d" not in fmt.group(1):
            anchor_missing(f'fmt.Sprintf("... %d ...", {getter}) under `if {guard} {{`', GO_CHAT)
        replies[key] = json.loads(f'"{fmt.group(1)}"').replace("%d", str(n))
    return replies


def says_wait_and_send_again(reply: str) -> bool:
    """Michael's 2026-11-01 criterion for every refused turn: the reply tells the phone to wait and send again."""
    return (re.search(r"\bwait\b", reply, re.I) is not None
            and re.search(r"\bsend\b.*\bagain\b", reply, re.I | re.S) is not None)


LIMITS = lr.deployed_limits()
PY_LIMIT = proxy_limit_replies(_proxy, LIMITS)
GO_LIMIT = go_limit_replies(_go_chat, LIMITS)

KEYWORDS = {
    # keyword: (status, body, the outcome the tool must report)
    "SERVE": (200, {"reply": "Pick a base: Black-Bog Rice.", "guarded": False,
                    "input_tokens": 100, "output_tokens": 40}, "served"),
    "EDGE": (200, NGINX_SLOW_DOWN, "edge_limit"),
    # guard-proxy's two rate-limit replies, exactly as the pinned proxy.py sends them at the deployed limits.
    "SESSION": (200, {"reply": PY_LIMIT["session"], "guarded": True,
                      "input_tokens": 0, "output_tokens": 0}, "session_limit"),
    "CLUSTER": (200, {"reply": PY_LIMIT["cluster"], "guarded": True,
                      "input_tokens": 0, "output_tokens": 0}, "cluster_limit"),
    "CAPPED": (200, {"reply": "The kitchen is closed: this cluster hit its $25.00 spend cap, so BurritoBot isn't "
                              "sending anything else to the model for anyone. A blocked request costs nothing.",
                     "guarded": True, "input_tokens": 0, "output_tokens": 0}, "cost_cap"),
    "BUDGET": (200, {"reply": "The kitchen tab is frozen. This conversation hit its $0.03 spend budget, so I'm not "
                              "sending anything else to the model. A blocked request costs nothing. Press Reset for "
                              "a fresh conversation; the budget guard stays on.",
                     "guarded": True, "input_tokens": 0, "output_tokens": 0}, "budget"),
    "GUARD": (200, {"reply": "I'm BurritoBot, and I only talk burritos!", "guarded": True,
                    "input_tokens": 0, "output_tokens": 0}, "guarded"),
    "EMPTY": (200, {"reply": "", "guarded": False, "input_tokens": 0, "output_tokens": 0}, "empty"),
    "EFIVEOTWO": (502, {"reply": "BurritoBot's kitchen isn't answering. Try again in a moment.",
                        "guarded": False}, "http_502"),
    "EFIVEOFOUR": (504, {"reply": "BurritoBot's kitchen isn't answering: that one took too long."}, "http_504"),
    "ETOOMANY": (429, None, "http_429"),
    "SLOW": (200, {"reply": "late", "guarded": False}, "timeout"),
}
# The client timeout has to outlast an ordinary reply from 500 user threads and as many server threads sharing one
# interpreter. At 0.4s it did not on a loaded gate host (load 17 on 16 cores, run 14714 of #265): 495 turns timed out
# where the server sent 95 SLOW ones, and the tally checks failed. SLOW stays well past the timeout, and a user's three
# turns all SLOW still end in 12s, inside the 60s ceiling below.
SLOW_S = 10.0
CLIENT_TIMEOUT = "4"


class Fake:
    """A /chat and /cost on loopback that records every request and tallies the outcome it caused."""

    def __init__(self, usd_per_served: float = 0.001):
        self.lock = threading.Lock()
        self.chats: list[dict] = []
        self.tally: dict[str, int] = {}
        self.cost_gets = 0
        self.usd = 0.5  # spend already on the cluster before the run
        self.requests = 7
        self.usd_per_served = usd_per_served
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # keep the suite's output to its PASS lines
                pass

            def _reply(self, code: int, body: dict | None) -> None:
                raw = b"Too Many Requests" if body is None else json.dumps(body).encode()
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json" if body is not None else "text/plain")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client gave up on a SLOW turn, as it is meant to

            def do_GET(self):
                if self.path == "/cost":
                    with fake.lock:
                        fake.cost_gets += 1
                        body = {"tier": "nova", "requests": fake.requests, "usd": round(fake.usd, 6),
                                "cap_usd": 25, "budget_guard": False}
                    self._reply(200, body)
                else:
                    self._reply(404, {"error": "no"})

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.loads(raw)
                key = next((k for k in KEYWORDS if k in body.get("prompt", "")), "SERVE")
                status, reply, outcome = KEYWORDS[key]
                with fake.lock:
                    fake.chats.append({"path": self.path, "body": body,
                                       "session_header": self.headers.get("X-BurritoBot-Session"),
                                       "content_type": self.headers.get("Content-Type")})
                    fake.tally[outcome] = fake.tally.get(outcome, 0) + 1
                    if outcome == "served":
                        fake.usd += fake.usd_per_served
                        fake.requests += 1
                if key == "SLOW":
                    time.sleep(SLOW_S)
                self._reply(status, reply)

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            request_queue_size = 2048

        self.server = Server(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def write_harvest(d: pathlib.Path, keys: list[str]) -> None:
    """Fixture harvest files in both shapes Datadog stored, one per keyword, three prompts each."""
    d.mkdir(parents=True, exist_ok=True)
    for i, key in enumerate(keys):
        prompts = [f"{key} order {n} {SECRET}" for n in range(3)]
        msgs = [{"role": "user", "parts": [{"content": prompts[0], "type": "text"}]},
                {"role": "assistant", "parts": [{"content": "ok", "type": "text"}]},
                {"role": "user", "parts": [{"content": prompts[1], "type": "text"}]}]
        records = [
            {"ts": f"2026-09-08T22:0{i % 10}:01.000Z", "user": [json.dumps(msgs, separators=(",", ":"))]},
            {"ts": f"2026-09-08T22:0{i % 10}:02.000Z",
             "user": [f"user: {prompts[1]}\nassistant: fine\nuser: {prompts[2]}"]},
            {"ts": f"2026-09-08T22:0{i % 10}:03.000Z",
             "user": [f"user: {key} smoke {lr.PROBE_MARKER}\nuser: {'x' * (lr.MAX_PROMPT_CHARS + 1)}"]},
        ]
        (d / f"cluster-{i:02d}.json").write_text(json.dumps(records))


def run_tool(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, timeout=timeout)


(REPO / "tmp").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=REPO / "tmp") as _t:
    tmp = pathlib.Path(_t)

    print("== the refusal texts and limits are the deployed ones ==")
    check("console.conf's @chat_slow_down body parses as /chat JSON", bool(NGINX_SLOW_DOWN.get("reply")))
    check("the tool reads nginx's refusal as edge_limit",
          lr.classify(200, NGINX_SLOW_DOWN) == "edge_limit", str(NGINX_SLOW_DOWN))
    check("EDGE_LIMIT_TEXT is in console.conf's refusal", lr.EDGE_LIMIT_TEXT in NGINX_SLOW_DOWN.get("reply", ""))
    for name in ("COST_CAP_TEXT", "BUDGET_TEXT"):
        check(f"{name} is in guard-proxy's /chat reply (proxy.py)", getattr(lr, name) in _proxy)

    print("\n== guard-proxy's rate-limit replies tell a phone to wait and send again (#790) ==")
    # The judge itself, on the wording before guard-proxy-agenticburn#43 and on the wording since.
    check("the judge refuses the pre-#43 reply, which only names the limit",
          not says_wait_and_send_again("Slow down, hungry traveler. (10/min per conversation.)"))
    check("the judge accepts a reply that says to wait and send that again",
          says_wait_and_send_again("Slow down. Wait a few seconds and send that again."))
    for build, replies in (("proxy.py", PY_LIMIT), ("internal/server/chat.go", GO_LIMIT)):
        for key, rpm_key in (("session", "proxy_session_rpm"), ("cluster", "proxy_cluster_rpm")):
            reply = replies[key]
            check(f"{build}'s per-{'conversation' if key == 'session' else 'cluster'} reply says to wait and send "
                  "again", says_wait_and_send_again(reply), reply)
            check(f"{build}'s {key} reply names the deployed {LIMITS[rpm_key]}/min", f"({LIMITS[rpm_key]}/min " in reply,
                  reply)
    check("proxy.py and the Go build send the same two rate-limit replies", PY_LIMIT == GO_LIMIT,
          f"{PY_LIMIT} != {GO_LIMIT}")
    check("SESSION_LIMIT_TEXT is in the per-conversation reply only",
          lr.SESSION_LIMIT_TEXT in PY_LIMIT["session"] and lr.SESSION_LIMIT_TEXT not in PY_LIMIT["cluster"],
          f"{lr.SESSION_LIMIT_TEXT!r} vs {PY_LIMIT}")
    check("CLUSTER_LIMIT_TEXT is in the per-cluster reply only",
          lr.CLUSTER_LIMIT_TEXT in PY_LIMIT["cluster"] and lr.CLUSTER_LIMIT_TEXT not in PY_LIMIT["session"],
          f"{lr.CLUSTER_LIMIT_TEXT!r} vs {PY_LIMIT}")
    for build, replies in (("proxy.py", PY_LIMIT), ("internal/server/chat.go", GO_LIMIT)):
        check(f"the tool reads {build}'s two rate-limit replies as session_limit and cluster_limit",
              lr.classify(200, {"reply": replies["session"], "guarded": True}) == "session_limit"
              and lr.classify(200, {"reply": replies["cluster"], "guarded": True}) == "cluster_limit", str(replies))
    check("the cluster's cost cap and a conversation's budget are told apart (guard-proxy-agenticburn#25)",
          lr.classify(200, KEYWORDS["CAPPED"][1]) == "cost_cap" and lr.classify(200, KEYWORDS["BUDGET"][1]) == "budget")
    check("PROBE_MARKER equals proxy.py's", f'PROBE_MARKER = "{lr.PROBE_MARKER}"' in _proxy)
    lim = lr.deployed_limits()
    check("limits read from git: nginx 10/min per conversation, burst 9",
          (lim["edge_session_rpm"], lim["edge_session_burst"]) == (10, 9), str(lim))
    # Since #450's ruling of 2026-11-01 nginx has no per-network zone, so the tool reads none and predicts none.
    check("the tool reads only the per-conversation zone, none per network",
          sorted(k for k in lim if k.startswith("edge_")) == ["edge_session_burst", "edge_session_rpm"]
          and "wib_chat_address" not in pathlib.Path(lr.__file__).read_text(), str(lim))
    _plan = lr.Plan(500, 3, 1500, 60.0, 15.0, 45.0, lr.USD_PER_CALL)
    check("one address sending as 500 phones is held only by the cluster window",
          _plan.predicted_served(lim) == int(lim["proxy_cluster_rpm"] * _plan.minutes()),
          str(_plan.predicted_served(lim)))
    check("limits read from git: guard-proxy 150/min cluster, 10/min session, $25 cap",
          (lim["proxy_cluster_rpm"], lim["proxy_session_rpm"], lim["cost_cap_usd"]) == (150, 10, 25.0), str(lim))
    check("client timeout outlasts nginx's 285s /chat read timeout",
          lr.TIMEOUT_S > int(re.search(r"location = /chat \{.*?proxy_read_timeout (\d+)s;", _conf, re.S).group(1)))

    print("\n== the prompts ==")
    h = tmp / "harvest"
    write_harvest(h, list(KEYWORDS))
    seqs, stats = lr.load_harvest(h)
    check("one conversation per harvested cluster file", len(seqs) == len(KEYWORDS), str(stats))
    check("both stored shapes read, in first-seen order, deduplicated",
          seqs[0] == [f"{list(KEYWORDS)[0]} order {n} {SECRET}" for n in range(3)], str(seqs[0]))
    check("prompts already carrying the probe marker are left out",
          stats["probes_left_out"] == len(KEYWORDS) and not any(lr.PROBE_MARKER in p for s in seqs for p in s))
    check("over-long prompts are left out", stats["too_long"] == len(KEYWORDS), str(stats))
    cat, _ = lr.load_catalog()
    flat = [p for s in cat for p in s]
    import kubecon_probe as kp  # noqa: E402
    import topic_cases as tc  # noqa: E402
    check("catalog source carries the off-topic asks", all(a in flat for a in tc.CANONICAL_OFF))
    check("catalog source carries the HC-666 ticket ask and the order", kp.ROOM_PROMPT in flat and kp.ORDER_PROMPT in flat)
    missing = run_tool("nowhere.invalid", "--harvest", str(tmp / "no-harvest"))
    check("a missing harvest is an error naming --source catalog, not a quiet switch",
          missing.returncode != 0 and "--source catalog" in missing.stderr, missing.stderr[-300:])

    print("\n== plan only: the estimate prints and nothing is sent ==")
    fake = Fake()
    try:
        p = run_tool(fake.url, "--harvest", str(h))
        check("exits 0", p.returncode == 0, p.stderr[-400:])
        check("prints the estimated cost and the ceiling",
              "estimated cost: worst case $7.50" in p.stdout and "--max-calls" in p.stdout, p.stdout)
        check("sends nothing without --yes, not even /cost", not fake.chats and fake.cost_gets == 0)
    finally:
        fake.close()

    print("\n== 500 users through every outcome, with a ceiling ==")
    fake = Fake()
    out = tmp / "report.json"
    try:
        t0 = time.monotonic()
        p = run_tool(fake.url, "--yes", "--harvest", str(h), "--users", "500", "--turns", "3",
                     "--max-calls", "1200", "--ramp", "0.5", "--think-min", "0", "--think-max", "0.05",
                     "--timeout", CLIENT_TIMEOUT, "--progress", "0.25", "--max-usd", "0", "--json-out", str(out))
        took = time.monotonic() - t0
        s = json.loads(out.read_text()) if out.exists() else {}
        lines = p.stdout.splitlines()
        est = next((i for i, ln in enumerate(lines) if ln.startswith("estimated cost")), None)
        prog = next((i for i, ln in enumerate(lines) if ln.startswith("[load]")), None)
        check("the estimate prints before the first progress line",
              est is not None and prog is not None and est < prog, p.stdout[:600])
        check("a progress line shows sent, percent and spend",
              prog is not None and re.search(r"sent \d+/1200 \(\d+%\).*spend \+\$", lines[prog]) is not None,
              lines[prog] if prog is not None else p.stdout[:300])
        check("the ceiling held: exactly 1200 sends, 300 held back",
              len(fake.chats) == 1200 and s.get("sent") == 1200 and s.get("not_sent_ceiling") == 300,
              f"server {len(fake.chats)}, report {s.get('sent')}/{s.get('not_sent_ceiling')}")
        check("every send went to /chat", all(c["path"] == "/chat" for c in fake.chats))
        check("every prompt carries the probe marker", all(lr.PROBE_MARKER in c["body"]["prompt"] for c in fake.chats))
        check("the session rides in the body and as X-BurritoBot-Session",
              all(c["body"]["session"] == c["session_header"] and c["session_header"] for c in fake.chats))
        _per = {}
        for c in fake.chats:
            _per[c["session_header"]] = _per.get(c["session_header"], 0) + 1
        check("one session per user: 500 made, none sends more than its 3 turns",
              s.get("sessions") == 500 and len(_per) <= 500 and max(_per.values()) <= 3, str((s.get("sessions"), len(_per))))
        check("sent as JSON", all(c["content_type"] == "application/json" for c in fake.chats))
        check("report outcomes equal what the server answered",
              {k: v for k, v in s.get("outcomes", {}).items() if v} == fake.tally,
              f"report {s.get('outcomes')} server {fake.tally}")
        st = s.get("statuses", {})
        check("502, 504 and 429 counted by status",
              st.get("502") == fake.tally.get("http_502") and st.get("504") == fake.tally.get("http_504")
              and st.get("429") == fake.tally.get("http_429"), str(st))
        check("rate-limit refusals are nginx's plus guard-proxy's two",
              s.get("rate_limit_refusals") == sum(fake.tally.get(k, 0) for k in lr.LIMIT_OUTCOMES))
        lat = s.get("latency_s", {}).get("all", {})
        check("latency percentiles in order", 0 < lat.get("p50", 0) <= lat.get("p95", 0) <= lat.get("max", 0), str(lat))
        check("the timeouts took the client timeout, not the server's sleep", lat.get("max", 99) < SLOW_S, str(lat))
        check("tokens summed from served replies", s.get("tokens", {}).get("input") == 100 * fake.tally["served"])
        check("/cost before and after are the server's",
              s.get("cost_before", {}).get("usd") == 0.5 and abs(s.get("spend_usd", 0) - 0.001 * fake.tally["served"]) < 1e-6,
              str((s.get("cost_before"), s.get("spend_usd"))))
        check("the report holds no prompt or reply text",
              SECRET not in out.read_text() and "Black-Bog" not in out.read_text() and SECRET not in p.stdout)
        check("errors make it RED and exit 1",
              p.returncode == 1 and "LOAD REPLAY RED" in p.stdout and "FAIL  every turn got a sentence" in p.stdout,
              p.stdout[-600:] + p.stderr[-400:])
        check("500 users ran in under a minute on loopback", took < 60, f"{took:.1f}s")
        check("stderr is clean", p.stderr == "", p.stderr[-400:])
    finally:
        fake.close()

    print("\n== a clean run is GREEN ==")
    hs = tmp / "harvest-serve"
    write_harvest(hs, ["SERVE", "SERVE", "SERVE"])
    fake = Fake()
    try:
        p = run_tool(fake.url, "--yes", "--harvest", str(hs), "--users", "50", "--turns", "2", "--ramp", "0.2",
                     "--think-min", "0", "--think-max", "0.02", "--progress", "0.2")
        check("exits 0 and prints LOAD REPLAY GREEN", p.returncode == 0 and "LOAD REPLAY GREEN" in p.stdout,
              p.stdout[-600:] + p.stderr[-300:])
        check("100 turns served", fake.tally == {"served": 100}, str(fake.tally))
        check("50 users are 50 sessions of 2 turns each on the server",
              sorted({c["session_header"]: sum(1 for d in fake.chats if d["session_header"] == c["session_header"])
                      for c in fake.chats}.values()) == [2] * 50)
        check("the report prints p50/p95/p99 and the /cost delta",
              re.search(r"latency all \(n=100\): p50 .* p95 .* p99", p.stdout) is not None
              and "this run $0.1000" in p.stdout, p.stdout[-700:])
    finally:
        fake.close()

    print("\n== the spend stop ==")
    fake = Fake(usd_per_served=0.01)
    out = tmp / "stop.json"
    try:
        p = run_tool(fake.url, "--yes", "--harvest", str(hs), "--users", "200", "--turns", "3", "--ramp", "3",
                     "--think-min", "0.2", "--think-max", "0.4", "--progress", "0.1", "--max-usd", "0.05",
                     "--json-out", str(out))
        s = json.loads(out.read_text()) if out.exists() else {}
        check("new turns stop once /cost rises by --max-usd",
              "--max-usd" in s.get("stop_reason", "") and s.get("not_sent_stopped", 0) > 0
              and len(fake.chats) < 600, f"{s.get('stop_reason')!r} sent {len(fake.chats)}")
        check("every planned turn is sent or accounted for",
              s.get("sent", 0) + s.get("not_sent_stopped", 0) + s.get("not_sent_ceiling", 0) == 600, str(s.get("sent")))
    finally:
        fake.close()

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("All load replay checks passed.")
