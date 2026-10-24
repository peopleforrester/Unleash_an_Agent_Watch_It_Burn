# ABOUTME: Live half of #450: reads the apex Caddyfile for a response timeout, proves Railway replaces a forged
# ABOUTME: X-Real-IP, and sends one burst from one session to see the per-phone limit refuse as a reply.
# SUITE: e2e
"""Needs kubectl, CONTEXT naming the cluster the room uses (attackme on the day), the public internet, and a
checkout of apex-agenticburn (APEX_CADDYFILE, default ~/repos/agenticburn/apex-agenticburn/Caddyfile). Every
missing prerequisite is a failure with the reason, never a skip.

What verify/test_audience_path.py cannot see from this repo, and this does:

  1. The apex Caddy sets no response timeout shorter than the console's nginx. A Caddy timeout under nginx's
     would cut a long guarded turn before guard-proxy answers, the BurritoBot#109 failure.
  2. The per-address limit keys on a real address. /whoami reports the X-Real-IP Railway's edge wrote, and a
     forged one sent by the caller must not survive the edge. If it does, anyone can mint addresses and
     the per-network ceiling holds nobody (guard-proxy's cluster-wide window still does).
  3. Seven prompts at once from one browser session: five reach the model, and the rest come back as
     BurritoBot's own sentence, status 200, not an HTTP error. It reports how long the slowest turn took.

Costs five model turns (about $0.025 on Nova). Prompts carry the probe marker, so none reach the side-screen
feed.

Usage: CONTEXT=<kube-context> [APEX_CADDYFILE=<path>] python3 verify/test_audience_path_live.py
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
CONF = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")
DOCS = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]
CONTEXT = os.environ.get("CONTEXT", "")
CADDYFILE = pathlib.Path(os.environ.get("APEX_CADDYFILE",
                                        str(pathlib.Path.home() / "repos/agenticburn/apex-agenticburn/Caddyfile")))
PROBE = "[[wib-probe]] "  # proxy.py PROBE_MARKER: answered normally, kept out of the prompt feed
RATE_REPLY = "BurritoBot is cooking for the whole room at once"  # console.conf @chat_rate_limited
FORGED = "203.0.113.77"  # TEST-NET-3: no caller really has it

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("The live audience path holds.")
    sys.exit(0)


def request(url: str, *, headers: dict | None = None, data: bytes | None = None,
            timeout: float = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "wib-verify/450", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, f"{type(e).__name__}: {e}"


def whoami(host: str, headers: dict | None = None) -> dict:
    _, body = request(f"https://{host}/whoami", headers=headers)
    return dict(line.split("=", 1) for line in body.splitlines() if "=" in line)


def duration_s(text: str) -> float:
    """A Caddy duration (90s, 5m, 1h30m, 500ms) in seconds."""
    units = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
    return sum(float(n) * units[u] for n, u in re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)", text))


nginx_chat = int(re.search(r"location = /chat \{.*?proxy_read_timeout (\d+)s;", CONF, re.S).group(1))
proxy_env = {e["name"]: e.get("value") for d in DOCS
             if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy"
             for c in d["spec"]["template"]["spec"]["containers"] if c["name"] == "proxy"
             for e in c.get("env", [])}
worst_turn = 5 * int(proxy_env["PROXY_TIMEOUT"])  # test_audience_path.py counts the 5 calls from proxy.py

print("== prerequisites ==")
missing = []
if not shutil.which("kubectl"):
    missing.append("kubectl is not on PATH")
if not CONTEXT:
    missing.append("CONTEXT is not set: name the kube-context of the cluster the room uses (attackme)")
if not CADDYFILE.is_file():
    missing.append(f"no apex Caddyfile at {CADDYFILE}: check out peopleforrester/apex-agenticburn or set APEX_CADDYFILE")
for m in missing:
    check(m, False)
if missing:
    finish()

print(f"== apex Caddy waits longer than nginx /chat ({nginx_chat}s) ==")
caddy = CADDYFILE.read_text(encoding="utf-8")
caddy_code = "\n".join(line.split("#", 1)[0] for line in caddy.splitlines())
# The waits on the response path: the transport's, and the server's write timeout. dial_timeout and
# lb_try_duration are connection setup, not the wait for an answer.
waits = re.findall(r"^\s*(response_header_timeout|read_timeout|write_timeout|write)\s+(\S+)", caddy_code, re.M)
check("the Caddyfile was read (it routes on routes.map)", "routes.map" in caddy_code)
for key, val in waits:
    check(f"Caddy {key} {val} outlasts nginx /chat", duration_s(val) > nginx_chat)
print(f"        response-path timeouts set in the Caddyfile: {waits or 'none (Caddy waits as long as the upstream)'}")

r = subprocess.run(["kubectl", "--context", CONTEXT, "--request-timeout=20s", "-n", "agent", "get", "configmap",
                    "cluster-identity", "-o", "jsonpath={.data.public-host}"], capture_output=True, text=True)
host = r.stdout.strip()
check("the cluster records its public host (cluster-identity public-host)", bool(host), r.stderr.strip())
if not host:
    finish()
print(f"  probing {host} through the apex")

print("== the per-address limit keys on the caller's address ==")
seen = whoami(host)
check("/whoami reports the address lines", {"real_ip", "limit_key", "peer"} <= set(seen), f"{seen}")
check("Railway's edge wrote an X-Real-IP", re.fullmatch(r"[0-9A-Fa-f:.]{2,45}", seen.get("real_ip", "")) is not None,
      f"{seen}")
check("the limit keys on it", seen.get("limit_key") == seen.get("real_ip"), f"{seen}")
check("and not on the hop in front (the NLB)", seen.get("peer") != seen.get("real_ip"), f"{seen}")
forged = whoami(host, {"X-Real-IP": FORGED})
check("a forged X-Real-IP does not survive the Railway edge", forged.get("real_ip") not in ("", FORGED),
      f"{forged}: the per-network ceiling can be dodged; guard-proxy's RATE_LIMIT_RPM is the only hold left")
print(f"        forwarded_for={seen.get('forwarded_for')} (Caddy's peer, the same for every phone)")

print("== one session, seven prompts at once ==")
session = "sess-wibverify" + secrets.token_hex(4)


def send(_: int) -> tuple[int, dict, float]:
    t0 = time.monotonic()
    status, body = request(f"https://{host}/chat", timeout=nginx_chat + 30,
                           headers={"Content-Type": "application/json", "X-BurritoBot-Session": session},
                           data=json.dumps({"prompt": PROBE + "what bases do you have?", "session": session}).encode())
    try:
        obj = json.loads(body)
    except ValueError:
        obj = {"_raw": body[:160]}
    return status, obj, time.monotonic() - t0


with concurrent.futures.ThreadPoolExecutor(7) as pool:
    answers = list(pool.map(send, range(7)))
refused = [a for a in answers if RATE_REPLY in a[1].get("reply", "")]
served = [a for a in answers if a not in refused]
check("every answer is JSON with a reply", all(isinstance(a[1].get("reply"), str) for a in answers),
      f"{[(a[0], a[1]) for a in answers if 'reply' not in a[1]]}")
check("the per-phone limit refused some of the burst", len(refused) >= 1, f"{len(served)} served, none refused")
check("each refusal is status 200, read as BurritoBot speaking", all(a[0] == 200 for a in refused))
check("the served prompts answered 200", all(a[0] == 200 for a in served), f"{[a[0] for a in served]}")
slowest = max((a[2] for a in served), default=0.0)
print(f"        {len(served)} served, {len(refused)} refused; slowest served turn {slowest:.1f}s")
check(f"the slowest turn ({slowest:.1f}s) is inside guard-proxy's worst-case bound ({worst_turn}s)", slowest < worst_turn)

finish()
