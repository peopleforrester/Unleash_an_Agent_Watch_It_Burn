# Dockerfile for the SYNTHETIC Beat-3 "bad" MCP server. Teaching prop only — see server.py.
# Pin the base image digest at build time and record it in VERSIONS.lock (verify-at-build rule).
FROM python:3.12-slim

# verify-at-build: confirm the current MCP Python SDK version and pin it here at build time.
# The `mcp` package provides FastMCP and the streamable-http transport used by server.py.
RUN pip install --no-cache-dir "mcp>=1.2.0"  # verify-at-build: pin exact version

WORKDIR /app
COPY server.py /app/server.py

# Streamable HTTP transport listens on 8000 (see FastMCP host/port in server.py).
EXPOSE 8000

# Run as non-root; the prop needs no privileges.
RUN useradd --create-home --uid 10001 evil && chown -R evil:evil /app
USER evil

CMD ["python", "/app/server.py"]
