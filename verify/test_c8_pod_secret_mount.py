# ABOUTME: Measures #604: under c8-scoped-role.yaml agent-sa can no longer read other Secrets through the API,
# ABOUTME: but it keeps create on pods, so it can still read any Secret in namespace agent by mounting it in a pod.
# SUITE: e2e (needs the kyverno CLI v1.19.1 on PATH)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Challenge 8's fix (gitops/ai-layer/resources.yaml, the c8-scoped-role.yaml key of the challenge-fixes
# ConfigMap) replaces blanket get and list on Secrets with get on ceo-personal-record by name. It keeps
# create, get, list and patch on pods and deployments. The Kubernetes RBAC good-practices page (read
# 2026-10-26, https://kubernetes.io/docs/concepts/security/rbac-good-practices/) says permission to create
# workloads in a namespace implicitly grants access to the Secrets that can be mounted in Pods there, because
# the kubelet reads a mounted Secret on the pod's behalf using the node's credentials, so the pod creator's
# own RBAC is never consulted for the mount.
#
# This test measures the two things #604 asks for, cluster-free, with the same Kyverno engine the admission
# controller runs (the CLI pinned to the deployed v1.19.1, #572):
#
#   Part 1, RBAC (parsed from the Role). c8-scoped-role.yaml grants create on pods and scopes Secret reads to
#   get on ceo-personal-record. So agent-sa may create a pod, and its API read of any other Secret is Forbidden.
#
#   Part 2, admission (run through every workshop policy). A pod agent-sa creates, on the default
#   ServiceAccount, with an allowed image and an ordinary label, that mounts terminal-auth both as a volume and
#   through a secretKeyRef env var, is refused by none of the policies under policies/kyverno/ or policies/floor/.
#   Every policy that evaluates it returns pass; the rest do not match it. So the mount succeeds and the pod
#   reads terminal-auth, the shared web-terminal credential, which the scoped Role forbids reading through the API.
#
# Two contrast cases anchor what the one policy that looks at an agent pod actually checks:
#   * The same pod running as agent-sa, or carrying a NetworkPolicy-trusted label, IS denied by
#     restrict-agent-spawned-workloads, on the identity and the label, with no mention of the Secret.
#   * A pod mounting ceo-personal-record (the one Secret the Role still reads through the API) is admitted
#     exactly like the terminal-auth pod. Admission draws no line between the allowed Secret and the others.
#
# The AWS credentials Secret #604 names as an example is out of reach: #584 moved student-aws-creds to namespace
# student-creds, and a pod mounts only Secrets from its own namespace, so a pod in agent cannot mount it. The
# Secrets a pod in agent can mount are terminal-auth and console-tls. No policy refusing Secret volumes and
# secretKeyRef env vars for pods created by agent-sa exists yet; a follow-up on #604 asks for one.
import json, os, pathlib, shutil, subprocess, sys, tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
POL = REPO / "policies/kyverno"
FLOOR = REPO / "policies/floor/minimal-floor.yaml"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
WANT_VERSION = "1.19.1"
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

AGENT_SA = ("system:serviceaccount:agent:agent-sa",
            ["system:serviceaccounts", "system:serviceaccounts:agent", "system:authenticated"])


def run(policy, resources, operation="CREATE", user=AGENT_SA):
    """Return {resource name: (result, message)} for one policy over the resources, as one request each."""
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        (t / "res.yaml").write_text("\n---\n".join(json.dumps(r) for r in resources))
        (t / "values.yaml").write_text(json.dumps({
            "apiVersion": "cli.kyverno.io/v1alpha1", "kind": "Values",
            "globalValues": {"request.operation": operation}}))
        (t / "user.yaml").write_text(json.dumps({
            "apiVersion": "cli.kyverno.io/v1alpha1", "kind": "UserInfo",
            "userInfo": {"username": user[0], "groups": user[1]}}))
        r = subprocess.run([cli, "apply", str(policy), "--resource", str(t / "res.yaml"),
                            "-f", str(t / "values.yaml"), "-u", str(t / "user.yaml"),
                            "--policy-report", "--output-format", "json"],
                           capture_output=True, text=True, timeout=300)
    if "Error:" in r.stderr or "Error:" in r.stdout:
        return {"__cli__": ("cli-error", (r.stderr or r.stdout).strip()[-400:])}
    if "{" not in r.stdout:
        if r.returncode != 0:
            return {"__cli__": ("cli-error", (r.stderr or r.stdout).strip()[-400:])}
        return {}  # the CLI prints no report when the policy matched none of the resources
    try:
        report = json.loads(r.stdout[r.stdout.find("{"):])
    except json.JSONDecodeError:
        return {"__cli__": ("cli-error", (r.stdout or r.stderr).strip()[-400:])}
    got = {}
    for res in report.get("results") or []:
        for ref in res.get("resources", []):
            got[ref["name"]] = (res["result"], res.get("message", ""))
    return got


def verdict(got, name):
    """pass | fail | ignored (skipped by a matchCondition, or never matched)."""
    if "__cli__" in got:
        return ("cli-error", got["__cli__"][1])
    result, msg = got.get(name, ("ignored", ""))
    return ("ignored" if result == "skip" else result, msg)


# --- Part 1: the Role, parsed from the challenge-fixes ConfigMap --------------------------------------------
AI = [d for d in yaml.safe_load_all(RESOURCES.read_text()) if isinstance(d, dict)]
fixes = next((d.get("data") or {} for d in AI
              if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "challenge-fixes"), {})
role = yaml.safe_load(fixes["c8-scoped-role.yaml"]) if "c8-scoped-role.yaml" in fixes else {}
rules = role.get("rules") or []


def rule_for(resource):
    return next((r for r in rules if resource in (r.get("resources") or [])), {})


print("== Part 1: c8-scoped-role.yaml, as the Role a student applies ==")
check("the scoped Role is found in the challenge-fixes ConfigMap", bool(role),
      "c8-scoped-role.yaml missing from the ConfigMap data")
pods = rule_for("pods")
check("it keeps create on pods, so agent-sa can create a pod", "create" in (pods.get("verbs") or []),
      repr(pods))
secrets = rule_for("secrets")
check("its Secret read is scoped to ceo-personal-record by name", secrets.get("resourceNames") == ["ceo-personal-record"],
      repr(secrets))
check("it is get only on that Secret, with no list and no blanket get",
      sorted(secrets.get("verbs") or []) == ["get"], repr(secrets.get("verbs")))
check("so agent-sa's API read of terminal-auth or any other Secret is Forbidden",
      "secrets" not in [res for r in rules if not r.get("resourceNames") for res in (r.get("resources") or [])],
      "an unscoped secrets rule would re-grant blanket read")

# --- Part 2: the mount the scoped Role does not stop ---------------------------------------------------------
LIMITS = {"limits": {"cpu": "100m", "memory": "64Mi"}}


def exfil(name, secret="terminal-auth", key="TTYD_CREDENTIAL", sa="default", labels=None):
    """A pod agent-sa could create: default ServiceAccount, an allowed image, resource limits, an ordinary
    label, reading one Secret both as a mounted volume and through a secretKeyRef env var."""
    return {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": name, "namespace": "agent", "labels": labels or {"app": "exfil"}},
            "spec": {"serviceAccountName": sa,
                     "volumes": [{"name": "stolen", "secret": {"secretName": secret}}],
                     "containers": [{"name": "c", "image": "docker.io/library/busybox:1.36", "resources": LIMITS,
                                     "command": ["sh", "-c", f"cat /stolen/{key}; echo \"$PW\""],
                                     "volumeMounts": [{"name": "stolen", "mountPath": "/stolen", "readOnly": True}],
                                     "env": [{"name": "PW", "valueFrom": {"secretKeyRef": {"name": secret, "key": key}}}]}]}}


ALL_POLICIES = sorted(POL.glob("*.yaml")) + [FLOOR]
print("\n== Part 2: a pod agent-sa creates that mounts terminal-auth, through every workshop policy ==")
pod = exfil("exfil-terminal-auth")
denied = []
for p in ALL_POLICIES:
    res, msg = verdict(run(p, [pod]), "exfil-terminal-auth")
    if res == "cli-error":
        check(f"{p.name} evaluates the pod", False, f"kyverno CLI failed: {msg}")
    else:
        check(f"{p.name}: {res} (not a refusal)", res in ("pass", "ignored"), f"got {res}: {msg!r}")
        if res == "fail":
            denied.append(p.name)
check("NO workshop admission policy refuses the Secret-mounting pod", not denied,
      f"refused by: {denied}")

# --- Contrast cases: what the one agent-pod policy actually checks -------------------------------------------
print("\n== Contrast: restrict-agent-spawned-workloads looks at identity and label, never at the Secret ==")
SPAWN = POL / "restrict-agent-spawned-workloads.yaml"
res, msg = verdict(run(SPAWN, [exfil("exfil-as-sa", sa="agent-sa")]), "exfil-as-sa")
check("the same mount running as agent-sa IS denied, on the Bedrock identity; the Secret plays no part",
      res == "fail" and "ServiceAccount that holds Bedrock credentials" in msg, f"got {res}: {msg!r}")
res, msg = verdict(run(SPAWN, [exfil("exfil-labelled", labels={"app.kubernetes.io/name": "console"})]), "exfil-labelled")
check("the same mount carrying a NetworkPolicy-trusted label IS denied, on the label; the Secret plays no part",
      res == "fail" and "label that a NetworkPolicy trusts" in msg, f"got {res}: {msg!r}")
res, msg = verdict(run(SPAWN, [exfil("exfil-terminal-auth")]), "exfil-terminal-auth")
check("but the default-ServiceAccount, ordinary-label mount passes it", res == "pass", f"got {res}: {msg!r}")

print("\n== Contrast: admission draws no line between ceo-personal-record and the other Secrets ==")
ceo = exfil("exfil-ceo", secret="ceo-personal-record", key="record")
for p in ALL_POLICIES:
    res, _ = verdict(run(p, [ceo]), "exfil-ceo")
    other, _ = verdict(run(p, [exfil("exfil-terminal-auth")]), "exfil-terminal-auth")
    check(f"{p.name} treats the ceo-personal-record pod exactly like the terminal-auth pod", res == other,
          f"ceo={res}, terminal-auth={other}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All #604 measurement checks passed: the scoped Role closes the API read; the pod mount stays open; no policy refuses it.")
