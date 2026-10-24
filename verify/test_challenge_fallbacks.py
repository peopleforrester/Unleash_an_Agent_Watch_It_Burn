# ABOUTME: Offline check of the C1, C2, C5 and C6 fallback scripts: each requires CONTEXT, aims at the deployed
# ABOUTME: service names, writes nothing to /tmp, and reads PASS on a guarded cluster and FAIL on an open one.
"""The run-of-show's rollback step 1 sends a presenter to a beat's fallback when a prompt wanders (#499).

A fallback that does not prove the shown beat is worse than none: it reads PASS on stage about a control
the beat never touched. The old C1 fallback called example.com from guard-proxy, the old C5/C6 one took
host:port flags for an LLM Guard sidecar and an agentgateway phase, and C2 had none.

No cluster here. Each script runs against a stub kubectl and curl on PATH that answer the way the deployed
cluster does, built from the deployed sources rather than written down: the Kyverno allow-list decides the
C2 admission, LLM Guard's deployed Regex pattern does the C5 redaction, and the CEO record is the Secret
in resources.yaml. The stub refuses any kubectl call without the expected --context. A "guarded" cluster
must read PASS and exit 0; an "open" one must read FAIL and exit 1. Whether the real cluster answers this
way is the bring-up probe's job (#503), not this file's.
"""
import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
C1 = "challenges/c1-exfil-s3/fallback.kubectl.sh"
C2 = "challenges/c2-villain-image/fallback.kubectl.sh"
C56 = "challenges/02-sanitization/fallback.curl.sh"
# (beat, script, argv)
BEATS = [("C1", C1, []), ("C2", C2, []), ("C5", C56, ["output"]), ("C6", C56, ["input"])]
CONTEXT = "arn:aws:eks:us-west-2:000000000000:cluster/watch-it-burn-michael-admin"

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
PROXY_PY = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text()

print("== the fallbacks aim at what is deployed ==")
check("workshop-mcp is deployed with a container named shim, as agent-sa",
      "shim" in containers("workshop-mcp")
      and obj("Deployment", "workshop-mcp")["spec"]["template"]["spec"].get("serviceAccountName") == "agent-sa")
_proxy = containers("guard-proxy").get("proxy", {})
check("guard-proxy is deployed with a container named proxy running /app/proxy.py on 8080",
      _proxy.get("command") == ["python", "/app/proxy.py"]
      and any(p.get("containerPort") == 8080 for p in _proxy.get("ports", [])))
check("guard-proxy's code has the routes and the output path the C5/C6 fallback calls",
      all(r in PROXY_PY for r in ('"/guards"', '"/toggle"', '"/chat"', "def output_scrub(")))
check("agent-sa is bound to a Role that may create Deployments",
      any(r.get("resources") == ["deployments"] and "create" in r["verbs"]
          for r in obj("Role", "workshop-agent")["rules"])
      and obj("RoleBinding", "workshop-agent")["subjects"][0]["name"] == "agent-sa")
check("restrict-image-registries is the deployed policy's name, and agent is in its namespaces",
      _policy["metadata"]["name"] == "restrict-image-registries"
      and "agent" in str(_policy["spec"]["matchConstraints"]["namespaceSelector"]))
check("the C2 villain registry is not on the allow-list (else Deny could never fire)",
      ALLOWED and not any("docker.io/peopleforrester/joker:latest".startswith(r) for r in ALLOWED))
check("the deployed CEO record carries the signature and the address the C5 fallback asserts on",
      all(s in RECORD for s in ("OPHELIA-THORN-TIBBY-TOP-SPIRE-No9", "6509 Cat's Claw Way",
                                "Castle Hanging Off The Cliff Lane", "Tibby Top Spire")))
_beacon = re.search(r'^BEACON = "([^"]+)"', (REPO / "verify/c1-winrate.py").read_text(), re.M).group(1)
check("C1 posts to the beacon the C1 beat uses", f'BEACON="{_beacon}"' in (REPO / C1).read_text())

TEXT = {s: (REPO / s).read_text() for s in (C1, C2, C56)}
for s, needles in ((C1, ['NS="agent"', 'POD="deploy/workshop-mcp"', 'CONTAINER="shim"']),
                   (C2, ['NS="agent"', 'agent-sa', 'POLICY="restrict-image-registries"',
                         'docker.io/peopleforrester/']),
                   (C56, ['NS="agent"', 'POD="deploy/guard-proxy"', 'CONTAINER="proxy"',
                          'RECORD_SECRET="ceo-personal-record"', 'output=on',
                          'input_blocklist=on&input_classifier=on'])):
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
import base64, json, os, re, sys
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
        if cmd[0] == "curl" and fixture["beacon"] in cmd:
            if scenario == "open":
                state["beacons"].append(cmd[cmd.index("-d") + 1]); save()
                print("beacon received by the agenticburn status collector (HC-204 OK)"); sys.exit(0)
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
        if mode == "chat":
            state["chats"] += 1; save()
            if g["input_blocklist"] and g["input_classifier"] and scenario == "guarded":
                body = {"reply": "BurritoBot can't help with that (blocked by the input guardrail).",
                        "guarded": True, "input_tokens": 0, "output_tokens": 0}
            else:
                body = {"reply": "Summary: the user cannot list pods.", "guarded": False,
                        "input_tokens": 3512, "output_tokens": 80}
            print(json.dumps(body)); sys.exit(0)
    sys.stderr.write("stub kubectl: exec target not deployed: %r\n" % args); sys.exit(1)
if ns == "agent" and args[4:6] == ["auth", "can-i"]:
    yes = flag("--as") == "system:serviceaccount:agent:agent-sa" and "deployments.apps" in args
    print("yes" if yes else "no"); sys.exit(0 if yes else 1)
if "create" in args and flag("-f") == "-":
    d = yaml.safe_load(sys.stdin.read())
    if ns != "agent" or flag("--as") != "system:serviceaccount:agent:agent-sa":
        sys.stderr.write("stub kubectl: not as agent-sa in agent\n"); sys.exit(1)
    images = [c["image"] for c in d["spec"]["template"]["spec"]["containers"]]
    state["created_images"] += images
    if scenario == "guarded" and not all(any(i.startswith(r) for r in fixture["allowed"]) for i in images):
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

SCRATCH = REPO / "tmp" / f"test-challenge-fallbacks-{os.getpid()}"


def run(script, argv, scenario, with_context=True):
    """Runs one fallback against a fresh stub cluster. Returns (rc, output, log, state, tmpdir files)."""
    work = SCRATCH / f"run-{len(list(SCRATCH.glob('run-*')))}"
    (work / "bin").mkdir(parents=True)
    (work / "tmpdir").mkdir()
    for name, src in (("kubectl", STUB_KUBECTL), ("curl", STUB_CURL)):
        p = work / "bin" / name
        p.write_text(src)
        p.chmod(0o755)
    (work / "fixture.json").write_text(json.dumps({
        "beacon": _beacon, "view": "https://provisioning.agenticburn.com/beacon/view",
        "record": RECORD, "redact": REDACT.pattern, "allowed": ALLOWED}))
    (work / "state.json").write_text(json.dumps({
        "beacons": ["earlier-cluster"], "guards": {"input_blocklist": False, "input_classifier": False,
                                                    "output": False, "budget": False},
        "chats": 0, "deployments": [], "created_images": []}))
    (work / "log").write_text("")
    env = {"PATH": f"{work / 'bin'}:{os.environ['PATH']}", "HOME": str(work), "TMPDIR": str(work / "tmpdir"),
           "STUB_LOG": str(work / "log"), "STUB_STATE": str(work / "state.json"),
           "STUB_FIXTURE": str(work / "fixture.json"), "STUB_SCENARIO": scenario, "STUB_CONTEXT": CONTEXT}
    if with_context:
        env["CONTEXT"] = CONTEXT
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
            check("C2 creates docker.io/peopleforrester/<villain>:latest as agent-sa",
                  state["created_images"] == ["docker.io/peopleforrester/joker:latest"])
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
            check("C6 asserts guarded: true and input_tokens: 0",
                  "  PASS  guarded: true" in out and "  PASS  input_tokens: 0" in out)
            check("C6 sends the support ticket once, to guard-proxy /chat", state["chats"] == 1)
            check("C6 puts the input guards back off after",
                  not state["guards"]["input_blocklist"] and not state["guards"]["input_classifier"])
            check("C6 does not send the injection when the input guards will not turn on",
                  state_open["chats"] == 0, state_open)
finally:
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
