# ABOUTME: Runtime for the workshop MCP servers (workshop-mcp + evil-mcp-shim), with every dependency
# ABOUTME: baked in so the pods need NO network at startup and can sit behind a default-deny egress policy.
#
# WHY THIS IMAGE EXISTS. The MCP servers used to run the stock python image and install their deps at
# pod start:
#
#     pip install mcp pyyaml && exec python /app/server.py
#
# That single line caused two separate failures, and they are the same failure wearing different hats.
#
#   1. Availability. The version was whatever PyPI served that morning. On 2026-08-27 upstream shipped
#      mcp 2.x, which renamed FastMCP to MCPServer, and both servers CrashLooped on import with 224+
#      restarts. Nothing in the repo had changed. A dependency resolved at RUNTIME means the build that
#      passed every gate yesterday is not the thing that runs today.
#
#   2. Security. Installing at startup means the pods MUST reach the public internet to boot, so they
#      could not be covered by the agent's default-deny egress policy. That hole is exactly what
#      Challenge 1 escapes through: the exfil POST is made by the MCP pod, not the agent pod, so
#      Round 2 did not block it (issue #108). The control was real and pointed at the wrong pod.
#
# Baking the deps fixes both. The image is pinned, reproducible, and the pods need no egress at all,
# which lets the NetworkPolicy cover them without breaking startup.
FROM python:3.12-slim

# curl is needed by the run_shell tool: Challenge 1's exfil POSTs through it, and the beat is that the
# egress POLICY stops it, not a missing binary. A tool that fails because curl is absent teaches the
# wrong lesson.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# mcp is pinned BELOW 2 deliberately. server.py uses `from mcp.server.fastmcp import FastMCP`, which
# 2.x removed. Moving to 2.x is a port of server.py to MCPServer, not a bump of this pin.
# Versions resolved and verified 2026-08-28.
RUN pip install --no-cache-dir --root-user-action=ignore \
      'mcp==1.29.1' \
      'pyyaml==6.0.2' \
 && python -c "from mcp.server.fastmcp import FastMCP; print('FastMCP import OK')"

# server.py is NOT copied in. It is mounted from a ConfigMap so the workshop can edit tool behaviour
# and poisoned descriptions without rebuilding an image mid-event.
WORKDIR /app
CMD ["python", "/app/server.py"]
