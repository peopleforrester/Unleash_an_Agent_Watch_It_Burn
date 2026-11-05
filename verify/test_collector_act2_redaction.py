# ABOUTME: The re-leak trap's Act 2 overlay redacts the attributes the conversation is in since GenAI semconv v1.37,
# ABOUTME: the same keys the burn scrub covers, on spans and span events, and no profile runs it by default (#784).
"""gitops/otel-collector/otel-collector-act2-overlay.yaml is PRD #22's Act 2: the collector replaces the prompt with
[DEMO-REDACTED] before Datadog sees it. Until #784 it matched the gen_ai.content.prompt and gen_ai.content.completion
events, which semconv v1.37 dropped and nothing in the stack emits, so Act 2 redacted nothing. The content is in the
gen_ai.input.messages and gen_ai.output.messages attributes (guard-proxy writes them, transform/adk_model_content copies
them onto kagent's model calls) and in the tool call's attributes. This holds the overlay offline to:

  - redacting, in both the span and the span-event context, exactly the keys transform/scrub_pii in values-burn.yaml
    keeps for its scrub (#647), the two lists naming the conversation;
  - replacing, never deleting, each one only where it is present, the messages with a semconv-shaped envelope that
    still parses as JSON;
  - naming none of the dropped event names, and no processor in any other collector config under gitops/ naming
    them either (#949);
  - being wired into no value file, so every profile starts in Act 1.

verify/test_collector_act2_redaction_e2e.py runs it through the real collector.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
OVERLAY = REPO / "gitops/otel-collector/otel-collector-act2-overlay.yaml"
BURN = REPO / "gitops/otel-collector/values-burn.yaml"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


text = OVERLAY.read_text(encoding="utf-8")
docs = [d for d in yaml.safe_load_all(text) if d]
proc = (docs[0].get("processors") or {}).get("transform/redact_sentinel", {}) if docs else {}
check("the overlay defines transform/redact_sentinel", bool(proc))
check("with error_mode ignore, so a statement that fails never stops the traces pipeline",
      proc.get("error_mode") == "ignore")
groups = {g.get("context"): g.get("statements", []) for g in proc.get("trace_statements", [])}
check("it has a span group and a span-event group (Datadog's fallback event)",
      sorted(groups) == ["span", "spanevent"], str(sorted(groups)))

scrub = yaml.safe_load(BURN.read_text(encoding="utf-8"))["config"]["processors"]["transform/scrub_pii"]
keep = next(s for g in scrub["trace_statements"] if g["context"] == "span" for s in g["statements"]
            if s.startswith("keep_keys("))
conversation = re.findall(r'"([^"]+)"', keep.split(",", 1)[1])
check("the burn scrub's keep_keys list is readable (the conversation's keys)",
      "gen_ai.input.messages" in conversation and "gen_ai.output.messages" in conversation, keep)

STMT = re.compile(r'^set\(attributes\["([^"]+)"\], "((?:[^"\\]|\\.)*)"\) where attributes\["([^"]+)"\] != nil$')
for context, statements in sorted(groups.items()):
    print(f"== {context} ==")
    parsed = [STMT.match(s) for s in statements]
    check(f"{context}: every statement is set(attributes[k], literal) where attributes[k] != nil",
          statements and all(m and m.group(1) == m.group(3) for m in parsed),
          str([s for s, m in zip(statements, parsed) if not (m and m.group(1) == m.group(3))]))
    values = {m.group(1): m.group(2).replace('\\"', '"') for m in parsed if m}
    check(f"{context}: it redacts exactly the keys the burn scrub covers",
          sorted(values) == sorted(conversation), f"overlay {sorted(values)} vs scrub {sorted(conversation)}")
    check(f"{context}: and each one once", len(values) == len(statements))
    for key, role in (("gen_ai.input.messages", "user"), ("gen_ai.output.messages", "assistant")):
        try:
            msgs = json.loads(values.get(key, ""))
        except ValueError:
            msgs = None
        check(f"{context}: {key} becomes one {role} message whose text is [DEMO-REDACTED], still JSON",
              isinstance(msgs, list) and len(msgs) == 1 and msgs[0].get("role") == role
              and msgs[0].get("parts") == [{"type": "text", "content": "[DEMO-REDACTED]"}], values.get(key))
    others = {k: v for k, v in values.items() if not k.endswith(".messages")}
    check(f"{context}: every other key becomes the bare [DEMO-REDACTED]",
          others and set(others.values()) == {"[DEMO-REDACTED]"}, str(others))

body = "\n".join(s for st in groups.values() for s in st)
check("no statement names the event names semconv v1.37 dropped",
      "gen_ai.content.prompt" not in body and "gen_ai.content.completion" not in body)
check("no statement deletes a key (Datadog has to show that the redaction happened)",
      "delete_key" not in body and "delete_matching_keys" not in body)
check("BurritoBot's own system prompt and its tool definitions are left alone",
      "gen_ai.system_instructions" not in body and "gen_ai.tool.definitions" not in body)

print("== no collector config under gitops/ keys redaction on the dropped event names ==")
# A collector config is any YAML mapping under gitops/ with a `processors` map (the overlay at the top level, the
# chart's value files under `config:`). The guard-proxy submodule is its own repo and carries no collector config.
DROPPED = ("gen_ai.content.prompt", "gen_ai.content.completion")
SUBMODULE = REPO / "gitops/ai-layer/guard-proxy"


def processor_maps(node):
    if isinstance(node, dict):
        if isinstance(node.get("processors"), dict):
            yield node["processors"]
        for v in node.values():
            yield from processor_maps(v)
    elif isinstance(node, list):
        for v in node:
            yield from processor_maps(v)


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield str(k)
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


configs: dict[str, list] = {}
unparsed: list[str] = []
for p in sorted((REPO / "gitops").rglob("*.y*ml")):
    if SUBMODULE in p.parents:
        continue
    rel = str(p.relative_to(REPO))
    try:
        loaded = [d for d in yaml.safe_load_all(p.read_text(encoding="utf-8")) if d]
    except yaml.YAMLError:
        unparsed.append(rel)
        continue
    found = [m for d in loaded for m in processor_maps(d)]
    if found:
        configs[rel] = found
EXPECTED = {"gitops/otel-collector/values.yaml", "gitops/otel-collector/values-burn.yaml",
            "gitops/otel-collector/otel-collector-act2-overlay.yaml"}
check("the scan finds the chart's value files and the overlay as collector configs",
      EXPECTED <= set(configs), str(sorted(configs)))
not_config = [r for r in unparsed if re.search(r"^\s*processors:", (REPO / r).read_text(encoding="utf-8"), re.M)]
check("no YAML under gitops/ that does not parse (a Helm template) holds a processors map the scan would miss",
      not not_config, str(not_config))
for rel, maps in sorted(configs.items()):
    named = sorted({name for m in maps for s in strings(m) for name in DROPPED if name in s})
    check(f"{rel}: no processor names {' or '.join(DROPPED)}", not named, str(named))

wired = [str(p.relative_to(REPO)) for p in sorted((REPO / "gitops").rglob("*.yaml"))
         if p != OVERLAY and "redact_sentinel" in p.read_text(encoding="utf-8")]
check("no file under gitops/ wires it in, so every profile starts in Act 1", not wired, str(wired))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All Act 2 redaction overlay checks passed.")
