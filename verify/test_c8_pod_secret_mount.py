# ABOUTME: Measures Challenge 8's residual gap (#604): the scoped c8 Role stops the agent reading other Secrets
# ABOUTME: through the API, but it keeps `create` on pods, and no admission policy refuses a pod that MOUNTS one.
# SUITE: e2e (needs the kyverno CLI v1.19.1 on PATH)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Spike for issue #604, discovered from peopleforrester/general-knowledge#108 (gap item 4) and feeding the
# deep dive in mrf-engagement-orchestrator#76. Recorded in decisions.md under 2026-10-26 · #604.
#
# The finding, in one line. c8-scoped-role.yaml (gitops/ai-layer/resources.yaml) replaces the broad Role's
# blanket `get`/`list` on Secrets with `get` on ceo-personal-record by name. It KEEPS create/get/list/patch
# on pods. Kubernetes' RBAC good-practices page is explicit that "permission to create workloads ... in a
# namespace implicitly grants access to many other resources in that namespace, such as Secrets ... that can
# be mounted in Pods" (https://kubernetes.io/docs/concepts/security/rbac-good-practices/, read 2026-10-26):
# the kubelet reads a mounted Secret on the pod's behalf at start, authorized by the pod existing, NOT by the
# creator's RBAC on that Secret. So agent-sa, forbidden to read the terminal password through the API under
# the scoped Role, can still read it by creating a pod that mounts the `terminal-auth` Secret. This measures
# the two things #604 asks for.
#
# FIRST: can agent-sa create such a pod, and is it admitted? The RBAC half is read off the scoped Role below
# (create on pods survives the scoping untouched). The admission half is run through the Kyverno CLI, which is
# the same engine the admission controller runs (test_kyverno_cel_policies.py pins it to the deployed
# version). The exploit pod is deliberately benign to every content control the agent namespace has: an
# allowed, signed image, CPU+memory limits, the default ServiceAccount (NOT a Bedrock identity), an ordinary
# label (NOT one a NetworkPolicy trusts), and no public-LLM endpoint env. The only thing left is the Secret it
# mounts and the secretKeyRef env it reads, and every policy still passes it.
#
# SECOND: which admission policy refuses it? None. The agent-namespace policies are run one by one below and
# every verdict is PASS or IGNORED. The control cases are the clincher: the SAME secret-mounting pod flips to
# a denial the instant it runs as a Bedrock ServiceAccount or wears a NetworkPolicy label, which proves the
# engine is live and judging the pod -- and that the Secret mount itself is never the reason for any deny.
#
# If this test's "no policy denies the Secret mount" assertions ever flip to a denial, the closing control
# (a ValidatingPolicy or ValidatingAdmissionPolicy that refuses Secret volumes and secretKeyRef for pods
# created by an agent-namespace identity, bar ceo-personal-record) has landed; move these assertions to its
# test. That control is the #604 follow-up, not this measurement.
#
# The AWS credentials Secret the issue names as an example is no longer in namespace `agent`: #584 moved the
# attendee key to namespace `student-creds`, and a pod's Secret volumes are namespace-local, so that specific
# target is already out of a pod's reach from `agent`. The in-namespace targets this still exposes are the
# ones the scoped Role is meant to protect: `terminal-auth` (the shared terminal login) and `console-tls`
# (the console's TLS private key).
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
POL = REPO / "policies/kyverno"
FLOOR = REPO / "policies/floor/minimal-floor.yaml"
RES = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
WANT_VERSION = "1.19.1"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


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

# agent-sa's groups, as the API server presents them for a namespace ServiceAccount.
AGENT_SA = ("system:serviceaccount:agent:agent-sa",
            ["system:serviceaccounts", "system:serviceaccounts:agent", "system:authenticated"])

# An allowed registry AND a real signature against policies/cosign/watch-it-burn.pub, so neither the registry
# wall nor the signature wall is the reason a verdict lands. Same digest test_kyverno_cel_policies.py uses.
SIGNED = ("ghcr.io/peopleforrester/watch-it-burn:busybox-1.36"
          "@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662")


def exploit_pod(name="secret-harvester", sa="default", labels=None):
    """A pod that reads a Secret other than ceo-personal-record two ways: a volume mount and a secretKeyRef
    env. Benign to every content control: allowed+signed image, CPU+memory limits, no public-LLM endpoint."""
    return {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": name, "namespace": "agent",
                     "labels": labels if labels is not None else {"app": "maintenance"}},
        "spec": {
            "serviceAccountName": sa,
            "containers": [{
                "name": "c", "image": SIGNED,
                "command": ["sh", "-c", "cat /loot/* && printf '%s\\n' \"$STOLEN\""],
                "resources": {"limits": {"cpu": "100m", "memory": "64Mi"}},
                "env": [{"name": "STOLEN", "valueFrom": {
                    "secretKeyRef": {"name": "terminal-auth", "key": "TTYD_CREDENTIAL"}}}],
                "volumeMounts": [{"name": "loot", "mountPath": "/loot", "readOnly": True}],
            }],
            "volumes": [{"name": "loot", "secret": {"secretName": "terminal-auth"}}],
        },
    }


def run(policy, resources, operation="CREATE"):
    """Return {resource name: (result, message)} for one policy over the resources, as agent-sa."""
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        (t / "res.yaml").write_text("\n---\n".join(json.dumps(r) for r in resources))
        (t / "values.yaml").write_text(json.dumps({
            "apiVersion": "cli.kyverno.io/v1alpha1", "kind": "Values",
            "globalValues": {"request.operation": operation}}))
        name, groups = AGENT_SA
        (t / "user.yaml").write_text(json.dumps({
            "apiVersion": "cli.kyverno.io/v1alpha1", "kind": "UserInfo",
            "userInfo": {"username": name, "groups": groups}}))
        r = subprocess.run([cli, "apply", str(policy), "--resource", str(t / "res.yaml"),
                            "-f", str(t / "values.yaml"), "-u", str(t / "user.yaml"),
                            "--policy-report", "--output-format", "json"],
                           capture_output=True, text=True, timeout=300)
    if "Error:" in r.stderr or "Error:" in r.stdout:
        return {"__cli__": ("cli-error", (r.stderr or r.stdout).strip()[-400:])}
    if "{" not in r.stdout:
        if r.returncode != 0:
            return {"__cli__": ("cli-error", (r.stderr or r.stdout).strip()[-400:])}
        return {}
    try:
        report = json.loads(r.stdout[r.stdout.find("{"):])
    except json.JSONDecodeError:
        return {"__cli__": ("cli-error", (r.stderr or r.stdout).strip()[-400:])}
    got = {}
    for res in report.get("results") or []:
        for ref in res.get("resources", []):
            got[ref["name"]] = (res["result"], res.get("message", ""))
    return got


def verdict(got, name):
    if "__cli__" in got:
        return ("cli-error", got["__cli__"][1])
    result, msg = got.get(name, ("ignored", ""))
    return ("ignored" if result == "skip" else result, msg)


# --------------------------------------------------------------------------------------------------------
print("== FIRST, the RBAC half: the scoped Role keeps `create` on pods, so agent-sa may make one ==")
# Parse the staged scoped Role out of the ConfigMap literal, exactly as a cluster applies it.
import re  # noqa: E402
m = re.search(r"c8-scoped-role\.yaml: \|\n(.*?)(?:\n  [a-z0-9-]+\.yaml: \||\n---)", RES, re.S)
scoped = yaml.safe_load("\n".join(ln[4:] for ln in m.group(1).split("\n"))) if m else None
check("c8-scoped-role.yaml parses as a Role", isinstance(scoped, dict) and scoped.get("kind") == "Role")
rules = {tuple(r.get("resources", [])): r for r in (scoped or {}).get("rules", [])}
pods_rule = rules.get(("pods", "configmaps", "services"))
check("it keeps create/get/list/patch on pods (the create verb is untouched by the scoping)",
      pods_rule is not None and "create" in pods_rule.get("verbs", []),
      f"pods rule: {pods_rule}")
secrets_rule = rules.get(("secrets",))
check("and it scopes Secrets to `get` on ceo-personal-record by name -- no blanket get, no list",
      secrets_rule is not None and secrets_rule.get("verbs") == ["get"]
      and secrets_rule.get("resourceNames") == ["ceo-personal-record"],
      f"secrets rule: {secrets_rule}")
# So the scoping shrinks the agent's API read of Secrets but does nothing to its power to create a pod, and
# a pod that mounts a Secret reads it without any API `get`/`list` at all. The two in-namespace Secrets that
# scoping is meant to protect, and that a mounted pod would hand over regardless:
fleet_sh = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
check("the terminal password Secret `terminal-auth` lives in namespace agent (fleet.sh creates it there)",
      "create secret generic terminal-auth" in fleet_sh and "-n agent" in fleet_sh
      and 'TTYD_CREDENTIAL' in fleet_sh)
check("the console TLS private key Secret `console-tls` lives in namespace agent (cert-manager issues it)",
      "secretName: console-tls" in RES)
# And the example the issue names is already out of a pod's reach: #584 moved the attendee AWS key out of agent.
awscreds = REPO / "verify/test_student_aws_creds_namespace.py"
check("the AWS credentials Secret is NOT in agent any more (#584 moved it to student-creds)",
      awscreds.exists() and 'NS = "student-creds"' in awscreds.read_text(encoding="utf-8"))

# --------------------------------------------------------------------------------------------------------
print("\n== SECOND, admission: every agent-namespace policy's verdict on the Secret-mounting pod ==")
# Each policy the agent namespace actually subjects a CREATE pod to. (require-labels, require-probes,
# disallow-privileged and require-networkpolicy are scoped to the `apps` namespace, so they never see it.)
POLICIES = [
    ("restrict-image-registries", POL / "restrict-image-registries.yaml", "CREATE"),
    ("require-resource-limits", POL / "require-resource-limits.yaml", "CREATE"),
    ("restrict-agent-spawned-workloads", POL / "restrict-agent-spawned-workloads.yaml", "CREATE"),
    ("deny-llm-endpoint-bypass", POL / "deny-llm-endpoint-bypass.yaml", "CREATE"),
    ("verify-image-signatures", POL / "verify-image-signatures.yaml", "CREATE"),
    ("block-argocd-drift", POL / "block-argocd-drift.yaml", "CREATE"),
    ("minimal-floor", FLOOR, "CREATE"),
]
denied_by = []
for label, path, op in POLICIES:
    got = run(path, [exploit_pod()], operation=op)
    result, msg = verdict(got, "secret-harvester")
    print(f"  [{label}] -> {result}" + (f": {msg}" if msg and result not in ('pass', 'ignored') else ""))
    check(f"{label} does not deny the Secret-mounting pod (got {result})",
          result in ("pass", "ignored"), msg or result)
    if result == "fail":
        denied_by.append(label)
check("NO admission policy refuses the pod on account of the Secret it mounts (the measured gap)",
      not denied_by, f"denied by: {denied_by}")

# --------------------------------------------------------------------------------------------------------
print("\n== the controls: the engine IS judging the pod, and the Secret mount is never the lever ==")
SPAWN = POL / "restrict-agent-spawned-workloads.yaml"
AS_IDENTITY = "may not run as a ServiceAccount that holds Bedrock credentials"
AS_LABEL = "may not carry a label that a NetworkPolicy trusts"
got = run(SPAWN, [exploit_pod(name="as-agent-sa", sa="agent-sa")])
result, msg = verdict(got, "as-agent-sa")
check("the SAME pod flips to a denial when it runs as agent-sa (identity, not the Secret)",
      result == "fail" and AS_IDENTITY in msg, f"{result}: {msg}")
got = run(SPAWN, [exploit_pod(name="as-console", labels={"app.kubernetes.io/name": "console"})])
result, msg = verdict(got, "as-console")
check("and when it wears a NetworkPolicy label (label, not the Secret)",
      result == "fail" and AS_LABEL in msg, f"{result}: {msg}")
# The exploit pod as written -- default SA, ordinary label -- passes that same policy, so the only thing the
# controls key on is identity/label; the terminal-auth volume and secretKeyRef are invisible to all of them.
got = run(SPAWN, [exploit_pod()])
result, _ = verdict(got, "secret-harvester")
check("while the default-SA, ordinary-label Secret-mounting pod passes restrict-agent-spawned-workloads",
      result == "pass", result)

print(f"\nMEASURED 2026-10-26 with kyverno CLI v{WANT_VERSION}: agent-sa under c8-scoped-role.yaml CAN read any "
      "Secret in namespace agent by mounting it into a pod it creates; NO workshop admission policy refuses "
      "the Secret volume or secretKeyRef. See decisions.md 2026-10-26 · #604 for the recorded commands.")
if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll Challenge 8 pod-Secret-mount measurement checks passed.")
