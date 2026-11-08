# ABOUTME: Pins the weather feed (#642, #861): C7's get_weather reads real conditions from an in-namespace service
# ABOUTME: whose only way out is the egress waypoint, and only the agent's guard keeps its label.
"""Offline checks for #642.

Whitney asked for the weather to be real. The agent namespace is default-deny egress once the network layer
is on, and C1's lesson depends on that staying true. So one small pod, weather-feed, fetches from Open-Meteo,
and get_weather asks it in-cluster. Since #861 the feed is enrolled in the Istio ambient mesh and its only way out is the
egress waypoint, which admits the two Open-Meteo hosts by TLS SNI. Its egress allow is its own NetworkPolicy, shipped with
the platform and in the C1 fix a student applies, and its label is on the Kyverno list that stops the agent minting a pod
that borrows that egress.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
RES_TEXT = (AI / "resources.yaml").read_text()
RES = [d for d in yaml.safe_load_all(RES_TEXT) if isinstance(d, dict)]
KUST = yaml.safe_load((AI / "kustomization.yaml").read_text())
SERVER = (AI / "server.py").read_text()
KYV = (REPO / "policies/kyverno/restrict-agent-spawned-workloads.yaml").read_text()
NP_FILE = REPO / "policies/network-policies/per-namespace/agent-allow-weather-feed-egress.yaml"
LABEL = {"app.kubernetes.io/name": "weather-feed"}

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def one(kind: str, name: str) -> dict:
    found = [d for d in RES if d.get("kind") == kind and d["metadata"]["name"] == name]
    return found[0] if len(found) == 1 else {}


print("== the feed runs in the agent namespace from its own source ==")
dep = one("Deployment", "weather-feed")
pod = dep.get("spec", {}).get("template", {})
check("a weather-feed Deployment exists", bool(dep))
check("its pods carry the label the egress policy selects",
      LABEL.items() <= (pod.get("metadata", {}).get("labels") or {}).items())
c = (pod.get("spec", {}).get("containers") or [{}])[0]
check("it has resource limits (the Enforce floor denies it otherwise)", bool((c.get("resources") or {}).get("limits")))
check("it uses the pinned workshop-mcp image, already on the registry allow-list",
      re.match(r"ghcr\.io/peopleforrester/watch-it-burn:workshop-mcp-mcp-1\.29\.1@sha256:[0-9a-f]{64}$", c.get("image", "")) is not None)
check("it runs weather_feed.py from a generated ConfigMap",
      c.get("command") == ["python", "/app/weather_feed.py"] and
      any(g.get("name") == "weather-feed-src" and "weather_feed.py" in g.get("files", []) for g in KUST["configMapGenerator"]))
FEED = (AI / "weather_feed.py").read_text()
# A Service named weather-feed makes Kubernetes inject WEATHER_FEED_PORT=tcp://<ip>:8080; the first rollout read
# it as the listen port and crashed (2026-10-28).
check("the feed reads no WEATHER_FEED_* variable, which Kubernetes service links would set",
      "WEATHER_FEED_" not in FEED.replace("# Not WEATHER_FEED_*", "").replace("WEATHER_FEED_PORT=tcp", ""))
check("and its pod turns service links off", pod.get("spec", {}).get("enableServiceLinks") is False)
svc = one("Service", "weather-feed")
check("a weather-feed Service on 8080", svc.get("spec", {}).get("ports", [{}])[0].get("port") == 8080
      and svc.get("spec", {}).get("selector") == LABEL)

print("== the feed is enrolled, and its only way out is the egress waypoint (#861) ==")
check("the feed's pods are enrolled in the ambient mesh, so ztunnel steers its Open-Meteo connections to the waypoint",
      (pod.get("metadata", {}).get("labels") or {}).get("istio.io/dataplane-mode") == "ambient")
np = yaml.safe_load(NP_FILE.read_text()) if NP_FILE.exists() else {}
check("the shipped policy exists", bool(np))
check("it selects only the feed", np.get("spec", {}).get("podSelector", {}).get("matchLabels") == LABEL)
egress = np.get("spec", {}).get("egress") or []
WAYPOINT = {"podSelector": {"matchLabels": {"gateway.networking.k8s.io/gateway-name": "egress-waypoint"}}}
check("its one rule is HBONE 15008 to the egress waypoint, with no 443 to anywhere",
      egress == [{"to": [WAYPOINT], "ports": [{"protocol": "TCP", "port": 15008}]}], repr(egress))
fixes = one("ConfigMap", "challenge-fixes").get("data", {})
stage2 = [d for d in yaml.safe_load_all(fixes.get("c1-network-policy.yaml", "")) if d]
stage2_feed = [d for d in stage2 if d["metadata"]["name"] == "agent-allow-weather-feed-egress"]
check("stage 2 keeps the feed's direct 443, the path the burn and community clusters run (question 1077)",
      len(stage2_feed) == 1 and stage2_feed[0]["spec"]["egress"] == [{"ports": [{"protocol": "TCP", "port": 443}]}])
lock = [d for d in yaml.safe_load_all(fixes.get("c1-dns-lock.yaml", "")) if d]
embedded = [d for d in lock if d["metadata"]["name"] == "agent-allow-weather-feed-egress"]
check("the C1 fix a student applies carries the same policy, so their lock-down keeps the weather",
      len(embedded) == 1 and embedded[0]["spec"] == np.get("spec"))

print("== the agent cannot mint a pod that borrows that egress ==")
m = re.search(r"name: egressLabels\s*\n\s*expression: \"(.*)\"", KYV)
check("egressLabels lists weather-feed", m is not None and "'weather-feed'" in m.group(1))
check("the refusal names it", "app.kubernetes.io/name=weather-feed" in KYV)

print("== get_weather asks the feed, and says so when it cannot ==")
check("get_weather takes a city", re.search(r"def get_weather\(city: str = \"Salt Lake City\"\)", SERVER) is not None)
check("it calls the in-cluster feed by default",
      'os.environ.get("WEATHER_FEED_URL", "http://weather-feed:8080")' in SERVER and '/current?' in SERVER)
check("no fixed reading is left", "21C, sunny" not in SERVER)
check("a failed lookup is reported as failed, not replaced by a made-up reading", "Weather lookup failed" in SERVER)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All weather feed checks passed.")
