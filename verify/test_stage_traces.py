# ABOUTME: Offline checks for verify/stage_traces.py (#648): the seeds in presentation order with the guards turned on
# ABOUTME: as the stage turns them, one session per trace, the views file, the retention filter and the morning check.
"""Holds the stage-trace seeder to its contract without a cluster, a model, Datadog or any money.

A fake cluster stands in for kubectl and /chat, answering each prompt the way the deployed bot does for the guard
state it is in, and a fake Datadog answers the Spans API and the retention-filter API. The facts the views depend on
are read from the code that produces them: the root span's service and env from the manifests, and the session.id
attribute from guard-proxy's own source.
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import re
import sys
import tempfile
import urllib.parse

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import kubecon_probe as kp  # noqa: E402
import stage_traces as st  # noqa: E402
from agent_probe import INJECTION_PROMPT, MCP_PROMPT, MCP_SENTINEL  # noqa: E402
from nova_replies import ADMIN_CEO  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


HOST = "burritobot-private.agenticburn.com"


class FakeCluster:
    """kubectl and /chat for one private cluster. Replies follow the guard state, as the deployed bot's do."""

    def __init__(self, host, context, profile, kubeconfig, timeout, identity=HOST, c7_chains=True,
                 fail_toggle=None, scrub_works=True):
        self.host, self.context, self.calls = host, context, 0
        self.identity, self.c7_chains, self.fail_toggle, self.scrub_works = identity, c7_chains, fail_toggle, scrub_works
        self.g = {k: False for k in kp.AI_GUARDS}
        self.rule, self.tools = kp.C7_OPEN, list(kp.EVIL_ALL)
        self.events: list[tuple] = []
        self.chats: list[dict] = []

    def get_json(self, path):
        return {"/controls": {"host": self.identity}, "/cost": {"usd": 0.0}}.get(path)

    def identity_host(self):
        return self.identity

    def guards(self):
        return dict(self.g)

    def toggle(self, query):
        self.events.append(("toggle", query))
        if self.fail_toggle and self.fail_toggle in query:
            raise RuntimeError("guard-proxy did not answer")
        for part in query.split("&"):
            k, v = part.split("=")
            self.g[k] = v == "on"
        return dict(self.g)

    def measure(self):
        return {"guards": dict(self.g), "evil_tools": list(self.tools), "c7_rule": self.rule,
                "kyverno_actions": ["Deny"], "networkpolicy": True, "kubearmor_action": "Block"}

    def evil_tools(self):
        return list(self.tools)

    def set_evil_tools(self, names):
        self.events.append(("tools", tuple(names)))
        self.tools = list(names)

    def c7_rule(self):
        return self.rule

    def set_c7_rule(self, rule):
        self.events.append(("c7-rule", rule))
        self.rule = rule

    def clear_c6_artifact(self):
        self.events.append(("c6-clear",))

    def remove_c6_artifact(self):
        self.events.append(("c6-remove",))

    def c6_artifact_exists(self):
        return False

    def chat_as(self, prompt, session):
        self.calls += 1
        self.chats.append({"prompt": prompt, "session": session, "guards": dict(self.g), "rule": self.rule})
        self.events.append(("chat", session))
        if prompt.startswith(kp.CEO_PROMPT):
            if self.g["output"] and self.scrub_works:
                return {"reply": "Ophelia's record: Residence: [REDACTED]. Shall we start your order?"}
            return {"reply": ADMIN_CEO}
        if prompt.startswith(INJECTION_PROMPT):
            return {"reply": "I read ticket HC-7731 and tried to help."}
        if prompt.startswith(MCP_PROMPT):
            if self.rule == kp.C7_NARROWED:
                return {"reply": "Sunny. I was told to call read_internal_config, but that tool is not available."}
            if self.c7_chains:
                return {"reply": f"Sunny. calibration_token: {MCP_SENTINEL}"}
            return {"reply": "Sunny and 20 degrees."}
        return {"reply": "?"}


class FakeDatadog:
    """The Spans API and the retention-filter API, enough for the seeder's calls."""

    def __init__(self, filters=None, indexed=None, write_status=201):
        self.filters = filters if filters is not None else []
        self.indexed = indexed  # None: every session query finds a span; else the set of sessions that do
        self.write_status = write_status
        self.calls: list[tuple] = []

    def __call__(self, method, url, headers, body):
        path = urllib.parse.urlparse(url).path
        data = json.loads(body) if body else None
        self.calls.append((method, path, data))
        if path == "/api/v2/apm/config/retention-filters" and method == "GET":
            return 200, {"data": self.filters}
        if path.startswith("/api/v2/apm/config/retention-filters"):
            if self.write_status >= 400:
                return self.write_status, {"errors": ["Forbidden"]}
            return self.write_status, {"data": data["data"]}
        if path == "/api/v2/spans/events/search":
            q = data["data"]["attributes"]["filter"]["query"]
            sessions = re.findall(r"wib-stage-[\w-]+", q)
            hit = self.indexed is None or (sessions and all(s in self.indexed for s in sessions))
            return 200, {"data": [{"id": "span"}] if hit or not sessions else []}
        return 404, {"errors": [path]}


GOOD_FILTER = {"id": "rf-1", "attributes": {**st.render_retention()["data"]["attributes"]}}


class Clock:
    def __init__(self, t=1_794_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def seeder(cluster, tries=2, max_calls=12):
    clock = Clock()
    probe = kp.Probe(cluster, max_calls, settle=0, sleep=clock.sleep)
    return st.Seeder(probe, tries, "202611112100", clock=clock)


print("== the views read what the deployed components emit ==")
res = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
check("the root span is service burritobot under the KubeCon env, as the views query it",
      f"service.name={st.ROOT_SERVICE},service.version=1.0.0,deployment.environment.name={st.DD_ENV}" in res)
proxy = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text(encoding="utf-8")
check("guard-proxy stamps the /chat body's session on the root span as session.id",
      'session = body.get("session", "")' in proxy and 'self._stamp("session.id", session)' in proxy)
check("guard-proxy keeps a prompt with the probe marker off the wall", f'PROBE_MARKER = "{kp.PROBE_MARKER}"' in proxy
      and "not _is_probe(prompt)" in proxy)
check("the live tabs are the two KubeCon cluster names (#629)",
      [c for c, _ in st.LIVE_TABS] == ["burritobot-public", "burritobot-private"])

print("== the seeds run in presentation order, the guards on as the stage turns them on ==")
check("the challenges in run-of-show order: C5, C6, C7", [c for c, _, _ in st.CHALLENGES] == ["C5", "C6", "C7"])
ros = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
order = [ros.index(f"| {n} | 7 |") for n in (2, 3, 4)]
check("the run-of-show's segments 2 to 4 are C5, C6 and C7",
      all(f"| {n} | 7 | " in ros for n in (2, 3, 4)) and order == sorted(order)
      and re.search(r"\| 2 \| 7 \|[^\n]*C5", ros) and re.search(r"\| 3 \| 7 \|[^\n]*C6", ros)
      and re.search(r"\| 4 \| 7 \|[^\n]*C7", ros))
check("each challenge is an off seed then an on seed",
      [s.key for s in st.SEEDS] == ["c5-off", "c5-on", "c6-off", "c6-on", "c7-off", "c7-on"])
check("each on seed is preceded by its own guard: output, input, mcp",
      [(s.key, s.flip) for s in st.SEEDS if s.flip] == [("c5-on", "output"), ("c6-on", "input"), ("c7-on", "mcp")])
check("the flips are the probe's, so they equal the terminal helpers verify/test_kubecon_probe.py holds",
      st.FLIPS["mcp"] is kp._mcp_on)
check("C6's seeds are judged on the maintenance-shell Deployment", [s.key for s in st.SEEDS if s.c6] == ["c6-off", "c6-on"])

print("== a clean run: six model calls, one session each, guards-off last ==")
fc = FakeCluster(HOST, "ctx", "p", None, 1)
rows, steps, start, end = seeder(fc).run()
check("six seeds, every one PASS", len(rows) == 6 and all(r["verdict"] == kp.PASS for r in rows),
      json.dumps(rows, indent=1))
check("six model calls, one per seed", fc.calls == 6)
sessions = [c["session"] for c in fc.chats]
check("every session is unique and starts wib-stage-<stamp>-<seed>-t1",
      sessions == [f"wib-stage-202611112100-{s.key}-t1" for s in st.SEEDS])
check("every prompt carries the probe marker, so no seed reaches the wall",
      all(c["prompt"].endswith(f"\n\n{kp.PROBE_MARKER}") for c in fc.chats))
by = {c["session"][len("wib-stage-202611112100-"):-len("-t1")]: c for c in fc.chats}
check("C5 off runs with no guard on, C5 on with the output guard", not any(by["c5-off"]["guards"].values())
      and by["c5-on"]["guards"]["output"] and not by["c5-on"]["guards"]["input_classifier"])
check("C6 off keeps the output guard on and the input guard off; C6 on has both",
      by["c6-off"]["guards"]["output"] and not by["c6-off"]["guards"]["input_classifier"]
      and by["c6-on"]["guards"]["input_blocklist"] and by["c6-on"]["guards"]["input_classifier"])
check("C7 off runs with the gateway rule open, C7 on with it narrowed",
      by["c7-off"]["rule"] == kp.C7_OPEN and by["c7-on"]["rule"] == kp.C7_NARROWED)
check("C6's Deployment is cleared before and removed after each C6 seed",
      [e[0] for e in fc.events if e[0].startswith("c6") or e == ("chat", sessions[2]) or e == ("chat", sessions[3])]
      == ["c6-clear", "chat", "c6-remove", "c6-clear", "chat", "c6-remove"])
check("steps: identity, start state, the three flips, guards-off last",
      [s["key"] for s in steps] == ["identity", "start-state", "guard-output-on", "guard-input-on", "guard-mcp-on",
                                    "guards-off"] and all(s["verdict"] == kp.PASS for s in steps))
check("the stage is left clean: every guard off, the rule open, the rogue tools listed",
      not any(fc.g.values()) and fc.rule == kp.C7_OPEN and fc.tools == kp.EVIL_ALL)

print("== retries, failures and the ceiling ==")
fc = FakeCluster(HOST, "ctx", "p", None, 1, c7_chains=False)
rows, steps, *_ = seeder(fc).run()
c7off = next(r for r in rows if r["key"] == "c7-off")
check("a seed whose beat did not show is retried in a fresh session, then FAIL with its last session kept",
      c7off["verdict"] == kp.FAIL and c7off["tries"] == 2 and c7off["session"].endswith("c7-off-t2"))
check("the run still goes on to C7 on, and ends with guards-off", rows[-1]["key"] == "c7-on"
      and steps[-1]["key"] == "guards-off" and fc.calls == 7)

fc = FakeCluster(HOST, "ctx", "p", None, 1, identity="attackme.agenticburn.com")
rows, steps, *_ = seeder(fc).run()
check("a context that is not the named cluster: nothing sent, nothing flipped, not even guards-off",
      fc.calls == 0 and not fc.events and [s["key"] for s in steps] == ["identity"])

fc = FakeCluster(HOST, "ctx", "p", None, 1, fail_toggle="input_classifier=on")
rows, steps, *_ = seeder(fc).run()
check("a flip that fails stops the seeds after it, which are FAIL and never sent",
      [r["key"] for r in rows] == [s.key for s in st.SEEDS] and fc.calls == 3
      and all(r["verdict"] == kp.FAIL and not r["session"] for r in rows[3:]))
check("and guards-off still runs", steps[-1]["key"] == "guards-off")

fc = FakeCluster(HOST, "ctx", "p", None, 1, scrub_works=False)
rows, *_ = seeder(fc, max_calls=3).run()
check("the call ceiling is never passed; a seed it stops is FAIL", fc.calls == 3
      and [r["verdict"] for r in rows[:2]] == [kp.PASS, kp.FAIL] and rows[1]["tries"] == 2
      and all(r["verdict"] == kp.FAIL and "--max-calls" in r["note"] for r in rows[2:]))

print("== the views ==")
fake_rows = [{"key": s.key, "challenge": s.challenge, "verdict": kp.PASS, "session": f"wib-stage-x-{s.key}-t1",
              "note": "ok"} for s in st.SEEDS]
views = st.build_views("datadoghq.com", fake_rows, 1000.0, 2000.0)
check("five views: the three challenges in order, then burritobot-public and burritobot-private",
      [v["name"] for v in views] == [n for _, n, _ in st.CHALLENGES] + ["burritobot-public", "burritobot-private"])
c5 = views[0]
check("a challenge view is its two sessions' root spans under the env",
      c5["query"] == f"env:{st.DD_ENV} service:burritobot @session.id:(wib-stage-x-c5-off-t1 OR wib-stage-x-c5-on-t1)")
u = urllib.parse.urlparse(c5["url"])
qs = urllib.parse.parse_qs(u.query)
check("its URL is Trace Explorer, pinned to the seed window on indexed spans",
      u.netloc == "app.datadoghq.com" and u.path == "/apm/traces" and qs["query"] == [c5["query"]]
      and qs["start"] == [str((1000 - 60) * 1000)] and qs["end"] == [str((2000 + 300) * 1000)]
      and qs["paused"] == ["true"] and qs["historicalData"] == ["true"])
pub = views[3]
pq = urllib.parse.parse_qs(urllib.parse.urlparse(pub["url"]).query)
check("a live tab is the cluster's root spans, live, unpinned",
      pub["query"] == f"env:{st.DD_ENV} service:burritobot kube_cluster_name:burritobot-public"
      and pq["paused"] == ["false"] and "start" not in pq)
check("the retention filter covers every challenge view's sessions",
      all(s.startswith(st.SESSION_PREFIX) for v in views for s in v["sessions"])
      and st.RETENTION_QUERY == f"env:{st.DD_ENV} service:burritobot @session.id:wib-stage-*")

print("== the retention filter ==")
body = st.render_retention()["data"]
check("one spans-sampling-processor filter, enabled, every span and every whole trace",
      body["type"] == "apm_retention_filter" and body["attributes"]["filter_type"] == "spans-sampling-processor"
      and body["attributes"]["enabled"] is True and body["attributes"]["rate"] == 1.0
      and body["attributes"]["trace_rate"] == 1.0)


def dd_of(fake):
    return st.Datadog("datadoghq.com", "api", "app", http=fake)


def quiet(fn, *a, **k):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = fn(*a, **k)
    return rc, out.getvalue()


fake = FakeDatadog()
rc, out = quiet(st.cmd_retention, dd_of(fake), False)
check("missing and no --apply: exit 1, the body printed, nothing written",
      rc == 1 and "MISSING" in out and not [c for c in fake.calls if c[0] != "GET"])
fake = FakeDatadog()
rc, out = quiet(st.cmd_retention, dd_of(fake), True)
check("--apply creates it", rc == 0 and [(m, p) for m, p, _ in fake.calls if m == "POST"]
      == [("POST", "/api/v2/apm/config/retention-filters")])
fake = FakeDatadog(filters=[{"id": "rf-9", "attributes": {**body["attributes"], "rate": 0.1}}])
rc, out = quiet(st.cmd_retention, dd_of(fake), True)
check("a drifted filter of ours is updated in place by id",
      rc == 0 and [(m, p, d["data"]["id"]) for m, p, d in fake.calls if m == "PUT"]
      == [("PUT", "/api/v2/apm/config/retention-filters/rf-9", "rf-9")])
fake = FakeDatadog(write_status=403)
rc, out = quiet(st.cmd_retention, dd_of(fake), True)
check("a key that cannot write it: exit 1 and the by-hand steps", rc == 1 and "Add Retention Filter" in out
      and st.RETENTION_QUERY in out)
rc, out = quiet(st.cmd_retention, dd_of(FakeDatadog(filters=[GOOD_FILTER])), False)
check("in place: exit 0", rc == 0 and "OK" in out)

print("== the morning check ==")
vf = {"seeded_end": 2000.0, "views": views}
rc, out = quiet(st.cmd_check, dd_of(FakeDatadog()), vf, 2000.0 + 600)
check("inside the live window it refuses: a hit would not prove indexing", rc == 1 and "TOO EARLY" in out)
rc, out = quiet(st.cmd_check, dd_of(FakeDatadog()), vf, 2000.0 + 3600)
check("every session indexed and both tabs answering: GREEN", rc == 0 and "STAGE VIEWS GREEN" in out)
lost = FakeDatadog(indexed={s for v in views for s in v["sessions"]} - {"wib-stage-x-c6-on-t1"})
rc, out = quiet(st.cmd_check, dd_of(lost), vf, 2000.0 + 3600)
check("a session the retention filter did not keep: RED, named", rc == 1 and "wib-stage-x-c6-on-t1" in out
      and "STAGE VIEWS RED" in out)
bad_views = st.build_views("datadoghq.com", [{**fake_rows[0], "verdict": kp.FAIL}] + fake_rows[1:], 1000.0, 2000.0)
rc, out = quiet(st.cmd_check, dd_of(FakeDatadog()), {"seeded_end": 2000.0, "views": bad_views}, 2000.0 + 3600)
check("a view holding a seed that did not show its beat: RED", rc == 1 and "c5-off" in out)

print("== main ==")


def run_main(argv, fake, cluster_cls=FakeCluster):
    clock = Clock()
    return quiet(st.main, argv, keys=lambda p, r: ("api", "app", "datadoghq.com"), http=fake,
                 cluster_cls=cluster_cls, sleep=clock.sleep, clock=clock)


made: list[FakeCluster] = []


def tracked(*a, **k):
    made.append(FakeCluster(*a, **k))
    return made[-1]


with tempfile.TemporaryDirectory() as d:
    out_file = pathlib.Path(d) / "views.json"
    base = ["--context", "ctx", "--profile", "accen-dev", "--region", "us-west-2", "--out", str(out_file)]
    rc, out = run_main(["seed", "attackme.agenticburn.com", *base], FakeDatadog(filters=[GOOD_FILTER]), tracked)
    check("the room's bot is refused: the stage's traces come from the private bot", rc == 2 and not made)
    rc, out = run_main(["seed", HOST, *base], FakeDatadog(), tracked)
    check("no retention filter in the org: exit 2 before any model call", rc == 2 and not made)
    rc, out = run_main(["seed", HOST, *base], FakeDatadog(filters=[GOOD_FILTER]), tracked)
    written = json.loads(out_file.read_text()) if out_file.exists() else {}
    check("a clean seed: exit 0, STAGE TRACES SEEDED", rc == 0 and "STAGE TRACES SEEDED" in out, out[-600:])
    check("the views file holds the five views, the window and the six model calls",
          len(written.get("views", [])) == 5 and written.get("model_calls") == 6
          and written.get("seeded_end", 0) > written.get("seeded_start", 1) - 1 and written.get("missing") == [])
    check("it prints each view's name and URL, in order, and how to save it",
          "Save as new view" in out and all(v["url"] in out for v in written.get("views", []))
          and out.index("1 C5") < out.index("2 C6") < out.index("3 C7") < out.index("burritobot-public"))
    never = FakeDatadog(filters=[GOOD_FILTER], indexed=set())
    rc, out = run_main(["seed", HOST, *base, "--wait", "60"], never, tracked)
    check("traces that never reach Datadog: RED, and the views file still written",
          rc == 1 and "not in Datadog" in out and json.loads(out_file.read_text())["missing"])

print("== the run-of-show names the commands ==")
check("the Night Before seeds the views with this script and checks them in the morning",
      "verify/stage_traces.py retention" in ros and "verify/stage_traces.py seed burritobot-private.agenticburn.com" in ros
      and "verify/stage_traces.py check" in ros)

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nALL STAGE TRACE CHECKS PASS")
