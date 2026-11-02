# ABOUTME: Runs deny-external-registries (#774) and restrict-image-registries through the Kyverno CLI on the breakout's
# ABOUTME: requests: the room's public image refused, the internal registry's admitted, the platform's own pods untouched.
# SUITE: e2e (needs the kyverno CLI v1.19.1 on PATH)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. With guardrails-on, both registry policies are at Deny on the two KubeCon clusters, and the story the breakout
# tells rests on what each one says: Challenge 2's public image (#773) is refused because BurritoBot asked for it,
# Challenge 3's image on registry.burritobot.co (#775) is admitted because the platform trusts that registry, and the
# platform's own pods, which Argo CD, kagent and the kube controllers create from ghcr.io and the kagent registries,
# are not the agent's requests and pass. A render check can say the expressions are there; the CLI, the engine the
# admission controller runs, says what they decide.
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import kubecon_probe as kp  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
BREAKOUT = REPO / "policies/kyverno-breakout/deny-external-registries.yaml"
REG = REPO / "policies/kyverno/restrict-image-registries.yaml"
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


def sa(ns, name):
    return (f"system:serviceaccount:{ns}:{name}",
            ["system:serviceaccounts", f"system:serviceaccounts:{ns}", "system:authenticated"])


USERS = {
    "workshop-mcp": sa("agent", "workshop-mcp"),  # deploy_app's identity
    "agent-sa": sa("agent", "agent-sa"),
    "web-terminal": sa("agent", "web-terminal"),
    "argocd": sa("argocd", "argocd-application-controller"),
    "kagent": sa("kagent", "kagent-controller"),
    "replicaset-controller": sa("kube-system", "replicaset-controller"),
    "admin": ("kubernetes-admin", ["system:masters", "system:authenticated"]),
}
LIMITS = {"limits": {"cpu": "100m", "memory": "64Mi"}}
INTERNAL = kp.INTERNAL_IMAGE
PUBLIC = kp.PUBLIC_IMAGE
DOCKER_NGINX = "nginx:1.27-alpine"  # what "deploy nginx" means to a model that knows Docker Hub
KAGENT = "cr.kagent.dev/kagent-dev/kagent/app:0.10.1"
MSG = "BurritoBot may run images only from the internal registry, registry.burritobot.co."


def pod(name, ns, images, init=None):
    spec = {"containers": [{"name": f"c{i}", "image": im, "resources": LIMITS} for i, im in enumerate(images)]}
    if init:
        spec["initContainers"] = [{"name": "init", "image": init, "resources": LIMITS}]
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": ns}, "spec": spec}


def deploy(name, image):
    return kp.dry_run_manifest(name, image)


def cronjob(name, ns, image):
    return {"apiVersion": "batch/v1", "kind": "CronJob", "metadata": {"name": name, "namespace": ns},
            "spec": {"schedule": "*/5 * * * *", "jobTemplate": {"spec": {"template": {"spec": {
                "restartPolicy": "Never", "containers": [{"name": "c", "image": image, "resources": LIMITS}]}}}}}}


def run(policy, resources, operation="CREATE", user="workshop-mcp"):
    """{resource name: (result, message)} for one policy over the resources, one request each."""
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        (t / "res.yaml").write_text("\n---\n".join(json.dumps(r) for r in resources))
        (t / "values.yaml").write_text(json.dumps({
            "apiVersion": "cli.kyverno.io/v1alpha1", "kind": "Values",
            "globalValues": {"request.operation": operation}}))
        name, groups = USERS[user]
        (t / "user.yaml").write_text(json.dumps({
            "apiVersion": "cli.kyverno.io/v1alpha1", "kind": "UserInfo",
            "userInfo": {"username": name, "groups": groups}}))
        r = subprocess.run([cli, "apply", str(policy), "--resource", str(t / "res.yaml"),
                            "-f", str(t / "values.yaml"), "-u", str(t / "user.yaml"),
                            "--policy-report", "--output-format", "json"],
                           capture_output=True, text=True, timeout=300)
    # The CLI exits 1 whenever a resource FAILS, which most cases want; a policy that does not compile prints Error:.
    if "Error:" in r.stderr or "Error:" in r.stdout:
        return {"__cli__": ("cli-error", (r.stderr or r.stdout).strip()[-400:])}
    if "{" not in r.stdout:
        if r.returncode != 0:
            return {"__cli__": ("cli-error", (r.stderr or r.stdout).strip()[-400:])}
        return {}  # no report at all: the policy matched none of the resources
    try:
        report = json.loads(r.stdout[r.stdout.find("{"):])
    except json.JSONDecodeError:
        return {"__cli__": ("cli-error", (r.stderr or r.stdout).strip()[-400:])}
    got = {}
    for res in report.get("results") or []:
        for ref in res.get("resources", []):
            got[ref["name"]] = (res["result"], res.get("message", ""))
    return got


def expect(label, got, name, verdict, message=None):
    """verdict: fail | pass | ignored (skipped by a matchCondition, or never matched)."""
    if "__cli__" in got:
        check(label, False, f"kyverno CLI failed: {got['__cli__'][1]}")
        return
    result, msg = got.get(name, ("ignored", ""))
    actual = "ignored" if result == "skip" else result
    ok = actual == verdict and (message is None or message in msg)
    check(label, ok, f"expected {verdict}{' with ' + repr(message) if message else ''}, got {result}: {msg!r}")


print("== deny-external-registries: what BurritoBot deploys runs from registry.burritobot.co only ==")
cases = [pod("docker-nginx", "agent", [DOCKER_NGINX]),
         deploy("public-deploy", PUBLIC),
         deploy("internal-deploy", INTERNAL),
         pod("platform-image", "agent", [KAGENT]),
         pod("init-external", "agent", [INTERNAL], init=PUBLIC),
         pod("lookalike", "agent", ["registry.burritobot.co.evil.example/burritobot/maintenance-shell:1"]),
         cronjob("public-cron", "agent", PUBLIC),
         kp.PUBLIC_MANIFEST, kp.INTERNAL_MANIFEST]
for user in ("workshop-mcp", "agent-sa"):
    g = run(BREAKOUT, cases, user=user)
    expect(f"{user}: a Docker Hub image ('deploy nginx') fails, naming the internal registry", g, "docker-nginx",
           "fail", MSG)
    expect(f"{user}: an official public image on ghcr.io fails at the Deployment (autogen)", g, "public-deploy",
           "fail", MSG)
    expect(f"{user}: the internal registry's image passes", g, "internal-deploy", "pass")
    expect(f"{user}: even an image the platform itself runs fails when the agent asks for it", g, "platform-image",
           "fail", MSG)
    expect(f"{user}: an external init container fails a Pod whose container is internal", g, "init-external",
           "fail", MSG)
    expect(f"{user}: a host that only starts with the internal registry's name fails", g, "lookalike", "fail", MSG)
    expect(f"{user}: a CronJob is refused too (autogen)", g, "public-cron", "fail", MSG)
    expect(f"{user}: the KubeCon probe's public-image Deployment fails", g, kp.PUBLIC_MANIFEST["metadata"]["name"],
           "fail", MSG)
    expect(f"{user}: and its internal-registry Deployment passes", g, kp.INTERNAL_MANIFEST["metadata"]["name"], "pass")
for user in ("argocd", "kagent", "replicaset-controller", "admin", "web-terminal"):
    g = run(BREAKOUT, [pod("platform-image", "agent", [KAGENT]), deploy("public-deploy", PUBLIC)], user=user)
    expect(f"{user}: the platform's own pods are not the agent's requests and are left alone", g, "platform-image",
           "ignored")
    expect(f"{user}: nor is a Deployment it makes", g, "public-deploy", "ignored")
g = run(BREAKOUT, [pod("platform-image", "agent", [KAGENT])], operation="UPDATE", user="agent-sa")
expect("an UPDATE that keeps every image passes, so a pod made before the flip is never wedged", g, "platform-image",
       "pass")

print("== restrict-image-registries agrees: the internal registry is trusted, the public image only it trusts ==")
g = run(REG, [kp.INTERNAL_MANIFEST, kp.PUBLIC_MANIFEST, pod("docker-nginx", "agent", [DOCKER_NGINX])],
        user="workshop-mcp")
expect("registry.burritobot.co passes restrict-image-registries (#775's image at Deny)",
       g, kp.INTERNAL_MANIFEST["metadata"]["name"], "pass")
expect("the public image on ghcr.io passes it, so only deny-external-registries can refuse #773's deploy",
       g, kp.PUBLIC_MANIFEST["metadata"]["name"], "pass")
expect("Docker Hub's nginx fails both", g, "docker-nginx", "fail")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All breakout registry policy checks passed.")
