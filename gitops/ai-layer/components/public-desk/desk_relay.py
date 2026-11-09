# ABOUTME: The admin KubeCon cluster's way to the public support desk (#1158): one ticket by its number, and a deploy
# ABOUTME: report sent with the desk's token. A fixed upstream and nothing else, so it is no route out for the bot.
"""desk-relay: what workshop-mcp's TICKET_SITE_URL points at on the kubecon-private profile (#1158, part of #1145).

On the KubeCon pair one support desk and one deployments page serve both clusters' bots, at the public addresses
(support.burritobot.co and deployments.burritobot.co, the community cluster's fake-ticket, #1157). The private
cluster's workshop-mcp reaches them through this pod and no other way:

    GET  /ticket?id=<number>   -> GET  <DESK_PUBLIC_URL>/ticket?id=<number>, the desk's answer as it is
    POST /landed               -> POST <DESK_PUBLIC_URL>/remote-landed with X-Desk-Report-Token, the answer as it is
    POST /cluster-read         -> POST <DESK_PUBLIC_URL>/remote-cluster-read with X-Desk-Report-Token, the answer as it is
    GET  /healthz              -> this relay's own state
    anything else              -> 404

So read_support_ticket still reads one ticket by its number and no list (#1077): the relay passes no other desk path,
and the desk's /ticket answers only the one id it is given. deploy_app's report lands on the public deployments page
under "private", the label the public desk gives a report that came with its token (#1157). The private cluster's
reader (#1050) posts what this cluster still runs to the same desk, with the same token (#1209), and the public desk
applies that read to the rows labelled private alone, so a deploy Kyverno's remove-untrusted-room-workloads deletes here
shows greyed on deployments.burritobot.co, and a read from here never greys a community row. This cluster's own desk
gets no deploy report from this cluster's bot, so it needs no read either, and the relay reaches no in-cluster desk.

Why a pod of its own and not an egress allow on workshop-mcp: support.burritobot.co, beacon.burritobot.co and the
registry share one router address (153.52.255.114, measured 2026-11-08), and a NetworkPolicy cannot name a host, so
any allow that reached the desk from workshop-mcp would also reach Challenge 1's beacon, from the pod run_shell runs
in. This pod builds every URL itself from DESK_PUBLIC_URL, and its label is on the Kyverno egressLabels list, so the
agent cannot mint a pod that borrows its egress (policies/kyverno/restrict-agent-spawned-workloads.yaml).

The token is read from DESK_REPORT_TOKEN_FILE on each report and each read, so the desk-report-token Secret can be
written after this pod starts (fleet.sh desk-link) and needs no restart. With no token, a report or a read is refused
here with a 503 naming the Secret, and nothing is sent.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN_HEADER = "X-Desk-Report-Token"   # the public desk's header (#1157, ticket_site.REMOTE_TOKEN_HEADER)
MAX_REPORT = 4 * 1024                  # the public console's client_max_body_size for /remote-landed
MAX_READ = 512 * 1024                  # the desk's MAX_READ_BODY, and the public console's limit for /remote-cluster-read
MAX_ID = 40                            # the desk keeps a ticket id to 40 characters
TIMEOUT = 5


def _base(name: str) -> str:
    url = os.environ.get(name, "").strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        raise SystemExit(f"desk-relay: {name} must be the desk's base URL (got {url!r})")
    return url


def report_token() -> str:
    """The desk's report token, read fresh each time; "" when the Secret has not been written."""
    try:
        with open(os.environ.get("DESK_REPORT_TOKEN_FILE", "/var/run/desk-report-token/token"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def forward(method: str, url: str, body: bytes | None = None, headers: dict | None = None) -> tuple[int, bytes]:
    """One request to a desk; its status and body, or a 502 naming what failed."""
    req = urllib.request.Request(url, method=method, data=body,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        return 502, json.dumps({"error": f"the support desk did not answer: {e}"}).encode()


class Handler(BaseHTTPRequestHandler):
    public = ""

    def log_message(self, fmt: str, *args) -> None:  # one line per request, without the query (a ticket number)
        print(f"desk-relay: {self.command} {urllib.parse.urlsplit(self.path).path} -> {args[1] if len(args) > 1 else ''}",
              flush=True)

    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode())

    def _body(self, limit: int) -> bytes | None:
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            self._json(413, {"error": f"at most {limit} bytes"})
            return None
        return self.rfile.read(n)

    def do_GET(self) -> None:  # noqa: N802
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/healthz":
            self._json(200, {"ok": True, "desk": self.public, "token": bool(report_token())})
            return
        if url.path != "/ticket":
            self._json(404, {"error": "not found: this relay reads one ticket by its number, nothing else"})
            return
        ids = urllib.parse.parse_qs(url.query).get("id") or []
        tid = ids[0].strip() if len(ids) == 1 else ""
        if not tid or len(tid) > MAX_ID:
            self._json(400, {"error": "give one ticket number, e.g. /ticket?id=HC-7731"})
            return
        self._send(*forward("GET", f"{self.public}/ticket?{urllib.parse.urlencode({'id': tid})}"))

    def do_POST(self) -> None:  # noqa: N802
        # Each POST this relay takes, and where it sends it on the public desk with the token: a deploy report, and a
        # cluster read (#1209), each at the size the public console takes.
        routes = {"/landed": ("/remote-landed", MAX_REPORT), "/cluster-read": ("/remote-cluster-read", MAX_READ)}
        path = urllib.parse.urlsplit(self.path).path
        if path not in routes:
            self._json(404, {"error": "not found: this relay reports a deploy and a cluster read, nothing else"})
            return
        upstream, limit = routes[path]
        raw = self._body(limit)
        if raw is None:
            return
        token = report_token()
        if not token:
            self._json(503, {"error": "no desk report token: write the agent/desk-report-token Secret "
                                      "(fleet.sh desk-link)"})
            return
        self._send(*forward("POST", f"{self.public}{upstream}", raw, {TOKEN_HEADER: token}))


def main() -> None:
    Handler.public = _base("DESK_PUBLIC_URL")
    # Not DESK_RELAY_*: Kubernetes injects DESK_RELAY_PORT=tcp://... for the Service named desk-relay.
    port = int(os.environ.get("RELAY_LISTEN_PORT", "8080"))
    print(f"desk-relay: tickets, deploy reports and cluster reads go to {Handler.public}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
