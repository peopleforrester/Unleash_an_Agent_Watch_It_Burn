# ABOUTME: The public cluster's collector scrubs attendee PII from trace content before any exporter runs (#647):
# ABOUTME: placement, the keys it reads, the four patterns, and what they do to attendee and demo text.
"""Pins #647's choice: the room's PII is scrubbed before spans leave attackme.

attackme's traces land in Whitney's sandbox org as burritobot-public. Its tab is projected, and anyone given a
view of it could read another attendee's prompt. The burn collector (values-burn.yaml) ends its traces pipeline
with transform/scrub_pii, which rewrites e-mail addresses, card numbers, US social security numbers and phone
numbers in the conversation's attributes and in every span-event attribute. This holds:

  - the scrub is the last traces processor on burn, with and without datadog-secret, after
    transform/adk_tool_content, so the gen_ai.* copies of the tool content are scrubbed with their sources;
  - it reads every content key: the gen_ai messages, and both halves of every copy adk_tool_content makes;
  - it never touches the other span attributes (session.id and the other ids stay whole);
  - the attendee and instructor collectors carry no scrub, because C1's fake customer records are meant to show
    in a student's own trace;
  - the four patterns are RE2-safe, written once per context, and do to attendee and demo text what
    pii_scrub_cases.py says. test_collector_pii_scrub_e2e.py runs the same cases through the real collector.

Offline: reads the collector value files and gitops/ai-layer/resources.yaml.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collector_render import REPO, collector_config  # noqa: E402
from pii_scrub_cases import (ATTENDEE, ATTENDEE_SCRUBBED, RAW_VALUES, SCRUB, UNTOUCHED, burn_scrub,  # noqa: E402
                             c5_record, patterns, unquote)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== burn's traces pipeline ends with the scrub, before any exporter ==")
for secret in (False, True):
    cfg = collector_config("burn", datadog_secret=secret)
    procs = cfg["service"]["pipelines"]["traces"]["processors"]
    label = "with datadog-secret" if secret else "without datadog-secret"
    check(f"burn {label}: {SCRUB} is defined", SCRUB in cfg.get("processors", {}))
    check(f"burn {label}: {SCRUB} is the last traces processor {procs}", procs[-1:] == [SCRUB])
    check(f"burn {label}: it runs after transform/adk_tool_content",
          {"transform/adk_tool_content", SCRUB} <= set(procs) and procs.index("transform/adk_tool_content") < procs.index(SCRUB))
    check(f"burn {label}: the lab pipeline is untouched (its contract keeps no content)",
          SCRUB not in cfg["service"]["pipelines"]["traces/lab"]["processors"])

print("== only the public cluster scrubs ==")
for profile in ("instructor", "attendee"):
    for secret in (False, True):
        cfg = collector_config(profile, datadog_secret=secret)
        check(f"{profile} {'with' if secret else 'without'} datadog-secret has no {SCRUB}",
              SCRUB not in cfg.get("processors", {})
              and all(SCRUB not in (p.get("processors") or []) for p in cfg["service"]["pipelines"].values()))

scrub = burn_scrub()
groups = {g["context"]: g["statements"] for g in scrub["trace_statements"]}
span, event = groups.get("span", []), groups.get("spanevent", [])
print("== the processor's shape ==")
check(f"two statement groups, span and spanevent ({sorted(groups)})", sorted(groups) == ["span", "spanevent"])
check("error_mode is ignore, so a statement that cannot run never drops a span", scrub.get("error_mode") == "ignore")
check("every statement is a string (an unquoted one can parse as a YAML map and fail the whole config)",
      all(isinstance(s, str) for s in span + event))
check("the span group copies the attributes into cache first",
      span[:1] == ['set(cache["pii"], attributes)'], str(span[:1]))
check("and merges the scrubbed copy back last", span[-1:] == ['merge_maps(attributes, cache["pii"], "upsert")'])
keep = next((s for s in span if s.startswith('keep_keys(cache["pii"], ')), "")
keys = re.findall(r'"([^"]+)"', keep.partition(", ")[2])
check("the span group keeps only the content keys before scrubbing", span[1:2] == [keep] and bool(keys), keep)
check("no statement in the span group writes attributes other than the merge",
      all("attributes" not in s for s in span[1:-1]))

print("== the content keys: the gen_ai messages and both halves of every adk_tool_content copy ==")
values = yaml.safe_load((REPO / "gitops/otel-collector/values.yaml").read_text(encoding="utf-8"))
adk = [s for g in values["config"]["processors"]["transform/adk_tool_content"]["trace_statements"]
       for s in g["statements"]]
copies = [m.groups() for m in (re.match(r'^set\(attributes\["([^"]+)"\], attributes\["([^"]+)"\]\)', s)
                               for s in adk) if m]
check(f"adk_tool_content still copies tool content ({len(copies)} copies)", len(copies) >= 2)
want = {"gen_ai.input.messages", "gen_ai.output.messages", "gcp.vertex.agent.llm_request",
        "gcp.vertex.agent.llm_response"} | {k for pair in copies for k in pair}
check(f"keep_keys names every content key {sorted(want - set(keys))} missing", want <= set(keys))
check("keep_keys names no id or session key", not any(k.endswith(".id") or "session" in k for k in keys), str(keys))

print("== the patterns: the same four, in the same order, in both contexts ==")
sp, ev = patterns(span), patterns(event)
check("the span group scrubs cache[\"pii\"] and the event group its attributes",
      {t for t, _, _ in sp} == {'cache["pii"]'} and {t for t, _, _ in ev} == {"attributes"})
check(f"labels in order {[lab for _, _, lab in sp]}",
      [lab for _, _, lab in sp] == ["[EMAIL]", "[CARD]", "[SSN]", "[PHONE]"])
check("the two contexts carry identical patterns", [(p, lab) for _, p, lab in sp] == [(p, lab) for _, p, lab in ev])
check("every statement between the copy and the merge is a scrub", len(sp) == len(span) - 3)
check("the event group is nothing but scrubs", len(ev) == len(event))
for _, p, lab in sp:
    check(f"{lab}: no lookaround or backreference (RE2 has neither)",
          not re.search(r"\(\?<?[=!]|\\[1-9]", unquote(p)), p)
    check(f"{lab}: every backslash is doubled for the OTTL string literal",
          all(len(run) % 2 == 0 for run in re.findall(r"\\+", p)), p)
    check(f"{lab}: no $ (the collector would read it as a config variable)", "$" not in p)


def scrub_text(text: str) -> str:
    for _, p, lab in sp:
        text = re.sub(unquote(p), lab, text, flags=re.ASCII)
    return text


print("== what the patterns do (Python's re in ASCII mode; the E2E half runs the collector) ==")
got = scrub_text(ATTENDEE)
check("the attendee prompt comes out as pii_scrub_cases.ATTENDEE_SCRUBBED", got == ATTENDEE_SCRUBBED, got)
check("no raw value survives", not any(v in got for v in RAW_VALUES), got)
check("the name is not caught, as the decision records", "Jo Example" in got)
record = c5_record()
check("C5's record, a street address the trace is meant to keep, is unchanged", scrub_text(record) == record)
for text in UNTOUCHED:
    check(f"unchanged: {text[:60]}...", scrub_text(text) == text, scrub_text(text))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All collector PII scrub checks passed.")
