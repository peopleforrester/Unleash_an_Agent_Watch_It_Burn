# ABOUTME: Offline checks for verify/stage_traces.py (#648): the seeds in presentation order with the guards turned on
# ABOUTME: as the stage turns them, one session per trace, the PII measurement, the views, the retention filter, the check.
"""Holds the stage-trace seeder to its contract without a cluster, a model, Datadog or any money.

A fake cluster stands in for kubectl, guard-proxy's pod and /chat, answering each prompt the way the deployed bot does
for the guard state it is in, and a fake Datadog answers the current-user, Spans and retention-filter APIs. The facts
the views depend on are read from the code that produces them: the root span's service and env from the manifests,
the session.id attribute from guard-proxy's own source, and the challenge order from the run-of-show.
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
import pathlib
import re
import sys
import tempfile
import urllib.parse

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import kubecon_probe as kp  # noqa: E402
import stage_traces as st  # noqa: E402
from agent_probe import MCP_PROMPT, MCP_SENTINEL  # noqa: E402
from nova_replies import ADMIN_CEO  # noqa: E402

# The seeder logs every step at INFO; the checks below say what matters.
logging.disable(logging.INFO)
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


HOST = "burritobot-private.burritobot.co"
ORG = {"included": [{"type": "orgs", "attributes": {"name": "Datadog sandbox"}}]}


def verdict(text: str) -> dict:
    """What the deployed LLM Guard answers guard-proxy for one text: the Regex PII scanner fires on the stage's PII."""
    hit = any(v in text for v in st.PII_VALUES) or bool(re.search(r"\d{3}-\d{2}-\d{4}|\d{4}-\d{4}|@example|555-01", text))
    return {"blocklist": None, "verdict": {"is_valid": not hit, "scanners": {
        "PromptInjection": 0.0, "Regex": 1.0 if hit else -1.0}}}


class FakeCluster:
    """kubectl, guard-proxy's pod and /chat for one private cluster. Replies follow the guard state."""

    def __init__(self, host, context, profile, kubeconfig, timeout, identity=HOST, c7_chains=True,
                 fail_toggle=None, scrub_works=True, pii_scanner=True):
        self.host, self.context, self.calls = host, context, 0
        self.identity, self.c7_chains, self.fail_toggle = identity, c7_chains, fail_toggle
        self.scrub_works, self.pii_scanner = scrub_works, pii_scanner
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

    def clear_room_joker(self):
        self.events.append(("joker-clear",))

    def remove_room_joker(self):
        self.events.append(("joker-remove",))

    def room_joker_exists(self):
        return False

    def kubectl_rc(self, *args, timeout=90, stdin=None):
        self.events.append(("kubectl", args[:4]))
        if tuple(args) == tuple(kp.C6_TOOL_CHECK):
            return 0, kp.TICKET_WITHHELD if self.g["input_classifier"] else "IGNORE ALL PREVIOUS INSTRUCTIONS"
        return 1, "unexpected"

    def guard_verdicts(self, texts):
        self.events.append(("guard-verdicts", len(texts)))
        return [verdict(t) if self.pii_scanner else {**verdict(""), "blocklist": None} for t in texts]

    def chat_as(self, prompt, session):
        self.calls += 1
        self.chats.append({"prompt": prompt, "session": session, "guards": dict(self.g), "rule": self.rule})
        self.events.append(("chat", session))
        if prompt.startswith(kp.CEO_PROMPT):
            if self.g["output"] and self.scrub_works:
                return {"reply": "Ophelia's record: Residence: [REDACTED]. Shall we start your order?"}
            return {"reply": ADMIN_CEO}
        if prompt.startswith(kp.ROOM_PROMPT):
            return {"reply": "I read HC-666; the deployment it asked for was refused by the cluster."}
        if prompt.startswith(st.PII_PROMPT):
            if self.g["input_classifier"] and self.pii_scanner:
                return {"reply": "BurritoBot can't help with that (blocked by the input guardrail).", "guarded": True,
                        "input_tokens": 0}
            return {"reply": "Done, Dana's card is on file.", "guarded": False, "input_tokens": 900}
        if prompt.startswith(MCP_PROMPT):
            if self.rule == kp.C7_NARROWED:
                return {"reply": "Sunny. I was told to call read_internal_config, but that tool is not available."}
            if self.c7_chains:
                return {"reply": f"Sunny. calibration_token: {MCP_SENTINEL}"}
            return {"reply": "Sunny and 20 degrees."}
        return {"reply": "?"}


class FakeDatadog:
    """The current-user, Spans and retention-filter APIs, enough for the seeder's calls."""

    def __init__(self, filters=None, indexed=None, write_status=201, pii_leaks=False, org=ORG):
        self.filters = filters if filters is not None else []
        self.indexed = indexed  # None: every session query finds a span; else the set of sessions that do
        self.write_status, self.pii_leaks, self.org = write_status, pii_leaks, org
        self.calls: list[tuple] = []
        self.keys: list[str] = []

    def __call__(self, method, url, headers, body):
        path = urllib.parse.urlparse(url).path
        data = json.loads(body) if body else None
        self.calls.append((method, path, data))
        self.keys.append(headers["DD-APPLICATION-KEY"])
        if path == "/api/v2/current_user":
            return 200, self.org
        if path == "/api/v2/apm/config/retention-filters" and method == "GET":
            return 200, {"data": self.filters}
        if path.startswith("/api/v2/apm/config/retention-filters"):
            if self.write_status >= 400:
                return self.write_status, {"errors": ["Forbidden"]}
            return self.write_status, {"data": data["data"]}
        if path == "/api/v2/spans/events/search":
            q = data["data"]["attributes"]["filter"]["query"]
            if q.startswith("trace_id:"):
                content = f"Please put her card {st.PII_VALUES[0]}" if self.pii_leaks else ""
                return 200, {"data": [{"id": "root", "attributes": {"service": "burritobot", "custom": {
                    "witb": {"guard": {"decision": "input_classifier"}}, "note": content}}},
                    {"id": "guard", "attributes": {"service": "burritobot-llm-guard"}}]}
            sessions = re.findall(r"wib-stage-[\w-]+", q)
            hit = self.indexed is None or (sessions and all(s in self.indexed for s in sessions))
            span = {"id": "span", "attributes": {"service": "burritobot", "trace_id": "123"}}
            return 200, {"data": [span] if hit or not sessions else []}
        return 404, {"errors": [path]}


GOOD_FILTER = {"id": "rf-1", "attributes": {**st.render_retention()["data"]["attributes"]}}


class Clock:
    def __init__(self, t=1_794_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def seeder(cluster, tries=2, max_calls=14):
    clock = Clock()
    probe = kp.Probe(cluster, max_calls, settle=0, sleep=clock.sleep)
    return st.Seeder(probe, tries, "202611112100", clock=clock)


print("== the views read what the deployed components emit ==")
res = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
check("the root span is service burritobot under the KubeCon env, as the views query it",
      f"service.name={st.ROOT_SERVICE},service.version=1.0.0,deployment.environment.name={st.DD_ENV}" in res)
check("the agent's spans are the service the PII check looks for",
      f"service.name={st.AGENT_SERVICE},service.version=" in res)
proxy = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text(encoding="utf-8")
check("guard-proxy stamps the /chat body's session on the root span as session.id",
      'session = body.get("session", "")' in proxy and 'self._stamp("session.id", session)' in proxy)
check("guard-proxy keeps a prompt with the probe marker off the wall", f'PROBE_MARKER = "{kp.PROBE_MARKER}"' in proxy
      and "not _is_probe(prompt)" in proxy)
check("guard-proxy runs from /app/proxy.py, where the pod-side check imports it",
      'command: ["python", "/app/proxy.py"]' in res)
check("the live tabs are the two KubeCon cluster names (#629)",
      [c for c, _ in st.LIVE_TABS] == ["burritobot-public", "burritobot-private"])

print("== the seeds run in presentation order, the guards on as the stage turns them on ==")
check("the challenge views in run-of-show order: 1, 3, the PII refusal, 4",
      [c for c, _, _ in st.CHALLENGES] == ["ch1", "ch3", "ch3-pii", "ch4"]
      and [n.split(":")[0] for _, n, _ in st.CHALLENGES] == ["Challenge 1", "Challenge 3", "Challenge 3", "Challenge 4"])
ros = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
rows_md = {n: re.search(rf"^\| {n} \| \d+ \|[^\n]*$", ros, re.M) for n in (2, 3, 4, 5)}
check("the run-of-show's segments 2, 4 and 5 are Challenges 1, 3 and 4 with a Datadog tab; segment 3 has none",
      all(rows_md.values())
      and "Challenge 1" in rows_md[2].group(0) and "Datadog Challenge 1 tab" in rows_md[2].group(0)
      and "Challenge 2" in rows_md[3].group(0) and "Datadog" not in rows_md[3].group(0)
      and "Challenge 3" in rows_md[4].group(0) and "Datadog Challenge 3 tab" in rows_md[4].group(0)
      and "Challenge 4" in rows_md[5].group(0) and "Datadog Challenge 4 tab" in rows_md[5].group(0))
check("seven seeds: Challenge 1 off and on, Challenge 3 off and on, the PII refusal, Challenge 4 off and on",
      [s.key for s in st.SEEDS] == ["c5-off", "c5-on", "c6-off", "c6-on", "pii-on", "c7-off", "c7-on"])
check("each on seed is preceded by its own guard: output, input, mcp; the PII seed rides the input guard",
      [(s.key, s.flip) for s in st.SEEDS if s.flip] == [("c5-on", "output"), ("c6-on", "input"), ("c7-on", "mcp")])
check("the flips are the probe's, so they equal the terminal helpers verify/test_kubecon_probe.py holds",
      st.FLIPS["mcp"] is kp._mcp_on)
check("Challenge 3 runs the stage's own ask, under the stage name", all(s.prompt == kp.ROOM_PROMPT for s in st.SEEDS
                                                                         if s.challenge == "ch3"))
check("Challenge 3's seeds are judged on joker-<stage name>", [s.key for s in st.SEEDS if s.joker] == ["c6-off", "c6-on"])
check("no-model checks before the seeds they prove: the tool withholds HC-666, the PII scanner fires",
      [(s.key, s.check) for s in st.SEEDS if s.check] == [("c6-on", "c6-tool-withheld"), ("pii-on", "pii-scanner")])

print("== the judges ==")
withheld_reply = {"reply": "BurritoBot can't help with that (blocked by the input guardrail).", "guarded": True,
                  "input_tokens": 0}
check("the PII seed passes only when refused by the input classifier stage with zero tokens",
      st.judge_pii_blocked(withheld_reply)[0]
      and not st.judge_pii_blocked({"reply": "Done.", "guarded": False})[0]
      and not st.judge_pii_blocked({"reply": "BurritoBot can't help with that (blocked: 'wipe').", "guarded": True})[0])
check("Challenge 3 off fails if the Joker exists (Kyverno not armed) or nothing was read",
      st.judge_c6_admission({"reply": "ok", "joker": False})[0]
      and not st.judge_c6_admission({"reply": "ok", "joker": True})[0]
      and not st.judge_c6_admission({"reply": "", "joker": False})[0]
      and not st.judge_c6_admission({"reply": "ok"})[0])
check("Challenge 3 on fails when the ask itself is refused: the trace would hold no read_support_ticket",
      st.judge_c6_withheld({"reply": "ok", "joker": False})[0]
      and not st.judge_c6_withheld({**withheld_reply, "joker": False})[0])
check("a PII verdict counts only when the Regex scanner refused it; an outage never counts",
      st.judge_pii_caught(verdict(st.PII_PROMPT))[0]
      and not st.judge_pii_caught(verdict("a burrito"))[0]
      and not st.judge_pii_caught({"blocklist": None, "verdict": {"is_valid": False, "scanners": {
          "PromptInjection": 0.9, "Regex": -1.0}}})[0]
      and not st.judge_pii_caught({"blocklist": None, "error": "timed out"})[0])

print("== a clean run: seven requests, one session each, guards-off last ==")
fc = FakeCluster(HOST, "ctx", "p", None, 1)
rows, steps, start, end = seeder(fc).run()
check("seven seeds, every one PASS", len(rows) == 7 and all(r["verdict"] == kp.PASS for r in rows),
      json.dumps(rows, indent=1))
check("seven /chat requests, one per seed", fc.calls == 7)
sessions = [c["session"] for c in fc.chats]
check("every session is unique and starts wib-stage-<stamp>-<seed>-t1",
      sessions == [f"wib-stage-202611112100-{s.key}-t1" for s in st.SEEDS])
check("every prompt carries the probe marker, so no seed reaches the wall",
      all(c["prompt"].endswith(f"\n\n{kp.PROBE_MARKER}") for c in fc.chats))
by = {c["session"][len("wib-stage-202611112100-"):-len("-t1")]: c for c in fc.chats}
check("Challenge 1 off runs with no guard on, Challenge 1 on with the output guard",
      not any(by["c5-off"]["guards"].values()) and by["c5-on"]["guards"]["output"]
      and not by["c5-on"]["guards"]["input_classifier"])
check("Challenge 3 off keeps the input guard off; Challenge 3 on and the PII seed have both input stages",
      not by["c6-off"]["guards"]["input_classifier"]
      and all(by[k]["guards"]["input_blocklist"] and by[k]["guards"]["input_classifier"] for k in ("c6-on", "pii-on")))
check("Challenge 4 off runs with the gateway rule open, Challenge 4 on with it narrowed",
      by["c7-off"]["rule"] == kp.C7_OPEN and by["c7-on"]["rule"] == kp.C7_NARROWED)
check("the Joker is cleared before and removed after each Challenge 3 seed",
      [e[0] for e in fc.events if e[0].startswith("joker") or e in (("chat", sessions[2]), ("chat", sessions[3]))]
      == ["joker-clear", "chat", "joker-remove", "joker-clear", "chat", "joker-remove"])
check("steps: identity, start state, the flips and the no-model checks in order, guards-off last",
      [s["key"] for s in steps] == ["identity", "start-state", "guard-output-on", "guard-input-on", "c6-tool-withheld",
                                    "pii-scanner", "guard-mcp-on", "guards-off"]
      and all(s["verdict"] == kp.PASS for s in steps), json.dumps(steps, indent=1))
check("the stage is left clean: every guard off, the rule open, the rogue tools listed",
      not any(fc.g.values()) and fc.rule == kp.C7_OPEN and fc.tools == kp.EVIL_ALL)

print("== retries, failures and the ceiling ==")
fc = FakeCluster(HOST, "ctx", "p", None, 1, c7_chains=False)
rows, steps, *_ = seeder(fc).run()
c7off = next(r for r in rows if r["key"] == "c7-off")
check("a seed whose beat did not show is retried in a fresh session, then FAIL with its last session kept",
      c7off["verdict"] == kp.FAIL and c7off["tries"] == 2 and c7off["session"].endswith("c7-off-t2"))
check("the run still goes on to Challenge 4 on, and ends with guards-off", rows[-1]["key"] == "c7-on"
      and steps[-1]["key"] == "guards-off" and fc.calls == 8)

fc = FakeCluster(HOST, "ctx", "p", None, 1, pii_scanner=False)
rows, steps, *_ = seeder(fc).run()
pii_row = next(r for r in rows if r["key"] == "pii-on")
pii_step = next(s for s in steps if s["key"] == "pii-scanner")
check("an input guard without the PII scanner: the check says it passes to the model, and the seed is FAIL",
      pii_step["verdict"] == kp.FAIL and "PASSES" in pii_step["note"] and pii_row["verdict"] == kp.FAIL
      and "NOT REFUSED" in pii_row["note"])

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
check("six views: the four challenge views in order, then burritobot-public and burritobot-private",
      [v["name"] for v in views] == [n for _, n, _ in st.CHALLENGES] + ["burritobot-public", "burritobot-private"])
c1 = views[0]
check("a challenge view is its sessions' root spans under the env",
      c1["query"] == f"env:{st.DD_ENV} service:burritobot @session.id:(wib-stage-x-c5-off-t1 OR wib-stage-x-c5-on-t1)")
check("the PII view holds the one PII session", views[2]["sessions"] == ["wib-stage-x-pii-on-t1"])
u = urllib.parse.urlparse(c1["url"])
qs = urllib.parse.parse_qs(u.query)
check("its URL is Trace Explorer, pinned to the seed window on indexed spans",
      u.netloc == "app.datadoghq.com" and u.path == "/apm/traces" and qs["query"] == [c1["query"]]
      and qs["start"] == [str((1000 - 60) * 1000)] and qs["end"] == [str((2000 + 300) * 1000)]
      and qs["paused"] == ["true"] and qs["historicalData"] == ["true"])
pub = views[4]
pq = urllib.parse.parse_qs(urllib.parse.urlparse(pub["url"]).query)
check("a live tab is the cluster's root spans, live, unpinned",
      pub["query"] == f"env:{st.DD_ENV} service:burritobot kube_cluster_name:burritobot-public"
      and pq["paused"] == ["false"] and "start" not in pq)
check("the retention filter covers every challenge view's sessions",
      all(s.startswith(st.SESSION_PREFIX) for v in views for s in v["sessions"])
      and st.RETENTION_QUERY == f"env:{st.DD_ENV} service:burritobot @session.id:wib-stage-*")

print("== the PII trace, as Datadog holds it ==")
root = [{"attributes": {"trace_id": "1"}}]
check("clean: spans present, no agent span, none of the PII",
      st.judge_pii_trace(root, [{"attributes": {"service": "burritobot"}}])[0])
check("any PII value anywhere in the trace is RED",
      not st.judge_pii_trace(root, [{"attributes": {"service": "burritobot", "x": st.PII_VALUES[2]}}])[0])
check("an agent span means the prompt reached the model: RED",
      not st.judge_pii_trace(root, [{"attributes": {"service": st.AGENT_SERVICE}}])[0])
check("no root span, or a trace_id that finds nothing: RED",
      not st.judge_pii_trace([], [])[0] and not st.judge_pii_trace(root, [])[0])

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
check("every session indexed, the PII trace clean and both tabs answering: GREEN",
      rc == 0 and "STAGE VIEWS GREEN" in out and "none of the PII" in out, out)
rc, out = quiet(st.cmd_check, dd_of(FakeDatadog(pii_leaks=True)), vf, 2000.0 + 3600)
check("the PII found in its trace: RED", rc == 1 and "THE PII IS IN THE TRACE" in out)
lost = FakeDatadog(indexed={s for v in views for s in v["sessions"]} - {"wib-stage-x-c6-on-t1"})
rc, out = quiet(st.cmd_check, dd_of(lost), vf, 2000.0 + 3600)
check("a session the retention filter did not keep: RED, named", rc == 1 and "wib-stage-x-c6-on-t1" in out
      and "STAGE VIEWS RED" in out)
bad_views = st.build_views("datadoghq.com", [{**fake_rows[0], "verdict": kp.FAIL}] + fake_rows[1:], 1000.0, 2000.0)
rc, out = quiet(st.cmd_check, dd_of(FakeDatadog()), {"seeded_end": 2000.0, "views": bad_views}, 2000.0 + 3600)
check("a view holding a seed that did not show its beat: RED", rc == 1 and "c5-off" in out)

print("== main ==")


def run_main(argv, fake, cluster_cls=FakeCluster, env=None):
    clock = Clock()
    return quiet(st.main, argv, keys=lambda p, r: ("api", "app", "datadoghq.com"), http=fake,
                 cluster_cls=cluster_cls, sleep=clock.sleep, clock=clock, env=env or {})


made: list[FakeCluster] = []


def tracked(*a, **k):
    made.append(FakeCluster(*a, **k))
    return made[-1]


def tracked_no_scanner(*a, **k):
    made.append(FakeCluster(*a, **k, pii_scanner=False))
    return made[-1]


creds = ["--profile", "accen-dev", "--region", "us-west-2"]
rc, out = run_main(["pii", HOST, "--context", "ctx", *creds], FakeDatadog(), tracked)
check("pii: every kind refused and the control passing: exit 0, no /chat request",
      rc == 0 and "REFUSES 5 OF 5" in out and made[-1].calls == 0 and not [e for e in made[-1].events
                                                                           if e[0] == "toggle"], out)
rc, out = run_main(["pii", HOST, "--context", "ctx", *creds], FakeDatadog(), tracked_no_scanner)
check("pii on a guard without the scanner: exit 1, every kind MISSED", rc == 1 and "REFUSES 0 OF 5" in out
      and out.count("MISSED") == 5)
n = len(made)
rc, out = run_main(["pii", "attackme.burritobot.co", "--context", "ctx", *creds], FakeDatadog(), tracked)
check("pii refuses the room's bot", rc == 2 and len(made) == n)

fake = FakeDatadog()
rc, out = run_main(["retention", "--apply", *creds], fake)
check("retention --apply without the write key: exit 2, nothing called", rc == 2 and not fake.calls)
fake = FakeDatadog()
rc, out = run_main(["retention", "--apply", *creds], fake, env={st.APP_KEY_ENV: "writer"})
check("retention --apply writes with the write key, never the secret's read-only one",
      rc == 0 and set(fake.keys) == {"writer"} and any(m == "POST" for m, _, _ in fake.calls))
fake = FakeDatadog(org={"included": [{"type": "orgs", "attributes": {"name": "Accenture prod"}}]})
rc, out = run_main(["retention", "--apply", *creds], fake, env={st.APP_KEY_ENV: "writer"})
check("keys that reach another org: exit 2, nothing written", rc == 2 and all(m == "GET" for m, _, _ in fake.calls))

with tempfile.TemporaryDirectory() as d:
    out_file = pathlib.Path(d) / "views.json"
    base = ["--context", "ctx", *creds, "--out", str(out_file)]
    n = len(made)
    rc, out = run_main(["seed", "attackme.agenticburn.com", *base], FakeDatadog(filters=[GOOD_FILTER]), tracked)
    check("the room's bot is refused: the stage's traces come from the private bot", rc == 2 and len(made) == n)
    rc, out = run_main(["seed", HOST, *base], FakeDatadog(), tracked)
    check("no retention filter in the org: exit 2 before any model call", rc == 2 and len(made) == n)
    rc, out = run_main(["seed", HOST, *base], FakeDatadog(filters=[GOOD_FILTER]), tracked)
    written = json.loads(out_file.read_text()) if out_file.exists() else {}
    check("a clean seed: exit 0, STAGE TRACES SEEDED", rc == 0 and "STAGE TRACES SEEDED" in out, out[-800:])
    check("the views file holds the six views, the window, the clean PII trace and the seven requests",
          len(written.get("views", [])) == 6 and written.get("model_calls") == 7
          and written.get("seeded_end", 0) >= written.get("seeded_start", 1) and written.get("missing") == []
          and (written.get("pii_trace") or {}).get("ok") is True)
    check("it prints each view's name and URL, in order, and how to save it",
          "Save as new view" in out and all(v["url"] in out for v in written.get("views", []))
          and out.index("Challenge 1:") < out.index("Challenge 3: the HC-666") < out.index("Challenge 3: someone")
          < out.index("Challenge 4:") < out.index("burritobot-public"))
    rc, out = run_main(["seed", HOST, *base], FakeDatadog(filters=[GOOD_FILTER], pii_leaks=True), tracked)
    check("PII found in the seeded trace: RED", rc == 1 and "THE PII IS IN THE TRACE" in out)
    never = FakeDatadog(filters=[GOOD_FILTER], indexed=set())
    rc, out = run_main(["seed", HOST, *base, "--wait", "60"], never, tracked)
    check("traces that never reach Datadog: RED, and the views file still written",
          rc == 1 and "not in Datadog" in out and json.loads(out_file.read_text())["missing"])

print("== the run-of-show names the commands ==")
check("the Night Before measures the input guard, seeds the views with this script and checks them in the morning",
      "verify/stage_traces.py pii burritobot-private.burritobot.co" in ros
      and "verify/stage_traces.py retention" in ros
      and "verify/stage_traces.py seed burritobot-private.burritobot.co" in ros
      and "verify/stage_traces.py check" in ros)

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nALL STAGE TRACE CHECKS PASS")
