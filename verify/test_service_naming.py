# ABOUTME: Every OpenTelemetry service in the BurritoBot path is one name family, and the root is
# ABOUTME: "burritobot" because Datadog names the Agent Observability application after the root span.
#
# Why. The application was called "guard-proxy": an infrastructure component name in front of a room
# attacking a burrito bot, and the top-level grouping for every page in that product. The root span is
# the proxy's, so renaming it renames the application. Everything else in the path takes the same prefix
# so the Service Map still shows the parts and nothing reads as a stranger. The failure this test
# prevents is a half-rename: a service renamed while a collector condition, a peer.service, or a test
# still matches the old literal, which silently stops a transform from firing.
import pathlib, re, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
ROOT_SERVICE = "burritobot"
FAMILY = {"burritobot", "burritobot-agent", "burritobot-gateway", "burritobot-evil-mcp"}
OLD = ("service.name=guard-proxy", "service.name=kagent", "service.name=agentgateway", "service.name=evil-mcp-shim")
failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


print("== every emitted service name is in the family ==")
emitted = set()
for path in ("gitops/ai-layer/resources.yaml", "gitops/ai-layer/agentgateway.yaml"):
    for m in re.finditer(r"service\.name=([A-Za-z0-9_.-]+)", (REPO / path).read_text()):
        emitted.add(m.group(1))
check(f"emitted service names {sorted(emitted)} are the family", emitted and emitted <= FAMILY)
check("the root service (guard-proxy's span) is exactly 'burritobot'", ROOT_SERVICE in emitted)
check("no old service name is emitted anywhere", not any(o in (REPO / p).read_text() for p in ("gitops/ai-layer/resources.yaml", "gitops/ai-layer/agentgateway.yaml") for o in OLD))

print("== the collector's conditions match the names that are emitted ==")
# Comment lines are ignored: values.yaml documents a commented Bedrock peer.service example, which is an
# external service and deliberately not in the family.
vals = "\n".join(l for l in (REPO / "gitops/otel-collector/values.yaml").read_text().split("\n") if not l.strip().startswith("#"))
referenced = set(re.findall(r'service\.name"\]\s*==\s*"([A-Za-z0-9_.-]+)"', vals))
check(f"collector matches only emitted services {sorted(referenced)}", referenced <= emitted)
peers = set(re.findall(r'set\(attributes\["peer\.service"\],\s*"([A-Za-z0-9_.-]+)"\)', vals))
check(f"peer.service values {sorted(peers)} name real services", peers <= emitted)

print("== the proxy's own peer.service default names a real service ==")
proxy = (REPO / "gitops/ai-layer/proxy.py").read_text()
m = re.search(r'_PEER_SERVICE = os\.environ\.get\("PEER_SERVICE"\) or "([A-Za-z0-9_.-]+)"', proxy)
check("proxy.py peer.service default is a service in the family", bool(m) and m.group(1) in emitted)

print("== the service-map test asserts edges between real services ==")
smap = (REPO / "verify/test_datadog_service_map.py").read_text()
edges = re.findall(r'\("([a-z0-9-]+)",\s*"([a-z0-9-]+)"\),', smap)
named = {s for e in edges for s in e if s.startswith("burritobot")}
check(f"service-map edges use the family {sorted(named)}", named and named <= emitted)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All service-naming checks passed.")
