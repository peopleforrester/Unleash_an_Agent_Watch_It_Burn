# ABOUTME: Offline checks for verify/stage_switch_check.py (#1182): each switch's PASS, a FAIL on one cluster only, a
# ABOUTME: missing field naming #1132, unreadable reads, the start state, and the field names held to guard-proxy's.
"""Holds the stage-switch judge to its contract on recorded /controls reads, with no cluster.

START is the shape both KubeCon clusters' /controls answered on 2026-11-08 (run 18703, a plain GET of each): every
switch's field off, Falco on only on the private cluster, and no agency_scoped, since the pinned guard-proxy does not
send it yet.
"""
from __future__ import annotations

import copy
import inspect
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import kubecon_probe as kp  # noqa: E402
import stage_switch_check as ssc  # noqa: E402

PROXY = REPO / "gitops/ai-layer/guard-proxy/proxy.py"

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _read(host: str, falco: bool) -> dict:
    return {"ai": {"input_blocklist": False, "input_classifier": False, "output": False, "budget": False,
                   "topic": False},
            "infra": {"networkpolicy": False, "kyverno": False, "kubearmor": False, "falco": falco,
                      "tool_allowlist": False, "rbac_scoped": False},
            "host": host}


START = {"private": _read("burritobot-private.agenticburn.com", True),
         "community": _read("attackme.agenticburn.com", False)}


def with_agency(reads: dict, value=False) -> dict:
    """The same reads once the repinned guard-proxy sends agency_scoped."""
    out = copy.deepcopy(reads)
    for r in out.values():
        r["infra"]["agency_scoped"] = value
    return out


def switched(reads: dict, switch: str, clusters=("private", "community")) -> dict:
    """The reads with every field `switch` owns turned on, on the named clusters."""
    out = copy.deepcopy(reads)
    for c in clusters:
        for section, key in ssc.SWITCHES[switch]:
            out[c][section][key] = True
    return out


def results(verdicts: dict) -> dict:
    return {c: v.result for c, v in verdicts.items()}


BOTH_PASS = {"private": ssc.PASS, "community": ssc.PASS}

# --- the switches and their fields, held to guard-proxy and the probe --------------------------------------------

check(list(ssc.SWITCHES) == ["guardrails-on", "guard-agency-on", "guard-input-on", "guard-mcp-on"],
      "the switches are the four stage switches, in talk order")
check(set(ssc.CLUSTERS.values()) == {"burritobot-private.burritobot.co", "attackme.burritobot.co"},
      "the two clusters are the private bot and the room's bot")
check(ssc.PASS == kp.PASS and ssc.FAIL == kp.FAIL and ssc.identity_name is kp.identity_name,
      "PASS, FAIL and identity_name are the probe's own, not copies")

proxy_src = PROXY.read_text(encoding="utf-8")
m = re.search(r"\ndef read_controls\(\):\n(.*?)\n(?=\S)", proxy_src, re.S)
if not m:
    sys.exit(f"{PROXY.relative_to(REPO)} has no top-level `def read_controls():`; the field check cannot run")
infra_sent = set(re.findall(r'out\["(\w+)"\]\s*=', m.group(1)))
g = re.search(r"\nGUARDS = \{\n(.*?)\n\}", proxy_src, re.S)
if not g:
    sys.exit(f"{PROXY.relative_to(REPO)} has no `GUARDS = {{` block; the field check cannot run")
ai_sent = set(re.findall(r'^\s*"(\w+)":', g.group(1), re.M))
check({"rbac_scoped", "kyverno", "kubearmor", "networkpolicy", "tool_allowlist"} <= infra_sent,
      f"the pinned read_controls sends the infra fields the guardrails and C7 badges read (sends {sorted(infra_sent)})")
check({"input_blocklist", "input_classifier"} <= ai_sent, f"the pinned GUARDS carries the input guards ({sorted(ai_sent)})")
for switch, fields in ssc.SWITCHES.items():
    for section, key in fields:
        sent = key in (infra_sent if section == "infra" else ai_sent)
        check(sent or (section, key) in ssc.WAITS_ON,
              f"{switch}'s {section}.{key} is sent by the pinned guard-proxy, or is named in WAITS_ON")
check(set(ssc.WAITS_ON) == {("infra", "agency_scoped")} and "#1132" in ssc.WAITS_ON[("infra", "agency_scoped")],
      "the only field waited on is agency_scoped, and it names #1132")
for key in ("input_blocklist", "input_classifier"):
    check(key in kp.AI_GUARDS, f"the probe's AI_GUARDS holds {key}")
badges_src = inspect.getsource(kp.judge_badges)
for key in ("networkpolicy", "kyverno", "kubearmor", "tool_allowlist", "rbac_scoped"):
    check(f'"{key}":' in badges_src, f"the probe's judge_badges reads infra.{key} too")

# --- PASS: every switch, on both clusters --------------------------------------------------------------------------

state = with_agency(START)
for switch in ssc.SWITCHES:
    after = switched(state, switch)
    v = ssc.judge_switch(switch, state, after)
    check(results(v) == BOTH_PASS, f"{switch} turning its fields on reaches both clusters: {v}")
    state = after  # cumulative, as the stage runs them

# the reads may arrive as JSON text or bytes, as the runner fetches them
before = with_agency(START)
after = switched(before, "guard-input-on")
v = ssc.judge_switch("guard-input-on", {c: json.dumps(r) for c, r in before.items()},
                     {c: json.dumps(r).encode() for c, r in after.items()})
check(results(v) == BOTH_PASS, f"a switch judged on JSON text and bytes passes the same: {v}")

# guardrails-on does not own agency_scoped, so it passes while /controls lacks it
v = ssc.judge_switch("guardrails-on", START, switched(START, "guardrails-on"))
check(results(v) == BOTH_PASS, f"guardrails-on passes on the reads of 2026-11-08, with no agency_scoped: {v}")

# --- FAIL on one cluster only -------------------------------------------------------------------------------------

after = switched(START, "guardrails-on")
after["community"]["infra"]["kubearmor"] = False
v = ssc.judge_switch("guardrails-on", START, after)
check(results(v) == {"private": ssc.PASS, "community": ssc.FAIL}, f"guardrails-on missing KubeArmor on the community "
      f"cluster fails there only: {v}")
check("infra.kubearmor" in v["community"].reason and "infra.kyverno" not in v["community"].reason,
      f"the community FAIL names infra.kubearmor and only it: {v['community'].reason!r}")

after = switched(with_agency(START), "guard-mcp-on", clusters=("private",))
v = ssc.judge_switch("guard-mcp-on", with_agency(START), after)
check(results(v) == {"private": ssc.PASS, "community": ssc.FAIL},
      f"guard-mcp-on that reached only the private cluster fails on the community one: {v}")
check("infra.tool_allowlist reads false after the switch" in v["community"].reason, v["community"].reason)

# half a switch is not the switch
after = switched(START, "guard-input-on")
after["private"]["ai"]["input_classifier"] = False
v = ssc.judge_switch("guard-input-on", START, after)
check(results(v) == {"private": ssc.FAIL, "community": ssc.PASS} and "ai.input_classifier" in v["private"].reason,
      f"guard-input-on with only the blocklist on fails on that cluster, naming the classifier: {v}")

# --- FAIL on a missing field: guard-agency-on until the repin, naming #1132 ----------------------------------------

v = ssc.judge_switch("guard-agency-on", START, START)
check(results(v) == {"private": ssc.FAIL, "community": ssc.FAIL}, f"guard-agency-on fails on both clusters while "
      f"/controls has no agency_scoped: {v}")
for c in ssc.CLUSTERS:
    check("#1132" in v[c].reason and "infra.agency_scoped" in v[c].reason,
          f"the {c} FAIL names infra.agency_scoped and #1132: {v[c].reason!r}")

# even a read that otherwise looks switched: the field is not there to read
after = copy.deepcopy(START)
after["private"]["infra"]["agency_scoped"] = True
before = copy.deepcopy(START)
before["private"]["infra"]["agency_scoped"] = False
v = ssc.judge_switch("guard-agency-on", before, after)
check(results(v) == {"private": ssc.PASS, "community": ssc.FAIL}, f"agency_scoped turned on where it is sent passes "
      f"there and fails where it is missing: {v}")
check("#1132" in v["community"].reason and "#1132" not in v["private"].reason, v["community"].reason)

# a field guard-proxy did send before, now gone: FAIL, but not blamed on #1132
after = switched(START, "guardrails-on")
del after["private"]["infra"]["kyverno"]
v = ssc.judge_switch("guardrails-on", START, after)
check(v["private"].result == ssc.FAIL and "does not carry infra.kyverno" in v["private"].reason
      and "#1132" not in v["private"].reason, f"a dropped field fails without naming #1132: {v['private'].reason!r}")

# --- not off before, or not on after ------------------------------------------------------------------------------

v = ssc.judge_switch("guard-mcp-on", switched(START, "guard-mcp-on"), switched(START, "guard-mcp-on"))
check(results(v) == {"private": ssc.FAIL, "community": ssc.FAIL} and "already on before" in v["private"].reason,
      f"a field already on before the switch is not shown turned on by it: {v}")

after = switched(START, "guard-mcp-on")
after["community"]["infra"]["tool_allowlist"] = None
v = ssc.judge_switch("guard-mcp-on", START, after)
check(v["community"].result == ssc.FAIL and "reads null after the switch" in v["community"].reason,
      f"a field guard-proxy could not measure (null) after the switch fails: {v['community'].reason!r}")

before = copy.deepcopy(START)
before["private"]["infra"]["tool_allowlist"] = None
v = ssc.judge_switch("guard-mcp-on", before, switched(START, "guard-mcp-on"))
check(v["private"].result == ssc.FAIL and "read null before the switch" in v["private"].reason,
      f"a field read null before the switch fails: {v['private'].reason!r}")

after = switched(START, "guard-mcp-on")
after["private"]["infra"]["tool_allowlist"] = "true"
v = ssc.judge_switch("guard-mcp-on", START, after)
check(v["private"].result == ssc.FAIL, f"only JSON true is on, not the string \"true\": {v['private'].reason!r}")

# --- an unreadable /controls --------------------------------------------------------------------------------------

UNREADABLE = {
    "no response": (None, "could not be read"),
    "an HTML error page": ("<html><body>502 Bad Gateway</body></html>", "not JSON"),
    "bytes not UTF-8": (b"\xff\xfe", "not UTF-8"),
    "a JSON list": ("[]", "not an object"),
    "no infra object": (json.dumps({"ai": {}}), "no infra object"),
    "infra not an object": ({"ai": {}, "infra": None}, "no infra object"),
}
for label, (raw, words) in UNREADABLE.items():
    after = switched(START, "guardrails-on")
    after["community"] = raw
    v = ssc.judge_switch("guardrails-on", START, after)
    check(results(v) == {"private": ssc.PASS, "community": ssc.FAIL} and words in v["community"].reason
          and "after the switch" in v["community"].reason,
          f"{label} after the switch fails that cluster only, saying why: {v['community'].reason!r}")
    before = copy.deepcopy(START)
    before["private"] = raw
    v = ssc.judge_switch("guardrails-on", before, switched(START, "guardrails-on"))
    check(results(v) == {"private": ssc.FAIL, "community": ssc.PASS} and "before the switch" in v["private"].reason,
          f"{label} before the switch fails that cluster: {v['private'].reason!r}")
    reads = copy.deepcopy(with_agency(START))
    reads["private"] = raw
    v = ssc.judge_start_state(reads)
    check(results(v) == {"private": ssc.FAIL, "community": ssc.PASS} and words in v["private"].reason,
          f"{label} at the start-state check fails that cluster: {v['private'].reason!r}")

v = ssc.judge_switch("guardrails-on", {"private": START["private"]}, switched(START, "guardrails-on"))
check(results(v) == {"private": ssc.PASS, "community": ssc.FAIL}, f"a cluster with no read at all fails: {v}")

# a read filed under the wrong cluster
after = switched(START, "guardrails-on")
after["private"], after["community"] = after["community"], after["private"]
v = ssc.judge_switch("guardrails-on", START, after)
check(results(v) == {"private": ssc.FAIL, "community": ssc.FAIL} and "answers as" in v["private"].reason,
      f"swapped reads fail on both clusters, naming who answered: {v}")
# the burritobot.co name and an empty host are the cluster's own (guard-proxy sends WIB_PUBLIC_HOST, maybe "")
for host in ("burritobot-private.burritobot.co", ""):
    after = switched(START, "guardrails-on")
    after["private"]["host"] = host
    v = ssc.judge_switch("guardrails-on", START, after)
    check(v["private"].result == ssc.PASS, f"host {host!r} is read as the private cluster: {v['private']}")

try:
    ssc.judge_switch("guards-on", START, START)
    check(False, "an unknown switch name raises")
except ValueError as e:
    check("guards-on" in str(e), f"an unknown switch name raises, naming it: {e}")

# --- the start state ----------------------------------------------------------------------------------------------

v = ssc.judge_start_state(with_agency(START))
check(results(v) == BOTH_PASS, f"every switch's field off is the start state on both clusters, Falco on or off: {v}")

v = ssc.judge_start_state(START)
check(results(v) == {"private": ssc.FAIL, "community": ssc.FAIL}, f"the start state cannot be confirmed while "
      f"/controls has no agency_scoped: {v}")
for c in ssc.CLUSTERS:
    check("infra.agency_scoped" in v[c].reason and "#1132" in v[c].reason and "cannot be read as off" in v[c].reason,
          f"the {c} start-state FAIL names agency_scoped and #1132: {v[c].reason!r}")

# guards-off ran but guardrails-off did not reach the community cluster
reads = with_agency(START)
reads["community"]["infra"].update(kyverno=True, networkpolicy=True)
v = ssc.judge_start_state(reads)
check(results(v) == {"private": ssc.PASS, "community": ssc.FAIL}, f"guardrails left on the community cluster fail "
      f"there only: {v}")
check("infra.kyverno reads true" in v["community"].reason and "infra.networkpolicy reads true" in v["community"].reason
      and "kubearmor" not in v["community"].reason,
      f"the FAIL names each field still on, and only those: {v['community'].reason!r}")

# every field every switch owns is judged
for switch, fields in ssc.SWITCHES.items():
    for section, key in fields:
        reads = with_agency(START)
        reads["private"][section][key] = True
        v = ssc.judge_start_state(reads)
        check(v["private"].result == ssc.FAIL and f"{section}.{key} reads true" in v["private"].reason
              and switch in v["private"].reason, f"{section}.{key} left on fails the start state, naming {switch}")
        reads["private"][section][key] = None
        v = ssc.judge_start_state(reads)
        check(v["private"].result == ssc.FAIL and f"{section}.{key} reads null" in v["private"].reason,
              f"{section}.{key} unreadable (null) fails the start state")

# Falco and the guards that are not stage switches are outside it
reads = with_agency(START)
reads["community"]["infra"]["falco"] = True
reads["private"]["infra"]["falco"] = False
reads["private"]["ai"]["topic"] = True
check(results(ssc.judge_start_state(reads)) == BOTH_PASS, "Falco and the topic guard do not decide the start state")

if failures:
    print(f"\n{len(failures)} stage-switch check(s) FAILED")
    sys.exit(1)
print("\nALL STAGE-SWITCH CHECKS PASS")
