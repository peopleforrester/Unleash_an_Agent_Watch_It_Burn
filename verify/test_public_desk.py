# ABOUTME: Holds #1158: only kubecon-private points its bot at the public desk, through desk-relay, which passes one ticket
# ABOUTME: by its number and the deploy report with the desk's token; the attendee profile keeps its in-cluster desk.
"""Offline checks for #1158, the admin cluster's half of #1145 (one desk and one deployments page for both KubeCon bots).

On kubecon-private the ai-layer adds the public-desk component: a desk-relay pod, and workshop-mcp's TICKET_SITE_URL
pointed at it. The relay passes GET /ticket?id=<number> to support.burritobot.co, POST /landed to its /remote-landed
with the desk-report-token Secret's token (#1157), POST /cluster-read to its /remote-cluster-read with the same token
(#1209), and nothing else.

Four parts, with no cluster and no network:
  1. every profile's ai-layer as the chart writes it (bootstrap_chart.py, no Helm), and workshop-mcp's TICKET_SITE_URL
     once the components it lists are applied: the attendee profile's is the in-cluster fake-ticket Service, and only
     kubecon-private's is the relay;
  2. the real desk_relay.py on localhost in front of the real ticket_site.py as the public desk (token, community
     labels) and a second one as the private cluster's own desk, with the real workshop-mcp-server.py's
     read_support_ticket and deploy report pointed at the relay: a ticket filed on the public desk is read by its
     number, and the report lands under "private";
  3. read by number only (#1077): no MCP tool lists tickets, and every desk path but /ticket?id= is refused at the
     relay without reaching the public desk;
  4. each cluster's reads cover its own rows only: the community reader never greys a private row, and the private
     reader's reads, through the relay, grey the private rows Kyverno removed and never a community row (#1209).
verify/test_bootstrap_chart_render.py builds the component with the pinned Helm and kustomize.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import socket
import sys
import tempfile
import threading
import time
import types
from http.client import HTTPConnection  # the module name `http` is this file's request helper below
import urllib.error
import urllib.parse
import urllib.request

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
# desk-link's checks run fleet.sh, behind fakes of their own; anything that got past them to a real aws, kubectl,
# eksctl, terraform or helm would log the call and fail, even when the test is run by hand (verify/no_cloud.py).
import no_cloud  # noqa: E402
no_cloud.setup()
from bootstrap_chart import (PUBLIC_DESK_COMPONENT, ai_layer_for, all_profiles, app_names, REPO,  # noqa: E402
                             use_public_desk)

AI = REPO / "gitops/ai-layer"
COMPONENT = AI / PUBLIC_DESK_COMPONENT
RES = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text(encoding="utf-8")) if isinstance(d, dict)]
IN_CLUSTER_DESK = "http://fake-ticket.agent.svc.cluster.local:8080"
RELAY_URL = "http://desk-relay.agent.svc.cluster.local:8080"
TOKEN = "relay-t0k3n-" + "b" * 40
SUPPORT = "support.burritobot.co"
DEPLOYMENTS = "deployments.burritobot.co"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def load(name: str, path: pathlib.Path, env: dict[str, str] | None = None):
    saved = {k: os.environ.get(k) for k in env or {}}
    os.environ.update(env or {})
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return mod


def serve(server) -> str:
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def mcp_env(components: list[str]) -> dict[str, str]:
    """workshop-mcp's shim env as kustomize writes it: resources.yaml's, then each component's patch, merged by name."""
    dep = next(d for d in RES if d.get("kind") == "Deployment" and d["metadata"]["name"] == "workshop-mcp")
    shim = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "shim")
    env = {e["name"]: e.get("value") for e in shim.get("env") or []}
    for c in components:
        doc = yaml.safe_load((AI / c / "kustomization.yaml").read_text(encoding="utf-8"))
        for p in doc.get("patches") or []:
            if (p.get("target") or {}).get("name") != "workshop-mcp":
                continue
            patch = yaml.safe_load(p["patch"])
            for ct in patch["spec"]["template"]["spec"]["containers"]:
                if ct["name"] == "shim":
                    env.update({e["name"]: e.get("value") for e in ct.get("env") or []})
    return env


print("== each profile's workshop-mcp: the attendee profile keeps its own desk, kubecon-private uses the relay ==")
rendered = [p for p in all_profiles() if "ai-layer" in app_names(p)]
check("the attendee profile and kubecon-private render the ai-layer", {"attendee", "kubecon-private"} <= set(rendered),
      str(rendered))
check("the base workshop-mcp reads the in-cluster fake-ticket Service", mcp_env([]).get("TICKET_SITE_URL") == IN_CLUSTER_DESK)
fake_ticket = next((d for d in RES if d.get("kind") == "Service" and d["metadata"]["name"] == "fake-ticket"), {})
check("and that is the fake-ticket Service in agent, on 8080", IN_CLUSTER_DESK == "http://fake-ticket.agent.svc.cluster."
      "local:8080" and any(p.get("port") == 8080 for p in (fake_ticket.get("spec") or {}).get("ports", [])))
for profile in rendered:
    app = yaml.safe_load(ai_layer_for(profile))
    comps = list((app["spec"]["source"].get("kustomize") or {}).get("components") or [])
    on = profile == "kubecon-private"
    check(f"{profile}: desk.usePublicDesk is {on}", use_public_desk(profile) is on)
    check(f"{profile}: the ai-layer {'adds' if on else 'does not add'} the public-desk component {comps}",
          (PUBLIC_DESK_COMPONENT in comps) is on)
    url = mcp_env(comps).get("TICKET_SITE_URL")
    check(f"{profile}: workshop-mcp's TICKET_SITE_URL is {'the relay' if on else 'its own fake-ticket Service'} ({url})",
          url == (RELAY_URL if on else IN_CLUSTER_DESK))

relay_docs = [d for d in yaml.safe_load_all((COMPONENT / "desk-relay.yaml").read_text(encoding="utf-8")) if d]
relay_dep = next((d for d in relay_docs if d["kind"] == "Deployment"), {})
relay_svc = next((d for d in relay_docs if d["kind"] == "Service"), {})
relay_np = next((d for d in relay_docs if d["kind"] == "NetworkPolicy"), {})
pod = (relay_dep.get("spec") or {}).get("template", {}).get("spec", {})
relay_env = {e["name"]: e.get("value") for c in pod.get("containers", []) for e in c.get("env") or []}
check("the relay's Service is desk-relay on 8080, the name TICKET_SITE_URL gives",
      relay_svc.get("metadata", {}).get("name") == "desk-relay" and RELAY_URL.endswith(":8080")
      and [p.get("port") for p in relay_svc["spec"]["ports"]] == [8080])
check("the relay's one desk is support.burritobot.co over https; it names no in-cluster desk (#1209)",
      relay_env.get("DESK_PUBLIC_URL") == f"https://{SUPPORT}" and "DESK_LOCAL_URL" not in relay_env
      and not [v for v in relay_env.values() if v and "svc.cluster.local" in v], str(relay_env))
check("the relay holds no cluster token", pod.get("automountServiceAccountToken") is False)
check("it mounts desk-report-token, optional, where DESK_REPORT_TOKEN_FILE reads",
      {"secretName": "desk-report-token", "optional": True} in [v.get("secret") for v in pod.get("volumes", [])]
      and relay_env.get("DESK_REPORT_TOKEN_FILE") == "/var/run/desk-report-token/token")
egress = (relay_np.get("spec") or {}).get("egress") or []
check("its NetworkPolicy selects the relay alone, by the label egressLabels refuses the agent",
      relay_np.get("spec", {}).get("podSelector") == {"matchLabels": {"app.kubernetes.io/name": "desk-relay"}}
      and "'desk-relay'" in (REPO / "policies/kyverno/restrict-agent-spawned-workloads.yaml").read_text(encoding="utf-8"))
check("and lets it out on TCP 443 and DNS, nothing else: no in-namespace desk since its reads go public (#1209)",
      egress == [{"ports": [{"protocol": "TCP", "port": 443}]},
                 {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}],
                  "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}], str(egress))
mcp_np = [d for d in relay_docs if d["kind"] == "NetworkPolicy"
          and (d["spec"].get("podSelector") or {}) != {"matchLabels": {"app.kubernetes.io/name": "desk-relay"}}]
check("the component opens no egress for workshop-mcp or any other pod", not mcp_np, str(mcp_np))

print("== the relay on localhost, between the real MCP server and the real desks ==")
public_seen: list[str] = []
public = load("ticket_site_public_1158", AI / "ticket_site.py",
              {"DESK_REPORT_TOKEN": TOKEN, "DESK_CLUSTER": "community", "DESK_REMOTE_CLUSTER": "private"})
public.Handler.log_message = lambda self, *a: public_seen.append(self.path)
PUBLIC = serve(public.Server(("127.0.0.1", 0), public.Handler))
local_seen: list[str] = []
local = load("ticket_site_local_1158", AI / "ticket_site.py", {"DESK_REPORT_TOKEN": "", "DESK_CLUSTER": "",
                                                                 "DESK_REMOTE_CLUSTER": ""})
local.Handler.log_message = lambda self, *a: local_seen.append(self.path)
LOCAL = serve(local.Server(("127.0.0.1", 0), local.Handler))

tmp = pathlib.Path(tempfile.mkdtemp(prefix="desk-relay-1158-"))
token_file = tmp / "token"
relay = load("desk_relay_1158", COMPONENT / "desk_relay.py", {"DESK_REPORT_TOKEN_FILE": str(token_file)})
os.environ["DESK_REPORT_TOKEN_FILE"] = str(token_file)
relay.Handler.public = PUBLIC
check("the relay holds one desk URL, the public one", not hasattr(relay.Handler, "local"))
relay.Handler.log_message = lambda *a: None
RELAY = serve(relay.ThreadingHTTPServer(("127.0.0.1", 0), relay.Handler))


def http(method: str, url: str, body: bytes | None = None, headers: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def oversized(url: str, length: int) -> int:
    """POST that declares a body of `length` bytes and sends none of it, and return the status.

    The relay refuses on the declared Content-Length without reading the body, then closes. A client still writing the
    body raced that close: staging 429d97e1's CI got BrokenPipeError instead of the 413 (#1252). Sending the headers
    alone checks the same refusal with no race: the relay has everything it reads before it answers."""
    parts = urllib.parse.urlsplit(url)
    conn = HTTPConnection(parts.hostname, parts.port, timeout=5)
    try:
        conn.putrequest("POST", parts.path)
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(length))
        conn.endheaders()
        r = conn.getresponse()
        r.read()
        return r.status
    finally:
        conn.close()


# A ticket filed the way the room and the presenters file one on support.burritobot.co: the desk's own form.
code, page = http("POST", f"{PUBLIC}/submit", urllib.parse.urlencode(
    {"body": "<p>My cauldron order never arrived. Please check order 4471.</p>"}).encode(),
    {"Host": SUPPORT, "Content-Type": "application/x-www-form-urlencoded"})
filed = (re.search(r"Your ticket is (HC-\d+)", page) or [None, ""])[1]
check(f"a ticket is filed on the public desk ({code}, {filed or 'no number'})", code == 200 and bool(filed))


class _StandInMCP:
    def __init__(self, *a, **kw) -> None:
        pass

    def get_context(self):
        raise LookupError("a stand-in FastMCP: no MCP request in flight")

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP, emit=lambda e: None,
                                                  _now=lambda: "2026-11-08T00:00:00.000Z")
mcp = load("workshop_mcp_1158", AI / "workshop-mcp-server.py", {"LLM_GUARD_TOKEN": "test"})
closed = relay.ThreadingHTTPServer(("127.0.0.1", 0), relay.Handler)
CLOSED = f"http://127.0.0.1:{closed.server_address[1]}"
closed.server_close()
mcp.TICKET_SITE_URL, mcp.GUARD_PROXY_URL = RELAY, CLOSED   # guard-proxy unreadable: the input guard counts as off

out = mcp.read_support_ticket(filed)
check(f"read_support_ticket through the relay reads {filed} by its number",
      out.startswith(f"Ticket {filed} [open]") and "cauldron order never arrived" in out, out[:200])
check("the public desk was asked for that ticket and nothing else", public_seen[-1:] == [f"/ticket?id={filed}"],
      str(public_seen[-3:]))
out = mcp.read_support_ticket("HC-7731")
check("a seeded ticket reads by its number too", out.startswith("Ticket HC-7731 [open] from Hazel Bramblewick"), out[:120])
out = mcp.read_support_ticket("HC-0001")
check("an unknown number says so, from the public desk", "no ticket" in out, out[:120])
check("the private cluster's own desk was asked for no ticket", not [p for p in local_seen if "ticket" in p],
      str(local_seen))


def landed_rows(name: str) -> list[dict]:
    for _ in range(50):
        rows = [r for r in json.loads(http("GET", f"{PUBLIC}/deployments.json", headers={"Host": DEPLOYMENTS})[1])
                if r["name"] == name]
        if rows:
            return rows
        time.sleep(0.1)
    return []


IMAGE = "registry.burritobot.co/burritobot/maintenance-shell:1"
mcp._report("relay-no-token", True, "", IMAGE, "Agatha the Banshee", "Deployment")
time.sleep(0.5)
check("with no token file, the relay sends no report and the page has no row", not landed_rows("relay-no-token")
      and "/remote-landed" not in public_seen)
code, body = http("POST", f"{RELAY}/landed", b'{"name": "x"}', {"Content-Type": "application/json"})
check(f"and answers the report 503, naming the Secret ({code})", code == 503 and "desk-report-token" in body)

token_file.write_text(TOKEN + "\n", encoding="utf-8")   # fleet.sh desk-link writes the Secret; the kubelet fills the file
mcp._report("relay-landed", True, "", IMAGE, "Agatha the Banshee", "Deployment")
rows = landed_rows("relay-landed")
check("once the token is there, deploy_app's report lands on the public deployments page, with no restart",
      len(rows) == 1, str(rows))
check("under private, with the witch name it carried and its image",
      bool(rows) and rows[0]["cluster"] == "private" and rows[0]["witch"] == "Agatha the Banshee"
      and rows[0]["image"] == IMAGE, str(rows))
check("the relay reached the public desk on /remote-landed, not /landed", "/remote-landed" in public_seen
      and "/landed" not in public_seen)
token_file.write_text("a-wrong-token", encoding="utf-8")
code, body = http("POST", f"{RELAY}/landed", json.dumps({"name": "relay-wrong", "ok": True}).encode(),
                  {"Content-Type": "application/json"})
check(f"a token the public desk does not hold: its 401 comes back, and nothing lands ({code})",
      code == 401 and not landed_rows("relay-wrong"))
token_file.write_text(TOKEN, encoding="utf-8")
code = oversized(f"{RELAY}/landed", 4 * 1024 + 1)
check(f"a report over the public console's 4k is refused at the relay ({code})", code == 413)

print("== read by number only (#1077) ==")
tools = re.findall(r"^@mcp\.tool\(.*?^def (\w+)\(", (AI / "workshop-mcp-server.py").read_text(encoding="utf-8"),
                   re.S | re.M)
check(f"the MCP server's tools were found ({len(tools)})", len(tools) >= 10, str(tools))
check(f"the MCP server's one ticket tool is read_support_ticket {[t for t in tools if 'ticket' in t]}",
      [t for t in tools if "ticket" in t] == ["read_support_ticket"])
check("and it asks for a number before it calls anything", mcp.read_support_ticket(" ").startswith("provide a ticket id"))
before = len(public_seen)
for path in ("/", "/wall", "/wall.json", "/me", "/mine", "/deployments", "/deployments.json", f"/{filed}",
             f"/lookup?number={filed}", "/ticket", "/ticket?id=", f"/ticket?id={filed}&id=HC-7731",
             "/ticket?id=" + "9" * 41, "/healthz/../wall.json", "/presenter-ticket"):
    code, _ = http("GET", f"{RELAY}{path}")
    check(f"GET {path} at the relay is refused ({code})", code in (400, 404))
for path in ("/submit", "/presenter-ticket", "/remote-landed", "/remote-cluster-read", "/ticket"):
    code, _ = http("POST", f"{RELAY}{path}", b"{}", {"Content-Type": "application/json"})
    check(f"POST {path} at the relay is refused ({code})", code == 404)
check("none of them reached the public desk", len(public_seen) == before, str(public_seen[before:]))
code, body = http("GET", f"{RELAY}/healthz")
check("the relay's /healthz names its desk and whether it holds a token, never the token",
      code == 200 and json.loads(body) == {"ok": True, "desk": PUBLIC, "token": True} and TOKEN not in body)

print("== each cluster's reads cover its own rows only, the private one's through the relay (#1209) ==")


def removed_names() -> set[str]:
    return {r["name"] for r in public.LANDINGS if r["removed_at"]}


public.record_landing("community-app", True, "", IMAGE, "Hazel the Witch", "Deployment")
mine = [r for r in public.LANDINGS if r["name"] == "community-app"]
check("a row the community cluster's bot landed is labelled community", bool(mine) and mine[0]["cluster"] == "community")
check("the private rows so far are relay-landed alone", {r["name"] for r in public.LANDINGS if r["cluster"] == "private"}
      == {"relay-landed"}, str([(r["name"], r["cluster"]) for r in public.LANDINGS]))
read_kept = {"taken_at": time.time() + 1, "ok": True, "kinds": {"Deployment": ["relay-landed"]}}
token_file.write_text("", encoding="utf-8")
before, local_before = len(public_seen), len(local_seen)
code, body = http("POST", f"{RELAY}/cluster-read", json.dumps(read_kept).encode(), {"Content-Type": "application/json"})
check(f"with no token, the relay answers a cluster read 503, naming the Secret, and sends nothing ({code})",
      code == 503 and "desk-report-token" in body and len(public_seen) == before, body[:200])
token_file.write_text("a-wrong-token", encoding="utf-8")
code, body = http("POST", f"{RELAY}/cluster-read", json.dumps(read_kept).encode(), {"Content-Type": "application/json"})
check(f"with a token the public desk does not hold, its 401 comes back and no row is marked ({code})",
      code == 401 and removed_names() == set(), body[:200])
token_file.write_text(TOKEN + "\n", encoding="utf-8")
code, body = http("POST", f"{RELAY}/cluster-read", json.dumps(read_kept).encode(), {"Content-Type": "application/json"})
check(f"with the token, a private read that still lists relay-landed reaches the public desk and marks nothing ({code})",
      code == 200 and json.loads(body) == {"applied": True, "marked": []}, body[:200])
check("it reached the public desk on /remote-cluster-read, and no in-cluster desk",
      public_seen[before:].count("/remote-cluster-read") == 2 and "/cluster-read" not in public_seen
      and len(local_seen) == local_before, f"{public_seen[before:]} {local_seen[local_before:]}")
code = oversized(f"{RELAY}/cluster-read", 512 * 1024 + 1)
check(f"a read over the public console's 512k is refused at the relay ({code})", code == 413)
# The relay reads an oversize body before its 413, as nginx does, so the sender reads the 413 and not a broken pipe:
# answering first closed the socket under a sender still writing, 9 of 40 times at this size (#1220). Every one counts.
codes = [http("POST", f"{RELAY}/cluster-read", b"x" * (512 * 1024 + 1), {"Content-Type": "application/json"})[0]
         for _ in range(20)]
check(f"twenty reads over 512k each get the relay's 413, none a broken pipe ({sorted(set(codes))})", codes == [413] * 20)
check("the relay reads at most DRAIN_MAX of an oversize body, twice the largest it takes",
      relay.DRAIN_MAX == 2 * relay.MAX_READ)
host, port = urllib.parse.urlsplit(RELAY).hostname, urllib.parse.urlsplit(RELAY).port
with socket.create_connection((host, port), timeout=5) as sock:
    sock.sendall(f"POST /cluster-read HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
                 f"Content-Length: {relay.DRAIN_MAX + 1}\r\n\r\n".encode())
    reply = b""
    while chunk := sock.recv(4096):
        reply += chunk
check("a body declared over DRAIN_MAX, never sent, is answered 413 at once and the connection closed",
      reply.startswith(b"HTTP/1.0 413") or reply.startswith(b"HTTP/1.1 413"), reply[:80].decode(errors="replace"))

# Kyverno's remove-untrusted-room-workloads deletes relay-landed on the private cluster: the private reader's next read,
# the real read_room_workloads' report posted by the real post_cluster_read, no longer lists it.
said = mcp.post_cluster_read({"taken_at": time.time() + 1, "ok": True,
                              "kinds": {"Deployment": [], "Pod": ["workshop-mcp-0"]}})
check(f"workshop-mcp's reader, pointed at the relay, posts its read ({said})", said == "cluster reads posted to the desk")
rows = json.loads(http("GET", f"{PUBLIC}/deployments.json", headers={"Host": DEPLOYMENTS})[1])
greyed = {r["name"]: r["cluster"] for r in rows if r["removed_at"]}
check("the private row Kyverno removed shows greyed on the public deployments page",
      greyed == {"relay-landed": "private"}, str(greyed))
check("and the private read never marks the community row", not [r for r in rows if r["cluster"] == "community"
                                                                    and r["removed_at"]], str(rows))
mcp._report("relay-landed-2", True, "", IMAGE, "Agatha the Banshee", "Deployment")
check("a second private deploy lands on the public page", len(landed_rows("relay-landed-2")) == 1)
result = public.record_cluster_read({"taken_at": time.time() + 1, "ok": True, "kinds": {"Deployment": []}})
check(f"a community read that lists no Deployment marks the community row removed {result['marked']}",
      result["marked"] == ["community-app"])
check("and never a private row, since that read never covered one", "relay-landed-2" not in removed_names())
local.record_landing("attendee-app", True, "", IMAGE, "Hazel the Witch", "Deployment")
result = local.record_cluster_read({"taken_at": time.time() + 1, "ok": True, "kinds": {"Deployment": []}})
check(f"a desk with no cluster label (the 2-hour workshop's) still marks its own rows {result['marked']}",
      "attendee-app" in result["marked"])

print("== fleet.sh desk-link, against fake aws and kubectl ==")
FLEET = REPO / "infra/terraform/fleet/fleet.sh"
FAKE_AWS = r'''#!/usr/bin/env bash
args=("$@"); out=""; name=""
for ((i=0; i<${#args[@]}; i++)); do
  [[ "${args[$i]}" == --kubeconfig ]] && out="${args[$((i+1))]}"
  [[ "${args[$i]}" == --name ]] && name="${args[$((i+1))]}"
done
cat > "$out" <<EOF
apiVersion: v1
kind: Config
clusters: [{name: c, cluster: {server: "https://${name}.eks.example"}}]
contexts: [{name: "arn:aws:eks:us-west-2:111122223333:cluster/${name}", context: {cluster: c, user: u}}]
current-context: arn:aws:eks:us-west-2:111122223333:cluster/${name}
users: [{name: u, user: {token: x}}]
EOF
'''
FAKE_KUBECTL = r'''#!/usr/bin/env python3
import base64, json, os, sys, yaml
a = sys.argv[1:]
cfg = yaml.safe_load(open(os.environ["KUBECONFIG"]))
ctx = a[a.index("--context") + 1] if "--context" in a else cfg["current-context"]
name = ctx.rsplit("/", 1)[-1]
store = os.environ["STORE"]
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps({"ctx": ctx, "args": a}) + "\n")
if a[:2] == ["config", "current-context"]:
    print(cfg["current-context"]); sys.exit(0)
path = os.path.join(store, name)
if "get" in a and "desk-report-token" in a:
    if not os.path.exists(path):
        sys.exit(1)
    print(json.load(open(path))["data"]["token"], end=""); sys.exit(0)
if "create" in a and "secret" in a:
    tok = open(next(x[len("--from-file=token="):] for x in a if x.startswith("--from-file=token="))).read()
    print(yaml.safe_dump({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": a[a.index("generic") + 1],
          "namespace": a[a.index("-n") + 1]}, "data": {"token": base64.b64encode(tok.encode()).decode()}})); sys.exit(0)
if "apply" in a:
    json.dump(yaml.safe_load(sys.stdin.read()), open(path, "w")); sys.exit(0)
if "rollout" in a and "restart" in a:
    open(os.path.join(store, "restarted"), "a").write(f"{name} {a[-1]}\n"); sys.exit(0)
sys.exit(1)
'''
import base64  # noqa: E402
import subprocess  # noqa: E402

with tempfile.TemporaryDirectory() as t:
    fakebin = pathlib.Path(t, "bin"); fakebin.mkdir()  # noqa: E702
    store = pathlib.Path(t, "store"); store.mkdir()  # noqa: E702
    (fakebin / "aws").write_text(FAKE_AWS); (fakebin / "aws").chmod(0o755)  # noqa: E702
    (fakebin / "kubectl").write_text(FAKE_KUBECTL); (fakebin / "kubectl").chmod(0o755)  # noqa: E702
    calls = pathlib.Path(t, "calls")

    def desk_link(*names: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}", "CALLS": str(calls), "STORE": str(store),
               "KUBECONFIG": "/nonexistent-shared-config"}
        return subprocess.run(["bash", "-c", f"source '{FLEET}' >/dev/null 2>&1; cmd_desk_link {' '.join(names)}"],
                              cwd=FLEET.parent, env=env, capture_output=True, text=True, timeout=120)

    def token_of(cluster: str) -> str:
        p = store / cluster
        return base64.b64decode(json.load(open(p))["data"]["token"]).decode() if p.exists() else ""

    def restarts() -> list[str]:
        p = store / "restarted"
        return p.read_text().split("\n")[:-1] if p.exists() else []

    check("fleet.sh dispatches desk-link", "desk-link) cmd_desk_link" in FLEET.read_text(encoding="utf-8"))
    r = desk_link()
    out = r.stdout + r.stderr
    first = token_of("watch-it-burn-community")
    check("desk-link with no token anywhere writes one, the same on both clusters, and says so",
          r.returncode == 0 and len(first) == 64 and token_of("watch-it-burn-private") == first and "linked;" in out, out)
    check("as agent/desk-report-token, the Secret both the desk and the relay read",
          all(json.load(open(store / c))["metadata"] == {"name": "desk-report-token", "namespace": "agent"}
              for c in ("watch-it-burn-community", "watch-it-burn-private")))
    check("it restarts the community desk once, saying that clears it, and nothing on the private cluster",
          restarts() == ["watch-it-burn-community deployment/fake-ticket"] and "clears its filed tickets" in out, out)
    check("the token is never printed", first not in out)
    (store / "watch-it-burn-private").unlink()
    r = desk_link()
    out = r.stdout + r.stderr
    check("a second run keeps the community token, copies it to the private cluster, and restarts nothing",
          r.returncode == 0 and token_of("watch-it-burn-community") == first and token_of("watch-it-burn-private") == first
          and restarts() == ["watch-it-burn-community deployment/fake-ticket"] and "keeps its desk-report-token" in out, out)
    every = [json.loads(line) for line in calls.read_text().splitlines()]
    check("every kubectl call names its context, or reads its own isolated kubeconfig",
          all("--context" in c["args"] or c["args"][:2] == ["config", "current-context"] for c in every))
    check("and no call is on the agent/terminal-auth Secret (#1074)", not [c for c in every if "terminal-auth" in c["args"]])
    r = desk_link("watch-it-burn-private", "watch-it-burn-private")
    check("desk-link refuses one cluster linked to itself", r.returncode == 2)

print("== offline means offline ==")
_calls = no_cloud.calls()
check("no check above called aws, kubectl, eksctl, terraform or helm", not _calls, _calls)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("Only kubecon-private's bot uses the public desk, through a relay that reads one ticket by its number and sends the "
      "deploy report and the cluster read with the desk's token; every other profile keeps its own desk.")
