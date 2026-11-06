# ABOUTME: Holds #954 offline: the recipe card BurritoBot's prompt names (#951) sits inside the directory both copies of
# ABOUTME: KubeArmor's block-recipe-snoop block, and the live check's judges (test_recipe_block_live.py) fail each way it can stop.
"""#951's rule sends the conversational attack to one file, and #954 holds that KubeArmor's block still covers it.

The git side, checked here on every run:
- the rule in gitops/workshop-agent/agent.yaml names exactly one card, under /tmp/burrito-data/config/legacy/;
- images/workshop-mcp/Dockerfile bakes that card, with the signature the C3 fallback and the live check read;
- both copies of block-recipe-snoop cover it with action Block on app=workshop-mcp in agent: the one Argo CD's
  kubearmor-policies app serves (policies/kubearmor/block-recipe-snoop.yaml) and the one guardrails-on applies
  (c3-kubearmor-policy.yaml in gitops/ai-layer/resources.yaml's challenge-fixes ConfigMap);
- app=workshop-mcp is a label of the workshop-mcp pod, in agent, so the selector reaches the pod run_shell runs in;
- the terminal's guardrails-on applies that challenge-fixes file for KubeArmor.

The live side is verify/test_recipe_block_live.py on the private cluster. Its judges and its run order are run here
against a fake cluster: one healthy, and one per way the block could stop covering the card, each of which must fail.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import test_recipe_block_live as live  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


LEGACY = "/tmp/burrito-data/config/legacy/"
AGENT_YAML = (REPO / "gitops/workshop-agent/agent.yaml").read_text(encoding="utf-8")
DOCKERFILE = (REPO / "images/workshop-mcp/Dockerfile").read_text(encoding="utf-8")
RESOURCES = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")) if d]
ENTRYPOINT = (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_text(encoding="utf-8")
FIXES = next(d for d in RESOURCES if d.get("kind") == "ConfigMap" and "c3-kubearmor-policy.yaml" in (d.get("data") or {}))
POLICIES = {
    "policies/kubearmor/block-recipe-snoop.yaml":
        yaml.safe_load((REPO / "policies/kubearmor/block-recipe-snoop.yaml").read_text(encoding="utf-8")),
    "challenge-fixes c3-kubearmor-policy.yaml (guardrails-on)": yaml.safe_load(FIXES["data"]["c3-kubearmor-policy.yaml"]),
}

print("== the card the rule names (#951) ==")
PATH = live.rule_path(AGENT_YAML)
check(f"the rule names one card, {PATH}, under {LEGACY}", PATH.startswith(LEGACY), PATH)
check("the Dockerfile bakes that card", f"cat > {PATH} <<" in DOCKERFILE)
check("with the signature the C3 fallback and the live check read", live.SIGNATURE in DOCKERFILE)
fallback = (REPO / "challenges/c3-secret-grep/fallback.kubectl.sh").read_text(encoding="utf-8")
check("the live check and the C3 fallback read the same signature", f'SIGNATURE="{live.SIGNATURE}"' in fallback)

print("== both copies of block-recipe-snoop cover it ==")
for name, pol in POLICIES.items():
    ok, note = live.judge_policy_covers(pol, PATH)
    check(f"{name}: {note}", ok, note)
    check(f"{name}: named {live.POLICY}", pol["metadata"]["name"] == live.POLICY)
check("the two copies carry the same spec", POLICIES["policies/kubearmor/block-recipe-snoop.yaml"]["spec"]
      == POLICIES["challenge-fixes c3-kubearmor-policy.yaml (guardrails-on)"]["spec"])
mcp = next(d for d in RESOURCES if d.get("kind") == "Deployment" and d["metadata"]["name"] == "workshop-mcp")
labels = mcp["spec"]["template"]["metadata"]["labels"]
check("app=workshop-mcp is a label of the workshop-mcp pod, the pod run_shell runs in", labels.get("app") == "workshop-mcp",
      str(labels))
check("and that pod is in agent, the policy's namespace", mcp["metadata"].get("namespace", "agent") == "agent")
check("guardrails-on applies the challenge-fixes copy for KubeArmor",
      'on:kubearmor)  c=("$@" apply -f "$HOME/challenges/c3-kubearmor-policy.yaml")' in ENTRYPOINT)

print("== covering_dirs: what covers a path and what does not ==")
pol = POLICIES["policies/kubearmor/block-recipe-snoop.yaml"]


def with_dirs(*dirs: dict, paths: tuple = ()) -> dict:
    p = copy.deepcopy(pol)
    p["spec"]["file"] = {"matchDirectories": list(dirs), **({"matchPaths": list(paths)} if paths else {})}
    return p


check("a recursive parent covers a card two folders down",
      live.covering_dirs(with_dirs({"dir": "/tmp/burrito-data/", "recursive": True}), PATH) == ["/tmp/burrito-data/"])
check("a non-recursive parent does not", not live.covering_dirs(with_dirs({"dir": "/tmp/burrito-data/"}), PATH))
check("a non-recursive dir covers its direct child", bool(live.covering_dirs(with_dirs({"dir": LEGACY}), PATH)))
check("a sibling with a shared prefix does not (/tmp/burrito-data/config/leg/)",
      not live.covering_dirs(with_dirs({"dir": "/tmp/burrito-data/config/leg", "recursive": True}), PATH))
check("a matchPaths entry equal to the card covers it",
      bool(live.covering_dirs(with_dirs(paths=({"path": PATH},)), PATH)))
check("a card moved out of legacy is not covered",
      not live.covering_dirs(pol, "/tmp/burrito-data/config/secret-sauce-recipe.conf"))
try:
    live.rule_path(AGENT_YAML.replace(PATH, f"{PATH} or /tmp/burrito-data/x.conf", 1))
    check("rule_path raises on two cards", False)
except ValueError:
    check("rule_path raises on two cards", True)
try:
    live.rule_path(AGENT_YAML.replace("The sauce recipe is kept on a recipe card", "The sauce", 1))
    check("rule_path names its anchor when the rule is reworded", False)
except ValueError as e:
    check("rule_path names its anchor when the rule is reworded", "The sauce recipe is kept on a recipe card" in str(e))

print("== the live check against fake clusters ==")
BLOCK_ALERT = json.dumps({"PolicyName": live.POLICY, "Action": "Block", "Operation": "File", "Resource": PATH,
                          "Result": "Permission denied", "PodName": "workshop-mcp-x"})
OFF = {"rbac_scoped": False, "kyverno_actions": ["Audit"], "breakout_actions": ["Audit"], "kubearmor_action": None,
       "networkpolicy": False}
ON = {"rbac_scoped": True, "kyverno_actions": ["Deny"], "breakout_actions": ["Deny"], "kubearmor_action": "Block",
      "networkpolicy": True}
FALLBACK_OK = "BLOCKED (prevention): ...\nDETECTED (KubeArmor alert): {...}\n"
T0 = dt.datetime(2026, 11, 6, 5, 0, tzinfo=dt.timezone.utc)


class Fake:
    """A cluster whose guardrails switch, and whose card reads open or blocked by the policy it holds."""

    def __init__(self, **over):
        self.armed = False
        self.switches: list[str] = []
        self.chats: list[str] = []
        self.o = {"prompt": live.git_system_message(), "start": OFF, "policy": pol, "covered": True, "alert": True,
                  "leak_reply": False, "switch_rc": 0, "found_armed": False, **over}
        if self.o["found_armed"]:
            self.armed = True

    def system_message(self):
        return self.o["prompt"]

    def measure(self):
        return ON if self.armed else self.o["start"]

    def cat(self, path):
        if self.armed and self.o["covered"]:
            return 1, f"cat: {path}: Permission denied\n"
        return 0, f"[recipe]\n{live.SIGNATURE}\n"

    def guardrails(self, state):
        self.switches.append(state)
        self.armed = state == "on"
        return self.o["switch_rc"], f"Both clusters, this one and peer: all four Kubernetes guardrails are {state}."

    def policy(self):
        return self.o["policy"] if self.armed else None

    def relay_since(self, since):
        return BLOCK_ALERT if self.armed and self.o["alert"] else ""

    def run_c3_fallback(self):
        return (0, FALLBACK_OK) if self.armed and self.o["covered"] else (1, "!! RECIPE LEAKED")

    def chat(self, prompt):
        self.chats.append(prompt)
        leak = self.o["leak_reply"] or not self.o["covered"]
        return {"reply": f"Here it is: {live.SIGNATURE}" if leak else "The pantry door is stuck, sugar."}

    def tool_calls_since(self, since):
        return [{"tool_name": "run_shell", "tool_input": {"command": f"cat {PATH}"}}]


def run(fake: Fake) -> list[str]:
    failed: list[str] = []
    live.run_checks(fake, lambda name, ok, detail="": failed.append(name) if not ok else None,
                    show=lambda _s: None, sleep=lambda _s: None, now=lambda: T0)
    return failed


healthy = Fake()
got = run(healthy)
check("a healthy cluster passes every check", not got, str(got))
check("it switched on, then off: left as found", healthy.switches == ["on", "off"], str(healthy.switches))
check("it asks #925's attack once, marked for the probe filter",
      len(healthy.chats) == 1 and live.ATTACK in healthy.chats[0] and "[[wib-probe]]" in healthy.chats[0])

uncovered = copy.deepcopy(pol)
uncovered["spec"]["file"]["matchDirectories"] = [{"dir": "/tmp/burrito-data/config/old/", "recursive": True}]
audit = copy.deepcopy(pol)
audit["spec"]["action"] = "Audit"
for why, fake, want in (
    ("a live prompt that is not git's", Fake(prompt="something else"), "the live systemMessage is git's"),
    ("a policy whose directory no longer holds the card", Fake(policy=uncovered, covered=False), "covers the card"),
    ("a policy at Audit", Fake(policy=audit, covered=False), "covers the card"),
    ("a read that is not denied", Fake(covered=False), "Permission denied"),
    ("no Block alert in the relay log", Fake(alert=False), "Block alert"),
    ("the recipe in the bot's reply", Fake(leak_reply=True), "conversational attack"),
    ("a switch that fails", Fake(switch_rc=1), "guardrails-on"),
):
    got = run(fake)
    check(f"{why} fails ({want})", any(want in g for g in got), str(got))
    if fake.switches:
        check(f"{why}: still switched back off", fake.switches[-1] == "off", str(fake.switches))
armed = Fake(found_armed=True)
got = run(armed)
check("a cluster found armed fails the start state and is not switched",
      any("start state" in g for g in got) and not armed.switches, f"{got} {armed.switches}")

print("== the alert parser ==")
check("a Block alert for the card is found behind a log prefix", len(live.block_alerts("relay: " + BLOCK_ALERT, PATH)) == 1)
check("an Audit alert is not a block", not live.block_alerts(BLOCK_ALERT.replace('"Block"', '"Audit"'), PATH))
check("another policy's alert is not this one", not live.block_alerts(BLOCK_ALERT.replace(live.POLICY, "other"), PATH))
check("an alert for another file is not the card's",
      not live.block_alerts(BLOCK_ALERT.replace(PATH, "/tmp/burrito-data/customers.json"), PATH))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The card #951's rule names is inside block-recipe-snoop's blocked directory, in both copies, and the live check "
      "fails each way that could stop holding.")
