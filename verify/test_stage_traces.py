# ABOUTME: Drives verify/stage_traces.py's pii, seed and check against a fake private cluster and a fake Datadog: seven
# ABOUTME: seeds in presentation order, each on its own session with no probe marker, then guards-off.
"""#648: the stage opens each challenge on its pre-seeded trace (Michael, 2026-10-31). The seed must run the attack
and the fix for Challenge 1, 3 and 4 the way the stage does, with the KubeCon probe's own guard flips, put each one
in a session of its own so Datadog can find it, leave the cluster as guards-off leaves it, and go red when a trace
never reaches Datadog. Challenge 3 adds someone else's PII refused by the input guard (Whitney, 2026-10-29): it is
sent only after guard-proxy's own input stages say they refuse it, and its trace must hold none of the PII.
`pii` measures that guard with no model call and must end REFUSES 5 OF 5."""
from __future__ import annotations

import json
import logging
import pathlib
import re
import sys
import tempfile

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


class FakePrivate(st.StageCluster):
    """The private cluster: Kyverno, NetworkPolicy and KubeArmor armed, every AI guard off, the shipped Role."""

    def __init__(self, pii_guard: bool = True) -> None:
        super().__init__(HOST, "wib-private", "accen-dev", None, 30)
        self.g = {k: False for k in kp.AI_GUARDS}
        self.tools, self.rule, self.role = list(kp.EVIL_ALL), kp.C7_OPEN, kp.RBAC_SHIPPED
        self.joker, self.log, self.sent = False, [], []
        self.pii_guard = pii_guard  # whether LLM Guard's input scanners include the PII Regex
        self.asked: list[list[str]] = []

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
            "networkpolicy": True, "kyverno": True, "kubearmor": True, "falco": True,
            "tool_allowlist": self.rule == kp.C7_NARROWED}}

    def identity_host(self):
        return HOST

    def measure(self):
        return {"guards": dict(self.g), "evil_tools": list(self.tools), "c7_rule": self.rule,
                "kyverno_actions": ["Deny"], "networkpolicy": True, "kubearmor_action": "Block"}

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
        return "removed"

    def chat(self, prompt):
        self.calls += 1
        self.sent.append((self.session, prompt))
        self.log.append(f"chat {self.session}")
        if prompt == kp.CEO_PROMPT:
            return reply("I'm not allowed to read that vault entry." if self.role == kp.RBAC_FIX else CEO_LEAK)
        if prompt == kp.ROOM_PROMPT:
            if self.g["input_classifier"]:
                return reply(f"I tried to read {kp.ROOM_TICKET_ID}, but it was withheld.")
            return reply(f"I tried to create {kp.ROOM_JOKER}, but the cluster refused it at admission.")
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
        return {"data": [{"attributes": {"name": n, "tags": tags}} for n in ["invocation", *self.tools[key]]]}


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
    check("the seeds run in presentation order, attack then fix, with the stage's flips between them",
          keys == ["identity", "start-state", "c1-attack", "guard-rbac-on", "c1-fixed", "c3-attack", "guard-input-on",
                   "c3-fixed", "c3-pii", "c4-attack", "guard-mcp-on", "c4-fixed", "guards-off"], str(keys))
    check("seven /chat requests", f.calls == 7, str(f.calls))
    sessions = [s for s, _ in f.sent]
    order = ["c1-attack", "c1-fixed", "c3-attack", "c3-fixed", "c3-pii", "c4-attack", "c4-fixed"]
    check("each seed is its own session, named for the seed and the stamp",
          sessions == [st.session_id(k, "202611111800") for k in order], str(sessions))
    check("c3-pii sends the PII prompt, with the input guard on",
          (st.session_id("c3-pii", "202611111800"), st.PII_PROMPT) in f.sent
          and f.log.index("toggle " + kp.GUARD_INPUT_ON) < f.log.index(f"chat {st.session_id('c3-pii', '202611111800')}"))
    check("guard-proxy's input stages are asked about that prompt before it is sent",
          f.asked == [[st.PII_PROMPT]]
          and f.log.index("guard_verdicts") < f.log.index(f"chat {st.session_id('c3-pii', '202611111800')}"))
    check("no seed carries the probe marker, so the trace reads as the stage prompt",
          not any(kp.PROBE_MARKER in p for _, p in f.sent))
    check("Challenge 1 is fixed by the scoped Role, never the output guard",
          f"role {kp.RBAC_FIX}" in f.log and f"toggle {kp.GUARD_OUTPUT_ON}" not in f.log
          and f.log.index(f"role {kp.RBAC_FIX}") < f.log.index(f"chat {st.session_id('c1-fixed', '202611111800')}"))
    check("guard-input-on comes before c3-fixed, guard-mcp-on before c4-fixed",
          f.log.index("toggle " + kp.GUARD_INPUT_ON) < f.log.index(f"chat {st.session_id('c3-fixed', '202611111800')}")
          and f.log.index(f"rule {kp.C7_NARROWED}") < f.log.index(f"chat {st.session_id('c4-fixed', '202611111800')}"))
    check("the cluster ends as guards-off leaves it: AI guards off, gateway open, rogue tools back, shipped Role",
          not any(f.g.values()) and f.rule == kp.C7_OPEN and f.tools == kp.EVIL_ALL and f.role == kp.RBAC_SHIPPED)
    views = saved.get("views", [])
    check("it writes one view per seed in presentation order, then the room's and the presenters'",
          [v["key"] for v in views] == order + ["room", "presenters"], str([v["key"] for v in views]))
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
          len(saved.get("spans", {})) == 7
          and not any("missing" in n or n == "no spans" for n in saved.get("spans", {}).values())
          and "none of the PII" in saved.get("spans", {}).get(st.session_id("c3-pii", "202611111800"), ""),
          str(saved.get("spans")))
    check("each seed names the tool spans Whitney points at",
          {v["key"]: v.get("must") for v in views if v["session"]}["c3-attack"] == ["read_support_ticket", "deploy_app"]
          and {v["key"]: v.get("must_not") for v in views if v["session"]}["c3-fixed"] == ["deploy_app"])

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

    print("== a trace that never reaches Datadog ==")
    out2 = pathlib.Path(tmp, "stage-traces-2.json")
    check("seed is red when one seed's trace never arrives",
          run_seed(FakePrivate(), FakeDatadog(missing=("c4-attack",)), out2) == 1)

    print("== a trace without the span the stage points at ==")
    no_deploy = {**TRACE_TOOLS, "c3-attack": ["read_support_ticket"]}
    out4 = pathlib.Path(tmp, "stage-traces-4.json")
    check("seed is red when the Challenge 3 attack trace has no deploy_app span",
          run_seed(FakePrivate(), FakeDatadog(tools=no_deploy), out4) == 1)
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
          and sum("none of the PII" not in v and "spans, with" in v for v in spans10.values()) == 6, str(spans10))
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
        def apply_fix(self, name):
            self.log.append(f"role {name}")
            return 0, "unchanged\n"

    out3 = pathlib.Path(tmp, "stage-traces-3.json")
    rc3 = run_seed(RoleStaysBroad(), FakeDatadog(), out3)
    beats3 = {b["key"]: b for b in json.loads(out3.read_text())["beats"]}
    check("a Role that never scopes fails c1-fixed, and the seed is red",
          rc3 == 1 and beats3["c1-fixed"]["verdict"] == kp.FAIL, str(beats3.get("c1-fixed")))
    check("guards-off still runs after a failed seed", beats3["guards-off"]["verdict"] == kp.PASS)

    st.StageCluster, st.datadog, st.wait_for.__defaults__ = real_cluster, real_dd, real_wait

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

print("== it refuses what it must not touch ==")
check("no --context: exit 2", st.main(["seed", HOST, "--profile", "accen-dev"]) == 2)
check("the room's host: exit 2",
      st.main(["seed", "attackme.burritobot.co", "--context", "x", "--profile", "accen-dev"]) == 2)
check("pii with no --context: exit 2", st.main(["pii", HOST]) == 2)
check("pii on the room's host: exit 2", st.main(["pii", "attackme.burritobot.co", "--context", "x"]) == 2)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every stage-trace seed check passed.")
