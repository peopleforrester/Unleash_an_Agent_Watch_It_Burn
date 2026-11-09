# ABOUTME: Offline checks for verify/llm_guard_burst.py (#1172) against a fake LLM Guard on loopback, and the llm-guard
# ABOUTME: Deployment's CPU limit held to the 3 CPUs a 100-prompt burst was measured inside scan_prompt_timeout with.
"""Holds the burst replay to its contract without a cluster, and the capacity #1172 measured to the manifest.

The fake LLM Guard answers /analyze/prompt on loopback, records each body and bearer header, and is told per case
to answer fast, to answer the long prompt with a 408 as LLM Guard does past scan_prompt_timeout, to answer slowly,
or to scan one prompt at a time so a burst queues. The tool runs as a command, as it runs in guard-proxy's pod:

  - every call sends guard-proxy's input_verdict body, the same literal the pinned proxy.py posts, and its token;
  - a fast LLM Guard reads BURST GREEN, exit 0, with every send counted 200, a burst all sent and a rate phase
    sending rate x secs;
  - a 408 reads BURST RED, exit 1, with the 408s counted and the phase named;
  - a 200 slower than --timeout reads BURST RED with it counted in over_timeout;
  - a one-at-a-time LLM Guard shows the queue: the slowest call of a burst waits for every scan in it;
  - no URL, and an unknown prompt kind, each fail by name;
  - the default phases are the ones #1172 measured with: the cap of all-long prompts at 150 a minute, and bursts
    of 50 and 100 long and 100 mixed.

And from the manifests: the llm-guard Deployment's CPU limit is at least 3 CPUs, with one replica and one uvicorn
worker, and scan_prompt_timeout is the 10 s the tool's verdict defaults to. The live figures behind the 3 are in
decisions.md's #1172 entry: at a 1 CPU limit a burst of 50 long prompts took up to 13.1 s and one came back 408;
at 3 CPUs a burst of 100 long ones took at most 8.3 s. Offline.
"""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
TOOL = REPO / "verify/llm_guard_burst.py"
PROXY = REPO / "gitops/ai-layer/guard-proxy/proxy.py"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
TOKEN = "t0ken-1172"
MIN_CPU = 3.0

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def cpu(v) -> float:
    s = str(v)
    return float(s[:-1]) / 1000 if s.endswith("m") else float(s)


# The fake LLM Guard. MODE is set per case; SEEN holds (body, authorization) of every call.
MODE = {"kind": "fast"}
SEEN: list[tuple[dict, str]] = []
SERIAL = threading.Lock()
# The serial case's burst size. The fake holds every scan until all of them have arrived (#1225), so the check on
# the queue holds however the client's threads are scheduled. Before, it needed all 20 sent within 0.05 s of each
# other, and on run 19503's host one run cleared its 0.95 s bound by 0.04 s.
QUEUE = 20
ARRIVED = threading.Barrier(QUEUE)


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        SEEN.append((body, self.headers.get("Authorization", "")))
        mode = MODE["kind"]
        if self.path != "/analyze/prompt":
            code, out = 404, {"detail": "Not Found"}
        elif mode == "408-long" and body.get("prompt", "").startswith("Ignore all previous"):
            code, out = 408, {"detail": "Request timeout."}
        else:
            if mode == "slow":
                time.sleep(0.3)
            elif mode == "serial":
                ARRIVED.wait(timeout=15)
                with SERIAL:
                    time.sleep(0.05)
            code, out = 200, {"sanitized_prompt": body.get("prompt"), "is_valid": True, "scanners": {}}
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Server(http.server.ThreadingHTTPServer):
    # socketserver's listen backlog is 5, and the bursts here send 12 and 20 at once. On a loaded host the calls past
    # it were held a second for a SYN retry or reset, and one reset is a status other than 200 (#1225).
    request_queue_size = 64


srv = Server(("127.0.0.1", 0), Fake)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"


def tool(mode: str, phases: list, *extra: str, url: str | None = URL) -> tuple[int, list[dict], str]:
    MODE["kind"] = mode
    SEEN.clear()
    env = {k: v for k, v in os.environ.items() if k != "LLM_GUARD_URL"} | {"LLM_GUARD_TOKEN": TOKEN}
    args = [sys.executable, "-I", str(TOOL), "--phases", json.dumps(phases), *extra]
    if url:
        args += ["--url", url]
    r = subprocess.run(args, capture_output=True, text=True, timeout=120, env=env)
    rows = [json.loads(ln) for ln in r.stdout.splitlines() if ln.startswith("{")]
    return r.returncode, rows, r.stdout + r.stderr


print("== the tool against a fake LLM Guard ==")
code, rows, out = tool("fast", [{"name": "b", "burst": 12, "mix": ["short", "medium", "long"]},
                                {"name": "r", "rate": 20, "secs": 0.5, "mix": ["long"]}])
check("a fast LLM Guard reads BURST GREEN, exit 0", code == 0 and "BURST GREEN" in out, out[-400:])
check("one JSON line per phase, named", [r["phase"] for r in rows] == ["b", "r"], str(rows))
check("a burst sends all of it and every call is counted 200",
      rows and rows[0]["sent"] == 12 and rows[0]["statuses"] == {"200": 12}, str(rows[:1]))
check("a rate phase sends rate x secs", len(rows) > 1 and rows[1]["sent"] == 10 and rows[1]["statuses"] == {"200": 10},
      str(rows[1:]))
check("the burst cycles through its mix", rows and {k: v["n"] for k, v in rows[0]["by_kind"].items()}
      == {"long": 4, "medium": 4, "short": 4}, str(rows[:1]))
check("every call carries guard-proxy's bearer token", len(SEEN) == 22 and all(a == f"Bearer {TOKEN}" for _, a in SEEN),
      f"{len(SEEN)} calls")
check("every call sends guard-proxy's input_verdict body",
      all(set(b) == {"prompt", "scanners_suppress"} and b["scanners_suppress"] == ["BanTopics"] for b, _ in SEEN))

anchor = '_post_guard("/analyze/prompt", {"prompt": text, "scanners_suppress": ["BanTopics"]}'
if not PROXY.is_file() or anchor not in PROXY.read_text():
    print(f"FAIL  {PROXY.relative_to(REPO)} no longer holds the literal {anchor!r}: input_verdict's body moved, "
          "so the tool's body is no longer known to be guard-proxy's", file=sys.stderr)
    sys.exit(1)
check("that body is the one the pinned proxy.py's input_verdict posts", True)

code, rows, out = tool("408-long", [{"name": "burst-x", "burst": 9, "mix": ["short", "medium", "long"]}])
check("a 408 reads BURST RED, exit 1, naming the phase", code == 1 and "BURST RED" in out and "burst-x: 3 not 200" in out,
      out[-400:])
check("the 408s are counted beside the 200s", rows and rows[0]["statuses"] == {"200": 6, "408": 3}, str(rows))

code, rows, out = tool("slow", [{"name": "s", "burst": 4, "mix": ["short"]}], "--timeout", "0.2")
check("a 200 past --timeout reads BURST RED", code == 1 and "s: 0 not 200, 4 of the 200s" in out, out[-400:])
check("and is counted in over_timeout", rows and rows[0]["over_timeout"] == 4, str(rows))

code, rows, out = tool("serial", [{"name": "q", "burst": QUEUE, "mix": ["long"]}])
# Which thread the fake serves first is the scheduler's choice, so the check is on what holds for every order:
# no scan starts before all 20 calls are in, 20 scans of 0.05 s one at a time take 1 s, and the one served last
# was sent before the first scan began, so it waited all of it.
check("a one-at-a-time LLM Guard shows the queue: the slowest of a burst of 20 waits for all 20 scans",
      rows and rows[0]["statuses"] == {"200": 20} and rows[0]["max"] >= 0.95 and rows[0]["wall_s"] >= 0.95, str(rows))

code, rows, out = tool("fast", [{"name": "w", "burst": 2, "mix": ["short"], "untimed": True}], "--timeout", "0")
check("an untimed phase (the warm-up) never turns the verdict red", code == 0 and "BURST GREEN" in out, out[-300:])

code, rows, out = tool("fast", [], url=None)
check("no --url and no LLM_GUARD_URL fails by name", code == 1 and "no LLM_GUARD_URL" in out, out[-300:])
code, rows, out = tool("fast", [{"name": "x", "burst": 1, "mix": ["huge"]}])
check("an unknown prompt kind fails by name", code == 1 and "unknown prompt kind(s) ['huge']" in out, out[-300:])

sys.path.insert(0, str(REPO / "verify"))
import llm_guard_burst as lgb  # noqa: E402

named = {p["name"]: p for p in lgb.DEFAULT_PHASES if "name" in p}
check("the default phases are #1172's: the cap of long prompts and the 50, 100 and 100-mixed bursts",
      named.get("cap-150/min-long", {}).get("rate") == 2.5 and named["cap-150/min-long"]["mix"] == ["long"]
      and named.get("burst-50-long", {}).get("burst") == 50 and named.get("burst-100-long", {}).get("burst") == 100
      and named.get("burst-100-mixed", {}).get("mix") == lgb.MIXED, str(sorted(named)))
check("the long prompt is about 40 words, as run 18563's was", 38 <= len(lgb.PROMPTS["long"].split()) <= 48,
      str(len(lgb.PROMPTS["long"].split())))
srv.shutdown()

print("== the capacity in the manifests ==")
docs = [d for d in yaml.safe_load_all(RESOURCES.read_text()) if d]
dep = next((d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "llm-guard"), None)
cm = next((d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "llm-guard-scanners"), None)
if dep is None or cm is None:
    print("FAIL  gitops/ai-layer/resources.yaml has no llm-guard Deployment or llm-guard-scanners ConfigMap",
          file=sys.stderr)
    sys.exit(1)
c = next(x for x in dep["spec"]["template"]["spec"]["containers"] if x["name"] == "llm-guard-api")
limit = cpu(c["resources"]["limits"]["cpu"])
check(f"llm-guard's CPU limit is at least {MIN_CPU:g} CPUs, the burst capacity #1172 measured", limit >= MIN_CPU,
      f"limit {limit:g}")
check("one replica, so the limit is the whole capacity the measurement read", dep["spec"].get("replicas") == 1,
      str(dep["spec"].get("replicas")))
workers = {e["name"]: e.get("value") for e in c.get("env", [])}.get("APP_WORKERS")
check("one uvicorn worker, as the image requires", workers == "1", str(workers))
timeout = float(yaml.safe_load(cm["data"]["scanners.yml"])["app"]["scan_prompt_timeout"])
m = re.search(r'"--timeout", type=float, default=([0-9.]+)', TOOL.read_text())
if m is None:
    print("FAIL  verify/llm_guard_burst.py has no '\"--timeout\", type=float, default=' argument to read", file=sys.stderr)
    sys.exit(1)
check("scan_prompt_timeout is the tool's default --timeout", float(m.group(1)) == timeout,
      f"scanners.yml {timeout:g}, tool {m.group(1)}")

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nThe burst replay holds its contract, and llm-guard keeps the CPU the room's bursts were measured with")
