# ABOUTME: Every profile's collector maps the Go runtime's model request and response to gen_ai.*.messages (#721):
# ABOUTME: transform/adk_llm_content in the traces pipeline, before burn's scrub, and the lambda gate it cannot run without.
"""Pins the placement of transform/adk_llm_content (#721), offline.

The processor is what gives a generate_content row in LLM Observability its input and output on kagent's Go
runtime. verify/test_adk_llm_content_e2e.py runs it through the pinned collector; this holds, without the binary:

  - it is in every profile's traces pipeline, with and without datadog-secret, after transform/adk_tool_content;
  - on burn it runs before transform/scrub_pii, so the derived messages are scrubbed like the rest of the conversation;
  - its statements use OTTL lambdas, so every profile's collector runs with --feature-gates=ottl.functions.enableLambda.
    Without the gate the collector refuses the whole config and the pod never starts; the gate is in values.yaml's
    command.extraArgs, which no overlay restates (Helm replaces lists, so an overlay that did would drop it);
  - it writes only gen_ai.input.messages and gen_ai.output.messages, each only where the span has none of its own.

Offline: reads the collector value files through collector_render.py.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collector_render import PROFILE_APP, REPO, collector_config, feature_gate_args, value_files  # noqa: E402

NAME = "transform/adk_llm_content"
GATE = "--feature-gates=ottl.functions.enableLambda"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== in every profile's traces pipeline, after the tool content and before burn's scrub ==")
for profile in PROFILE_APP:
    for secret in (False, True):
        cfg = collector_config(profile, datadog_secret=secret)
        procs = cfg["service"]["pipelines"]["traces"]["processors"]
        label = f"{profile} {'with' if secret else 'without'} datadog-secret"
        check(f"{label}: {NAME} is defined and in the traces pipeline", NAME in cfg["processors"] and NAME in procs,
              str(procs))
        check(f"{label}: it runs after transform/adk_tool_content", "transform/adk_tool_content" in procs
              and NAME in procs and procs.index("transform/adk_tool_content") < procs.index(NAME), str(procs))
        if "transform/scrub_pii" in procs:
            check(f"{label}: it runs before transform/scrub_pii",
                  NAME in procs and procs.index(NAME) < procs.index("transform/scrub_pii"), str(procs))
check("burn's pipeline has the scrub this ordering is for",
      "transform/scrub_pii" in collector_config("burn", True)["service"]["pipelines"]["traces"]["processors"])

print("== the lambda feature gate, on every profile ==")
statements = [s for group in collector_config("instructor", True)["processors"][NAME]["trace_statements"]
              for s in group["statements"]]
check(f"{NAME}'s statements use lambdas (so the gate is needed at all)", any("=>" in s for s in statements))
for profile in PROFILE_APP:
    check(f"{profile}: the collector runs with {GATE}", GATE in feature_gate_args(profile),
          str(feature_gate_args(profile)))
    for f in value_files(PROFILE_APP[profile])[1:]:
        over = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        check(f"{profile}: {f.relative_to(REPO)} does not restate command.extraArgs (it would drop the gate)",
              "extraArgs" not in (over.get("command") or {}))

print("== what it writes, and where it holds back ==")
written = {s.split("], ", 1)[0].split('attributes["', 1)[1].rstrip('"]') for s in statements
           if s.startswith('set(attributes["')}
check("it writes only gen_ai.input.messages and gen_ai.output.messages",
      written == {"gen_ai.input.messages", "gen_ai.output.messages"}, str(written))
for key, source in (("gen_ai.input.messages", "gcp.vertex.agent.llm_request"),
                    ("gen_ai.output.messages", "gcp.vertex.agent.llm_response")):
    parse = [s for s in statements if s.startswith("set(cache[") and f'ParseJSON(attributes["{source}"])' in s]
    check(f"{source} is parsed only where the span has no {key} of its own",
          len(parse) == 1 and f'attributes["{key}"] == nil' in parse[0], str(parse))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All adk_llm_content checks passed.")
