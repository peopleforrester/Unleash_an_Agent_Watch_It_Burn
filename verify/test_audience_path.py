# ABOUTME: Holds the KubeCon audience path (#450): every timeout in front of guard-proxy outlasts its worst
# ABOUTME: /chat turn, the per-phone and per-network limits exist and refuse readably, and the cost cap holds.
"""A ballroom of phones on one venue NAT hits one cluster at once. Four things have to hold for that.

1. Every hop in front of guard-proxy waits longer than guard-proxy can take to answer. Otherwise a long
   guarded turn ends on a hop's 504 instead of the guardrail's own reply (BurritoBot#109). guard-proxy's
   worst /chat turn is counted from proxy.py itself: each agent forward and each LLM Guard call is allowed
   PROXY_TIMEOUT. The hops outward are the console's nginx (console.conf), the NLB, the apex Caddy and the
   Railway edge. The last three are not in this repo; their limits are written down below with where each
   comes from, and verify/test_audience_path_live.py reads the Caddyfile and measures the path live.
2. One phone cannot take the room's budget (10 a minute per browser session) and one network cannot take
   more than the room's ceiling (300 a minute per client address, the address Railway's edge writes).
3. A refusal reads as a refusal on a phone: nginx's own errors on /chat answer in guard-proxy's /chat
   shape, and the page shows `reply` whatever the status (BurritoBot#110).
4. COST_CAP_USD outlasts the audience segment with the room at its ceiling.

Offline: python3 and PyYAML, reading the files. The guard-proxy submodule must be checked out
(verify/ensure-submodules.sh does it).
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
PROXY = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text(encoding="utf-8")
PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
ROS = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
DOCS = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]

# The hops outside this repo, and where each number comes from. A change to any of these is a change to
# the path, and has to be made here as well as there.
RAILWAY_IDLE_S = 300  # docs.railway.com/networking/public-networking/specs-and-limits: closed after 5 min with no data
NLB_IDLE_S = 350      # AWS NLB TCP idle timeout default; the console Service sets no listener attribute
# apex Caddy: no response_header_timeout, read or write timeout in the apex-agenticburn Caddyfile, so it
# waits as long as the hop behind it. test_audience_path_live.py reads the Caddyfile to hold that.
# The measured cost of a turn on Nova, the dearest lab prompt (BUDGET_CAP_USD's note in proxy.py:
# attendee-001, 2026-09-08, four sends moved $0.0500 to $0.0708).
NOVA_TURN_USD = 0.005

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def location(path: str) -> str:
    """The body of one nginx `location` block, braces balanced."""
    m = re.search(r"location\s+" + re.escape(path) + r"\s*\{", CONF)
    if not m:
        return ""
    depth, i = 1, m.end()
    while depth and i < len(CONF):
        depth += {"{": 1, "}": -1}.get(CONF[i], 0)
        i += 1
    return CONF[m.end():i - 1]


def seconds(block: str, directive: str) -> int | None:
    m = re.search(rf"^\s*{directive}\s+(\d+)s;", block, re.M)
    return int(m.group(1)) if m else None


proxy_env = {}
for d in DOCS:
    if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy":
        for c in d["spec"]["template"]["spec"]["containers"]:
            if c["name"] == "proxy":
                proxy_env = {e["name"]: e.get("value") for e in c.get("env", [])}
console_svc = next((d for d in DOCS if d.get("kind") == "Service" and d["metadata"]["name"] == "console"), {})

print("== guard-proxy's worst /chat turn, counted from proxy.py ==")
tree = ast.parse(PROXY)
chat = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_handle_chat"), None)
check("proxy.py has _handle_chat", chat is not None)
calls = [n.func.id for n in ast.walk(chat) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)] if chat else []
forwards = calls.count("_attempt")
guard_calls = calls.count("input_allowed") + calls.count("output_scrub")
check("a /chat turn makes at most three agent forwards (first try, two retries)", forwards == 3,
      f"counted {forwards}: re-derive the bound below if this changed")
check("a /chat turn makes at most two LLM Guard calls (classifier, output scrub)", guard_calls == 2,
      f"counted {guard_calls}")
# Every forward and every guard call goes through urllib with timeout=TIMEOUT, read from PROXY_TIMEOUT.
check("proxy.py reads its per-call timeout from PROXY_TIMEOUT",
      re.search(r'^TIMEOUT = float\(os\.environ\.get\("PROXY_TIMEOUT"', PROXY, re.M) is not None)
check("the forwards and the guard calls are each bounded by TIMEOUT",
      PROXY.count("urlopen(req, timeout=TIMEOUT)") >= 3, "a urlopen without timeout=TIMEOUT is unbounded")
check("resources.yaml sets PROXY_TIMEOUT explicitly", (proxy_env.get("PROXY_TIMEOUT") or "").isdigit(),
      "the proxy.py default (150s) puts the worst turn at 750s")
per_call = int(proxy_env.get("PROXY_TIMEOUT") or 150)
worst = (forwards + guard_calls) * per_call
print(f"        worst /chat turn = ({forwards} forwards + {guard_calls} guard calls) x {per_call}s = {worst}s")

print("== every hop in front outlasts it ==")
chat_loc, a2a_loc = location("= /chat"), location("/a2a/")
nginx_chat = seconds(chat_loc, "proxy_read_timeout")
nginx_a2a = seconds(a2a_loc, "proxy_read_timeout")
check("nginx /chat sets proxy_read_timeout", nginx_chat is not None)
check("nginx /a2a/ sets proxy_read_timeout", nginx_a2a is not None)
nginx_chat, nginx_a2a = nginx_chat or 0, nginx_a2a or 0
check(f"nginx /chat ({nginx_chat}s) outlasts guard-proxy's worst turn ({worst}s)", nginx_chat > worst)
# The A2A path is one forward, a classifier call and the scrub; holding it to the /chat bound covers it.
check(f"nginx /a2a/ ({nginx_a2a}s) outlasts guard-proxy's worst turn ({worst}s)", nginx_a2a > worst)
# proxy_send_timeout and proxy_connect_timeout stay at nginx's 60s: the request is small and the Service
# is in-cluster. Neither is the wait for guard-proxy's answer, which proxy_read_timeout is.
check(f"the Railway edge ({RAILWAY_IDLE_S}s idle) outlasts nginx /chat and /a2a/",
      RAILWAY_IDLE_S > max(nginx_chat, nginx_a2a))
ann = (console_svc.get("metadata") or {}).get("annotations") or {}
check("the console Service leaves the NLB's TCP idle timeout at its 350s default",
      not any("listener-attributes" in k for k in ann), f"{sorted(ann)}: re-derive NLB_IDLE_S from it")
check(f"the NLB ({NLB_IDLE_S}s idle) outlasts the Railway edge", NLB_IDLE_S > RAILWAY_IDLE_S)
# Caddy is not checked here: its Caddyfile is in apex-agenticburn, and test_audience_path_live.py reads it.

print("== the per-phone and per-network limits ==")
zones = {m.group(2): (m.group(1), int(m.group(3)))
         for m in re.finditer(r"^limit_req_zone\s+(\$\w+)\s+zone=(\w+):\w+\s+rate=(\d+)r/m;", CONF, re.M)}
check("a per-session zone at 10 a minute", zones.get("wib_chat_session") == ("$wib_chat_session", 10), f"{zones}")
check("a per-address zone at 300 a minute", zones.get("wib_chat_addr") == ("$wib_client_addr", 300), f"{zones}")
check("the session key is the X-BurritoBot-Session header",
      re.search(r"map \$http_x_burritobot_session \$wib_chat_session \{", CONF) is not None)
check("the address key is Railway's X-Real-IP, falling back to the peer",
      re.search(r"map \$http_x_real_ip \$wib_client_addr \{\n[^\n]*\$http_x_real_ip;\n\s*default\s+\$remote_addr;\n\}",
                CONF) is not None)
check("the address key is never X-Forwarded-For (Caddy replaces it with the Railway edge)",
      "$http_x_forwarded_for $wib_client_addr" not in CONF)
check("/chat applies the session limit", re.search(r"limit_req zone=wib_chat_session burst=\d+ nodelay;", chat_loc) is not None)
check("/chat applies the address limit", re.search(r"limit_req zone=wib_chat_addr burst=\d+ nodelay;", chat_loc) is not None)
# The cluster-wide window sits behind both. Below the per-address ceiling, the room on one NAT would be held
# to less than its own ceiling and the nginx limit would never be what answered.
rpm = int(proxy_env.get("RATE_LIMIT_RPM") or 0)
check(f"guard-proxy's cluster-wide RATE_LIMIT_RPM ({rpm}) is at least the per-address ceiling",
      rpm >= zones.get("wib_chat_addr", ("", 10**9))[1])

print("== a refusal reads as a refusal on a phone ==")
check("limit refusals are 429, not nginx's default 503", "limit_req_status 429;" in chat_loc)
for code, name, want_status in (("429", "@chat_rate_limited", 200), ("502", "@chat_kitchen_down", 502),
                                ("504", "@chat_too_slow", 504)):
    check(f"/chat sends its own {code} to {name}", f"error_page {code} = {name};" in chat_loc)
    body = location(name)
    m = re.search(r"default_type application/json;\s*return (\d+) '(.*)';", body, re.S)
    check(f"{name} answers JSON", m is not None)
    if not m:
        continue
    check(f"{name} answers {want_status}", int(m.group(1)) == want_status)
    try:
        obj = json.loads(m.group(2))
    except ValueError as e:
        check(f"{name} body is valid JSON", False, str(e))
        continue
    check(f"{name} carries guard-proxy's /chat keys",
          {"reply", "guarded", "input_tokens", "output_tokens"} <= set(obj) and len(obj["reply"]) > 20)
    check(f"{name} names no HTTP status in its reply", not re.search(r"\b(HTTP|[45]\d\d)\b", obj["reply"]))
check("the rate refusal is marked guarded, like guard-proxy's own",
      '"guarded":true' in location("@chat_rate_limited"))
# guard-proxy's own 400 and 502 already carry a reply; intercepting them would replace it.
check("guard-proxy's own error replies pass through",
      re.search(r"^\s*proxy_intercept_errors\s+on;", chat_loc, re.M) is None)
check("the page sends the session as a header too",
      re.search(r"'X-BurritoBot-Session':sess\}.*?session:sess\}", PAGE) is not None)
check("the page's session ids match nginx's session pattern",
      "var s='sess-'+Math.random().toString(36).slice(2)+Date.now().toString(36);" in PAGE
      and '"~^sess-[a-z0-9]{1,48}$"' in CONF)
check("the page shows a reply whatever the status",
      "if(!res.ok && !(data && data.reply))" in PAGE and "botReply(data.reply);" in PAGE)

print("== COST_CAP_USD outlasts the audience segment ==")
prices = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "TIER_PRICES_PER_1K":
        prices = ast.literal_eval(node.value)
tier = (proxy_env.get("MODEL_TIER") or "").lower()
check(f"MODEL_TIER ({tier}) has a price in proxy.py", tier in prices and "nova" in prices)
ratio = max(prices[tier]["in"] / prices["nova"]["in"], prices[tier]["out"] / prices["nova"]["out"]) if tier in prices else 1
seg = re.search(r"^\| 2 \| (\d+) \|.*attackme\.agenticburn\.com", ROS, re.M)
check("the run-of-show times the audience segment on attackme", seg is not None)
minutes = int(seg.group(1)) if seg else 0
cap = float(proxy_env.get("COST_CAP_USD") or 0)
spend = rpm * minutes * NOVA_TURN_USD * ratio * forwards
print(f"        {rpm}/min x {minutes} min x ${NOVA_TURN_USD * ratio:.4f} a call x {forwards} calls a turn = ${spend:.2f}")
check(f"the room at its ceiling, every turn retried twice, spends under COST_CAP_USD (${cap:.0f})",
      0 < spend < cap, "raise COST_CAP_USD or lower RATE_LIMIT_RPM, and re-check the Bedrock bill")

print("== the run-of-show says what the config does ==")
path = ROS[ROS.find("## The audience path"):]
path = path[:path.find("\n## ", 4)] if path else ""
check("the run-of-show has an audience-path section", bool(path))
for want in ("attackme.agenticburn.com", "X-Real-IP", "10 a minute", "300 a minute",
             f"RATE_LIMIT_RPM={rpm}", f"PROXY_TIMEOUT={per_call}", f"{worst}s", f"{nginx_chat}s",
             f"{RAILWAY_IDLE_S}s", f"{NLB_IDLE_S}s", f"${cap:.0f}", "verify/test_audience_path_live.py"):
    check(f"it names {want}", want in path)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The audience path holds.")
