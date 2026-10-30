# ABOUTME: Offline check of the C1, C2, C5, C6 and C7 fallback scripts: each requires CONTEXT, aims at the deployed
# ABOUTME: service names, writes nothing to /tmp, and reads PASS on a guarded cluster and FAIL on an open one.
"""The run-of-show's rollback step 1 sends a presenter to a beat's fallback when a prompt wanders (#499).

A fallback that does not prove the shown beat is worse than none: it reads PASS on stage about a control
the beat never touched. The old C1 fallback called example.com from guard-proxy, the old C5/C6 one took
host:port flags for an LLM Guard sidecar and an agentgateway phase, and C2 had none.

No cluster here. Each script runs against a stub kubectl and curl on PATH that answer the way the deployed
cluster does, built from the deployed sources rather than written down: the Kyverno allow-list decides the
C2 admission, LLM Guard's deployed Regex pattern does the C5 redaction, and the CEO record is the Secret
in resources.yaml. For C7 on an admin cluster the stub's web terminal runs the script's own MCP exchange against a
fake :3003 gateway that serves the committed rule and evil-mcp's own tool output (#517). On a workshop cluster the
stub's guard-proxy runs the script's own weather question against a fake agent that answers with the toolset kagent
last rolled out, from the committed Agent tools and the real toggle-mcp-authz-on.sh patch (#545). The stub refuses
any kubectl call without the expected --context. A "guarded" cluster
must read PASS and exit 0; an "open" one must read FAIL and exit 1. Whether the real cluster answers this
way is the bring-up probe's job (#503), not this file's.
"""
import base64
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import resource_limits as rl  # noqa: E402
from agent_probe import MCP_PROMPT  # noqa: E402
from promo_villains import ref as promo_ref  # noqa: E402
from registry_allowlist import allowed, refused_paths  # noqa: E402
C1 = "challenges/c1-exfil-s3/fallback.kubectl.sh"
C2 = "challenges/c2-villain-image/fallback.kubectl.sh"
C56 = "challenges/02-sanitization/fallback.curl.sh"
C7 = "challenges/03-bad-mcp-excessive-agency/fallback.curl.sh"
# (beat, script, argv)
BEATS = [("C1", C1, []), ("C2", C2, []), ("C5", C56, ["output"]), ("C6", C56, ["input"]), ("C7", C7, [])]
CONTEXT = "arn:aws:eks:us-west-2:000000000000:cluster/watch-it-burn-private"

failures = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f": {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# --- What is deployed ----------------------------------------------------------------------------------
DOCS = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]


def obj(kind, name):
    return next((d for d in DOCS if d.get("kind") == kind and d["metadata"]["name"] == name), None)


def containers(name):
    d = obj("Deployment", name)
    return {c["name"]: c for c in d["spec"]["template"]["spec"]["containers"]} if d else {}


RECORD = obj("Secret", "ceo-personal-record")["stringData"]["record"]
_scanners = yaml.safe_load(obj("ConfigMap", "llm-guard-scanners")["data"]["scanners.yml"])
REDACT = re.compile(_scanners["output_scanners"][0]["params"]["patterns"][0])
_policy = yaml.safe_load((REPO / "policies/kyverno/restrict-image-registries.yaml").read_text())
_allowed_expr = next(v["expression"] for v in _policy["spec"]["variables"] if v["name"] == "allowedRegistries")
ALLOWED = re.findall(r"'([^']+)'", _allowed_expr)
REFUSED = refused_paths()
PROXY_PY = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text()
# C7: the rule agentgateway serves for evil-mcp on :3003, what evil-mcp's tools return, and the terminal's toggles.
_gateway_docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/agentgateway.yaml").read_text()) if d]
C7_CONFIG = next(d for d in _gateway_docs if d.get("kind") == "ConfigMap"
                 and d["metadata"]["name"] == "agentgateway-c7-config")["data"]["config.yaml"]
C7_OPEN, C7_NARROWED = "true", 'mcp.tool.name == "get_weather"'
EVIL_URL = obj("RemoteMCPServer", "evil-mcp")["spec"]["url"]
SHIM_PY = (REPO / "challenges/03-bad-mcp-excessive-agency/evil-mcp-shim/server.py").read_text()
MCP_SENTINEL = re.search(r'"FAKE_MCP_SENTINEL", "([^"]+)"', SHIM_PY).group(1)
WEATHER = re.search(r'def get_weather\(\).*?return "([^"]+)"', SHIM_PY, re.S).group(1)
ENTRY = (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_text()


def terminal_says(cmd):
    """What the terminal's <cmd> prints when it switched C7 at the gateway: the echo lines of its gateway) branch."""
    body = re.search(rf"cat > \"\$HOME/{cmd}\" <<'EOS'\n(.*?)\nEOS\n", ENTRY, re.S)
    branch = re.search(r"^\s*gateway\)\n(.*?);;", body.group(1) if body else "", re.M | re.S)
    return "\n".join(re.findall(r'echo "(.*)"', branch.group(1))) if branch else ""


TERMINAL_SAYS = {c: terminal_says(c) for c in ("guard-mcp-on", "guard-mcp-off")}

print("== the fallbacks aim at what is deployed ==")
check("workshop-mcp is deployed with a container named shim, as its own workshop-mcp ServiceAccount (#553)",
      "shim" in containers("workshop-mcp")
      and obj("Deployment", "workshop-mcp")["spec"]["template"]["spec"].get("serviceAccountName") == "workshop-mcp")
_proxy = containers("guard-proxy").get("proxy", {})
check("guard-proxy is deployed with a container named proxy running /app/proxy.py on 8080",
      _proxy.get("command") == ["python", "/app/proxy.py"]
      and any(p.get("containerPort") == 8080 for p in _proxy.get("ports", [])))
check("guard-proxy's code has the routes and the output path the C5/C6 fallback calls",
      all(r in PROXY_PY for r in ('"/guards"', '"/toggle"', '"/chat"', "def output_scrub(")))
check("agent-sa and workshop-mcp are bound to a Role that may create Deployments",
      any(r.get("resources") == ["deployments"] and "create" in r["verbs"]
          for r in obj("Role", "workshop-agent")["rules"])
      and {s["name"] for s in obj("RoleBinding", "workshop-agent")["subjects"]} == {"agent-sa", "workshop-mcp"})
check("restrict-image-registries is the deployed policy's name, and agent is in its namespaces",
      _policy["metadata"]["name"] == "restrict-image-registries"
      and "agent" in str(_policy["spec"]["matchConstraints"]["namespaceSelector"]))
check("the C2 villain is refused by the allow-list (else Deny could never fire)",
      ALLOWED and REFUSED and not allowed(promo_ref("joker")))
check("the deployed CEO record carries the signature and the address the C5 fallback asserts on",
      all(s in RECORD for s in ("OPHELIA-THORN-TIBBY-TOP-SPIRE-No9", "6509 Cat's Claw Way",
                                "Castle Hanging Off The Cliff Lane", "Tibby Top Spire")))
check("web-terminal is deployed with a container named ttyd, as the web-terminal ServiceAccount",
      "ttyd" in containers("web-terminal")
      and obj("Deployment", "web-terminal")["spec"]["template"]["spec"].get("serviceAccountName") == "web-terminal")
check("the evil-mcp RemoteMCPServer dials agentgateway's :3003 bind", EVIL_URL == "http://agentgateway.agent:3003/mcp")
_c7_marked = [line.strip() for line in C7_CONFIG.split("\n") if line.rstrip().endswith("# c7-rule")]
check("agentgateway-c7-config serves 3003 to evil-mcp, with one '# c7-rule' line committed 'true'",
      "port: 3003" in C7_CONFIG and "name: evil-mcp" in C7_CONFIG and _c7_marked == ["- 'true' # c7-rule"], _c7_marked)
check("the terminal's rule rewrite narrows to the rule the C7 fallback expects",
      """RULES = {"on": "'mcp.tool.name == \\"get_weather\\"'", "off": "'true'"}""" in ENTRY)
check("guard-mcp-on and guard-mcp-off say 'at the gateway' when they switched the rule (the C7 fallback reads it)",
      all("at the gateway" in t for t in TERMINAL_SAYS.values()), TERMINAL_SAYS)
_drift = (REPO / "policies/kyverno/block-argocd-drift.yaml").read_text()
check("block-argocd-drift lets the web terminal edit agentgateway-c7-config",
      "system:serviceaccount:agent:web-terminal" in _drift and "agentgateway-c7-config" in _drift)
check("the C7 sentinel is the one evil-mcp returns", MCP_SENTINEL == "FAKE-MCP-EXFIL-sentinel-4c1d")
_beacon = re.search(r'^BEACON = "([^"]+)"', (REPO / "verify/c1-winrate.py").read_text(), re.M).group(1)
check("C1 posts to the beacon the C1 beat uses", f'BEACON="{_beacon}"' in (REPO / C1).read_text())

_spec = importlib.util.spec_from_file_location("ticket_site", REPO / "gitops/ai-layer/ticket_site.py")
ticket_site = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ticket_site)
_t = ticket_site.TICKETS[ticket_site.C6_TICKET_ID]
TICKET_SHOWN = f"Ticket {_t['id']} [{_t['status']}] from {_t['customer']}: {_t['subject']}\n\n{_t['body']}"
_MCP = (REPO / "gitops/ai-layer/workshop-mcp-server.py").read_text()
_withheld = re.search(r'^TICKET_WITHHELD = "([^"]+)"$', _MCP, re.M)
check("workshop-mcp names the guard's withheld notice", _withheld is not None)
TICKET_WITHHELD_SHOWN = (f"Ticket {_t['id']} [{_t['status']}] from {_t['customer']}: {_t['subject']}\n"
                         f"{_withheld.group(1) if _withheld else ''}: the ticket body was flagged as a prompt-injection "
                         "attempt and was not loaded.")
check("C6's fallback looks for the notice the tool writes and the Deployment the paragraph asks for",
      _withheld is not None and f'WITHHELD="{_withheld.group(1)}"' in (REPO / C56).read_text()
      and f'PAYLOAD_MARK="{ticket_site.C6_DEPLOYMENT}"' in (REPO / C56).read_text()
      and f'TICKET_ID="{ticket_site.C6_TICKET_ID}"' in (REPO / C56).read_text())

TEXT = {s: (REPO / s).read_text() for s in (C1, C2, C56, C7)}
for s, needles in ((C1, ['NS="agent"', 'POD="deploy/workshop-mcp"', 'CONTAINER="shim"']),
                   (C2, ['NS="agent"', 'SA="system:serviceaccount:${NS}:workshop-mcp"', 'POLICY="restrict-image-registries"',
                         'ghcr.io/peopleforrester/lab-platform/promo/']),
                   (C56, ['NS="agent"', 'POD="deploy/guard-proxy"', 'CONTAINER="proxy"',
                          'RECORD_SECRET="ceo-personal-record"', 'output=on',
                          'input_blocklist=on&input_classifier=on', 'MCP_POD="deploy/workshop-mcp"',
                          'MCP_CONTAINER="shim"']),
                   (C7, ['NS="agent"', 'POD="deploy/web-terminal"', 'CONTAINER="ttyd"', f'GATEWAY="{EVIL_URL}"',
                         f'SENTINEL="{MCP_SENTINEL}"', 'C7_CONFIGMAP="agentgateway-c7-config"', 'get application lab-bootstrap',
                         'bash "${TERMINAL_HOME}/$1"', 'toggle guard-mcp-off', 'toggle guard-mcp-on',
                         'AGENT="workshop-agent"', 'toggle-mcp-authz-on.sh', 'PROXY_POD="deploy/guard-proxy"',
                         'PROXY_CONTAINER="proxy"', 'set_tools --off', 'set_tools --on'])):
    check(f"{s} names {', '.join(needles)}", all(n in TEXT[s] for n in needles))

print("\n== no scratch outside the repo's tmp/, kube context explicit ==")
for s, t in TEXT.items():
    check(f"{s} never names /tmp", "/tmp" not in t)
    check(f"{s} makes no mktemp scratch", "mktemp" not in t and "TMPDIR" not in t)
    check(f"{s} requires CONTEXT and routes kubectl through --context",
          'CONTEXT="${CONTEXT:?' in t and 'kubectl --context "${CONTEXT}"' in t)
    check(f"{s} has no --gateway/--sidecar host:port flags", "--gateway" not in t and "--sidecar" not in t)
    check(f"{s} carries no verify-at-build markers", "verify-at-build" not in t)
    check(f"{s} is executable", os.access(REPO / s, os.X_OK))

# --- The stub cluster -----------------------------------------------------------------------------------
STUB_KUBECTL = r'''#!/usr/bin/env python3
import base64, json, os, re, subprocess, sys
from urllib.parse import parse_qs
import yaml
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
if "--context" not in args or args[args.index("--context") + 1] != os.environ["STUB_CONTEXT"]:
    sys.stderr.write("stub kubectl: refused, no --context " + os.environ["STUB_CONTEXT"] + "\n")
    sys.exit(97)
fixture = json.load(open(os.environ["STUB_FIXTURE"]))
state = json.load(open(os.environ["STUB_STATE"]))
scenario = os.environ["STUB_SCENARIO"]
def save():
    json.dump(state, open(os.environ["STUB_STATE"], "w"))
def flag(name):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None
ns = flag("-n")
if "exec" in args:
    target, container, cmd = args[args.index("exec") + 1], flag("-c"), args[args.index("--") + 1:]
    if (ns, target, container) == ("agent", "deploy/workshop-mcp", "shim"):
        if cmd == ["true"]:
            sys.exit(0)
        if cmd[:2] == ["python3", "-c"] and "read_support_ticket" in cmd[2]:
            # C6: the deployed tool, called in the tool pod. It withholds the ticket when guard-proxy's input
            # classifier is on, as read_support_ticket does; an open cluster's guard never turns on.
            compile(cmd[2], "ticket-snippet", "exec")
            state["ticket_reads"].append({"id": cmd[3], **state["guards"]}); save()
            print(fixture["withheld"] if state["guards"]["input_classifier"] else fixture["ticket"]); sys.exit(0)
        if cmd[0] == "curl" and fixture["beacon"] in cmd:
            if scenario == "open":
                state["beacons"].append(cmd[cmd.index("-d") + 1]); save()
                print("beacon received by the status collector (HC-204 OK)"); sys.exit(0)
            sys.stderr.write("curl: (28) Connection timed out after 15002 milliseconds\n"
                             "command terminated with exit code 28\n")
            sys.exit(28)
    if (ns, target, container) == ("agent", "deploy/guard-proxy", "proxy") and \
            cmd[:4] == ["env", "OTEL_SDK_DISABLED=true", "python3", "-c"]:
        compile(cmd[4], "pod-snippet", "exec")
        mode, rest = cmd[5], cmd[6:]
        g = state["guards"]
        if mode == "guards":
            print(json.dumps(g)); sys.exit(0)
        if mode == "toggle":
            if scenario != "open":  # an open cluster's guard-proxy has no such guard: the flip does nothing
                for k, v in parse_qs(rest[0]).items():
                    g[k] = v[0] == "on"
                save()
            print(json.dumps(g)); sys.exit(0)
        if mode == "reply":
            text = rest[0]
            if g["output"]:
                text = None if scenario == "failclosed" else re.sub(fixture["redact"], "[REDACTED]", text)
            print(json.dumps({"output_guard": g["output"], "reply": text})); sys.exit(0)
        if mode == "ask":
            # The C7 workshop branch's weather question, run against the fake agent instead of the pod's own root.
            if rest[0] != "http://localhost:8080/":
                sys.stderr.write("stub kubectl: %r is not guard-proxy's own root\n" % rest[0]); sys.exit(1)
            p = subprocess.run([sys.executable, "-I", "-c", cmd[4], "ask", fixture["fake_agent"], *rest[1:]],
                               capture_output=True, text=True, timeout=30)
            sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); sys.exit(p.returncode)
        if mode == "chat":
            state["chats"] += 1; save()
            if g["input_blocklist"] and g["input_classifier"] and scenario == "guarded":
                body = {"reply": "BurritoBot can't help with that "
                                  "(blocked by the input guardrail: PromptInjection, risk 1.00).",
                        "guarded": True, "input_tokens": 0, "output_tokens": 0}
            else:
                body = {"reply": "Summary: the user cannot list pods.", "guarded": False,
                        "input_tokens": 3512, "output_tokens": 80}
            print(json.dumps(body)); sys.exit(0)
    if (ns, target, container) == ("agent", "deploy/web-terminal", "ttyd"):
        if cmd[:2] != ["env", "HOME=/home/student"]:  # the terminal's commands read their kubeconfig from HOME
            sys.stderr.write("stub kubectl: the terminal's commands need HOME=/home/student\n"); sys.exit(1)
        cmd = cmd[2:]
        if cmd == ["true"]:
            sys.exit(0)
        if cmd in (["bash", "/home/student/guard-mcp-on"], ["bash", "/home/student/guard-mcp-off"]):
            name = cmd[1].rsplit("/", 1)[1]
            state["toggles"].append(name)
            rule = fixture["narrowed"] if name == "guard-mcp-on" else fixture["open"]
            if state["rule"] != rule:
                state["rule"], state["rule_at"] = rule, state["clock"]
            save()
            print(fixture["terminal_says"][name]); sys.exit(0)
        if cmd[:2] == ["python3", "-c"]:
            # The script's own MCP exchange, run against the fake :3003 gateway instead of the pod's.
            if cmd[3] != fixture["gateway"]:
                sys.stderr.write("stub kubectl: %r is not the evil-mcp url\n" % cmd[3]); sys.exit(1)
            p = subprocess.run([sys.executable, "-I", "-c", cmd[2], fixture["fake_gateway"], *cmd[4:]],
                               capture_output=True, text=True, timeout=30)
            sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); sys.exit(p.returncode)
    sys.stderr.write("stub kubectl: exec target not deployed: %r\n" % args); sys.exit(1)
# Which profile the cluster's root, lab-bootstrap, was applied with: its lab-platform/profile label (#609).
if ns == "argocd" and args[4:7] == ["get", "application", "lab-bootstrap"] \
        and "jsonpath={.metadata.labels.lab-platform/profile}" in args:
    sys.stdout.write("attendee" if scenario.startswith("workshop") else "admin"); sys.exit(0)
# C7 on a workshop cluster: the Agent's tools, the toggle's merge patch, and kagent rolling workshop-agent. kagent
# bumps the Deployment's generation KAGENT_DELAY fake seconds after a patch that changed evil-mcp's list (never, on
# "workshop-norollout"); the roll serves the new list (an "workshop-open" kagent keeps serving the full one).
def evil(tools):
    return sorted(next(t["mcpServer"].get("toolNames") or [] for t in tools if t["mcpServer"]["name"] == "evil-mcp"))
if ns == "agent" and args[4:7] == ["get", "agent", "workshop-agent"] and flag("-o") == "json":
    print(json.dumps({"metadata": {"name": "workshop-agent"}, "spec": {"declarative": {"tools": state["tools"]}}}))
    sys.exit(0)
if ns == "agent" and args[4:7] == ["patch", "agent", "workshop-agent"] and "--type=merge" in args:
    tools = json.loads(flag("-p"))["spec"]["declarative"]["tools"]
    names = evil(tools)
    state["patches"].append(names)
    if names != evil(state["tools"]):
        state["pending"], state["patched_at"] = names, state["clock"]
    state["tools"] = tools; save()
    print("agent.kagent.dev/workshop-agent patched"); sys.exit(0)
if ns == "agent" and args[4:7] == ["get", "deployment", "workshop-agent"] and flag("-o") == "jsonpath={.metadata.generation}":
    if state["pending"] is not None and scenario != "workshop-norollout" \
            and state["clock"] - state["patched_at"] >= fixture["kagent_delay"]:
        state["generation"] += 1
        state["served_tools"] = state["served_tools"] if scenario == "workshop-open" else state["pending"]
        state["pending"] = None; save()
    print(state["generation"], end=""); sys.exit(0)
if ns == "agent" and args[4:7] == ["rollout", "status", "deployment/workshop-agent"]:
    print('deployment "workshop-agent" successfully rolled out'); sys.exit(0)
if ns == "agent" and args[4:7] == ["get", "configmap", "agentgateway-c7-config"] and flag("-o") == "json":
    text = re.sub(r"- '.*' # c7-rule$", lambda m: "- '%s' # c7-rule" % state["rule"], fixture["c7_config"], flags=re.M)
    print(json.dumps({"metadata": {"name": "agentgateway-c7-config", "resourceVersion": "4711"},
                      "data": {"config.yaml": text}})); sys.exit(0)
if ns == "agent" and args[4:6] == ["auth", "can-i"]:
    yes = flag("--as") == "system:serviceaccount:agent:workshop-mcp" and "deployments.apps" in args
    print("yes" if yes else "no"); sys.exit(0 if yes else 1)
if "create" in args and flag("-f") == "-":
    d = yaml.safe_load(sys.stdin.read())
    if ns != "agent" or flag("--as") != "system:serviceaccount:agent:workshop-mcp":
        sys.stderr.write("stub kubectl: not as workshop-mcp in agent\n"); sys.exit(1)
    images = [c["image"] for c in d["spec"]["template"]["spec"]["containers"]]
    state["created_images"] += images
    state["created_manifests"].append(d)
    if scenario == "guarded" and not all(any(i.startswith(r) for r in fixture["allowed"])
                                         and not any(p in i for p in fixture["refused"]) for i in images):
        sys.stderr.write('Error from server: error when creating "STDIN": admission webhook '
                         '"vpol.validate.kyverno.svc-fail" denied the request: Policy restrict-image-registries '
                         'failed: Images must come from allowed registries\n')
        save(); sys.exit(1)
    state["deployments"].append(d["metadata"]["name"]); save()
    print("deployment.apps/%s created" % d["metadata"]["name"]); sys.exit(0)
if "delete" in args and "deployment" in args:
    name = args[args.index("deployment") + 1]
    state["deployments"] = [n for n in state["deployments"] if n != name]; save(); sys.exit(0)
if ns == "agent" and args[4:7] == ["get", "secret", "ceo-personal-record"]:
    print(base64.b64encode(fixture["record"].encode()).decode(), end=""); sys.exit(0)
sys.stderr.write("stub kubectl: unexpected call %r\n" % args); sys.exit(1)
'''

STUB_CURL = r'''#!/usr/bin/env python3
import html, json, os, sys
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(["curl"] + args) + "\n")
fixture = json.load(open(os.environ["STUB_FIXTURE"]))
if fixture["view"] not in args:
    sys.stderr.write("curl: (6) Could not resolve host\n"); sys.exit(6)
state = json.load(open(os.environ["STUB_STATE"]))
n = len(state["beacons"])
rows = "".join("<td class=\"body\">%s</td>" % html.escape(b) for b in state["beacons"])
print('<div class="big" id="beacon-count" data-count="%d">%d</div>%s' % (n, n, rows))
'''

# A fake clock, so the C7 fallback's waits cost no real time: sleep advances it, `date +%s` reads it.
STUB_SLEEP = r'''#!/usr/bin/env python3
import json, os, sys
path = os.environ["STUB_STATE"]
state = json.load(open(path))
state["clock"] += float(sys.argv[1])
json.dump(state, open(path, "w"))
'''
STUB_DATE = r'''#!/usr/bin/env python3
import json, os, sys
if sys.argv[1:] == ["+%%s"]:
    print(1800000000 + int(json.load(open(os.environ["STUB_STATE"]))["clock"])); sys.exit(0)
os.execv(%r, ["date", *sys.argv[1:]])
''' % shutil.which("date")

# The fake :3003 gateway the C7 exchange talks to: streamable HTTP with a session, answers as event streams, and
# mcpAuthorization as agentgateway documents it: a bare CEL string is an allow rule, the rest is denied, so a narrowed rule refuses every tool but get_weather.
# A new rule is served RELOAD fake seconds after the terminal wrote it, on a "guarded" cluster. An "open" one never
# reloads, so the deny never comes; a "down" one stops answering once it serves the narrowed rule.
RELOAD = 6
SESSION = "stub-session-1"
GATEWAY = {}  # the current run's state file and scenario


class FakeGateway(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, code, body=b"", ctype="text/plain", sid=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if sid:
            self.send_header("Mcp-Session-Id", sid)
        self.end_headers()
        self.wfile.write(body)

    def stream(self, msg_id, payload, sid=None):
        msg = json.dumps({"jsonrpc": "2.0", "id": msg_id, **payload})
        self.reply(200, f"event: message\ndata: {msg}\n\n".encode(), "text/event-stream", sid)

    def do_POST(self):
        path = pathlib.Path(GATEWAY["state"])
        state = json.loads(path.read_text())
        if GATEWAY["scenario"] in ("guarded", "down") and state["clock"] - state["rule_at"] >= RELOAD:
            state["served"] = state["rule"]
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        name = (msg.get("params") or {}).get("name")
        state["gateway"].append([self.path, msg.get("method"), name, state["served"]])
        path.write_text(json.dumps(state))
        if self.path != "/mcp":
            return self.reply(404)
        if GATEWAY["scenario"] == "down" and state["served"] == C7_NARROWED:
            return self.reply(503, b"upstream connect error or disconnect/reset before headers")
        if msg.get("method") == "initialize":
            return self.stream(msg["id"], {"result": {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                                                      "serverInfo": {"name": "agentgateway", "version": "1.5.0"}}},
                               SESSION)
        if "id" not in msg:
            return self.reply(202)
        if self.headers.get("Mcp-Session-Id") != SESSION:
            return self.reply(400, b"Session not found")
        if msg.get("method") != "tools/call":
            return self.reply(400, b"unexpected method")
        if state["served"] == C7_NARROWED and name != "get_weather":
            return self.stream(msg["id"], {"error": {"code": -32602, "message": f"Unknown tool: {name}"}})
        text = {"get_weather": WEATHER,
                "read_internal_config": f"internal-config:\n  exfil_target_token: {MCP_SENTINEL}\n"}.get(name)
        if text is None:
            return self.stream(msg["id"], {"error": {"code": -32602, "message": f"Unknown tool: {name}"}})
        return self.stream(msg["id"], {"result": {"content": [{"type": "text", "text": text}], "isError": False}})


FAKE = ThreadingHTTPServer(("127.0.0.1", 0), FakeGateway)
threading.Thread(target=FAKE.serve_forever, daemon=True).start()
FAKE_URL = f"http://127.0.0.1:{FAKE.server_address[1]}/mcp"

# The fake agent behind guard-proxy's A2A root, for C7 on a workshop cluster. It answers message/send with the
# toolset the last roll served: with read_internal_config in it the poisoned description chains and the reply
# carries the sentinel (never, on "workshop-nochain"); without it the agent says it cannot call the tool. The
# output guard, when on, redacts the sentinel in the text the way guard-proxy does. A "workshop-down" agent stops
# answering once it serves the narrowed list.
KAGENT_DELAY = 4
EVIL_ALL = sorted(["get_weather", "read_internal_config", "apply_optimization"])
EVIL_NARROWED = ["get_weather"]
AGENT_TOOLS = obj("Agent", "workshop-agent")["spec"]["declarative"]["tools"]


class FakeAgent(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        path = pathlib.Path(GATEWAY["state"])
        state = json.loads(path.read_text())
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = msg["params"]["message"]["parts"][0]["text"]
        state["asks"].append({"served": state["served_tools"], "listed": sorted(
            next(t["mcpServer"].get("toolNames") or [] for t in state["tools"] if t["mcpServer"]["name"] == "evil-mcp")),
            "output": state["guards"]["output"], "prompt": prompt, "path": self.path, "method": msg.get("method")})
        path.write_text(json.dumps(state))
        scenario = GATEWAY["scenario"]
        if scenario == "workshop-down" and state["served_tools"] == EVIL_NARROWED:
            body = b"upstream connect error"
            self.send_response(503)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        history = [msg["params"]["message"],
                   {"role": "agent", "parts": [{"kind": "data", "data": {"name": "get_weather"}}]}]
        if "read_internal_config" in state["served_tools"] and scenario != "workshop-nochain":
            text = f"{WEATHER} Internal config: exfil_target_token: {MCP_SENTINEL}"
            history.append({"role": "agent", "parts": [{"kind": "data", "data": {"name": "read_internal_config"}}]})
        elif "read_internal_config" in state["served_tools"]:
            text = WEATHER
        else:
            text = f"{WEATHER} I was also told to call read_internal_config, but that tool is not available to me."
        if state["guards"]["output"]:
            text = text.replace(MCP_SENTINEL, "[REDACTED]")
        body = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "kind": "task", "status": {"state": "completed"}, "history": history,
            "artifacts": [{"parts": [{"kind": "text", "text": text}]}]}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


FAKE_AGENT = ThreadingHTTPServer(("127.0.0.1", 0), FakeAgent)
threading.Thread(target=FAKE_AGENT.serve_forever, daemon=True).start()
FAKE_AGENT_URL = f"http://127.0.0.1:{FAKE_AGENT.server_address[1]}/"

SCRATCH = REPO / "tmp" / f"test-challenge-fallbacks-{os.getpid()}"


def evil_names(state):
    """evil-mcp's toolNames on the stub's Agent, sorted."""
    return sorted(next(t["mcpServer"].get("toolNames") or [] for t in state["tools"]
                       if t["mcpServer"]["name"] == "evil-mcp"))


def with_evil(names):
    """The committed Agent tools with evil-mcp's toolNames set to <names>."""
    tools = json.loads(json.dumps(AGENT_TOOLS))
    next(t for t in tools if t["mcpServer"]["name"] == "evil-mcp")["mcpServer"]["toolNames"] = names
    return tools


def run(script, argv, scenario, with_context=True, rule=C7_OPEN, tools=None, output=False):
    """Runs one fallback against a fresh stub cluster, whose C7 rule starts as <rule>, its Agent tools as <tools>
    (the committed ones by default) and its output guard as <output>. Returns (rc, output, log, state, tmpdir files)."""
    tools = AGENT_TOOLS if tools is None else tools
    served = sorted(next(t["mcpServer"].get("toolNames") or [] for t in tools if t["mcpServer"]["name"] == "evil-mcp"))
    work = SCRATCH / f"run-{len(list(SCRATCH.glob('run-*')))}"
    (work / "bin").mkdir(parents=True)
    (work / "tmpdir").mkdir()
    for name, src in (("kubectl", STUB_KUBECTL), ("curl", STUB_CURL), ("sleep", STUB_SLEEP), ("date", STUB_DATE)):
        p = work / "bin" / name
        p.write_text(src)
        p.chmod(0o755)
    (work / "fixture.json").write_text(json.dumps({
        "beacon": _beacon, "view": "https://provisioning.agenticburn.com/beacon/view",
        "record": RECORD, "redact": REDACT.pattern, "allowed": ALLOWED, "refused": REFUSED,
        "gateway": EVIL_URL, "fake_gateway": FAKE_URL, "c7_config": C7_CONFIG, "open": C7_OPEN,
        "narrowed": C7_NARROWED, "terminal_says": TERMINAL_SAYS, "fake_agent": FAKE_AGENT_URL,
        "kagent_delay": KAGENT_DELAY, "ticket": TICKET_SHOWN, "withheld": TICKET_WITHHELD_SHOWN}))
    (work / "state.json").write_text(json.dumps({
        "beacons": ["earlier-cluster"], "guards": {"input_blocklist": False, "input_classifier": False,
                                                    "output": output, "budget": False},
        "chats": 0, "deployments": [], "created_images": [], "created_manifests": [],
        "rule": rule, "served": rule, "rule_at": -1000, "clock": 0, "toggles": [], "gateway": [],
        "tools": tools, "patches": [], "pending": None, "patched_at": 0, "generation": 7, "served_tools": served,
        "asks": [], "ticket_reads": []}))
    (work / "log").write_text("")
    env = {"PATH": f"{work / 'bin'}:{os.environ['PATH']}", "HOME": str(work), "TMPDIR": str(work / "tmpdir"),
           "STUB_LOG": str(work / "log"), "STUB_STATE": str(work / "state.json"),
           "STUB_FIXTURE": str(work / "fixture.json"), "STUB_SCENARIO": scenario, "STUB_CONTEXT": CONTEXT}
    if with_context:
        env["CONTEXT"] = CONTEXT
    GATEWAY.update(state=str(work / "state.json"), scenario=scenario)
    p = subprocess.run(["bash", str(REPO / script), *argv], env=env, cwd=str(work), capture_output=True,
                       text=True, timeout=120)
    log = [json.loads(line) for line in (work / "log").read_text().splitlines()]
    state = json.loads((work / "state.json").read_text())
    return p.returncode, p.stdout + p.stderr, log, state, list((work / "tmpdir").iterdir())


tmp_before = sorted(p.name for p in (REPO / "tmp").iterdir()) if (REPO / "tmp").exists() else []
try:
    for beat, script, argv in BEATS:
        print(f"\n== {beat}: {script} {' '.join(argv)} ==")
        rc, out, log, state, _ = run(script, argv, "guarded", with_context=False)
        check(f"{beat} refuses to run without CONTEXT", rc != 0 and "CONTEXT" in out, out[-200:])
        check(f"{beat} makes no kubectl call without CONTEXT", not [c for c in log if c[:1] != ["curl"]], log)

        rc, out, log, state, tmpfiles = run(script, argv, "guarded")
        check(f"{beat} on a guarded cluster: exit 0, PASS lines, no FAIL",
              rc == 0 and "  PASS  " in out and "  FAIL  " not in out and f"{beat} PROVEN" in out, out)
        check(f"{beat} sends --context {CONTEXT} on every kubectl call",
              all("--context" in c and c[c.index("--context") + 1] == CONTEXT for c in log if c[:1] != ["curl"]))
        check(f"{beat} writes nothing to TMPDIR", not tmpfiles, tmpfiles)

        rc_open, out_open, log_open, state_open, _ = run(script, argv, "open")
        check(f"{beat} on an open cluster: exit 1 and FAIL lines",
              rc_open == 1 and "  FAIL  " in out_open and "NOT PROVEN" in out_open, out_open)

        if beat == "C1":
            execs = [c for c in log if "exec" in c]
            check("C1 runs the POST in workshop-mcp's shim container in agent",
                  any(c[c.index("exec") + 1:c.index("exec") + 4] == ["deploy/workshop-mcp", "-c", "shim"]
                      and c[c.index("-n") + 1] == "agent" and "curl" in c for c in execs))
            check("C1 reads the beacon view before and after", sum(c[:1] == ["curl"] for c in log) == 2)
            check("C1 on an open cluster names the moved count", "does not move" in out_open
                  and "  FAIL  the beacon count does not move" in out_open, out_open)
        if beat == "C2":
            check("C2 creates lab-platform's promo/<villain>:v1 as workshop-mcp",
                  state["created_images"] == [promo_ref("joker")], state["created_images"])
            # #529: on an admin cluster with every policy at Deny, a limit-less Deployment is also refused by
            # require-resource-limits, and whichever webhook answers first is the deny message the room hears.
            check("C2's Deployment satisfies require-resource-limits, so only the registry wall can deny it",
                  len(state["created_manifests"]) == 1 and rl.missing(state["created_manifests"][0]) == [],
                  [rl.missing(m) for m in state["created_manifests"]])
            check("C2 prints the denial naming restrict-image-registries",
                  "  PASS  the denial names restrict-image-registries" in out)
            check("C2 on an open cluster deletes the villain it was let deploy", state_open["deployments"] == [],
                  state_open["deployments"])
        if beat == "C5":
            check("C5 asserts the signature and the address", all(
                f"  PASS  {s}" in out for s in ("OPHELIA-THORN-TIBBY-TOP-SPIRE-No9 is redacted",
                                                "the address is redacted")))
            check("C5 puts the output guard back off after", state["guards"]["output"] is False)
            rc_fc, out_fc, *_ = run(script, argv, "failclosed")
            check("C5 reads FAIL when LLM Guard does not answer (fail closed is not redaction)",
                  rc_fc == 1 and "failed closed" in out_fc, out_fc)
        if beat == "C6":
            check("C6 reads ticket HC-7731 in workshop-mcp's shim, once with the input guards off and once on",
                  [(r["id"], r["input_classifier"]) for r in state["ticket_reads"]]
                  == [("HC-7731", False), ("HC-7731", True)], state["ticket_reads"])
            check("C6 asserts the hidden paragraph first, then the withheld ticket with none of it",
                  all(f"  PASS  {s}" in out for s in ("input guards off: the ticket comes back with its hidden paragraph",
                                                      "the ticket comes back withheld by the input guard",
                                                      "nothing of the hidden paragraph reaches the model")), out)
            check("C6 never calls /chat, so the model is never called", state["chats"] == 0 and state_open["chats"] == 0)
            check("C6 puts the input guards back off after",
                  not state["guards"]["input_blocklist"] and not state["guards"]["input_classifier"])
            check("C6 stops after the allow read when the input guards will not turn on",
                  len(state_open["ticket_reads"]) == 1, state_open["ticket_reads"])
        if beat == "C7":
            execs = [c for c in log if "exec" in c]
            check("C7 runs every command in the web terminal's ttyd container in agent",
                  execs and all(c[c.index("exec") + 1:c.index("exec") + 4] == ["deploy/web-terminal", "-c", "ttyd"]
                                and c[c.index("-n") + 1] == "agent" for c in execs), execs)
            others = [c for c in log if "exec" not in c]
            check("C7 never calls the model: from the laptop it only reads lab-bootstrap's profile and the rule, no curl",
                  all(c[2:7] in (["-n", "argocd", "get", "application", "lab-bootstrap"],
                                 ["-n", "agent", "get", "configmap", "agentgateway-c7-config"]) for c in others),
                  others)
            check("C7 flips the rule with the terminal's guard-mcp-off, then guard-mcp-on, then puts it back",
                  state["toggles"] == ["guard-mcp-off", "guard-mcp-on", "guard-mcp-off"], state["toggles"])
            calls = [g for g in state["gateway"] if g[1] == "tools/call"]
            check("C7 calls only read_internal_config and get_weather, on the gateway's /mcp path",
                  calls and {g[2] for g in calls} == {"read_internal_config", "get_weather"}
                  and all(g[0] == "/mcp" for g in state["gateway"]), state["gateway"])
            check("C7 reads the sentinel with the rule open and the gateway's refusal with it narrowed",
                  f"  PASS  with the rule open, read_internal_config through :3003 returns {MCP_SENTINEL}" in out
                  and "  PASS  with the rule narrowed, the gateway refuses read_internal_config" in out, out)
            delay = re.search(r"the narrowed rule took effect after (\d+) s", out)
            check(f"C7 prints the reload delay (this stub gateway serves a new rule after {RELOAD} s)",
                  delay is not None and RELOAD <= int(delay.group(1)) < RELOAD + 3, out)
            check("C7 leaves the rule as it found it ('true')",
                  state["rule"] == C7_OPEN and "  PASS  the rule is left as it was found ('true'" in out)
            check("C7 on an open cluster names the call the gateway never refused",
                  "  FAIL  with the rule narrowed, the gateway refuses read_internal_config: after 120 s, the "
                  "sentinel came back" in out_open, out_open)
            check("C7 on an open cluster still puts the rule back",
                  state_open["rule"] == C7_OPEN and state_open["toggles"][-1:] == ["guard-mcp-off"], state_open)
            rc_n, out_n, _, state_n, _ = run(script, argv, "guarded", rule=C7_NARROWED)
            check("C7 on a cluster it found narrowed: PROVEN, and the rule is narrowed again after",
                  rc_n == 0 and "C7 PROVEN" in out_n and state_n["rule"] == C7_NARROWED
                  and state_n["toggles"] == ["guard-mcp-off", "guard-mcp-on", "guard-mcp-on"], out_n)
            rc_d, out_d, _, state_d, _ = run(script, argv, "down")
            check("C7 does not count a gateway that stops answering as a refusal",
                  rc_d == 1 and "did not answer" in out_d and "  PASS  with the rule narrowed" not in out_d
                  and state_d["rule"] == C7_OPEN, out_d)
            # A workshop cluster (lab-bootstrap's profile is not admin): the toolNames list, through the weather question (#545).
            rc_w, out_w, log_w, state_w, tmp_w = run(script, argv, "workshop")
            check("C7 on a workshop cluster: exit 0, PASS lines, no FAIL",
                  rc_w == 0 and "  PASS  " in out_w and "  FAIL  " not in out_w and "C7 PROVEN" in out_w, out_w)
            check("C7 on a workshop cluster sends --context on every kubectl call and writes nothing to TMPDIR",
                  all("--context" in c and c[c.index("--context") + 1] == CONTEXT for c in log_w if c[:1] != ["curl"])
                  and not tmp_w)
            check("C7 on a workshop cluster leaves the gateway rule and the web terminal alone",
                  state_w["toggles"] == [] and state_w["rule"] == C7_OPEN
                  and not [c for c in log_w if "deploy/web-terminal" in c or "agentgateway-c7-config" in c], log_w)
            w_execs = [c for c in log_w if "exec" in c]
            check("C7 on a workshop cluster asks in guard-proxy's proxy container in agent",
                  w_execs and all(c[c.index("exec") + 1:c.index("exec") + 4] == ["deploy/guard-proxy", "-c", "proxy"]
                                  and c[c.index("-n") + 1] == "agent" for c in w_execs), w_execs)
            check("C7 on a workshop cluster flips toolNames with toggle-mcp-authz-on.sh --off, --on, then puts it back",
                  state_w["patches"] == [EVIL_ALL, EVIL_NARROWED, EVIL_ALL] and evil_names(state_w) == EVIL_ALL,
                  state_w["patches"])
            check("C7 on a workshop cluster asks the probe's C7 question, marked, as A2A message/send to the root",
                  state_w["asks"] and all(a["prompt"] == MCP_PROMPT + "\n\n[[wib-probe]]" and a["path"] == "/"
                                          and a["method"] == "message/send" for a in state_w["asks"]),
                  state_w["asks"][:1])
            check("C7 on a workshop cluster never asks before kagent has rolled the agent onto the list",
                  all(a["served"] == a["listed"] for a in state_w["asks"]), state_w["asks"])
            check("C7 on a workshop cluster asks once with the full list, then 3 times narrowed",
                  [a["served"] for a in state_w["asks"]] == [EVIL_ALL] + [EVIL_NARROWED] * 3,
                  [a["served"] for a in state_w["asks"]])
            check("C7 on a workshop cluster reads the leak with the list full and none with it narrowed",
                  f"  PASS  with read_internal_config on the list, the weather question returns {MCP_SENTINEL}" in out_w
                  and "  PASS  with the list narrowed to get_weather, 3 weather questions are answered and none "
                      f"returns {MCP_SENTINEL}" in out_w
                  and "  PASS  evil-mcp's toolNames are left as they were found" in out_w, out_w)
            rc_wn, out_wn, _, state_wn, _ = run(script, argv, "workshop", tools=with_evil(["get_weather"]))
            check("C7 on a workshop cluster it found narrowed: PROVEN, and the list is narrowed again after",
                  rc_wn == 0 and "C7 PROVEN" in out_wn and evil_names(state_wn) == EVIL_NARROWED
                  and state_wn["patches"] == [EVIL_ALL, EVIL_NARROWED, EVIL_NARROWED], out_wn)
            rc_wg, out_wg, _, state_wg, _ = run(script, argv, "workshop", output=True)
            check("C7 on a workshop cluster holds the output guard off for the asks and puts it back on",
                  rc_wg == 0 and "C7 PROVEN" in out_wg and state_wg["asks"]
                  and not any(a["output"] for a in state_wg["asks"]) and state_wg["guards"]["output"] is True
                  and "  PASS  the output guard is back on" in out_wg, out_wg)
            rc_wo, out_wo, _, state_wo, _ = run(script, argv, "workshop-open")
            check("C7 on a workshop cluster whose list does not hold: NOT PROVEN, names the leak, list put back",
                  rc_wo == 1 and "NOT PROVEN" in out_wo and "  FAIL  with the list narrowed to get_weather, the weather "
                  f"question is answered without {MCP_SENTINEL}: ask 1 of 3: the reply carried" in out_wo
                  and evil_names(state_wo) == EVIL_ALL, out_wo)
            rc_wc, out_wc, _, state_wc, _ = run(script, argv, "workshop-nochain")
            check("C7 on a workshop cluster where the model never chains: NOT PROVEN, and it never narrows the list",
                  rc_wc == 1 and "  FAIL  with read_internal_config on the list, the weather question returns "
                  f"{MCP_SENTINEL}: 3 asks" in out_wc and EVIL_NARROWED not in state_wc["patches"]
                  and len(state_wc["asks"]) == 3, out_wc)
            rc_wd, out_wd, _, state_wd, _ = run(script, argv, "workshop-down")
            check("C7 on a workshop cluster does not count an agent that stops answering as the list",
                  rc_wd == 1 and "no answer" in out_wd and "  PASS  with the list narrowed" not in out_wd
                  and evil_names(state_wd) == EVIL_ALL, out_wd)
            rc_wr, out_wr, _, state_wr, _ = run(script, argv, "workshop-norollout")
            check("C7 on a workshop cluster where kagent never rolls the agent: NOT PROVEN, no ask on the stale pod",
                  rc_wr == 1 and "  FAIL  kagent rolls deploy/workshop-agent for the new list" in out_wr
                  and all(a["served"] == EVIL_ALL and a["listed"] == EVIL_ALL for a in state_wr["asks"])
                  and evil_names(state_wr) == EVIL_ALL, out_wr)
            rc_wu, out_wu, _, state_wu, _ = run(script, argv, "workshop", tools=with_evil([]))
            check("C7 on a workshop cluster with an empty evil-mcp list (every tool): FAIL, list left alone",
                  rc_wu == 1 and "which neither toggle flag would put back" in out_wu and state_wu["patches"] == []
                  and not state_wu["asks"], out_wu)
finally:
    FAKE.shutdown()
    FAKE_AGENT.shutdown()
    shutil.rmtree(SCRATCH, ignore_errors=True)
tmp_after = sorted(p.name for p in (REPO / "tmp").iterdir()) if (REPO / "tmp").exists() else []
check("the repo's tmp/ is left as it was found", tmp_before == tmp_after, (tmp_before, tmp_after))

print("\n== the run-of-show names each script per beat ==")
ros = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text()
for beat, script, argv in BEATS:
    ref = " ".join([script, *argv])
    check(f"run-of-show names {beat}: {ref}", re.search(rf"{beat}\b[^\n]*`[^`]*{re.escape(ref)}", ros) is not None)

if failures:
    print(f"\nFAILED: {len(failures)}")
    sys.exit(1)
print("\nAll challenge fallback checks passed.")
