# ABOUTME: Drives verify/stage_traces.py's pii, seed and check against a fake private cluster and a fake Datadog: nine
# ABOUTME: seeds in presentation order, each on its own session with no probe marker, then guards-off.
"""#648: the stage opens each challenge on its pre-seeded trace (Michael, 2026-10-31). The seed must run the attack
and the fix for Challenges 1 to 4 the way the stage does, with the KubeCon probe's own guard flips, put each one
in a session of its own so Datadog can find it, leave the cluster as guards-off leaves it, and go red when a trace
never reaches Datadog. Challenge 3 adds someone else's PII refused by the input guard (Whitney, 2026-10-29): it is
sent only after guard-proxy's own input stages say they refuse it, and its trace must hold none of the PII.
`pii` measures that guard with no model call and must end REFUSES 5 OF 5. Challenge 2 is seeded with the /kubecon recipe
read, before guardrails-on and after it (#843), and both seeds need run_shell's grep in workshop-mcp's audit log."""
from __future__ import annotations

import ast
import contextlib
import datetime as dt
import json
import logging
import pathlib
import re
import sys
import tempfile
import types
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kubecon_probe as kp  # noqa: E402
import stage_traces as st  # noqa: E402

failures: list[str] = []
HOST = "burritobot-private.burritobot.co"


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


CEO_LEAK = "Here you go: Ophelia Thorn, Residence: 6509 Cat's Claw Way, Tibby Top Spire."
C7_LEAK = "It's sunny. Region calibration block:\n  calibration_token: FAKE-MCP-EXFIL-sentinel-4c1d"
C7_DENIED = "It's sunny. I tried read_internal_config but the gateway refused it."


def reply(text: str) -> dict:
    return {"reply": text, "guarded": False, "input_tokens": 3400, "output_tokens": 120}


def audit(tool: str, **args) -> dict:
    """One workshop-mcp audit `pre` line; test_kubecon_probe.py holds the probe's parsing to tool_audit.py's own."""
    return {"event": "tool_invocation", "phase": "pre", "tool_name": tool, "tool_input": args}


READ_ROOM = audit("read_support_ticket", ticket_id=kp.ROOM_TICKET_ID)
DEPLOY_ROOM = audit("deploy_app", manifest=json.dumps(kp.C6_MANIFEST))
RECIPE_GREP = audit("run_shell", command="grep -ri -A3 recipe /tmp/burrito-data")
RECIPE_LEAK = (f"Found it! /tmp/burrito-data/secret-recipe.txt: {kp.RECIPE_MARK}: ghost pepper, a generous splash of "
               "bat saliva and a half teaspoon of ground **ogre toenails**. Signature: WITCH-HAZEL-GHOST-PEPPER-BAT-SPIT-No7")
RECIPE_DENIED = "I ran the search, but the system said: grep: /tmp/burrito-data/secret-recipe.txt: Permission denied"


class FakePrivate(st.StageCluster):
    """The private cluster at its start (#774): the four Kubernetes guardrails off until guardrails-on, every AI guard
    off, the shipped Role."""

    def __init__(self, pii_guard: bool = True) -> None:
        super().__init__(HOST, "wib-private", "accen-dev", None, 30)
        self.g = {k: False for k in kp.AI_GUARDS}
        self.tools, self.rule, self.role = list(kp.EVIL_ALL), kp.C7_OPEN, kp.RBAC_SHIPPED
        self.armed = False
        self.joker, self.log, self.sent, self.witches = False, [], [], []
        self.audit: list[dict] = []
        self.pii_guard = pii_guard  # whether LLM Guard's input scanners include the PII Regex
        self.asked: list[list[str]] = []

    def kubectl_rc(self, *args, timeout=90, stdin=None):
        """The terminal's guardrails-on and guardrails-off, run in its pod: both clusters switch."""
        assert "deploy/web-terminal" in args, args
        state = "on" if args[-1].endswith("guardrails-on") else "off"
        self.log.append(f"guardrails {state}")
        self.armed = state == "on"
        self.role = kp.RBAC_FIX if self.armed else kp.RBAC_SHIPPED
        return 0, f"Both clusters, this one and watch-it-burn-community: all four Kubernetes guardrails are {state}.\n"

    def guard_verdicts(self, texts):
        """guard-proxy's input stages: the block-list catches none of this, the Regex scanner catches the PII."""
        self.asked.append(list(texts))
        self.log.append("guard_verdicts")
        out = []
        for t in texts:
            hit = self.pii_guard and PII.search(t) is not None
            out.append({"blocklist": None, "verdict": {"is_valid": not hit, "sanitized_prompt": t, "scanners": {
                "PromptInjection": 0.0, **({"Regex": 1.0 if hit else -1.0} if self.pii_guard else {})}}})
        return out

    def get_json(self, path):
        if path == "/cost":
            return {"usd": 1.0}
        return {"ai": dict(self.g), "host": HOST, "infra": {
            "networkpolicy": self.armed, "kyverno": self.armed, "kubearmor": self.armed, "falco": True,
            "tool_allowlist": self.rule == kp.C7_NARROWED, "rbac_scoped": self.role == kp.RBAC_FIX}}

    def identity_host(self):
        return HOST

    def measure(self):
        action = ["Deny"] if self.armed else ["Audit"]
        return {"guards": dict(self.g), "evil_tools": list(self.tools), "c7_rule": self.rule,
                "kyverno_actions": action, "breakout_actions": action, "networkpolicy": self.armed,
                "kubearmor_action": "Block" if self.armed else None, "rbac_scoped": self.role == kp.RBAC_FIX}

    def toggle(self, q):
        self.log.append(f"toggle {q}")
        for part in q.split("&"):
            k, v = part.split("=")
            if k in self.g:
                self.g[k] = v == "on"
        return dict(self.g)

    def apply_fix(self, name):
        self.log.append(f"role {name}")
        self.role = name
        return 0, "role.rbac.authorization.k8s.io/workshop-agent configured\n"

    def evil_tools(self):
        return list(self.tools)

    def set_evil_tools(self, names):
        self.log.append(f"tools {names}")
        self.tools = list(names)

    def c7_rule(self):
        return self.rule

    def set_c7_rule(self, rule):
        self.log.append(f"rule {rule}")
        self.rule = rule

    def clear_room_joker(self):
        self.joker = False

    def room_joker_exists(self):
        return self.joker

    def remove_room_joker(self):
        self.joker = False
        return None

    def tool_calls_since(self, since):
        return list(self.audit)

    def recipe_ask(self) -> tuple[list[dict], str]:
        """Challenge 2's recipe read: run_shell's grep, which KubeArmor denies once guardrails-on has run."""
        return [RECIPE_GREP], RECIPE_DENIED if self.armed else RECIPE_LEAK

    def room_calls(self) -> list[dict]:
        """What workshop-mcp logs for HC-666 with the input guard off: the ticket read, then the Joker deployed."""
        return [READ_ROOM, DEPLOY_ROOM]

    def chat(self, prompt):
        self.calls += 1
        self.sent.append((self.session, prompt))
        self.witches.append(self.chat_body(prompt).get("witch", ""))
        self.log.append(f"chat {self.session}")
        if prompt == kp.CEO_PROMPT:
            return reply("I'm not allowed to read that vault entry." if self.role == kp.RBAC_FIX else CEO_LEAK)
        if prompt == kp.ROOM_PROMPT:
            if self.g["input_classifier"]:
                self.audit = [READ_ROOM]
                return reply(f"I tried to read {kp.ROOM_TICKET_ID}, but it was withheld.")
            self.audit = self.room_calls()
            # Kyverno trusts the internal registry the Joker comes from (#775): only least privilege refuses it.
            if self.role != kp.AGENCY_FIX:
                self.joker = True
                return reply(f"Done! I created {kp.ROOM_JOKER}.")
            return reply(f"I tried to create {kp.ROOM_JOKER}, but the cluster said I'm not allowed to.")
        if prompt == st.RECIPE_PROMPT:
            self.audit, text = self.recipe_ask()
            return reply(text)
        if prompt == kp.MCP_PROMPT:
            return reply(C7_LEAK if self.rule == kp.C7_OPEN else C7_DENIED)
        if prompt == st.PII_PROMPT and self.g["input_classifier"] and self.pii_guard:
            return {"reply": "BurritoBot can't help with that (blocked by the input guardrail: Regex, risk 1.00).",
                    "guarded": True, "input_tokens": 0, "output_tokens": 0}
        return reply("Sure.")


# The configured PII scanner's pattern, so the fake guard refuses what the deployed one would.
_docs = [d for d in kp.yaml.safe_load_all((HERE.parent / "gitops/ai-layer/resources.yaml").read_text()) if d]
_scanners = kp.yaml.safe_load(next(d for d in _docs if d.get("kind") == "ConfigMap"
                                   and d["metadata"]["name"] == "llm-guard-scanners")["data"]["scanners.yml"])
PII = re.compile(next(s for s in _scanners["input_scanners"] if s["type"] == "Regex")["params"]["patterns"][0])


# The tool spans each seed's trace carries on a well-behaved cluster.
TRACE_TOOLS = {"c1-attack": ["get_vault_entry"], "c1-fixed": ["get_vault_entry"],
               "c2-attack": ["run_shell"], "c2-fixed": ["run_shell"],
               "c3-attack": ["read_support_ticket", "deploy_app"], "c3-fixed": ["read_support_ticket"],
               "c4-attack": ["get_weather", "read_internal_config"], "c4-fixed": ["get_weather"]}


class FakeDatadog:
    """LLM Observability's span events for the model seeds, APM's span search for the PII seed."""

    def __init__(self, missing: tuple[str, ...] = (), tools: dict | None = None, pii_trace: str = "clean") -> None:
        self.missing, self.tools, self.pii_trace = missing, tools or TRACE_TOOLS, pii_trace

    def apm(self, query: str) -> list[dict]:
        if query.startswith("service:burritobot @session.id:"):
            sess = query.split("@session.id:", 1)[1]
            if any(m in sess for m in self.missing):
                return []
            return [{"attributes": {"service": "burritobot", "resource_name": "POST /chat", "trace_id": f"t-{sess}",
                                    "custom": {"session": {"id": sess}, "witb": {"guard": {
                                        "decision": "input_classifier"}}}}}]
        tid = query.removeprefix("trace_id:")
        spans = [{"attributes": {"service": "burritobot", "resource_name": "POST /chat", "trace_id": tid,
                                 "custom": {"witb": {"guard": {"decision": "input_classifier"}}}}},
                 {"attributes": {"service": "burritobot", "resource_name": "POST /analyze/prompt", "trace_id": tid}}]
        if self.pii_trace == "leaked":
            spans[0]["attributes"]["custom"]["gen_ai"] = {"input": {"messages": st.PII_PROMPT}}
        if self.pii_trace == "agent":
            spans.append({"attributes": {"service": "burritobot-agent", "resource_name": "invoke_agent",
                                         "trace_id": tid}})
        return spans

    def call(self, method, path, body=None):
        if path == "/api/v2/spans/events/search":
            assert method == "POST" and body["data"]["type"] == "search_request"
            return {"data": self.apm(body["data"]["attributes"]["filter"]["query"])}
        assert method == "GET" and "/api/v2/llm-obs/v1/spans/events" in path and "filter[ml_app]=burritobot" in path
        sess = path.split("session_id%3A", 1)[1].split("&", 1)[0]
        if any(m in sess for m in self.missing):
            return {"data": []}
        key = next(k for k in self.tools if f"-{k}-" in sess)
        tags = [f"session_id:{sess}", "k8s.cluster.name:burritobot-private"]
        # Newest first, as the spans API lists them (run 17405's fixture), each stamped with its start_ns.
        names = ["invocation", *self.tools[key]]
        return {"data": [{"attributes": {"name": n, "tags": tags, "start_ns": 1_000 + i}}
                         for i, n in reversed(list(enumerate(names)))]}


# The cluster's guard lock (#1024) without a cluster: a stand-in hold that records the context it was asked for and
# whether the seeds' Probe.run ran inside it. verify/test_guard_lease.py tests the lock itself.
LOCK: dict = {}


@contextlib.contextmanager
def fake_hold(context, kubeconfig=None, profile=None, what="", wait=0.0, **kw):
    LOCK.update(context=context, what=what, inside=True)
    try:
        yield types.SimpleNamespace(lost=None, holder="fake")
    finally:
        LOCK["inside"] = False


st.guard_lease.hold_switch = fake_hold
_real_probe_run = st.StageProbe.run


def _run_in_lock(self, *a, **k):
    LOCK["ran_inside"] = LOCK.get("inside")
    return _real_probe_run(self, *a, **k)


st.StageProbe.run = _run_in_lock


def run_seed(cluster: FakePrivate, dd: FakeDatadog, out: pathlib.Path) -> int:
    st.StageCluster = lambda *a, **k: cluster  # noqa: E731 - the seed builds its cluster from argv
    st.datadog = lambda profile, region: (dd, "datadoghq.com")  # noqa: E731
    st.wait_for.__defaults__ = (0.0, lambda s: None)
    return st.main(["seed", HOST, "--context", "wib-private", "--profile", "accen-dev", "--settle", "0",
                    "--wait", "0", "--stamp", "202611111800", "--out", str(out)])


print("== a seed on a well-behaved private cluster ==")
with tempfile.TemporaryDirectory() as tmp:
    out = pathlib.Path(tmp, "stage-traces.json")
    real_cluster, real_dd, real_wait = st.StageCluster, st.datadog, st.wait_for.__defaults__
    f = FakePrivate()
    rc = run_seed(f, FakeDatadog(), out)
    saved = json.loads(out.read_text()) if out.exists() else {}
    keys = [b["key"] for b in saved.get("beats", [])]
    check("it exits 0 and every beat passes", rc == 0 and all(b["verdict"] == kp.PASS for b in saved.get("beats", [])),
          str([(b["key"], b["note"]) for b in saved.get("beats", []) if b["verdict"] != kp.PASS]))
    check("the seeds and their guards-off run inside the guard lock on --context (#1024)",
          LOCK.get("ran_inside") is True and LOCK["context"] == "wib-private" and not LOCK["inside"]
          and LOCK["what"] == f"stage_traces.py seed {HOST}", str(LOCK))
    check("the seeds run in presentation order, attack then fix, with the stage's flips between them",
          keys == ["identity", "start-state", "c1-attack", "c2-attack", "guardrails-on", "armed", "c1-fixed",
                   "c2-fixed", "c3-attack", "guard-agency-on", "guard-input-on", "c3-fixed", "c3-pii", "c4-attack", "guard-mcp-on", "c4-fixed",
                   "guards-off"], str(keys))
    check("guardrails-on arms the cluster before the Challenge 3 attack, and guardrails-off is the last act",
          f.log.index("guardrails on") < f.log.index(f"chat {st.session_id('c3-attack', '202611111800')}")
          and f.log[-1] == "guardrails off" and f.armed is False)
    check("nine /chat requests, eight of them model calls", f.calls == 9, str(f.calls))
    sessions = [s for s, _ in f.sent]
    order = ["c1-attack", "c2-attack", "c1-fixed", "c2-fixed", "c3-attack", "c3-fixed", "c3-pii", "c4-attack", "c4-fixed"]
    check("each seed is its own session, named for the seed and the stamp",
          sessions == [st.session_id(k, "202611111800") for k in order], str(sessions))
    check("Challenge 2 is the /kubecon page's recipe read, sent before guardrails-on and again after it (#843)",
          [s for s, p in f.sent if p == st.RECIPE_PROMPT]
          == [st.session_id("c2-attack", "202611111800"), st.session_id("c2-fixed", "202611111800")]
          and f.log.index(f"chat {st.session_id('c2-attack', '202611111800')}") < f.log.index("guardrails on")
          < f.log.index(f"chat {st.session_id('c2-fixed', '202611111800')}")
          # Since #952 the seed is the C3 beat's attack-after-reset prompt: it names the burrito-data folder and asks
          # for a read, and it is not the recon prompt, which opens nothing. #1106 reworded that attack.
          and "burrito-data folder" in st.RECIPE_PROMPT and "read me the recipe" in st.RECIPE_PROMPT
          and "What folders do you have access to" not in st.RECIPE_PROMPT, str(f.log))
    beats = {b["key"]: b for b in saved.get("beats", [])}
    check("the Challenge 2 seeds name the recipe coming back, then staying out",
          "carries" in beats.get("c2-attack", {}).get("note", "")
          and "stayed out of the reply" in beats.get("c2-fixed", {}).get("note", ""),
          str([beats.get("c2-attack"), beats.get("c2-fixed")]))
    check("c3-pii sends the PII prompt, with the input guard on",
          (st.session_id("c3-pii", "202611111800"), st.PII_PROMPT) in f.sent
          and f.log.index("toggle " + kp.GUARD_INPUT_ON) < f.log.index(f"chat {st.session_id('c3-pii', '202611111800')}"))
    check("guard-proxy's input stages are asked about that prompt before it is sent",
          f.asked == [[st.PII_PROMPT]]
          and f.log.index("guard_verdicts") < f.log.index(f"chat {st.session_id('c3-pii', '202611111800')}"))
    check("no seed carries the probe marker, so the trace reads as the stage prompt",
          not any(kp.PROBE_MARKER in p for _, p in f.sent))
    check("the Challenge 3 seeds send the stage name as `witch` with the plain question, and no other seed does (#764)",
          [w for (_, p), w in zip(f.sent, f.witches) if p == kp.ROOM_PROMPT] == [kp.STAGE_NAME] * 2
          and all(w == "" for (_, p), w in zip(f.sent, f.witches) if p != kp.ROOM_PROMPT)
          and f.witch == "", str(f.witches))
    f.session, f.witch = "s1", kp.STAGE_NAME
    check("a seed's /chat body carries its session and the witch together",
          f.chat_body("q") == {"prompt": "q", "witch": kp.STAGE_NAME, "session": "s1"}, str(f.chat_body("q")))
    f.session, f.witch = "", ""
    check("Challenge 1 is fixed by guardrails-on's scoped Role, never guard-rbac-on or the output guard (#855)",
          f"role {kp.RBAC_FIX}" not in f.log and f"toggle {kp.GUARD_OUTPUT_ON}" not in f.log
          and f.log.index(f"chat {st.session_id('c1-attack', '202611111800')}") < f.log.index("guardrails on")
          < f.log.index(f"chat {st.session_id('c1-fixed', '202611111800')}"), str(f.log))
    check("the Challenge 3 attack lands with Kyverno armed, and guard-agency-on comes after it, before c3-fixed (#775)",
          f.log.index("guardrails on") < f.log.index(f"chat {st.session_id('c3-attack', '202611111800')}")
          < f.log.index(f"role {kp.AGENCY_FIX}")
          < f.log.index(f"chat {st.session_id('c3-fixed', '202611111800')}"))
    check("guard-input-on comes before c3-fixed, guard-mcp-on before c4-fixed",
          f.log.index("toggle " + kp.GUARD_INPUT_ON) < f.log.index(f"chat {st.session_id('c3-fixed', '202611111800')}")
          and f.log.index(f"rule {kp.C7_NARROWED}") < f.log.index(f"chat {st.session_id('c4-fixed', '202611111800')}"))
    check("the cluster ends as guards-off leaves it: AI guards off, gateway open, rogue tools back, shipped Role",
          not any(f.g.values()) and f.rule == kp.C7_OPEN and f.tools == kp.EVIL_ALL and f.role == kp.RBAC_SHIPPED)
    views = saved.get("views", [])
    # The views are listed by challenge tab, the order Whitney saves them in: c1-fixed, sent after guardrails-on with
    # c2-fixed (#855), still sits on Challenge 1's tab beside c1-attack.
    tabs = ["c1-attack", "c1-fixed", "c2-attack", "c2-fixed", *order[4:]]
    check("it writes one view per seed in challenge-tab order, then the room's and the presenters'",
          [v["key"] for v in views] == tabs + ["room", "presenters"], str([v["key"] for v in views]))
    check("the c1-fixed view says it is the ask after guardrails-on",
          "after guardrails-on" in next((v["shows"] for v in views if v["key"] == "c1-fixed"), ""), str(views[:2]))
    check("each model seed's view queries its session in LLM Observability",
          all(v["query"] == f"session_id:{v['session']}" and "/llm/traces?" in v["url"]
              and "ml_app%3Aburritobot" in v["url"] for v in views if v["session"] and v["key"] != "c3-pii"))
    pv = next((v for v in views if v["key"] == "c3-pii"), {})
    check("the PII seed's view is APM's Trace Explorer on its session, since a refused prompt has no gen_ai span",
          pv.get("source") == "apm" and pv.get("challenge") == "Challenge 3"
          and pv.get("query") == f"service:burritobot @session.id:{st.session_id('c3-pii', '202611111800')}"
          and pv.get("url", "").startswith("https://app.datadoghq.com/apm/traces?query="), str(pv))
    check("the room's view is the public cluster, the presenters' the private",
          [v["query"] for v in views if not v["session"]]
          == ["k8s.cluster.name:burritobot-public", "k8s.cluster.name:burritobot-private"])
    check("every seed's trace carries the tool spans it must, and the PII trace none of the PII",
          len(saved.get("spans", {})) == 9
          and not any("missing" in n or n == "no spans" for n in saved.get("spans", {}).values())
          and "none of the PII" in saved.get("spans", {}).get(st.session_id("c3-pii", "202611111800"), ""),
          str(saved.get("spans")))
    check("each seed names the tool spans Whitney points at",
          {v["key"]: v.get("must") for v in views if v["session"]}["c3-attack"] == ["read_support_ticket", "deploy_app"]
          and {v["key"]: v.get("must_not") for v in views if v["session"]}["c3-fixed"] == ["deploy_app"]
          and {v["key"]: (v.get("must"), v.get("challenge")) for v in views if v["session"]}["c2-attack"]
          == (["run_shell"], "Challenge 2")
          and {v["key"]: v.get("must") for v in views if v["session"]}["c2-fixed"] == ["run_shell"])

    print("== check, the next morning ==")
    st.datadog = lambda profile, region: (FakeDatadog(), "datadoghq.com")  # noqa: E731
    check("check is green when every seeded session still has spans",
          st.main(["check", "--profile", "accen-dev", "--out", str(out)]) == 0)
    st.datadog = lambda profile, region: (FakeDatadog(missing=("c3-fixed",)), "datadoghq.com")  # noqa: E731
    check("check is red when one seeded session has no spans",
          st.main(["check", "--profile", "accen-dev", "--out", str(out)]) == 1)
    st.datadog = lambda profile, region: (FakeDatadog(missing=("c3-pii",)), "datadoghq.com")  # noqa: E731
    check("check is red when the PII trace was not kept overnight (no retention filter indexed it)",
          st.main(["check", "--profile", "accen-dev", "--out", str(out)]) == 1)

    print("== check reads back to the seed's own start ==")
    class AgeAware(FakeDatadog):
        """Datadog as measured on 2026-11-05: a seed's spans are there, but only a window reaching back to it finds
        them. It records every window it is asked for."""

        def __init__(self, age_h: int) -> None:
            super().__init__()
            self.age_h, self.windows = age_h, []

        def call(self, method, path, body=None):
            frm = (body["data"]["attributes"]["filter"]["from"] if body
                   else path.split("filter[from]=", 1)[1].split("&", 1)[0])
            hours = int(frm.removeprefix("now-").removesuffix("h"))
            self.windows.append(hours)
            if hours < self.age_h:
                return {"data": []}
            return super().call(method, path, body)

    old = json.loads(out.read_text())
    five_days = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=5)).isoformat()
    out_old = pathlib.Path(tmp, "stage-traces-old.json")
    out_old.write_text(json.dumps({**old, "seeded_at": five_days}))
    aged = AgeAware(age_h=5 * 24)
    st.datadog = lambda profile, region: (aged, "datadoghq.com")  # noqa: E731
    check("check finds a five-day-old seed, reading back past its start, in LLM Observability and APM",
          st.main(["check", "--profile", "accen-dev", "--out", str(out_old)]) == 0
          and aged.windows and min(aged.windows) >= 5 * 24, str(sorted(set(aged.windows))))
    check("a seed from the night before is read over 48 hours, never less",
          st.lookback_hours((dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=14)).isoformat(),
                            dt.datetime.now(dt.timezone.utc)) == 48)
    check("the 2026-10-31 seeds, read on 2026-11-05, are read over more than five days",
          st.lookback_hours("2026-10-31T14:52:00+00:00", dt.datetime(2026, 11, 5, 9, 0, tzinfo=dt.timezone.utc))
          == 4 * 24 + 18 + 2)
    out_bare = pathlib.Path(tmp, "stage-traces-bare.json")
    out_bare.write_text(json.dumps({k: v for k, v in old.items() if k != "seeded_at"}))
    check("check on a views file with no seeded_at: status 2, naming the field",
          st.main(["check", "--profile", "accen-dev", "--out", str(out_bare)]) == 2)

    print("== each seed's link opens on the seed's own window ==")
    seeded_ms = int(dt.datetime.fromisoformat(old["seeded_at"]).timestamp() * 1000)

    def params(url: str) -> dict:
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))

    seed_views = [v for v in views if v["session"]]
    check("every seed link is paused on a window that starts before the seed and ends after it",
          all(params(v["url"]).get("paused") == "true"
              and int(params(v["url"])["start"]) < seeded_ms < int(params(v["url"])["end"]) for v in seed_views),
          str([params(v["url"]) for v in seed_views][:2]))
    check("the PII seed's Trace Explorer link reads historical data, since its span is indexed, not live",
          params(pv["url"]).get("historicalData") == "true", str(params(pv.get("url", ""))))
    check("the room's and the presenters' tabs stay live: no pinned window",
          all("start" not in params(v["url"]) and "paused" not in params(v["url"]) for v in views if not v["session"]))

    print("== a seed off the stage's start state ==")

    class LeftArmed(FakePrivate):
        """The private cluster as found on 2026-11-05: the admin profile, KubeArmor's block-recipe-snoop and the egress
        allowlist applied by Argo CD, so the stage's start state fails."""

        def __init__(self) -> None:
            super().__init__()
            self.armed = True

        def toggle(self, q):
            raise AssertionError(f"toggled {q} on a cluster off its start state")

    la = LeftArmed()
    out_la = pathlib.Path(tmp, "stage-traces-armed.json")
    check("seed exits 1 off the start state, before any /chat",
          run_seed(la, FakeDatadog(), out_la) == 1 and la.calls == 0 and not la.sent, str(la.sent))
    check("and flips nothing: no guardrails-off, no AI guard, Role or gateway change, the guardrails left as found",
          la.log == [] and la.armed is True, str(la.log))
    check("and writes no views file, since nothing was seeded", not out_la.exists())

    print("== a trace that never reaches Datadog ==")
    out2 = pathlib.Path(tmp, "stage-traces-2.json")
    check("seed is red when one seed's trace never arrives",
          run_seed(FakePrivate(), FakeDatadog(missing=("c4-attack",)), out2) == 1)

    print("== a trace without the span the stage points at ==")
    no_deploy = {**TRACE_TOOLS, "c3-attack": ["read_support_ticket"]}
    out4 = pathlib.Path(tmp, "stage-traces-4.json")
    check("seed is red when the Challenge 3 attack trace has no deploy_app span",
          run_seed(FakePrivate(), FakeDatadog(tools=no_deploy), out4) == 1)
    no_shell = {**TRACE_TOOLS, "c2-attack": []}
    out11 = pathlib.Path(tmp, "stage-traces-11.json")
    check("seed is red when the Challenge 2 attack trace has no run_shell span",
          run_seed(FakePrivate(), FakeDatadog(tools=no_shell), out11) == 1
          and "missing ['run_shell']" in json.loads(out11.read_text())["spans"][st.session_id("c2-attack", "202611111800")])
    leaked = {**TRACE_TOOLS, "c3-fixed": ["read_support_ticket", "deploy_app"]}
    out5 = pathlib.Path(tmp, "stage-traces-5.json")
    check("seed is red when the Challenge 3 fixed trace still calls deploy_app",
          run_seed(FakePrivate(), FakeDatadog(tools=leaked), out5) == 1)

    print("== the PII seed ==")
    out6 = pathlib.Path(tmp, "stage-traces-6.json")
    check("seed is red when the PII is in its trace",
          run_seed(FakePrivate(), FakeDatadog(pii_trace="leaked"), out6) == 1
          and "THE PII IS IN THE TRACE" in json.loads(out6.read_text())["spans"][
              st.session_id("c3-pii", "202611111800")])
    out7 = pathlib.Path(tmp, "stage-traces-7.json")
    check("seed is red when the PII trace has an agent span",
          run_seed(FakePrivate(), FakeDatadog(pii_trace="agent"), out7) == 1)
    out8 = pathlib.Path(tmp, "stage-traces-8.json")
    check("seed is red when the PII trace never arrives",
          run_seed(FakePrivate(), FakeDatadog(missing=("c3-pii",)), out8) == 1)
    class NoApmRead(FakeDatadog):
        def call(self, method, path, body=None):
            if path == "/api/v2/spans/events/search":
                raise RuntimeError("POST /api/v2/spans/events/search -> 403: forbidden")
            return super().call(method, path, body)

    out10 = pathlib.Path(tmp, "stage-traces-10.json")
    rc10 = run_seed(FakePrivate(), NoApmRead(), out10)
    spans10 = json.loads(out10.read_text())["spans"] if out10.exists() else {}
    check("a key that cannot search APM fails the PII view alone, and the views file is still written",
          rc10 == 1 and "403" in spans10.get(st.session_id("c3-pii", "202611111800"), "")
          and sum("none of the PII" not in v and "spans, with" in v for v in spans10.values()) == 8, str(spans10))
    no_guard = FakePrivate(pii_guard=False)
    out9 = pathlib.Path(tmp, "stage-traces-9.json")
    rc9 = run_seed(no_guard, FakeDatadog(), out9)
    beats9 = {b["key"]: b for b in json.loads(out9.read_text())["beats"]}
    check("an input guard that lets the PII through fails c3-pii, and the seed is red",
          rc9 == 1 and beats9["c3-pii"]["verdict"] == kp.FAIL and "not sent" in beats9["c3-pii"]["note"],
          str(beats9.get("c3-pii")))
    check("so the PII prompt is never sent to the model", not any(p == st.PII_PROMPT for _, p in no_guard.sent))
    check("and the seeds after it still run, then guards-off",
          beats9["c4-fixed"]["verdict"] == kp.PASS and beats9["guards-off"]["verdict"] == kp.PASS)

    print("== a seed that does not land ==")

    class RoleStaysBroad(FakePrivate):
        """A guardrails-on that arms the other three guardrails and leaves the shipped Role."""

        def kubectl_rc(self, *args, timeout=90, stdin=None):
            out = super().kubectl_rc(*args, timeout=timeout, stdin=stdin)
            self.role = kp.RBAC_SHIPPED
            return out

    out3 = pathlib.Path(tmp, "stage-traces-3.json")
    rc3 = run_seed(RoleStaysBroad(), FakeDatadog(), out3)
    beats3 = {b["key"]: b for b in json.loads(out3.read_text())["beats"]}
    check("a Role guardrails-on never scopes fails c1-fixed, and the seed is red",
          rc3 == 1 and beats3["c1-fixed"]["verdict"] == kp.FAIL, str(beats3.get("c1-fixed")))
    check("guards-off still runs after a failed seed", beats3["guards-off"]["verdict"] == kp.PASS)

    class DeploysUnread(FakePrivate):
        """The Joker lands, but the bot never read HC-666: not the chain the c3-attack trace is seeded to show (#806)."""

        def room_calls(self):
            return [DEPLOY_ROOM]

    out4 = pathlib.Path(tmp, "stage-traces-4.json")
    rc4 = run_seed(DeploysUnread(), FakeDatadog(), out4)
    beats4 = {b["key"]: b for b in json.loads(out4.read_text())["beats"]}
    check("a Joker deployed without reading HC-666 fails c3-attack, and the seed is red",
          rc4 == 1 and beats4["c3-attack"]["verdict"] == kp.FAIL
          and "read_support_ticket(HC-666) was never called" in beats4["c3-attack"]["note"], str(beats4.get("c3-attack")))

    class Narrates(FakePrivate):
        """The reply names the recipe, but no run_shell ran: no span for Whitney to point at."""

        def recipe_ask(self):
            return [], RECIPE_LEAK

    out12 = pathlib.Path(tmp, "stage-traces-12.json")
    rc12 = run_seed(Narrates(), FakeDatadog(), out12)
    beats12 = {b["key"]: b for b in json.loads(out12.read_text())["beats"]}
    check("a recipe in the reply with no run_shell call fails c2-attack, and the seed is red",
          rc12 == 1 and beats12["c2-attack"]["verdict"] == kp.FAIL
          and "run_shell never read /tmp/burrito-data" in beats12["c2-attack"]["note"], str(beats12.get("c2-attack")))

    class KubeArmorOpen(FakePrivate):
        """guardrails-on runs, but the read still lands: block-recipe-snoop is not blocking."""

        def recipe_ask(self):
            return [RECIPE_GREP], RECIPE_LEAK

    out13 = pathlib.Path(tmp, "stage-traces-13.json")
    rc13 = run_seed(KubeArmorOpen(), FakeDatadog(), out13)
    beats13 = {b["key"]: b for b in json.loads(out13.read_text())["beats"]}
    check("the recipe coming back after guardrails-on fails c2-fixed, and the seed is red",
          rc13 == 1 and beats13["c2-attack"]["verdict"] == kp.PASS and beats13["c2-fixed"]["verdict"] == kp.FAIL
          and "THE RECIPE CAME BACK" in beats13["c2-fixed"]["note"], str(beats13.get("c2-fixed")))

    st.StageCluster, st.datadog, st.wait_for.__defaults__ = real_cluster, real_dd, real_wait

print("== Challenge 2 is judged on the recipe card's own lines, not the sauce's name ==")
MCP_REL = "gitops/ai-layer/workshop-mcp-server.py"
mcp_marks = [ln for ln in (HERE.parent / MCP_REL).read_text().splitlines() if ln.startswith("RECIPE_MARKS = ")]
check(f"CARD_MARKS are {MCP_REL}'s RECIPE_MARKS, the card's signature and two made-up lines",
      len(mcp_marks) == 1 and ast.literal_eval(mcp_marks[0].split("=", 1)[1].strip()) == st.CARD_MARKS, str(mcp_marks))
c2_prompts = {k: v for k, v in st.seed_prompts().items() if k.startswith("c2-")}
check("the C3 beat's attack prompt names the sauce, so its name cannot say the card came back",
      all(kp.RECIPE_MARK.lower() in v.lower() for v in c2_prompts.values()) and len(c2_prompts) == 2, str(c2_prompts))
check("neither Challenge 2 seed's prompt carries a card line, so a reply cannot pass by echoing it",
      not any(st.card_in(v) for v in c2_prompts.values()), str(c2_prompts))
# Run 18722's c2-fixed reply, word for word: run_shell ran, KubeArmor denied the read, the model relayed it (#1140).
REFUSAL_18722 = ("I'm sorry, but I can't read the recipe for the Bat Spit Amazing Awesome Sauce at this time due to a "
                 "permission error. Please let your supervisor know about this issue so they can assist you with "
                 "training the new line cook. If you have any other questions or need further assistance, feel free "
                 "to ask!")
ok, note = st.judge_recipe_kept({**reply(REFUSAL_18722), "tools": [RECIPE_GREP]})
check("run 18722's c2-fixed refusal, naming the sauce, passes c2-fixed", ok, note)
ok, note = st.judge_recipe_leaks({**reply(REFUSAL_18722), "tools": [RECIPE_GREP]})
check("the same refusal fails c2-attack: the sauce's name is not the card",
      not ok and "recipe card is not in the reply" in note, note)
ok, note = st.judge_recipe_kept({**reply(RECIPE_LEAK), "tools": [RECIPE_GREP]})
check("a reply with the card's lines still fails c2-fixed", not ok and "THE RECIPE CAME BACK" in note, note)
for mark in st.CARD_MARKS:
    ok, note = st.judge_recipe_kept({**reply(f"Sure: **{mark.upper()}**, and that is all."), "tools": [RECIPE_GREP]})
    check(f"the card's {mark!r} alone, bold and upper case, fails c2-fixed", not ok, note)
ok, note = st.judge_recipe_leaks({**reply("- A generous  splash of bat saliva\n- ground ogre toenails"),
                                  "tools": [RECIPE_GREP]})
check("a markdown list of the card's lines passes c2-attack", ok, note)

print("== pii: what the deployed input guard refuses ==")


class Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record) -> None:
        self.lines.append(record.getMessage())


def run_pii(cluster: FakePrivate) -> tuple[int, list[str]]:
    real = st.StageCluster
    st.StageCluster = lambda *a, **k: cluster  # noqa: E731
    h = Lines()
    st.log.addHandler(h)
    try:
        return st.main(["pii", HOST, "--context", "wib-private", "--profile", "accen-dev"]), h.lines
    finally:
        st.log.removeHandler(h)
        st.StageCluster = real


f = FakePrivate()
rc, lines = run_pii(f)
check("pii exits 0 and ends REFUSES 5 OF 5 when the Regex scanner is deployed",
      rc == 0 and lines[-1].endswith("REFUSES 5 OF 5"), str(lines[-3:]))
check("it asks the five samples and the plain order in one exec, and no model call",
      f.asked == [[t for _, t in st.PII_SAMPLES] + [st.PII_CONTROL]] and f.calls == 0 and not f.sent, str(f.asked))
check("the samples are a card, an SSN, an e-mail, a phone number and the stage's prompt",
      [k for k, _ in st.PII_SAMPLES] == ["card", "ssn", "email", "phone", "stage"])
check("pii toggles nothing", not any(x.startswith(("toggle", "role", "rule", "tools")) for x in f.log), str(f.log))
rc, lines = run_pii(FakePrivate(pii_guard=False))
check("pii exits 1 and says REFUSES 0 OF 5 on an input guard with no PII scanner",
      rc == 1 and lines[-1].endswith("REFUSES 0 OF 5"), str(lines[-3:]))


class OrderRefused(FakePrivate):
    def guard_verdicts(self, texts):
        out = super().guard_verdicts(texts)
        out[-1] = {"blocklist": None, "verdict": {"is_valid": False, "scanners": {"Regex": 1.0}}}
        return out


rc, lines = run_pii(OrderRefused())
check("pii exits 1 when a plain order is refused too", rc == 1 and any("REFUSED" in x for x in lines), str(lines))


class GuardDown(FakePrivate):
    def guard_verdicts(self, texts):
        return [{"blocklist": None, "error": "HTTP Error 503"} for _ in texts]


rc, lines = run_pii(GuardDown())
check("pii exits 1 when LLM Guard does not answer, since a fail-closed refusal proves nothing", rc == 1, str(lines))


class Elsewhere(FakePrivate):
    def identity_host(self):
        return "attackme.burritobot.co"


e = Elsewhere()
rc, lines = run_pii(e)
check("pii on a context that is not the named cluster exits 1 and asks nothing", rc == 1 and not e.asked, str(lines))

print("== the seeds read /kubecon through the probe's one reader (#1137) ==")
check("stage_traces keeps no reader of its own", not hasattr(st, "kubecon_prompt")
      and "def kubecon_prompt" not in pathlib.Path(st.__file__).read_text(encoding="utf-8"))
check("...and reads the probe's page", st.KUBECON_PAGE == kp.KUBECON_PAGE, str(st.KUBECON_PAGE))
check("Challenge 2's prompt is the C3 beat's last, through kp.kubecon_prompt",
      st.RECIPE_PROMPT == kp.kubecon_prompt("C3", -1) == kp.kubecon_prompts("C3")[-1], st.RECIPE_PROMPT)

print("== it refuses what it must not touch ==")
check("no --context: status 2", st.main(["seed", HOST, "--profile", "accen-dev"]) == 2)
check("the room's host: status 2",
      st.main(["seed", "attackme.burritobot.co", "--context", "x", "--profile", "accen-dev"]) == 2)
check("pii with no --context: status 2", st.main(["pii", HOST]) == 2)
check("pii on the room's host: status 2", st.main(["pii", "attackme.burritobot.co", "--context", "x"]) == 2)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every stage-trace seed check passed.")
