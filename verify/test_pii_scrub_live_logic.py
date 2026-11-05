# ABOUTME: Offline checks for verify/test_collector_pii_scrub_live.py (#647): pii_scrub_live.run passes on a fake cluster
# ABOUTME: and org that scrub, and fails on each way the live scrub can break: absent, not last, raw text stored or read back.
"""Nothing here reaches a cluster, AWS or Datadog. The cluster is a fake kubectl answering the two ConfigMap reads, the
OTLP send is a stub, and the org is a fake fleet_monitors.Datadog answering the APM search and the LLM Observability
spans API. A live check that passes whatever it is fed proves nothing on the day it runs, so each break below must
turn it red, and the healthy case must be green.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pii_scrub_live as live  # noqa: E402
from pii_scrub_cases import ATTENDEE, ATTENDEE_SCRUBBED, SCRUB, burn_scrub  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


TRACE, SPAN, STAMP = "0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331", "20261105T000000Z"
LO_TRACE = live.llmobs_trace_id(TRACE)
NOW = 1_793_000_000_000_000_000


def relay(last: str = SCRUB, scrub: dict | None = None) -> str:
    procs = ["k8s_attributes", "memory_limiter", "batch", "transform/llmobs_apm_off", SCRUB]
    if last != SCRUB:
        procs = [p for p in procs if p != SCRUB] + [last]
        procs.insert(2, SCRUB)
    return yaml.safe_dump({"processors": {SCRUB: burn_scrub() if scrub is None else scrub, "batch": {}},
                           "service": {"pipelines": {"traces": {"processors": procs}}}})


def fake_kubectl(relay_yaml: str, cluster: str = live.CLUSTER):
    def kubectl(args: list[str]) -> str:
        if live.COLLECTOR_CM in args:
            return relay_yaml
        if "cluster-identity" in args:
            return cluster
        raise AssertionError(f"unexpected kubectl {args}")
    return kubectl


def apm_span(**over) -> dict:
    """The sent span as Datadog APM stores it after the scrub (shape read live on 2026-11-05)."""
    custom = {
        "events": json.dumps([{"time_unix_nano": 1793860870518936394, "name": "gen_ai.content.prompt",
                               "attributes": {"content": ATTENDEE_SCRUBBED}}]),
        "gcp": {"vertex": {"agent": {"tool_call_args": live.TOOL_ARGS_SCRUBBED,
                                     "tool_response": live.TOOL_RESULT_SCRUBBED}}},
        "gen_ai": {"input": {"messages": live.messages("user", ATTENDEE_SCRUBBED)}, "operation": {"name": "chat"},
                   "tool": {"call": {"arguments": live.TOOL_ARGS_SCRUBBED, "result": live.TOOL_RESULT_SCRUBBED}}},
        "k8s": {"cluster": {"name": live.CLUSTER}}, "session": {"id": live.SESSION},
        "otel": {"trace_id": TRACE},
    }
    attrs = {"custom": custom, "service": live.SERVICE, "resource_name": live.span_name(STAMP),
             "span_id": "16350861867650382999", "trace_id": TRACE,
             "tags": [f"kube_cluster_name:{live.CLUSTER}", "env:burritobot-kubecon-na-26"]}
    for path, val in over.items():
        d = attrs
        *head, tail = path.split("__")
        for h in head:
            d = d[h]
        d[tail] = val
    return {"id": "x", "type": "spans", "attributes": attrs}


def llmobs_span(value: str = ATTENDEE_SCRUBBED, extra_tags: tuple[str, ...] = ()) -> dict:
    sid = live.SESSION.replace("+", "_")
    return {"id": "1", "type": "span", "attributes": {
        "input": {"value": value, "messages": [{"content": value, "role": "user"}]}, "ml_app": live.SERVICE,
        "trace_id": "badc8af176b45e9f800ef488680624b6",
        "tags": [f"session_id:{sid}", f"session.id:{sid}", f"conversation_id:{sid}", f"otel.trace_id:{LO_TRACE}",
                 f"k8s.cluster.name:{live.CLUSTER}", *extra_tags]}}


class FakeDD:
    """Answers the APM search (by trace id, or the cluster scan in pages) and the LLM Observability spans API."""

    def __init__(self, sent=None, copy_=None, stored=(), stored_lo=(), endless=False):
        self.sent = sent if sent is not None else apm_span()
        self.copy = copy_ if copy_ is not None else llmobs_span()
        self.stored, self.stored_lo, self.endless = list(stored), list(stored_lo), endless

    def call(self, method, path, body=None):
        if method == "POST" and path == live.APM_SEARCH:
            f = body["data"]["attributes"]
            q, cursor = f["filter"]["query"], f["page"].get("cursor")
            if q == f"trace_id:{TRACE}":
                return {"data": [self.sent] if self.sent else []}
            assert q == f"kube_cluster_name:{live.CLUSTER}", q
            if self.endless:
                return {"data": [apm_span()] * live.PAGE, "meta": {"page": {"after": "more"}}}
            # Two pages: the stored spans, then the sent one, so pagination is followed.
            if cursor is None:
                return {"data": self.stored, "meta": {"page": {"after": "p2"}}}
            return {"data": [apm_span()], "meta": {"page": None}}
        if method == "GET" and path.startswith(live.LLMOBS_SPANS + "?"):
            if "service%3A" in path:
                return {"data": [self.copy] if self.copy else []}
            return {"data": self.stored_lo}
        raise AssertionError(f"unexpected Datadog call {method} {path}")


def run(kubectl=None, dd=None, send=lambda argv, body: "") -> list[live.Check]:
    t = [0.0]

    def sleep(s):
        t[0] += s
    return live.run(["fake-kubectl"], kubectl or fake_kubectl(relay()), dd or FakeDD(), 168, 60,
                    send=send, sleep=sleep, clock=lambda: t[0], ids=lambda: (TRACE, SPAN, STAMP),
                    now_ns=lambda: NOW, log=lambda s: None)


def failed(checks) -> list[str]:
    return [n for n, ok, _ in checks if not ok]


def red(label: str, checks, expect: str) -> None:
    bad = failed(checks)
    check(f"{label}: red, on '{expect}'", any(expect in n for n in bad), f"failed: {bad}")


print("== the inputs ==")
body = live.otlp_body(TRACE, SPAN, STAMP, NOW).decode()
sent_text = json.loads(body)
attrs = {a["key"]: a["value"]["stringValue"]
         for a in sent_text["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]}
check("the sent span carries every raw value the leak check looks for, outside session.id",
      all(any(r in v for k, v in attrs.items() if k != "session.id") or r in ATTENDEE for r in live.SENT_RAW),
      str([r for r in live.SENT_RAW if r not in body]))
check("the scrubbed text holds none of them",
      not [r for r in live.SENT_RAW for s in (ATTENDEE_SCRUBBED, live.TOOL_ARGS_SCRUBBED, live.TOOL_RESULT_SCRUBBED)
           if r in s])
check("the session.id holds raw values (so its being left whole is a real check)",
      any(r in live.SESSION for r in live.SENT_RAW))
check("the span's service is the check's own, not one of BurritoBot's",
      sent_text["resourceSpans"][0]["resource"]["attributes"][0]["value"]["stringValue"] == live.SERVICE
      and not live.SERVICE.startswith("burritobot"))
check("the span name carries the run's stamp", live.span_name(STAMP).endswith(STAMP))
check("the scan reads the eight keys values-burn.yaml's scrub rewrites", len(live.conversation_keys()) == 8
      and "gen_ai.input.messages" in live.conversation_keys(), str(live.conversation_keys()))
check("the scan's patterns are the scrub's four", [lab for lab, _ in live.compiled()] == ["EMAIL", "CARD", "SSN", "PHONE"])
check("the Agent Observability trace id is traces/llmobs's rewrite (SHA-256, first 32 hex digits)",
      len(LO_TRACE) == 32 and LO_TRACE != TRACE)

print("== a healthy cluster and org ==")
checks = run()
check(f"green: all {len(checks)} checks pass", not failed(checks), str(failed(checks)))

print("== each break turns it red ==")
red("no scrub on the live collector", run(kubectl=fake_kubectl(relay(scrub={}))), "with values-burn.yaml's statements")
weak = copy.deepcopy(burn_scrub())
weak["trace_statements"][0]["statements"] = weak["trace_statements"][0]["statements"][:-1]
red("a scrub that never merges its result back", run(kubectl=fake_kubectl(relay(scrub=weak))),
    "with values-burn.yaml's statements")
red("the scrub not last", run(kubectl=fake_kubectl(relay(last="batch"))), "is the last processor")
red("another cluster's name", run(kubectl=fake_kubectl(relay(), cluster="burritobot-private")),
    "cluster-identity names")
red("the collector refuses the span", run(send=lambda argv, body: "the collector answered 503"),
    "the collector took the span")
red("the span never reaches APM", run(dd=FakeDD(sent={})), "is in Datadog APM")
red("the copy never reaches Agent Observability", run(dd=FakeDD(copy_={})), "copy is in Agent Observability")
red("the prompt stored raw in APM",
    run(dd=FakeDD(sent=apm_span(custom__gen_ai={"input": {"messages": live.messages("user", ATTENDEE)}}))),
    "gen_ai.input.messages is scrubbed")
red("the span event stored raw",
    run(dd=FakeDD(sent=apm_span(custom__events=json.dumps([{"attributes": {"content": ATTENDEE}}])))),
    "span event content is scrubbed")
red("session.id rewritten", run(dd=FakeDD(sent=apm_span(custom__session={"id": "wib-pii-scrub-[EMAIL]"}))),
    "session.id is an id")
red("a raw value under a key the scrub does not cover",
    run(dd=FakeDD(sent=apm_span(custom__mcp={"arguments": live.TOOL_ARGS}))), "anywhere else in the APM span")
red("the Agent Observability input stored raw", run(dd=FakeDD(copy_=llmobs_span(ATTENDEE))),
    "Agent Observability's input is scrubbed")
red("a raw value in an Agent Observability tag",
    run(dd=FakeDD(copy_=llmobs_span(extra_tags=("phone:(503) 555-0142",)))), "anywhere in the Agent Observability copy")
raw_stored = apm_span(custom__gen_ai={"output": {"messages": live.messages("assistant", "mail jo@corp.example.com")}})
red("a stored APM span with a raw e-mail in its reply", run(dd=FakeDD(stored=[raw_stored])),
    "APM: no raw e-mail")
raw_event = apm_span(custom__events=json.dumps([{"time_unix_nano": 1, "attributes": {"content": "SSN 123-45-6789"}}]))
red("a stored APM span with a raw SSN in a span event", run(dd=FakeDD(stored=[raw_event])), "APM: no raw e-mail")
red("a stored Agent Observability span with a raw card",
    run(dd=FakeDD(stored_lo=[llmobs_span("card 4111111111111111")])), "Agent Observability (ml_app:burritobot): no raw")
red("a scan that cannot finish", run(dd=FakeDD(endless=True)), "the scan read every span")

print("== what the stored scan leaves alone ==")
ids = apm_span(custom__session={"id": "admin@kagent.dev 5035550142"},
               custom__kagent={"user_id": "admin@kagent.dev"},
               custom__events=json.dumps([{"time_unix_nano": 1793465139709107321, "name": "x",
                                           "attributes": {"content": "[EMAIL]"}}]))
hits = live.conversation_hits(ids["attributes"]["custom"], live.conversation_keys(), live.compiled())
check("ids and span event timestamps are not conversation, so they are not hits", not hits, str(hits))
check("a stored span holding only ids and timestamps keeps the run green", not failed(run(dd=FakeDD(stored=[ids]))),
      str(failed(run(dd=FakeDD(stored=[ids])))))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All live PII scrub logic checks passed.")
