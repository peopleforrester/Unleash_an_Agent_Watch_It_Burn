# ABOUTME: The host half of the wib-e2e-tools image's gh (#1188): serves `gh issue view ...` from inside the container
# ABOUTME: with the host's own gh and login, over a Unix socket verify/e2e-image.sh mounts. Every other gh call is refused.
"""Usage: python3 verify/gh_relay.py serve <socket> [--gh <path>]

Inside the image, verify/e2e-image/gh is the gh on PATH. It sends one JSON line, {"argv": [...]}, to this server and
prints what comes back, {"rc": n, "stdout": "...", "stderr": "..."}. The server runs the host's gh with that argv only
when it begins `issue view`, the one read verify/gh_comments.py makes (#863); anything else gets exit 2 and a line
naming what was refused, so the container cannot reach the host's gh for a write. The host's gh is found on PATH when
the server starts (the hecaton wrapper on a dispatched run, the runner's gh with the job's GH_TOKEN in CI); none is a
failure before any test runs.

The socket is made mode 0600 in a directory the caller made. The server runs until it is stopped; verify/e2e-image.sh
stops it when the container ends.
"""
from __future__ import annotations

import json
import os
import shutil
import socketserver
import subprocess
import sys

ALLOWED = ("issue", "view")
TIMEOUT = 300
MAX_REQUEST = 1 << 16


def answer(gh: str, request: bytes) -> dict:
    """The reply to one request line: the host gh's result, or why it was refused."""
    try:
        argv = json.loads(request).get("argv")
    except (ValueError, AttributeError):
        return {"rc": 2, "stdout": "", "stderr": "gh relay: the request is not a JSON object with an argv list\n"}
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        return {"rc": 2, "stdout": "", "stderr": "gh relay: argv must be a list of strings\n"}
    if tuple(argv[:2]) != ALLOWED:
        return {"rc": 2, "stdout": "",
                "stderr": f"gh relay: only `gh issue view` is relayed to the host, not `gh {' '.join(argv)}`\n"}
    try:
        p = subprocess.run([gh, *argv], capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"rc": 1, "stdout": "", "stderr": f"gh relay: the host's gh did not answer within {TIMEOUT}s\n"}
    except OSError as e:
        return {"rc": 1, "stdout": "", "stderr": f"gh relay: cannot run the host's gh {gh}: {e}\n"}
    return {"rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def serve(path: str, gh: str) -> None:
    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            line = self.rfile.readline(MAX_REQUEST)
            self.wfile.write(json.dumps(answer(gh, line)).encode() + b"\n")

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    old = os.umask(0o177)
    try:
        server = Server(path, Handler)
    finally:
        os.umask(old)
    print(f"gh relay: serving `gh issue view` from {gh} at {path}", flush=True)
    server.serve_forever()


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 4) or argv[0] != "serve" or (len(argv) == 4 and argv[2] != "--gh"):
        print(__doc__.splitlines()[0], file=sys.stderr)
        return 2
    gh = argv[3] if len(argv) == 4 else shutil.which("gh")
    if not gh:
        print("GH RELAY FAILED: no gh on the host's PATH; the tier's cause-comment tests read issues with it (#863)",
              file=sys.stderr)
        return 1
    serve(argv[1], gh)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
