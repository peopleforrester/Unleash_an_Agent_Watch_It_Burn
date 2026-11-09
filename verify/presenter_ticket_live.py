# ABOUTME: #1221's live check of segment 4's demo ticket on watch-it-burn-community: a presenter ticket filed on the one
# ABOUTME: desk by the presenters' port-forward, in HC-900 to HC-999, read by number by the public bot, then removed.
"""The live demo flow of segment 4's "Let's file a ticket." step (#1156, #1160), run by hand on the community cluster.
One model call (two on a 424).

    . "$HECATON_CLUSTER_ENV"
    python3 verify/presenter_ticket_live.py --context watch-it-burn-community --kubeconfig "$KUBECONFIG" \\
        --profile accen-dev

Run 18741 (#1160) did this by hand and recorded it in decisions.md; no test did it (#1221). What it checks, in order:

  identity  the kube-context's cluster-identity and https://attackme.burritobot.co/controls are the same cluster.
  filed     the presenters' path, as the run-of-show's "Let's file a ticket." step gives it: `kubectl port-forward
            svc/fake-ticket` in agent, then POST /presenter-ticket with a JSON body, an ordinary complaint carrying
            one unusual word. The desk must answer 201 with the ticket, its number in ticket_site.py's
            PRESENTER_NUMBERS (HC-900 to HC-999).
  on desk   https://support.burritobot.co/ticket/<number>, the one desk the room is given, shows that ticket and its
            word, so the port-forward reached the one desk and not another.
  read      the public bot, https://attackme.burritobot.co/chat, is asked "What's the status of my support ticket
            <number>?" with the probe marker, which keeps the ask off the room's prompt feed. workshop-mcp's audit log
            must show read_support_ticket(<number>) and the reply must carry the ticket's word. The reply is printed
            whole, under the steps.

Then, on every path out, a failure or a raise included, the ticket is removed from the one desk with its loopback-only
POST /desk-forget, run in the desk's pod (kubecon_probe's forget_on_desk), and
  gone      https://support.burritobot.co/ticket/<number> answers 404, so the number is free for the stage again.
Nothing else on the desk is touched: no other ticket, no row, no restart, and no guard is flipped. It reads and writes
no Secret, and never agent/terminal-auth. It exits 1 when any check fails, the cleanup's included, and 2 when the
kube-context is not the community cluster, before anything is filed.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import logging
import pathlib
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Iterator

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import desk_ticket_live as dtl  # noqa: E402
import kubecon_probe as kp  # noqa: E402
import support_desk_hosts as sdh  # noqa: E402

log = logging.getLogger("presenter-ticket-live")

PASS, FAIL = "PASS", "FAIL"
BOT = kp.COMMUNITY_HOSTS[0]
DESK = sdh.DESK[0]
PATH = "/presenter-ticket"
# The presenters' port-forward, as the run-of-show's "Let's file a ticket." step gives it, on a port kubectl picks.
SERVICE, SERVICE_PORT = "svc/fake-ticket", 8080
FORWARD = ["-n", "agent", "port-forward", "--address", "127.0.0.1", SERVICE, f":{SERVICE_PORT}"]
FORWARDING = re.compile(rf"Forwarding from 127\.0\.0\.1:(\d+) -> {SERVICE_PORT}\b")
FORWARD_WAIT_S = 30.0
# The presenter's name on the ticket and as the chat page's visitor, the stage's name in the vocabulary it hands out.
CUSTOMER = kp.STAGE_NAME
NUMBER = re.compile(r"HC-(\d+)")


def demo_ticket(word: str) -> str:
    """The step's ordinary complaint, with one unusual word the reply is checked for."""
    return f"My burrito came without salsa, and the note in the bag just said {word}. What does that mean?"


def ask(tid: str) -> str:
    return f"What's the status of my support ticket {tid}?"


# --- judges ---------------------------------------------------------------------------------------------------


def judge_filed(status: int, d, word: str, numbers: range) -> tuple[str | None, str]:
    """POST /presenter-ticket answered 201 with the ticket, numbered in the presenters' reserved range."""
    shown = json.dumps(d) if isinstance(d, dict) else str(d)[:200]
    if status != 201 or not isinstance(d, dict):
        return None, f"POST {PATH} answered {status}, not 201 with the ticket: {shown}"
    tid = str(d.get("id") or "")
    m = NUMBER.fullmatch(tid)
    if not m or int(m.group(1)) not in numbers:
        return None, (f"POST {PATH} numbered the ticket {tid!r}, outside the presenters' range "
                      f"HC-{numbers.start} to HC-{numbers.stop - 1}: {shown}")
    if word not in str(d.get("body") or ""):
        return None, f"POST {PATH} answered {tid}, but its body does not carry {word!r}: {shown}"
    return tid, f"POST {PATH} answered 201: {shown}"


def judge_on_desk(status: int, page: str, tid: str, word: str) -> tuple[bool, str]:
    """The one desk's own page for the number shows the ticket the presenter filed."""
    if status != 200:
        return False, f"https://{DESK}/ticket/{tid} answered {status}, not 200"
    if tid not in page or word not in page:
        return False, (f"https://{DESK}/ticket/{tid} answered 200 without the ticket's number and {word!r}: "
                       f"{page[:200]!r}")
    return True, f"https://{DESK}/ticket/{tid} answered 200 with the ticket's text"


def judge_read(tid: str, word: str, d: dict) -> tuple[bool, str]:
    """The public bot read the ticket by its number (workshop-mcp's audit log) and its reply carries the word."""
    if d.get("transport_error"):
        return False, f"the ask never came back: {d['transport_error']}"
    if d.get("guarded"):
        return False, (f"an AI guard answered, and the demo ticket is an ordinary complaint: "
                       f"{kp._reply(d)[:kp.EXCERPT]!r}")
    return dtl.judge_read_by_number(tid, word, d)


def judge_gone(status: int, tid: str) -> tuple[bool, str]:
    if status != 404:
        return False, (f"https://{DESK}/ticket/{tid} answered {status} after /desk-forget: the ticket is still on "
                       "the desk")
    return True, f"https://{DESK}/ticket/{tid} answers 404: the number is free again"


# --- the run --------------------------------------------------------------------------------------------------


@contextlib.contextmanager
def port_forward(cluster: kp.KubeconCluster, wait: float = FORWARD_WAIT_S) -> Iterator[str]:
    """`kubectl port-forward svc/fake-ticket` on the cluster's own context, yielding the local base URL; stopped on
    the way out. Raises when kubectl names no local port within `wait` seconds."""
    if not cluster.context:
        raise RuntimeError("no --context given")
    p = subprocess.Popen(["kubectl", "--context", cluster.context, *FORWARD], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, env=cluster.env())
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(ln) for ln in p.stdout], daemon=True).start()
    try:
        deadline, seen = time.monotonic() + wait, []
        while True:
            left = deadline - time.monotonic()
            try:
                line = lines.get(timeout=max(0.1, left))
            except queue.Empty:
                line = None
            if line:
                seen.append(line.strip())
                m = FORWARDING.search(line)
                if m:
                    break
            if p.poll() is not None or left <= 0:
                raise RuntimeError(f"kubectl port-forward {SERVICE} named no local port: {' | '.join(seen)[:200]}")
        yield f"http://127.0.0.1:{m.group(1)}"
    finally:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


class PresenterTicket:
    """One run of the check on the community cluster: `cluster` is its KubeconCluster, `word` the ticket's own word."""

    def __init__(self, cluster: kp.KubeconCluster, word: str, max_calls: int = 2,
                 forward: Callable = port_forward, http: Callable = urllib.request.urlopen,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.cluster, self.word, self.forward, self.http, self.sleep = cluster, word, forward, http, sleep
        self.probe = kp.Probe(cluster, max_calls)
        self.tid: str | None = None
        self.reply: str | None = None
        self.results: list[dict] = []

    def record(self, step: str, ok: bool, note: str) -> bool:
        self.results.append({"step": step, "verdict": PASS if ok else FAIL, "note": note})
        log.info("%-4s  %-8s %s", PASS if ok else FAIL, step, note)
        return ok

    def _send(self, req, timeout: float = 30) -> tuple[int, str]:
        try:
            with self.http(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def desk_page(self, tid: str) -> tuple[int, str]:
        return self._send(urllib.request.Request(f"https://{DESK}/ticket/{tid}", headers={"Cache-Control": "no-cache"}))

    def identity(self) -> bool:
        c = self.cluster
        return self.record("identity", *kp.judge_identity(c.host, c.identity_host(),
                                                          (c.get_json("/controls") or {}).get("host")))

    def file(self) -> bool:
        data = json.dumps({"body": demo_ticket(self.word), "customer": CUSTOMER}).encode()
        with self.forward(self.cluster) as base:
            status, raw = self._send(urllib.request.Request(base + PATH, data=data, method="POST",
                                                            headers={"Content-Type": "application/json"}))
        try:
            d = json.loads(raw)
        except ValueError:
            d = raw
        if isinstance(d, dict) and isinstance(d.get("id"), str):
            # Whatever number the desk gave is the run's to remove, in range or not.
            self.tid = d["id"].strip().upper()
        tid, note = judge_filed(status, d, self.word, sdh.presenter_numbers())
        return self.record("filed", tid is not None, note)

    def on_desk(self) -> bool:
        return self.record("on desk", *judge_on_desk(*self.desk_page(self.tid), self.tid, self.word))

    def read(self) -> bool:
        since = dt.datetime.now(dt.timezone.utc)
        self.cluster.witch = CUSTOMER
        try:
            d = self.probe.ask(ask(self.tid))
        finally:
            self.cluster.witch = ""
        self.reply = kp._reply(d)
        d = {**d, "tools": self.cluster.tool_calls_since(since)}
        return self.record("read", *judge_read(self.tid, self.word, d))

    def checks(self) -> None:
        if not self.file():
            return
        self.on_desk()
        self.read()

    def cleanup(self, since: float) -> None:
        if not self.tid:
            return
        why = self.cluster.forget_on_desk([], since, [self.tid], sleep=self.sleep)
        self.record("cleanup", why is None, why or f"/desk-forget removed {self.tid} from the one desk")
        try:
            self.record("gone", *judge_gone(self.desk_page(self.tid)[0], self.tid))
        except Exception as e:  # noqa: BLE001 - a desk that cannot be read is a failed check, not a crash
            self.record("gone", False, f"https://{DESK}/ticket/{self.tid} could not be read after the cleanup: {e}")

    def run(self) -> list[dict]:
        if not self.identity():
            return self.results
        since = time.time()
        try:
            self.checks()
        except Exception as e:  # noqa: BLE001 - a step that cannot run is a failed step; the cleanup still runs
            self.record("error", False, f"could not run: {e}")
        finally:
            self.cleanup(since)
        return self.results


def report(results: list[dict], tid: str | None, reply: str | None) -> str:
    """What the run prints: each step and its note, then the public bot's reply whole, then the verdict."""
    fails = [r for r in results if r["verdict"] == FAIL]
    out = [f"  {r['verdict']}  {r['step']:<8} {r['note']}" for r in results]
    if reply is not None:
        out += ["", f"The public bot ({BOT}) printed, asked {ask(tid)!r}:", f"  {reply}"]
    out += ["", f"{len(results)} checks: {len(results) - len(fails)} PASS, {len(fails)} FAIL",
            "PRESENTER TICKET LIVE GREEN" if results and not fails else "PRESENTER TICKET LIVE RED"]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--context", required=True, help="kube-context of the community cluster (the one desk)")
    ap.add_argument("--kubeconfig", help="isolated kubeconfig, passed per command, never exported")
    ap.add_argument("--profile", help="AWS_PROFILE for kubectl, passed per command")
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cluster = kp.KubeconCluster(BOT, args.context, args.profile, args.kubeconfig, args.timeout)
    run = PresenterTicket(cluster, f"zarzamora{secrets.randbelow(9000) + 1000}")
    results = run.run()
    print()
    print(report(results, run.tid, run.reply))
    if results and results[0]["step"] == "identity" and results[0]["verdict"] == FAIL:
        return 2
    return 1 if any(r["verdict"] == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
