# ABOUTME: Judges a /chat turn's trace, as Tempo returns it, for tasks/get poll spans (#1225, #1260): none from guard-proxy,
# ABOUTME: agentgateway or kagent, and the message/send hop with the agent's spans under it. Shared by the live test.
"""guard-proxy forwards a turn to the agent as one A2A `message/send`, then polls `tasks/get` once a second until the
task ends. guard-proxy-agenticburn#77 (a637e68, pinned by #1225) sends each poll with the `agent.forward` span's
context and the sampled flag cleared, and suppresses urllib's span for it, so no poll is recorded anywhere: not by
guard-proxy, not by agentgateway, not by kagent. Before it, a blocked run_shell turn read 114 spans in Tempo, 100 of
them from 25 polls, four per poll (run 19452, trace 5619b12f); after it, 14 (run 19527, trace 117dfe9f). Both traces,
cut to the fields read here, are verify/fixtures/unsampled-polls/.

A poll the change stops dropping can be recorded in three places, and each is judged on its own:

- guard-proxy: a second CLIENT span under `agent.forward`. The first in start order is the message/send.
- agentgateway: a span of the gateway's that is not below the message/send hop. A poll the gateway records while
  guard-proxy does not hangs straight off `agent.forward`, the parent the poll's traceparent names.
- kagent: a span of the agent's that is not below the message/send hop, for the same reason one hop further on.

The message/send hop must still be whole: one gateway SERVER span under it, the gateway's outbound CLIENT span under
that, the agent's server span under the outbound one, and `invocation` and `execute_tool run_shell` below it.

The gateway's access log is read as well (`gateway_hops`): its A2A requests to the agent carrying the trace id are
the message/send and the polls, so a turn whose trace has no poll span can be told from a turn that never polled.
"""
from __future__ import annotations

import base64
import re

GUARD_PROXY = "burritobot"
GATEWAY = ("burritobot-gateway", "agentgateway")
AGENT = "burritobot-agent"
SERVER = (2, "SPAN_KIND_SERVER")
CLIENT = (3, "SPAN_KIND_CLIENT")
RUN_SHELL = "execute_tool run_shell"


def hex_id(v: str) -> str:
    """Tempo writes OTLP ids as base64 in JSON; traceparents and the gateway's log use hex."""
    if re.fullmatch(r"[0-9a-f]{16}|[0-9a-f]{32}", v or ""):
        return v
    return base64.b64decode(v).hex() if v else ""


def spans_of(doc) -> list[dict]:
    """Every span in a Tempo trace answer, with its resource's service.name, whatever the envelope. `input` is the
    span's gen_ai.input.messages, which guard-proxy's POST /chat carries: the prompt the turn was sent."""
    out: list[dict] = []

    def walk(node, svc):
        if isinstance(node, dict):
            res = node.get("resource")
            if isinstance(res, dict):
                svc = next((a["value"].get("stringValue") for a in res.get("attributes", [])
                            if a.get("key") == "service.name"), svc)
            if "spanId" in node and "name" in node:
                attrs = {a.get("key"): a.get("value", {}) for a in node.get("attributes", []) or []}
                out.append({"service": svc, "name": node["name"], "kind": node.get("kind"),
                            "id": hex_id(node["spanId"]), "parent": hex_id(node.get("parentSpanId", "")),
                            "start": int(node.get("startTimeUnixNano", 0) or 0),
                            "input": attrs.get("gen_ai.input.messages", {}).get("stringValue", "")})
                return
            for v in node.values():
                walk(v, svc)
        elif isinstance(node, list):
            for v in node:
                walk(v, svc)

    walk(doc, None)
    return out


def is_turn(spans: list[dict], prompt_text: str) -> bool:
    """The trace is a /chat turn rooted at guard-proxy whose prompt holds `prompt_text`."""
    return any(s["service"] == GUARD_PROXY and s["name"] == "POST /chat" and prompt_text in s["input"] for s in spans)


def judge(spans: list[dict]) -> list[tuple[str, bool, str]]:
    """Each check on one turn's trace, as (name, holds, detail). Every one must hold."""
    by_id = {s["id"]: s for s in spans}
    fwd = [s for s in spans if s["service"] == GUARD_PROXY and s["name"] == "agent.forward"]
    fwd_ids = {s["id"] for s in fwd}
    hops = sorted((s for s in spans if s["service"] == GUARD_PROXY and s["kind"] in CLIENT and s["parent"] in fwd_ids),
                  key=lambda s: s["start"])
    send = hops[0]["id"] if hops else None

    def below_send(span: dict) -> bool:
        seen: set[str] = set()
        cur = by_id.get(span["parent"])
        while cur and cur["id"] not in seen:
            if cur["id"] == send:
                return True
            seen.add(cur["id"])
            cur = by_id.get(cur["parent"])
        return False

    gateway = [s for s in spans if s["service"] in GATEWAY]
    agent = [s for s in spans if s["service"] == AGENT]
    send_gw = [s for s in gateway if s["kind"] in SERVER and s["parent"] == send]
    send_out = [s for s in gateway if s["kind"] in CLIENT and s["parent"] in {g["id"] for g in send_gw}]
    send_agent = [s for s in agent if s["kind"] in SERVER and s["parent"] in {o["id"] for o in send_out}]
    agent_root = {s["id"] for s in send_agent}

    def below_agent(span: dict) -> bool:
        seen: set[str] = set()
        cur = by_id.get(span["parent"])
        while cur and cur["id"] not in seen:
            if cur["id"] in agent_root:
                return True
            seen.add(cur["id"])
            cur = by_id.get(cur["parent"])
        return False

    stray_gw = [s for s in gateway if not below_send(s)]
    stray_agent = [s for s in agent if not below_send(s)]
    inv = [s for s in spans if s["name"] == "invocation"]
    tool = [s for s in spans if s["name"] == RUN_SHELL]

    def names(group: list[dict]) -> str:
        return ", ".join(f"{s['service']} {s['name']!r}" for s in group[:4]) + (" ..." if len(group) > 4 else "")

    return [
        ("the turn called run_shell", bool(tool), f"no {RUN_SHELL!r} span among {len(spans)}"),
        ("guard-proxy's agent.forward is in the trace, once", len(fwd) == 1, f"{len(fwd)} agent.forward spans"),
        ("guard-proxy recorded no tasks/get poll span: one CLIENT span under agent.forward, the message/send",
         len(hops) == 1, f"{len(hops)} CLIENT spans under agent.forward: the message/send and {max(len(hops) - 1, 0)} "
                         "polls" if hops else "no CLIENT span under agent.forward, so no message/send hop"),
        ("agentgateway recorded no tasks/get poll span: every gateway span is below the message/send hop",
         bool(send) and not stray_gw, f"{len(stray_gw)} of {len(gateway)} gateway spans are not: {names(stray_gw)}"),
        ("kagent recorded no tasks/get poll span: every agent span is below the message/send hop",
         bool(send) and not stray_agent, f"{len(stray_agent)} of {len(agent)} agent spans are not: {names(stray_agent)}"),
        ("the gateway's span for the message/send hop is under it, once", len(send_gw) == 1,
         f"{len(send_gw)} gateway SERVER spans under guard-proxy's message/send"),
        ("the agent's server span is under the gateway's outbound span for the message/send", len(send_agent) == 1,
         f"{len(send_agent)} agent SERVER spans under {len(send_out)} gateway outbound spans"),
        ("invocation and execute_tool run_shell hang under the agent's server span for the message/send",
         bool(inv) and bool(tool) and all(below_agent(s) for s in inv + tool),
         f"invocation {len(inv)}, run_shell {len(tool)}; under it: {[below_agent(s) for s in inv + tool]}"),
    ]


def summary(trace_id: str, spans: list[dict]) -> str:
    """One line for the run's record, in the counts run 19452's reader printed."""
    fwd_ids = {s["id"] for s in spans if s["service"] == GUARD_PROXY and s["name"] == "agent.forward"}
    hops = [s for s in spans if s["service"] == GUARD_PROXY and s["kind"] in CLIENT and s["parent"] in fwd_ids]
    gw = [s for s in spans if s["service"] in GATEWAY and s["kind"] in SERVER and s["parent"] in {h["id"] for h in hops}]
    agent = [s for s in spans if s["service"] == AGENT and s["kind"] in SERVER]
    return (f"trace {trace_id}: {len(spans)} spans; guard-proxy hops under agent.forward {len(hops)} "
            f"(tasks/get polls {max(len(hops) - 1, 0)}); gateway SERVER under them {len(gw)}; agent server spans "
            f"{len(agent)}")


_FIELD = re.compile(r"(\S+?)=(\S*)")


def gateway_hops(log: str, trace_id: str) -> int:
    """How many requests agentgateway's access log shows it forwarding to the agent (endpoint workshop-agent, path /)
    under `trace_id`: the message/send and every tasks/get poll. MCP calls to the tool server are not counted."""
    n = 0
    for line in log.splitlines():
        if "\trequest " not in line and " request " not in line:
            continue
        f = dict(_FIELD.findall(line))
        if (f.get("trace.id") == trace_id and f.get("http.path") == "/"
                and f.get("endpoint", "").startswith("workshop-agent.")):
            n += 1
    return n
