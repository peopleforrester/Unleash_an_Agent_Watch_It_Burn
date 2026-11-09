# ABOUTME: Every profile's collector masks the code of conduct's terms in the conversation before any exporter (#1277):
# ABOUTME: the rendered config's transform/coc_mask, its pattern equal to the #1267 spike's portable_pattern(), its place.
"""Pins #1277: the term list the #1267 spike chose is masked in trace content in the collector, on every profile,
whatever the guardrails are set to, so an expletive or slur typed into /chat never reaches Tempo or the Datadog
panels on the screen.

The collector config is rendered as each profile builds it (collector_render.py: the Application's value files, then
what the datadog-gate loads), with and without datadog-secret, and with one org and two on attendee. This holds:

  - transform/coc_mask is in the traces pipeline of every render, after transform/adk_model_content and
    transform/adk_tool_content (which copy the content to gen_ai.*), and last but for burn's transform/scrub_pii;
  - every other traces pipeline either receives only from a connector a masked pipeline exports to (traces/llmobs,
    through forward/llmobs) or keeps none of the eight keys (traces/lab's contract), so no exporter gets an unmasked
    copy;
  - its statements are exactly coc_mask_cases.statements(): the eight keys burn's scrub keeps, copied to the cache,
    masked twice, merged back, in the span and the span-event context;
  - the pattern, decoded from the config as the collector and OTTL read it, equals floor.portable_pattern();
  - applied with Python's re, it masks the term cases and leaves HC-666's ticket as it is.

test_collector_coc_mask_e2e.py runs the same cases through the real collector. Offline: reads the collector value
files, the bootstrap Applications, the spike's term list and gitops/ai-layer/ticket_site.py.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from coc_mask_cases import KEYS, MASK, decode, hc666_ticket, mask, pattern, statements, term_cases  # noqa: E402
from collector_render import REPO, collector_config  # noqa: E402

SCRUB = "transform/scrub_pii"
COPIERS = ("transform/adk_model_content", "transform/adk_tool_content")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail[:600]}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


RENDERS = [(p, s, a) for p in ("instructor", "attendee", "burn") for s in (False, True)
           for a in ((True, False) if p == "attendee" and s else (True,))]

print("== every profile: the mask is in the traces pipeline, after the content copies, before every exporter ==")
for profile, secret, admin in RENDERS:
    cfg = collector_config(profile, datadog_secret=secret, admin_secret=admin)
    label = f"{profile} {'with' if secret else 'without'} datadog-secret" + ("" if admin or not secret else ", one org")
    pipes = cfg["service"]["pipelines"]
    procs = pipes["traces"]["processors"]
    check(f"{label}: {MASK} is defined", MASK in cfg.get("processors", {}))
    check(f"{label}: {MASK} is a traces processor {procs}", MASK in procs)
    if MASK not in procs:
        continue
    check(f"{label}: after {', '.join(COPIERS)}",
          all(c in procs and procs.index(c) < procs.index(MASK) for c in COPIERS))
    after = procs[procs.index(MASK) + 1:]
    check(f"{label}: nothing but burn's scrub runs after it ({after})",
          after == ([SCRUB] if profile == "burn" else []))
    check(f"{label}: the traces pipeline exports somewhere", bool(pipes["traces"].get("exporters")))
    fed = set(pipes["traces"].get("exporters", []))  # connectors fed by the masked pipeline
    for name, pipe in pipes.items():
        if not name.startswith("traces") or name == "traces":
            continue
        receivers = set(pipe.get("receivers", []))
        if receivers <= fed:
            check(f"{label}: {name} receives only from the masked pipeline ({sorted(receivers)})", True)
            continue
        kept = [s for g in cfg["processors"].get("transform/lab_contract", {}).get("trace_statements", [])
                if g.get("context") == "span" for s in g["statements"] if s.startswith("keep_keys(attributes,")]
        check(f"{label}: {name} takes spans of its own, and its contract keeps none of the conversation keys",
              "transform/lab_contract" in pipe.get("processors", []) and len(kept) == 1
              and not any(f'"{k}"' in kept[0] for k in KEYS), f"{name}: {pipe}")

print("== the processor: the eight keys, cached, masked twice, merged back, on spans and span events ==")
proc = collector_config("instructor", datadog_secret=False)["processors"][MASK]
check("error_mode is ignore, so a statement that cannot run never drops a span", proc.get("error_mode") == "ignore")
groups = {g["context"]: g["statements"] for g in proc.get("trace_statements", [])}
check(f"a span and a span-event group ({sorted(groups)})", sorted(groups) == ["span", "spanevent"])
want = statements()
for context, got in sorted(groups.items()):
    check(f"{context}: every statement is a string", all(isinstance(s, str) for s in got))
    check(f"{context}: the statements are coc_mask_cases.statements() (rerun python3 verify/coc_mask_cases.py "
          "and paste its line after the term list changes)", got == want,
          next((f"statement {i}: {g[:200]}..." for i, (g, w) in enumerate(zip(got, want)) if g != w), str(len(got))))

burn = yaml.safe_load((REPO / "gitops/otel-collector/values-burn.yaml").read_text(encoding="utf-8"))
keep = next(s for g in burn["config"]["processors"][SCRUB]["trace_statements"] if g["context"] == "span"
            for s in g["statements"] if s.startswith("keep_keys("))
check("the keys are the eight burn's transform/scrub_pii keeps",
      sorted(re.findall(r'"([^"]+)"', keep.partition(", ")[2])) == sorted(KEYS), keep)

print("== the pattern is the spike's floor.portable_pattern(), as the collector reads it ==")
written = re.match(r'^replace_all_patterns\(cache\["coc"\], "value", "(.*)", "\$\$1\[redacted\]\$\$3"\)$',
                   groups.get("span", ["", "", ""])[2])
check("the replace statement has the shape the decoding reads", bool(written))
regex = decode(written.group(1)) if written else ""
check(f"decoded, it equals floor.portable_pattern() ({len(regex)} vs {len(pattern())} characters)",
      regex == pattern())
check("every $ in the config is doubled, so confmap reads none as a ${...} reference",
      written and all(len(run) % 2 == 0 for run in re.findall(r"\$+", written.group(1))))
check("no lookaround or backreference, which RE2 lacks", not re.search(r"\(\?<?[=!]|\\[1-9]", regex))
check("the replacement keeps both word edges ($1 and $3, written $$1 and $$3)", "$$1[redacted]$$3" in want[2])

print("== what it does, with Python's re (test_collector_coc_mask_e2e.py runs RE2 in the collector) ==")
for text, masked in term_cases():
    check(f"a {len(text)}-character text with a term comes out masked", mask(text) == masked)
# The attributes are JSON: guard-proxy writes them with json.dumps, whose \n and \uXXXX escapes sit right before a
# term on a line's start or after a curly quote, and kagent's Go marshaller keeps UTF-8 as it is. Both must mask.
lines = "\n".join(t for t, _ in term_cases())
lines_masked = "\n".join(m for _, m in term_cases())
check("the cases on lines of one prompt, JSON-encoded with escapes (guard-proxy), come out masked",
      mask(json.dumps(lines)) == json.dumps(lines_masked), mask(json.dumps(lines)))
check("and JSON-encoded as UTF-8 (kagent)",
      mask(json.dumps(lines, ensure_ascii=False)) == json.dumps(lines_masked, ensure_ascii=False))
check("HC-666's ticket JSON-encoded either way is unchanged",
      all(mask(json.dumps(ticket_text, ensure_ascii=a)) == json.dumps(ticket_text, ensure_ascii=a)
          for ticket_text in [hc666_ticket()] for a in (True, False)))
ticket = hc666_ticket()
check(f"HC-666's ticket ({len(ticket)} characters, its injection included) comes out unchanged", mask(ticket) == ticket)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All collector code-of-conduct mask checks passed.")
