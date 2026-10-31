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
sys.path.insert(0, str(REPO / "verify"))
import collector_render  # noqa: E402
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
MANIFESTS = ("gitops/ai-layer/resources.yaml", "gitops/ai-layer/agentgateway.yaml", "gitops/workshop-agent/agent.yaml")
for path in MANIFESTS:
    for m in re.finditer(r"service\.name=([A-Za-z0-9_.-]+)", (REPO / path).read_text()):
        emitted.add(m.group(1))
check(f"emitted service names {sorted(emitted)} are the family", emitted and emitted <= FAMILY)
check("the root service (guard-proxy's span) is exactly 'burritobot'", ROOT_SERVICE in emitted)
check("no old service name is emitted anywhere", not any(o in (REPO / p).read_text() for p in MANIFESTS for o in OLD))

# The OTEL_SERVICE_NAME pin is checked on the kustomize render in test_service_naming_render.py, which
# needs kubectl and so runs in the E2E suite.

print("== the collector's conditions match the names that are emitted ==")
# Comment lines are ignored: values.yaml documents a commented Bedrock peer.service example, which is an
# external service and deliberately not in the family.
vals = "\n".join(l for l in (REPO / "gitops/otel-collector/values.yaml").read_text().split("\n") if not l.strip().startswith("#"))
# Conditions may name a LEGACY alias as well: a binary that ignores the rename must keep being filtered.
LEGACY = {"agentgateway", "kagent", "guard-proxy", "evil-mcp-shim"}
# kagent reports the Agent's metadata.name with "-" turned into "_" as service.name, whatever the env says
# (#634), and transform/kagent_service_name maps exactly that name to burritobot-agent.
agent_doc = next(d for d in yaml.safe_load_all((REPO / "gitops/workshop-agent/agent.yaml").read_text())
                 if d and d.get("kind") == "Agent" and d.get("apiVersion", "").startswith("kagent.dev/"))
kagent_name = agent_doc["metadata"]["name"].replace("-", "_")
rename = yaml.safe_load((REPO / "gitops/otel-collector/values.yaml").read_text())["config"]["processors"]["transform/kagent_service_name"]
want = f'set(attributes["service.name"], "burritobot-agent") where attributes["service.name"] == "{kagent_name}"'
for signal in ("trace_statements", "metric_statements"):
    stmts = [s for blk in rename.get(signal, []) if blk.get("context") == "resource" for s in blk["statements"]]
    check(f"{signal}: the collector maps kagent's own name {kagent_name!r} to burritobot-agent", stmts == [want])
# Right after memory_limiter on every profile, with and without datadog-secret: every filter and transform after
# it matches burritobot-agent, and silently matches nothing if the rename comes later.
for profile in collector_render.PROFILE_APP:
    for secret in (False, True):
        pipes = collector_render.collector_config(profile, secret)["service"]["pipelines"]
        for p in ("traces", "metrics"):
            check(f"{profile} (datadog-secret {secret}) {p}: transform/kagent_service_name runs right after memory_limiter",
                  pipes[p]["processors"][:2] == ["memory_limiter", "transform/kagent_service_name"])
referenced = set(re.findall(r'service\.name"\]\s*==\s*"([A-Za-z0-9_.-]+)"', vals)) - {kagent_name}
referenced |= {n for grp in re.findall(r'IsMatch\(resource\.attributes\["service\.name"\],\s*"\^\(([^)]+)\)\$"', vals) for n in grp.split("|")}
check(f"collector matches only known services {sorted(referenced)}", referenced <= (emitted | LEGACY))
check("every collector condition that names a legacy alias also names its new name",
      all(any(n in emitted for n in grp.split("|")) for grp in re.findall(r'IsMatch\(resource\.attributes\["service\.name"\],\s*"\^\(([^)]+)\)\$"', vals)))
peers = set(re.findall(r'set\(attributes\["peer\.service"\],\s*"([A-Za-z0-9_.-]+)"\)', vals))
check(f"peer.service values {sorted(peers)} name real services", peers <= emitted)

print("== the proxy's own peer.service default names a real service ==")
proxy = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text()
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
