# ABOUTME: Offline check of verify/gateway_forward.py against a stub kubectl: the port-forward it asks for, the chat it
# ABOUTME: sends over it, Bedrock's reply on a 200 and on a refusal, and no port-forward left running afterwards (#583).
"""On watch-it-burn-community on 2026-10-31 the live Bedrock check got as far as the model call and failed there,
because it ran `python3 -c` inside the workshop-agent pod and the kagent container would not exec it (#583).
gateway_forward sends the call from this host instead, over a kubectl port-forward to the gateway's :3002.

No cluster here. The stub kubectl refuses any call without the expected --context, takes only a loopback
port-forward to :3002, prints the line kubectl prints once its listener is up, and answers the way agentgateway's
bedrock route does. Whether Bedrock takes the escaped ARN is verify/test_gateway_bedrock_tagged_live.py's question,
on a cluster.
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
import gateway_forward  # noqa: E402

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
    if args[2:6] != ["-n", "agent", "port-forward", "--address"] or args[6] != "127.0.0.1" or args[8] != ":3002":
        sys.exit(f"stub kubectl: not a loopback port-forward to :3002: {args}")
    mode = os.environ["STUB_MODE"]
    if mode == "nostart":
        sys.stderr.write("error: unable to forward port because pod is not running. Current status=Pending\\n")
        sys.exit(1)
    with open(log + ".pid", "w") as f:
        f.write(str(os.getpid()))
    REPLY = {
        "ok": (200, json.dumps({"id": "c1", "object": "chat.completion", "model": "bedrock-nova",
                                "choices": [{"index": 0, "finish_reason": "length",
                                             "message": {"role": "assistant", "content": "OK"}}],
                                "usage": {"prompt_tokens": 12, "completion_tokens": 1, "total_tokens": 13},
                                "padding": "x" * 500})),
        "denied": (403, json.dumps({"message": "The request signature we calculated does not match the signature "
                                               "you provided."})),
    }[mode]

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["content-length"]))
            with open(log, "w") as f:
                json.dump({"path": self.path, "body": json.loads(body),
                           "type": self.headers.get("content-type")}, f)
            self.send_response(REPLY[0])
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(REPLY[1].encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    print("Forwarding from 127.0.0.1:%d -> 3002" % srv.server_address[1], flush=True)
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

    def run(mode: str, ctx: list[str] = kubectl) -> tuple[str, str, str]:
        os.environ.update(STUB_MODE=mode, STUB_LOG=str(log))
        for p in (log, pathlib.Path(f"{log}.pid")):
            p.unlink(missing_ok=True)
        return gateway_forward.chat(ctx, "agent", "pod/agentgateway-abc", "bedrock", "bedrock-nova", timeout=10)

    print("== a 200 through the port-forward ==")
    status, reply, err = run("ok")
    check("the port-forward came up and the request was made", status == "200" and not err, f"{status} {err}")
    argv = json.loads(pathlib.Path(f"{log}.argv").read_text())
    check("it forwards the named pod's :3002 on loopback, with the context it was given",
          argv == ["--context", "wib-test", "-n", "agent", "port-forward", "--address", "127.0.0.1",
                   "pod/agentgateway-abc", ":3002"], f"{argv}")
    sent = json.loads(log.read_text()) if log.exists() else {}
    check("the request goes to the route's chat completions path", sent.get("path") == "/bedrock/v1/chat/completions",
          f"{sent.get('path')}")
    body = sent.get("body") or {}
    check("it asks for the gateway-bedrock-nova model and at most 5 tokens",
          body.get("model") == "bedrock-nova" and body.get("max_tokens") == 5, f"{body}")
    check("it is one user message, sent as JSON",
          [m.get("role") for m in body.get("messages", [])] == ["user"] and sent.get("type") == "application/json",
          f"{sent}")
    try:
        choices = json.loads(reply).get("choices")
    except json.JSONDecodeError:
        choices = None
    check("the reply comes back whole, so a long completion still parses as JSON", bool(choices), reply[:200])
    pid = int(pathlib.Path(f"{log}.pid").read_text())
    check("the port-forward is stopped once the call is done", not alive(pid), f"pid {pid} still running")

    print("== a refusal from Bedrock ==")
    status, reply, err = run("denied")
    check("the status is the gateway's, not an error of the helper's", status == "403" and not err, f"{status} {err}")
    check("Bedrock's message is in the reply, so the live failure shows it", "signature" in reply, reply)
    pid = int(pathlib.Path(f"{log}.pid").read_text())
    check("the port-forward is stopped after a refusal too", not alive(pid), f"pid {pid} still running")

    print("== a port-forward that never comes up ==")
    status, reply, err = run("nostart")
    check("no request is made and nothing reads as a status", status == "" and reply == "" and not log.exists(),
          f"{status!r} {reply!r}")
    check("the error carries kubectl's own reason", "pod is not running" in err, err)
    status, reply, err = run("ok", [sys.executable, str(stub), "--context", "someone-elses"])
    check("a kubectl that refuses the context is an error, never a call", status == "" and "wib-test" in err, err)

print("== the live checks use it, and no longer exec into the agent pod ==")
for name in ("test_gateway_bedrock_tagged_live.py", "local-inference-live.py"):
    text = (REPO / "verify" / name).read_text()
    check(f"{name} sends its model call through gateway_forward.chat", "gateway_forward.chat(" in text)
    check(f"{name} runs nothing inside workshop-agent",
          '"exec", "deploy/workshop-agent"' not in text and '"python3", "-c"' not in text)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("PASS: gateway_forward makes one chat call over a port-forward and leaves nothing running")
