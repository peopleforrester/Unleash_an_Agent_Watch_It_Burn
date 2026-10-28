# ABOUTME: Every service address the console pages hand out must be one a browser can open: a published
# ABOUTME: <service>-<cluster> host the router and the console's nginx both know, or Grafana Explore (#381).
"""Why (#381). Michael, 2026-09-08, on the live pool: the Grafana, Loki, Argo CD and Backstage URLs did not
work. Three of those failures were in what these pages handed out, not in the routing:

- The lab's Links tab sent `echo open https://grafana-<your console host>.agenticburn.com` to the terminal,
  and the same for Argo CD. Bash reads `<your` as an input redirect, so the student got
  "your: No such file or directory" instead of an address.
- Loki, Prometheus and Tempo were offered as a `kubectl port-forward`. In a browser terminal that listens
  inside the terminal pod, so the localhost URL it promises never opens on the student's laptop. Those
  three have no login and are deliberately not published (#233); Grafana is how a browser reaches them.
- Backstage has no host because nothing deploys it yet (#244, which adds backstage-<cluster>).

Three lists name the service hosts and must agree: fleet.sh WIB_SERVICE_HOSTS (the routes table rows),
the console's nginx map, and its server_name. A label in one and not the others is a host that 404s at the
router or lands on the BurritoBot storefront. The live half is test_service_hosts_live.py.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
FLEET = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
CONF = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")
WEB = REPO / "gitops/ai-layer/web"
LINKS = (WEB / "links.html").read_text(encoding="utf-8")
PLATFORM = (WEB / "platform.html").read_text(encoding="utf-8")
PROM_APP = yaml.safe_load((REPO / "gitops/bootstrap/apps/prometheus.yaml").read_text(encoding="utf-8"))

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== the three lists of service hosts agree ==")
m = re.search(r'^readonly WIB_SERVICE_HOSTS="([^"]+)"', FLEET, re.M)
check("fleet.sh declares WIB_SERVICE_HOSTS", m is not None)
routed = set(m.group(1).split()) if m else set()
DOMS = r"\\\.\(\?:agenticburn\\\.com\|burritobot\\\.co\)\$"  # both domains are served (#651)
mapped = set(re.findall(r'"~\^([a-z-]+)-\[a-z0-9-\]\+' + DOMS + '"', CONF))
sn = re.search(r"server_name ~\^\(([a-z|-]+)\)-\[a-z0-9-\]\+" + DOMS + ";", CONF)
named = set(sn.group(1).split("|")) if sn else set()
check("the console's nginx map routes exactly the hosts fleet.sh publishes", mapped == routed,
      f"map={sorted(mapped)} fleet={sorted(routed)}")
check("its server_name accepts exactly those hosts", named == routed, f"server_name={sorted(named)}")
check("Grafana and Argo CD are among them", {"grafana", "argocd"} <= routed)
# Prometheus and Tempo have no login of their own (#233). Publishing one would hand the internet an
# unauthenticated query API; the pages reach them through Grafana instead.
check("Prometheus and Tempo are not published on their own", not routed & {"prometheus", "tempo"})

print("== the console pages link only to hosts that exist ==")
page_svcs = set(re.findall(r'data-svc="([a-z-]+)"', PLATFORM))
link_svcs = set(re.findall(r"\bsvc:'([a-z-]+)'", LINKS))
check("platform.html links some service hosts", bool(page_svcs))
check("links.html links some service hosts", bool(link_svcs))
check("every platform.html service link is a published host", page_svcs <= routed, f"{sorted(page_svcs - routed)}")
check("every links.html service card is a published host", link_svcs <= routed, f"{sorted(link_svcs - routed)}")
check("links.html gives Grafana and Argo CD a real address", {"grafana", "argocd"} <= link_svcs)

print("== no address is a shell redirect or a port-forward ==")
# Every command a card can send to the terminal. JS string literals, single- or double-quoted.
cmds = [re.sub(r"\\(.)", r"\1", lit[1:-1]) for lit in
        re.findall(r"\b(?:cmd|pw):\s*('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")", LINKS)]
check("links.html still has terminal commands to check", len(cmds) > 5, f"{len(cmds)} found")
for c in cmds:
    bare = re.sub(r"'[^']*'", "", c)   # shell single quotes make < and > literal
    check(f"no unquoted < or > in: {c[:70]}", "<" not in bare and ">" not in bare)
check("no command carries a <placeholder> for the student to fill in", not any("<your" in c for c in cmds))
for name, text in (("links.html", LINKS), ("platform.html", PLATFORM)):
    check(f"{name} offers no port-forward as a way in", re.search(r"port-forward svc/", text) is None)
# The fallback when the page is opened off its agenticburn.com name: the terminal's own public host.
check("links.html quotes the address it prints", "echo '\" + u + \"'\"" in LINKS)

print("== the stores open in Grafana Explore, on data sources Grafana has ==")
grafana = PROM_APP["spec"]["source"]["helm"]["valuesObject"]["grafana"]
uids = {d["uid"] for d in grafana.get("additionalDataSources", [])}
# kube-prometheus-stack provisions its own Prometheus data source with uid "prometheus" unless
# grafana.sidecar.datasources.uid overrides it; Tempo's tracesToMetrics already relies on that uid.
ds_sidecar = grafana.get("sidecar", {}).get("datasources", {})
if ds_sidecar.get("enabled") and ds_sidecar.get("uid", "prometheus") == "prometheus":
    uids.add("prometheus")
# Tempo's data source ships with the tempo Application (gitops/tempo/), on the admin and full profiles only
# (#475): on an attendee cluster the Tempo link has nothing behind it, and the pages say so.
for f in sorted((REPO / "gitops/tempo").glob("*.yaml")):
    cm = yaml.safe_load(f.read_text(encoding="utf-8"))
    if ds_sidecar.get("enabled") and (cm.get("metadata", {}).get("labels") or {}).get("grafana_datasource") == "1":
        uids |= {d["uid"] for v in cm["data"].values() for d in (yaml.safe_load(v) or {}).get("datasources", [])}
page_ds = set(re.findall(r'data-explore="([a-z]+)"', PLATFORM))
link_ds = set(re.findall(r"\bexplore:'([a-z]+)'", LINKS))
want = {"prometheus", "tempo"}
check("platform.html opens Prometheus and Tempo in Explore", page_ds == want, f"{sorted(page_ds)}")
check("links.html opens Prometheus and Tempo in Explore", link_ds == want, f"{sorted(link_ds)}")
check("each is a data source uid Grafana is provisioned with", want <= uids, f"uids={sorted(uids)}")
print("== the pages are true on an attendee cluster, which has no Tempo and no Talon (#475) ==")
for name, text in (("links.html", LINKS), ("platform.html", PLATFORM)):
    tempo_row = re.search(r"(?s)Tempo<small>.*?</tr>", text) if name == "platform.html" else re.search(r"(?s)\{nm:'Tempo'.*?\}", text)
    check(f"{name} says Tempo is on instructor clusters only", bool(tempo_row) and "instructor clusters only" in tempo_row.group(0))
    check(f"{name} no longer says Talon reacts", "Talon reacts" not in text)
    check(f"{name} says Talon runs on instructor clusters only",
          re.search(r"Falco Talon, which acts on an alert, runs on instructor clusters only", text) is not None)
    # Falco runs in `security`; `falco` holds only Talon, and on an attendee cluster it does not exist at all.
    check(f"{name} reads Falco's logs where Falco runs (ns security)",
          "kubectl -n security logs -l app.kubernetes.io/name=falco" in text and "kubectl -n falco logs" not in text)
# Loki is gone (#474): the pod logs, the #190 audit trail among them, are read in Datadog. A data source or
# a trace-to-logs link left pointing at it is a Grafana pane that errors on open.
check("Grafana has no data source or link to the removed Loki",
      "loki" not in uids and "loki" not in json.dumps(grafana).lower(), f"uids={sorted(uids)}")
for name, text in (("links.html", LINKS), ("platform.html", PLATFORM)):
    check(f"{name} builds the Explore URL Grafana 10+ reads (schemaVersion 1, panes)",
          "explore?schemaVersion=1&orgId=1&panes=" in text and "encodeURIComponent(JSON.stringify(" in text)
    check(f"{name} derives the host from the address bar", "location.hostname" in text)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All service-link checks passed.")
