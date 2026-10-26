# ABOUTME: Grafana has no Ingress of its own and knows its own address: root_url is this cluster's
# ABOUTME: grafana-<public-host>, read from cluster-identity, the host the console's nginx serves it on (#493).
"""Why (#493). After #233 Grafana is reached at grafana-<cluster>.agenticburn.com, through the apex router and
the console LB. The chart's ALB Ingress stayed behind, claiming grafana.agenticburn.com on every cluster:
a host routes.map has no row for, so the router answered it 404. It cost an internet-facing ALB per cluster,
the access harvester read its host and would hand it out, and the chart derives server.domain from the first
Ingress host, so Grafana believed it lived at http://grafana.agenticburn.com:3000/ and every absolute link it
built (Share, alert links) pointed there. #233 asked for root_url per host and the build shipped without it.

The live half is test_service_hosts_live.py, which reads Grafana's appUrl through its hostname.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
PROM_APP = yaml.safe_load((REPO / "gitops/bootstrap/apps/prometheus.yaml").read_text(encoding="utf-8"))
IDENTITY = (REPO / "infra/datadog-cluster-identity.sh").read_text(encoding="utf-8")
DEPLOY = (REPO / "infra/deploy-full-idp.sh").read_text(encoding="utf-8")
CONF = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


grafana = PROM_APP["spec"]["source"]["helm"]["valuesObject"]["grafana"]

print("== Grafana has no Ingress of its own ==")
ingress = grafana.get("ingress", {})
check("the chart's Grafana Ingress is disabled", ingress.get("enabled") is False, f"ingress={ingress}")
check("and names no host for the chart to derive server.domain from", not ingress.get("hosts"))
# Parsed values, not text: the comment that says why the Ingress went is allowed to name the old host.
claimed = []
for p in sorted((REPO / "gitops").rglob("*.yaml")):
    text = p.read_text(encoding="utf-8")
    if "grafana.agenticburn.com" in text and "grafana.agenticburn.com" in repr(list(yaml.safe_load_all(text))):
        claimed.append(str(p.relative_to(REPO)))
check("nothing in gitops/ claims the fixed host grafana.agenticburn.com", not claimed, f"{claimed}")
check("the console's nginx serves grafana-<cluster> instead",
      '"~^grafana-[a-z0-9-]+\\.agenticburn\\.com$"' in CONF and "prometheus-grafana.monitoring" in CONF)

print("== root_url is this cluster's grafana-<public-host> ==")
server = (grafana.get("grafana.ini") or {}).get("server") or {}
check("root_url is https://grafana-<public-host>/, expanded by Grafana from WIB_PUBLIC_HOST",
      server.get("root_url") == "https://grafana-$__env{WIB_PUBLIC_HOST}/", f"root_url={server.get('root_url')!r}")
check("domain is grafana-<public-host>, overriding the chart's Ingress-derived default",
      server.get("domain") == "grafana-$__env{WIB_PUBLIC_HOST}", f"domain={server.get('domain')!r}")
check("nothing pins the old address in root_url or domain",
      "grafana.agenticburn.com" not in f"{server.get('root_url')}{server.get('domain')}")
env = (grafana.get("envValueFrom") or {}).get("WIB_PUBLIC_HOST") or {}
ref = env.get("configMapKeyRef") or {}
check("WIB_PUBLIC_HOST comes from the cluster-identity ConfigMap's public-host key",
      ref.get("name") == "cluster-identity" and ref.get("key") == "public-host", f"{env}")
check("and is optional, so a cluster without the ConfigMap still starts Grafana", ref.get("optional") is True)
# Grafana's chart deploys into the Application's destination namespace; the ConfigMap must exist there.
dest_ns = PROM_APP["spec"]["destination"]["namespace"]
m = re.search(r'^readonly NAMESPACES="([^"]+)"', IDENTITY, re.M)
check(f"datadog-cluster-identity.sh writes cluster-identity into Grafana's namespace ({dest_ns})",
      bool(m) and dest_ns in m.group(1).split(), f"NAMESPACES={m.group(1) if m else None!r}")
check("and writes the public-host key", "--from-literal=public-host=" in IDENTITY)
# Grafana reads env once, at pod start: the identity must already be there when Argo CD first starts it.
ident_at = DEPLOY.find("datadog-cluster-identity.sh")
root_at = DEPLOY.find("  name: lab-bootstrap\n")
check("deploy-full-idp.sh writes the identity before it applies the lab-bootstrap root",
      0 <= ident_at < root_at, f"identity at {ident_at}, lab-bootstrap at {root_at}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All Grafana host checks passed.")
