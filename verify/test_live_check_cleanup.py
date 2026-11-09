# ABOUTME: Holds #1215: a live check that deploys on a KubeCon bot removes what it made from the one deployments page
# ABOUTME: on every path out, the probe's HC-666 ask and #1158's desk check, through the desk's loopback-only /desk-forget.
"""Offline checks for #1215. On 2026-11-08 deployments.burritobot.co showed three rows the room would have seen: run
18737's two desk-check-1158 ConfigMaps and run 18740's private joker-agatha-the-banshee. Each check had deleted what it
made on its cluster, but nothing removed its row from the one page.

Four parts, with no cluster and no network beyond localhost:
  1. the real ticket_site.py's POST /desk-forget: from the pod's loopback it removes exactly the named rows that landed
     at or after `since` and the named filed tickets, keeps every other row, every other ticket and every fixed one;
     through a proxy, from a pod address, on the deployments host or with a bad body it changes nothing, and the
     console refuses the path on the desk's public server;
  2. kubecon_probe's KubeconCluster.forget_on_desk, whose kubectl exec runs the in-pod script against that real desk:
     the row goes, a report that lands between its two passes goes too, and a desk it cannot reach is a reason, never
     a raise;
  3. room_ask, the probe's and the trace seeds' HC-666 ask, removes its Joker's row on every path out: a clean ask, an
     ask that raises, an audit read that raises, a Joker delete that fails or raises; a row it cannot remove fails the
     beat, and an admin run's desk is its guardrails peer (main), never the private cluster's own desk;
  4. verify/one_desk_live.py, #1158's desk check: both ConfigMaps deleted and both rows and its ticket forgotten on every
     path out, a failed filing, a raise mid-check, a failed delete and an interrupt included; and its one-shot
     deploy_app call waits for the desk report deploy_app sends from a daemon thread, so the row lands (#1223).
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
# Every kubectl here is a fake runner; anything past them to a real aws or kubectl would log the call and fail.
import no_cloud  # noqa: E402
no_cloud.setup()
import kubecon_probe as kp  # noqa: E402
import one_desk_live as odl  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
TOKEN = "test-desk-token"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== the desk's /desk-forget, on the real ticket_site.py ==")
# The community desk as the kubecon-community profile runs it: its own rows labelled community, the token's private.
os.environ.update(DESK_CLUSTER="community", DESK_REMOTE_CLUSTER="private", DESK_REPORT_TOKEN=TOKEN)
spec = importlib.util.spec_from_file_location("ticket_site_1215", AI / "ticket_site.py")
ts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ts)
for v in ("DESK_CLUSTER", "DESK_REMOTE_CLUSTER", "DESK_REPORT_TOKEN"):
    os.environ.pop(v, None)
server = ts.Server(("127.0.0.1", 0), ts.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
DESK = f"http://127.0.0.1:{server.server_address[1]}"


def post(path: str, body, headers: dict | None = None, host: str | None = None, form: bool = False) -> tuple[int, dict | str]:
    data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
    h = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json", **(headers or {})}
    if host:
        h["Host"] = host
    try:
        with urllib.request.urlopen(urllib.request.Request(DESK + path, data=data, method="POST", headers=h),
                                    timeout=10) as r:
            raw = r.read().decode()
            code = r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read().decode(), e.code
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, raw


def rows() -> list[tuple[str, str]]:
    return [(r["name"], r["cluster"]) for r in ts.LANDINGS]


def stock() -> tuple[float, str, str]:
    """An old row and a new one of the Joker's name, a check's ConfigMap row, a real room row, a filed ticket of the
    check's and one of the room's. Returns the check's `since` and the two ticket ids."""
    ts.LANDINGS.clear()
    for k in [k for k in ts.TICKETS if k not in ts.FIXED_TICKETS]:
        ts.TICKETS.pop(k)
    ts.record_landing(kp.ROOM_JOKER, True, "", kind="Deployment", requested_by="Agatha the Banshee")
    ts.LANDINGS[0]["ts"] -= 3600   # a room's Joker of the same name, from an hour before the check
    since = time.time() - 1
    ts.record_landing("tron", True, "", kind="Deployment", requested_by="Edgar the Kelpie")
    ts.record_landing(kp.ROOM_JOKER, True, "", kind="Deployment", requested_by="Agatha the Banshee",
                      cluster="private")
    ts.record_landing("desk-check-x-community", True, "", kind="ConfigMap", requested_by="Agatha the Gargoyle")
    check_ticket = ts.file_ticket("the check's ticket", "Agatha the Gargoyle")["id"]
    room_ticket = ts.file_ticket("a room ticket", "Edgar the Kelpie")["id"]
    return since, check_ticket, room_ticket


since, mine, theirs = stock()
before = rows()
code, d = post(ts.DESK_FORGET_PATH, {"names": [kp.ROOM_JOKER, "desk-check-x-community"], "since": since,
                                     "tickets": [mine, "HC-666"]})
check("from the pod's loopback it answers 200 and says what it removed",
      code == 200 and d.get("rows_removed") == 2 and d.get("tickets_removed") == 1 and d.get("named_left") == 0
      and d.get("tickets_left") == 0, f"{code} {d}")
check("it removes only the check's rows: the room's row and the same-named row from before `since` stay",
      rows() == [("tron", "community"), (kp.ROOM_JOKER, "community")], f"{before} -> {rows()}")
check("it removes the check's ticket, keeps the room's, and keeps a fixed ticket it was asked for (HC-666)",
      mine not in ts.TICKETS and theirs in ts.TICKETS and "HC-666" in ts.TICKETS and d.get("fixed_kept") == ["HC-666"],
      str(d))

since, mine, theirs = stock()
before, tickets = rows(), set(ts.TICKETS)
refused = [
    ("through a proxy (the console sets X-Forwarded-For)",
     post(ts.DESK_FORGET_PATH, {"names": [kp.ROOM_JOKER]}, headers={"X-Forwarded-For": "203.0.113.9"}), 403),
    ("on the deployments host", post(ts.DESK_FORGET_PATH, {"names": [kp.ROOM_JOKER]},
                                     host="deployments.burritobot.co"), 404),
    ("with no name and no ticket (it never clears the page)", post(ts.DESK_FORGET_PATH, {}), 400),
    ("with a key it does not know", post(ts.DESK_FORGET_PATH, {"names": [kp.ROOM_JOKER], "tickets_all": True}), 400),
    ("with names that are not a list of names", post(ts.DESK_FORGET_PATH, {"names": kp.ROOM_JOKER}), 400),
    ("with a since that is not epoch seconds", post(ts.DESK_FORGET_PATH, {"names": [kp.ROOM_JOKER], "since": True}),
     400),
    ("with more names than it takes", post(ts.DESK_FORGET_PATH, {"names": [f"n{i}" for i in range(ts.MAX_FORGET + 1)]}),
     400),
]
for why, (code, d), want in refused:
    check(f"refused {why}: {want}, nothing changed", code == want and rows() == before and set(ts.TICKETS) == tickets,
          f"{code} {d}; {before} -> {rows()}")
check("a request from any pod address (the bot's tool pod included) is refused by the same gate as /desk-reset",
      not ts.reset_allowed("10.0.55.163", None) and ts.reset_allowed("127.0.0.1", None)
      and not ts.reset_allowed("127.0.0.1", "203.0.113.9"))
conf = (AI / "console.conf").read_text(encoding="utf-8")
desk_server = conf[conf.index("location = /landed { deny all; }") - 600:conf.index("location = /landed { deny all; }") + 400]
check("the console refuses /desk-forget on the desk's public server, beside /desk-reset",
      "location = /desk-forget { deny all; }" in desk_server and "location = /desk-reset { deny all; }" in desk_server,
      desk_server[-400:])


print("== KubeconCluster.forget_on_desk, its kubectl exec run against that real desk ==")


class DeskRunner:
    """kubectl for the desk's cluster: an exec runs the in-pod script it was given with this test's desk in place of the
    pod's loopback port, so the request still comes from 127.0.0.1. `down` makes kubectl fail, `raises` makes it raise,
    and `between` runs once after the first exec (a report still in flight)."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.down = self.raises = False
        self.between = None

    def __call__(self, argv, capture_output=True, text=True, timeout=None, env=None, input=None):
        self.calls.append(list(argv))
        if self.raises:
            raise subprocess.TimeoutExpired(argv, timeout or 0)
        if self.down:
            return subprocess.CompletedProcess(argv, 1, "", 'Error from server (NotFound): pods "fake-ticket" not found\n')
        assert "exec" in argv and "--" in argv, argv
        cmd = argv[argv.index("--") + 1:]
        cmd[2] = cmd[2].replace("http://127.0.0.1:8080", DESK)
        p = subprocess.run([sys.executable, *cmd[1:]], capture_output=True, text=True, timeout=30)
        if self.between:
            self.between, run = None, self.between
            run()
        return p


runner = DeskRunner()
desk = kp.KubeconCluster(kp.COMMUNITY_HOSTS[0], "ctx-community", "accen-dev", "/tmp/kc", 5, runner=runner)
since, _, _ = stock()
slept: list[float] = []


def late_report() -> None:
    ts.record_landing(kp.ROOM_JOKER, True, "", kind="Deployment", requested_by="Agatha the Banshee", cluster="private")


runner.between = late_report
why = desk.forget_on_desk([kp.ROOM_JOKER], since, sleep=slept.append)
check("it removes the ask's row, and a report that lands between its two passes, leaving the room's rows",
      why is None and rows() == [("desk-check-x-community", "community"), ("tron", "community"),
                                 (kp.ROOM_JOKER, "community")], f"{why}; {rows()}")
check("it waits DESK_REPORT_SETTLE_S between the two passes", slept == [kp.DESK_REPORT_SETTLE_S], str(slept))
check("each pass is one exec into fake-ticket's site container in agent, on the desk's own context",
      len(runner.calls) == 2 and all(c[0] == "kubectl" and c[1:3] == ["--context", "ctx-community"]
                                     and c[3:3 + len(kp.DESK_FORGET)] == kp.DESK_FORGET for c in runner.calls)
      and "deploy/fake-ticket" in kp.DESK_FORGET and kp.DESK_FORGET[kp.DESK_FORGET.index("-c") + 1] == "site",
      str(runner.calls))
check("its `since` is moved back for the desk's clock, so a row stamped by a slightly slow desk pod still goes",
      json.loads(runner.calls[0][-1])["since"] == since - kp.DESK_CLOCK_SKEW_S, runner.calls[0][-1])
for attr, why_word in (("down", "NotFound"), ("raises", "timed out")):
    runner2 = DeskRunner()
    setattr(runner2, attr, True)
    d2 = kp.KubeconCluster(kp.COMMUNITY_HOSTS[0], "ctx-community", None, None, 5, runner=runner2)
    try:
        why = d2.forget_on_desk([kp.ROOM_JOKER], time.time(), sleep=lambda s: None)
        raised = None
    except Exception as e:  # noqa: BLE001
        why, raised = None, e
    check(f"a desk whose kubectl {'fails' if attr == 'down' else 'raises'} is a reason naming the row, never a raise",
          raised is None and why and kp.ROOM_JOKER in why and why_word in why, f"{why}; raised {raised!r}")


print("== room_ask removes its Joker's row on every path out ==")


class AskCluster:
    """The probe's cluster, as room_ask uses it. `fail` names the step that raises or fails."""

    def __init__(self, host: str = kp.COMMUNITY_HOSTS[0], fail: str = "") -> None:
        self.host, self.fail, self.witch, self.calls, self.forgets = host, fail, "", 0, []
        self.context = "ctx-own"

    def chat(self, prompt):
        self.calls += 1
        if self.fail == "ask":
            raise ConnectionResetError("connection reset by peer")
        return {"reply": "Done! I created the Joker."}

    def clear_room_joker(self):
        pass

    def room_joker_exists(self):
        return True

    def tool_calls_since(self, since):
        if self.fail == "audit":
            raise RuntimeError('pods "workshop-mcp" not found')
        return []

    def remove_room_joker(self):
        if self.fail == "delete-raises":
            raise subprocess.TimeoutExpired(["kubectl"], 90)
        return f"{kp.ROOM_JOKER} could not be removed" if self.fail == "delete-fails" else None

    def forget_on_desk(self, names, since, tickets=()):
        self.forgets.append((list(names), since))
        return "the desk on ctx-own answered: exit 1" if self.fail == "forget" else None


class PeerDesk(AskCluster):
    pass


for fail, raises in (("", None), ("ask", ConnectionResetError), ("audit", RuntimeError),
                     ("delete-raises", subprocess.TimeoutExpired), ("delete-fails", None), ("forget", None)):
    c = AskCluster(fail=fail)
    p = kp.Probe(c, 5)
    out, raised = None, None
    t0 = time.time()
    try:
        out = kp.room_ask(p)
    except Exception as e:  # noqa: BLE001
        raised = e
    check(f"{fail or 'a clean ask'}: the row is asked off the one desk once, for the Joker, since the ask began"
          + (f", and the {raises.__name__} still reaches the beat" if raises else ""),
          c.forgets and c.forgets[0][0] == [kp.ROOM_JOKER] and len(c.forgets) == 1
          and t0 - 1 <= c.forgets[0][1] <= time.time() and (type(raised) is raises if raises else raised is None),
          f"forgets {c.forgets}; raised {raised!r}")
    if fail in ("delete-fails", "forget"):
        key = "joker_left" if fail == "delete-fails" else "row_left"
        check(f"{fail}: the reply carries {key}, and the C6 beat fails on it whatever the reply's own verdict",
              out and out.get(key) and kp._c6(lambda d: (True, "landed"))(kp.Probe(AskCluster(fail=fail), 5))[0] is False,
              str(out))
    check(f"{fail or 'a clean ask'}: the witch name is cleared after the ask", c.witch == "", c.witch)

admin = AskCluster(host="burritobot-private.burritobot.co")
out = kp.room_ask(kp.Probe(admin, 5))
check("an admin run with no desk never looks on the private cluster's own desk, and says the row stays",
      admin.forgets == [] and "no desk cluster is known" in (out.get("row_left") or ""), str(out))
ok, note = kp._c6(lambda d: (True, "landed"))(kp.Probe(AskCluster(host="burritobot-private.burritobot.co"), 5))
check("and its C6 beat fails, so an admin run that cannot clear the row never ends green", ok is False
      and "no desk cluster is known" in note, note)
peer = PeerDesk()
admin = AskCluster(host="burritobot-private.burritobot.co")
kp.room_ask(kp.Probe(admin, 5, desk=peer))
check("an admin run with its desk set asks the row off that desk, not its own cluster",
      admin.forgets == [] and [n for n, _ in peer.forgets] == [[kp.ROOM_JOKER]], f"{admin.forgets} {peer.forgets}")

lease = types.SimpleNamespace(contexts=["ctx-community", "ctx-private"])
pd = kp.peer_desk(lease, "ctx-private", "accen-dev", "/tmp/kc", 30)
check("peer_desk is the other context the guardrails switch's lock was taken on, on the one desk's host",
      pd is not None and pd.context == "ctx-community" and pd.host in kp.COMMUNITY_HOSTS and pd.kubeconfig == "/tmp/kc"
      and pd.profile == "accen-dev", str(pd and vars(pd)))
check("and None when the cluster is not linked (the lock was taken on it alone) or the lease names no contexts",
      kp.peer_desk(types.SimpleNamespace(contexts=["ctx-private"]), "ctx-private", None, None, 30) is None
      and kp.peer_desk(types.SimpleNamespace(), "ctx-private", None, None, 30) is None)

seen: dict = {}


@contextlib.contextmanager
def fake_switch(context, kubeconfig=None, profile=None, what="", wait=0.0, **kw):
    yield types.SimpleNamespace(contexts=sorted([context, "ctx-community"]), lost=None)


real = (kp.guard_lease.hold_switch, kp.Probe.run, kp.KubeconCluster.get_json)
kp.guard_lease.hold_switch = fake_switch
kp.Probe.run = lambda self, beats, final=None: seen.update(desk=self.desk) or []
kp.KubeconCluster.get_json = lambda self, path: None
try:
    rc = kp.main(["admin", "burritobot-private.burritobot.co", "--context", "ctx-private", "--kubeconfig", "/tmp/kc"])
finally:
    kp.guard_lease.hold_switch, kp.Probe.run, kp.KubeconCluster.get_json = real
check("the admin probe's main hands its beats the guardrails peer as the desk",
      rc == 0 and seen.get("desk") is not None and seen["desk"].context == "ctx-community"
      and seen["desk"].kubeconfig == "/tmp/kc", str(seen))


print("== verify/one_desk_live.py, #1158's desk check, cleans up on every path out ==")


class SideRunner:
    """kubectl for one KubeCon cluster: the bot's two tools in its tool pod, the check's ConfigMap, and, on the
    community side, the desk's /desk-forget, all against the real desk above. `fail` names a step that fails."""

    def __init__(self, side: str, fail: str = "") -> None:
        self.side, self.fail, self.cms, self.calls = side, fail, set(), []
        self.desk = DeskRunner()

    def __call__(self, argv, capture_output=True, text=True, timeout=None, env=None, input=None):
        a = list(argv)[3:]
        self.calls.append(a)

        def done(rc: int, out: str) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(argv, rc, out, "")
        if a[:len(odl.READ_TOOL)] == odl.READ_TOOL:
            if self.fail == "read-raises":
                raise subprocess.TimeoutExpired(argv, 60)
            t = json.loads(urllib.request.urlopen(f"{DESK}/ticket?id={a[-1]}", timeout=10).read())
            return done(0, f"Ticket {t['id']} [open] from {t['customer']}\n\n{t['body']}\n")
        if a[:len(odl.DEPLOY_TOOL)] == odl.DEPLOY_TOOL:
            name = json.loads(a[-2])["metadata"]["name"]
            self.cms.add(name)
            if self.fail == "deploy":
                return done(1, "deploy failed for ConfigMap: HTTP 500\n")
            report = {"name": name, "ok": True, "kind": "ConfigMap", "requested_by": a[-1]}
            if self.side == "private":
                post(ts.REMOTE_PATH, report, headers={ts.REMOTE_TOKEN_HEADER: TOKEN})
            else:
                post("/landed", report)
            return done(0, f"deployed ConfigMap/{name} in agent.\n")
        if a[:4] == ["-n", "agent", "delete", "configmap"]:
            if self.fail == "delete":
                return done(1, 'Error from server (Forbidden): configmaps "x" is forbidden\n')
            self.cms.discard(a[4])
            return done(0, "")
        if a[:4] == ["-n", "agent", "get", "configmap"]:
            return done(0, f"configmap/{a[4]}\n" if a[4] in self.cms else "")
        if a[:len(kp.DESK_FORGET)] == kp.DESK_FORGET and self.side == "community":
            return self.desk(argv)
        return done(1, f"unexpected kubectl {a}\n")


def http(fail: str = ""):
    """urlopen with the public desk and the one page mapped onto the real desk above."""
    def go(req, timeout=None):
        url = req.full_url.replace(odl.PUBLIC_DESK, DESK).replace(odl.DEPLOYMENTS, f"{DESK}/deployments.json")
        if fail == "file" and url.endswith("/submit"):
            raise urllib.error.URLError("connection refused")
        if fail == "page-raises" and url.endswith("/deployments.json") and not http.cleaning:
            raise urllib.error.URLError("deployments page unreachable")
        if fail == "interrupt" and url.endswith("/deployments.json") and not http.cleaning:
            raise KeyboardInterrupt
        return urllib.request.urlopen(urllib.request.Request(url, data=req.data, method=req.get_method(),
                                                             headers=dict(req.header_items())), timeout=timeout)
    return go


http.cleaning = False


def desk_check(fail: str = "", side_fail: tuple[str, str] = ("", "")) -> tuple[odl.DeskCheck, dict, BaseException | None]:
    _, _, room_ticket = stock()
    runners = {"community": SideRunner("community"), "private": SideRunner("private")}
    if side_fail[0]:
        runners[side_fail[0]].fail = side_fail[1]
    clusters = {s: kp.KubeconCluster(kp.COMMUNITY_HOSTS[0] if s == "community" else "burritobot-private.burritobot.co",
                                     f"ctx-{s}", None, None, 5, runner=r) for s, r in runners.items()}
    dc = odl.DeskCheck(clusters, "t1215", http=http(fail), sleep=lambda s: None)
    dc.room_ticket = room_ticket
    real_cleanup = dc.cleanup

    def cleanup(since):
        http.cleaning = True
        try:
            real_cleanup(since)
        finally:
            http.cleaning = False
    dc.cleanup = cleanup
    raised = None
    try:
        dc.run()
    except BaseException as e:  # noqa: BLE001 - an interrupt is one of the paths
        raised = e
    return dc, runners, raised


def left(dc: odl.DeskCheck, runners: dict) -> list[str]:
    """What the check left: its ConfigMaps on either cluster, its rows on the desk, its ticket."""
    out = [f"cm {n}" for r in runners.values() for n in r.cms]
    out += [f"row {n}" for n, _ in rows() if n in dc.names.values()]
    return out + ([f"ticket {dc.tid}"] if dc.tid and dc.tid in ts.TICKETS else [])


dc, runners, raised = desk_check()
verdicts = {(r["step"], r["verdict"]) for r in dc.results}
check("a clean run passes every step, the page listing each ConfigMap under its own cluster",
      raised is None and all(r["verdict"] == odl.PASS for r in dc.results)
      and {s for s, _ in verdicts} == {"filed", "read", "deploy", "page", "cleanup", "gone"},
      str([r for r in dc.results if r["verdict"] != odl.PASS]))
check("and leaves nothing: no ConfigMap, no row, no ticket, and the room's rows and ticket untouched",
      left(dc, runners) == [] and ("tron", "community") in rows() and dc.room_ticket in ts.TICKETS
      and len([n for n, _ in rows() if n == kp.ROOM_JOKER]) == 2, f"{left(dc, runners)}; {rows()}")
check("its names are desk-check-<stamp>-<cluster>", dc.names == {"community": "desk-check-t1215-community",
                                                                 "private": "desk-check-t1215-private"}, str(dc.names))

for label, fail, side_fail, want_raise in (
        ("the ticket cannot be filed", "file", ("", ""), None),
        ("the private read raises", "", ("private", "read-raises"), None),
        ("the private deploy fails after making its ConfigMap", "", ("private", "deploy"), None),
        ("the page read raises", "page-raises", ("", ""), None),
        ("the run is interrupted mid-check", "interrupt", ("", ""), KeyboardInterrupt)):
    dc, runners, raised = desk_check(fail, side_fail)
    steps = [r["step"] for r in dc.results]
    check(f"{label}: the cleanup still runs and leaves nothing on either cluster or the one desk",
          "cleanup" in steps and "gone" in steps and left(dc, runners) == []
          and (type(raised) is want_raise if want_raise else raised is None),
          f"{left(dc, runners)}; raised {raised!r}; {dc.results}")
    check(f"{label}: and the run is red", want_raise is not None or any(r["verdict"] == odl.FAIL for r in dc.results),
          str(dc.results))

dc, runners, raised = desk_check("", ("community", "delete"))
check("a ConfigMap delete that fails is a FAIL, and the desk's rows and ticket are still forgotten",
      any(r["step"] == "cleanup" and r["verdict"] == odl.FAIL for r in dc.results)
      and not [n for n, _ in rows() if n in dc.names.values()] and dc.tid not in ts.TICKETS,
      str(dc.results))
check("and the check says the ConfigMap may be left", any(r["step"] == "gone" and r["verdict"] == odl.FAIL
                                                          and "community" in r["note"] for r in dc.results),
      str(dc.results))
check("one_desk_live refuses one context for both clusters, and a stamp that is not a name",
      odl.main(["--community-context", "a", "--private-context", "a"]) == 2
      and odl.main(["--community-context", "a", "--private-context", "b", "--stamp", "Bad_Stamp"]) == 2)

# The one-shot deploy_app call must outlive its own desk report (#1223). On 2026-11-09 run 19437's live run deployed
# both ConfigMaps and the desk logged no /landed: the real _report sends from a daemon thread, which python3 -c killed
# on exit. Here DEPLOY_TOOL's own code runs in a fresh interpreter against a stand-in server whose deploy_app does the
# same (a daemon thread that reports after a pause) and also arms a daemon Timer, as a room Joker's scale-down does.
FAKE_SERVER = """
import threading, time
def deploy_app(manifest, requested_by=""):
    def send():
        time.sleep(0.5)
        print("REPORTED " + manifest, flush=True)
    threading.Thread(target=send, daemon=True).start()
    t = threading.Timer(600, print, args=("TIMER FIRED",))
    t.daemon = True
    t.start()
    return "deployed ConfigMap/" + manifest
"""
code_at = odl.DEPLOY_TOOL.index("-c", odl.DEPLOY_TOOL.index("--")) + 1
check("DEPLOY_TOOL runs one python3 -c in the shim container", odl.DEPLOY_TOOL[code_at - 2:code_at] == ["python3", "-c"]
      and code_at == len(odl.DEPLOY_TOOL) - 1, str(odl.DEPLOY_TOOL))
wrapper = ("import sys, types\n"
           "server = types.ModuleType('server')\n"
           f"exec({FAKE_SERVER!r}, server.__dict__)\n"
           "sys.modules['server'] = server\n"
           "sys.argv = ['-c', 'desk-check-t1223-community', 'Agatha the Gargoyle']\n"
           f"exec({odl.DEPLOY_TOOL[code_at]!r})\n")
started = time.monotonic()
done = subprocess.run([sys.executable, "-I", "-c", wrapper], capture_output=True, text=True, timeout=60)
took = time.monotonic() - started
check("the one-shot deploy_app call prints its answer and waits for its desk report before it exits",
      done.returncode == 0 and "deployed ConfigMap/desk-check-t1223-community" in done.stdout
      and "REPORTED desk-check-t1223-community" in done.stdout, f"rc {done.returncode}: {done.stdout!r} {done.stderr!r}")
check("and does not wait on a Timer deploy_app armed, which dies with the process as before",
      "TIMER FIRED" not in done.stdout and took < odl.REPORT_JOIN_S, f"{took:.1f}s: {done.stdout!r}")

check("no check above called aws, kubectl, eksctl, terraform or helm", not no_cloud.calls(), str(no_cloud.calls()))
server.shutdown()
if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll live check cleanup checks passed.")
