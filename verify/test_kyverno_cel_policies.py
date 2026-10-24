# ABOUTME: Runs every Kyverno CEL policy through the Kyverno CLI against fixture requests: the villain image,
# ABOUTME: Beat 1's limit-less Deployment, drift by agent-sa, the floor, and a real signed image on ghcr.io.
# SUITE: e2e (needs the kyverno CLI v1.19.0 on PATH, and network to ghcr.io for the signature check)
#
# Why (#206). The policies moved from kyverno.io/v1 ClusterPolicy patterns to CEL ValidatingPolicy and
# ImageValidatingPolicy. A YAML render check can say a field is present; it cannot say an expression
# evaluates. Three of these policies sit under live beats, so each case below is a request the room
# actually makes, and the assertion is the verdict Kyverno's own engine reaches on it, message included.
#
# Two things this caught while it was written, and keeps catching:
#   * A missing object reaches CEL as an EMPTY MAP, not null: oldObject on CREATE and in background scans,
#     object on DELETE. `object != null` guards are therefore true and the next field access errors, which
#     failurePolicy Fail turns into a denial. Every "UPDATE only" branch tests request.operation instead.
#   * Autogen is what makes Beat 1's `kubectl create deployment` fail AT THE DEPLOYMENT. The Deployment cases
#     below prove the generated rules exist and carry the same message.
#
# The CLI is the same evaluation engine the admission controller runs, and is pinned to the deployed version.
import json, os, pathlib, shutil, subprocess, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
POL = REPO / "policies/kyverno"
FLOOR = REPO / "policies/floor/minimal-floor.yaml"
WANT_VERSION = "1.19.0"
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


cli = os.environ.get("KYVERNO_CLI") or shutil.which("kyverno")
if not cli:
    print("FAIL: the kyverno CLI is not on PATH (set KYVERNO_CLI to its path). Install v1.19.0 from "
          "https://github.com/kyverno/kyverno/releases/tag/v1.19.0 (kyverno-cli_v1.19.0_<os>_<arch>.tar.gz).",
          file=sys.stderr)
    sys.exit(1)
ver = subprocess.run([cli, "version"], capture_output=True, text=True).stdout
if f"Version: {WANT_VERSION}" not in ver:
    print(f"FAIL: kyverno CLI is not v{WANT_VERSION} (the deployed engine); got: {ver.strip()!r}", file=sys.stderr)
    sys.exit(1)

USERS = {
    "agent-sa": ("system:serviceaccount:agent:agent-sa",
                 ["system:serviceaccounts", "system:serviceaccounts:agent", "system:authenticated"]),
    "student": ("attendee", ["system:authenticated"]),
    "argocd": ("system:serviceaccount:argocd:argocd-application-controller",
               ["system:serviceaccounts", "system:serviceaccounts:argocd", "system:authenticated"]),
    "kagent": ("system:serviceaccount:kagent:kagent-controller",
               ["system:serviceaccounts", "system:serviceaccounts:kagent", "system:authenticated"]),
    "kube-controller": ("system:serviceaccount:kube-system:deployment-controller",
                        ["system:serviceaccounts", "system:serviceaccounts:kube-system", "system:authenticated"]),
    "admin": ("kubernetes-admin", ["system:masters", "system:authenticated"]),
}

TRACKED = {"argocd.argoproj.io/tracking-id": "ai-layer:apps/Deployment:agent/guard-proxy"}
LIMITS = {"limits": {"cpu": "100m", "memory": "64Mi"}}
VILLAIN = "docker.io/peopleforrester/promo-mascot:latest"
SIGNED = ("ghcr.io/peopleforrester/watch-it-burn:busybox-1.36"
          "@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662")


def pod(name, ns, containers, labels=None, init=None):
    spec = {"containers": containers}
    if init:
        spec["initContainers"] = init
    return {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": name, "namespace": ns, **({"labels": labels} if labels else {})}, "spec": spec}


def deploy(name, ns, containers, labels=None, annotations=None):
    md = {"name": name, "namespace": ns}
    if annotations:
        md["annotations"] = annotations
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": md,
            "spec": {"selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": labels or {"app": name}}, "spec": {"containers": containers}}}}


def c(image="ghcr.io/peopleforrester/watch-it-burn:x", **kw):
    return {"name": "c", "image": image, **kw}


def run(policy, resources, operation="CREATE", user="student"):
    """Return {resource name: (result, message)} for one policy over the resources, as one request each."""
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        # The CLI reads multi-document YAML; JSON documents separated by '---' are valid YAML documents.
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
    # The exit code cannot tell a broken policy from a working one: the CLI exits 1 whenever any resource
    # FAILS, which most cases here want. A policy that does not compile prints "Error:" instead of a report.
    if "Error:" in r.stderr or "Error:" in r.stdout:
        return {"__cli__": ("cli-error", (r.stderr or r.stdout).strip()[-400:])}
    if "{" not in r.stdout:
        if r.returncode != 0:
            return {"__cli__": ("cli-error", (r.stderr or r.stdout).strip()[-400:])}
        return {}  # the CLI prints no report at all when the policy matched none of the resources
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


REG = POL / "restrict-image-registries.yaml"
REG_MSG = "Images must come from allowed registries"
print("== restrict-image-registries: the C2 villain wall ==")
g = run(REG, [pod("villain", "agent", [c(VILLAIN)]),
              deploy("promo-mascot", "agent", [c(VILLAIN)]),
              pod("ai-layer", "agent", [c(), c("cr.agentgateway.dev/agentgateway:v1.5.0", name="d"),
                                        c("cr.kagent.dev/kagent-dev/kagent/app:0.10.1", name="e")]),
              pod("apps-ok", "apps", [c("docker.io/library/nginx:1.27-alpine"),
                                      c("123456789012.dkr.ecr.us-west-2.amazonaws.com/shop:1", name="d"),
                                      c("registry.k8s.io/pause:3.9", name="e")]),
              pod("spoofed-ecr", "apps", [c("evil.example/x.dkr.ecr.y.amazonaws.com/z:1")]),
              pod("docker-user", "apps", [c("docker.io/someone/nginx:1")]),
              pod("elsewhere", "default", [c(VILLAIN)])])
expect("the villain Pod in agent fails with the named message", g, "villain", "fail", REG_MSG)
expect("the villain DEPLOYMENT fails too (autogen), so deploy_app is refused at the Deployment",
       g, "promo-mascot", "fail", REG_MSG)
expect("every ai-layer registry passes", g, "ai-layer", "pass")
expect("docker.io/library, ECR and registry.k8s.io pass in apps", g, "apps-ok", "pass")
expect("an ECR-looking path on another host does not pass as ECR", g, "spoofed-ecr", "fail", REG_MSG)
expect("a docker.io user namespace is not docker.io/library", g, "docker-user", "fail", REG_MSG)
expect("namespaces other than apps and agent are out of scope", g, "elsewhere", "ignored")
g = run(REG, [pod("villain", "agent", [c(VILLAIN)])], operation="UPDATE")
expect("an UPDATE to a Pod that already violated passes (the old allowExistingViolations)", g, "villain", "pass")

LIM = POL / "require-resource-limits.yaml"
LIM_MSG = "CPU and memory resource limits are required on every container."
print("== require-resource-limits: the Beat 1 wall ==")
g = run(LIM, [deploy("sample-web", "attendee-001", [c("nginx:latest")]),
              pod("no-limits", "kube-system", [c("x")]),
              pod("cpu-only", "agent", [c("x", resources={"limits": {"cpu": "1"}})]),
              pod("limited", "agent", [c("x", resources=LIMITS)])], user="agent-sa")
expect("Beat 1's `kubectl create deployment sample-web --image=nginx:latest` fails at the Deployment",
       g, "sample-web", "fail", LIM_MSG)
expect("a limit-less Pod fails in any namespace", g, "no-limits", "fail", LIM_MSG)
expect("cpu without memory fails", g, "cpu-only", "fail", LIM_MSG)
expect("cpu and memory limits pass", g, "limited", "pass")
g = run(LIM, [pod("no-limits", "monitoring", [c("x")])], operation="UPDATE")
expect("an UPDATE to a Pod that already lacked limits passes", g, "no-limits", "pass")

DRIFT = POL / "block-argocd-drift.yaml"
DRIFT_MSG = "This resource is managed by ArgoCD. Change it in Git, not in the cluster."
print("== block-argocd-drift: Beat 1's third wall and the lab's delete-guard-proxy step ==")
managed = deploy("guard-proxy", "agent", [c()], annotations=TRACKED)
unmanaged = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "scratch", "namespace": "agent"}}
managed_cm = {"apiVersion": "v1", "kind": "ConfigMap",
              "metadata": {"name": "proxy-src", "namespace": "agent", "annotations": TRACKED}}
for op in ("UPDATE", "DELETE"):
    g = run(DRIFT, [managed, managed_cm, unmanaged], operation=op, user="agent-sa")
    expect(f"{op} of a managed Deployment by agent-sa is denied with the named message", g, "guard-proxy", "fail",
           DRIFT_MSG)
    expect(f"{op} of a managed ConfigMap by agent-sa is denied", g, "proxy-src", "fail", DRIFT_MSG)
    expect(f"{op} of an unmanaged ConfigMap is not this policy's business", g, "scratch", "ignored")
    g = run(DRIFT, [managed], operation=op, user="student")
    expect(f"{op} of a managed Deployment by the student's terminal is denied", g, "guard-proxy", "fail", DRIFT_MSG)
    for who in ("argocd", "kagent", "kube-controller", "admin"):
        g = run(DRIFT, [managed], operation=op, user=who)
        expect(f"{op} by {who} is let through", g, "guard-proxy", "ignored")
g = run(DRIFT, [managed], operation="CREATE", user="agent-sa")
expect("CREATE is not matched (UPDATE and DELETE only)", g, "guard-proxy", "ignored")

FLOOR_NS_MSG = "Protected platform namespace; deletion is not permitted (workshop floor)."
FLOOR_WL_MSG = "Protected platform workload; deletion is not permitted (workshop floor)."
print("== minimal-floor: the safety floor ==")
ns = lambda n: {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": n}}
g = run(FLOOR, [ns("kagent"), ns("kube-system"), ns("apps"),
                deploy("kagent-controller", "kagent", [c()]), deploy("burn-party", "apps", [c()])],
        operation="DELETE", user="agent-sa")
expect("deleting a platform namespace is denied with the namespace message", g, "kagent", "fail", FLOOR_NS_MSG)
expect("kube-system is on the namespace list", g, "kube-system", "fail", FLOOR_NS_MSG)
expect("a demo namespace is deletable", g, "apps", "ignored")
expect("deleting a platform workload is denied with the workload message", g, "kagent-controller", "fail",
       FLOOR_WL_MSG)
expect("a demo workload stays deletable (the visible burn)", g, "burn-party", "ignored")
g = run(FLOOR, [ns("kagent"), deploy("kagent-controller", "kagent", [c()])], operation="DELETE", user="argocd")
expect("Argo CD may replace a platform workload it owns (#389)", g, "kagent-controller", "pass")
expect("but Argo CD still may not delete a platform namespace", g, "kagent", "fail", FLOOR_NS_MSG)
g = run(FLOOR, [deploy("kagent-controller", "kagent", [c()])], operation="DELETE", user="kube-controller")
expect("kube-system controllers may delete platform workloads", g, "kagent-controller", "pass")
g = run(FLOOR, [ns("kagent"), deploy("kagent-controller", "kagent", [c()])], operation="DELETE", user="admin")
expect("system:masters (teardown) may delete a platform namespace", g, "kagent", "ignored")
expect("system:masters may delete a platform workload", g, "kagent-controller", "ignored")
g = run(FLOOR, [ns("kagent")], operation="UPDATE", user="agent-sa")
expect("only DELETE is matched", g, "kagent", "ignored")

print("== the apps-namespace hygiene policies ==")
good = c("x", readinessProbe={"httpGet": {"path": "/", "port": 80}}, livenessProbe={"httpGet": {"path": "/", "port": 80}})
g = run(POL / "require-labels.yaml", [pod("no-version", "apps", [good], labels={"app": "a"}),
                                       pod("no-app", "apps", [good], labels={"version": "1"}),
                                       pod("labelled", "apps", [good], labels={"app": "a", "version": "1"}),
                                       deploy("tmpl-labelled", "apps", [good], labels={"app": "a", "version": "1"}),
                                       deploy("tmpl-bare", "apps", [good], labels={"app": "a"}),
                                       pod("elsewhere", "agent", [good])])
expect("a missing version label fails with its message", g, "no-version", "fail",
       "The label 'version' is required on pods in apps namespace.")
expect("a missing app label fails with its message", g, "no-app", "fail",
       "The label 'app' is required on pods in apps namespace.")
expect("both labels pass", g, "labelled", "pass")
expect("a Deployment is judged on its pod template's labels (autogen)", g, "tmpl-labelled", "pass")
expect("a Deployment whose template lacks version fails", g, "tmpl-bare", "fail", "The label 'version'")
expect("outside apps the policy does not apply", g, "elsewhere", "ignored")
g = run(POL / "require-probes.yaml", [pod("no-ready", "apps", [c("x", livenessProbe={"exec": {"command": ["true"]}})]),
                                       pod("no-live", "apps", [c("x", readinessProbe={"exec": {"command": ["true"]}})]),
                                       pod("probed", "apps", [good])])
expect("a missing readinessProbe fails with its message", g, "no-ready", "fail",
       "A readinessProbe is required for all containers in apps namespace.")
expect("a missing livenessProbe fails with its message", g, "no-live", "fail",
       "A livenessProbe is required for all containers in apps namespace.")
expect("both probes pass", g, "probed", "pass")
priv = {"securityContext": {"privileged": True}}
g = run(POL / "disallow-privileged.yaml", [pod("priv", "apps", [c("x", **priv)]),
                                            pod("priv-init", "apps", [c("x")], init=[c("i", **priv)]),
                                            pod("explicit-false", "apps", [c("x", securityContext={"privileged": False})]),
                                            pod("plain", "apps", [c("x")])])
expect("a privileged container fails", g, "priv", "fail", "Privileged containers are not allowed")
expect("a privileged init container fails", g, "priv-init", "fail", "Privileged containers are not allowed")
expect("privileged: false passes", g, "explicit-false", "pass")
expect("no securityContext passes", g, "plain", "pass")
labelled = deploy("labelled", "apps", [c()])
labelled["metadata"]["labels"] = {"app": "labelled"}
g = run(POL / "require-networkpolicy.yaml", [deploy("unlabelled", "apps", [c()]), labelled])
expect("a Deployment without an app label is reported", g, "unlabelled", "fail",
       "A NetworkPolicy should exist for this application.")
expect("a Deployment with one passes", g, "labelled", "pass")

print("== deny-llm-endpoint-bypass: the AI-plane audit ==")
env = lambda k, v: c("x", env=[{"name": k, "value": v}])
g = run(POL / "deny-llm-endpoint-bypass.yaml", [
    pod("rogue-openai", "agent", [env("OPENAI_BASE_URL", "https://api.openai.com/v1")]),
    pod("rogue-anthropic", "agent", [env("ANTHROPIC_BASE_URL", "https://api.anthropic.com")]),
    pod("rogue-legacy", "agent", [env("OPENAI_API_BASE", "https://api.openai.com/v1")]),
    pod("routed", "agent", [env("OPENAI_BASE_URL", "http://guard-proxy.agent.svc:8080/v1")]),
    pod("guard-proxy-6d9f", "agent", [env("OPENAI_BASE_URL", "https://api.openai.com/v1")]),
    pod("agentgateway-0", "agent", [env("ANTHROPIC_BASE_URL", "https://api.anthropic.com")]),
    deploy("rogue-deploy", "agent", [env("OPENAI_BASE_URL", "https://api.openai.com/v1")]),
    pod("other-ns", "apps", [env("OPENAI_BASE_URL", "https://api.openai.com/v1")])])
BYPASS = "This pod sets an LLM endpoint pointing at a public API."
expect("OPENAI_BASE_URL at api.openai.com is reported", g, "rogue-openai", "fail", BYPASS)
expect("ANTHROPIC_BASE_URL at api.anthropic.com is reported", g, "rogue-anthropic", "fail", BYPASS)
expect("OPENAI_API_BASE at api.openai.com is reported", g, "rogue-legacy", "fail", BYPASS)
expect("a base URL pointed at guard-proxy passes", g, "routed", "pass")
expect("guard-proxy itself is exempt", g, "guard-proxy-6d9f", "ignored")
expect("agentgateway itself is exempt", g, "agentgateway-0", "ignored")
expect("Deployments are not judged (Pods only, as the ClusterPolicy was)", g, "rogue-deploy", "ignored")
expect("only the agent namespace is in scope", g, "other-ns", "ignored")

print("== verify-image-signatures: a real signed image, verified offline-capable with the workshop key ==")
SIG = POL / "verify-image-signatures.yaml"
g = run(SIG, [pod("ours-signed", "agent", [c(SIGNED)]),
              pod("third-party", "agent", [c("docker.io/library/nginx:1.27-alpine")])])
expect("our signed image passes against policies/cosign/watch-it-burn.pub", g, "ours-signed", "pass")
expect("a third-party image is not asked for our signature", g, "third-party", "pass")
# The negative: the same image under a key that did not sign it must fail, or "pass" above proves nothing.
with tempfile.TemporaryDirectory() as tmp:
    key = pathlib.Path(tmp) / "k"
    if not shutil.which("openssl"):
        check("openssl is on PATH (needed to mint a wrong key for the negative case)", False)
    else:
        subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(key)], check=True,
                       capture_output=True)
        pub = subprocess.run(["openssl", "ec", "-in", str(key), "-pubout"], check=True, capture_output=True,
                             text=True).stdout.strip()
        text = SIG.read_text()
        start, end = text.index("-----BEGIN PUBLIC KEY-----"), text.index("-----END PUBLIC KEY-----") + 24
        indent = " " * (start - text.rfind("\n", 0, start) - 1)
        wrong = pathlib.Path(tmp) / "wrong-key.yaml"
        wrong.write_text(text[:start] + ("\n" + indent).join(pub.splitlines()) + text[end:])
        g = run(wrong, [pod("ours-signed", "agent", [c(SIGNED)])])
        expect("the same image under a different key fails with the named message", g, "ours-signed", "fail",
               "must carry a valid cosign signature")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All Kyverno CEL policy checks passed.")
