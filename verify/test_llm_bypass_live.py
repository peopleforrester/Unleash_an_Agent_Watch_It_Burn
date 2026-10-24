# ABOUTME: Live half of deny-llm-endpoint-bypass (#333): creates pods of the bypass shape in the agent namespace
# ABOUTME: and reads the PolicyReport Kyverno writes for each, which a CLI run on fixtures cannot show.
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

Before any of that, the policy on the cluster must be the one in policies/kyverno/: a result for a
different expression says nothing about this repo's file.

Usage: CONTEXT=<kube-context> [NAMESPACE=agent] python3 verify/test_llm_bypass_live.py
"""
from __future__ import annotations

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
    print("All live deny-llm-endpoint-bypass checks passed.")


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
if failures:
    finish()

RUN = uuid.uuid4().hex[:6]
RUN_LABEL = f"wib.test/run={RUN}"


def container(name: str, env: dict[str, str]) -> dict:
    return {"name": name, "image": IMAGE, "command": ["sleep", "600"],
            "env": [{"name": k, "value": v} for k, v in env.items()],
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
    r = kubectl("delete", "deployments,pods", "-n", NS, "-l", RUN_LABEL, "--ignore-not-found", "--wait=false")
    print(f"\n  cleanup ({RUN_LABEL}): {'done' if r.returncode == 0 else 'FAILED: ' + r.stderr.strip()}")

finish()
