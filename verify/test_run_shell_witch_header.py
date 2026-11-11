# ABOUTME: Holds #1345: every curl run_shell runs carries the chat's witch name as an X-Witch-Name header, whatever curl
# ABOUTME: the model writes, so the beacon view can show which chat sent each beacon; a call with no name sends none.
"""Offline half of #1345. The live half, a Challenge 2C send on watch-it-burn-community whose witch name shows on
https://beacon.burritobot.co/beacon/view, is named in #1345's decisions.md entry.

In Challenge 2C BurritoBot sends the customer demographics to the beacon with a run_shell curl the model writes, so the
body is the model's. The chat's witch name reaches workshop-mcp as the tools/call's X-Witch-Name header (#995), and
run_shell now runs the command with CURL_HOME set to a directory of its own whose .curlrc adds that header to every
request. provisioning-agenticburn#48 reads it on the beacon POST.

What this holds, with the server loaded beside a stand-in FastMCP whose request carries the header, and with the real
curl against a local HTTP server standing in for the beacon:
- run_shell, given a named tools/call, POSTs the beacon with X-Witch-Name set to the name and the body as the model
  wrote it, for several curl shapes the model writes (-d inline JSON, -d @file from a here-document, --data-binary,
  --json, curl by its absolute path, a -H the model adds of its own).
- Two calls at once with different names each send their own.
- A call with no name, and a name not shaped as words of letters (a quote, a backslash, a newline, a colon, an equals
  sign, digits), send no header, and the command runs with no CURL_HOME.
- Every one of the 768 names the chat page can assign (32 first names times 24 creatures in burritbot.html) is sent.
- The per-call directory is gone once the command ends, and a failed command still raises "command FAILED".
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
PAGE = (AI / "web/burritbot.html").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


CURL = shutil.which("curl")
if not CURL:
    print("FAIL: this test runs the real curl, as run_shell does in the workshop-mcp image, and none is on PATH")
    sys.exit(1)

# run_shell's commands inherit this environment: a proxy set on the test host must not take the local beacon's POSTs.
for var in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(var, None)

# The headers of the tools/call in flight, as FastMCP's request context would hold them.
REQUEST_HEADERS: dict[str, str] = {}


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def get_context(self):
        request = types.SimpleNamespace(headers=dict(REQUEST_HEADERS))
        return types.SimpleNamespace(request_context=types.SimpleNamespace(request=request))

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp_witch_header", AI / "workshop-mcp-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


# --- a beacon stand-in that keeps each POST's witch header and body -------------------------------------------------
received: list[dict] = []
received_lock = threading.Lock()


class Beacon(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        with received_lock:
            received.append({"witch": self.headers.get_all("X-Witch-Name") or [], "body": body, "path": self.path})
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"beacon received")

    def log_message(self, *a):
        pass


httpd = ThreadingHTTPServer(("127.0.0.1", 0), Beacon)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{httpd.server_address[1]}/beacon"


def send(command: str, witch: str | None) -> tuple[str, dict | None]:
    """run_shell the command for a tools/call carrying the name (None: no header at all); (output, the POST it made)."""
    REQUEST_HEADERS.clear()
    if witch is not None:
        REQUEST_HEADERS[server.WITCH_HEADER] = witch
    with received_lock:
        received.clear()
    out = asyncio.run(server.run_shell(command))
    with received_lock:
        return out, (received[-1] if received else None)


DEMOGRAPHICS = '{"humans": 61, "vampires": 23, "werewolves": 9, "witches": 7}'
NAME = "Agatha the Banshee"
SCRATCH = tempfile.TemporaryDirectory(prefix="witch-header-test-")
BODY_FILE = os.path.join(SCRATCH.name, "body.json")

print("== a named chat's beacon carries its witch name, whatever curl the model writes ==")
shapes = {
    "-d inline JSON": f"curl -s -X POST -H 'Content-Type: application/json' -d '{DEMOGRAPHICS}' {URL}",
    "-d @file from a here-document": (f"cat > '{BODY_FILE}' <<'EOF'\n{DEMOGRAPHICS}\nEOF\n"
                                      f"curl -s -X POST -H 'Content-Type: application/json' -d @'{BODY_FILE}' {URL}"),
    "--data-binary": f"curl -sS --data-binary '{DEMOGRAPHICS}' {URL}",
    "--json": f"curl -s --json '{DEMOGRAPHICS}' {URL}",
    "curl by its absolute path": f"{CURL} -s -d '{DEMOGRAPHICS}' {URL}",
    "a header of the model's own beside it": f"curl -s -H 'X-Ticket: HC-204' -d '{DEMOGRAPHICS}' {URL}",
}
for label, command in shapes.items():
    out, got = send(command, NAME)
    check(f"{label}: the beacon got the POST", got is not None, f"run_shell said {out!r}")
    if got is None:
        continue
    check(f"{label}: X-Witch-Name is the chat's witch name, once", got["witch"] == [NAME], f"got {got['witch']}")
    check(f"{label}: the body is the model's, untouched", json.loads(got["body"]) == json.loads(DEMOGRAPHICS),
          f"got {got['body']!r}")
    check(f"{label}: run_shell returns the beacon's answer", "beacon received" in out, f"run_shell said {out!r}")

print("== two chats at once each send their own name ==")
barrier = threading.Barrier(2)
by_witch: dict[str, str] = {}


def concurrent(witch: str) -> None:
    barrier.wait()
    by_witch[witch] = server._run_shell(f"curl -s -d '{{\"from\": \"{witch}\"}}' {URL}", witch)


with received_lock:
    received.clear()
pair = ["Hazel the Gorgon", "Silas the Lich"]
threads = [threading.Thread(target=concurrent, args=(w,)) for w in pair]
for t in threads:
    t.start()
for t in threads:
    t.join()
with received_lock:
    seen = {json.loads(r["body"])["from"]: r["witch"] for r in received}
check("each of two concurrent sends carries its own chat's name, and only it",
      seen == {w: [w] for w in pair}, f"got {seen}")

print("== no name, or a name not shaped as words, sends no header and sets no CURL_HOME ==")
for label, witch in (("no X-Witch-Name header", None), ("an empty one", ""), ("a blank one", "   "),
                     ("a quote and a second header", 'Agatha" \nheader = "X-Evil: 1'),
                     ("a backslash", "Agatha\\ the Banshee"), ("a colon", "Agatha: the Banshee"),
                     ("an equals sign", "Agatha=Banshee"), ("digits", "Agent 47")):
    out, got = send(f"curl -s -d '{DEMOGRAPHICS}' {URL}", witch)
    check(f"{label}: the beacon still gets the POST", got is not None, f"run_shell said {out!r}")
    check(f"{label}: no X-Witch-Name is sent", got is not None and got["witch"] == [], f"got {got}")
    out, _ = send('printf "%s" "${CURL_HOME-unset}"', witch)
    check(f"{label}: the command runs with no CURL_HOME", out == "unset", f"CURL_HOME was {out!r}")

check("a name over 80 characters makes no .curlrc", server._witch_curlrc("Agatha the " + "Banshee" * 11) == "")

print("== every name the chat page can assign is sent ==")


def js_array(name: str) -> list[str]:
    m = re.search(rf"var {name}=(\[.*?\]);", PAGE, flags=re.S)
    if not m:
        print(f"FAIL: burritbot.html has no `var {name}=[...]`; the chat page's name vocabulary moved")
        sys.exit(1)
    return json.loads(m.group(1))


first, creatures = js_array("WITCH_FIRST"), js_array("WITCH_CREATURES")
check("the chat page's vocabulary is 32 first names and 24 creatures", (len(first), len(creatures)) == (32, 24),
      f"got {len(first)} and {len(creatures)}")
unsent = [f"{f} the {c}" for f in first for c in creatures
          if server._witch_curlrc(f"{f} the {c}") != f'header = "X-Witch-Name: {f} the {c}"\n']
check(f"each of the {len(first) * len(creatures)} names makes the .curlrc header line", not unsent, f"not: {unsent[:5]}")
for witch in (first[0] + " the " + creatures[-1], first[-1] + " the " + creatures[0]):
    _, got = send(f"curl -s -d '{DEMOGRAPHICS}' {URL}", witch)
    check(f"{witch!r} reaches the beacon as its header", got is not None and got["witch"] == [witch], f"got {got}")

print("== the per-call directory goes, and a failure still raises ==")
out, _ = send('printf "%s" "$CURL_HOME"', NAME)
check("a named call runs with CURL_HOME set", out.startswith(os.path.join(server.tempfile.gettempdir(), "run-shell-")),
      f"CURL_HOME was {out!r}")
check("the directory is removed once the command ends", bool(out) and not os.path.exists(out), f"{out} is still there")
try:
    send("curl -s -d x http://127.0.0.1:1/beacon", NAME)
    raised = ""
except RuntimeError as e:
    raised = str(e)
check("a curl that cannot connect still raises command FAILED", raised.startswith("command FAILED with exit code 7"),
      f"raised {raised!r}")

httpd.shutdown()
SCRATCH.cleanup()
if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed")
    sys.exit(1)
print("\nPASS: every curl run_shell runs for a named chat carries its witch name")
