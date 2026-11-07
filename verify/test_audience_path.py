# ABOUTME: Holds the KubeCon audience path to a ballroom (#450): the per-conversation limit on /chat and no per-network
# ABOUTME: one, the timeout ladder from Railway's edge down to guard-proxy's worst turn, and refusals a phone can read.
"""A ballroom of phones on one venue NAT reaches attackme through Railway's edge, the apex Caddy, the NLB and the
console's nginx, then guard-proxy. Three things break there without anything on the platform being wrong:

- The limits. The room's limit is per person: nginx holds one conversation to 10 a minute, keyed on the
  X-BurritoBot-Session header the page sends, as guard-proxy's RATE_LIMIT_SESSION_RPM does. Behind that are
  guard-proxy's cluster window and the cost cap. nginx sets no per-network limit (Michael, 2026-11-01, #450): the
  venue Wi-Fi leaves through one NAT address, so a per-address zone is one bucket for the whole ballroom, and the
  #644 load run saw it refuse 1,164 of 1,500 turns. Nothing on /chat may change the prompt on its way to the model.
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


def burst_in(loc_body: str, name: str) -> int:
    """The burst a location body's limit_req gives a zone, or -1."""
    m = re.search(r"limit_req zone=" + re.escape(name) + r" burst=(\d+)", loc_body)
    return int(m.group(1)) if m else -1


def outer_lines() -> list[str]:
    """The http-level lines and the default server's own lines, outside any location: what /chat inherits."""
    end = CONF.index("server {", CONF.index("server {") + 1)
    depth, out = 0, []
    for line in CONF[:end].splitlines():
        code = line.split("#", 1)[0]
        if depth <= 1 and not code.strip().startswith("location"):
            out.append(code)
        depth += code.count("{") - code.count("}")
    return out


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


# Since guard-proxy-agenticburn#21 _handle_chat sets the turn's deadline and _chat_turn runs the turn, and the input
# classifier stage is input_verdict (it also names the scanners that flagged, #684).
chat = funcs["_chat_turn"]
guard_calls = {g: calls_in(chat, g, skip_nested=True) for g in ("input_verdict", "topic_refused", "output_scrub")}
forwards = calls_in(chat, "_attempt", skip_nested=True)
check(f"each LLM Guard stage in /chat is one _post_guard call {guard_calls}",
      all(calls_in(funcs[g], "_post_guard") == 1 for g in guard_calls) and calls_in(funcs["_post_guard"], "urlopen") == 1)
check("each agent forward is one urlopen", calls_in(funcs["_forward"], "urlopen") == 1
      and calls_in(funcs["_attempt"], "_forward") == 1)
# The first forward, and one retry behind each reply check this test knows: a dangling tool_use, a reasoning-only
# reply, and since guard-proxy-agenticburn#62 (44b98d1, #1060) Bedrock's 424 tool-call grammar error. A pin from
# before #62 has no 424 check, so it forwards at most three times; a retry with no check named here fails.
RETRY_CHECKS = ("_is_dangling_tooluse", "_is_thinking_only", "_is_tooluse_model_error")
retry_checks = [g for g in RETRY_CHECKS if calls_in(chat, g, skip_nested=True)]
check(f"/chat checks a reply for each retry it knows: {retry_checks}",
      retry_checks[:2] == ["_is_dangling_tooluse", "_is_thinking_only"])
want_forwards = 1 + len(retry_checks)
check(f"/chat runs each LLM Guard stage once and forwards at most {want_forwards} times, once and once per "
      f"retry check (found {forwards})",
      all(v == 1 for v in guard_calls.values()) and forwards == want_forwards)
upstream_calls = sum(guard_calls.values()) + forwards
check("guard-proxy's TIMEOUT is PROXY_TIMEOUT", any(
    isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "TIMEOUT" for t in n.targets)
    and "PROXY_TIMEOUT" in ast.unparse(n.value) for n in PROXY.body))
check("the deployment sets PROXY_TIMEOUT", ENV.get("PROXY_TIMEOUT") is not None)
per_call = float(ENV.get("PROXY_TIMEOUT") or 150)
# One deadline for the whole turn (guard-proxy-agenticburn#21, #694): each call gets PROXY_TIMEOUT or what is left
# of TURN_TIMEOUT, whichever is less, so the turn's worst is TURN_TIMEOUT and no longer calls x PROXY_TIMEOUT.
check("guard-proxy reads TURN_TIMEOUT", any(
    isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "TURN_TIMEOUT" for t in n.targets)
    for n in PROXY.body))
check("the deployment sets TURN_TIMEOUT", float(ENV.get("TURN_TIMEOUT") or 0) > 0)
turn_timeout = float(ENV.get("TURN_TIMEOUT") or 0)
worst_turn = turn_timeout if turn_timeout > 0 else upstream_calls * per_call

# --- the ladder ---------------------------------------------------------------------------------------------
chat_loc = block("= /chat")
m = re.search(r"proxy_read_timeout (\S+);", chat_loc)
nginx_chat = seconds(m.group(1)) if m else 60.0
listener = " ".join(v for k, v in (console_svc["metadata"].get("annotations") or {}).items()
                    if "listener-attributes" in k)
m = re.search(r"tcp\.idle_timeout\.seconds=(\d+)", listener)
nlb_idle = float(m.group(1)) if m else NLB_IDLE_DEFAULT_S
print(f"  ladder: guard-proxy turn {worst_turn:g}s ({upstream_calls} calls, each at most {per_call:g}s)"
      f" < nginx /chat {nginx_chat:g}s"
      f" < Railway {RAILWAY_SILENCE_S}s, NLB {nlb_idle:g}s")
check("nginx /chat outlasts guard-proxy's slowest turn", nginx_chat >= worst_turn + MARGIN_S)
check("Railway's edge outlasts nginx /chat", RAILWAY_SILENCE_S >= nginx_chat + MARGIN_S)
check("the NLB outlasts nginx /chat", nlb_idle >= nginx_chat + MARGIN_S)
check("one agent forward gets more than the 45s it was cut to before TURN_TIMEOUT (#694)", per_call > 45)
check("and no single call can outlast the turn", per_call <= worst_turn)

# --- the limits ---------------------------------------------------------------------------------------------
s_key, s_rpm = zone("wib_chat_session")
window, session_rpm = int(ENV["RATE_LIMIT_RPM"]), int(ENV["RATE_LIMIT_SESSION_RPM"])
check("the conversation zone keys on the page's X-BurritoBot-Session", s_key == "$http_x_burritobot_session")
check(f"nginx's per-conversation rate is guard-proxy's RATE_LIMIT_SESSION_RPM ({s_rpm:g} vs {session_rpm})",
      s_rpm == session_rpm)
# The room's limits behind nginx stay as they were (#450, 2026-11-01): 10 a minute per session, 150 for the cluster.
check(f"guard-proxy keeps RATE_LIMIT_RPM 150, RATE_LIMIT_SESSION_RPM 10 and COST_CAP_USD 25 (got {window}, "
      f"{session_rpm}, {ENV.get('COST_CAP_USD')})",
      (window, session_rpm, float(ENV.get("COST_CAP_USD") or 0)) == (150, 10, 25.0))
limits = re.findall(r"limit_req zone=(\S+)", chat_loc)
check(f"/chat applies the conversation zone and no other (found {limits})", limits == ["wib_chat_session"])
s_burst = burst_in(chat_loc, "wib_chat_session")
check(f"the conversation zone is 10 a minute with a burst of 9 (got {s_rpm:g}, {s_burst})", s_rpm == 10 and s_burst == 9)
# The limit is per person (#450, 2026-11-01): no zone in this file keys on an address, whichever way an address
# reaches nginx (its peer, the apex's X-Forwarded-For, or a real_ip rewrite of the peer), and nothing caps
# connections, which on venue Wi-Fi would be per address too.
address_keys = re.findall(r"^\s*limit_req_zone\s+(\S*(?:addr|forwarded|realip|real_ip)\S*)", CONF, re.M)
check(f"no limit_req_zone is keyed on a client address (found {address_keys})", not address_keys)
check("no limit_conn or limit_conn_zone", re.search(r"^\s*limit_conn", CONF, re.M) is None)
check("/chat answers a limit as 429 into its refusal", "limit_req_status 429;" in chat_loc
      and re.search(r"error_page 429 = @chat_slow_down;", chat_loc) is not None)
check("/chat passes the caller's X-Forwarded-For to guard-proxy as it came",
      "X-Forwarded-For" not in chat_loc and "real_ip" not in CONF)

# --- the prompt reaches the model as typed ------------------------------------------------------------------
# Nothing that applies to /chat (its location, or the default server and http level around it) may replace,
# rewrite, cap or reorder the request body. guard-proxy's own stages are held by its pin, which this file leaves be.
BODY_DIRECTIVES = ("proxy_set_body", "proxy_pass_request_body", "client_max_body_size", "sub_filter", "rewrite",
                   "js_", "perl", "mirror", "proxy_method")
found = [d for d in BODY_DIRECTIVES for text in (chat_loc, "\n".join(outer_lines()))
         if re.search(r"^\s*" + re.escape(d), text, re.M)]
check(f"nothing on /chat changes the request body (found {found})", not found)
check("/chat proxies to guard-proxy's own /chat", re.search(r"^\s*proxy_pass http://guard-proxy:8080/chat;$",
                                                          chat_loc, re.M) is not None)
check("the /prompts feed is still guard-proxy's own GET /prompts",
      re.search(r"^\s*location = /prompts \{ proxy_pass http://guard-proxy:8080/prompts; \}$", CONF, re.M) is not None)

# --- the words on the phone ---------------------------------------------------------------------------------
status, body = returned("@chat_slow_down")
check("a limit is a guarded 200 in the /chat shape", status == 200 and body.get("guarded") is True
      and isinstance(body.get("reply"), str))
reply = body.get("reply") or ""
check(f"the limit's sentence names {session_rpm} a minute per conversation and no network",
      f"{session_rpm} a minute per conversation" in reply and "network" not in reply.lower())
check("the limit's sentence says to wait and send that again",
      re.search(r"\bwait\b", reply, re.I) is not None and "send that again" in reply)
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
