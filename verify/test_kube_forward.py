# ABOUTME: Offline check of verify/kube_forward.py against a stub kubectl, and that the deployments page's live test reads
# ABOUTME: /deployments.json over a port-forward to svc/fake-ticket :8080, not the API server's service proxy (#998).
"""On 2026-11-06 and again on 2026-11-07, `kubectl get --raw /api/v1/namespaces/agent/services/fake-ticket:8080/proxy/
deployments.json` timed out on both KubeCon clusters. The service proxy dials the pod from the control-plane ENIs,
and neither cluster's node security group admits the cluster security group on 8080 (#869's rule is in the root,
not in AWS). verify/test_deployments_page_live.py's step 1 now reads the feed over a kubectl port-forward, which
goes through the kubelet on :10250.

No cluster here. The stub kubectl refuses any call without the expected --context, takes only a loopback
port-forward to the asked port, prints the line kubectl prints once its listener is up, and answers GETs the way
fake-ticket does.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import textwrap

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import kube_forward  # noqa: E402

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
    mode = os.environ["STUB_MODE"]
    if mode == "nostart":
        sys.stderr.write("error: unable to forward port because pod is not running. Current status=Pending\\n")
        sys.exit(1)
    with open(log + ".pid", "w") as f:
        f.write(str(os.getpid()))
    FEED = [{"name": "tron", "image": "public.ecr.aws/docker/library/nginx:latest", "witch": "Prudence",
             "at": "2026-11-07T08:00:00Z"}]

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            with open(log, "w") as f:
                json.dump({"path": self.path}, f)
            if mode == "missing" or self.path != "/deployments.json":
                code, body = 404, "not found"
            else:
                code, body = 200, json.dumps(FEED)
            self.send_response(code)
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
    # A stopped child that this process has not reaped is a zombie, not a running port-forward.
    try:
        return pathlib.Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


with tempfile.TemporaryDirectory() as tmp:
    stub = pathlib.Path(tmp, "kubectl.py")
    stub.write_text(STUB)
    log = pathlib.Path(tmp, "request.json")
    kubectl = [sys.executable, str(stub), "--context", "wib-test"]

    def run(mode: str, ctx: list[str] = kubectl, path: str = "/deployments.json") -> tuple[str, str, str]:
        os.environ.update(STUB_MODE=mode, STUB_LOG=str(log))
        for p in (log, pathlib.Path(f"{log}.pid"), pathlib.Path(f"{log}.argv")):
            p.unlink(missing_ok=True)
        return kube_forward.get(ctx, "agent", "svc/fake-ticket", 8080, path, timeout=10)

    print("== a 200 through the port-forward ==")
    status, body, err = run("ok")
    check("the port-forward came up and the GET was answered", status == "200" and not err, f"{status} {err}")
    argv = json.loads(pathlib.Path(f"{log}.argv").read_text())
    check("it forwards svc/fake-ticket's :8080 on loopback, with the context it was given",
          argv == ["--context", "wib-test", "-n", "agent", "port-forward", "--address", "127.0.0.1",
                   "svc/fake-ticket", ":8080"], f"{argv}")
    sent = json.loads(log.read_text()) if log.exists() else {}
    check("the GET asks for the path it was given", sent.get("path") == "/deployments.json", f"{sent}")
    try:
        feed = json.loads(body)
    except json.JSONDecodeError:
        feed = None
    check("the body comes back whole, as the JSON list fake-ticket sent",
          isinstance(feed, list) and feed and feed[0].get("name") == "tron", body[:200])
    pid = int(pathlib.Path(f"{log}.pid").read_text())
    check("the port-forward is stopped once the GET is done", not alive(pid), f"pid {pid} still running")

    print("== a 404 from the app ==")
    status, body, err = run("missing")
    check("the status is the app's, not an error of the helper's", status == "404" and not err, f"{status} {err}")
    pid = int(pathlib.Path(f"{log}.pid").read_text())
    check("the port-forward is stopped after a 404 too", not alive(pid), f"pid {pid} still running")

    print("== a port-forward that never comes up ==")
    status, body, err = run("nostart")
    check("no GET is made and nothing reads as a status", status == "" and body == "" and not log.exists(),
          f"{status!r} {body!r}")
    check("the error names the target and port and carries kubectl's own reason",
          "svc/fake-ticket :8080" in err and "pod is not running" in err, err)
    status, body, err = run("ok", [sys.executable, str(stub), "--context", "someone-elses"])
    check("a kubectl that refuses the context is an error, never a GET", status == "" and "wib-test" in err, err)

print("== the deployments page's live test reads the feed over the port-forward ==")
live_path = REPO / "verify" / "test_deployments_page_live.py"
live = live_path.read_text()
anchor = '== 1. the fake-ticket site answers /deployments.json =='
if anchor not in live:
    sys.exit(f"anchor {anchor!r} is not in {live_path}: step 1's heading was reworded; update this test with it")
step1 = live.split(anchor, 1)[1].split("== 2.", 1)[0]
check("step 1 calls kube_forward.get on svc/fake-ticket :8080 for /deployments.json, with --context CONTEXT",
      re.search(r'kube_forward\.get\(\[\s*"kubectl",\s*"--context",\s*CONTEXT\s*\],\s*"agent",\s*"svc/fake-ticket",'
                r'\s*8080,\s*"/deployments\.json"', step1) is not None, step1[:400])
check("no part of the live test reads fake-ticket through the API server's service proxy",
      "/proxy/" not in live and "services/fake-ticket" not in live)
check("it imports kube_forward from verify/", "import kube_forward" in live)

print("== gateway_forward's chat uses the same port-forward ==")
gw = (REPO / "verify" / "gateway_forward.py").read_text()
check("gateway_forward.chat opens its port-forward through kube_forward.forward",
      "kube_forward.forward(kubectl, namespace, target, PORT)" in gw and "subprocess.Popen" not in gw)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("PASS: kube_forward makes one GET over a port-forward, leaves nothing running, and step 1 of the deployments "
      "page's live test uses it")
