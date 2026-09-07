# ABOUTME: The Collector refuses its whole config and CrashLoops if one OTTL statement parses as a YAML
# ABOUTME: map instead of a string, so every statement is asserted to be a string before it ships.
"""Guards the Collector config against the failure that takes the whole pipeline down.

An OTTL statement is plain text, but YAML does not know that. A statement containing `": true"` outside
quotes parses as a mapping, and the Collector then rejects the ENTIRE configuration:

    'processors' error reading configuration for "transform/adk_tool_content": decoding failed
    'trace_statements[0].statements[2]' expected type 'string', got unconvertible type 'map[string]interface {}'

Not the one processor. All of it. The DaemonSet CrashLoops and every cluster on that config stops shipping
telemetry, which for this workshop means every trace, every badge and every challenge's evidence. Caught on
michael-admin, 2026-09-07, by restarting the collector rather than trusting that valid YAML meant a valid
config; the fix is to single-quote the scalar, which the filter rules in the same file already do.

The check is cheap and the failure is total, so it runs offline on every build.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
VALUES = REPO / "gitops/otel-collector/values.yaml"
CFG = (yaml.safe_load(VALUES.read_text(encoding="utf-8")) or {}).get("config", {})

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== every OTTL statement is a string, in every processor ==")
seen = 0
for pname, pcfg in sorted((CFG.get("processors") or {}).items()):
    if not isinstance(pcfg, dict):
        continue
    for key in ("trace_statements", "metric_statements", "log_statements"):
        for i, group in enumerate(pcfg.get(key) or []):
            # A group is either {context, statements} or, in the older form, a bare statement string.
            stmts = group.get("statements", []) if isinstance(group, dict) else [group]
            for j, s in enumerate(stmts):
                seen += 1
                if not isinstance(s, str):
                    check(f"{pname}.{key}[{i}].statements[{j}] is a string, not a {type(s).__name__}", False)
check(f"all {seen} OTTL statements parse as strings", not failures)

print("== filter conditions too, which have the same shape and the same trap ==")
fseen = 0
for pname, pcfg in sorted((CFG.get("processors") or {}).items()):
    if not isinstance(pcfg, dict) or not pname.startswith("filter"):
        continue
    for sig in ("traces", "metrics", "logs"):
        block = pcfg.get(sig) or {}
        for key in ("span", "spanevent", "metric", "datapoint", "log_record"):
            for k, cond in enumerate(block.get(key) or []):
                fseen += 1
                if not isinstance(cond, str):
                    check(f"{pname}.{sig}.{key}[{k}] is a string, not a {type(cond).__name__}", False)
check(f"all {fseen} filter conditions parse as strings", len(failures) == 0)

print("== the pipeline runs the processors that exist, and only those ==")
# A processor named in a pipeline but absent from `processors` is also a whole-config rejection, and it is
# the easy half of the same mistake: renaming a transform and missing one of its two mentions.
declared = set((CFG.get("processors") or {}).keys())
for pipe, pcfg in sorted(((CFG.get("service") or {}).get("pipelines") or {}).items()):
    for used in pcfg.get("processors") or []:
        check(f"{pipe} references a declared processor: {used}", used in declared)

print("== the transforms this workshop depends on are wired in, not just defined ==")
traces = ((CFG.get("service") or {}).get("pipelines") or {}).get("traces", {}).get("processors", [])
for needed in ("filter/drop_noise", "transform/mark_tool_failure", "transform/adk_tool_content"):
    check(f"{needed} is in the traces pipeline", needed in traces)
# Order matters: the ADK copy has to run after the noise filter, or it decorates spans that get dropped.
check("the ADK tool-content copy runs after the noise filter",
      traces.index("transform/adk_tool_content") > traces.index("filter/drop_noise"))

print("== the lab describes what the trace actually contains ==")
# Measured on watch-it-burn-michael-admin, 2026-09-07, after the transform went live:
#   execute_tool run_shell           STATUS_CODE_ERROR   args = the full curl, result = "command FAILED..."
#   execute_tool get_marketing_intel UNSET               result = the full customer data
# The lab used to promise "a tool call to agenticburn.com/beacon", which was not what the span showed.
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
check("the lab names the tool span a student should open", "execute_tool run_shell" in LAB)
check("it says the arguments carry the stolen payload",
      "arguments are the command the agent tried to run" in LAB)
check("it quotes the failure the tool actually returns",
      "most likely by a NetworkPolicy. Nothing was sent." in LAB)
check("it contrasts the blocked call with the successful one",
      "is not an error, and its result is the full customer data" in LAB)
check("it says why that contrast is the point",
      "could not tell a blocked exfiltration from a completed one" in LAB)
# The old promise named a URL the span does not carry as its own field.
check("the old inaccurate promise is gone",
      "the trace shows a tool call to <code class=\"inl\">agenticburn.com/beacon</code>" not in LAB)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All collector-config checks passed.")
