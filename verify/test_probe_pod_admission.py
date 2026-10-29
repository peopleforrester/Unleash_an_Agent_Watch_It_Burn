# ABOUTME: Holds #555: the one-shot pod test_tool_audit_live.py sends its tools/call from is admitted by every
# ABOUTME: workshop policy, while the curlimages/curl pod it used to run is refused by the two the admin profile arms.
# SUITE: e2e (needs the kyverno CLI v1.19.1 on PATH)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# fleet.sh arm_infra_guardrails flips restrict-image-registries and require-resource-limits to Deny on every
# admin and full cluster, and the private KubeCon cluster is admin. The live audit-trail check used to send its
# call from `kubectl run --image=curlimages/curl:8.10.1` with no limits, which both of those refuse, so on the
# armed cluster it failed before it reached Datadog. verify/probe_pod.py builds the pod instead; this runs that
# manifest, with the shim image the workshop-mcp Deployment pins, through the same Kyverno engine the admission
# controller runs (the CLI pinned to the deployed v1.19.1). The Kyverno CLI reports a violation as fail whatever
# the policy's validationActions say, so a pass here is a pass under Deny.
import json, os, pathlib, shutil, subprocess, sys, tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import probe_pod  # noqa: E402

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

# Who runs the live check: an operator on their cluster-admin kubeconfig. Both shapes it can take are judged, the
# certificate admin in system:masters and an EKS access-entry IAM principal, which is in no system group.
OPERATORS = {
    "the certificate admin": ("kubernetes-admin", ["system:masters", "system:authenticated"]),
    "an EKS access-entry principal": ("arn:aws:iam::111122223333:user/operator", ["system:authenticated"]),
}


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
            got[ref["name"]] = (res["result"], res.get("message", ""))
    return got


def verdict(got, name):
    """pass | fail | ignored (skipped by a matchCondition, or never matched) | cli-error."""
    if "__cli__" in got:
        return got["__cli__"]
    result, msg = got.get(name, ("ignored", ""))
    return ("ignored" if result == "skip" else result, msg)


print("== the probe pod runs the image the workshop-mcp Deployment pins ==")
DOCS = [d for d in yaml.safe_load_all(RESOURCES.read_text(encoding="utf-8")) if isinstance(d, dict)]
dep = next((d for d in DOCS if d.get("kind") == "Deployment" and d["metadata"]["name"] == "workshop-mcp"), {})
shim = next((c for c in dep.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
             if c.get("name") == "shim"), {})
image = shim.get("image", "")
check("the workshop-mcp Deployment has a shim container with a pinned image", "@sha256:" in image, repr(image))
check("the workshop-mcp image installs curl, which the probe's script runs",
      "curl" in (REPO / "images/workshop-mcp/Dockerfile").read_text(encoding="utf-8"))

SCRIPT = "curl -s -X POST http://agentgateway.agent.svc.cluster.local:3001/mcp -d '{}'"
probe = probe_pod.shell_pod("toolaudit-probe", "agent", image, SCRIPT)
c = probe["spec"]["containers"][0]
check("the probe pod runs the script once, under sh, and stops",
      c["command"] == ["sh", "-c", SCRIPT] and probe["spec"]["restartPolicy"] == "Never")
check("its container sets CPU and memory limits", {"cpu", "memory"} <= set(c["resources"].get("limits", {})))

# The pod `kubectl run --image=curlimages/curl:8.10.1 --restart=Never` made, before #555.
old = {"apiVersion": "v1", "kind": "Pod",
       "metadata": {"name": "toolaudit-old", "namespace": "agent", "labels": {"run": "toolaudit-old"}},
       "spec": {"restartPolicy": "Never", "containers": [
           {"name": "toolaudit-old", "image": "curlimages/curl:8.10.1", "command": ["sh", "-c", SCRIPT],
            "resources": {}, "stdin": True, "stdinOnce": True}]}}

ARMED = {"restrict-image-registries.yaml", "require-resource-limits.yaml"}
ALL_POLICIES = sorted(POL.glob("*.yaml")) + [FLOOR]
check("both policies the admin profile arms are among the workshop policies",
      ARMED <= {p.name for p in ALL_POLICIES})

for who, user in OPERATORS.items():
    print(f"\n== created by {who}, through every workshop policy ==")
    refused_old = {}
    for p in ALL_POLICIES:
        got = run(p, [probe, old], user)
        res, msg = verdict(got, "toolaudit-probe")
        if res == "cli-error":
            check(f"{p.name} evaluates the pods", False, f"kyverno CLI failed: {msg}")
            continue
        check(f"{p.name} admits the probe pod", res in ("pass", "ignored"), f"got {res}: {msg!r}")
        if p.name in ARMED:
            # Judged, not merely unmatched: an "ignored" here would make the line above say nothing.
            check(f"{p.name} judges the probe pod and returns pass", res == "pass", f"got {res}")
        if verdict(got, "toolaudit-old")[0] == "fail":
            refused_old[p.name] = verdict(got, "toolaudit-old")[1]
    check("the old curlimages/curl pod is refused by exactly the two armed policies, so this test can tell them apart",
          set(refused_old) == ARMED, f"refused by: {sorted(refused_old)}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All #555 probe-pod checks passed: the armed admin profile admits the live check's pod.")
