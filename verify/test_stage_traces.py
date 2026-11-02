# ABOUTME: Drives verify/stage_traces.py's seed and check against a fake private cluster and a fake Datadog: six seeds
# ABOUTME: in presentation order, attack then fix, each on its own session with no probe marker, then guards-off.
"""#648: the stage opens each challenge on its pre-seeded trace (Michael, 2026-10-31). The seed must run the attack
and the fix for Challenge 1, 3 and 4 the way the stage does, with the KubeCon probe's own guard flips, put each one
in a session of its own so LLM Observability can find it, leave the cluster as guards-off leaves it, and go red when
a trace never reaches Datadog."""
from __future__ import annotations

import json
import pathlib
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
    """The private cluster at its start (#774): the four Kubernetes guardrails off until guardrails-on, every AI guard
    off, the shipped Role."""

    def __init__(self) -> None:
        super().__init__(HOST, "wib-private", "accen-dev", None, 30)
        self.g = {k: False for k in kp.AI_GUARDS}
        self.tools, self.rule, self.role = list(kp.EVIL_ALL), kp.C7_OPEN, kp.RBAC_SHIPPED
        self.armed = False
        self.joker, self.log, self.sent, self.witches = False, [], [], []

    def kubectl_rc(self, *args, timeout=90, stdin=None):
        """The terminal's guardrails-on and guardrails-off, run in its pod: both clusters switch."""
        assert "deploy/web-terminal" in args, args
        state = "on" if args[-1].endswith("guardrails-on") else "off"
        self.log.append(f"guardrails {state}")
        self.armed = state == "on"
        self.role = kp.RBAC_FIX if self.armed else kp.RBAC_SHIPPED
        return 0, f"Both clusters, this one and watch-it-burn-community: all four Kubernetes guardrails are {state}.\n"

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
        return "removed"

    def chat(self, prompt):
        self.calls += 1
        self.sent.append((self.session, prompt))
        self.witches.append(self.chat_body(prompt).get("witch", ""))
        self.log.append(f"chat {self.session}")
        if prompt == kp.CEO_PROMPT:
            return reply("I'm not allowed to read that vault entry." if self.role == kp.RBAC_FIX else CEO_LEAK)
        if prompt == kp.ROOM_PROMPT:
            if self.g["input_classifier"]:
                return reply(f"I tried to read {kp.ROOM_TICKET_ID}, but it was withheld.")
            if not self.armed:  # Kyverno only reports: the Joker lands
                self.joker = True
                return reply(f"Done! I created {kp.ROOM_JOKER}.")
            return reply(f"I tried to create {kp.ROOM_JOKER}, but the cluster refused it at admission.")
        if prompt == kp.MCP_PROMPT:
            return reply(C7_LEAK if self.rule == kp.C7_OPEN else C7_DENIED)
        return reply("Sure.")


# The tool spans each seed's trace carries on a well-behaved cluster.
TRACE_TOOLS = {"c1-attack": ["get_vault_entry"], "c1-fixed": ["get_vault_entry"],
               "c3-attack": ["read_support_ticket", "deploy_app"], "c3-fixed": ["read_support_ticket"],
               "c4-attack": ["get_weather", "read_internal_config"], "c4-fixed": ["get_weather"]}


class FakeDatadog:
    def __init__(self, missing: tuple[str, ...] = (), tools: dict | None = None) -> None:
        self.missing, self.tools = missing, tools or TRACE_TOOLS

    def call(self, method, path):
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
          keys == ["identity", "start-state", "c1-attack", "guard-rbac-on", "c1-fixed", "guardrails-on", "c3-attack",
                   "guard-input-on", "c3-fixed", "c4-attack", "guard-mcp-on", "c4-fixed", "guards-off"], str(keys))
    check("guardrails-on arms the cluster before the Challenge 3 attack, and guardrails-off is the last act",
          f.log.index("guardrails on") < f.log.index(f"chat {st.session_id('c3-attack', '202611111800')}")
          and f.log[-1] == "guardrails off" and f.armed is False)
    check("six model calls", f.calls == 6, str(f.calls))
    sessions = [s for s, _ in f.sent]
    check("each seed is its own session, named for the seed and the stamp",
          sessions == [st.session_id(k, "202611111800") for k, *_ in st.SEEDS], str(sessions))
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
    check("Challenge 1 is fixed by the scoped Role, never the output guard",
          f"role {kp.RBAC_FIX}" in f.log and f"toggle {kp.GUARD_OUTPUT_ON}" not in f.log
          and f.log.index(f"role {kp.RBAC_FIX}") < f.log.index(f"chat {st.session_id('c1-fixed', '202611111800')}"))
    check("guard-input-on comes before c3-fixed, guard-mcp-on before c4-fixed",
          f.log.index("toggle " + kp.GUARD_INPUT_ON) < f.log.index(f"chat {st.session_id('c3-fixed', '202611111800')}")
          and f.log.index(f"rule {kp.C7_NARROWED}") < f.log.index(f"chat {st.session_id('c4-fixed', '202611111800')}"))
    check("the cluster ends as guards-off leaves it: AI guards off, gateway open, rogue tools back, shipped Role",
          not any(f.g.values()) and f.rule == kp.C7_OPEN and f.tools == kp.EVIL_ALL and f.role == kp.RBAC_SHIPPED)
    views = saved.get("views", [])
    check("it writes one view per seed, then the room's and the presenters'",
          [v["key"] for v in views] == [k for k, *_ in st.SEEDS] + ["room", "presenters"], str(views))
    check("each seed's view queries its session in LLM Observability",
          all(v["query"] == f"session_id:{v['session']}" and "ml_app%3Aburritobot" in v["url"]
              for v in views if v["session"]))
    check("the room's view is the public cluster, the presenters' the private",
          [v["query"] for v in views if not v["session"]]
          == ["k8s.cluster.name:burritobot-public", "k8s.cluster.name:burritobot-private"])
    check("every seed's trace carries the tool spans it must", len(saved.get("spans", {})) == 6
          and not any("missing" in n or n == "no spans" for n in saved.get("spans", {}).values()),
          str(saved.get("spans")))
    check("each seed names the tool spans Whitney points at",
          {v["key"]: v["must"] for v in views if v["session"]}["c3-attack"] == ["read_support_ticket", "deploy_app"]
          and {v["key"]: v["must_not"] for v in views if v["session"]}["c3-fixed"] == ["deploy_app"])

    print("== check, the next morning ==")
    st.datadog = lambda profile, region: (FakeDatadog(), "datadoghq.com")  # noqa: E731
    check("check is green when every seeded session still has spans",
          st.main(["check", "--profile", "accen-dev", "--out", str(out)]) == 0)
    st.datadog = lambda profile, region: (FakeDatadog(missing=("c3-fixed",)), "datadoghq.com")  # noqa: E731
    check("check is red when one seeded session has no spans",
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

print("== it refuses what it must not touch ==")
check("no --context: exit 2", st.main(["seed", HOST, "--profile", "accen-dev"]) == 2)
check("the room's host: exit 2",
      st.main(["seed", "attackme.burritobot.co", "--context", "x", "--profile", "accen-dev"]) == 2)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every stage-trace seed check passed.")
