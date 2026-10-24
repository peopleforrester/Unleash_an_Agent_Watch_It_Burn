# ABOUTME: MCP client for the #480 spike: tools/list against one URL, printed as JSON, error or result.
# ABOUTME: Needs the mcp package (the workshop-mcp image has it); used by the local bed and the cluster check.
"""python probe.py http://127.0.0.1:3003/mcp [--call <tool>]

Prints one JSON object: {"ok": true, "result": <the tools/list result>} or {"ok": false, "error": {...}}.
With --call it calls that tool by name instead of listing, whatever tools/list said.
The result is the client's view, after the gateway; feed it to `tool_pin.py pin` only from a DIRECT
listing of the upstream server, because that is what the processor sees.
"""
from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.shared.exceptions import McpError
from mcp.client.streamable_http import streamablehttp_client


def leaf(e: BaseException) -> BaseException:
    """The first real error inside the anyio ExceptionGroups the client wraps everything in."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return e


def as_error(e: BaseException) -> dict:
    e = leaf(e)
    if isinstance(e, McpError):
        return {"code": e.error.code, "message": e.error.message, "data": e.error.data}
    return {"type": type(e).__name__, "message": str(e)[:400]}


async def list_tools(url: str, call: str | None = None) -> dict:
    try:
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await (session.call_tool(call, {}) if call else session.list_tools())
                return {"ok": True, "result": result.model_dump(mode="json", by_alias=True, exclude_none=True)}
    except BaseException as e:  # JSON-RPC errors and transport failures both arrive wrapped in ExceptionGroups
        return {"ok": False, "error": as_error(e)}


if __name__ == "__main__":
    call = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--call" else None
    print(json.dumps(asyncio.run(list_tools(sys.argv[1], call)), ensure_ascii=False))
