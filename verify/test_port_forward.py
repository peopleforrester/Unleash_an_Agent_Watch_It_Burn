# ABOUTME: Offline check of verify/port_forward.py against a stub kubectl: the port-forward it asks for, the GET it sends,
# ABOUTME: the reply on a 200 and a 404, kubectl's reason when it never comes up, and nothing left running (#998).
"""On 2026-11-06 and 2026-11-07, test_deployments_page_live.py's step 1 hung on both KubeCon clusters: it read
/deployments.json through the API server's Service proxy, and the control plane cannot dial a pod on 8080 there
(#998). Step 1 now reads it with port_forward.get over a port-forward to svc/fake-ticket:8080.

No cluster here. The stub kubectl refuses any call without the expected --context, takes only a loopback
port-forward to :8080, prints the line kubectl prints once its listener is up, and answers GETs as the fake-ticket
desk does. That fake-ticket answers on a real cluster is test_deployments_page_live.py's question.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import port_forward  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


STUB = textwrap.dedent('''
    import json, os, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    args = sys.argv[1:]
    log = os.environ["STUB_LOG"]
    with open(log + ".argv", "w") as f:
        json.dump(args, f)
    if args[:2] != ["--context", "wib-test"]:
        sys.exit("stub kubectl: no --context wib-test")
    if args[2:6] != ["-n", "agent", "port-forward", "--address"] or args[6] != "127.0.0.1" or args[8] != ":8080":
        sys.exit(f"stub kubectl: not a loopback port-forward to :8080: {args}")
    if os.environ["STUB_MODE"] == "nostart":
        sys.stderr.write("error: unable to forward port because pod is not running. Current status=Pending\\n")
        sys.exit(1)
    with open(log + ".pid", "w") as f:
        f.write(str(os.getpid()))
    LISTED = [{"name": "tron", "image": "public.ecr.aws/docker/library/nginx:latest", "witch": "Prudence",
               "at": "2026-11-07T10:00:00Z", "padding": "x" * 500}]

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            with open(log, "w") as f:
                json.dump({"path": self.path}, f)
            if self.path == "/deployments.json":
                code, body = 200, json.dumps(LISTED)
            else:
                code, body = 404, "no such ticket"
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    print("Forwarding from 127.0.0.1:%d -> 8080" % srv.server_address[1], flush=True)
    srv.serve_forever()
''')


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


with tempfile.TemporaryDirectory() as tmp:
    stub = pathlib.Path(tmp, "kubectl.py")
    stub.write_text(STUB)
    log = pathlib.Path(tmp, "request.json")
    kubectl = [sys.executable, str(stub), "--context", "wib-test"]

    def run(mode: str, path: str, ctx: list[str] = kubectl) -> tuple[str, str, str]:
        os.environ.update(STUB_MODE=mode, STUB_LOG=str(log))
        for p in (log, pathlib.Path(f"{log}.pid")):
            p.unlink(missing_ok=True)
        return port_forward.get(ctx, "agent", "svc/fake-ticket", 8080, path, timeout=10)

    print("== a 200 through the port-forward ==")
    status, body, err = run("ok", "/deployments.json")
    check("the port-forward came up and the GET was made", status == "200" and not err, f"{status} {err}")
    argv = json.loads(pathlib.Path(f"{log}.argv").read_text())
    check("it forwards the Service's :8080 on loopback, with the context it was given",
          argv == ["--context", "wib-test", "-n", "agent", "port-forward", "--address", "127.0.0.1",
                   "svc/fake-ticket", ":8080"], f"{argv}")
    sent = json.loads(log.read_text()) if log.exists() else {}
    check("the GET goes to the path it was given", sent.get("path") == "/deployments.json", f"{sent}")
    try:
        listed = json.loads(body)
    except json.JSONDecodeError:
        listed = None
    check("the body comes back whole, so a long list still parses as JSON",
          isinstance(listed, list) and listed[0]["witch"] == "Prudence", body[:200])
    pid = int(pathlib.Path(f"{log}.pid").read_text())
    check("the port-forward is stopped once the GET is done", not alive(pid), f"pid {pid} still running")

    print("== a 404 from the app ==")
    status, body, err = run("ok", "/HC-666")
    check("the status is the app's, not an error of the helper's", status == "404" and not err, f"{status} {err}")
    check("the app's body is in the reply", "no such ticket" in body, body)
    pid = int(pathlib.Path(f"{log}.pid").read_text())
    check("the port-forward is stopped after a 404 too", not alive(pid), f"pid {pid} still running")

    print("== a port-forward that never comes up ==")
    status, body, err = run("nostart", "/deployments.json")
    check("no request is made and nothing reads as a status", status == "" and body == "" and not log.exists(),
          f"{status!r} {body!r}")
    check("the error carries kubectl's own reason", "pod is not running" in err, err)
    status, body, err = run("ok", "/deployments.json", [sys.executable, str(stub), "--context", "someone-elses"])
    check("a kubectl that refuses the context is an error, never a call", status == "" and "wib-test" in err, err)

print("== test_deployments_page_live.py reads /deployments.json this way, not through the Service proxy ==")
live = (REPO / "verify" / "test_deployments_page_live.py").read_text()
check("step 1 calls port_forward.get on svc/fake-ticket:8080 for /deployments.json",
      "port_forward.get(" in live and '"--context", CONTEXT], "agent", "svc/fake-ticket", 8080,' in live
      and '"/deployments.json")' in live)
check("no read in it goes through the API server's Service proxy", "/proxy/" not in live)
r = subprocess.run([sys.executable, "-c", "import ast,sys; ast.parse(open(sys.argv[1]).read())",
                    str(REPO / "verify" / "test_deployments_page_live.py")], capture_output=True, text=True)
check("test_deployments_page_live.py parses", r.returncode == 0, r.stderr[-300:])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("PASS: port_forward.get makes one GET over a port-forward and leaves nothing running")
