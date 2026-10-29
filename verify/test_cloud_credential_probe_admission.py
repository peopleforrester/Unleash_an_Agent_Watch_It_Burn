# ABOUTME: Holds #203's C8 probe to admission: the Job the student applies, and the pod its controller makes as
# ABOUTME: agent-sa, pass every workshop policy, while the same pod asked for by the agent is refused.
# SUITE: e2e (needs the kyverno CLI v1.19.1 on PATH)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# The probe (cloud-credential-probe.yaml in the challenge-fixes ConfigMap) runs as agent-sa on purpose: Pod Identity
# binds the agent's AWS credential to that ServiceAccount, so a pod running as it holds exactly what BurritoBot
# holds. restrict-agent-spawned-workloads refuses such a pod when an agent-namespace identity asks for it (#490),
# and the lab's claim is that it does not refuse this one, because the student's terminal creates the Job and the
# Job controller creates the pod. Both are judged here through the same Kyverno engine the admission controller
# runs, as the two users they really are, and the agent's own request is judged too so a pass means something.
# The Kyverno CLI reports a violation as fail whatever validationActions say, so a pass here is a pass under Deny,
# which is how the admin profile arms restrict-image-registries and require-resource-limits.
import json, os, pathlib, shutil, subprocess, sys, tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
POL = REPO / "policies/kyverno"
FLOOR = REPO / "policies/floor/minimal-floor.yaml"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
SPAWN = "restrict-agent-spawned-workloads.yaml"
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

# Who asks. The student's terminal runs as web-terminal; the Job controller makes the Job's pods; the agent is
# agent-sa (and its tools workshop-mcp), both of which restrict-agent-spawned-workloads matches.
STUDENT = ("system:serviceaccount:agent:web-terminal",
           ["system:serviceaccounts", "system:serviceaccounts:agent", "system:authenticated"])
JOB_CONTROLLER = ("system:serviceaccount:kube-system:job-controller",
                  ["system:serviceaccounts", "system:serviceaccounts:kube-system", "system:authenticated"])
AGENT = ("system:serviceaccount:agent:workshop-mcp",
         ["system:serviceaccounts", "system:serviceaccounts:agent", "system:authenticated"])


def run(policy, resources, user):
    """Return {resource name: (result, message)} for one policy over the resources, as CREATE requests."""
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        (t / "res.yaml").write_text("\n---\n".join(json.dumps(r) for r in resources))
        (t / "values.yaml").write_text(json.dumps({
            "apiVersion": "cli.kyverno.io/v1alpha1", "kind": "Values",
            "globalValues": {"request.operation": "CREATE"}}))
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
            if res["result"] == "fail" or ref["name"] not in got:
                got[ref["name"]] = (res["result"], res.get("message", ""))
    return got


def verdict(got, name):
    """pass | fail | ignored (skipped by a matchCondition, or never matched) | cli-error."""
    if "__cli__" in got:
        return got["__cli__"]
    result, msg = got.get(name, ("ignored", ""))
    return ("ignored" if result == "skip" else result, msg)


print("== the probe as staged ==")
DOCS = [d for d in yaml.safe_load_all(RESOURCES.read_text(encoding="utf-8")) if isinstance(d, dict)]
fixes = next((d for d in DOCS if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "challenge-fixes"), {})
job = yaml.safe_load((fixes.get("data") or {}).get("cloud-credential-probe.yaml") or "{}") or {}
check("challenge-fixes stages cloud-credential-probe.yaml as a Job", job.get("kind") == "Job")
tmpl = (job.get("spec") or {}).get("template") or {}
check("its pods run as agent-sa", (tmpl.get("spec") or {}).get("serviceAccountName") == "agent-sa")
if failures:
    sys.exit(1)

# The pod the Job controller creates from the template: the template's metadata and spec, the Job's namespace, and
# the controller's own labels and owner reference.
pod = {"apiVersion": "v1", "kind": "Pod",
       "metadata": {"name": "cloud-credential-probe-x7k2p", "namespace": job["metadata"]["namespace"],
                    "labels": {**(tmpl.get("metadata") or {}).get("labels", {}),
                               "batch.kubernetes.io/job-name": job["metadata"]["name"]},
                    "ownerReferences": [{"apiVersion": "batch/v1", "kind": "Job", "name": job["metadata"]["name"],
                                         "uid": "00000000-0000-0000-0000-000000000203", "controller": True}]},
       "spec": tmpl["spec"]}
agent_pod = json.loads(json.dumps(pod))
agent_pod["metadata"] = {"name": "agent-made-probe", "namespace": "agent", "labels": dict(pod["metadata"]["labels"])}

ALL_POLICIES = sorted(POL.glob("*.yaml")) + [FLOOR]
check("restrict-agent-spawned-workloads is among the workshop policies", SPAWN in {p.name for p in ALL_POLICIES})

for who, user, res, name in (("the student's terminal applies the Job", STUDENT, job, job["metadata"]["name"]),
                             ("the Job controller creates its pod", JOB_CONTROLLER, pod, pod["metadata"]["name"])):
    print(f"\n== {who}, through every workshop policy ==")
    for p in ALL_POLICIES:
        got = run(p, [res], user)
        r, msg = verdict(got, name)
        if r == "cli-error":
            check(f"{p.name} evaluates it", False, f"kyverno CLI failed: {msg}")
            continue
        check(f"{p.name} admits it", r in ("pass", "ignored"), f"got {r}: {msg!r}")

print("\n== the same pod, asked for by the agent, is refused ==")
r, msg = verdict(run(POL / SPAWN, [agent_pod], AGENT), "agent-made-probe")
check("restrict-agent-spawned-workloads refuses a pod as agent-sa that the agent's tools ask for",
      r == "fail" and "Bedrock credentials" in msg, f"got {r}: {msg!r}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All #203 probe admission checks passed: the student's probe is admitted, the agent's copy is not.")
