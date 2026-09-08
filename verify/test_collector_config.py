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
import re
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
#
# WHAT THIS BLOCK USED TO PIN, AND WHY IT NO LONGER DOES. It required Challenge 1 to walk the student
# through the span by name: "execute_tool run_shell", the arguments carrying the stolen payload, the
# quoted "command FAILED..." result, and the contrast with get_marketing_intel. Whitney replaced that
# whole block on 2026-09-08 with a short instruction to find the trace and see that the POST to the
# beacon failed. Her edits are primary on this page, so what is pinned now is that the lab still sends
# the student to the trace and still tells them what outcome to look for. Do not restore the span
# walkthrough as a fix for a failure here.
#
# The collector side is unchanged and is still asserted above: mark_tool_failure is what puts the error
# status on that span, so the thing her sentence promises is still produced.
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
check("the lab sends the student to the trace after the fix",
      "See the block in the trace." in LAB)
check("it uses the standard trace instruction she settled on",
      "You should be able to see the model calls it made, the tools it used, and what each tool returned." in LAB)
check("it names the outcome to look for",
      "tried to POST to the Beacon endpoint but was unsuccessful" in LAB)
# The old promise named a URL the span does not carry as its own field.
check("the old inaccurate promise is gone",
      "the trace shows a tool call to <code class=\"inl\">agenticburn.com/beacon</code>" not in LAB)

print("== Kyverno reports arrive while the student is still looking (#323) ==")
# Challenge 2 asks a student to read the PolicyReport for a Pod they created seconds ago. The chart default
# scans hourly, so the report Whitney called a "broken command" was correct and up to an hour early.
#
# Measured on watch-it-burn-michael-admin, 2026-09-08, policy in Audit and the villain running:
#   at 1h default   no report for the pod after 2 minutes, while every older pod had one
#   at 30s          restrict-image-registries: validation error: Images must come from allowed registries...
KYV = (REPO / "gitops/apps/kyverno.yaml").read_text(encoding="utf-8")
check("the scan interval is set", "backgroundScanInterval: 30s" in KYV)
# The key path is the trap. reportsController.extraArgs is a real key, applies cleanly, syncs Healthy and
# does nothing, because the chart already emits the flag from its own value and the duplicate is ignored.
check("it is under the chart's own feature block",
      re.search(r"features:\s*\n\s+backgroundScan:\s*\n\s+backgroundScanInterval: 30s", KYV) is not None)
# Test the KEY, not the word. The comment above it names extraArgs precisely so nobody tries it again,
# and a check that cannot tell a YAML key from prose fails on its own documentation.
check("extraArgs is not used as a key",
      re.search(r"^\s*extraArgs:", KYV, re.M) is None)
check("the comment records how the wrong key failed", "duplicate flag is ignored" in KYV)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All collector-config checks passed.")
