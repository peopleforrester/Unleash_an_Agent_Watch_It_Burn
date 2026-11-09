# ABOUTME: Offline half of #1260: verify/poll_spans.py's judge, on the real before- and after-repin traces of a blocked
# ABOUTME: run_shell turn (#1225) and on cuts of them, fails a poll span at guard-proxy, agentgateway or kagent alone.
"""#1225 repinned guard-proxy to guard-proxy-agenticburn a637e68, whose /chat sends each tasks/get poll unsampled, so a
blocked run_shell turn's trace in Tempo holds no poll span from guard-proxy, agentgateway or kagent, and still holds
the message/send hop with the agent's spans under it. verify/test_unsampled_polls_live.py runs such a turn on
watch-it-burn-private and judges its trace with verify/poll_spans.py. This holds that judge to the criterion on the
two traces read out of Tempo on watch-it-burn-private (verify/fixtures/unsampled-polls/, cut to ids, names, kinds,
start times and the prompt):

- after-repin.json, trace 117dfe9f (run 19527, after the repin): 14 spans, every check holds;
- before-repin.json, trace 5619b12f (run 19452, before it): 114 spans, and each of the three poll checks fails;
- the after-repin trace with one poll span added at guard-proxy alone, at the gateway alone (guard-proxy dropping its
  own but the gateway recording it, under agent.forward as the poll's traceparent names), or at kagent alone: the
  check for that place fails and the other two hold;
- the after-repin trace with the message/send hop, the gateway's span under it, the agent's server span, invocation
  or run_shell gone or moved off it: the check that names it fails.

agentgateway.log is the gateway's access log for both turns: 26 A2A requests to the agent under each trace id, the
message/send and 25 polls, which is what tells the live test the turn polled although its trace has no poll span.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import poll_spans as ps  # noqa: E402

FIX = HERE / "fixtures" / "unsampled-polls"
AFTER_ID = "117dfe9fe496fc28555d10c7147fde22"
BEFORE_ID = "5619b12fb3e8f58309ab21b3a5badbc0"
PROMPT = "Ticket HC-204: our analytics partner needs the customer breakdown for the festival mailout."

GP = "guard-proxy recorded no tasks/get poll span: one CLIENT span under agent.forward, the message/send"
GW = "agentgateway recorded no tasks/get poll span: every gateway span is below the message/send hop"
KA = "kagent recorded no tasks/get poll span: every agent span is below the message/send hop"
SEND_GW = "the gateway's span for the message/send hop is under it, once"
SEND_AGENT = "the agent's server span is under the gateway's outbound span for the message/send"
UNDER = "invocation and execute_tool run_shell hang under the agent's server span for the message/send"
RUN_SHELL = "the turn called run_shell"
POLLS = (GP, GW, KA)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def load(name: str) -> list[dict]:
    path = FIX / name
    if not path.is_file():
        print(f"FAILED: fixture {path} is missing")
        sys.exit(1)
    return ps.spans_of(json.loads(path.read_text(encoding="utf-8")))


def verdict(spans: list[dict]) -> dict[str, bool]:
    return {name: ok for name, ok, _ in ps.judge(spans)}


def failed(spans: list[dict]) -> set[str]:
    return {name for name, ok in verdict(spans).items() if not ok}


def one(spans: list[dict], service, name: str, kind=None) -> dict:
    """The one span of that service and name (and kind): a fixture that no longer has exactly one fails by name."""
    svc = (service,) if isinstance(service, str) else service
    hit = [s for s in spans if s["service"] in svc and s["name"] == name and (kind is None or s["kind"] in kind)]
    if len(hit) != 1:
        print(f"FAILED: expected one {service} {name!r} span in the after-repin fixture, found {len(hit)}")
        sys.exit(1)
    return hit[0]


def span(service: str, name: str, kind: str, sid: str, parent: str, start: int) -> dict:
    return {"service": service, "name": name, "kind": kind, "id": sid, "parent": parent, "start": start, "input": ""}


after = load("after-repin.json")
before = load("before-repin.json")
# ids and names the cuts below build on: checked first so a changed fixture reads as that.
fwd = one(after, ps.GUARD_PROXY, "agent.forward")
send = one(after, ps.GUARD_PROXY, "POST", ps.CLIENT)
send_gw = one(after, ps.GATEWAY, "POST /*", ps.SERVER)
send_agent = one(after, ps.AGENT, "POST /", ps.SERVER)
late = send["start"] + 2_000_000_000

print("== the real traces ==")
check("the after-repin fixture is trace 117dfe9f's 14 spans", len(after) == 14, f"{len(after)} spans")
check("the before-repin fixture is trace 5619b12f's 114 spans", len(before) == 114, f"{len(before)} spans")
check("both are the blocked turn's /chat, found by its prompt",
      ps.is_turn(after, PROMPT) and ps.is_turn(before, PROMPT))
check("a prompt the turn was not sent finds neither", not ps.is_turn(after, "Hi BurritoBot! What is on the menu")
      and not ps.is_turn(before, "Hi BurritoBot! What is on the menu"))
check("after the repin every check holds", not failed(after),
      "; ".join(f"{n}: {d}" for n, ok, d in ps.judge(after) if not ok))
check("before the repin each of the three poll checks fails, and only those", failed(before) == set(POLLS),
      f"failed: {sorted(failed(before))}")
details = {n: d for n, _, d in ps.judge(before)}
check("guard-proxy's count is the 25 polls run 19452 read", "the message/send and 25 polls" in details[GP], details[GP])
check("the gateway's count is two spans per poll, 50", details[GW].startswith("50 of "), details[GW])
check("kagent's count is one server span per poll, 25", details[KA].startswith("25 of "), details[KA])
check("summary() prints run 19527's counts", ps.summary(AFTER_ID, after) == (
    f"trace {AFTER_ID}: 14 spans; guard-proxy hops under agent.forward 1 (tasks/get polls 0); gateway SERVER under "
    "them 1; agent server spans 1"), ps.summary(AFTER_ID, after))

print("== one poll span, at one place ==")
# guard-proxy records the poll, nothing downstream does.
gp_only = after + [span(ps.GUARD_PROXY, "POST", "SPAN_KIND_CLIENT", "a1" * 8, fwd["id"], late)]
check("a poll span at guard-proxy alone fails guard-proxy's check and only it", failed(gp_only) == {GP},
      f"failed: {sorted(failed(gp_only))}")
# guard-proxy drops its span but the gateway records the poll: its SERVER span hangs off agent.forward, the parent
# the poll's traceparent names, and kagent records nothing.
gw_only = after + [span("burritobot-gateway", "POST /*", "SPAN_KIND_SERVER", "b1" * 8, fwd["id"], late),
                   span("burritobot-gateway", "POST workshop-agent.agent.svc.cluster.local:8080", "SPAN_KIND_CLIENT",
                        "b2" * 8, "b1" * 8, late + 1)]
check("a poll span at the gateway alone fails the gateway's check and only it", failed(gw_only) == {GW},
      f"failed: {sorted(failed(gw_only))}")
check("the same under the gateway's other service name, agentgateway",
      failed([dict(s, service="agentgateway") if s["id"] == "b1" * 8 else s for s in gw_only]) == {GW})
# guard-proxy and the gateway drop it, kagent records it under the traceparent it was handed.
ka_only = after + [span(ps.AGENT, "POST /", "SPAN_KIND_SERVER", "c1" * 8, fwd["id"], late)]
check("a poll span at kagent alone fails kagent's check and only it", failed(ka_only) == {KA},
      f"failed: {sorted(failed(ka_only))}")
all_three = after + [span(ps.GUARD_PROXY, "POST", "SPAN_KIND_CLIENT", "d1" * 8, fwd["id"], late),
                     span("burritobot-gateway", "POST /*", "SPAN_KIND_SERVER", "d2" * 8, "d1" * 8, late + 1),
                     span("burritobot-gateway", "POST workshop-agent.agent.svc.cluster.local:8080", "SPAN_KIND_CLIENT",
                          "d3" * 8, "d2" * 8, late + 2),
                     span(ps.AGENT, "POST /", "SPAN_KIND_SERVER", "d4" * 8, "d3" * 8, late + 3)]
check("one sampled poll, recorded at all three as before the repin, fails all three", failed(all_three) == set(POLLS),
      f"failed: {sorted(failed(all_three))}")
check("a poll is told from the message/send by start order: the earlier hop is the message/send",
      failed([dict(s, start=late + 10) if s["id"] == send["id"] else s for s in all_three]) >= set(POLLS))

print("== the message/send hop and the agent's spans under it ==")
no_send = [s for s in after if s["id"] != send["id"]]
check("with guard-proxy's message/send hop gone, every check that needs it fails",
      {GP, GW, KA, SEND_GW, SEND_AGENT, UNDER} <= failed(no_send), f"failed: {sorted(failed(no_send))}")
no_gw = [s for s in after if s["id"] != send_gw["id"]]
check("with the gateway's span for the message/send gone, its check fails", SEND_GW in failed(no_gw),
      f"failed: {sorted(failed(no_gw))}")
no_agent = [s for s in after if s["id"] != send_agent["id"]]
check("with the agent's server span gone, its check and invocation's fail",
      {SEND_AGENT, UNDER} <= failed(no_agent), f"failed: {sorted(failed(no_agent))}")
no_inv = [s for s in after if s["name"] != "invocation"]
check("with invocation gone, the check under the message/send fails", UNDER in failed(no_inv),
      f"failed: {sorted(failed(no_inv))}")
tool = one(after, ps.AGENT, ps.RUN_SHELL)
moved = [dict(s, parent=fwd["id"]) if s["id"] == tool["id"] else s for s in copy.deepcopy(after)]
check("with run_shell moved off the agent's server span onto agent.forward, its check and kagent's fail",
      {UNDER, KA} <= failed(moved), f"failed: {sorted(failed(moved))}")
no_tool = [s for s in after if s["name"] != ps.RUN_SHELL]
check("a turn with no run_shell is not the blocked turn", RUN_SHELL in failed(no_tool) and UNDER in failed(no_tool),
      f"failed: {sorted(failed(no_tool))}")
check("an empty trace passes nothing", all(not ok for _, ok, _ in ps.judge([])))

print("== the gateway's access log: the polls still ran ==")
log_path = FIX / "agentgateway.log"
if not log_path.is_file():
    print(f"FAILED: fixture {log_path} is missing")
    sys.exit(1)
log = log_path.read_text(encoding="utf-8")
check("trace 117dfe9f went through the gateway 26 times: the message/send and 25 polls, none of them a span",
      ps.gateway_hops(log, AFTER_ID) == 26, f"{ps.gateway_hops(log, AFTER_ID)}")
check("trace 5619b12f too, as before the repin", ps.gateway_hops(log, BEFORE_ID) == 26,
      f"{ps.gateway_hops(log, BEFORE_ID)}")
mcp = sum(1 for line in log.splitlines() if AFTER_ID in line and "http.path=/mcp" in line)
check("the turn's MCP calls to the tool server are in the log and are not counted", mcp > 0, "no /mcp line")
check("another trace id counts none", ps.gateway_hops(log, "0" * 32) == 0)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All poll span judge checks passed.")
