# ABOUTME: Holds verify/presenter_ticket_live.py (#1221): segment 4's demo ticket, filed on the real desk through the
# ABOUTME: presenters' path in HC-900 to HC-999, read by number by a bot, printed, and removed on every path out.
"""Offline checks for #1221, the test #1160's criterion lacked: "The run report names the live demo flow: a presenter
ticket filed on the one desk in the reserved range, read by number by the public cluster's bot, with what it printed."
Run 18741 did that flow by hand on watch-it-burn-community; verify/presenter_ticket_live.py does it as a check, and
this holds the check, with no cluster, no model and no network beyond localhost:

  1. the run-of-show's "Let's file a ticket." step still files the demo ticket the way the check does: port-forward
     svc/fake-ticket in agent on watch-it-burn-community, then POST /presenter-ticket, and asks the bot "What's the
     status of my support ticket HC-<n>?"; a reworded step names the literal it lost;
  2. the whole flow against the real gitops/ai-layer/ticket_site.py: the ticket is filed through POST /presenter-ticket,
     numbered in the desk's own PRESENTER_NUMBERS (HC-900 on a fresh desk, the next one after a rehearsal's ticket),
     shown on the desk's page for its number, read back by a bot whose read_support_ticket reads that desk, its reply
     printed whole in the report, and then removed through the real /desk-forget, the rehearsal's ticket, the room's
     and the fixed ones kept;
  3. each way the flow can stop holding fails a named step: a desk that numbers the ticket outside the range or
     refuses it, a bot that reads another ticket, reads none, leaves the word out, never answers or is guarded, a
     wrong cluster (nothing filed, nothing asked), and a raise mid-check, after which the ticket is still removed;
  4. port_forward, against a fake kubectl on PATH: it runs on the cluster's own context and reads the local port off
     kubectl's "Forwarding from" line, stops kubectl on the way out, and raises when kubectl names no port.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
# Every kubectl here is a fake; anything past them to a real aws or kubectl would log the call and fail.
import no_cloud  # noqa: E402
no_cloud.setup()
import presenter_ticket_live as ptl  # noqa: E402
import support_desk_hosts as sdh  # noqa: E402

# kubecon_probe, as the live check itself imports it. Taken from there, not imported here, so this test is not the
# 31st to import it by name, which would make it a shared helper whose every change runs the whole suite
# (verify/scope_tests.py SHARED_HELPER); the map still lists it among this test's reads, so a change to it still runs
# this test.
kp = ptl.kp

REPO = pathlib.Path(__file__).resolve().parent.parent
WORD = "zarzamora4321"   # the live run draws one; pinned here

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== 1. the run-of-show's ticket step files and asks the way the check does ==")
seg4 = sdh.segment_4(sdh.RUN_OF_SHOW.read_text(encoding="utf-8"))
for literal in ("kubectl --context watch-it-burn-community -n agent port-forward svc/fake-ticket 18080:8080",
                f"curl -s -X POST localhost:18080{ptl.PATH}", "What's the status of my support ticket HC-900?"):
    if literal not in seg4:
        sys.exit(f"ANCHOR MISSING: {literal!r} is not in segment 4 of {sdh.RUN_OF_SHOW}; presenter_ticket_live.py "
                 "files the demo ticket and asks the bot the way that step says")
check("the check forwards the step's service and port, and posts to its path",
      ptl.SERVICE == "svc/fake-ticket" and ptl.SERVICE_PORT == 8080
      and ptl.FORWARD[:3] == ["-n", "agent", "port-forward"]
      and ptl.PATH == "/presenter-ticket", f"{ptl.FORWARD} {ptl.PATH}")
check("the check asks the step's question for the number the desk gave",
      ptl.ask("HC-900") == "What's the status of my support ticket HC-900?", ptl.ask("HC-900"))
check("the check asks the public cluster's bot and reads the one desk the room is given",
      ptl.BOT == "attackme.burritobot.co" and ptl.DESK == "support.burritobot.co" == sdh.DESK[0])

print("== 2. the whole flow against the real ticket_site.py ==")
spec = importlib.util.spec_from_file_location("ticket_site_1221", REPO / "gitops/ai-layer/ticket_site.py")
ts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ts)
ts.Handler.log_message = lambda *a: None
server = ts.Server(("127.0.0.1", 0), ts.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"
check("the check's range is the desk's own PRESENTER_NUMBERS", sdh.presenter_numbers() == ts.PRESENTER_NUMBERS,
      f"{sdh.presenter_numbers()} vs {ts.PRESENTER_NUMBERS}")


def filed() -> list[str]:
    return sorted(k for k in ts.TICKETS if k not in ts.FIXED_TICKETS)


class DeskRunner:
    """kubectl for the community cluster: an exec runs the in-pod script it was given against this test's desk in place
    of the pod's loopback port, so /desk-forget still sees a request from 127.0.0.1."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, capture_output=True, text=True, timeout=None, env=None, input=None):
        self.calls.append(list(argv))
        if argv[3:3 + len(kp.DESK_FORGET)] != kp.DESK_FORGET or argv[1:3] != ["--context", "ctx-community"]:
            return subprocess.CompletedProcess(argv, 1, "", f"unexpected kubectl: {argv}\n")
        cmd = argv[argv.index("--") + 1:]
        cmd[2] = cmd[2].replace("http://127.0.0.1:8080", BASE)
        return subprocess.run([sys.executable, *cmd[1:]], capture_output=True, text=True, timeout=30)


class Bot(kp.KubeconCluster):
    """The community cluster as the check sees it: /chat answered by a bot whose read_support_ticket reads this test's
    desk, and the audit log it leaves. `mode` picks how it answers."""

    def __init__(self, mode: str = "reads", identity: str = ptl.BOT) -> None:
        super().__init__(ptl.BOT, "ctx-community", "accen-dev", "/tmp/kc", 5, runner=DeskRunner())
        self.mode, self.identity, self.audit, self.asked = mode, identity, [], []

    def identity_host(self):
        return self.identity

    def get_json(self, path):
        return {"host": self.identity} if path == "/controls" else None

    def tool_calls_since(self, since):
        return list(self.audit)

    def chat(self, prompt: str) -> dict:
        self.calls += 1
        self.asked.append((prompt, self.witch))
        if self.mode == "down":
            raise urllib.error.URLError("timed out")
        if self.mode == "audit-raises":
            self.tool_calls_since = lambda since: (_ for _ in ()).throw(RuntimeError("kubectl logs failed"))
        tid = prompt.split("support ticket ", 1)[1].split("?", 1)[0]
        if self.mode == "no-read":
            return {"reply": f"Your support ticket {tid} is open."}
        if self.mode == "guarded":
            return {"reply": "I can't help with that.", "guarded": True}
        read = "HC-666" if self.mode == "other" else tid
        self.audit.append({"tool_name": "read_support_ticket", "tool_input": {"ticket_id": read}})
        with urllib.request.urlopen(f"{BASE}/ticket?id={read}", timeout=5) as r:
            t = json.load(r)
        if self.mode == "no-word":
            return {"reply": f"The status of your support ticket {tid} is currently {t['status']}."}
        return {"reply": f"The status of your support ticket {tid} is currently {t['status']}. It was submitted by "
                         f"{t['customer']}: {t['body']}"}


def http(req, timeout=30):
    """urlopen with the one desk's public host sent to this test's desk."""
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    if isinstance(req, urllib.request.Request):
        req.full_url = url.replace(f"https://{ptl.DESK}", BASE)
        return urllib.request.urlopen(req, timeout=timeout)
    return urllib.request.urlopen(url.replace(f"https://{ptl.DESK}", BASE), timeout=timeout)


forwards: list[str] = []


@contextlib.contextmanager
def forward(cluster):
    forwards.append(cluster.context)
    yield BASE


def run(bot: Bot, fwd=forward, word: str = WORD) -> ptl.PresenterTicket:
    t = ptl.PresenterTicket(bot, word, forward=fwd, http=http, sleep=lambda s: None)
    t.run()
    return t


def verdicts(t: ptl.PresenterTicket) -> dict[str, str]:
    return {r["step"]: r["verdict"] for r in t.results}


room = ts.file_ticket("a room ticket", "Edgar the Kelpie")["id"]
bot = Bot()
t = run(bot)
out = ptl.report(t.results, t.tid, t.reply)
check("every step passes: identity, filed, on desk, read, cleanup, gone",
      [r["step"] for r in t.results] == ["identity", "filed", "on desk", "read", "cleanup", "gone"]
      and set(verdicts(t).values()) == {"PASS"}, out)
check("the presenter ticket takes HC-900 on a fresh desk, in the reserved range",
      t.tid == "HC-900" and ts.ticket_number(t.tid) in sdh.presenter_numbers(), str(t.tid))
check("the port-forward ran on the community cluster's context", forwards == ["ctx-community"], str(forwards))
check("the bot was asked once, by the number, as the stage's visitor, with the probe marker",
      len(bot.asked) == 1 and bot.asked[0][0].startswith(ptl.ask("HC-900")) and kp.PROBE_MARKER in bot.asked[0][0]
      and bot.asked[0][1] == ptl.CUSTOMER, str(bot.asked))
filed_note = next(r["note"] for r in t.results if r["step"] == "filed")
check("the report prints what the desk answered: 201, the number and the complaint",
      f"POST {ptl.PATH} answered 201" in out and '"id": "HC-900"' in filed_note and WORD in filed_note, filed_note)
check("the report prints what the public bot printed, whole, under the question asked",
      f"The public bot ({ptl.BOT}) printed, asked {ptl.ask('HC-900')!r}:" in out
      and f"  The status of your support ticket HC-900 is currently open. It was submitted by {ptl.CUSTOMER}: "
          f"{ptl.demo_ticket(WORD)}" in out, out)
check("the report ends GREEN", out.endswith("PRESENTER TICKET LIVE GREEN"), out[-80:])
check("the ticket is gone from the desk, and the room's ticket and the fixed ones stay",
      "HC-900" not in ts.TICKETS and room in ts.TICKETS and all(k in ts.TICKETS for k in ts.FIXED_TICKETS),
      str(filed()))
check("the cleanup was one /desk-forget exec per pass, naming only the check's ticket",
      len(bot.runner.calls) == 2 and all(json.loads(c[-1]) == {"names": [], "since": json.loads(c[-1])["since"],
                                                                 "tickets": ["HC-900"]} for c in bot.runner.calls),
      str(bot.runner.calls))

rehearsal = ts.file_presenter_ticket("a rehearsal's ticket")["id"]
t = run(Bot())
check("after a rehearsal's ticket the check takes the next number up, and removes only its own",
      rehearsal == "HC-900" and t.tid == "HC-901" and set(verdicts(t).values()) == {"PASS"}
      and "HC-901" not in ts.TICKETS and rehearsal in ts.TICKETS, f"{t.tid} {verdicts(t)} {filed()}")
ts.TICKETS.pop(rehearsal)

print("== 3. each way the flow stops holding fails a named step ==")
numbers = sdh.presenter_numbers()
ok_body = {"id": "HC-900", "subject": ts.SUBMITTED_SUBJECT, "status": "open", "customer": ptl.CUSTOMER,
           "body": ptl.demo_ticket(WORD)}
check("filed passes a 201 with a reserved number and the complaint", ptl.judge_filed(201, ok_body, WORD, numbers)[0]
      == "HC-900")
for why, status, body in (("a room number (four digits)", 201, {**ok_body, "id": "HC-1234"}),
                          ("HC-666, the fixed ticket", 201, {**ok_body, "id": "HC-666"}),
                          ("a number past the range", 201, {**ok_body, "id": "HC-1000"}),
                          ("an id of another shape", 201, {**ok_body, "id": "TICKET-900"}),
                          ("a body without the complaint's word", 201, {**ok_body, "body": "My burrito"}),
                          ("403 from the console", 403, {"error": "forbidden"}),
                          ("409, the range full", 409, {"error": "every presenter number is taken"}),
                          ("a 201 that is not JSON", 201, "<html>")):
    check(f"filed fails on {why}", ptl.judge_filed(status, body, WORD, numbers)[0] is None)
check("on desk fails on a 404 and on a page without the ticket",
      not ptl.judge_on_desk(404, "", "HC-900", WORD)[0] and not ptl.judge_on_desk(200, "HC-900", "HC-900", WORD)[0])
check("gone fails while the desk still shows the ticket", not ptl.judge_gone(200, "HC-900")[0]
      and ptl.judge_gone(404, "HC-900")[0])

real_file_presenter_ticket = ts.file_presenter_ticket
ts.file_presenter_ticket = lambda raw, customer="": ts.file_ticket(raw, customer)   # a desk that forgot the range
t = run(Bot())
ts.file_presenter_ticket = real_file_presenter_ticket
check("a desk that numbers the presenter ticket as a room ticket fails filed, asks no bot, and removes it",
      verdicts(t).get("filed") == "FAIL" and "read" not in verdicts(t) and ts.ticket_number(t.tid or "") in
      ts.ROOM_NUMBERS and t.tid not in ts.TICKETS and verdicts(t).get("gone") == "PASS", f"{t.tid} {verdicts(t)}")

for mode, why in (("other", "reads another ticket (HC-666)"), ("no-read", "answers without reading the ticket"),
                  ("no-word", "leaves the ticket's word out of its reply"), ("down", "never answers"),
                  ("guarded", "is answered by an AI guard")):
    before = filed()
    t = run(Bot(mode))
    check(f"a bot that {why} fails read, and the ticket is still removed",
          verdicts(t).get("read") == "FAIL" and verdicts(t).get("cleanup") == "PASS" and verdicts(t).get("gone")
          == "PASS" and filed() == before and ptl.report(t.results, t.tid, t.reply).endswith("RED"),
          f"{verdicts(t)} {filed()}")
t = run(Bot("no-read"))
check("a failed read still prints what the bot printed",
      "  Your support ticket HC-900 is open." in ptl.report(t.results, t.tid, t.reply))

before = filed()
t = run(Bot("audit-raises"))
check("an audit log that cannot be read is a failed step, and the ticket is still removed",
      verdicts(t).get("error") == "FAIL" and "kubectl logs failed" in t.results[-3]["note"]
      and verdicts(t).get("gone") == "PASS" and filed() == before, f"{t.results}")

forwards.clear()
wrong = Bot(identity="burritobot-private.burritobot.co")
t = run(wrong)
check("a kube-context that is not the community cluster stops at identity: nothing filed, nothing asked",
      [r["step"] for r in t.results] == ["identity"] and verdicts(t)["identity"] == "FAIL" and not forwards
      and not wrong.asked and not wrong.runner.calls and filed() == before, f"{t.results} {filed()}")


@contextlib.contextmanager
def broken(cluster):
    raise RuntimeError("kubectl port-forward svc/fake-ticket named no local port")
    yield BASE


t = run(Bot(), fwd=broken)
check("a port-forward that fails is a failed step, and nothing is filed or left",
      verdicts(t).get("error") == "FAIL" and t.tid is None and "cleanup" not in verdicts(t) and filed() == before
      and ptl.report(t.results, t.tid, t.reply).endswith("RED"), f"{t.results}")

print("== 4. port_forward, against a fake kubectl ==")
with tempfile.TemporaryDirectory() as tmp:
    log = pathlib.Path(tmp) / "kubectl.log"
    fake = pathlib.Path(tmp) / "kubectl"
    fake.write_text("#!/usr/bin/env bash\n"
                    f'echo "$@" >> "{log}"\n'
                    'if [ -n "$FAKE_PORT" ]; then echo "Forwarding from 127.0.0.1:$FAKE_PORT -> 8080"; fi\n'
                    'echo "Handling connection for 8080"\n'
                    'if [ -n "$FAKE_PORT" ]; then exec sleep 60; fi\n'
                    "exit 1\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    path = os.environ["PATH"]
    os.environ["PATH"] = f"{tmp}{os.pathsep}{path}"
    try:
        os.environ["FAKE_PORT"] = str(server.server_address[1])
        c = kp.KubeconCluster(ptl.BOT, "ctx-community", "accen-dev", "/tmp/kc", 5)
        with ptl.port_forward(c, wait=10) as base:
            with urllib.request.urlopen(f"{base}/healthz", timeout=5) as r:
                health = json.load(r)
        argv = log.read_text().split()
        check("port_forward yields the local port kubectl names, and it reaches the desk",
              base == BASE and health == {"ok": True}, f"{base} {health}")
        check("it runs on the cluster's own context, forwarding svc/fake-ticket's 8080 in agent",
              argv == ["--context", "ctx-community", *ptl.FORWARD], str(argv))
        os.environ.pop("FAKE_PORT")
        try:
            with ptl.port_forward(c, wait=5):
                raised = None
        except RuntimeError as e:
            raised = str(e)
        check("it raises, naming what kubectl said, when kubectl names no port",
              raised is not None and "named no local port" in raised and "Handling connection" in raised, str(raised))
        try:
            with ptl.port_forward(kp.KubeconCluster(ptl.BOT, None, None, None, 5)):
                raised = None
        except RuntimeError as e:
            raised = str(e)
        check("it refuses a cluster with no context, before kubectl runs", raised == "no --context given", str(raised))
    finally:
        os.environ["PATH"] = path
        os.environ.pop("FAKE_PORT", None)

server.shutdown()
check("no check above called a real aws or kubectl", not no_cloud.calls(), no_cloud.calls())
print()
if failures:
    print(f"FAIL: {len(failures)} check(s): {failures}")
    sys.exit(1)
print("PASS: presenter_ticket_live.py files the demo ticket in the reserved range, has the bot read it by number, "
      "prints what it printed and removes it (#1221)")
