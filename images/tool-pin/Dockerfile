# ABOUTME: Runtime for tool-pin, the #480 spike's agentgateway ExtMCP processor (tools/list hash pinning, #117).
# ABOUTME: grpcio is baked in so the pod needs no egress at start, same reason as images/workshop-mcp.
#
# Built by hand, like the workshop-mcp image, and only for the spike's live check:
#   docker build -t ghcr.io/peopleforrester/watch-it-burn:tool-pin-grpcio-1.84.1 images/tool-pin
#   docker push ghcr.io/peopleforrester/watch-it-burn:tool-pin-grpcio-1.84.1
# then sign it (policies/cosign/README.md) or verify-image-signatures denies the pod.
# Our ghcr.io copy, by digest, not Docker Hub's python:3.12-slim (#714).
FROM ghcr.io/peopleforrester/watch-it-burn:python-3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e

# grpcio only: the protobuf messages are encoded by hand in tool_pin.py, so neither protobuf nor generated
# stubs are needed. Version resolved and checked against the local bed on 2026-10-24 (decisions.md, #480).
RUN pip install --no-cache-dir --root-user-action=ignore 'grpcio==1.84.1' \
 && python -c "import grpc; print('grpcio', grpc.__version__)"

# Baked, not ConfigMap-mounted: the processor is the control, so changing it should be an image change.
# What an operator changes is the baseline, which is mounted (PIN_BASELINE) and re-read on every call.
COPY --chown=1000:1000 tool_pin.py /app/tool_pin.py
WORKDIR /app
USER 1000
EXPOSE 9001
CMD ["python", "/app/tool_pin.py", "serve"]
