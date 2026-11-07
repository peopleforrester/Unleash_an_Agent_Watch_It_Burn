# ABOUTME: Runs remove-untrusted-room-workloads (#990) through the Kyverno CLI on what deploy_app really applies: with the
# ABOUTME: guardrails on, the room's untrusted workloads are deleted and the internal registry's and the platform's stay.
# SUITE: e2e (needs the kyverno CLI v1.19.1 on PATH)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. The policy deletes from the agent namespace, where the platform runs too, so what it decides is the whole risk:
# a wrong condition takes agentgateway or BurritoBot itself off the cluster in front of the room. A render check can
# say the expressions are there; the CLI, the engine the cleanup controller runs, says which objects they delete.
# The resources are the bodies deploy_app sends to the API server (gitops/ai-layer/workshop-mcp-server.py, with its
# HTTP call stubbed), so the room label the policy keys on is the one deploy_app stamps, not a copy of it.
#
# The CLI cannot answer resource.Get for a ValidatingPolicy (its context file takes no policies.kyverno.io kinds), so
# the guardrails-on condition is set to true, then false, here; verify/test_guardrails_switch.py holds that condition
# to deny-external-registries at Deny, and the live check in decisions.md (#990, run 17969) ran it on a cluster.
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import kubecon_probe as kp  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
AI = REPO / "gitops/ai-layer"
POLICY = REPO / "policies/kyverno-breakout/remove-untrusted-room-workloads.yaml"
WANT_VERSION = "1.19.1"
# The condition the test replaces, as the policy writes it. A reworded gate fails here by name, not as a case below.
GATE = ('resource.Get("policies.kyverno.io/v1", "validatingpolicies", "", "deny-external-registries") '
        ".spec.validationActions.exists(a, a == 'Deny')")
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


cli = os.environ.get("KYVERNO_CLI") or shutil.which("kyverno")
if not cli:
    print("FAIL: the kyverno CLI is not on PATH (set KYVERNO_CLI to its path). Install v1.19.1 from "
          "https://github.com/kyverno/kyverno/releases/tag/v1.19.1 (kyverno-cli_v1.19.1_<os>_<arch>.tar.gz).",
          file=sys.stderr)
    sys.exit(1)
ver = subprocess.run([cli, "version"], capture_output=True, text=True).stdout
if f"Version: {WANT_VERSION}" not in ver:
    print(f"FAIL: kyverno CLI is not v{WANT_VERSION} (the deployed engine); got: {ver.strip()!r}", file=sys.stderr)
    sys.exit(1)

policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
gates = [c for c in policy["spec"]["conditions"] if c["name"] == "guardrails-on"]
if len(gates) != 1 or " ".join(gates[0]["expression"].split()) != GATE:
    print(f"FAIL: {POLICY.relative_to(REPO)} has no condition guardrails-on reading exactly {GATE!r}; "
          "the test sets that condition to true and false, so update GATE with the policy", file=sys.stderr)
    sys.exit(1)


# deploy_app, its HTTP call stubbed: every apply's body is kept, as the API server would receive it.
class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def get_context(self):
        # No request in flight, as the real FastMCP has none outside its transport; deploy_app reads the
        # request's X-Witch-Name through it (#995) and so finds no name here.
        raise LookupError("a stand-in FastMCP: no MCP request in flight")

    def tool(self, *a, **kw):
        return lambda f: f


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
os.environ["JOKER_SCALE_DOWN_SECONDS"] = "3600"
m = load("workshop_mcp_room_cleanup", AI / "workshop-mcp-server.py")
os.environ.pop("JOKER_SCALE_DOWN_SECONDS", None)
m._ns = lambda: "agent"
m._report = lambda *a, **kw: None
KINDS = {"/apis/apps/v1": [("Deployment", "deployments"), ("StatefulSet", "statefulsets"),
                           ("DaemonSet", "daemonsets"), ("ReplicaSet", "replicasets")],
         "/apis/batch/v1": [("Job", "jobs"), ("CronJob", "cronjobs")],
         "/api/v1": [("Pod", "pods")]}
applied = {}


def fake_req(method, path, body=None, content_type="application/json"):
    if method == "GET":
        base = path.split("?")[0]
        if base in KINDS:
            return 200, json.dumps({"resources": [{"kind": k, "name": n} for k, n in KINDS[base]]})
        return 404, "{}"  # no live object yet, so deploy_app keeps the selector it wrote
    if method == "PATCH" and "/scale" not in path:
        obj = json.loads(body)
        applied[obj["metadata"]["name"]] = obj
    return 201, "{}"


m._req = fake_req
INTERNAL = kp.INTERNAL_IMAGE  # Challenge 3's image on registry.burritobot.co (#775)
PUBLIC = "quay.io/prometheus/busybox:latest"
TPL = {"metadata": {"labels": {"app": "x"}}, "spec": {"containers": [{"name": "c", "image": PUBLIC}]}}


def deploy_app(manifest):
    m.deploy_app(manifest if isinstance(manifest, str) else json.dumps(manifest), requested_by="Agatha the Banshee")


def workload(kind, name, image, init=None, api="apps/v1"):
    pod = {"containers": [{"name": "c", "image": image}]}
    if init:
        pod["initContainers"] = [{"name": "init", "image": init}]
    if kind == "Pod":
        return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name}, "spec": pod}
    tmpl = {"metadata": {"labels": {"app": name}}, "spec": {"restartPolicy": "Never", **pod} if api == "batch/v1" else pod}
    if kind == "CronJob":
        return {"apiVersion": api, "kind": kind, "metadata": {"name": name},
                "spec": {"schedule": "*/5 * * * *", "jobTemplate": {"spec": {"template": tmpl}}}}
    spec = {"template": tmpl} if api == "batch/v1" else {"selector": {"matchLabels": {"app": name}}, "template": tmpl}
    return {"apiVersion": api, "kind": kind, "metadata": {"name": name}, "spec": spec}


# What the room deploys while the guardrails are off.
deploy_app("Tron")                                          # an app's name: the landing page on public.ecr.aws (#939)
deploy_app("redis:8")                                       # Docker Hub's redis, moved to its public.ecr.aws copy
deploy_app(workload("Deployment", "quay-app", PUBLIC))
deploy_app(workload("Deployment", "init-public", INTERNAL, init=PUBLIC))
deploy_app(workload("Deployment", "lookalike", "registry.burritobot.co.evil.example/burritobot/maintenance-shell:1"))
deploy_app(workload("StatefulSet", "room-sts", PUBLIC))
deploy_app(workload("DaemonSet", "room-ds", PUBLIC))
deploy_app(workload("Pod", "room-pod", PUBLIC))
deploy_app(workload("Job", "room-job", PUBLIC, api="batch/v1"))
deploy_app(workload("CronJob", "room-cron", PUBLIC, api="batch/v1"))
# What the room deploys from the internal registry: Challenge 3's maintenance-shell and a room Joker.
deploy_app(workload("Deployment", "maintenance-shell", INTERNAL))
deploy_app(workload("Deployment", "joker-agatha", INTERNAL))
deploy_app(workload("CronJob", "internal-cron", INTERNAL, api="batch/v1"))
# A room manifest named after a platform Deployment: deploy_app applies it with force over Argo CD's object.
deploy_app(workload("Deployment", "guard-proxy", PUBLIC))

room = {name: obj for name, obj in applied.items()}
check("deploy_app applied every room workload the test asked for", len(room) == 14, str(sorted(room)))
# The API server's record of who applied what, as `kubectl get --show-managed-fields` reads it on the cluster.
WORKSHOP_MCP = {"manager": "workshop-mcp", "operation": "Apply", "apiVersion": "apps/v1"}
for obj in room.values():
    obj["metadata"]["managedFields"] = [WORKSHOP_MCP]
room["guard-proxy"]["metadata"]["managedFields"].insert(
    0, {"manager": "argocd-controller", "operation": "Apply", "apiVersion": "apps/v1"})
check("the landing page's image is outside the internal registry",
      room.get("tron", {}).get("spec", {}).get("template", {}).get("spec", {}).get("containers", [{}])[0]
      .get("image", "").startswith("public.ecr.aws/"))

# What deploy_app never made: the platform's own workloads, and the children of the room's.
agentgateway = workload("Deployment", "agentgateway", "cr.agentgateway.dev/agentgateway:v1.7.0")
workshop_agent = workload("Deployment", "workshop-agent", "ghcr.io/kagent-dev/kagent/golang-adk:0.10.1")
platform_pod = workload("Pod", "guard-proxy-abc12", "ghcr.io/peopleforrester/watch-it-burn:python-3.12-slim")
owner = {"apiVersion": "apps/v1", "kind": "Deployment", "name": "quay-app", "uid": "1", "controller": True}
child_rs = json.loads(json.dumps(room["quay-app"]))
child_rs.update(kind="ReplicaSet", metadata={"name": "quay-app-6d4cf56db6", "ownerReferences": [owner]})
child_pod = {"apiVersion": "v1", "kind": "Pod",
             "metadata": {"name": "quay-app-6d4cf56db6-x7k2p", "labels": room["quay-app"]["spec"]["template"]["metadata"]["labels"],
                          "ownerReferences": [{**owner, "kind": "ReplicaSet", "name": "quay-app-6d4cf56db6"}]},
             "spec": room["quay-app"]["spec"]["template"]["spec"]}
elsewhere = json.loads(json.dumps(room["quay-app"]))
elsewhere["metadata"] = {"name": "in-apps", "namespace": "apps"}
others = [agentgateway, workshop_agent, platform_pod, child_rs, child_pod]
for o in others:
    o["metadata"]["namespace"] = "agent"


def run(gate):
    """{resource name: delete | keep} for the policy over every resource, its guardrails-on condition set to gate."""
    pol = json.loads(json.dumps(policy))
    for c in pol["spec"]["conditions"]:
        if c["name"] == "guardrails-on":
            c["expression"] = gate
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        (t / "policy.yaml").write_text(json.dumps(pol))
        (t / "res.yaml").write_text("\n---\n".join(json.dumps(r) for r in [*room.values(), *others, elsewhere]))
        r = subprocess.run([cli, "apply", str(t / "policy.yaml"), "--resource", str(t / "res.yaml"),
                            "--policy-report", "--output-format", "json"], capture_output=True, text=True, timeout=300)
    if "Error:" in r.stderr or "Error:" in r.stdout or "{" not in r.stdout:
        return {"__cli__": (r.stderr or r.stdout).strip()[-400:]}
    report = json.loads(r.stdout[r.stdout.find("{"):])
    got = {}
    for res in report.get("results") or []:
        for ref in res.get("resources", []):
            # The CLI reads a DeletingPolicy's verdict as pass, "resource matched" (deleted), or fail, "resource did
            # not match" (kept). Anything else is read as neither, and fails the case it lands on.
            verdict = {("pass", "resource matched"): "delete", ("fail", "resource did not match"): "keep"}
            got[ref["name"]] = verdict.get((res["result"], res.get("message", "")), f"{res['result']}: {res.get('message')}")
    return got


print("== guardrails on (deny-external-registries at Deny): the room's untrusted workloads are deleted ==")
on = run("true")
if "__cli__" in on:
    check("the kyverno CLI evaluates the DeletingPolicy", False, on["__cli__"])
else:
    for name, why in (("tron", "the landing page an app's name gets, on public.ecr.aws"),
                      ("redis", "Docker Hub's redis, which deploy_app moved to public.ecr.aws"),
                      ("quay-app", "a Deployment from quay.io"),
                      ("init-public", "an internal container with a public init container"),
                      ("lookalike", "a host that only starts with the internal registry's name"),
                      ("room-sts", "a StatefulSet"), ("room-ds", "a DaemonSet"), ("room-pod", "a bare Pod"),
                      ("room-job", "a Job"), ("room-cron", "a CronJob")):
        check(f"deleted: {why} ({name})", on.get(name) == "delete", f"got {on.get(name, 'not matched')}")
    for name, why in (("maintenance-shell", "Challenge 3's maintenance-shell, from registry.burritobot.co"),
                      ("joker-agatha", "a room Joker from registry.burritobot.co"),
                      ("internal-cron", "a CronJob from registry.burritobot.co"),
                      ("guard-proxy", "the platform's guard-proxy, which Argo CD applies, after the room's manifest "
                                      "of that name put the room label and a public image on it"),
                      ("agentgateway", "the platform's agentgateway, external but never deploy_app's"),
                      ("workshop-agent", "BurritoBot itself, from ghcr.io/kagent-dev"),
                      ("guard-proxy-abc12", "a platform Pod"),
                      ("quay-app-6d4cf56db6", "a room Deployment's ReplicaSet, which goes with its owner"),
                      ("quay-app-6d4cf56db6-x7k2p", "that ReplicaSet's Pod, which goes with it")):
        check(f"kept: {why}", on.get(name) == "keep", f"got {on.get(name, 'not matched')}")
    check("a room workload outside the agent namespace is not matched at all", "in-apps" not in on, str(on.get("in-apps")))

print("== guardrails off (deny-external-registries at Audit): nothing is deleted ==")
off = run("false")
if "__cli__" in off:
    check("the kyverno CLI evaluates the DeletingPolicy", False, off["__cli__"])
else:
    deleted = sorted(n for n, v in off.items() if v != "keep")
    check("every workload is kept, the room's untrusted ones too", not deleted and "tron" in off, str(deleted))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All breakout room cleanup checks passed.")
