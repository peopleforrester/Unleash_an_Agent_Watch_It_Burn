# ABOUTME: Holds that no MCP session the agent opens through agentgateway can die of its own standalone stream (#1303):
# ABOUTME: each MCP bind answers GET /mcp with 405, and evil-mcp's timeout outlasts a stage day where that cannot land.
"""Why this exists (#1303).

On 2026-11-09 the admin KubeCon probe's Challenge 4 attempt on watch-it-burn-private came back with no sentinel. It was
read as Nova not chaining the poisoned description. The gateway's log said otherwise: the bot did call
read_internal_config and get_weather, and the agent logged get_weather failing with "standalone SSE stream: exceeded 5
retries without progress", at the moment the evil-mcp session's sixth GET /mcp stream ended.

kagent 0.10.1's MCP client is go-sdk v1.6.1's StreamableClientTransport, and kagent makes the RemoteMCPServer's
`timeout` (30s by default and as committed) the HTTP client's whole-request timeout (go/adk/pkg/mcp/registry.go,
createTransport). So the client's own GET /mcp stream, the one a server may push on, is cut every 30 seconds. Nothing
is pushed on it, so no event id arrives, and go-sdk counts each cut as a retry without progress; on the sixth
(maxRetries 5) it fails the session, and every tool call in flight fails with it (mcp/streamable.go, handleSSE, at tag
v1.6.1). Every session died about three minutes after it opened, and a turn whose tool call was in flight then lost it.

Two changes, held here:

  * Each MCP bind in both gateway ConfigMaps answers GET /mcp with 405, on a route of its own with no backend. The
    spec's 405 is "no SSE stream at this endpoint", and go-sdk then opens no standalone stream, so there is nothing to
    cut (connectStandaloneSSE). POSTs still reach the MCP route. test_agentgateway_mcp_get_e2e.py runs both ConfigMaps
    on the pinned binary to hold that it routes this way.
  * ai-layer ignores agentgateway-c7-config's content (the live rule flips), so the 3003 bind's 405 reaches new
    clusters only. On one built before it, evil-mcp's session still holds a stream, and its RemoteMCPServer timeout is
    what bounds it: six cuts at the timeout must come to more than MIN_SESSION, so it is at least MIN_SESSION / 6.
    workshop-mcp keeps its 30s, since its bind's ConfigMap is synced and rolls the pod (checksum/agentgateway-config).

Negative controls take each part away and require the check to fail.
"""
from __future__ import annotations

import copy
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
GATEWAY = REPO / "gitops/ai-layer/agentgateway.yaml"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
AI_LAYER_APP = REPO / "gitops/bootstrap/apps/ai-layer.yaml"
CONFIGMAPS = ("agentgateway-config", "agentgateway-c7-config")
# The binds that front an MCP server, and the server each fronts (the RemoteMCPServer urls in resources.yaml).
MCP_BINDS = {("agentgateway-config", 3001): "workshop-mcp", ("agentgateway-c7-config", 3003): "evil-mcp"}
# go-sdk v1.6.1's default maxRetries is 5, so the session fails on the sixth cut.
CUTS = 6
# A session that holds a stream must outlast a stage day and the rehearsal the day before it.
MIN_SESSION_H = 36

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def docs(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def configs(gateway_docs: list[dict]) -> dict[str, dict]:
    return {d["metadata"]["name"]: yaml.safe_load(d["data"]["config.yaml"]) for d in gateway_docs
            if d.get("kind") == "ConfigMap" and d["metadata"]["name"] in CONFIGMAPS}


def routes(cfg: dict, port: int) -> list[dict]:
    return [r for b in cfg.get("binds", []) if b.get("port") == port for li in b.get("listeners", [])
            for r in li.get("routes", [])]


def mcp_targets(route: dict) -> list[str]:
    return [t.get("name") for be in route.get("backends", []) for t in (be.get("mcp") or {}).get("targets", [])]


def refuses_get(route: dict) -> bool:
    """A route that answers GET /mcp itself with 405: matches only GET under /mcp, has no backend."""
    matches = route.get("matches") or []
    return (bool(matches) and all(m.get("method") == "GET" and (m.get("path") or {}).get("pathPrefix") == "/mcp"
                                  for m in matches)
            and not route.get("backends")
            and (route.get("policies") or {}).get("directResponse", {}).get("status") == 405)


def bind_problems(cfg: dict, port: int, target: str) -> list[str]:
    """What keeps this bind from serving MCP POSTs and refusing the standalone GET; empty when it does both."""
    rs = routes(cfg, port)
    out = []
    mcp = [r for r in rs if mcp_targets(r)]
    if [mcp_targets(r) for r in mcp] != [[target]]:
        out.append(f"one MCP route to {target} (found {[mcp_targets(r) for r in mcp]})")
    elif any(m.get("method") for m in mcp[0].get("matches") or []):
        out.append(f"the MCP route matches on a method {mcp[0].get('matches')}, so a POST could miss it")
    refusing = [r for r in rs if refuses_get(r)]
    if len(refusing) != 1:
        out.append(f"one route answering GET /mcp with 405 (found {len(refusing)})")
    if len(rs) != len(mcp) + len(refusing):
        out.append(f"no other route ({len(rs)} routes)")
    return out


DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
UNIT_S = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


def seconds(text: str) -> float | None:
    """A Kubernetes metav1.Duration (Go time.ParseDuration's form, as kagent's CRD takes it) in seconds."""
    parts = DURATION.findall(text or "")
    if not parts or "".join(n + u for n, u in parts) != text:
        return None
    return sum(float(n) * UNIT_S[u] for n, u in parts)


def server(resources: list[dict], name: str) -> dict:
    found = [d for d in resources if d.get("kind") == "RemoteMCPServer" and d["metadata"]["name"] == name]
    return found[0] if len(found) == 1 else {}


def ignored_configmaps(app: dict) -> set[str]:
    return {i.get("name") for i in app["spec"].get("ignoreDifferences", []) if i.get("kind") == "ConfigMap"}


gateway_docs, resources, app = docs(GATEWAY), docs(RESOURCES), docs(AI_LAYER_APP)[0]
cfgs = configs(gateway_docs)
check(f"both gateway ConfigMaps are in {GATEWAY.relative_to(REPO)} ({sorted(cfgs)})", set(cfgs) == set(CONFIGMAPS))
if failures:
    sys.exit(1)

print("== each MCP bind serves MCP POSTs and answers the standalone GET /mcp with 405 ==")
for (cm, port), target in MCP_BINDS.items():
    problems = bind_problems(cfgs[cm], port, target)
    check(f"{cm} :{port} ({target})", not problems, "; ".join(problems))

print("== each RemoteMCPServer dials its bind ==")
for (cm, port), target in MCP_BINDS.items():
    spec = server(resources, target).get("spec", {})
    check(f"{target} is STREAMABLE_HTTP at agentgateway :{port} ({spec.get('protocol')}, {spec.get('url')})",
          spec.get("protocol") == "STREAMABLE_HTTP" and spec.get("url") == f"http://agentgateway.agent:{port}/mcp")

print("== where the 405 cannot land, evil-mcp's session outlasts a stage day ==")
ignored = ignored_configmaps(app)
check(f"ai-layer syncs agentgateway-config, so the 3001 bind's 405 reaches every cluster (ignored: {sorted(ignored)})",
      "agentgateway-config" not in ignored)
check("ai-layer ignores agentgateway-c7-config's content, the case evil-mcp's timeout is for",
      "agentgateway-c7-config" in ignored)
evil_timeout = server(resources, "evil-mcp").get("spec", {}).get("timeout", "")
s = seconds(evil_timeout)
check(f"evil-mcp's timeout {evil_timeout!r} times {CUTS} cuts is at least {MIN_SESSION_H}h",
      s is not None and s * CUTS >= MIN_SESSION_H * 3600, f"parsed as {s} s")

print("== negative controls ==")
for label, mutate in (
    ("the 405 route taken off the 3003 bind",
     lambda c: c["agentgateway-c7-config"]["binds"][0]["listeners"][0]["routes"].pop()),
    ("the 3001 bind's 405 turned into a 404",
     lambda c: routes(c["agentgateway-config"], 3001)[-1]["policies"]["directResponse"].update({"status": 404})),
    ("the 3003 bind's refusing route matching every method",
     lambda c: routes(c["agentgateway-c7-config"], 3003)[-1]["matches"][0].pop("method")),
    ("the 3001 bind's MCP route limited to GET",
     lambda c: routes(c["agentgateway-config"], 3001)[0].update({"matches": [{"method": "GET"}]})),
):
    broken = copy.deepcopy(cfgs)
    try:
        mutate(broken)
    except (IndexError, KeyError) as e:
        check(f"{label}: the control could edit the committed config", False, f"{type(e).__name__}: {e}")
        continue
    caught = any(bind_problems(broken[cm], port, target) for (cm, port), target in MCP_BINDS.items())
    check(f"{label} is caught", caught)
for text, want in (("30s", 30.0), ("12h", 43200.0), ("1h30m", 5400.0), ("500ms", 0.5), ("12 h", None), ("", None)):
    check(f"a duration of {text!r} reads as {want}", seconds(text) == want)
check("kagent's 30s default would be caught", seconds("30s") * CUTS < MIN_SESSION_H * 3600)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nNo MCP session the agent opens through agentgateway dies of its standalone stream.")
