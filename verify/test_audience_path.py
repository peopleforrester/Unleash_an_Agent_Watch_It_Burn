# ABOUTME: Holds the KubeCon audience path to a ballroom (#450): the per-conversation and per-network limits on /chat,
# ABOUTME: the timeout ladder from Railway's edge down to guard-proxy's worst turn, and refusals a phone can read.
"""A ballroom of phones on one venue NAT reaches attackme through Railway's edge, the apex Caddy, the NLB and the
console's nginx, then guard-proxy. Three things break there without anything on the platform being wrong:

- The limits. guard-proxy's cluster window is one budget for the whole room, and its per-conversation limit is
  keyed on a session the client chooses, so a script rotating sessions can spend the room's window. nginx adds a
  per-network ceiling under that window, keyed on the one X-Forwarded-For entry the apex sends
  (apex-agenticburn#40), and a per-conversation zone in front of it so a phone over its own 10 does not spend
  its network's ceiling.
- The timeouts. /chat sends nothing until the turn is done, so every hop in front must wait longer than
  guard-proxy's slowest turn, or the phone gets the outer hop's bare error. guard-proxy's PROXY_TIMEOUT is per
  call, and a turn makes several in a row: this counts them in proxy.py, so a new retry fails here.
- The words. nginx's own 429, 502 and 504 answer in guard-proxy's /chat shape, and the page shows that reply
  whatever the status, so the phone never reads "(429)" (BurritoBot#110).

The hops outside this repo are constants with their source. Railway: docs.railway.com/networking/public-networking/
specs-and-limits, read 2026-10-29, "closed after 5 minutes with no data transferred". The apex Caddy sets no
response timeout (apex-agenticburn Caddyfile, read 2026-10-29: only dial_timeout 2s and lb_try_duration 5s).
The NLB's TCP idle timeout is AWS's default 350s unless the console Service sets a listener attribute.
The live measurement is verify/test_audience_path_live.py, in the E2E suite.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
CONF = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")
PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
DOCS = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8"))
        if isinstance(d, dict)]
PROXY_SRC = REPO / "gitops/ai-layer/guard-proxy/proxy.py"
if not PROXY_SRC.exists():
    print(f"FAILED: {PROXY_SRC} is missing; run bash verify/ensure-submodules.sh")
    sys.exit(1)
PROXY = ast.parse(PROXY_SRC.read_text(encoding="utf-8"))

RAILWAY_SILENCE_S = 300   # Railway's edge, no data transferred
NLB_IDLE_DEFAULT_S = 350  # AWS NLB TCP idle timeout, default
MARGIN_S = 10             # each hop waits at least this much longer than the one behind it
KITCHEN_DOWN = "kitchen isn't answering"  # what the probes read as a failed turn (verify/bedrock_profile_check.py)

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def seconds(v: str) -> float:
    m = re.fullmatch(r"(\d+)(ms|s|m)?", v)
    n = float(m.group(1))
    return {"ms": n / 1000, "m": n * 60}.get(m.group(2), n)


def block(name: str) -> str:
    """The body of `location <name> {` in the console's default server, up to its closing brace."""
    m = re.search(r"^\s*location " + re.escape(name) + r" \{\n(.*?)^\s*\}", CONF, re.M | re.S)
    return m.group(1) if m else ""


def zone(name: str) -> tuple[str, float]:
    """(key, requests per minute) of a limit_req_zone."""
    m = re.search(r"^limit_req_zone (\S+) zone=" + re.escape(name) + r":\S+ rate=(\d+)r/([sm]);", CONF, re.M)
    if not m:
        return "", 0.0
    return m.group(1), float(m.group(2)) * (60 if m.group(3) == "s" else 1)


def returned(loc: str) -> tuple[int, dict]:
    """(status, JSON body) a named location returns."""
    m = re.search(r"return (\d+) '((?:[^'\\]|\\.)*)';", block(loc))
    if not m:
        return 0, {}
    try:
        return int(m.group(1)), json.loads(m.group(2).replace("\\'", "'"))
    except ValueError:
        return int(m.group(1)), {}


guard_proxy = next(d for d in DOCS if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
ENV = {e["name"]: e.get("value") for e in guard_proxy["spec"]["template"]["spec"]["containers"][0]["env"]}
console_svc = next(d for d in DOCS if d.get("kind") == "Service"
                   and (d.get("spec") or {}).get("type") == "LoadBalancer"
                   and "console" in d["metadata"]["name"])

# --- guard-proxy's slowest /chat turn, counted from proxy.py -----------------------------------------------
funcs = {n.name: n for n in ast.walk(PROXY) if isinstance(n, ast.FunctionDef)}


def calls_in(node: ast.AST, name: str, skip_nested: bool = False) -> int:
    count = 0
    todo = list(ast.iter_child_nodes(node))
    while todo:
        n = todo.pop()
        if skip_nested and isinstance(n, ast.FunctionDef):
            continue
        f = getattr(n, "func", None) if isinstance(n, ast.Call) else None
        if f is not None and (getattr(f, "id", None) == name or getattr(f, "attr", None) == name):
            count += 1
        todo.extend(ast.iter_child_nodes(n))
    return count


chat = funcs["_handle_chat"]
guard_calls = {g: calls_in(chat, g, skip_nested=True) for g in ("input_allowed", "topic_refused", "output_scrub")}
forwards = calls_in(chat, "_attempt", skip_nested=True)
check(f"each LLM Guard stage in /chat is one _post_guard call {guard_calls}",
      all(calls_in(funcs[g], "_post_guard") == 1 for g in guard_calls) and calls_in(funcs["_post_guard"], "urlopen") == 1)
check("each agent forward is one urlopen", calls_in(funcs["_forward"], "urlopen") == 1
      and calls_in(funcs["_attempt"], "_forward") == 1)
check(f"/chat runs each LLM Guard stage once and forwards at most three times (found {forwards})",
      all(v == 1 for v in guard_calls.values()) and forwards == 3)
upstream_calls = sum(guard_calls.values()) + forwards
check("guard-proxy's TIMEOUT is PROXY_TIMEOUT", any(
    isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "TIMEOUT" for t in n.targets)
    and "PROXY_TIMEOUT" in ast.unparse(n.value) for n in PROXY.body))
check("the deployment sets PROXY_TIMEOUT", ENV.get("PROXY_TIMEOUT") is not None)
per_call = float(ENV.get("PROXY_TIMEOUT") or 150)
worst_turn = upstream_calls * per_call

# --- the ladder ---------------------------------------------------------------------------------------------
chat_loc = block("= /chat")
m = re.search(r"proxy_read_timeout (\S+);", chat_loc)
nginx_chat = seconds(m.group(1)) if m else 60.0
listener = " ".join(v for k, v in (console_svc["metadata"].get("annotations") or {}).items()
                    if "listener-attributes" in k)
m = re.search(r"tcp\.idle_timeout\.seconds=(\d+)", listener)
nlb_idle = float(m.group(1)) if m else NLB_IDLE_DEFAULT_S
print(f"  ladder: guard-proxy {upstream_calls} x {per_call:g}s = {worst_turn:g}s < nginx /chat {nginx_chat:g}s"
      f" < Railway {RAILWAY_SILENCE_S}s, NLB {nlb_idle:g}s")
check("nginx /chat outlasts guard-proxy's slowest turn", nginx_chat >= worst_turn + MARGIN_S)
check("Railway's edge outlasts nginx /chat", RAILWAY_SILENCE_S >= nginx_chat + MARGIN_S)
check("the NLB outlasts nginx /chat", nlb_idle >= nginx_chat + MARGIN_S)
check("one agent forward still gets at least 45s", per_call >= 45)

# --- the limits ---------------------------------------------------------------------------------------------
s_key, s_rpm = zone("wib_chat_session")
a_key, a_rpm = zone("wib_chat_address")
window, session_rpm = int(ENV["RATE_LIMIT_RPM"]), int(ENV["RATE_LIMIT_SESSION_RPM"])
check("the conversation zone keys on the page's X-BurritoBot-Session", s_key == "$http_x_burritobot_session")
check("the network zone keys on the apex's X-Forwarded-For, not nginx's peer (the NLB)",
      a_key == "$http_x_forwarded_for")
check(f"nginx's per-conversation rate is guard-proxy's RATE_LIMIT_SESSION_RPM ({s_rpm:g} vs {session_rpm})",
      s_rpm == session_rpm)
check(f"the per-network ceiling ({a_rpm:g}/min) is under the cluster window ({window}/min) and holds ten phones",
      session_rpm * 10 <= a_rpm < window)
limits = re.findall(r"limit_req zone=(\S+)", chat_loc)
check("/chat applies the conversation zone, then the network zone", limits == ["wib_chat_session", "wib_chat_address"])
check("/chat answers a limit as 429 into its refusal", "limit_req_status 429;" in chat_loc
      and re.search(r"error_page 429 = @chat_slow_down;", chat_loc) is not None)
check("/chat passes the caller's X-Forwarded-For to guard-proxy as it came",
      "X-Forwarded-For" not in chat_loc and "real_ip" not in CONF)

# --- the words on the phone ---------------------------------------------------------------------------------
status, body = returned("@chat_slow_down")
check("a limit is a guarded 200 in the /chat shape", status == 200 and body.get("guarded") is True
      and isinstance(body.get("reply"), str) and str(session_rpm) in body["reply"] and f"{a_rpm:g}" in body["reply"])
for loc, code, statuses in (("@chat_kitchen_down", 502, "502 503"), ("@chat_kitchen_slow", 504, "504")):
    status, body = returned(loc)
    check(f"nginx's own {statuses} is a {code} in the /chat shape that the probes read as a failure",
          status == code and body.get("guarded") is False and KITCHEN_DOWN in body.get("reply", "")
          and re.search(r"error_page " + statuses + " = " + loc + ";", chat_loc) is not None)
# The default server, up to the next server block: the service vhosts after it intercept their own errors.
DEFAULT_SERVER = CONF[CONF.index("server {"):CONF.index("server {", CONF.index("server {") + 1)]
check("guard-proxy's own error replies pass through (no proxy_intercept_errors in the default server)",
      re.search(r"^[ \t]*proxy_intercept_errors[ \t]+on", DEFAULT_SERVER, re.M) is None)
check("the page sends its session as X-BurritoBot-Session",
      re.search(r"fetch\(CHAT_ENDPOINT,\{[^}]*headers:\{[^}]*'X-BurritoBot-Session':getSession\(\)\}", PAGE) is not None)
bad = re.search(r"if\(!res\.ok\)\{(.*?)return; \}", PAGE, re.S)
check("on an error status the page shows the reply before any status code",
      bad is not None and ".reply" in bad.group(1) and bad.group(1).index(".reply") < bad.group(1).index("res.status"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All audience-path checks passed.")
