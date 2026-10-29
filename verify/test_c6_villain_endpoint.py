# ABOUTME: Holds C6's endpoint together (#664): the Joker image serves a page, a Service selects the pod deploy_app
# ABOUTME: labels, the console and fleet.sh publish maintenance-shell-<cluster>, and deploy_app's reply names it.
"""The 2026-10-28 planning note (facilitation/kubecon-na-2026-planning-2026-10-28.md) wanted C6 to end with the bot
naming the Deployment and returning an endpoint the attendee can open, so they see they did it. #640 built the naming.
The endpoint takes five pieces that live in five files, and any one of them out of step leaves a dead link:

  1. images/villains/build.sh builds docker.io/peopleforrester/joker:latest, the image the ticket asks for, from
     joker-web/: busybox httpd serving www/ on PORT=8080 beside the old log loop.
  2. gitops/ai-layer/resources.yaml ships the maintenance-shell Service, port 80 to 8080, selecting
     burritobot.co/workload=maintenance-shell.
  3. workshop-mcp's deploy_app puts that label on every pod it creates, whatever labels the model wrote, and names
     https://maintenance-shell-<public host>/ in its reply once the Deployment is applied.
  4. console.conf serves maintenance-shell-<cluster> from that Service, with its own page while nothing answers.
  5. fleet.sh publishes the host in the routes table (WIB_VILLAIN_HOSTS).

The image runs for real in verify/test_joker_web_busybox.py (tools tier); this file is offline.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import types

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
BUILD = (REPO / "images/villains/build.sh").read_text(encoding="utf-8")
JOKER = REPO / "images/villains/joker-web"
START = (JOKER / "start.sh").read_text(encoding="utf-8")
PAGE = (JOKER / "www/index.html").read_text(encoding="utf-8")
CONF = (AI / "console.conf").read_text(encoding="utf-8")
FLEET = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
DOCS = list(yaml.safe_load_all((AI / "resources.yaml").read_text(encoding="utf-8")))
SPAWN = (REPO / "policies/kyverno/restrict-agent-spawned-workloads.yaml").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f": {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _StandInMCP:
    def __init__(self, *a, **kw) -> None:
        pass

    def tool(self, *a, **kw):
        return lambda f: f


site = load("ticket_site", AI / "ticket_site.py")
sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)


def server(public_host: str):
    """workshop-mcp's server as the pod runs it, with WIB_PUBLIC_HOST set (or not) and the API call captured."""
    old = os.environ.pop("WIB_PUBLIC_HOST", None)
    if public_host:
        os.environ["WIB_PUBLIC_HOST"] = public_host
    try:
        m = load("workshop_mcp", AI / "workshop-mcp-server.py")
    finally:
        os.environ.pop("WIB_PUBLIC_HOST", None)
        if old is not None:
            os.environ["WIB_PUBLIC_HOST"] = old
    m._ns = lambda: "agent"
    # deploy_app's report to the support desk runs on a daemon thread that looks up fake-ticket. Left running, it was
    # still in getaddrinfo when the interpreter finalized, and about one run in three ended in a segfault or abort
    # after every check had passed (#441). What the desk is told is test_room_jokers.py's, against a desk of its own.
    m._report = lambda name, ok, detail: None
    return m


def deploy(m, obj: dict, status: int = 201) -> tuple[str, dict]:
    sent: list[dict] = []

    def fake_req(method: str, path: str, body=None, content_type: str = "application/json"):
        if method == "GET":
            return 200, json.dumps({"resources": [{"kind": k, "name": n} for k, n in (
                ("Deployment", "deployments"), ("Pod", "pods"), ("CronJob", "cronjobs"), ("Service", "services"))]})
        sent.append(json.loads(body))
        return status, "{}" if status < 400 else '{"message":"denied by restrict-image-registries"}'

    m._req = fake_req
    reply = m.deploy_app(json.dumps(obj))
    return reply, (sent[0] if sent else {})


def c6_deployment(labels: dict | None = None, name: str | None = None) -> dict:
    """maintenance-shell as a model writes it from the ticket: its own labels, no ports, no limits."""
    labels = labels if labels is not None else {"app": "maintenance-shell"}
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name or site.C6_DEPLOYMENT},
            "spec": {"replicas": 1, "selector": {"matchLabels": labels},
                     "template": {"metadata": {"labels": labels},
                                  "spec": {"containers": [{"name": "maintenance-shell", "image": site.C6_IMAGE}]}}}}


print("== 1. the image the ticket names is the one build.sh builds to serve a page ==")
org = re.search(r'^ORG="([^"]+)"', BUILD, re.M)
check("the ticket asks for build.sh's $ORG/joker:latest", bool(org) and site.C6_IMAGE == f"{org.group(1)}/joker:latest",
      site.C6_IMAGE)
v = re.search(r"^declare -A V=\((.*?)^\)", BUILD, re.M | re.S)
check("the Joker is no longer a plain log loop in the V roster", bool(v) and "[joker]=" not in v.group(1))
check("build_joker_web runs, after the loops", BUILD.rstrip().endswith("build_joker_web"))
base = re.search(r'^JOKER_BASE="(docker\.io/library/busybox@sha256:[0-9a-f]{64})"', BUILD, re.M)
check("the Joker's base is busybox pinned by digest", base is not None)
check("joker-web goes in as a layer under /villain",
      "--transform 's,^joker-web,villain,'" in BUILD and '-b "$JOKER_BASE"' in BUILD and "-C \"${HERE}\"" in BUILD)
check("the layer is amd64, the nodes' architecture",
      "--platform linux/amd64" in BUILD
      and 'ami_type       = "AL2023_x86_64_STANDARD"' in (REPO / "infra/terraform/aws/cluster/main.tf").read_text())
mut = re.search(r'"\$CR" mutate "\$ORG/joker:latest" (.*) -t "\$ORG/joker:latest"', BUILD)
check("the entrypoint runs start.sh with the image's own sh", bool(mut) and '--entrypoint "/bin/sh,/villain/start.sh"' in mut.group(1))
port = re.search(r"--env PORT=(\d+)", mut.group(1) if mut else "")
check("the image sets PORT, which start.sh requires", port is not None and ': "${PORT:?' in START)
mode = subprocess.run(["git", "-C", str(REPO), "ls-files", "-s", "images/villains/joker-web/start.sh"],
                      capture_output=True, text=True).stdout
check("start.sh is committed executable", mode.startswith("100755"), mode.strip() or "not tracked")
check("start.sh serves www/ beside itself with busybox httpd in the foreground",
      'httpd -f -p "${PORT}" -h "${ROOT}/www"' in START and 'ROOT="$(dirname "$0")"' in START)
check("start.sh still laughs in the logs, the Joker's old line",
      "HAHAHA! The Joker runs on your cluster now. Why so SERIOUS about admission control?" in START)
check("start.sh ends both children on SIGTERM", "trap 'kill \"${LOOP}\" \"${HTTPD}\"" in START and "TERM" in START)
check("the page laughs and names the Deployment", "HA HA HA" in PAGE and site.C6_DEPLOYMENT in PAGE)
check("the page loads nothing from anywhere else",
      re.search(r"""\b(?:src|href)\s*=|@import|url\(""", PAGE) is None and "<script" not in PAGE)

print("== 2. the Service selects the pod deploy_app labels, on the port the image serves ==")
svc = next((d for d in DOCS if d and d.get("kind") == "Service"
            and d["metadata"]["name"] == site.C6_DEPLOYMENT), None)
check("resources.yaml ships a Service named for the ticket's Deployment", svc is not None)
m = server("")
want_sel = {m.WORKLOAD_LABEL: site.C6_DEPLOYMENT}
check("it selects burritobot.co/workload=maintenance-shell", bool(svc) and svc["spec"].get("selector") == want_sel,
      f"{svc and svc['spec'].get('selector')}")
ports = svc["spec"]["ports"] if svc else []
check("it maps port 80 to the image's PORT", len(ports) == 1 and ports[0]["port"] == 80
      and port is not None and ports[0]["targetPort"] == int(port.group(1)), f"{ports}")
check("the label is not the key the NetworkPolicies trust", m.WORKLOAD_LABEL != "app.kubernetes.io/name"
      and f"'{m.WORKLOAD_LABEL}'" not in SPAWN)

print("== 3. deploy_app labels the pod and names the address ==")
for labels in ({"app": "maintenance-shell"}, {"run": "shell", "tier": "ops"}):
    reply, out = deploy(m, c6_deployment(labels))
    tmpl = out.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {})
    check(f"the pod gets the workload label beside the model's own ({sorted(labels)})",
          tmpl == {**labels, m.WORKLOAD_LABEL: site.C6_DEPLOYMENT}, f"{tmpl}")
    check("the model's selector is left as written", out.get("spec", {}).get("selector") == {"matchLabels": labels})
c6 = c6_deployment()
del c6["spec"]["template"]["metadata"]
_, out = deploy(m, c6)
check("a template with no metadata still gets the label",
      out.get("spec", {}).get("template", {}).get("metadata", {}).get("labels") == want_sel)
_, out = deploy(m, {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "maintenance-shell"},
                    "spec": {"containers": [{"name": "c", "image": site.C6_IMAGE}]}})
check("a bare Pod gets the label on itself", out.get("metadata", {}).get("labels") == want_sel)
_, out = deploy(m, {"apiVersion": "batch/v1", "kind": "CronJob", "metadata": {"name": "nightly"},
                    "spec": {"schedule": "* * * * *", "jobTemplate": {"spec": {"template": {
                        "spec": {"containers": [{"name": "c", "image": "x"}]}}}}}})
check("a CronJob's job template gets it", out.get("spec", {}).get("jobTemplate", {}).get("spec", {})
      .get("template", {}).get("metadata", {}).get("labels") == {m.WORKLOAD_LABEL: "nightly"})
_, out = deploy(m, {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "x"}, "spec": {"ports": []}})
check("an object that creates no pod is applied without one", "template" not in out.get("spec", {})
      and "labels" not in out.get("metadata", {}))

reply, _ = deploy(m, c6_deployment())
check("with no public host the reply names no address", reply == f"deployed Deployment/{site.C6_DEPLOYMENT} in agent.",
      reply)
m = server("attackme.agenticburn.com")
reply, _ = deploy(m, c6_deployment())
# The room is shown burritobot.co (#651, #663): the cluster's identity stays attackme.agenticburn.com, and the reply
# names its burritobot.co twin, which fleet.sh routes to the same console.
check("with the public host the reply names https://maintenance-shell-attackme.burritobot.co/",
      reply.endswith("Once its pod is ready it answers at https://maintenance-shell-attackme.burritobot.co/"), reply)
check("and no agenticburn.com address", "agenticburn" not in reply, reply)
m = server("attackme.burritobot.co")
reply, _ = deploy(m, c6_deployment())
check("a public host already on burritobot.co is named as it is",
      reply.endswith("answers at https://maintenance-shell-attackme.burritobot.co/"), reply)
m = server("attackme.agenticburn.com")
reply, _ = deploy(m, c6_deployment(name="promo-mascot"))
check("a Deployment the console does not publish gets no address", "https://" not in reply, reply)
reply, _ = deploy(m, c6_deployment(), status=403)
check("a refused Deployment gets no address", "https://" not in reply and "deploy failed" in reply, reply)
check("the ticket's Deployment is the one workload deploy_app publishes", m.PUBLISHED_WORKLOADS == (site.C6_DEPLOYMENT,))
mcp_dep = next(d for d in DOCS if d and d.get("kind") == "Deployment" and d["metadata"]["name"] == "workshop-mcp")
env = {e["name"]: e for e in mcp_dep["spec"]["template"]["spec"]["containers"][0].get("env", [])}
ref = env.get("WIB_PUBLIC_HOST", {}).get("valueFrom", {}).get("configMapKeyRef", {})
check("workshop-mcp reads WIB_PUBLIC_HOST from cluster-identity's public-host",
      ref.get("name") == "cluster-identity" and ref.get("key") == "public-host", f"{ref}")

print("== 4. the console serves the host from the Service ==")
block = CONF[CONF.find("# Challenge 6's endpoint (#664)"):]
sn = re.search(r"server_name ~\^([a-z-]+)-\[a-z0-9-\]\+\\\.\(\?:agenticburn\\\.com\|burritobot\\\.co\)\$;", block)
check("a server answers maintenance-shell-<cluster> on both domains", bool(sn) and sn.group(1) == site.C6_DEPLOYMENT)
up = re.search(r"set \$wib_c6_villain http://([a-z0-9-]+)\.agent\.svc\.cluster\.local:(\d+);", block)
check("it proxies to the Service, in agent, on its port", bool(up) and up.group(1) == site.C6_DEPLOYMENT
      and bool(ports) and int(up.group(2)) == ports[0]["port"])
check("the name is resolved per request, so the console starts without it", "resolver 172.20.0.10" in block
      and "proxy_pass $wib_c6_villain;" in block)
check("it forwards GET (and HEAD) only", "limit_except GET { deny all; }" in block)
check("nothing answering yet is a page of its own, not a 502",
      "error_page 502 503 504 = @wib_c6_nothing_yet;" in block and "Nothing is running at this address yet" in block)
check("it is not the platform's 'not running on this cluster' page", "not running on this cluster" not in block)
nothing = block[block.find("location @wib_c6_nothing_yet"):]
check("that page loads nothing from anywhere else", "<link" not in nothing and "<script" not in nothing
      and "<img" not in nothing)

print("== 5. fleet.sh publishes the host ==")
hosts = re.search(r'^readonly WIB_VILLAIN_HOSTS="([^"]+)"', FLEET, re.M)
check("WIB_VILLAIN_HOSTS names the ticket's Deployment and the ticket desk, nothing else",
      bool(hosts) and hosts.group(1).split() == [site.C6_DEPLOYMENT, "support"])
check("emit_service_hosts writes a row for it beside the service hosts",
      "for svc in ${WIB_SERVICE_HOSTS} ${WIB_VILLAIN_HOSTS}; do" in FLEET)
emitted = subprocess.run(["bash", "-c", 'eval "$(sed -n "/^readonly WIB_SERVICE_HOSTS=/,/^}/p" "$1")"; '
                          'emit_service_hosts attackme.agenticburn.com lb-test.elb', "_",
                          str(REPO / "infra/terraform/fleet/fleet.sh")], capture_output=True, text=True)
check("the attackme rows include maintenance-shell-attackme.agenticburn.com on the console's LB",
      "maintenance-shell-attackme.agenticburn.com  lb-test.elb:443" in emitted.stdout.splitlines(),
      emitted.stdout + emitted.stderr)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All C6 villain endpoint checks passed.")
