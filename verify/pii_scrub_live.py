# ABOUTME: The live half of #647's trace scrub: the community cluster's collector runs it, a span this check sends in
# ABOUTME: comes back from Datadog APM and LLM Observability scrubbed, and nothing stored for burritobot-public holds raw PII.
"""What test_collector_pii_scrub_live.py runs, kept apart so test_pii_scrub_live_logic.py can run it against fakes.

Three questions, each answered on the live system:

1. Does attackme's collector run the scrub? The collector's rendered config is read off the community cluster
   (ConfigMap otel-collector-opentelemetry-collector-agent in monitoring): transform/scrub_pii must be there with
   values-burn.yaml's own statements, and be the last processor of the traces pipeline. cluster-identity must name
   the cluster burritobot-public, the tag the room's spans carry and the post-talk purge selects on.

2. Does a span with PII in it leave the cluster scrubbed? One span, from a service of its own
   (wib-pii-scrub-check, so it lands in none of BurritoBot's views), is sent over a kubectl port-forward into the
   collector's OTLP/HTTP port, as every BurritoBot pod sends its spans. It carries pii_scrub_cases.ATTENDEE on
   gen_ai.input.messages and on a span event, a tool call's arguments and result holding an e-mail, a phone number
   and a card, and a session.id holding an e-mail. It is then read back from Datadog by its trace id: the APM span
   and its Agent Observability (LLM Observability) copy must hold the scrubbed text, the session.id must be whole,
   and none of the raw values may be anywhere in either. Its span name carries the run's stamp, so APM's diversity
   sampling, which keeps one span per service and resource each 15 minutes, keeps every run's span.

   Why not a chat? Since #648 the public bot's input guard refuses a prompt with any of the four kinds before the
   root span is given it, so a chat carrying PII puts none of it in a trace, and so tests nothing here.

3. Has anything raw reached Datadog? Every APM span stored for kube_cluster_name:burritobot-public in the window,
   and every ml_app:burritobot Agent Observability span on that cluster, is read, and the scrub's own patterns are
   run over the conversation: the keys the scrub rewrites (read from values-burn.yaml's keep_keys, so a key added
   there is scanned too) and every span event's attributes on APM, the input and output on Agent Observability.
   A match is raw PII stored in Whitney's org, and fails. Ids (session.id, gen_ai.conversation.id, kagent.user_id)
   are not conversation, and the scrub leaves them whole on purpose, so they are not scanned.

What it leaves behind: the one span, in Whitney's org under burritobot-public, which the post-talk purge (#647's
teardown step in facilitation/kubecon-na-2026-run-of-show.md) deletes with the rest, and a wib-pii-scrub-check
entry in APM's service list and Agent Observability's ml_app list. Nothing on the cluster changes.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

import yaml

from pii_scrub_cases import ATTENDEE, ATTENDEE_SCRUBBED, SCRUB, burn_scrub, patterns, unquote

CLUSTER = "burritobot-public"
SERVICE = "wib-pii-scrub-check"
ML_APP = "burritobot"
NAMESPACE = "monitoring"
COLLECTOR_CM = "otel-collector-opentelemetry-collector-agent"
COLLECTOR_SVC = "svc/otel-collector-opentelemetry-collector"
OTLP_HTTP = 4318
APM_SEARCH = "/api/v2/spans/events/search"
LLMOBS_SPANS = "/api/v2/llm-obs/v1/spans/events"
# A page of the stored-span scan, and how many spans it reads before it stops and fails as incomplete.
PAGE = 1000
CAP = 100_000

SESSION = "wib-pii-scrub-jo.example+kc@example.co.uk"
TOOL_ARGS = json.dumps({"email": "jo.example+kc@example.co.uk", "phone": "(503) 555-0142"})
TOOL_ARGS_SCRUBBED = json.dumps({"email": "[EMAIL]", "phone": "[PHONE]"})
TOOL_RESULT = json.dumps({"content": [{"type": "text", "text": "morticia@gravemail.com, card 4111 1111 1111 1111"}]})
TOOL_RESULT_SCRUBBED = json.dumps({"content": [{"type": "text", "text": "[EMAIL], card [CARD]"}]})
# Raw values the sent span carries outside session.id, each long enough that no id, hash or timestamp Datadog adds
# can hold it by chance (pii_scrub_cases.RAW_VALUES has 4-digit ones such as "6789", which a random span id can).
SENT_RAW = ("jo.example", "example.co.uk", "555-0142", "503.555.0142", "5035550142", "7946 0958",
            "4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111", "3782 822463 10005", "123-45-6789",
            "gravemail", "morticia@")

Check = tuple[str, bool, str]


def messages(role: str, text: str) -> str:
    return json.dumps([{"role": role, "parts": [{"type": "text", "content": text}]}])


def kv(key: str, value: str) -> dict:
    return {"key": key, "value": {"stringValue": value}}


def conversation_keys() -> list[str]:
    """The span attributes the scrub rewrites, as values-burn.yaml's keep_keys names them."""
    for st in burn_scrub()["trace_statements"][0]["statements"]:
        m = re.match(r'^keep_keys\(cache\["pii"\], \[(.*)\]\)$', st)
        if m:
            return json.loads(f"[{m.group(1)}]")
    raise SystemExit(f"{SCRUB}'s keep_keys statement is not in gitops/otel-collector/values-burn.yaml")


def compiled() -> list[tuple[str, re.Pattern]]:
    """(label, regex) of the scrub's span-context patterns, read as RE2 reads them (ASCII \\b)."""
    stmts = burn_scrub()["trace_statements"][0]["statements"]
    return [(label.strip("[]"), re.compile(unquote(p), re.A)) for _, p, label in patterns(stmts)]


def new_ids() -> tuple[str, str, str]:
    """trace id, span id and a stamp for the span name."""
    return secrets.token_hex(16), secrets.token_hex(8), time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def span_name(stamp: str) -> str:
    return f"pii-scrub-live-check {stamp}"


def otlp_body(trace_id: str, span_id: str, stamp: str, now_ns: int) -> bytes:
    span = {
        "traceId": trace_id, "spanId": span_id, "name": span_name(stamp), "kind": 1,
        "startTimeUnixNano": str(now_ns - 1_000_000_000), "endTimeUnixNano": str(now_ns),
        "attributes": [kv("gen_ai.operation.name", "chat"), kv("gen_ai.input.messages", messages("user", ATTENDEE)),
                       kv("gcp.vertex.agent.tool_call_args", TOOL_ARGS),
                       kv("gcp.vertex.agent.tool_response", TOOL_RESULT), kv("session.id", SESSION)],
        "events": [{"name": "gen_ai.content.prompt", "timeUnixNano": str(now_ns - 500_000_000),
                    "attributes": [kv("content", ATTENDEE)]}],
    }
    return json.dumps({"resourceSpans": [{"resource": {"attributes": [kv("service.name", SERVICE)]},
                                          "scopeSpans": [{"spans": [span]}]}]}).encode()


def llmobs_trace_id(trace_id: str) -> str:
    """The trace id Agent Observability files the span under: traces/llmobs's transform/llmobs_one_root rewrites it
    to the first 32 hex digits of the SHA-256 of the APM trace id."""
    return hashlib.sha256(trace_id.encode()).hexdigest()[:32]


# == 1. the collector on the cluster ==

def collector_checks(kubectl: Callable[[list[str]], str]) -> list[Check]:
    """kubectl takes the arguments after `kubectl --context <ctx>` and returns stdout (raising on failure)."""
    out: list[Check] = []
    relay = yaml.safe_load(kubectl(["-n", NAMESPACE, "get", "configmap", COLLECTOR_CM, "-o", "jsonpath={.data.relay}"])
                           or "{}") or {}
    live = (relay.get("processors") or {}).get(SCRUB)
    out.append((f"the live collector defines {SCRUB} with values-burn.yaml's statements", live == burn_scrub(),
                "absent" if live is None else "its statements differ from gitops/otel-collector/values-burn.yaml"))
    procs = ((relay.get("service") or {}).get("pipelines") or {}).get("traces", {}).get("processors") or []
    out.append((f"{SCRUB} is the last processor of the live traces pipeline", bool(procs) and procs[-1] == SCRUB,
                f"traces processors: {procs}"))
    name = kubectl(["-n", NAMESPACE, "get", "configmap", "cluster-identity", "-o",
                    "jsonpath={.data.datadog-cluster-name}"]).strip()
    out.append((f"cluster-identity names the cluster {CLUSTER}", name == CLUSTER, f"datadog-cluster-name is {name!r}"))
    return out


# == 2. one span through the collector, read back from Datadog ==

def send_through_forward(kubectl_argv: list[str], body: bytes, timeout: float = 30) -> str:
    """POST body to the collector's OTLP/HTTP port over a port-forward. Returns "" on a 200, else why not."""
    pf = subprocess.Popen([*kubectl_argv, "-n", NAMESPACE, "port-forward", "--address", "127.0.0.1", COLLECTOR_SVC,
                           f":{OTLP_HTTP}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        found: list[str] = []

        def first() -> None:
            for line in pf.stdout:
                m = re.search(r"Forwarding from 127\.0\.0\.1:(\d+) -> " + str(OTLP_HTTP), line)
                if m:
                    found.append(m.group(1))
                    return
        reader = threading.Thread(target=first, daemon=True)
        reader.start()
        reader.join(timeout=timeout)
        if not found:
            pf.kill()
            return f"kubectl port-forward {COLLECTOR_SVC} :{OTLP_HTTP} did not come up: {' '.join(pf.stderr.read().split())[:300]}"
        req = urllib.request.Request(f"http://127.0.0.1:{found[0]}/v1/traces", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return "" if r.status == 200 else f"the collector answered {r.status}"
        except (urllib.error.URLError, OSError) as e:
            return f"the OTLP POST over the port-forward failed: {e}"
    finally:
        if pf.poll() is None:
            pf.terminate()
        try:
            pf.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pf.kill()
            pf.wait()


def apm_search(dd, query: str, frm: str, limit: int, cursor: str | None = None, sort: str = "-timestamp") -> dict:
    page = {"limit": limit, **({"cursor": cursor} if cursor else {})}
    return dd.call("POST", APM_SEARCH, {"data": {"type": "search_request", "attributes": {
        "filter": {"query": query, "from": frm, "to": "now"}, "page": page, "sort": sort}}})


def llmobs_get(dd, params: dict) -> dict:
    return dd.call("GET", LLMOBS_SPANS + "?" + urllib.parse.urlencode(params))


def poll(fetch: Callable[[], list[dict]], wait_s: float, every_s: float,
         sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> list[dict]:
    deadline = clock() + wait_s
    while True:
        got = fetch()
        if got or clock() >= deadline:
            return got
        sleep(every_s)


def strings(o, path: str = ""):
    """(dotted path, string) of every string under o."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield from strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(o, list):
        for v in o:
            yield from strings(v, path + "[]")
    elif isinstance(o, str):
        yield path, o


def leaks(o, skip: tuple[str, ...] = ()) -> list[str]:
    """Paths under o, other than those ending in a skip entry, whose string holds a raw value the span was sent with."""
    return sorted({p for p, v in strings(o) if not any(p.endswith(s) for s in skip) and any(r in v for r in SENT_RAW)})


def dig(d: dict, dotted: str):
    for part in dotted.split("."):
        d = d.get(part) if isinstance(d, dict) else None
    return d


def apm_checks(span: dict | None) -> list[Check]:
    """The APM span read back by trace id (one item of /api/v2/spans/events/search's data)."""
    if not span:
        return [("the sent span is in Datadog APM", False, "no span with its trace id arrived in the wait")]
    a = span.get("attributes") or {}
    c = a.get("custom") or {}
    events = c.get("events")
    try:
        ev = json.loads(events) if isinstance(events, str) else (events or [])
    except json.JSONDecodeError:
        ev = []
    content = [((e.get("attributes") or {}).get("content")) for e in ev]
    want = {"gen_ai.input.messages": messages("user", ATTENDEE_SCRUBBED),
            "gcp.vertex.agent.tool_call_args": TOOL_ARGS_SCRUBBED,
            "gen_ai.tool.call.arguments": TOOL_ARGS_SCRUBBED,
            "gcp.vertex.agent.tool_response": TOOL_RESULT_SCRUBBED,
            "gen_ai.tool.call.result": TOOL_RESULT_SCRUBBED}
    out: list[Check] = [("the sent span is in Datadog APM", True, "")]
    out.append((f"it carries kube_cluster_name:{CLUSTER}", f"kube_cluster_name:{CLUSTER}" in (a.get("tags") or []),
                str(a.get("tags"))))
    for key, val in want.items():
        out.append((f"APM's {key} is scrubbed", dig(c, key) == val, f"got {dig(c, key)!r}"))
    out.append(("APM's span event content is scrubbed", content == [ATTENDEE_SCRUBBED], f"got {content!r}"))
    out.append(("APM's session.id is an id, not conversation, and is whole", dig(c, "session.id") == SESSION,
                f"got {dig(c, 'session.id')!r}"))
    bad = leaks(a, skip=("session.id",))
    out.append(("no raw value the span was sent with is anywhere else in the APM span", not bad, f"found under {bad}"))
    return out


def llmobs_checks(span: dict | None) -> list[Check]:
    """The Agent Observability copy (one item of /api/v2/llm-obs/v1/spans/events's data)."""
    if not span:
        return [("the sent span's copy is in Agent Observability", False,
                 "no span with its rewritten trace id arrived in the wait")]
    a = span.get("attributes") or {}
    inp = a.get("input") or {}
    out: list[Check] = [("the sent span's copy is in Agent Observability", True, "")]
    out.append(("Agent Observability's input is scrubbed", inp.get("value") == ATTENDEE_SCRUBBED,
                f"got {inp.get('value')!r}"))
    out.append((f"it carries k8s.cluster.name:{CLUSTER}", f"k8s.cluster.name:{CLUSTER}" in (a.get("tags") or []),
                str(a.get("tags"))))
    # Tags hold the session id as session_id:, session.id: and conversation_id:, the id left whole on purpose.
    tags = [t for t in a.get("tags") or [] if not t.startswith(("session_id:", "session.id:", "conversation_id:"))]
    bad = leaks({**a, "tags": tags})
    out.append(("no raw value the span was sent with is anywhere in the Agent Observability copy", not bad,
                f"found under {bad}"))
    return out


# == 3. what is stored for burritobot-public ==

def conversation_hits(custom: dict, keys: list[str], rxs: list[tuple[str, re.Pattern]]) -> list[tuple[str, str, str]]:
    """(key, label, match) for raw PII in an APM span's conversation keys and span event attributes."""
    texts = [(k, dig(custom, k)) for k in keys]
    events = custom.get("events")
    if isinstance(events, str):
        try:
            events = json.loads(events)
        except json.JSONDecodeError:
            texts.append(("events", events))
            events = []
    for e in events or []:
        for p, v in strings((e or {}).get("attributes") or {}):
            texts.append((f"events.attributes.{p}", v))
    return [(k, label, m.group(0)) for k, v in texts if isinstance(v, str) for label, rx in rxs for m in [rx.search(v)] if m]


def llmobs_hits(attrs: dict, rxs: list[tuple[str, re.Pattern]]) -> list[tuple[str, str, str]]:
    texts = [(f"{side}{p and '.' + p}", v) for side in ("input", "output") for p, v in strings(attrs.get(side) or {})]
    return [(k, label, m.group(0)) for k, v in texts for label, rx in rxs for m in [rx.search(v)] if m]


def scan_apm(dd, hours: int, cap: int = CAP) -> tuple[int, list[tuple[str, str, str, str]], bool]:
    """(spans read, (trace id, key, label, match) hits, complete) over kube_cluster_name:burritobot-public."""
    keys, rxs = conversation_keys(), compiled()
    n, hits, cursor = 0, [], None
    while True:
        r = apm_search(dd, f"kube_cluster_name:{CLUSTER}", f"now-{hours}h", PAGE, cursor)
        for s in r.get("data") or []:
            n += 1
            a = s.get("attributes") or {}
            hits += [(str(a.get("trace_id")), *h) for h in conversation_hits(a.get("custom") or {}, keys, rxs)]
        cursor = ((r.get("meta") or {}).get("page") or {}).get("after")
        if not cursor:
            return n, hits, True
        if n >= cap:
            return n, hits, False


def scan_llmobs(dd, hours: int, cap: int = CAP) -> tuple[int, list[tuple[str, str, str, str]], bool]:
    rxs = compiled()
    n, hits, cursor = 0, [], None
    while True:
        params = {"filter[ml_app]": ML_APP, "filter[query]": f"k8s.cluster.name:{CLUSTER}",
                  "filter[from]": f"now-{hours}h", "filter[to]": "now", "page[limit]": "1000"}
        if cursor:
            params["page[cursor]"] = cursor
        r = llmobs_get(dd, params)
        for s in r.get("data") or []:
            n += 1
            a = s.get("attributes") or {}
            hits += [(str(a.get("trace_id")), *h) for h in llmobs_hits(a, rxs)]
        cursor = ((r.get("meta") or {}).get("page") or {}).get("after")
        if not cursor:
            return n, hits, True
        if n >= cap:
            return n, hits, False


def scan_checks(where: str, n: int, hits: list, complete: bool, hours: int) -> list[Check]:
    shown = "; ".join(f"trace {t} {k} {lab} {m!r}" for t, k, lab, m in hits[:5])
    return [(f"{where}: the scan read every span of the last {hours}h ({n} read)", complete,
             f"stopped at the {CAP}-span cap; set WIB_PII_SCAN_HOURS lower"),
            (f"{where}: no raw e-mail, card, SSN or phone number in the stored conversation", not hits,
             f"{len(hits)} match(es): {shown}")]


def run(kubectl_argv: list[str], kubectl: Callable[[list[str]], str], dd, hours: int, wait_s: float,
        send: Callable[[list[str], bytes], str] = send_through_forward,
        sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
        ids: Callable[[], tuple[str, str, str]] = new_ids, now_ns: Callable[[], int] = time.time_ns,
        log: Callable[[str], None] = print) -> list[Check]:
    checks: list[Check] = []
    log("== 1. the community cluster's collector runs the scrub ==")
    checks += collector_checks(kubectl)
    log("== 2. one span with PII, sent into the live collector, read back from Datadog ==")
    trace_id, span_id, stamp = ids()
    why = send(kubectl_argv, otlp_body(trace_id, span_id, stamp, now_ns()))
    checks.append(("the collector took the span over the port-forward", not why, why))
    if not why:
        log(f"  sent trace {trace_id}, span {span_name(stamp)!r}; waiting up to {wait_s:.0f}s for Datadog")
        apm = poll(lambda: apm_search(dd, f"trace_id:{trace_id}", "now-1h", 5).get("data") or [], wait_s, 20, sleep, clock)
        checks += apm_checks(apm[0] if apm else None)
        lo_id = llmobs_trace_id(trace_id)
        lo = poll(lambda: [s for s in llmobs_get(dd, {"filter[query]": f"service:{SERVICE}", "filter[from]": "now-1h",
                                                       "filter[to]": "now", "page[limit]": "50"}).get("data") or []
                           if (s.get("attributes") or {}).get("trace_id") == lo_id
                           or f"otel.trace_id:{lo_id}" in ((s.get("attributes") or {}).get("tags") or [])],
                  wait_s, 20, sleep, clock)
        checks += llmobs_checks(lo[0] if lo else None)
    log(f"== 3. nothing raw is stored for {CLUSTER} in the last {hours}h ==")
    checks += scan_checks("APM", *scan_apm(dd, hours), hours)
    checks += scan_checks(f"Agent Observability (ml_app:{ML_APP})", *scan_llmobs(dd, hours), hours)
    return checks
