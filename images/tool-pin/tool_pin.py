# ABOUTME: tool-pin, an agentgateway ExtMCP processor for the tools/list response (#480, design for #117).
# ABOUTME: Hashes each tool's name, description and inputSchema, and strips or denies any not in the pinned baseline.
"""Pin the tool definitions at approval and refuse on mismatch (#117's proposed control).

agentgateway v1.5.0 calls this server over gRPC (`agentgateway.dev.ext_mcp.ExtMcp`, the proto at
crates/protos/proto/ext_mcp.proto at the v1.5.0 tag) when a route's `mcpGuardrails.processors` maps
`tools/list: response` to it. Once per backend, it hands over the upstream JSON-RPC `result` as raw JSON.
For each tool in it this computes

    sha256( canonical JSON of {"name", "description", "inputSchema"} )

and compares it with the baseline file. A tool whose hash is not in the baseline for that backend, because
its definition changed after approval or because it is new, is not approved. What happens then is PIN_MODE:

    strip (default)  return the result with only the approved tools in it (ExtMCP "mutated")
    deny             reject the whole tools/list with JSON-RPC error -32001 (ExtMCP PERMISSION_DENIED)

Everything else passes unchanged. A baseline that is missing or unreadable raises, the RPC fails, and the
gateway's failureMode (failClosed by default) refuses the list, so a broken pin never fails open.

Stripping a tool from the list does not stop a client calling it by name: on the local bed the gateway
forwarded a tools/call for the stripped get_weather and the rug-pulled tool answered. So the bind also
maps `tools/call: request` here, and a call is refused (the client gets a tool result with isError) unless
the tool was approved in the most recent tools/list for that backend. Before any list has been judged,
nothing is approved.

The baseline is re-read on every call, so re-approving is a ConfigMap edit and needs no restart.

Only the hashing and the protobuf wire format are in this file, both stdlib, so the offline suite tests them
without grpcio (verify/test_tool_pin.py). grpcio is imported only by `serve`, in the image.

Usage:
    python tool_pin.py serve                      # PIN_PORT (9001), PIN_BASELINE, PIN_MODE from the env
    python tool_pin.py pin --service evil-mcp < result.json    # print a baseline from a tools/list result
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field

SERVICE = "agentgateway.dev.ext_mcp.ExtMcp"
PINNED_FIELDS = ("name", "description", "inputSchema")

# AuthorizationError.Code. agentgateway maps PERMISSION_DENIED to JSON-RPC -32001 (ExtMCP docs).
PERMISSION_DENIED = 1
INVALID = 3


# --- the pin ------------------------------------------------------------------------------------
def definition_hash(tool: dict) -> str:
    """The pinned hash of one tool. Keys are sorted and separators fixed, so key order and whitespace in
    the server's JSON do not change it; any change to the text of the three fields does."""
    body = {k: tool.get(k) for k in PINNED_FIELDS}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_baseline(path: str) -> dict[str, dict[str, str]]:
    """{service: {tool name: sha256}} from the baseline file. Raises on anything malformed."""
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    pins: dict[str, dict[str, str]] = {}
    for service, tools in doc["services"].items():
        pins[service] = {name: entry["sha256"] for name, entry in tools.items()}
    return pins


def baseline_from_result(service: str, result: dict) -> dict:
    """A baseline document approving every tool in one tools/list result, with the pinned fields kept
    beside each hash so a reviewer can read what was approved."""
    tools = {}
    for tool in result.get("tools", []):
        entry = {"sha256": definition_hash(tool)}
        entry.update({k: tool.get(k) for k in PINNED_FIELDS if k != "name"})
        tools[tool["name"]] = entry
    return {"services": {service: tools}}


@dataclass
class Verdict:
    kind: str                      # "pass", "mutated" or "deny"
    result: dict | None = None     # the replacement result, for "mutated"
    reason: str = ""               # the JSON-RPC error message, for "deny"
    kept: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)   # pinned name, different definition
    unpinned: list[str] = field(default_factory=list)  # name not in the baseline at all


def judge(result: dict, service: str, pins: dict[str, dict[str, str]], mode: str) -> Verdict:
    approved = pins.get(service, {})
    v = Verdict(kind="pass")
    kept_tools = []
    for tool in result.get("tools", []):
        name = tool.get("name", "")
        if approved.get(name) == definition_hash(tool):
            v.kept.append(name)
            kept_tools.append(tool)
        elif name in approved:
            v.changed.append(name)
        else:
            v.unpinned.append(name)
    if not (v.changed or v.unpinned):
        return v
    if mode == "deny":
        v.kind = "deny"
        parts = []
        if v.changed:
            parts.append("changed since approval: " + ", ".join(v.changed))
        if v.unpinned:
            parts.append("never approved: " + ", ".join(v.unpinned))
        v.reason = f"tool-pin: {service} tool definitions refused ({'; '.join(parts)})"
        return v
    v.kind = "mutated"
    v.result = {**result, "tools": kept_tools}
    return v


# --- protobuf wire format, just the messages this server reads and writes --------------------------
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = n = 0
    while True:
        if i >= len(buf):
            raise ValueError("truncated varint")
        b = buf[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, i
        shift += 7


def _fields(buf: bytes):
    """Yield (field number, wire type, value) for every field; value is an int or bytes."""
    i = 0
    while i < len(buf):
        key, i = _read_varint(buf, i)
        num, wt = key >> 3, key & 7
        if wt == 0:
            val, i = _read_varint(buf, i)
        elif wt == 2:
            ln, i = _read_varint(buf, i)
            if i + ln > len(buf):
                raise ValueError("truncated field")
            val, i = buf[i:i + ln], i + ln
        elif wt == 1:
            val, i = buf[i:i + 8], i + 8
        elif wt == 5:
            val, i = buf[i:i + 4], i + 4
        else:
            raise ValueError(f"unsupported wire type {wt}")
        yield num, wt, val


def _ld(num: int, payload: bytes) -> bytes:
    return _varint(num << 3 | 2) + _varint(len(payload)) + payload


@dataclass
class McpRequest:
    service_names: list[str]
    method: str
    mcp_request: bytes


def decode_mcp_request(buf: bytes) -> McpRequest:
    # 1 service_names, 2 method, 3 metadata_context (unused), 4 mcp_request (params JSON), 5 headers (unused)
    msg = McpRequest([], "", b"")
    for num, wt, val in _fields(buf):
        if num == 1 and wt == 2:
            msg.service_names.append(val.decode("utf-8"))
        elif num == 2 and wt == 2:
            msg.method = val.decode("utf-8")
        elif num == 4 and wt == 2:
            msg.mcp_request = bytes(val)
    return msg


def encode_mcp_request(msg: McpRequest) -> bytes:
    out = b"".join(_ld(1, s.encode()) for s in msg.service_names)
    return out + _ld(2, msg.method.encode()) + _ld(4, msg.mcp_request)


@dataclass
class McpResponse:
    service_names: list[str]
    method: str
    mcp_response: bytes


def decode_mcp_response(buf: bytes) -> McpResponse:
    # 1 service_names (repeated string), 2 method, 3 metadata_context (Struct, unused), 4 mcp_response
    msg = McpResponse([], "", b"")
    for num, wt, val in _fields(buf):
        if num == 1 and wt == 2:
            msg.service_names.append(val.decode("utf-8"))
        elif num == 2 and wt == 2:
            msg.method = val.decode("utf-8")
        elif num == 4 and wt == 2:
            msg.mcp_response = bytes(val)
    return msg


def encode_mcp_response(msg: McpResponse) -> bytes:
    """The gateway's side of the wire, for tests and the local bed."""
    out = b"".join(_ld(1, s.encode()) for s in msg.service_names)
    return out + _ld(2, msg.method.encode()) + _ld(4, msg.mcp_response)


# McpRequestResult and McpResponseResult share the oneof layout: 1 pass, 2 mutated, 3 error.
PASS = _ld(1, b"")


def encode_mutated(result: dict) -> bytes:
    return _ld(2, json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def encode_error(code: int, reason: str) -> bytes:
    return _ld(3, _varint(1 << 3 | 0) + _varint(code) + _ld(2, reason.encode("utf-8")))


def encode_verdict(v: Verdict) -> bytes:
    if v.kind == "pass":
        return PASS
    if v.kind == "mutated":
        return encode_mutated(v.result)
    return encode_error(PERMISSION_DENIED, v.reason)


# --- the server ---------------------------------------------------------------------------------
# service -> the tool names the most recent tools/list for it approved. Written by check_response, read by
# check_request. One process, so one dict; the gateway calls both phases on the same processor. Each list
# replaces the set, so a paginated server (nextCursor) would only keep its last page; evil-mcp has one.
APPROVED: dict[str, set[str]] = {}


def check_request(raw: bytes, log=print) -> bytes:
    msg = decode_mcp_request(raw)
    if msg.method != "tools/call":
        return PASS
    name = json.loads(msg.mcp_request or b"{}").get("name", "")
    service = msg.service_names[0] if len(msg.service_names) == 1 else ""
    if name in APPROVED.get(service, set()):
        return PASS
    log(json.dumps({"event": "tool_pin", "phase": "call", "service": service, "tool": name, "verdict": "deny"},
                   sort_keys=True))
    return encode_error(PERMISSION_DENIED, f"tool-pin: {service} tool {name} is not an approved definition")


def check_response(raw: bytes, baseline_path: str, mode: str, log=print) -> bytes:
    msg = decode_mcp_response(raw)
    if msg.method != "tools/list":
        return PASS
    if len(msg.service_names) != 1:
        # The gateway calls once per backend for a fanout method, so this is a contract change: refuse.
        log(json.dumps({"event": "tool_pin", "verdict": "deny", "error": "backends", "services": msg.service_names}))
        return encode_error(INVALID, f"tool-pin: expected one backend per call, got {msg.service_names}")
    service = msg.service_names[0]
    v = judge(json.loads(msg.mcp_response), service, load_baseline(baseline_path), mode)
    APPROVED[service] = set(v.kept)
    log(json.dumps({"event": "tool_pin", "service": service, "mode": mode, "verdict": v.kind,
                    "kept": v.kept, "changed": v.changed, "unpinned": v.unpinned}, sort_keys=True))
    return encode_verdict(v)


def serve(port: int, baseline_path: str, mode: str) -> None:
    from concurrent import futures

    import grpc

    load_baseline(baseline_path)  # refuse to start on a broken baseline, rather than on the first call

    def on_response(raw, context):
        return check_response(raw, baseline_path, mode, log=lambda line: print(line, flush=True))

    def on_request(raw, context):
        return check_request(raw, log=lambda line: print(line, flush=True))

    handler = grpc.method_handlers_generic_handler(SERVICE, {
        "CheckRequest": grpc.unary_unary_rpc_method_handler(on_request),
        "CheckResponse": grpc.unary_unary_rpc_method_handler(on_response),
    })
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    server.add_generic_rpc_handlers((handler,))
    server.add_insecure_port(f"0.0.0.0:{port}")
    server.start()
    print(json.dumps({"event": "tool_pin_start", "port": port, "mode": mode, "baseline": baseline_path}), flush=True)
    server.wait_for_termination()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    p = sub.add_parser("pin")
    p.add_argument("--service", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "pin":
        print(json.dumps(baseline_from_result(args.service, json.load(sys.stdin)), indent=2, ensure_ascii=False))
        return 0
    mode = os.environ.get("PIN_MODE", "strip")
    if mode not in ("strip", "deny"):
        print(f"PIN_MODE must be strip or deny, not {mode!r}", file=sys.stderr)
        return 2
    serve(int(os.environ.get("PIN_PORT", "9001")), os.environ["PIN_BASELINE"], mode)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
