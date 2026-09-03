# ABOUTME: Checks the guard-proxy rejects a cross-origin browser POST (#151) and no longer advertises
# ABOUTME: Access-Control-Allow-Origin: *. Runs the real Handler on a local port; no cluster needed.
import importlib.util
import json
import pathlib
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "gitops" / "ai-layer" / "proxy.py"

spec = importlib.util.spec_from_file_location("guard_proxy_under_test", SRC)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


srv = ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def call(method, path, origin=None, body=None, ctype="application/json"):
    """Returns (status, headers, body-text). A dead upstream is a normal outcome here."""
    data = body.encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", ctype)
    if origin:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, dict(r.headers), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


CONSOLE = "https://start.agenticburn.com"

# The attack from #151, in both the shapes that worked against a live cluster. text/plain matters:
# it is a CORS-simple request, so a browser sends it with no preflight to stop it.
for path in ("/chat", "/a2a/"):
    for ctype in ("application/json", "text/plain"):
        st, _, txt = call("POST", path, origin="https://evil.example", body="{}", ctype=ctype)
        check(f"POST {path} ({ctype}) from a hostile origin is rejected",
              st == 403 and "cross-origin" in txt)

# A request with no Origin is not a browser cross-origin call: the in-cluster A2A hop, the verify
# probes and curl all land here and must not be broken by the gate. It is allowed THROUGH the gate,
# which with no agent behind it means anything except a 403.
st, _, _ = call("POST", "/chat", body='{"prompt":"hello"}')
check("POST /chat with no Origin passes the gate (in-cluster and probe traffic)", st != 403)

# The attendee's own console page is served from the cluster's own hostname, so its Origin is that
# host. Host here is 127.0.0.1, which is what the local server sees.
st, _, _ = call("POST", "/chat", origin=f"http://127.0.0.1:{srv.server_address[1]}",
                body='{"prompt":"hello"}')
check("POST /chat from the cluster's own page passes the gate", st != 403)

st, _, _ = call("POST", "/chat", origin=CONSOLE, body='{"prompt":"hello"}')
check("POST /chat from the instructor console passes the gate", st != 403)

# CORS: never a wildcard, echoed only for an allowed origin.
st, hdr, _ = call("GET", "/cost")
check("GET /cost still answers", st == 200)
check("GET /cost sends no Access-Control-Allow-Origin when there is no Origin",
      "Access-Control-Allow-Origin" not in hdr)

st, hdr, _ = call("GET", "/cost", origin=CONSOLE)
check("GET /cost echoes the instructor console origin",
      hdr.get("Access-Control-Allow-Origin") == CONSOLE)
check("GET /cost sets Vary: Origin so a cache cannot cross the two", hdr.get("Vary") == "Origin")

st, hdr, _ = call("GET", "/cost", origin="https://evil.example")
check("GET /cost does NOT let a hostile origin read the spend",
      "Access-Control-Allow-Origin" not in hdr)

st, hdr, _ = call("GET", "/prompts", origin="https://evil.example")
check("GET /prompts does NOT let a hostile origin read the moderated feed",
      "Access-Control-Allow-Origin" not in hdr)

check("no wildcard Access-Control-Allow-Origin remains in the source",
      '"Access-Control-Allow-Origin", "*"' not in SRC.read_text())

# Absent on purpose: a failed preflight is a second layer under the Origin check, so a cross-origin
# JSON POST is blocked by the browser before it is ever sent.
check("do_OPTIONS stays absent so a cross-origin preflight keeps failing",
      not hasattr(proxy.Handler, "do_OPTIONS"))

srv.shutdown()
print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'All origin-guard checks passed.'}")
sys.exit(1 if failures else 0)
