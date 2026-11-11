# ABOUTME: Offline checks for verify/test_coc_floor_probes_live.py (#1293): its checks run against fake KubeCon clusters and
# ABOUTME: fake probe runs, pass on a healthy pair, and fail on each way #1267's probe criterion can stop holding.
"""test_coc_floor_probes_live.py is the live test for #1267's criterion that every challenge still lands with the
code-of-conduct floor on and every guardrail off: the KubeCon probe's community and admin runs green. It needs both
clusters and spends model calls. This runs its run_checks against fakes, the clusters' reads and the probe's output
both faked, so each way the criterion can break is shown to fail it: a floor layer off on either cluster, a guardrail
left on, a probe red, a challenge beat missing from a run, a probe that did not run, and a cluster left with a
guardrail on or the floor off at the end. It also holds that no probe runs, so no model call is spent, when the start
is not the floor on with every guardrail off, and that the live test is in run-e2e.sh's suite. Nothing here touches the
network or a cluster.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import test_coc_floor_probes_live as live  # noqa: E402

# The probe, read through the live test, which runs it: this test has no reason to import it on its own.
kp = live.kp

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


HOSTS = {"private": "burritobot-private.burritobot.co", "community": kp.COMMUNITY_HOSTS[0]}
CONTROLS = {"ai": {k: False for k in kp.AI_GUARDS},
            "infra": {**{k: False for k in live.INFRA_SWITCHED}, "falco": True},
            "always_on": {"code_of_conduct": True}}
MEASURE = {"guards": {k: False for k in kp.AI_GUARDS}, "evil_tools": list(kp.EVIL_ALL), "c7_rule": kp.C7_OPEN,
           "kyverno_actions": ["Audit"], "breakout_actions": ["Audit"], "rbac_scoped": False, "networkpolicy": False,
           "kubearmor_action": None, "kubearmor_unenforced": []}
LAYERS = {k: True for k in live.FLOOR_LAYERS}


class FakeCluster:
    """One KubeCon cluster as the live test reads it. `after` is what its reads turn into once a probe has run."""

    def __init__(self, name: str, host: str) -> None:
        self.name = name
        self._host = host
        self.state = {"controls": copy.deepcopy(CONTROLS), "measure": copy.deepcopy(MEASURE),
                      "layers": dict(LAYERS)}
        self.after: dict | None = None
        self.log: list[str] = []

    def host(self) -> str | None:
        return self._host

    def controls(self) -> dict | None:
        return self.state["controls"]

    def floor_layers(self) -> dict[str, bool]:
        return self.state["layers"]

    def measure(self) -> dict:
        return self.state["measure"]

    def floor_log(self, since: dt.datetime) -> list[str]:
        return self.log


def green_out(role: str, drop: str | None = None, fail: str | None = None) -> tuple[int, str]:
    """What the probe prints with --json on a run: every beat PASS, or one dropped or FAIL, with its verdict lines."""
    results = [{"key": b.key, "segment": b.segment, "title": b.title,
                "verdict": kp.FAIL if b.key == fail else kp.PASS, "note": "fake"}
               for b in live.expected_beats(role) if b.key != drop]
    fails = sum(r["verdict"] == kp.FAIL for r in results)
    out = (json.dumps(results, indent=2) + f"\n\n{len(results)} beats: {len(results) - fails} PASS, {fails} FAIL\n"
           + ("KUBECON PROBE GREEN\n" if not fails else "KUBECON PROBE RED\n"))
    return (1 if fails else 0), out


class FakeProbe:
    """The probe runner: records each run, answers green unless told otherwise, and applies the clusters' `after`."""

    def __init__(self, clusters: list[FakeCluster], answers: dict | None = None) -> None:
        self.clusters = clusters
        self.answers = answers or {}
        self.runs: list[tuple] = []

    def __call__(self, role: str, host: str, context: str, switch: str | None) -> tuple[int, str]:
        self.runs.append((role, host, context, switch))
        for c in self.clusters:
            if c.after:
                c.state.update(c.after)
        return self.answers.get(role) or green_out(role)


def scenario(mutate=None, answers: dict | None = None) -> tuple[list[str], FakeProbe]:
    private, community = FakeCluster("watch-it-burn-private", HOSTS["private"]), \
        FakeCluster("watch-it-burn-community", HOSTS["community"])
    if mutate:
        mutate(private, community)
    probe = FakeProbe([private, community], answers)
    failed: list[str] = []

    def quiet(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            failed.append(f"{name}: {detail}")

    live.run_checks(private, community, probe, quiet)
    return failed, probe


# --- the healthy pair ---------------------------------------------------------------------------------------------
failed, probe = scenario()
check("a healthy pair passes every check", not failed, "; ".join(failed))
check("it runs the admin probe on the private cluster, then the community probe with the private cluster's terminal",
      probe.runs == [("admin", HOSTS["private"], "watch-it-burn-private", None),
                     ("community", HOSTS["community"], "watch-it-burn-community", "watch-it-burn-private")],
      str(probe.runs))
check("Falco's badge on (the private cluster runs it) is not read as a guardrail on", not failed)


def fails(name: str, mutate=None, answers: dict | None = None, *, probes_run: bool, mentions: str) -> None:
    got, p = scenario(mutate, answers)
    check(f"fails: {name}", bool(got) and any(mentions in f for f in got), "; ".join(got) or "no check failed")
    if not probes_run:
        check(f"  and runs no probe, so spends no model call: {name}", not p.runs, str(p.runs))


def set_(path: str, value, which: str = "community", when: str = "start"):
    def mutate(private: FakeCluster, community: FakeCluster) -> None:
        c = community if which == "community" else private
        target = copy.deepcopy(c.state) if when == "end" else c.state
        keys = path.split(".")
        node = target
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
        if when == "end":
            c.after = target
    return mutate


# --- the floor off at the start: each layer, on each cluster --------------------------------------------------------
for which in ("private", "community"):
    fails(f"guard-proxy's /chat check off on {which} (always_on.code_of_conduct false)",
          set_("controls.always_on.code_of_conduct", False, which), probes_run=False, mentions="floor is on")
    for layer in live.FLOOR_LAYERS:
        fails(f"the floor's {layer} layer missing on {which}", set_(f"layers.{layer}", False, which),
              probes_run=False, mentions="floor is on")
fails("/controls unreadable", set_("controls", None, "private"), probes_run=False, mentions="floor is on")

# --- a guardrail on at the start --------------------------------------------------------------------------------------
for guard in kp.AI_GUARDS:
    fails(f"the AI guard {guard} on", set_(f"controls.ai.{guard}", True), probes_run=False, mentions="guardrail is off")
for badge in live.INFRA_SWITCHED:
    fails(f"the {badge} badge on", set_(f"controls.infra.{badge}", True, "private"), probes_run=False,
          mentions="guardrail is off")
fails("Kyverno already at Deny (the probe's start-state read)", set_("measure.kyverno_actions", ["Deny"]),
      probes_run=False, mentions="guardrail is off")
fails("the workshop-agent Role already scoped", set_("measure.rbac_scoped", True, "private"), probes_run=False,
      mentions="guardrail is off")
fails("the C7 gateway rule narrowed", set_("measure.c7_rule", "narrowed", "private"), probes_run=False,
      mentions="guardrail is off")

# --- the probes not green -------------------------------------------------------------------------------------------
challenge = {role: [b.key for b in live.expected_beats(role) if b.stage] for role in ("admin", "community")}
check("both runs have challenge beats to require", all(challenge.values()), str(challenge))
for role in ("admin", "community"):
    for key in challenge[role]:
        fails(f"{role} challenge beat {key} FAIL", answers={role: green_out(role, fail=key)}, probes_run=True,
              mentions=f"challenge beat {key} FAIL")
        rc, out = green_out(role, drop=key)
        fails(f"{role} challenge beat {key} not reported, the run otherwise green", answers={role: (rc, out)},
              probes_run=True, mentions=f"challenge beat {key} was not reported")
    final = live.expected_beats(role)[-1].key
    fails(f"{role} final beat {final} FAIL", answers={role: green_out(role, fail=final)}, probes_run=True,
          mentions=f"beat {final} FAIL")
    fails(f"{role} probe not run (another holder kept the lock)",
          answers={role: (3, "\nKUBECON PROBE NOT RUN: another holder kept the cluster's guard lock\n")},
          probes_run=True, mentions="printed no beat results")
    rc, out = green_out(role)
    fails(f"{role} probe exits non-zero though it printed green", answers={role: (1, out)}, probes_run=True,
          mentions="exited 1")
    fails(f"{role} probe output cut off before its verdict",
          answers={role: (124, out.split("\n\n")[0])}, probes_run=True, mentions="not KUBECON PROBE GREEN")

# --- the end state ----------------------------------------------------------------------------------------------------
fails("the floor off after the probes", set_("controls.always_on.code_of_conduct", False, "private", when="end"),
      probes_run=True, mentions="at the end: the code-of-conduct floor is on")
fails("a guardrail left on after the probes", set_("measure.networkpolicy", True, "community", when="end"),
      probes_run=True, mentions="at the end: every guardrail is off")

# --- the contexts --------------------------------------------------------------------------------------------------


def swap(private: FakeCluster, community: FakeCluster) -> None:
    private._host, community._host = community._host, private._host


fails("the two contexts swapped", swap, probes_run=False, mentions="is the private admin cluster")

# --- the parts read off the probe and the floor ------------------------------------------------------------------------
check("the admin run's beats are kubecon_probe.ADMIN with guardrails-all-off",
      [b.key for b in live.expected_beats("admin")] == [b.key for b in kp.ADMIN] + ["guardrails-all-off"])
check("the community run's beats are kubecon_probe.COMMUNITY with guardrails-kates-off",
      [b.key for b in live.expected_beats("community")] == [b.key for b in kp.COMMUNITY] + ["guardrails-kates-off"])
cfg = "service:\n  pipelines:\n    traces:\n      processors: [batch, transform/coc_mask]\n"
check("a collector config with transform/coc_mask in a pipeline reads as masking",
      live.collector_masks([{"data": {"relay": cfg}}]))
check("one that only defines the processor does not",
      not live.collector_masks([{"data": {"relay": "processors:\n  transform/coc_mask: {}\nservice:\n  pipelines:\n"
                                          "    traces:\n      processors: [batch]\n"}}]))
src = (REPO / "gitops/ai-layer/workshop-mcp-server.py").read_text()
check("the repo's workshop-mcp-server.py reads as carrying deploy_app's check", live.deploy_checks(src))
check("one with _refuse_coc defined and never called does not",
      not live.deploy_checks("def _refuse_coc(*texts):\n    pass\n"))
values = (REPO / "gitops/otel-collector/values.yaml").read_text()
check("the collector values the clusters render run transform/coc_mask in a pipeline (the layer the live read wants)",
      re.search(r"^\s*- transform/coc_mask\b", values, re.M) is not None)
policy = (REPO / "gitops/namespaces/code-of-conduct-names.yaml").read_text()
check("the admission policy's binding is named code-of-conduct-names, the name the live read gets",
      re.search(r"kind: ValidatingAdmissionPolicyBinding\nmetadata:\n  name: code-of-conduct-names\n", policy) is not None)
check("the floor's guard-proxy events are picked out of its JSON log",
      live.floor_events(['{"timestamp": "t1", "event": "conduct_refused"}', '{"event": "guard_toggle"}', "not json",
                         '{"timestamp": "t2", "event": "conduct_masked"}']) == ["t1 conduct_refused",
                                                                                "t2 conduct_masked"])

# --- the live test runs where it should --------------------------------------------------------------------------------
head = (HERE / "test_coc_floor_probes_live.py").read_text().splitlines()[:4]
check("the live test is in run-e2e.sh's suite (`# SUITE: e2e`)", "# SUITE: e2e" in head, str(head))
check("and not in the cluster-free tier (no `# E2E TIER` line)", not any(ln.startswith("# E2E TIER") for ln in head))
e2e = (HERE / "run-e2e.sh").read_text()
check("run-e2e.sh requires both contexts the live test reads",
      'missing+=("COMMUNITY_CONTEXT is not set' in e2e and 'missing+=("PRIVATE_CONTEXT is not set' in e2e)
check("run-e2e.sh names the live test", "test_coc_floor_probes_live.py" in e2e)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All offline checks of the floor-on probe test passed.")
