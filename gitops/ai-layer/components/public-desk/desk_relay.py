# ABOUTME: The admin KubeCon cluster's way to the public support desk (#1158): one ticket by its number, a deploy report
# ABOUTME: sent with the desk's token, and one witch's private deployments rows (#1256). Fixed upstreams, nothing else.
"""desk-relay: what workshop-mcp's TICKET_SITE_URL points at on the kubecon-private profile (#1158, part of #1145).

On the KubeCon pair one support desk and one deployments page serve both clusters' bots, at the public addresses
(support.burritobot.co and deployments.burritobot.co, the community cluster's fake-ticket, #1157). The private
cluster's workshop-mcp reaches them through this pod and no other way:

    GET  /ticket?id=<number>   -> GET  <DESK_PUBLIC_URL>/ticket?id=<number>, the desk's answer as it is
    POST /landed               -> POST <DESK_PUBLIC_URL>/remote-landed with X-Desk-Report-Token, the answer as it is
    POST /cluster-read         -> POST <DESK_PUBLIC_URL>/remote-cluster-read with X-Desk-Report-Token, the answer as it is
    GET  /deployments.json?witch=<slug>
                               -> GET  <DESK_DEPLOYMENTS_URL>/deployments.json?witch=<slug>, its rows labelled private
    GET  /healthz              -> this relay's own state
    anything else              -> 404

So read_support_ticket still reads one ticket by its number and no list (#1077): the relay passes no other desk path,
and the desk's /ticket answers only the one id it is given. deploy_app's report lands on the public deployments page
under "private", the label the public desk gives a report that came with its token (#1157). The private cluster's
reader (#1050) posts what this cluster still runs to the same desk, with the same token (#1209), and the public desk
applies that read to the rows labelled private alone, so a deploy Kyverno's remove-untrusted-room-workloads deletes here
shows greyed on deployments.burritobot.co, and a read from here never greys a community row. This cluster's own desk
gets no deploy report from this cluster's bot, so it needs no read either, and the relay reaches no in-cluster desk.

The admin chat page's "see your deployments" link (burritbot.html, checkMyDeployments) shows once /deployments.json on
the bot's own host lists a row for the visitor. On this profile the console sends that read here (#1256), since this
cluster's own desk holds no rows: the relay asks the one deployments page for the one witch named, with no token, and
answers with the rows labelled private alone, so the admin page shows its link for the admin bot's deploys and not for
a deploy the room's bot made under the same name. The read takes exactly one witch slug and nothing else: no witch,
two, or a name outside the vocabulary's characters is refused here and sends nothing. It is GET only, and it reads the
deployments page, which serves nothing of the desk's (console.conf), so it is no way to a ticket list (#1077).

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
import re
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN_HEADER = "X-Desk-Report-Token"   # the public desk's header (#1157, ticket_site.REMOTE_TOKEN_HEADER)
MAX_REPORT = 4 * 1024                  # the public console's client_max_body_size for /remote-landed
MAX_READ = 512 * 1024                  # the desk's MAX_READ_BODY, and the public console's limit for /remote-cluster-read
MAX_ID = 40                            # the desk keeps a ticket id to 40 characters
MAX_ROWS_BODY = 256 * 1024             # the desk answers 200 rows at most; a larger answer is not the desk's
PRIVATE_LABEL = "private"              # the label the public desk gives this cluster's rows (its DESK_REMOTE_CLUSTER)
# A witch slug as the chat page writes one (witchSlug: the name lower-cased, spaces to dashes): every name in the
# desk's vocabulary is lower-case letters joined by single dashes. The desk reads at most 80 characters of it.
WITCH_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_WITCH = 80
# An oversize body up to this size is read and dropped before the 413, as nginx discards one before its own 413, so the
# caller reads the 413 and not a broken pipe: answering before the body is read closed the socket under a sender still
# writing (#1220 measured 9 of 40 POSTs of 512k + 1 ending in EPIPE). A body declared larger is answered at once and the
# connection closed unread, so no caller holds the relay reading.
DRAIN_MAX = 2 * MAX_READ
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


def private_rows(status: int, body: bytes) -> tuple[int, bytes]:
    """The deployments page's answer cut to the rows labelled private; a status other than 200 passes as it is, and an
    answer that is not the page's list of rows is a 502."""
    if status != 200:
        return status, body
    try:
        rows = json.loads(body)
    except ValueError:
        rows = None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        return 502, json.dumps({"error": "the deployments page did not answer with its rows"}).encode()
    return 200, json.dumps([r for r in rows if r.get("cluster") == PRIVATE_LABEL]).encode()


class Handler(BaseHTTPRequestHandler):
    public = ""
    deployments = ""

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
            left = n if n <= DRAIN_MAX else 0
            while left > 0:
                chunk = self.rfile.read(min(left, 64 * 1024))
                if not chunk:
                    break
                left -= len(chunk)
            self.close_connection = True
            self._json(413, {"error": f"at most {limit} bytes"})
            return None
        return self.rfile.read(n)

    def do_GET(self) -> None:  # noqa: N802
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/healthz":
            self._json(200, {"ok": True, "desk": self.public, "token": bool(report_token())})
            return
        if url.path == "/deployments.json":
            self._deployments(url.query)
            return
        if url.path != "/ticket":
            self._json(404, {"error": "not found: this relay reads one ticket by its number and one witch's "
                                      "deployments, nothing else"})
            return
        ids = urllib.parse.parse_qs(url.query).get("id") or []
        tid = ids[0].strip() if len(ids) == 1 else ""
        if not tid or len(tid) > MAX_ID:
            self._json(400, {"error": "give one ticket number, e.g. /ticket?id=HC-7731"})
            return
        self._send(*forward("GET", f"{self.public}/ticket?{urllib.parse.urlencode({'id': tid})}"))

    def _deployments(self, query: str) -> None:
        """One witch's rows labelled private on the one deployments page (#1256), for the admin chat page's link."""
        asked = urllib.parse.parse_qs(query, keep_blank_values=True)
        witches = asked.get("witch") or []
        witch = witches[0] if len(witches) == 1 and set(asked) == {"witch"} else ""
        if not (len(witch) <= MAX_WITCH and WITCH_SLUG.fullmatch(witch)):
            self._json(400, {"error": "give one witch name, e.g. /deployments.json?witch=agatha-the-banshee"})
            return
        status, body = forward("GET", f"{self.deployments}/deployments.json?{urllib.parse.urlencode({'witch': witch})}")
        if len(body) > MAX_ROWS_BODY:
            self._json(502, {"error": "the deployments page answered more than its rows"})
            return
        self._send(*private_rows(status, body))

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
    Handler.deployments = _base("DESK_DEPLOYMENTS_URL")
    # Not DESK_RELAY_*: Kubernetes injects DESK_RELAY_PORT=tcp://... for the Service named desk-relay.
    port = int(os.environ.get("RELAY_LISTEN_PORT", "8080"))
    print(f"desk-relay: tickets, deploy reports and cluster reads go to {Handler.public}, deployments reads to "
          f"{Handler.deployments}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
