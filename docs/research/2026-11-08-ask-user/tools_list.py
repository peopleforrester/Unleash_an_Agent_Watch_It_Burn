# ABOUTME: #889's tool specs: lists workshop-mcp's and evil-mcp's tools from the live servers over streamable HTTP and
# ABOUTME: writes them as Bedrock toolSpecs for bedrock_replica.py.
"""kubectl --context watch-it-burn-community -n agent port-forward svc/agentgateway 13001:3001 13003:3003 &
uv run -p 3.12 --with mcp==1.29.1 python tools_list.py tools.json http://127.0.0.1:13001/mcp http://127.0.0.1:13003/mcp
"""
import asyncio, json, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
async def one(url):
    async with streamablehttp_client(url) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return [{"toolSpec": {"name": t.name, "description": t.description or "", "inputSchema": {"json": t.inputSchema}}}
                    for t in (await s.list_tools()).tools]
out = []
for u in sys.argv[2:]:
    out += asyncio.run(one(u))
json.dump(out, open(sys.argv[1], "w"), indent=1)
print([t["toolSpec"]["name"] for t in out])
