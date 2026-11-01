# ABOUTME: What Agent Observability shows for one BurritoBot interaction (#746, #757): its rows from OTLP spans by Datadog's
# ABOUTME: documented conversion, or from the LLM Observability export API, and the judge for one root row with content.
"""#746's symptom was a BurritoBot interaction drawn as two root-level rows in LLM Observability, the root row reading
"No content". Its done-bar (Whitney's comment on #746, 2026-11-01) starts with the two halves of that: one chat is one
root row, and that row shows the prompt as input and the final reply as output. `problems` judges exactly that, on rows
from either source, so the offline check and the live one fail on the same thing.

`from_otlp` turns the spans the collector sends Datadog into the rows Datadog builds from them, by the rules on
docs.datadoghq.com/llm_observability/instrument/otel_instrumentation (read 2026-11-01, decisions.md #746):

  - a trace converts only when some span has gen_ai.operation.name, gen_ai.provider.name, openinference.span.kind,
    langfuse.observation.type or gen_ai.system;
  - an explicit dd_llmobs_enabled false on any span prevents conversion of the entire trace;
  - in a trace that converts, a span with no gen_ai.* attribute is dropped on its own;
  - parent_span_id becomes parent_id unchanged, so a span whose parent was dropped is a root;
  - the kind comes from gen_ai.operation.name: chat, generate_content, text_completion and completion are llm,
    execute_tool is tool, invoke_agent and create_agent are agent, anything else or none is workflow;
  - llm, agent and workflow rows take their input and output from gen_ai.input.messages and gen_ai.output.messages
    (gen_ai.system_instructions put in front of an llm row's input), tool rows from gen_ai.tool.call.arguments and
    gen_ai.tool.call.result.

Only these rules are modelled. openinference.* and langfuse.* spans, which nothing in the lab sends, are not.

`from_export` reads the LLM Observability export API's spans (docs.datadoghq.com/llm_observability/evaluations/
export_api, read 2026-11-01): span_id, trace_id, parent_id ("undefined" on a root), name, span_kind, and input and
output, each a value and a list of messages.
"""
from __future__ import annotations

import json

QUALIFIERS = ("gen_ai.operation.name", "gen_ai.provider.name", "openinference.span.kind", "langfuse.observation.type",
              "gen_ai.system")
LLM_OPS = ("chat", "generate_content", "text_completion", "completion")
AGENT_OPS = ("invoke_agent", "create_agent")
NO_PARENT = (None, "", "undefined", "0", "0000000000000000")


def _attrs(span: dict) -> dict:
    """An OTLP JSON span's attributes, each as its plain value."""
    out = {}
    for a in span.get("attributes", []):
        v = a.get("value", {})
        out[a["key"]] = next(iter(v.values())) if v else None
    return out


def kind_of(op: str | None) -> str:
    if op in LLM_OPS:
        return "llm"
    if op == "execute_tool":
        return "tool"
    if op in AGENT_OPS:
        return "agent"
    return "workflow"


def _has_text(raw) -> bool:
    """True when a content attribute or export field holds something a row would print."""
    if raw is None:
        return False
    if isinstance(raw, str):
        if not raw.strip():
            return False
        try:
            raw = json.loads(raw)
        except ValueError:
            return True
    if isinstance(raw, dict):
        # A message's role, a part's type and a finish reason label content; alone they are not content.
        return any(_has_text(v) for k, v in raw.items() if k not in ("role", "type", "finish_reason"))
    if isinstance(raw, list):
        return any(_has_text(v) for v in raw)
    return raw is not False


def from_otlp(spans: list[dict]) -> list[dict]:
    """The Agent Observability rows Datadog builds from OTLP JSON spans (each carrying a "service" key, as the
    collector tests read them), for every trace among them."""
    by_trace: dict[str, list[dict]] = {}
    for s in spans:
        by_trace.setdefault(s["traceId"].lower(), []).append(s)
    rows = []
    for trace, members in by_trace.items():
        attrs = [_attrs(s) for s in members]
        if not any(q in a for a in attrs for q in QUALIFIERS):
            continue
        if any(a.get("dd_llmobs_enabled") is False for a in attrs):
            continue
        for s, a in zip(members, attrs):
            if not any(k.startswith("gen_ai.") for k in a):
                continue
            kind = kind_of(a.get("gen_ai.operation.name"))
            if kind == "tool":
                inp, out = a.get("gen_ai.tool.call.arguments"), a.get("gen_ai.tool.call.result")
            else:
                inp, out = a.get("gen_ai.input.messages"), a.get("gen_ai.output.messages")
                if kind == "llm" and _has_text(a.get("gen_ai.system_instructions")):
                    inp = [a["gen_ai.system_instructions"], inp]
            rows.append({"trace_id": trace, "span_id": s["spanId"].lower(),
                         "parent_id": (s.get("parentSpanId") or "").lower() or None, "name": s.get("name"),
                         "kind": kind, "service": s.get("service"), "input": _has_text(inp), "output": _has_text(out)})
    return rows


def from_export(data: list[dict]) -> list[dict]:
    """The rows of the export API's `data` list."""
    rows = []
    for item in data:
        a = item.get("attributes", {})
        rows.append({"trace_id": str(a.get("trace_id", "")).lower(), "span_id": str(a.get("span_id", item.get("id"))),
                     "parent_id": None if a.get("parent_id") is None else str(a["parent_id"]), "name": a.get("name"),
                     "kind": a.get("span_kind"), "service": None,
                     "input": _has_text(a.get("input")), "output": _has_text(a.get("output"))})
    return rows


def interactions(rows: list[dict]) -> dict[str, list[dict]]:
    """Rows by trace id, the interaction they belong to."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["trace_id"], []).append(r)
    return out


def roots(rows: list[dict]) -> list[dict]:
    """The root-level rows: no parent, or a parent that is not a row of the same interaction."""
    ids = {r["span_id"] for r in rows}
    return [r for r in rows if r["parent_id"] in NO_PARENT or r["parent_id"] not in ids]


def problems(rows: list[dict]) -> list[str]:
    """Why one interaction's rows are not one root row holding the prompt and the reply; empty when they are."""
    if not rows:
        return ["Agent Observability has no row for the interaction"]
    top = roots(rows)
    found = []
    if len(top) != 1:
        found.append(f"{len(top)} root-level rows, not one: "
                     + ", ".join(f"{r['name']} ({r['kind']})" for r in top))
    for r in top:
        empty = [side for side in ("input", "output") if not r[side]]
        if empty:
            found.append(f"root row {r['name']} ({r['kind']}) reads No content for its {' and '.join(empty)}")
    return found
