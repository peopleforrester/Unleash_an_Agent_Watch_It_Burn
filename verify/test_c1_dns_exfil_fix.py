# ABOUTME: Offline cover for the C1 stage-2b fix config (#727): the locked resolver forwards only the lab's own
# ABOUTME: zones so the exfil collector is closed, and the forced egress proxy admits only the Open-Meteo hosts.
"""Offline half of the fix beat, at the altitude the repo uses for the attack half (test_c1_dns_exfil.py).

The fix is config: a locked CoreDNS Corefile (floor C), an Istio ambient egress waypoint with a hostname
allowlist (option B, chosen by question 1009 on #724), and the NetworkPolicy deltas that make the waypoint
the only public-443 path. This test reads those committed files and proves the invariants that make the fix
hold, without a cluster. The live half, that with the fix applied the DNS collector records nothing new for
the same stage-2b request while Bedrock and in-cluster resolution still work, needs a cluster and the DNS
collector and is owed under verify/run-e2e.sh, tracked by #728.

What it proves without a cluster:
  - floor C closes the relay: the locked Corefile serves in-cluster names, forwards exactly the lab's two
    external zones (amazonaws.com, open-meteo.com), and carries no catch-all `forward .`, so the exfil
    collector's zone under agenticburn.com finds no upstream and never leaves the cluster;
  - the collector zone dns-exfil.py sends to is forwarded by nothing in the fix;
  - option B admits only the hosts C7's weather feed actually uses: the ServiceEntry and the waypoint's
    AuthorizationPolicy name exactly geocoding-api.open-meteo.com and api.open-meteo.com, read from
    weather_feed.py so the allowlist cannot drift from the code;
  - the fix keeps the stage-2 L3/L4 egress allowlist intact: it defines no agent-egress-allowlist and no
    agent-allow-dns of its own, so those stage-2 objects stand, and the policies/network-policies files
    still carry Bedrock's in-VPC allow;
  - the waypoint is the one workload granted a public 443, and the weather feed's direct public door is shut.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
FIX = REPO / "challenges/c1-exfil-s3/fix"
WEATHER = REPO / "gitops/ai-layer/weather_feed.py"
STAGE2_ALLOWLIST = REPO / "policies/network-policies/per-namespace/agent-egress-allowlist.yaml"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f": {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def docs(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


# The hosts the weather feed actually reaches, read from the code so the allowlist owns its inputs.
WEATHER_SRC = WEATHER.read_text(encoding="utf-8")
WEATHER_HOSTS = set(re.findall(r"https://([a-z0-9.-]+\.open-meteo\.com)/", WEATHER_SRC))
# The collector zone the attack sends to (test_c1_dns_exfil.py drives dns-exfil.py with this), under which
# label-encoded names leave. The fix must forward nothing under it.
COLLECTOR_ZONE = "dns.agenticburn.com"
COLLECTOR_APEX = "agenticburn.com"


print("== the test owns its inputs ==")
check("weather_feed.py names its two Open-Meteo hosts, so the allowlist can be checked against them",
      WEATHER_HOSTS == {"geocoding-api.open-meteo.com", "api.open-meteo.com"}, str(WEATHER_HOSTS))


# ---- Floor C: the locked CoreDNS Corefile ----------------------------------------------------------
print("== floor C: the locked resolver forwards only the lab's zones, and nothing else leaves ==")
rl = docs(FIX / "resolver-lockdown.yaml")
cm = next((d for d in rl if d.get("kind") == "ConfigMap"), None)
check("resolver-lockdown.yaml is the kube-system coredns ConfigMap with a Corefile",
      bool(cm) and cm["metadata"]["name"] == "coredns"
      and cm["metadata"]["namespace"] == "kube-system" and "Corefile" in (cm.get("data") or {}),
      str(cm.get("metadata") if cm else None))

corefile = (cm or {}).get("data", {}).get("Corefile", "")


def top_level_blocks(text: str) -> dict[str, str]:
    """Map each top-level server block's zone label to its body text."""
    blocks: dict[str, str] = {}
    depth = 0
    header = None
    body: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if depth == 0 and stripped.endswith("{"):
            header = stripped[:-1].strip()
            body = []
            depth = 1
            continue
        if depth >= 1:
            depth += stripped.count("{") - stripped.count("}")
            if depth == 0 and header is not None:
                # zone label is the token before :53 (e.g. ".:53" -> ".", "amazonaws.com:53" -> "amazonaws.com")
                zone = header.split(":", 1)[0].strip()
                blocks[zone] = "\n".join(body)
                header = None
            else:
                body.append(line)
    return blocks


blocks = top_level_blocks(corefile)
check("the Corefile has a catch-all `.` block and blocks for amazonaws.com and open-meteo.com",
      {".", "amazonaws.com", "open-meteo.com"} <= set(blocks), str(sorted(blocks)))
check("the `.` block serves in-cluster names through the kubernetes plugin (cluster.local)",
      "kubernetes cluster.local" in blocks.get(".", ""), "no kubernetes plugin in the . block")
check("the `.` block carries NO catch-all forward, so unlisted names get no upstream",
      "forward" not in blocks.get(".", ""), "a forward directive is still in the . block")
check("amazonaws.com and open-meteo.com each forward (so Bedrock and the weather host resolve)",
      "forward" in blocks.get("amazonaws.com", "") and "forward" in blocks.get("open-meteo.com", ""),
      "a needed zone does not forward")

# The set of zones that forward to an upstream must be exactly the lab's two external zones.
forwarding_zones = {z for z, b in blocks.items() if "forward" in b}
check("exactly amazonaws.com and open-meteo.com forward upstream, nothing more",
      forwarding_zones == {"amazonaws.com", "open-meteo.com"}, str(sorted(forwarding_zones)))
check("the exfil collector zone is served or forwarded by nothing in the Corefile",
      COLLECTOR_APEX not in corefile and COLLECTOR_ZONE not in corefile,
      "the Corefile names the collector zone")


# ---- Option B: the forced egress proxy -------------------------------------------------------------
print("== option B: the egress waypoint admits only the Open-Meteo hosts ==")
wp = docs(FIX / "egress-waypoint.yaml")
gw = next((d for d in wp if d.get("kind") == "Gateway"), None)
check("an istio-waypoint Gateway named egress-waypoint is in the agent namespace",
      bool(gw) and gw["spec"].get("gatewayClassName") == "istio-waypoint"
      and gw["metadata"]["name"] == "egress-waypoint" and gw["metadata"]["namespace"] == "agent",
      str(gw.get("spec") if gw else None))

se = next((d for d in wp if d.get("kind") == "ServiceEntry"), None)
se_hosts = set((se or {}).get("spec", {}).get("hosts", []))
check("the ServiceEntry lists exactly the Open-Meteo hosts the weather feed uses", se_hosts == WEATHER_HOSTS,
      str(sorted(se_hosts)))
check("the ServiceEntry routes through the waypoint (istio.io/use-waypoint label)",
      (se or {}).get("metadata", {}).get("labels", {}).get("istio.io/use-waypoint") == "egress-waypoint",
      str((se or {}).get("metadata", {}).get("labels")))
check("the ServiceEntry is external and TLS on 443",
      (se or {}).get("spec", {}).get("location") == "MESH_EXTERNAL"
      and any(p.get("number") == 443 for p in (se or {}).get("spec", {}).get("ports", [])), str(se))

ap = next((d for d in wp if d.get("kind") == "AuthorizationPolicy"), None)
check("the AuthorizationPolicy is an ALLOW targeting the egress-waypoint Gateway",
      bool(ap) and ap["spec"].get("action") == "ALLOW"
      and any(r.get("name") == "egress-waypoint" and r.get("kind") == "Gateway"
              for r in ap["spec"].get("targetRefs", [])), str(ap.get("spec") if ap else None))
ap_hosts = {h for rule in (ap or {}).get("spec", {}).get("rules", [])
            for to in rule.get("to", []) for h in to.get("operation", {}).get("hosts", [])}
check("the AuthorizationPolicy admits exactly the Open-Meteo hosts, nothing else",
      ap_hosts == WEATHER_HOSTS, str(sorted(ap_hosts)))
check("neither the ServiceEntry nor the allowlist names the exfil collector zone",
      not any(COLLECTOR_APEX in h for h in se_hosts | ap_hosts), str(sorted(se_hosts | ap_hosts)))


# ---- The NetworkPolicy deltas ----------------------------------------------------------------------
print("== the deltas force the waypoint and leave the stage-2 allowlist intact ==")
nps = {d["metadata"]["name"]: d for d in docs(FIX / "agent-egress-fqdn.yaml") if d.get("kind") == "NetworkPolicy"}
check("the fix touches only the weather-feed companion and the new waypoint policy",
      set(nps) == {"agent-allow-weather-feed-egress", "agent-allow-egress-waypoint"}, str(sorted(nps)))
check("the fix defines NO agent-egress-allowlist and NO agent-allow-dns, so the stage-2 objects stand",
      "agent-egress-allowlist" not in nps and "agent-allow-dns" not in nps, str(sorted(nps)))

wf = nps.get("agent-allow-weather-feed-egress", {})
check("the weather feed's direct public egress is shut (its egress rule set is empty)",
      wf.get("spec", {}).get("podSelector", {}).get("matchLabels", {}).get("app.kubernetes.io/name") == "weather-feed"
      and wf.get("spec", {}).get("egress", "unset") == [], str(wf.get("spec", {}).get("egress")))

wpn = nps.get("agent-allow-egress-waypoint", {})
sel = wpn.get("spec", {}).get("podSelector", {}).get("matchLabels", {})
check("the waypoint pod is the one workload granted a public 443",
      sel.get("gateway.networking.k8s.io/gateway-name") == "egress-waypoint"
      and any(p.get("port") == 443 for rule in wpn.get("spec", {}).get("egress", [])
              for p in rule.get("ports", [])), str(wpn.get("spec", {}).get("egress")))
check("the waypoint may resolve names through the locked resolver (DNS to kube-system)",
      any(p.get("port") == 53 for rule in wpn.get("spec", {}).get("egress", []) for p in rule.get("ports", [])),
      "no DNS allow for the waypoint")

# The stage-2 L3/L4 allowlist file itself still carries Bedrock's in-VPC allow, unchanged by the fix.
stage2 = next((d for d in docs(STAGE2_ALLOWLIST) if d.get("kind") == "NetworkPolicy"), {})
cidrs = {peer["ipBlock"]["cidr"] for rule in stage2.get("spec", {}).get("egress", [])
         for peer in rule.get("to", []) if "ipBlock" in peer}
check("the stage-2 allowlist still permits Bedrock in-VPC (10.0.0.0/16) and is untouched by the fix",
      "10.0.0.0/16" in cidrs and stage2.get("metadata", {}).get("name") == "agent-egress-allowlist", str(cidrs))


print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All C1 stage-2b fix config checks passed.")
