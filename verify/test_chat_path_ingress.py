# ABOUTME: Holds chat-path-ingress (#552) to the chat path's real callers: agentgateway :3000 admits guard-proxy only,
# ABOUTME: :3002 the agent only, workshop-agent :8080 agentgateway and kagent only; the MCP and probe ports stay open.
"""Why (#552). A pod the agent creates, on the default ServiceAccount with ordinary labels, reached agentgateway's
:3002 model bind (Bedrock, signed with agentgateway's own credentials) and the agent's A2A port (agentgateway :3000
or workshop-agent :8080) over agent-allow-intra-namespace, all around guard-proxy. Neither pod restricted ingress.

gitops/ai-layer/chat-path-ingress.yaml admits those ports only from the hop before them. A rule like that can fail
two ways and both look the same on stage, a chat that hangs: it shuts out a real caller (guard-proxy, the agent,
the kagent controller, the C7 fallback in the web terminal), or it leaves the bypass open. So each caller is read
from where it is decided (guard-proxy's AGENT_URL, the gateway-* ModelConfigs, the RemoteMCPServer urls, the
agentgateway :3000 backend, the C7 fallback's GATEWAY) and evaluated against the rules, and so is the bypass pod.
Offline: YAML only. verify/test_llm_bypass_live.py reads the same rules off a live cluster and sends the packets.
"""
from __future__ import annotations

import pathlib
import re
import sys
from urllib.parse import urlparse

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
LAYER = REPO / "gitops/ai-layer"
NS = "agent"
NAME = "app.kubernetes.io/name"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def docs(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]


def one(found: list[dict], kind: str, name: str) -> dict:
    hit = [d for d in found if d.get("kind") == kind and d["metadata"]["name"] == name]
    check(f"{kind}/{name} is declared exactly once", len(hit) == 1)
    return hit[0] if hit else {}


def selects(sel: dict, labels: dict) -> bool:
    return not sel.get("matchExpressions") and all(labels.get(k) == v for k, v in (sel.get("matchLabels") or {}).items())


INGRESS = docs(LAYER / "chat-path-ingress.yaml")
RESOURCES = docs(LAYER / "resources.yaml")
GATEWAY = docs(LAYER / "agentgateway.yaml")
KUSTOMIZATION = yaml.safe_load((LAYER / "kustomization.yaml").read_text())

print("== the policies ship in the ai-layer bundle, on every profile ==")
check("kustomization.yaml lists chat-path-ingress.yaml", "chat-path-ingress.yaml" in KUSTOMIZATION["resources"])
gw_np = one(INGRESS, "NetworkPolicy", "agentgateway-ingress")
agent_np = one(INGRESS, "NetworkPolicy", "workshop-agent-ingress")
for np in (gw_np, agent_np):
    spec = np.get("spec") or {}
    check(f"{np['metadata']['name']} is Ingress only (egress stays the C1 policies' business)",
          spec.get("policyTypes") == ["Ingress"], repr(spec.get("policyTypes")))
    check(f"{np['metadata']['name']} sets no namespace of its own (the bundle's is agent)",
          "namespace" not in np["metadata"])
check("the bundle's namespace is agent", KUSTOMIZATION.get("namespace") == NS)


def pod_template(found: list[dict], name: str) -> dict:
    return one(found, "Deployment", name).get("spec", {}).get("template", {})


gw_pod = pod_template(GATEWAY, "agentgateway")
proxy_pod = pod_template(RESOURCES, "guard-proxy")
terminal_pod = pod_template(RESOURCES, "web-terminal")
gw_labels = gw_pod.get("metadata", {}).get("labels") or {}
proxy_labels = proxy_pod.get("metadata", {}).get("labels") or {}
# kagent writes the agent's Deployment, so its pod labels are not in this repo. fleet.sh finds the pod by this
# selector on every live cluster (restart-agent, the walkthrough's Ready check), which is the measured fact.
fleet = (REPO / "infra/terraform/fleet/fleet.sh").read_text()
m = re.search(r'^readonly AGENT_POD_SELECTOR="([^=]+)=([^"]+)"', fleet, re.M)
agent_labels = {m.group(1): m.group(2)} if m else {}
check("fleet.sh names the agent pod's label (AGENT_POD_SELECTOR)", agent_labels == {NAME: "workshop-agent"},
      repr(agent_labels))
check("agentgateway-ingress selects the agentgateway pod", selects(gw_np["spec"]["podSelector"], gw_labels),
      repr(gw_labels))
check("workshop-agent-ingress selects the agent's pod", selects(agent_np["spec"]["podSelector"], agent_labels))
check("it selects nothing else in the bundle", not any(
    selects(agent_np["spec"]["podSelector"], d["spec"]["template"]["metadata"].get("labels") or {})
    for d in RESOURCES + GATEWAY if d.get("kind") == "Deployment"))


def admits(np: dict, port: int, peer_labels: dict, peer_ns: str = NS, named: dict | None = None) -> bool:
    """Does one Ingress NetworkPolicy let a pod with peer_labels in peer_ns reach its target on TCP port?"""
    named = named or {}
    ns_labels = {"kubernetes.io/metadata.name": peer_ns}
    for rule in np["spec"].get("ingress") or []:
        ports = rule.get("ports")
        if ports and not any(named.get(p["port"], p["port"]) == port and p.get("protocol", "TCP") == "TCP"
                             for p in ports):
            continue
        peers = rule.get("from")
        if not peers:
            return True
        for peer in peers:
            if "ipBlock" in peer:
                return True  # an address range: every pod IP in it, whatever its labels
            ns_ok = selects(peer["namespaceSelector"], ns_labels) if "namespaceSelector" in peer else peer_ns == NS
            if ns_ok and selects(peer.get("podSelector") or {}, peer_labels):
                return True
    return False


gw_ports = {p["name"]: p["containerPort"] for c in gw_pod["spec"]["containers"] for p in c.get("ports") or []}
gw = lambda port, labels, ns=NS: admits(gw_np, port, labels, ns, gw_ports)  # noqa: E731
agent = lambda port, labels, ns=NS: admits(agent_np, port, labels, ns)  # noqa: E731
# The bypass shape: what restrict-agent-spawned-workloads admits (default ServiceAccount, ordinary labels).
PLAIN = {"app": "plain"}
KAGENT = ({}, "kagent")  # any pod in the kagent namespace: the controller, its UI


def port_of(url: str) -> int:
    return urlparse(url).port or 0


print("== agentgateway :3000, the A2A route: guard-proxy only ==")
env = {e["name"]: e.get("value") for c in proxy_pod["spec"]["containers"] for e in c.get("env") or []}
a2a = env.get("AGENT_URL") or ""
check("guard-proxy's AGENT_URL is agentgateway :3000", urlparse(a2a).hostname.split(".")[0] == "agentgateway"
      and port_of(a2a) == 3000, a2a)
check("guard-proxy's pod is admitted on that port", gw(port_of(a2a), proxy_labels), repr(proxy_labels))
for who, labels, ns in (("the bypass pod", PLAIN, NS), ("the agent's own pod", agent_labels, NS),
                        ("the web terminal", terminal_pod["metadata"]["labels"], NS), ("the kagent namespace", *KAGENT)):
    check(f"{who} is not admitted to :3000", not gw(3000, labels, ns))

print("== agentgateway :3002, the model bind: the agent only ==")
inference = [d for d in RESOURCES if d.get("kind") == "ModelConfig"
             and urlparse((d["spec"].get("openAI") or {}).get("baseUrl", "")).hostname
             and urlparse(d["spec"]["openAI"]["baseUrl"]).hostname.split(".")[0] == "agentgateway"]
check("the gateway-* ModelConfigs dial agentgateway", len(inference) >= 2, repr([d["metadata"]["name"] for d in inference]))
for d in inference:
    port = port_of(d["spec"]["openAI"]["baseUrl"])
    check(f"ModelConfig {d['metadata']['name']} (:{port}) is admitted from the agent's pod", gw(port, agent_labels))
    check(f"and not from the bypass pod", not gw(port, PLAIN))
for who, labels, ns in (("guard-proxy", proxy_labels, NS), ("the web terminal", terminal_pod["metadata"]["labels"], NS),
                        ("the kagent namespace", *KAGENT)):
    check(f"{who} is not admitted to :3002", not gw(3002, labels, ns))

print("== agentgateway's MCP fronts and readiness listeners: open ==")
mcp = [d for d in RESOURCES if d.get("kind") == "RemoteMCPServer"]
check("both RemoteMCPServers are found", len(mcp) == 2, repr([d["metadata"]["name"] for d in mcp]))
for d in mcp:
    port = port_of(d["spec"]["url"])
    # The agent calls the tools; the kagent controller lists them from this url; neither reaches a model.
    for who, labels, ns in (("the agent's pod", agent_labels, NS), ("the kagent namespace", *KAGENT)):
        check(f"RemoteMCPServer {d['metadata']['name']} (:{port}) admits {who}", gw(port, labels, ns))
fallback = (REPO / "challenges/03-bad-mcp-excessive-agency/fallback.curl.sh").read_text()
m = re.search(r'^readonly GATEWAY="([^"]+)"', fallback, re.M)
check("the C7 fallback names the gateway it calls from the web terminal", bool(m))
if m:
    check(f"the web terminal is admitted to it (:{port_of(m.group(1))})",
          gw(port_of(m.group(1)), terminal_pod["metadata"]["labels"]))
probes = {c["name"]: [c[k]["tcpSocket"]["port"] for k in ("readinessProbe", "livenessProbe") if "tcpSocket" in c.get(k, {})]
          for c in gw_pod["spec"]["containers"]}
for container, ports in probes.items():
    for p in ports:
        port = gw_ports.get(p, p)
        if port in (3000, 3002):
            continue  # kubelet probes come from the node, which the VPC CNI admits whatever the policy says
        check(f"{container}'s probe port {p} (:{port}) is open to every pod", gw(port, PLAIN))
covered = {3000, 3002} | {port for port in gw_ports.values() if gw(port, PLAIN)}
check("every agentgateway container port is open or guarded on purpose (none closed by accident)",
      set(gw_ports.values()) <= covered, f"closed: {sorted(set(gw_ports.values()) - covered)}")

print("== workshop-agent :8080, the agent itself: agentgateway and kagent only ==")
config = yaml.safe_load(one(GATEWAY, "ConfigMap", "agentgateway-config")["data"]["config.yaml"])
hosts = [b.get("host", "") for bind in config["binds"] if bind["port"] == 3000
         for li in bind["listeners"] for r in li["routes"] for b in r.get("backends", [])]
check("agentgateway :3000 proxies to workshop-agent", any(h.startswith("workshop-agent.") for h in hosts), repr(hosts))
for h in hosts:
    port = int(h.rsplit(":", 1)[1])
    check(f"agentgateway's pod is admitted to the backend {h}", agent(port, gw_labels))
check("the kagent namespace is admitted to :8080 (the controller's A2A proxy behind its UI)", agent(8080, *KAGENT))
for who, labels in (("the bypass pod", PLAIN), ("guard-proxy", proxy_labels),
                    ("the web terminal", terminal_pod["metadata"]["labels"])):
    check(f"{who} is not admitted to :8080", not agent(8080, labels))

print("== every label these rules trust is refused to the agent ==")
policy = yaml.safe_load((REPO / "policies/kyverno/restrict-agent-spawned-workloads.yaml").read_text())
expr = next(v["expression"] for v in policy["spec"]["variables"] if v["name"] == "egressLabels")
for np in (gw_np, agent_np):
    for rule in np["spec"]["ingress"]:
        for peer in rule.get("from") or []:
            for k, v in ((peer.get("podSelector") or {}).get("matchLabels") or {}).items():
                check(f"{np['metadata']['name']} trusts {k}={v}, and egressLabels refuses it", f"'{v}'" in expr
                      and f"'{k}'" in expr, expr)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("chat-path-ingress admits the chat path's callers and nothing around guard-proxy.")
