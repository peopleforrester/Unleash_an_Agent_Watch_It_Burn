# ABOUTME: Holds Challenge 1's option B build (#861): stage 2 keeps the DNS door open, the DNS lock shuts it, 443 leaves
# ABOUTME: only through the egress waypoint's Open-Meteo allowlist, Bedrock stays in-VPC, Pod Identity stays, agent-dns splits.
"""Offline checks for the #861 build items, read from the manifests.

The #724 decision (question 1009) chose B, a forced egress proxy with a hostname allowlist, over floor C, a locked
resolver. Question 1077 (#860) settled that it is built on the Istio ambient mesh, as an egress waypoint, and #959 checked
on the pinned Istio 1.30.4 that the pattern works when the waypoint's AuthorizationPolicy matches the TLS SNI. #861 named
four build items. This test pins each one in the files that carry it:

1. No agent pod but the egress waypoint has a path to the internet on 443, in the fixed set, and the fix narrows
   agent-allow-dns from all of kube-system to the agent-dns resolver, which may reach kube-dns alone. Stage 2 keeps DNS
   open, so stage 2b still shows the door, and it keeps the feed's direct 443, which the burn and community clusters use.
2. The waypoint's allowlist is exactly the Open-Meteo hosts weather_feed.py calls, so C7's get_weather keeps working.
3. Bedrock keeps the in-VPC 10.0.0.0/16:443 allow, which reaches no public host, and Pod Identity keeps
   169.254.170.23:80. agent-dns answers the Bedrock runtime name, the one interface endpoint in the VPC.
4. The waypoint is on the mesh profiles, which list the Istio layer and the Gateway API CRDs it needs, and on no other.

The admin profile's armed set (policies/network-policies/per-namespace) is the fixed state, and the challenge-fixes
ConfigMap carries both the stage 2 file and the fix a student applies. What the CNI and ztunnel enforce, and whether a
name leaves, is the live check verify/test_c1_dns_lock_live.py; the mutation's effect on a pod is
verify/test_agent_dns_mutation.py.
"""
from __future__ import annotations

import ipaddress
import pathlib
import re
import sys
import urllib.parse

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
PER_NS = REPO / "policies/network-policies/per-namespace"
RES = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text()) if isinstance(d, dict)]
WAYPOINT_DOCS = [d for d in yaml.safe_load_all((REPO / "gitops/egress-waypoint/egress-waypoint.yaml").read_text()) if d]
DNS_DIR = REPO / "gitops/agent-dns"
DNS_DOCS = [d for f in sorted(DNS_DIR.glob("*.yaml")) for d in yaml.safe_load_all(f.read_text()) if d]
VPC_RESOLVER = "169.254.169.253/32"
WAYPOINT = {"gateway.networking.k8s.io/gateway-name": "egress-waypoint"}
RESOLVER = {"app.kubernetes.io/name": "agent-dns"}
KUBE_DNS_PEER = {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
                 "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}
DNS_PORTS = [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def one(docs: list[dict], kind: str, name: str) -> dict:
    found = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    return found[0] if len(found) == 1 else {}


fixes = next(d for d in RES if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "challenge-fixes").get("data") or {}


def policies(text: str) -> dict[str, dict]:
    return {d["metadata"]["name"]: d for d in yaml.safe_load_all(text) if d and d.get("kind") == "NetworkPolicy"}


STAGE2 = policies(fixes.get("c1-network-policy.yaml", ""))
LOCK = policies(fixes.get("c1-dns-lock.yaml", ""))
ADMIN = {}
for f in sorted(PER_NS.glob("agent-*.yaml")):
    ADMIN.update(policies(f.read_text()))
# What a cluster holds once the student has applied both files in order: the fix replaces policies by name.
FIXED = {**STAGE2, **LOCK}

check("the stage 2 file and the fix are both in challenge-fixes", bool(STAGE2) and bool(LOCK),
      f"stage 2 {sorted(STAGE2)}, fix {sorted(LOCK)}")
check("the fix replaces agent-allow-dns, the feed's rule and the waypoint's allows",
      sorted(LOCK) == ["agent-allow-dns", "agent-allow-egress-waypoint", "agent-allow-weather-feed-egress"], sorted(LOCK))


def selects(np: dict, labels: dict) -> bool:
    """Whether the policy's podSelector selects a pod carrying `labels` (matchLabels only; the set uses no more)."""
    sel = np["spec"].get("podSelector") or {}
    return all(labels.get(k) == v for k, v in (sel.get("matchLabels") or {}).items())


def rules_for(pset: dict[str, dict], labels: dict) -> list[dict]:
    return [r for np in pset.values() if np["metadata"].get("namespace", "agent") == "agent" and selects(np, labels)
            for r in np["spec"].get("egress") or []]


def internet_443(rule: dict) -> bool:
    """A rule that admits TCP 443 to some address outside the VPC and the service range."""
    ports = rule.get("ports")
    if ports is not None and not any(p.get("port") == 443 for p in ports):
        return False
    peers = rule.get("to")
    if not peers:
        return True
    inside = [ipaddress.ip_network("10.0.0.0/16"), ipaddress.ip_network("172.20.0.0/16")]
    for p in peers:
        block = p.get("ipBlock")
        if block and not any(ipaddress.ip_network(block["cidr"]).subnet_of(n) for n in inside):
            return True
    return False


def dns_peers(rule: dict) -> list[dict]:
    ports = rule.get("ports")
    if ports is not None and not any(p.get("port") == 53 for p in ports):
        return []
    return rule.get("to") or [{"anywhere": True}]


TOOL = {"app": "workshop-mcp"}            # where run_shell runs, and so where stage 2b's lookup starts
AGENT = {"app.kubernetes.io/name": "workshop-agent"}
FEED = {"app.kubernetes.io/name": "weather-feed"}

print("== item 1: 443 leaves only through the egress waypoint, in the fixed set ==")
for who, labels in (("workshop-mcp", TOOL), ("workshop-agent", AGENT)):
    for label, pset in (("stage 2", STAGE2), ("fixed", FIXED), ("admin set", ADMIN)):
        bad = [r for r in rules_for(pset, labels) if internet_443(r)]
        check(f"{label}: {who} has no rule to the internet on 443", not bad, repr(bad))
for label, pset in (("fixed", FIXED), ("admin set", ADMIN)):
    check(f"{label}: the weather feed has no rule to the internet on 443", not any(
        internet_443(r) for r in rules_for(pset, FEED)))
    check(f"{label}: the egress waypoint may reach 443 (its AuthorizationPolicy admits only the two hosts)",
          any(internet_443(r) for r in rules_for(pset, WAYPOINT)))
    feed = pset.get("agent-allow-weather-feed-egress", {}).get("spec", {})
    check(f"{label}: the weather feed's own policy sends it to the waypoint on HBONE 15008 alone",
          feed.get("egress") == [{"to": [{"podSelector": {"matchLabels": WAYPOINT}}],
                                  "ports": [{"protocol": "TCP", "port": 15008}]}], repr(feed.get("egress")))
stage_feed = STAGE2.get("agent-allow-weather-feed-egress", {}).get("spec", {})
check("stage 2: the weather feed keeps its direct 443, the path the burn and community clusters run (question 1077)",
      stage_feed.get("egress") == [{"ports": [{"protocol": "TCP", "port": 443}]}], repr(stage_feed.get("egress")))

check("stage 2: the egress waypoint keeps its 443 allow, so the feed's Open-Meteo path answers while stage 2 holds the beacon",
      STAGE2.get("agent-allow-egress-waypoint", {}).get("spec") == FIXED.get("agent-allow-egress-waypoint", {}).get("spec")
      and any(internet_443(r) for r in rules_for(STAGE2, WAYPOINT)))

print("== item 1: stage 2 leaves DNS open, so stage 2b still shows the door ==")
peers = [p for r in rules_for(STAGE2, TOOL) for p in dns_peers(r)]
check("stage 2: workshop-mcp may reach kube-system on 53",
      {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}} in peers, repr(peers))
check("stage 2: and the VPC resolver, where agent-dns sends names outside the lab's zones",
      {"ipBlock": {"cidr": VPC_RESOLVER}} in peers, repr(peers))

print("== item 1: the fix narrows DNS to the locked resolver ==")
lock = LOCK.get("agent-allow-dns", {}).get("spec", {})
check("the fix's agent-allow-dns selects agent-dns alone", lock.get("podSelector") == {"matchLabels": RESOLVER})
check("and lets it reach kube-dns pods in kube-system on 53, nothing else",
      lock.get("egress") == [{"to": [KUBE_DNS_PEER], "ports": DNS_PORTS}], repr(lock.get("egress")))
# agent-allow-kagent-egress admits every port to namespace kagent (the controller and its postgres). No resolver runs
# there, so it is not a DNS path; it is named here so that a resolver added to kagent shows up as a decision.
KAGENT_PEER = {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kagent"}}}


def outside(labels: dict) -> list[dict]:
    return [p for r in rules_for(FIXED, labels) for p in dns_peers(r)
            if ("podSelector" not in p or p.get("namespaceSelector")) and p != KAGENT_PEER]


for who, labels in (("workshop-mcp", TOOL), ("workshop-agent", AGENT), ("weather-feed", FEED)):
    reach = outside(labels)
    check(f"fixed: {who} may reach no DNS server outside the namespace (kagent runs none)", not reach, repr(reach))
resolver_out = outside(RESOLVER)
check("fixed: agent-dns may reach kube-dns and nothing else outside the namespace",
      resolver_out == [KUBE_DNS_PEER], repr(resolver_out))
waypoint_out = outside(WAYPOINT)
check("fixed: the waypoint may reach kube-dns, for its ServiceEntry hosts, and nothing else outside the namespace",
      waypoint_out == [KUBE_DNS_PEER], repr(waypoint_out))
check("fixed: no rule anywhere names the VPC resolver",
      VPC_RESOLVER not in yaml.safe_dump([np["spec"] for np in FIXED.values()]))
check("the admin set's agent-allow-dns is the fix's, so an admin cluster is the fixed state",
      ADMIN.get("agent-allow-dns", {}).get("spec") == lock)
for name in ("agent-allow-weather-feed-egress", "agent-allow-egress-waypoint", "agent-egress-allowlist",
             "agent-allow-otel-egress", "agent-allow-kagent-egress", "agent-allow-intra-namespace"):
    check(f"the admin set's {name} is the fix's", ADMIN.get(name, {}).get("spec") == FIXED.get(name, {}).get("spec"))

print("== item 2: the waypoint's allowlist is exactly the weather feed's hosts ==")
feed_src = (AI / "weather_feed.py").read_text()
feed_hosts = {urllib.parse.urlsplit(u).hostname for u in re.findall(r'"(https://[^"]+)"', feed_src)}
check("weather_feed.py calls Open-Meteo's geocoding and forecast hosts",
      feed_hosts == {"geocoding-api.open-meteo.com", "api.open-meteo.com"}, repr(feed_hosts))
se = one(WAYPOINT_DOCS, "ServiceEntry", "open-meteo-egress")
check("the ServiceEntry names exactly those hosts, on TLS 443, and routes them through the waypoint",
      set(se.get("spec", {}).get("hosts") or []) == feed_hosts
      and (se.get("metadata", {}).get("labels") or {}).get("istio.io/use-waypoint") == "egress-waypoint"
      and se.get("spec", {}).get("ports") == [{"number": 443, "name": "https", "protocol": "TLS"}],
      repr(se.get("spec")))
ap = one(WAYPOINT_DOCS, "AuthorizationPolicy", "egress-waypoint-allowlist")
rules = ap.get("spec", {}).get("rules") or []
sni = [v for r in rules for w in r.get("when") or [] if w.get("key") == "connection.sni" for v in w.get("values") or []]
check("the waypoint's AuthorizationPolicy is an ALLOW that matches the TLS SNI, not operation.hosts",
      ap.get("spec", {}).get("action") == "ALLOW" and set(sni) == feed_hosts
      and not any("hosts" in (r.get("to") or [{}])[0].get("operation", {}) for r in rules), repr(ap.get("spec")))
check("the AuthorizationPolicy is attached to the egress waypoint Gateway",
      ap.get("spec", {}).get("targetRefs") == [{"group": "gateway.networking.k8s.io", "kind": "Gateway",
                                                  "name": "egress-waypoint"}])
gw = one(WAYPOINT_DOCS, "Gateway", "egress-waypoint")
check("the waypoint is a Gateway of the istio-waypoint class, listening for HBONE on 15008",
      gw.get("spec", {}).get("gatewayClassName") == "istio-waypoint"
      and gw.get("spec", {}).get("listeners") == [{"name": "mesh", "port": 15008, "protocol": "HBONE"}])

print("== item 3: Bedrock stays in-VPC, Pod Identity stays ==")
for label, pset in (("stage 2", STAGE2), ("fixed", FIXED), ("admin set", ADMIN)):
    allow = pset.get("agent-egress-allowlist", {}).get("spec", {})
    check(f"{label}: agent-egress-allowlist still covers the whole namespace", allow.get("podSelector") == {})
    rules = allow.get("egress") or []
    check(f"{label}: Bedrock's PrivateLink endpoint stays reachable on 10.0.0.0/16:443",
          {"to": [{"ipBlock": {"cidr": "10.0.0.0/16"}}], "ports": [{"protocol": "TCP", "port": 443}]} in rules)
    check(f"{label}: the Pod Identity agent stays reachable on 169.254.170.23:80",
          {"to": [{"ipBlock": {"cidr": "169.254.170.23/32"}}], "ports": [{"protocol": "TCP", "port": 80}]} in rules)
tf = (REPO / "infra/terraform/aws/network/main.tf").read_text()
endpoints = re.findall(r'resource "aws_vpc_endpoint" "(\w+)"', tf)
check("the VPC has one interface endpoint, bedrock_runtime, so the resolver needs one AWS name",
      endpoints == ["bedrock_runtime"], repr(endpoints))

print("== the resolver: the lab's zones one way, every other name another ==")
cm = one(DNS_DOCS, "ConfigMap", "agent-dns")
corefile = (cm.get("data") or {}).get("Corefile", "")
blocks = dict(re.findall(r"(?m)^(\S[^{\n]*?)\s*\{\n(.*?)^\}", corefile, re.S))
lab = "cluster.local:1053 bedrock-runtime.us-west-2.amazonaws.com:1053 open-meteo.com:1053"
check("there are two server blocks: the lab zones and the root", sorted(blocks) == sorted([lab, ".:1053"]),
      repr(sorted(blocks)))
check("the lab zones are the cluster names, Bedrock's endpoint and open-meteo.com, which the weather feed resolves (#861)",
      lab.split() == ["cluster.local:1053", "bedrock-runtime.us-west-2.amazonaws.com:1053", "open-meteo.com:1053"])
check("open-meteo.com names the weather feed's zone, so the feed resolves its two hosts under the lock",
      all(h.endswith("open-meteo.com") for h in feed_hosts))
check("the lab zones forward to the cluster DNS (the resolver's own resolv.conf)",
      re.search(r"(?m)^\s*forward \. /etc/resolv\.conf$", blocks.get(lab, "")) is not None)
check("every other name forwards to the VPC resolver alone",
      re.findall(r"(?m)^\s*forward (.*)$", blocks.get(".:1053", "")) == [". 169.254.169.253"])
check("the root block logs each name, so the room can see what was asked", "\n    log\n" in "\n" + blocks.get(".:1053", ""))
region = re.search(r'variable "region" \{[^}]*default\s*=\s*"([^"]+)"',
                   (REPO / "infra/terraform/aws/cluster/main.tf").read_text(), re.S)
check("the Bedrock zone is in the cluster's region", region is not None and f"bedrock-runtime.{region.group(1)}." in lab,
      region.group(1) if region else "no region default found")
svc = one(DNS_DOCS, "Service", "agent-dns")
check("the resolver's Service is pinned at 172.20.0.53, in the low static band of the service range",
      svc.get("spec", {}).get("clusterIP") == "172.20.0.53")
dep = one(DNS_DOCS, "Deployment", "agent-dns")
pod = dep.get("spec", {}).get("template", {})
check("the resolver pods carry the label the fix's policy selects", RESOLVER.items() <= pod["metadata"]["labels"].items())
check("the resolver keeps ClusterFirst, so /etc/resolv.conf is kube-dns", pod["spec"].get("dnsPolicy") == "ClusterFirst")
ctr = pod["spec"]["containers"][0]
check("the image is registry.k8s.io's CoreDNS, pinned by digest",
      re.match(r"registry\.k8s\.io/coredns/coredns:v[\d.]+@sha256:[0-9a-f]{64}$", ctr["image"]) is not None)
check("it has limits and both probes", bool(ctr.get("resources", {}).get("limits")) and "readinessProbe" in ctr
      and "livenessProbe" in ctr)

print("== every agent pod is pointed at the resolver ==")
mp = one(DNS_DOCS, "MutatingPolicy", "agent-dns-resolver")
check("the MutatingPolicy exists", bool(mp))
spec = mp.get("spec", {})
check("it matches pod CREATE in namespace agent", spec.get("matchConstraints", {}).get("resourceRules") ==
      [{"apiGroups": [""], "apiVersions": ["v1"], "operations": ["CREATE"], "resources": ["pods"]}]
      and spec["matchConstraints"]["namespaceSelector"]["matchExpressions"][0]["values"] == ["agent"])
expr = spec.get("mutations", [{}])[0].get("jsonPatch", {}).get("expression", "")
check("it sets the Service's address as the only nameserver", '["172.20.0.53"]' in expr and 'value: "None"' in expr)
skip = spec.get("matchConditions", [{}])[0].get("expression", "")
check("it skips agent-dns and the egress waypoint, and only those",
      "'agent-dns'" in skip and "'egress-waypoint'" in skip and "gateway.networking.k8s.io/gateway-name" in skip)
kyv = (REPO / "policies/kyverno/restrict-agent-spawned-workloads.yaml").read_text()
check("both skipped labels are on egressLabels, so the agent cannot wear one",
      "'agent-dns'" in kyv and "'gateway.networking.k8s.io/gateway-name': ['egress-waypoint']" in kyv)

print("== item 4: the waypoint is on the mesh profiles, which carry the Istio layer and its CRDs ==")
values = {p.stem.removeprefix("values-"): yaml.safe_load(p.read_text())["apps"]
          for p in (REPO / "gitops/bootstrap").glob("values-*.yaml")}
check("agent-dns is on attendee, admin, full and local-inference, and on no KubeCon or burn profile",
      sorted(p for p, apps in values.items() if "agent-dns" in apps) == ["admin", "attendee", "full", "local-inference"],
      repr(sorted(p for p, apps in values.items() if "agent-dns" in apps)))
MESH = ["admin", "attendee", "full", "kubecon-private", "local-inference"]
check("egress-waypoint is on the mesh profiles and on no other: burn and the community cluster carry no Istio (question 1077)",
      sorted(p for p, apps in values.items() if "egress-waypoint" in apps) == MESH,
      repr(sorted(p for p, apps in values.items() if "egress-waypoint" in apps)))
check("every profile that lists the waypoint lists istio and gateway-api, the layer and CRDs it needs",
      all({"istio", "gateway-api"} <= set(values[p]) for p in MESH))
check("no profile sets the retired egressProxy flag",
      not any("egressProxy" in (yaml.safe_load(p.read_text()) or {}) for p in (REPO / "gitops/bootstrap").glob("values-*.yaml")))
app = yaml.safe_load((REPO / "gitops/bootstrap/apps/egress-waypoint.yaml").read_text())
check("the egress-waypoint Application syncs gitops/egress-waypoint at the root's revision, into agent's objects",
      app["spec"]["source"]["path"] == "gitops/egress-waypoint"
      and app["spec"]["source"]["targetRevision"] == "{{ .Values.revision }}")
check("the Application is synced after istiod and ztunnel are up (wave -2 follows istio-mesh-config at -3)",
      app["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "-2")
check("the admin profile, which syncs the fixed set, also runs agent-dns, so its pods can resolve",
      "network-policies" in values["admin"] and "agent-dns" in values["admin"])
check("no profile syncs the fixed set without agent-dns",
      all("agent-dns" in apps for apps in values.values() if "network-policies" in apps))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All egress lock checks passed.")
