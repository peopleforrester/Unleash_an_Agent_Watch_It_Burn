# ABOUTME: Offline check of #1163: Agent Observability's copy sends every kagent span that can be a trace's root as
# ABOUTME: service burritobot, so a turn that skipped guard-proxy files under ml_app burritobot and not burritobot-agent.
"""Datadog sets a trace's ml_app from its root span's service.name (docs.datadoghq.com/llm_observability/
instrumentation/otel_instrumentation, read 2026-11-09), and Whitney's sandbox org has one ml_app, burritobot
(verify/test_datadog_sandbox_live.py check 4). A turn that came through guard-proxy has the guard's span, service
burritobot, as its root. A message/send sent to agentgateway or kagent directly has none, and kagent's invocation was
the root: 140 traces filed under ml_app burritobot-agent from 2026-11-01 to 2026-11-08, 139 rooted at invocation and
one at kagent's server span (decisions.md, #1163).

gitops/otel-collector/values.yaml now ends the traces/llmobs pipeline with three steps that move those spans to a
resource whose service.name is burritobot. This reads each profile's rendered config (collector_render.py, with and
without datadog-secret) and holds: the three steps are the copy's last, after filter/llmobs_one_root; the mark covers
invocation, kagent's server spans and any kagent span with no parent, and only kagent's; groupbyattrs lifts that one
attribute; the resource step makes it service.name and removes it; the name is the live check's ML_APP and the guard's
root service; and APM's pipeline has none of them, so APM keeps burritobot-agent. Each way of breaking a rule is fed to
the same judge and must fail. verify/test_trace_shape_e2e.py runs the turns through the real collector.
"""
from __future__ import annotations

import copy
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
from collector_render import collector_config  # noqa: E402

PROFILES = ("instructor", "attendee", "burn")
MARK, GROUP, RENAME = "transform/llmobs_root_mark", "groupbyattrs/llmobs_root", "transform/llmobs_root_service"
KEY = "witb.llmobs.root_service"
AGENT_NAMES = '"^(burritobot-agent|kagent)$"'

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def constant(path: str, name: str) -> str:
    text = (REPO / path).read_text(encoding="utf-8")
    m = re.search(rf'^{name} = "([^"]+)"$', text, re.M)
    if not m:
        print(f"FAIL: {path} has no line `{name} = \"...\"`, the anchor this test reads")
        sys.exit(1)
    return m.group(1)


ML_APP = constant("verify/test_datadog_sandbox_live.py", "ML_APP")
ROOT_SERVICE = constant("verify/test_service_naming.py", "ROOT_SERVICE")


def statements(proc: dict, context: str) -> list[str]:
    return [s for block in proc.get("trace_statements", []) if block.get("context") == context
            for s in block.get("statements", [])]


def judge(conf: dict) -> list[str]:
    """What is wrong with one rendered collector config, as a list of reasons (empty when it holds)."""
    bad: list[str] = []
    procs, pipes = conf.get("processors", {}), conf.get("service", {}).get("pipelines", {})
    lp = pipes.get("traces/llmobs", {}).get("processors", [])
    if lp[-3:] != [MARK, GROUP, RENAME]:
        bad.append(f"traces/llmobs does not end with {MARK}, {GROUP}, {RENAME}: {lp}")
    elif "filter/llmobs_one_root" not in lp or lp.index("filter/llmobs_one_root") > lp.index(MARK):
        bad.append("the mark does not run after filter/llmobs_one_root, whose rules match kagent by its own name")
    mark = statements(procs.get(MARK, {}), "span")
    want = (f'set(attributes["{KEY}"], "{ML_APP}") where IsMatch(resource.attributes["service.name"], {AGENT_NAMES}) '
            'and (name == "invocation" or kind == SPAN_KIND_SERVER or IsRootSpan())')
    if mark != [want]:
        bad.append(f"{MARK} is not the one rule naming {ML_APP} on kagent's invocation, server and parentless spans: "
                   f"{mark}")
    if procs.get(GROUP, {}).get("keys") != [KEY]:
        bad.append(f"{GROUP} does not lift exactly {KEY}: {procs.get(GROUP)}")
    rename = statements(procs.get(RENAME, {}), "resource")
    if rename != [f'set(attributes["service.name"], attributes["{KEY}"]) where attributes["{KEY}"] != nil',
                  f'delete_key(attributes, "{KEY}")']:
        bad.append(f"{RENAME} does not make {KEY} the service.name and then remove it: {rename}")
    if statements(procs.get(RENAME, {}), "span"):
        bad.append(f"{RENAME} has span statements; service.name is the resource's")
    for name, pipe in pipes.items():
        if name != "traces/llmobs" and {MARK, GROUP, RENAME} & set(pipe.get("processors", [])):
            bad.append(f"{name} runs the copy's renaming, so its spans lose burritobot-agent")
    return bad


print(f"== the name: ML_APP {ML_APP!r} (test_datadog_sandbox_live.py), the guard's root {ROOT_SERVICE!r} ==")
check("the ml_app the live check wants is the guard's root service, the one Datadog names a guard turn after",
      ML_APP == ROOT_SERVICE == "burritobot")
kagent_map = (REPO / "gitops/otel-collector/values.yaml").read_text(encoding="utf-8")
check("the mark matches kagent under the name transform/kagent_service_name gives it, burritobot-agent",
      "'set(attributes[\"service.name\"], \"burritobot-agent\") where attributes[\"service.name\"] == \"workshop_agent\"'"
      in kagent_map)

confs = {}
for profile in PROFILES:
    for secret in (True, False):
        label = f"{profile}, {'with' if secret else 'without'} datadog-secret"
        conf = collector_config(profile, datadog_secret=secret)
        confs[label] = conf
        print(f"== {label} ==")
        bad = judge(conf)
        check(f"{label}: the copy's possible roots go out as service {ML_APP}, and only in the copy", not bad,
              "; ".join(bad))
        check(f"{label}: APM's traces pipeline ships no renamed span (it runs none of the three)",
              not {MARK, GROUP, RENAME} & set(conf["service"]["pipelines"]["traces"]["processors"]))

print("== each way of breaking it fails the judge ==")
base = confs["instructor, with datadog-secret"]


def broken(name: str, change) -> None:
    conf = copy.deepcopy(base)
    change(conf)
    check(f"fails: {name}", bool(judge(conf)))


def set_mark(conf: dict, rule: str) -> None:
    conf["processors"][MARK]["trace_statements"][0]["statements"] = [rule]


def lp(conf: dict) -> list[str]:
    return conf["service"]["pipelines"]["traces/llmobs"]["processors"]


RULE = statements(base["processors"][MARK], "span")[0]
broken("the three steps left out of traces/llmobs", lambda c: lp(c).__delitem__(slice(-3, None)))
broken("the steps in another order", lambda c: lp(c).__setitem__(slice(-3, None), [GROUP, MARK, RENAME]))
broken("the mark before filter/llmobs_one_root",
       lambda c: (lp(c).remove("filter/llmobs_one_root"), lp(c).append("filter/llmobs_one_root")))
broken("the mark naming burritobot-agent", lambda c: set_mark(c, RULE.replace(f'"{ML_APP}") where', '"burritobot-agent") where')))
broken("the mark missing invocation", lambda c: set_mark(c, RULE.replace('name == "invocation" or ', "")))
broken("the mark missing kagent's server spans", lambda c: set_mark(c, RULE.replace("kind == SPAN_KIND_SERVER or ", "")))
broken("the mark missing parentless spans", lambda c: set_mark(c, RULE.replace(" or IsRootSpan()", "")))
broken("the mark on every service's spans", lambda c: set_mark(c, RULE.replace(
    f'IsMatch(resource.attributes["service.name"], {AGENT_NAMES}) and ', "")))
broken("groupbyattrs lifting nothing", lambda c: c["processors"][GROUP].update(keys=[]))
broken("the resource step keeping the marker", lambda c: c["processors"][RENAME]["trace_statements"][0]["statements"].pop())
broken("the rename done on spans", lambda c: c["processors"][RENAME]["trace_statements"][0].update(context="span"))
broken("APM's pipeline renaming kagent too",
       lambda c: c["service"]["pipelines"]["traces"]["processors"].extend([MARK, GROUP, RENAME]))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All one-ml_app checks passed.")
