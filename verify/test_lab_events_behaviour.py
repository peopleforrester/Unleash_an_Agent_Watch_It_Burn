# ABOUTME: Runs lab-events.js under node against a fake lab page (verify/lab-events-harness.js) and asserts what
# ABOUTME: it actually POSTs: valid OTLP/JSON, the documented events, and no text, e-mail or query string in it.
# SUITE: e2e (needs node: the page's own script is executed)
#
# The offline half (test_lab_events.py) proves the contract is written down the same way in five files. This half
# proves the script does what the contract says when a student clicks: a step, a hint, the "try this prompt"
# reveal, a command block whose text is a Datadog password, a Feedback link whose URL carries their e-mail.
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
HARNESS = REPO / "verify/lab-events-harness.js"
SRC = REPO / "gitops/ai-layer/web/lab-events.js"
CFG = yaml.safe_load((REPO / "gitops/otel-collector/values.yaml").read_text(encoding="utf-8"))["config"]
failures: list[str] = []


def check(n: str, c: bool) -> None:
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


if shutil.which("node") is None:
    print("node is not on PATH; this E2E check executes lab-events.js and cannot run without it", file=sys.stderr)
    sys.exit(1)


def run(*args: str) -> dict:
    out = subprocess.run(["node", str(HARNESS), str(SRC), *args], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        print(out.stderr, file=sys.stderr)
        sys.exit(1)
    return json.loads(out.stdout)


def value(v: dict):
    return next(iter(v.values()))


print("== a student's clicks become OTLP spans ==")
d = run()
posts = d["posts"]
check("it posted to /lab-events as JSON", posts and all(p["url"] == "/lab-events" and p["method"] == "POST"
                                                          and p["type"] == "application/json" for p in posts))
spans, resources = [], []
for p in posts:
    for rs in p["body"]["resourceSpans"]:
        resources.append({a["key"]: value(a["value"]) for a in rs["resource"]["attributes"]})
        for ss in rs["scopeSpans"]:
            spans.extend(ss["spans"])
check("the resource is burritobot-lab and nothing else", resources and all(r == {"service.name": "burritobot-lab"} for r in resources))
check("trace and span ids are OTLP/JSON hex (32 and 16)",
      all(len(s["traceId"]) == 32 and len(s["spanId"]) == 16 and int(s["traceId"], 16) and int(s["spanId"], 16) for s in spans))
check("timestamps are decimal nanosecond strings",
      all(isinstance(s["startTimeUnixNano"], str) and s["startTimeUnixNano"].isdigit() and len(s["startTimeUnixNano"]) == 19 for s in spans))
ev = [(s["name"], {a["key"]: value(a["value"]) for a in s["attributes"]}) for s in spans]
names = [n for n, _ in ev]


def has(name: str, attrs: dict) -> bool:
    return any(n == name and all(a.get(k) == v for k, v in attrs.items()) for n, a in ev)


check("the session start is first", names[:1] == ["lab.session.start"])
check("opening Challenge 1 is a step.open for challenge 1", has("lab.step.open", {"witb.lab.challenge": "1"}))
check("the steps without a number report their data-lab name", has("lab.step.open", {"witb.lab.challenge": "reset"}))
check("a hint is kind=hint, item 1", has("lab.hint.open", {"witb.lab.challenge": "1", "witb.lab.kind": "hint", "witb.lab.item": "1"}))
check("the 'try this prompt' reveal is kind=solution", has("lab.hint.open", {"witb.lab.kind": "solution", "witb.lab.item": "2"}))
check("a command block reports its position and target, terminal or chat",
      has("lab.command.send", {"witb.lab.item": "1", "witb.lab.kind": "terminal"})
      and has("lab.command.send", {"witb.lab.item": "2", "witb.lab.kind": "chat"}))
check("a Feedback click names the challenge on screen", has("lab.feedback.open", {"witb.lab.challenge": "3"}))
check("a fix measured ON by /controls is control.installed, mapped to its challenge",
      has("lab.control.installed", {"witb.lab.control": "networkpolicy", "witb.lab.challenge": "1"})
      and has("lab.control.installed", {"witb.lab.control": "budget", "witb.lab.challenge": "4"}))
check("a control measured OFF is not reported, and Falco (always on) never is",
      not has("lab.control.installed", {"witb.lab.control": "output"})
      and not has("lab.control.installed", {"witb.lab.control": "falco"}))
check("the heartbeat fires on its interval", "lab.heartbeat" in names)
check("every span carries the session, the friendly name and the role",
      all(a.get("witb.lab.alias") == "bane-agatha" and a.get("witb.lab.role") == "student" and len(a.get("session.id", "")) == 16
          for _, a in ev))

print("== nothing the student wrote, or who they are, is in it ==")
wire = json.dumps(posts)
check("not the command text (one block is a Datadog password)", "my-datadog-password" not in wire and "kubectl" not in wire)
check("not the e-mail or the query string from the Feedback link", "a%40b.c" not in wire and "a@b.c" not in wire and "user" not in wire)
keep = next(s for g in CFG["processors"]["transform/lab_contract"]["trace_statements"] if g["context"] == "span"
            for s in g["statements"] if s.startswith("keep_keys("))
sent = {k for _, a in ev for k in a}
check(f"every attribute it sends survives the collector's keep-list {sorted(sent)}", all(f'"{k}"' in keep for k in sent))

print("== the off switches ==")
o = run("optout")
check("Global Privacy Control: nothing is sent and nothing is scheduled", o["posts"] == [] and o["intervals"] == [])
p = d["pure"]
check("Do Not Track counts as opted out; no signal does not", p["dnt"] is True and p["plain"] is False)
check("a control already on at the first poll is reported installed", p["first"] == [{"name": "lab.control.installed", "control": "networkpolicy", "challenge": "1"}])
check("a control turned off is reported removed", p["removed"] == [{"name": "lab.control.removed", "control": "networkpolicy", "challenge": "1"}])
check("only a literal true counts as on", p["on"] == {"kubearmor": True, "budget": True})

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All lab-events behaviour checks passed.")
