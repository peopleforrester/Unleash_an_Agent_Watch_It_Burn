# ABOUTME: Live half of deny-llm-endpoint-bypass (#333) and restrict-agent-spawned-workloads (#490): creates pods of
# ABOUTME: the bypass shapes in the agent namespace and reads what Kyverno and the NetworkPolicies make of each.
# SUITE: e2e
"""Needs kubectl and CONTEXT naming a guarded cluster (Kyverno and the ai-layer). Every missing prerequisite
is a failure with the reason, never a skip.

Why (#333). The policy is the one structural control between the agent and a full guardrail bypass: a pod
in the agent namespace without the workshop-agent label is outside the egress NetworkPolicy, so it can
reach a model with every guard-proxy toggle out of the path. It ships Audit, so a policy that matched
nothing would look exactly like a policy with nothing to report. test_kyverno_cel_policies.py proves the
expression on fixture requests; this proves that the installed engine, its webhook and its reports
controller actually turn a real pod of that shape into a `fail` in a PolicyReport.

What it creates, in NAMESPACE, all labelled wib.test/run=<id> and deleted again on the way out (success,
failure or Ctrl-C). Nothing here calls any endpoint: the env vars are only declared.
  * a bare Pod with OPENAI_BASE_URL at api.openai.com                         -> fail
  * a Deployment with ANTHROPIC_BASE_URL at api.anthropic.com, the agent's own -> fail, on its Pod
    shape (it can create Deployments, and the policy judges the Pods they make)
  * a Deployment NAMED guard-proxy-*, which the old name exemption waved through -> fail, on its Pod
  * a Pod whose init container sets OPENAI_API_BASE                           -> fail
  * a Pod whose base URL points at guard-proxy                                 -> pass
The pass case is what makes the fails mean something: a policy that failed every pod would also fail
the four above. It also reads the reports of the running guard-proxy and agentgateway pods, which must
pass: that is the precondition the policy's header names for ever promoting it to Deny.

Why (#490). deny-llm-endpoint-bypass sees only a DECLARED public endpoint. The bypass an agent would actually
use declares none, so these shapes are made AS the agent (impersonating agent-sa, which the agent runs as) and
judged by the controls that do catch them:
  * a Pod with no endpoint env at all, the SDK's default          -> admitted, and no egress to the internet
  * a Pod reading the endpoint from a ConfigMap, by envFrom        -> admitted, and no egress to the internet
  * a Pod reading it by valueFrom configMapKeyRef                  -> admitted, and no egress to the internet
  * a Deployment whose pods run as agent-sa (Bedrock over PrivateLink with the agent's own credentials)
                                                                   -> refused by restrict-agent-spawned-workloads
  * a Pod running as agentgateway, the gateway's Bedrock identity -> refused
  * a Pod labelled app.kubernetes.io/name=console, whose egress platform-console-egress opens -> refused
"No egress to the internet" is read off the live NetworkPolicies: some Egress policy selects the pod, and no
policy that selects it allows a peer outside private address space. No packet is sent.

Before any of that, the policy on the cluster must be the one in policies/kyverno/: a result for a
different expression says nothing about this repo's file.

Usage: CONTEXT=<kube-context> [NAMESPACE=agent] python3 verify/test_llm_bypass_live.py
"""
from __future__ import annotations

import ipaddress
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import uuid

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
POLICY_FILE = REPO / "policies/kyverno/deny-llm-endpoint-bypass.yaml"
POLICY = "deny-llm-endpoint-bypass"
MESSAGE = "This pod sets an LLM endpoint pointing at a public API."
SPAWN_FILE = REPO / "policies/kyverno/restrict-agent-spawned-workloads.yaml"
SPAWN = "restrict-agent-spawned-workloads"
AS_IDENTITY = "may not run as a ServiceAccount that holds Bedrock credentials"
AS_CONSOLE = "may not carry a label that a NetworkPolicy opens to the internet"
AGENT = "system:serviceaccount:agent:agent-sa"
CONTEXT = os.environ.get("CONTEXT", "")
NS = os.environ.get("NAMESPACE", "agent")
# The reports controller rescans every 30s (gitops/apps/kyverno.yaml); admission results land sooner.
# Four rescans covers a busy controller and a Deployment whose Pod takes a moment to be created.
REPORT_TIMEOUT_S = 150
# Signed, so verify-image-signatures (Deny) admits it; on ghcr.io/peopleforrester, so the registry wall does.
IMAGE = ("ghcr.io/peopleforrester/watch-it-burn:busybox-1.36"
         "@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662")

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
    print("All live deny-llm-endpoint-bypass and restrict-agent-spawned-workloads checks passed.")


KUBECTL = shutil.which("kubectl")


def kubectl(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    return subprocess.run([KUBECTL, "--context", CONTEXT, *args], input=stdin, capture_output=True, text=True,
                          timeout=60)


def kjson(*args: str) -> dict | None:
    r = kubectl(*args, "-o", "json")
    return json.loads(r.stdout) if r.returncode == 0 else None


print("== prerequisites ==")
check("kubectl is on PATH", KUBECTL is not None)
check("CONTEXT names the cluster to run against", bool(CONTEXT))
if failures:
    finish()
r = kubectl("--request-timeout=15s", "get", "--raw", "/readyz")
check(f"cluster for context {CONTEXT!r} is reachable", r.returncode == 0, r.stderr.strip())
if failures:
    finish()
check(f"namespace {NS} exists", kjson("get", "namespace", NS) is not None)
live = kjson("get", f"validatingpolicies.policies.kyverno.io/{POLICY}")
check(f"ValidatingPolicy {POLICY} is installed (no Kyverno or no policy: this is not a guarded cluster)",
      live is not None)
if failures:
    finish()

want = yaml.safe_load(POLICY_FILE.read_text())["spec"]
have = live["spec"]


def same(field: str) -> bool:
    return (have.get(field) or []) == (want.get(field) or [])


# The fields that decide what matches and what the verdict is. The API server adds defaults elsewhere.
for field in ("validationActions", "matchConditions", "variables"):
    check(f"live spec.{field} is the repo's", same(field), f"cluster: {have.get(field)!r}")
check("live validation expressions are the repo's",
      [v.get("expression") for v in have.get("validations") or []]
      == [v.get("expression") for v in want.get("validations") or []],
      "the cluster runs a different policy; sync the kyverno-policies Application first")
check("live namespaceSelector is the repo's",
      have.get("matchConstraints", {}).get("namespaceSelector")
      == want["matchConstraints"]["namespaceSelector"])
status = (live.get("status") or {}).get("conditionStatus") or {}
check("Kyverno reports the policy ready (webhook configured, reports controller may read pods)",
      status.get("ready") is True, json.dumps(status.get("conditions")))

spawn = kjson("get", f"validatingpolicies.policies.kyverno.io/{SPAWN}")
check(f"ValidatingPolicy {SPAWN} is installed", spawn is not None)
if failures:
    finish()
want_spawn, have_spawn = yaml.safe_load(SPAWN_FILE.read_text())["spec"], spawn["spec"]
for field in ("validationActions", "matchConditions", "variables"):
    check(f"live {SPAWN} spec.{field} is the repo's",
          (have_spawn.get(field) or []) == (want_spawn.get(field) or []), f"cluster: {have_spawn.get(field)!r}")
check(f"live {SPAWN} validation expressions are the repo's",
      [v.get("expression") for v in have_spawn.get("validations") or []]
      == [v.get("expression") for v in want_spawn.get("validations") or []])
status = (spawn.get("status") or {}).get("conditionStatus") or {}
check(f"Kyverno reports {SPAWN} ready", status.get("ready") is True, json.dumps(status.get("conditions")))
r = kubectl("auth", "can-i", "create", "pods", "-n", NS, f"--as={AGENT}")
check("agent-sa may create pods in the namespace (else the shapes below are not the agent's to make)",
      r.stdout.strip() == "yes", (r.stdout + r.stderr).strip())
if failures:
    finish()

RUN = uuid.uuid4().hex[:6]
RUN_LABEL = f"wib.test/run={RUN}"


def container(name: str, env: dict[str, str], **extra) -> dict:
    return {"name": name, "image": IMAGE, "command": ["sleep", "600"],
            "env": [{"name": k, "value": v} for k, v in env.items()], **extra,
            "resources": {"limits": {"cpu": "20m", "memory": "16Mi"}, "requests": {"cpu": "5m", "memory": "8Mi"}},
            "securityContext": {"allowPrivilegeEscalation": False, "runAsNonRoot": True, "runAsUser": 65534,
                                "capabilities": {"drop": ["ALL"]}}}


def pod_spec(containers: list[dict], init: list[dict] | None = None) -> dict:
    spec = {"containers": containers, "automountServiceAccountToken": False, "terminationGracePeriodSeconds": 0}
    if init:
        spec["initContainers"] = init
    return spec


def labels(case: str) -> dict:
    # Deliberately NOT app.kubernetes.io/name: workshop-agent: unlabelled is the bypass shape.
    return {"wib.test/run": RUN, "wib.test/case": case}


def pod(name: str, case: str, spec: dict) -> dict:
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": NS, "labels": labels(case)},
            "spec": spec}


def deployment(name: str, case: str, spec: dict) -> dict:
    return {"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": name, "namespace": NS, "labels": labels(case)},
            "spec": {"replicas": 1, "selector": {"matchLabels": labels(case)},
                     "template": {"metadata": {"labels": labels(case)}, "spec": spec}}}


OPENAI = {"OPENAI_BASE_URL": "https://api.openai.com/v1"}
CASES = [  # (case label, expected result, what it is)
    ("bare-pod", "fail", "a bare Pod with OPENAI_BASE_URL at api.openai.com"),
    ("deployment", "fail", "a Deployment's Pod with ANTHROPIC_BASE_URL at api.anthropic.com"),
    ("named-like-guard-proxy", "fail", "a Deployment named guard-proxy-* (the old name exemption's hole)"),
    ("init-container", "fail", "a Pod whose init container sets OPENAI_API_BASE"),
    ("routed", "pass", "a Pod whose OPENAI_BASE_URL points at guard-proxy"),
]
objects = [
    pod(f"llm-bypass-pod-{RUN}", "bare-pod", pod_spec([container("c", OPENAI)])),
    deployment(f"llm-bypass-deploy-{RUN}", "deployment",
               pod_spec([container("c", {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"})])),
    deployment(f"guard-proxy-llm-bypass-{RUN}", "named-like-guard-proxy", pod_spec([container("c", OPENAI)])),
    pod(f"llm-bypass-init-{RUN}", "init-container",
        pod_spec([container("c", {})], init=[container("i", {"OPENAI_API_BASE": "https://api.openai.com/v1"})])),
    pod(f"llm-routed-{RUN}", "routed",
        pod_spec([container("c", {"OPENAI_BASE_URL": f"http://guard-proxy.{NS}.svc.cluster.local:8080/v1"})])),
]


# The #490 shapes, made as the agent. None declares a public endpoint as a literal, so the policy above passes
# them all; what has to hold is the network for the first three and the refusal for the last three.
ENDPOINTS = f"llm-endpoints-{RUN}"
AGENT_OBJECTS = [
    {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": ENDPOINTS, "namespace": NS, "labels": labels("cm")},
     "data": {"OPENAI_BASE_URL": "https://api.openai.com/v1"}},
    pod(f"llm-default-endpoint-{RUN}", "default-endpoint", pod_spec([container("c", {})])),
    pod(f"llm-envfrom-{RUN}", "envfrom",
        pod_spec([container("c", {}, envFrom=[{"configMapRef": {"name": ENDPOINTS}}])])),
    pod(f"llm-valuefrom-{RUN}", "valuefrom", pod_spec([container("c", {}, env=[
        {"name": "OPENAI_BASE_URL", "valueFrom": {"configMapKeyRef": {"name": ENDPOINTS, "key": "OPENAI_BASE_URL"}}}])])),
]
OPEN_SHAPES = ["default-endpoint", "envfrom", "valuefrom"]


def as_sa(obj: dict, sa: str) -> dict:
    spec = obj["spec"]["template"]["spec"] if obj["kind"] == "Deployment" else obj["spec"]
    spec["serviceAccountName"] = sa
    return obj


def console_pod() -> dict:
    p = pod(f"llm-console-impostor-{RUN}", "console-label", pod_spec([container("c", {})]))
    p["metadata"]["labels"]["app.kubernetes.io/name"] = "console"
    return p


REFUSED = [  # (what it is, object, the refusal's message)
    ("a Deployment whose pods run as agent-sa (Bedrock over PrivateLink, the agent's own credentials)",
     as_sa(deployment(f"llm-bedrock-{RUN}", "bedrock-agent-sa", pod_spec([container("c", {})])), "agent-sa"),
     AS_IDENTITY),
    ("a Pod running as agentgateway, the gateway's Bedrock identity",
     as_sa(pod(f"llm-bedrock-gw-{RUN}", "bedrock-agentgateway", pod_spec([container("c", {})])), "agentgateway"),
     AS_IDENTITY),
    ("a Pod labelled app.kubernetes.io/name=console, whose egress is open", console_pod(), AS_CONSOLE),
]


def selects(sel: dict, pod_labels: dict) -> bool:
    if any(pod_labels.get(k) != v for k, v in (sel.get("matchLabels") or {}).items()):
        return False
    for e in sel.get("matchExpressions") or []:
        k, op, vals = e["key"], e["operator"], e.get("values") or []
        ok = {"In": k in pod_labels and pod_labels[k] in vals, "NotIn": pod_labels.get(k) not in vals,
              "Exists": k in pod_labels, "DoesNotExist": k not in pod_labels}[op]
        if not ok:
            return False
    return True


def internet_paths(pod_labels: dict) -> list[str]:
    """Why a pod with these labels could reach the internet, read off the live NetworkPolicies. Empty: it cannot."""
    nps = (kjson("get", "networkpolicies.networking.k8s.io", "-n", NS) or {"items": []})["items"]
    egress = [np for np in nps if "Egress" in (np["spec"].get("policyTypes") or [])
              and selects(np["spec"].get("podSelector") or {}, pod_labels)]
    if not egress:
        return ["no Egress NetworkPolicy selects it, so its egress is unrestricted"]
    out = []
    for np in egress:
        for rule in np["spec"].get("egress") or []:
            if not rule.get("to"):
                out.append(f"{np['metadata']['name']} allows egress to every destination")
            for peer in rule.get("to") or []:
                cidr = (peer.get("ipBlock") or {}).get("cidr")
                if cidr and not ipaddress.ip_network(cidr, strict=False).is_private:
                    out.append(f"{np['metadata']['name']} allows {cidr}")
    return out


def results_by_uid() -> dict[str, dict]:
    """This policy's result for every Pod in NS that has one, keyed by the Pod's UID."""
    reports = kjson("get", "policyreports.wgpolicyk8s.io", "-n", NS) or {"items": []}
    out = {}
    for rep in reports["items"]:
        scope = rep.get("scope") or {}
        if scope.get("kind") != "Pod":
            continue
        for res in rep.get("results") or []:
            if res.get("policy") == POLICY:
                out[scope.get("uid")] = res
    return out


def pod_uids(selector: str) -> list[tuple[str, str]]:
    pods = kjson("get", "pods", "-n", NS, "-l", selector) or {"items": []}
    return [(p["metadata"]["name"], p["metadata"]["uid"]) for p in pods["items"]]


try:
    print(f"== creating the bypass-shaped workloads (run {RUN}) ==")
    r = kubectl("apply", "-f", "-", stdin="\n---\n".join(json.dumps(o) for o in objects))
    check("the API server admitted every probe (the policy is Audit, so a refusal is some other policy's)",
          r.returncode == 0, (r.stderr or r.stdout).strip())
    if failures:
        finish()

    print(f"== reading the PolicyReports (up to {REPORT_TIMEOUT_S}s) ==")
    deadline = time.monotonic() + REPORT_TIMEOUT_S
    found: dict[str, tuple[str, dict | None]] = {}
    while True:
        by_uid = results_by_uid()
        for case, _, _ in CASES:
            pods = pod_uids(f"wib.test/run={RUN},wib.test/case={case}")
            if pods:
                name, uid = pods[0]
                found[case] = (name, by_uid.get(uid))
        if all(found.get(case, ("", None))[1] for case, _, _ in CASES) or time.monotonic() > deadline:
            break
        time.sleep(5)
    for case, verdict, what in CASES:
        name, res = found.get(case, ("(no pod was created)", None))
        got = f"{res.get('result')}: {res.get('message', '')!r}" if res else "no result for this policy"
        ok = res is not None and res.get("result") == verdict and (verdict == "pass" or MESSAGE in res.get("message", ""))
        check(f"{what} is reported {verdict.upper()} ({name})", ok, got)

    print("== the shapes deny-llm-endpoint-bypass cannot see, made as the agent (#490) ==")
    r = kubectl("apply", f"--as={AGENT}", "-f", "-", stdin="\n---\n".join(json.dumps(o) for o in AGENT_OBJECTS))
    check("agent-sa may create a pod with no endpoint env, and ones reading it from a ConfigMap",
          r.returncode == 0, (r.stderr or r.stdout).strip())
    for case in OPEN_SHAPES:
        made = pod_uids(f"wib.test/run={RUN},wib.test/case={case}")
        paths = internet_paths(labels(case))
        check(f"the {case} pod exists and no NetworkPolicy lets it reach a public API", bool(made) and not paths,
              "; ".join(paths) or "the pod was not created")
    paths = internet_paths({**labels("console-label"), "app.kubernetes.io/name": "console"})
    check("the console label really does open egress (why the policy refuses it)", bool(paths),
          "no live NetworkPolicy opens egress for app.kubernetes.io/name=console; update the policy's egressLabels")
    for what, obj, message in REFUSED:
        r = kubectl("create", f"--as={AGENT}", "-f", "-", stdin=json.dumps(obj))
        err = " ".join(((r.stderr or "") + " " + (r.stdout or "")).split())
        check(f"{what} is refused by {SPAWN}",
              r.returncode != 0 and f"Policy {SPAWN} failed:" in err and message in err, err or "it was admitted")

    print("== the guarded path itself passes (the precondition for ever promoting to Deny) ==")
    by_uid = results_by_uid()
    for app in ("guard-proxy", "agentgateway"):
        pods = pod_uids(f"app.kubernetes.io/name={app}")
        check(f"{app} has a pod in {NS}", bool(pods))
        for name, uid in pods:
            res = by_uid.get(uid)
            check(f"{name} is reported PASS", res is not None and res.get("result") == "pass",
                  f"{res.get('result')}: {res.get('message', '')!r}" if res else "no result for this policy")
finally:
    r = kubectl("delete", "deployments,pods,configmaps", "-n", NS, "-l", RUN_LABEL, "--ignore-not-found",
                "--wait=false")
    print(f"\n  cleanup ({RUN_LABEL}): {'done' if r.returncode == 0 else 'FAILED: ' + r.stderr.strip()}")

finish()
