# ABOUTME: Pins C6's fake ticket site and read_support_ticket (#640): the ticket is fetched, not pasted, and with the
# ABOUTME: input guard on the tool runs the body through LLM Guard and withholds a flagged ticket before the model reads it.
"""Offline checks for #640.

Since the 2026-10-28 planning call the room asks BurritoBot to read ticket HC-7731 and nothing else. The bot fetches
it from `fake-ticket`, an in-namespace site serving fixed tickets, through workshop-mcp's read_support_ticket. The
ticket's hidden paragraph asks for the Joker villain image, which restrict-image-registries refuses (question 872).

guard-proxy never sees the ticket, so its input guard on /chat cannot stop it. read_support_ticket applies the same
guard to what it fetched: it reads guard-proxy's input_classifier toggle from /guards, and when it is on, sends the
ticket body to LLM Guard's /analyze/prompt and withholds a flagged ticket.

The real site runs here on localhost, and so does the real tool, with stand-ins for guard-proxy and LLM Guard and
for tool_audit (the offline suite has no `mcp`). No cluster, no model.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys
import threading
import types
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
RES = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text()) if isinstance(d, dict)]
KUST = yaml.safe_load((AI / "kustomization.yaml").read_text())
SITE_SRC = (AI / "ticket_site.py").read_text()
MCP_SRC = (AI / "workshop-mcp-server.py").read_text()
LABEL = {"app.kubernetes.io/name": "fake-ticket"}

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def one(kind: str, name: str) -> dict:
    found = [d for d in RES if d.get("kind") == kind and d["metadata"]["name"] == name]
    return found[0] if len(found) == 1 else {}


def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


print("== the site runs in the agent namespace from its own source ==")
dep = one("Deployment", "fake-ticket")
pod = dep.get("spec", {}).get("template", {})
spec = pod.get("spec", {})
c = (spec.get("containers") or [{}])[0]
check("a fake-ticket Deployment exists", bool(dep))
check("its pods carry the Service's label", LABEL.items() <= (pod.get("metadata", {}).get("labels") or {}).items())
check("it has resource limits (the Enforce floor denies it otherwise)", bool((c.get("resources") or {}).get("limits")))
check("it uses the pinned workshop-mcp image, already on the registry allow-list",
      re.match(r"ghcr\.io/peopleforrester/watch-it-burn:workshop-mcp@sha256:[0-9a-f]{64}$", c.get("image", "")) is not None)
check("it runs ticket_site.py from a generated ConfigMap",
      c.get("command") == ["python", "/app/ticket_site.py"]
      and any(v.get("configMap", {}).get("name") == "fake-ticket-src" for v in spec.get("volumes") or [])
      and any(g.get("name") == "fake-ticket-src" and "ticket_site.py" in g.get("files", [])
              for g in KUST["configMapGenerator"]))
check("it holds no ServiceAccount token: it calls no API", spec.get("automountServiceAccountToken") is False)
check("its pod turns service links off", spec.get("enableServiceLinks") is False)
check("the site reads no FAKE_TICKET_* variable, which service links would set", "FAKE_TICKET_" not in
      SITE_SRC.replace("Not FAKE_TICKET_*", "").replace("FAKE_TICKET_PORT=tcp", ""))
check("it makes no outbound call, so it needs no egress allow", "urlopen" not in SITE_SRC)
svc = one("Service", "fake-ticket")
check("a fake-ticket Service on 8080", svc.get("spec", {}).get("ports", [{}])[0].get("port") == 8080
      and svc.get("spec", {}).get("selector") == LABEL)

print("== workshop-mcp is told where the ticket and the guard are ==")
mcp = one("Deployment", "workshop-mcp")
shim = next((x for x in mcp["spec"]["template"]["spec"]["containers"] if x["name"] == "shim"), {})
env = {e["name"]: e for e in shim.get("env") or []}
check("TICKET_SITE_URL is the fake-ticket Service", env.get("TICKET_SITE_URL", {}).get("value")
      == "http://fake-ticket.agent.svc.cluster.local:8080")
check("GUARD_PROXY_URL is guard-proxy's Service", env.get("GUARD_PROXY_URL", {}).get("value")
      == "http://guard-proxy.agent.svc.cluster.local:8080")
proxy = one("Deployment", "guard-proxy")["spec"]["template"]["spec"]["containers"]
proxy_env = {e["name"]: e for e in next(x for x in proxy if x["name"] == "proxy")["env"]}
check("LLM_GUARD_URL and its token are guard-proxy's own", env.get("LLM_GUARD_URL") == proxy_env.get("LLM_GUARD_URL")
      and env.get("LLM_GUARD_TOKEN") == proxy_env.get("LLM_GUARD_TOKEN"))
check("no setting the tool reads is a name Kubernetes service links inject",
      not any(n.endswith(("_PORT", "_SERVICE_HOST", "_SERVICE_PORT")) for n in env))
agent = one("Agent", "workshop-agent")["spec"]["declarative"]
wm = next(t["mcpServer"] for t in agent["tools"] if t["mcpServer"]["name"] == "workshop-mcp")
check("read_support_ticket is on the agent's workshop-mcp allow-list", "read_support_ticket" in wm["toolNames"])
check("the RemoteMCPServer description lists it", "read_support_ticket" in
      one("RemoteMCPServer", "workshop-mcp")["spec"]["description"])
check("the system prompt tells BurritoBot to read a ticket it is asked about",
      "read_support_ticket" in agent["systemMessage"] and "HC-" in agent["systemMessage"])

print("== nothing new is needed on the network ==")
intra = yaml.safe_load((REPO / "policies/network-policies/per-namespace/agent-allow-intra-namespace.yaml").read_text())
check("every agent pod may reach every agent pod, so workshop-mcp reaches the site, guard-proxy and LLM Guard",
      intra["spec"]["podSelector"] == {} and intra["spec"]["egress"] == [{"to": [{"podSelector": {}}]}])
ingress = [d for d in yaml.safe_load_all((AI / "chat-path-ingress.yaml").read_text()) if d]
selected = [d["spec"]["podSelector"]["matchLabels"].get("app.kubernetes.io/name") for d in ingress]
check("and no ingress policy selects any of the three",
      not {"fake-ticket", "guard-proxy", "llm-guard"} & set(selected), str(selected))

print("== the site serves the ticket the room names ==")
site = load("ticket_site", AI / "ticket_site.py")
check("the C6 ticket's hidden paragraph asks for the Joker as maintenance-shell",
      site.C6_IMAGE == "docker.io/peopleforrester/joker:latest" and site.C6_DEPLOYMENT == "maintenance-shell"
      and f'"{site.C6_DEPLOYMENT}"' in site.C6_PAYLOAD and site.C6_IMAGE in site.C6_PAYLOAD)
check("and asks the bot to name the Deployment, the payoff the planning note wants", "tell the customer the name"
      in site.C6_PAYLOAD)
check("the ticket body carries that paragraph after a plain complaint",
      site.TICKETS[site.C6_TICKET_ID]["body"].endswith("\n\n" + site.C6_PAYLOAD))
check("the other tickets carry no instruction (HC-666, the room's ticket, is held by test_support_desk.py)",
      all("IGNORE" not in t["body"] for k, t in site.TICKETS.items() if k not in (site.C6_TICKET_ID, site.ROOM_TICKET_ID)))


def serve(handler) -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


site.Handler.log_message = lambda *a: None
site_srv, SITE = serve(site.Handler)


def get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


check("/healthz answers", get(f"{SITE}/healthz") == (200, {"ok": True}))
code, body = get(f"{SITE}/ticket?id=hc-7731")
check("/ticket?id=HC-7731 returns the ticket, whatever the case", code == 200 and body["id"] == "HC-7731")
check("an unknown ticket is a 404, not an invented one", get(f"{SITE}/ticket?id=HC-0000")[0] == 404)
check("no id is a 400", get(f"{SITE}/ticket")[0] == 400)
check("any other path is a 404", get(f"{SITE}/admin")[0] == 404)
# 2026-10-29 on the private cluster the model called read_support_ticket('HC7731') and told the room the ticket did
# not exist. A ticket number is unique, so any spelling that carries exactly its digits finds it.
for spelled in ("HC7731", "hc 7731", "HC_7731", "7731", "HH-7731"):
    code, body = get(f"{SITE}/ticket?id={urllib.parse.quote(spelled)}")
    check(f"/ticket?id={spelled} finds HC-7731", code == 200 and body.get("id") == "HC-7731", f"{code} {body}")
check("digits that match no ticket are still a 404", get(f"{SITE}/ticket?id=HC-773")[0] == 404)

print("== the room can open the ticket desk: support-<cluster> (2026-10-28 call) ==")


def page(url: str) -> tuple[int, str, str]:
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read().decode()


code, ctype, html_page = page(f"{SITE}/")
check("/ is an HTML page", code == 200 and ctype.startswith("text/html"), ctype)
check("it lists every ticket by id", all(t in html_page for t in site.TICKETS))
check("it shows HC-7731's hidden instruction, so the room can see what the bot read",
      "IGNORE ALL PREVIOUS INSTRUCTIONS" in html_page)
check("ticket text is escaped, not injected as markup", "<script" not in html_page.lower())
code, ctype, one_page = page(f"{SITE}/HC-7731")
check("/HC-7731 is that ticket's own page", code == 200 and "Hazel Bramblewick" in one_page
      and "Barnaby" not in one_page)
CONF = (AI / "console.conf").read_text()
block = re.search(r"server \{[^{}]*server_name ~\^support[^;]*;.*?\n\}\n", CONF, re.S)
check("console.conf has a server for support-<cluster>", block is not None)
body_txt = block.group(0) if block else ""
for d in ("agenticburn.com", "burritobot.co"):
    rx = re.search(r"server_name (~\^support[^;]+);", body_txt)
    check(f"it answers support-attackme.{d}", bool(rx) and re.fullmatch(rx.group(1)[1:], f"support-attackme.{d}"))
check("it proxies to the fake-ticket Service", "fake-ticket.agent.svc.cluster.local:8080" in body_txt)
rx = re.search(r"server_name (~\^[^;]+);", body_txt)
check("it also answers the bare support.burritobot.co (#685)",
      bool(rx) and re.fullmatch(rx.group(1)[1:], "support.burritobot.co") is not None)
check("GET and POST only: tickets are filed with a POST (#685)", "limit_except GET POST" in body_txt)
check("/landed is refused from outside: only deploy_app, in the cluster, reports a deployment",
      re.search(r"location = /landed \{\s*deny all;", body_txt) is not None)
check("the visitor's address is passed on, for their name", "X-Forwarded-For" in body_txt)
check("a ticket body is capped at the edge", "client_max_body_size" in body_txt)
FLEET_SRC = (REPO / "infra/terraform/fleet/fleet.sh").read_text()
hosts = " ".join(re.findall(r'^readonly WIB_(?:SERVICE|VILLAIN)_HOSTS="([^"]*)"', FLEET_SRC, re.M)).split()
check("fleet.sh publishes support-<cluster>", "support" in hosts, str(hosts))

print("== read_support_ticket, against stand-ins for guard-proxy and LLM Guard ==")
state = {"guards": {"input_classifier": False}, "guards_up": True, "llm_up": True, "scans": [], "auth": []}


class Guards(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if not state["guards_up"]:
            self.send_response(503); self.end_headers(); return  # noqa: E702
        data = json.dumps(state["guards"]).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()  # noqa: E702
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class LLMGuard(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        state["scans"].append(req)
        state["auth"].append(self.headers.get("Authorization"))
        if not state["llm_up"]:
            self.send_response(500); self.end_headers(); return  # noqa: E702
        data = json.dumps({"is_valid": "IGNORE ALL PREVIOUS INSTRUCTIONS" not in req["prompt"]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()  # noqa: E702
        self.wfile.write(data)

    def log_message(self, *a):
        pass


guards_srv, GUARDS = serve(Guards)
llm_srv, LLM = serve(LLMGuard)

emitted: list[dict] = []


class _StandInMCP:
    def __init__(self, *a, **kw) -> None:
        pass

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP, emit=emitted.append,
                                                  _now=lambda: "2026-10-29T00:00:00.000Z")
import os  # noqa: E402

os.environ["LLM_GUARD_TOKEN"] = "witb-test-token"
m = load("workshop_mcp", AI / "workshop-mcp-server.py")
m.TICKET_SITE_URL, m.GUARD_PROXY_URL, m.LLM_GUARD_URL = SITE, GUARDS, LLM

out = m.read_support_ticket("HC-7731")
check("guard off: the ticket comes back with its hidden paragraph", site.C6_PAYLOAD in out
      and "Ticket HC-7731 [open] from Hazel Bramblewick: cannot list my pods" in out)
check("guard off: LLM Guard is not asked", state["scans"] == [])

state["guards"]["input_classifier"] = True
out = m.read_support_ticket("HC-7731")
check("guard on: the ticket comes back withheld", m.TICKET_WITHHELD in out)
check("guard on: nothing of the paragraph reaches the model", "IGNORE" not in out and site.C6_IMAGE not in out
      and site.C6_DEPLOYMENT not in out)
check("LLM Guard scanned the body, as guard-proxy scans a prompt",
      state["scans"] and state["scans"][-1] == {"prompt": site.TICKETS["HC-7731"]["body"],
                                                "scanners_suppress": ["BanTopics"]})
check("with the token LLM Guard expects", state["auth"][-1] == "Bearer witb-test-token")
check("the withhold is logged as ticket_withheld for the leaderboard",
      emitted and emitted[-1]["event"] == "ticket_withheld" and emitted[-1]["ticket_id"] == "HC-7731")

out = m.read_support_ticket("HC-7702")
check("guard on: a clean ticket still comes back whole", site.TICKETS["HC-7702"]["body"] in out
      and m.TICKET_WITHHELD not in out)

state["llm_up"] = False
out = m.read_support_ticket("HC-7731")
check("guard on and LLM Guard failing: the ticket is withheld (fail closed)", m.TICKET_WITHHELD in out
      and "IGNORE" not in out)
state["llm_up"] = True

state["guards_up"] = False
out = m.read_support_ticket("HC-7731")
check("guard-proxy unreadable counts as off: the wide-open bot is the default", site.C6_PAYLOAD in out)
state["guards_up"] = True
state["guards"]["input_classifier"] = False

check("an unknown ticket says so", "no ticket" in m.read_support_ticket("HC-0000"))
check("no id asks for one", m.read_support_ticket("  ").startswith("provide a ticket id"))
m.TICKET_SITE_URL = "http://127.0.0.1:9"
check("a site that does not answer says the desk is unavailable",
      m.read_support_ticket("HC-7731").startswith("ticket desk unavailable"))

for s in (site_srv, guards_srv, llm_srv):
    s.shutdown()

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All fake ticket checks passed.")
