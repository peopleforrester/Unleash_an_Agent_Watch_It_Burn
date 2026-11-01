# ABOUTME: Offline tests for llmobs_view.py and test_llmobs_one_root_live.py (#757): Datadog's documented OTLP conversion,
# ABOUTME: and #746's two-root, "No content" interaction failing the judge where one root row with content passes.
"""Nothing here reaches Datadog or AWS. The conversion is fed hand-built OTLP spans, one per documented rule. The judge
and the live check are fed export API payloads: #746's evidence shape (guard-proxy's POST /chat and kagent's empty
workflow POST / both roots, every tool call under the second) must fail, and so must each way of half-fixing it. A judge
that passes whatever it is fed proves nothing on the day the live check finally runs.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import llmobs_view as view  # noqa: E402

spec = importlib.util.spec_from_file_location("llmobs_live", HERE / "test_llmobs_one_root_live.py")
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)
fm = live.fm

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


TRACE = "7c2e0f57a3b84d2f8e6a1b7c4d5e0757"
PROMPT = json.dumps([{"role": "user", "parts": [{"type": "text", "content": "One carnitas burrito, please."}]}])
REPLY = json.dumps([{"role": "assistant", "parts": [{"type": "text", "content": "Coming right up."}]}])


def otlp(span_id: str, name: str, parent: str | None, service: str = "burritobot", **attrs) -> dict:
    def value(v):
        if isinstance(v, bool):
            return {"boolValue": v}
        if isinstance(v, int):
            return {"intValue": str(v)}
        return {"stringValue": v}
    s = {"traceId": TRACE, "spanId": span_id, "name": name, "service": service,
         "attributes": [{"key": k.replace("__", "."), "value": value(v)} for k, v in attrs.items()]}
    if parent:
        s["parentSpanId"] = parent
    return s


# The pre-#746 path, as APM's copy carries it with no marker: the guard's chat root, four hops with no gen_ai.*, and
# kagent's server span with only the ids its executor copies on, its invocation and a tool call under it.
BEFORE = [
    otlp("a1", "POST /chat", None, gen_ai__operation__name="chat", gen_ai__input__messages=PROMPT,
         gen_ai__output__messages=REPLY),
    otlp("a2", "agent.forward", "a1"),
    otlp("a3", "POST", "a2"),
    otlp("a4", "POST /", "a3", service="burritobot-gateway", http__request__method="POST"),
    otlp("a5", "Http", "a4", service="burritobot-gateway"),
    otlp("a6", "POST /", "a5", service="burritobot-agent", gen_ai__task__id="t1", gen_ai__conversation__id="c1"),
    otlp("a7", "invoke_agent burritobot", "a6", service="burritobot-agent", gen_ai__operation__name="invoke_agent"),
    otlp("a8", "execute_tool read_support_ticket", "a7", service="burritobot-agent",
         gen_ai__operation__name="execute_tool", gen_ai__tool__call__arguments='{"id": "HC-666"}',
         gen_ai__tool__call__result='{"status": "open"}'),
    otlp("a9", "generate_content", "a7", service="burritobot-agent", gen_ai__operation__name="generate_content",
         gen_ai__system_instructions="You are BurritoBot.", gen_ai__input__messages=PROMPT),
]

print("== the conversion, rule by rule (llmobs_view.from_otlp) ==")
rows = {r["span_id"]: r for r in view.from_otlp(BEFORE)}
check("spans with no gen_ai.* attribute are dropped: the four hops make no row",
      sorted(rows) == ["a1", "a6", "a7", "a8", "a9"], str(sorted(rows)))
check("the parent is kept as sent, so kagent's POST / under the dropped Http span is a root",
      sorted(r["name"] for r in view.roots(list(rows.values()))) == ["POST /", "POST /chat"])
check("kinds come from gen_ai.operation.name: chat llm, invoke_agent agent, execute_tool tool, none workflow",
      [rows[k]["kind"] for k in ("a1", "a7", "a8", "a6", "a9")] == ["llm", "agent", "tool", "workflow", "llm"])
check("an llm row takes gen_ai.input.messages and gen_ai.output.messages", rows["a1"]["input"] and rows["a1"]["output"])
check("a tool row takes gen_ai.tool.call.arguments and gen_ai.tool.call.result", rows["a8"]["input"] and rows["a8"]["output"])
check("a workflow row with neither message attribute reads No content", not rows["a6"]["input"] and not rows["a6"]["output"])
check("an llm row's system instructions count as input, and no output reads empty",
      rows["a9"]["input"] and not rows["a9"]["output"])
marked = [otlp("m1", "x", None, gen_ai__operation__name="chat", gen_ai__input__messages=PROMPT),
          otlp("m2", "y", "m1", dd_llmobs_enabled=False)]
check("an explicit dd_llmobs_enabled false on any span stops the whole trace converting", view.from_otlp(marked) == [])
check("a trace with no qualifying attribute does not convert",
      view.from_otlp([otlp("q1", "POST /", None, gen_ai__conversation__id="c1")]) == [])
check("a message list whose parts hold no text is empty",
      not view.from_otlp([otlp("e1", "chat", None, gen_ai__operation__name="chat",
                                gen_ai__input__messages=json.dumps([{"role": "user", "parts": []}]))])[0]["input"])

print("== the judge on what Datadog builds (llmobs_view.problems) ==")
before = view.problems(view.from_otlp(BEFORE))
check("#746's shape fails on its two roots", "2 root-level rows, not one: POST /chat (llm), POST / (workflow)" in before,
      str(before))
check("and on the root row reading No content", "root row POST / (workflow) reads No content for its input and output"
      in before, str(before))
after = copy.deepcopy(BEFORE)
after[0]["attributes"][0]["value"] = {"stringValue": "invoke_agent"}
after = [s for s in after if s["spanId"] != "a6"]
after[5]["parentSpanId"] = "a1"  # invoke_agent re-parented onto the turn, as transform/llmobs_one_root does
check("one root row with the prompt and the reply passes", view.problems(view.from_otlp(after)) == [],
      str(view.problems(view.from_otlp(after))))
joined_empty = copy.deepcopy(after)
joined_empty[0]["attributes"] = joined_empty[0]["attributes"][:1]
check("one root that reads No content still fails",
      view.problems(view.from_otlp(joined_empty)) == ["root row POST /chat (agent) reads No content for its input and output"],
      str(view.problems(view.from_otlp(joined_empty))))
half = copy.deepcopy(after)
half[0]["attributes"] = [a for a in half[0]["attributes"] if a["key"] != "gen_ai.output.messages"]
check("a root with the prompt but no reply fails on its output",
      view.problems(view.from_otlp(half)) == ["root row POST /chat (agent) reads No content for its output"],
      str(view.problems(view.from_otlp(half))))
check("no row at all fails", view.problems([]) == ["Agent Observability has no row for the interaction"])


def export(trace: str, span_id: str, parent: str, name: str, kind: str, inp: str = "", out: str = "") -> dict:
    side = lambda text: {"value": text, "messages": [{"role": "user", "content": text}] if text else []}  # noqa: E731
    return {"type": "span", "id": span_id, "attributes": {
        "span_id": span_id, "trace_id": trace, "parent_id": parent, "name": name, "span_kind": kind,
        "ml_app": "burritobot", "input": side(inp), "output": side(out)}}


EVIDENCE = "c943363f5467508c8bfc14c6a40c4b59"  # #746's HC-666 trace in the sandbox org, as Whitney read it
TWO_ROOTS = [export(EVIDENCE, "11", "undefined", "POST /chat", "llm", "status of HC-666?", "Deployed."),
             export(EVIDENCE, "12", "99", "POST /", "workflow"),  # its parent, the gateway's Http, was dropped
             export(EVIDENCE, "13", "12", "invoke_agent burritobot", "agent"),
             export(EVIDENCE, "14", "13", "execute_tool read_support_ticket", "tool", '{"id":"HC-666"}', "{}")]
ONE_ROOT_TRACE = "0a2a0f57a3b84d2f8e6a1b7c4d5e0757"
ONE_ROOT = [export(ONE_ROOT_TRACE, "21", "undefined", "POST /chat", "agent", "status of HC-666?", "Deployed."),
            export(ONE_ROOT_TRACE, "22", "21", "invoke_agent burritobot", "agent"),
            export(ONE_ROOT_TRACE, "23", "22", "execute_tool read_support_ticket", "tool", '{"id":"HC-666"}', "{}")]

print("== the judge on the export API's spans (llmobs_view.from_export) ==")
ev = view.problems(view.from_export(TWO_ROOTS))
check("#746's evidence trace fails on its two roots and its empty workflow root",
      ev == ["2 root-level rows, not one: POST /chat (llm), POST / (workflow)",
             "root row POST / (workflow) reads No content for its input and output"], str(ev))
check("an interaction drawn as one root row with content passes", view.problems(view.from_export(ONE_ROOT)) == [])
check("an export span with an empty value and no messages reads No content",
      not view.from_export([export("t", "1", "undefined", "x", "agent")])[0]["input"])


class FakeOrg:
    """A fleet_monitors.Datadog transport answering the export API only, a page per call."""

    def __init__(self, pages: list[list[dict]], status: int = 200):
        self.pages, self.status = pages, status
        self.queries: list[dict] = []

    def __call__(self, method: str, url: str, headers: dict, body: bytes | None):
        path, _, qs = url.partition("?")
        if not (method == "GET" and path.endswith("/api/v2/llm-obs/v1/spans/events")):
            return 404, {"errors": [f"unexpected {method} {path}"]}
        if self.status != 200:
            return self.status, {"errors": ["Forbidden"]}
        q = {k: v[0] for k, v in urllib.parse.parse_qs(qs).items()}
        self.queries.append(q)
        n = int(q.get("page[cursor]", "0"))
        after = str(n + 1) if n + 1 < len(self.pages) else None
        return 200, {"data": self.pages[n], "meta": {"page": {"after": after}}}


def run_live(pages: list[list[dict]], status: int = 200) -> tuple[list[str], FakeOrg]:
    org = FakeOrg(pages, status)
    return live.run(fm.Datadog("datadoghq.com", "api", "app", http=org), minutes=30, say=lambda *_: None), org


print("== the live check's logic (test_llmobs_one_root_live.run) ==")
ok, org = run_live([ONE_ROOT[:2], ONE_ROOT[2:]])
check("an org whose interactions are each one root row with content passes", ok == [], str(ok))
check("it asks for ml_app burritobot over the window, the most a page holds, and follows the cursor",
      [q.get("page[cursor]") for q in org.queries] == [None, "1"]
      and all(q["filter[ml_app]"] == "burritobot" and q["filter[from]"] == "now-30m" and q["filter[to]"] == "now"
              and q["page[limit]"] == "5000" for q in org.queries), str(org.queries))
bad, _ = run_live([ONE_ROOT + TWO_ROOTS])
check("#746's evidence trace in the window fails the live check, and only it",
      bad == [f"interaction {EVIDENCE}: one root row, with the prompt and the reply (4 rows)"], str(bad))
none, _ = run_live([[]])
check("an empty window fails, not passes", none == ["at least one BurritoBot interaction in the last 30 minutes"],
      str(none))
try:
    run_live([ONE_ROOT], status=403)
    refused = False
except RuntimeError as exc:
    refused = "403" in str(exc)
check("a refused query raises, so main() reports it as a FAIL", refused)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All Agent Observability view checks passed.")
