# ABOUTME: Live half of #381: requests every <service>-<cluster>.agenticburn.com host through the real apex
# ABOUTME: router and says which hop failed: the routes table, the console's Host fan-out, or the Service.
# SUITE: e2e
"""Needs kubectl, CONTEXT naming an attendee (or admin) cluster whose routes are published, and the public
internet. Every missing prerequisite is a failure with the reason, never a skip.

Why (#381). On 2026-09-08 none of the service URLs worked on the live pool, while the console, the lab and
the terminal did, and nothing could say which hop was at fault. A service host crosses three things before
it reaches its Service, and each one fails with a page that is recognisable:

  1. the apex router's routes table (fleet.sh routes, emit_service_hosts). No row: the router answers its
     own "no cluster here yet" page with 404.
  2. the console's nginx, which fans out on Host (console.conf). If the router stops passing Host, or the
     server_name does not match, the console's default server answers: the BurritoBot storefront.
  3. the in-cluster Service. The vhost matched but nothing answered: the "not running on this cluster" page.

This names the hop for each host, in that order, the order #381 asked the diagnosis to go in. Then it
proves the two with a login get past their front page: Grafana's data sources answer through it (that is
how a browser reaches Prometheus and Tempo, which are not published on their own), and Argo CD hands
out a session, which a server that is not running insecure behind the proxy cannot do.

Read-only: GETs, one Argo CD session POST, and kubectl get. The two passwords are read from the cluster
the same way the platform page tells a student to.

Usage: CONTEXT=<kube-context> python3 verify/test_service_hosts_live.py
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
FLEET = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
CONF = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")
CONTEXT = os.environ.get("CONTEXT", "")
TIMEOUT_S = 20
# The three pages a service host can land on instead of its service. Each is the marker of one hop.
APEX_UNKNOWN = "no cluster here yet"                       # apex-agenticburn site/unknown.html <title>
CONSOLE_DEFAULT = "BurritoBot — agenticburn"               # gitops/ai-layer/web/burritbot.html <title>
NOT_HERE = "That service is not running on this cluster"   # console.conf @wib_not_here
# Grafana data sources the console pages open in Explore (platform.html, links.html). tempo only where Tempo is.
DATASOURCES = ("prometheus", "tempo")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All live service-host checks passed.")


def kubectl(*args: str) -> subprocess.CompletedProcess:
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    return subprocess.run(["kubectl", "--context", CONTEXT, "--request-timeout=20s", *args],
                          capture_output=True, text=True)


def secret(ns: str, name: str, key: str) -> str:
    r = kubectl("-n", ns, "get", "secret", name, "-o", f"jsonpath={{.data.{key}}}")
    return base64.b64decode(r.stdout).decode() if r.returncode == 0 and r.stdout else ""


def fetch(url: str, *, auth: tuple[str, str] | None = None, data: bytes | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "wib-verify/381"})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if auth:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, f"{type(e).__name__}: {e}"


def hop(status: int, body: str, upstream: str) -> str:
    """Which hop stopped the request, or "" when it reached the service."""
    if status == 0:
        return f"no answer at all ({body}): DNS, the wildcard certificate or the router itself"
    if APEX_UNKNOWN in body:
        return "hop 1: the router has no row for this host (fleet.sh routes, then reload the apex table)"
    if CONSOLE_DEFAULT in body:
        return "hop 2: the console's default server answered, so Host was not passed or server_name missed"
    if NOT_HERE in body:
        return f"hop 3: the vhost matched but {upstream} did not answer"
    if status >= 400:
        return f"the service answered HTTP {status}"
    return ""


print("== prerequisites ==")
missing = []
if not shutil.which("kubectl"):
    missing.append("kubectl is not on PATH")
if not CONTEXT:
    missing.append("CONTEXT is not set: name the kube-context of the cluster whose hosts to probe")
if missing:
    for m in missing:
        check(m, False)
    finish()
m = re.search(r'^readonly WIB_SERVICE_HOSTS="([^"]+)"', FLEET, re.M)
labels = m.group(1).split() if m else []
check("fleet.sh names the service hosts it publishes", bool(labels))
# The domain part is whatever follows the label's `[a-z0-9-]+\.`: one domain until #651, both since. Reading
# only agenticburn\.com$ found no upstream at all once the patterns took the two-domain group.
upstreams = dict(re.findall(r'"~\^([a-z-]+)-\[a-z0-9-\]\+\\\.[^"]*\$"\s+http://([a-z0-9.-]+):\d+;', CONF))
check("console.conf names an upstream for each", set(upstreams) == set(labels), f"{sorted(upstreams)}")
r = kubectl("-n", "agent", "get", "configmap", "cluster-identity", "-o", "jsonpath={.data.public-host}")
host = r.stdout.strip()
check("the cluster records its public host (cluster-identity public-host)", bool(host),
      r.stderr.strip() or "empty: infra/datadog-cluster-identity.sh writes it at bootstrap")
if not host or not labels:
    finish()
print(f"  probing {host} through the router")

print("== the router passes Host to the console ==")
status, body = fetch(f"https://{host}/whoami")
check(f"https://{host}/whoami answers host={host}", status == 200 and body.strip() == f"host={host}",
      f"HTTP {status}: {body.strip()[:160]}")

print("== the roster-only pages are not served under the volume's dot entries ==")
# console-src is a ConfigMap volume, so kubelet's ..data symlink sits under the console's root. The router gates
# /brief and /kubecon by exact path only, so a 200 here hands the presenter pages to any attendee (#650).
for page in ("brief", "kubecon"):
    status, body = fetch(f"https://{host}/..data/{page}.html")
    check(f"https://{host}/..data/{page}.html is a 404", status == 404, f"HTTP {status}: {body.strip()[:160]}")

print("== every service host reaches its Service ==")
for label in labels:
    upstream = upstreams.get(label, "")
    svc, _, rest = upstream.partition(".")
    ns = rest.split(".")[0]
    r = kubectl("-n", ns, "get", "service", svc, "-o", "name")
    check(f"{label}: Service {ns}/{svc} exists", r.returncode == 0, r.stderr.strip()[:160])
    status, body = fetch(f"https://{label}-{host}/")
    why = hop(status, body, f"{ns}/{svc}")
    check(f"{label}: https://{label}-{host}/ reaches it", not why, why)

print("== Grafana works past its front page, and fronts Prometheus and Tempo ==")
status, body = fetch(f"https://grafana-{host}/api/health")
check("Grafana's /api/health answers through its hostname", status == 200 and '"database"' in body,
      f"HTTP {status}: {hop(status, body, 'monitoring/prometheus-grafana') or body[:160]}")
gpw = secret("monitoring", "prometheus-grafana", "admin-password")
check("the Grafana admin password is readable, as the platform page tells a student", bool(gpw))
# Grafana builds absolute links (Share, alert links) from root_url, which the frontend gets as appUrl. With the
# old ALB Ingress it was http://grafana.agenticburn.com:3000/ on every cluster (#493).
status, body = fetch(f"https://grafana-{host}/api/frontend/settings", auth=("admin", gpw))
try:
    app_url = json.loads(body).get("appUrl")
except ValueError:
    app_url = None
check(f"Grafana's root_url is its own hostname, https://grafana-{host}/", app_url == f"https://grafana-{host}/",
      f"HTTP {status}: appUrl={app_url!r}" if app_url is not None else f"HTTP {status}: {body[:160]}")
r = kubectl("-n", "monitoring", "get", "ingress", "-o", "jsonpath={.items[*].metadata.name}")
check("Grafana has no Ingress of its own (no ALB for it)", r.returncode == 0 and "grafana" not in r.stdout,
      r.stderr.strip()[:160] or r.stdout)
# The party apps had ALB Ingresses at a fixed <app>.agenticburn.com in the same group until #554.
r = kubectl("-n", "apps", "get", "ingress", "-o", "jsonpath={.items[*].metadata.name}")
check("the party apps have no Ingress (no ALB for them)", r.returncode == 0 and not r.stdout.strip(),
      r.stderr.strip()[:160] or r.stdout)
# The attendee profile installs no Tempo, and its data source ships with the tempo Application (#475), so on an
# attendee cluster the right answer for uid tempo is "no such data source", not a healthy one.
r = kubectl("-n", "argocd", "get", "applications.argoproj.io", "-o", "jsonpath={.items[*].metadata.name}")
argo_apps = set(r.stdout.split())
# One root on every profile since #609, lab-bootstrap, labelled with the profile it was applied with.
old_roots = argo_apps & {"app-of-apps", "app-of-apps-attendee", "app-of-apps-admin", "app-of-apps-burn"}
check("the root is lab-bootstrap and no pre-#609 root is left", "lab-bootstrap" in argo_apps and not old_roots,
      r.stderr.strip()[:160] or f"{sorted(old_roots)}")
p = kubectl("-n", "argocd", "get", "application", "lab-bootstrap", "-o",
            "jsonpath={.metadata.labels.lab-platform/profile}")
profile = p.stdout.strip()
check("lab-bootstrap names this cluster's profile", profile in {"attendee", "admin", "full", "burn"},
      p.stderr.strip()[:160] or repr(profile))
attendee = profile == "attendee"
check("the tempo Application is present on admin and full, absent on attendee", ("tempo" in argo_apps) != attendee,
      f"profile={profile} tempo={'tempo' in argo_apps}")
for uid in DATASOURCES:
    status, body = fetch(f"https://grafana-{host}/api/datasources/uid/{uid}/health", auth=("admin", gpw))
    if uid == "tempo" and attendee:
        check("attendee: Grafana has no tempo data source, since the cluster has no Tempo", status == 404,
              f"HTTP {status}: {body[:200]}")
        continue
    try:
        ok = json.loads(body).get("status") == "OK"
    except ValueError:
        ok = False
    check(f"Grafana's {uid} data source is healthy, so its Explore link has something behind it",
          status == 200 and ok, f"HTTP {status}: {body[:200]}")

print("== Argo CD works past its front page ==")
status, body = fetch(f"https://argocd-{host}/api/version")
check("Argo CD's /api/version answers through its hostname", status == 200 and '"Version"' in body,
      f"HTTP {status}: {hop(status, body, 'argocd/argocd-server') or body[:160]}")
apw = secret("argocd", "argocd-initial-admin-secret", "password")
check("the Argo CD admin password is readable, as the platform page tells a student", bool(apw))
status, body = fetch(f"https://argocd-{host}/api/v1/session",
                     data=json.dumps({"username": "admin", "password": apw}).encode())
check("Argo CD hands out a session through its hostname (server.insecure behind the proxy)",
      status == 200 and '"token"' in body, f"HTTP {status}: {body[:160]}")

finish()
