# ABOUTME: Runs every Kyverno CEL policy through the Kyverno CLI against fixture requests: the villain image,
# ABOUTME: Beat 1's limit-less Deployment, drift by agent-sa, the floor, and real signed images on ghcr.io.
# SUITE: e2e (needs the kyverno CLI v1.19.1 on PATH, and network to ghcr.io and ECR for the signature checks)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, kustomize_images  # noqa: E402
from mirror_copies import COPIES  # noqa: E402
import yaml  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
POL = REPO / "policies/kyverno"
FLOOR = REPO / "policies/floor/minimal-floor.yaml"
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

USERS = {
    "agent-sa": ("system:serviceaccount:agent:agent-sa",
                 ["system:serviceaccounts", "system:serviceaccounts:agent", "system:authenticated"]),
    "student": ("attendee", ["system:authenticated"]),
    "argocd": ("system:serviceaccount:argocd:argocd-application-controller",
               ["system:serviceaccounts", "system:serviceaccounts:argocd", "system:authenticated"]),
    "kagent": ("system:serviceaccount:kagent:kagent-controller",
               ["system:serviceaccounts", "system:serviceaccounts:kagent", "system:authenticated"]),
    "datadog-operator": ("system:serviceaccount:datadog:datadog-operator",
                         ["system:serviceaccounts", "system:serviceaccounts:datadog", "system:authenticated"]),
    "kube-controller": ("system:serviceaccount:kube-system:deployment-controller",
                        ["system:serviceaccounts", "system:serviceaccounts:kube-system", "system:authenticated"]),
    "admin": ("kubernetes-admin", ["system:masters", "system:authenticated"]),
    "agentgateway": ("system:serviceaccount:agent:agentgateway",
                     ["system:serviceaccounts", "system:serviceaccounts:agent", "system:authenticated"]),
    "web-terminal": ("system:serviceaccount:agent:web-terminal",
                     ["system:serviceaccounts", "system:serviceaccounts:agent", "system:authenticated"]),
    "replicaset-controller": ("system:serviceaccount:kube-system:replicaset-controller",
                              ["system:serviceaccounts", "system:serviceaccounts:kube-system", "system:authenticated"]),
}

TRACKED = {"argocd.argoproj.io/tracking-id": "ai-layer:apps/Deployment:agent/guard-proxy"}
LIMITS = {"limits": {"cpu": "100m", "memory": "64Mi"}}
VILLAIN = "ghcr.io/peopleforrester/lab-platform/promo/promo-mascot:v1"
SIGNED = ("ghcr.io/peopleforrester/watch-it-burn:busybox-1.36"
          "@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662")
# lab-platform's llm-guard as the ai-layer Application pins it (#652), signed by lab-platform with the workshop
# key (#669), at the chart's default registry and at an ECR pull-through cache path a root can pass instead.
_GUARD = next(i for i in kustomize_images(yaml.safe_load((APPS / "ai-layer.yaml").read_text(encoding="utf-8")))
              if i["name"] == "llm-guard")
GUARD = f"{_GUARD['newName']}:{_GUARD['newTag']}@{_GUARD['digest']}".replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR)
CACHE = "123456789012.dkr.ecr.us-west-2.amazonaws.com/lp-shared/peopleforrester/lab-platform"
GUARD_CACHE = GUARD.replace(LAB_PLATFORM_GHCR, CACHE)
# A mirror/ copy by digest, as an unsigned image of lab-platform's that the scope must leave out (question 878).
MIRROR = next(f"{LAB_PLATFORM_GHCR}/{x.path}@{x.digest}" for x in COPIES if "falcosidekick" in x.path)


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
              pod("lab-platform", "apps", [c("ghcr.io/peopleforrester/lab-platform/web:v1"),
                                          c("ghcr.io/peopleforrester/lab-platform/mirror/mcp/grafana:latest-208f8ea16064",
                                            name="d")]),
              pod("promo-via-ecr", "agent",
                  [c("123456789012.dkr.ecr.us-west-2.amazonaws.com/ghcr/peopleforrester/lab-platform/promo/joker:v1")]),
              pod("promo-beside-ok", "agent", [c(), c("ghcr.io/peopleforrester/lab-platform/promo/joker:v1", name="d")]),
              pod("old-villain", "agent", [c("docker.io/peopleforrester/promo-mascot:latest")]),
              pod("elsewhere", "default", [c(VILLAIN)])])
expect("the villain Pod in agent fails with the named message", g, "villain", "fail", REG_MSG)
expect("the villain DEPLOYMENT fails too (autogen), so deploy_app is refused at the Deployment",
       g, "promo-mascot", "fail", REG_MSG)
expect("every ai-layer registry passes", g, "ai-layer", "pass")
expect("docker.io/library, ECR and registry.k8s.io pass in apps", g, "apps-ok", "pass")
expect("an ECR-looking path on another host does not pass as ECR", g, "spoofed-ecr", "fail", REG_MSG)
expect("a docker.io user namespace is not docker.io/library", g, "docker-user", "fail", REG_MSG)
# #653: the villain is on ghcr.io, which stays allowed, so the refusal is the promo/ path and only that path.
expect("lab-platform's other ghcr.io paths (web, mirror/) still pass", g, "lab-platform", "pass")
expect("the promo/ path is refused through an ECR pull-through cache too", g, "promo-via-ecr", "fail", REG_MSG)
expect("one promo/ container fails a Pod whose other containers pass", g, "promo-beside-ok", "fail", REG_MSG)
expect("the old Docker Hub villain is still refused", g, "old-villain", "fail", REG_MSG)
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

# #529: each ValidatingPolicy is its own webhook and the first to answer is the deny message, so the probe's C2
# Deployment must break the registry allow-list and nothing else.
sys.path.insert(0, str(REPO / "verify"))
import kubecon_probe as kp  # noqa: E402
print("== the KubeCon probe's C2 Deployment: only the registry wall denies it ==")
g = run(LIM, [kp.C2_MANIFEST], user="agent-sa")
expect("the probe's C2 Deployment passes require-resource-limits", g, "promo-mascot", "pass")
g = run(REG, [kp.C2_MANIFEST], user="agent-sa")
expect("and fails restrict-image-registries with the named message", g, "promo-mascot", "fail", REG_MSG)

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
# C7's live gateway rule (#496, #515): the terminal may UPDATE agentgateway-c7-config, and nothing else changes.
c7_cm = {"apiVersion": "v1", "kind": "ConfigMap",
         "metadata": {"name": "agentgateway-c7-config", "namespace": "agent", "annotations": TRACKED}}
gw_cm = {"apiVersion": "v1", "kind": "ConfigMap",
         "metadata": {"name": "agentgateway-config", "namespace": "agent", "annotations": TRACKED}}
g = run(DRIFT, [c7_cm, gw_cm], operation="UPDATE", user="web-terminal")
expect("the terminal may UPDATE agentgateway-c7-config (guard-mcp-on/off)", g, "agentgateway-c7-config", "ignored")
expect("but not agentgateway-config, which carries every other route", g, "agentgateway-config", "fail", DRIFT_MSG)
g = run(DRIFT, [c7_cm], operation="DELETE", user="web-terminal")
expect("nor DELETE agentgateway-c7-config", g, "agentgateway-c7-config", "fail", DRIFT_MSG)
g = run(DRIFT, [c7_cm], operation="UPDATE", user="agent-sa")
expect("and agent-sa may not UPDATE it (the agent cannot switch off its own C7 guard)", g,
       "agentgateway-c7-config", "fail", DRIFT_MSG)

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
# #477: Falco runs in security, BurritoBot in agent, the Datadog agent in datadog. None was protected.
ds = lambda n, namespace: {**deploy(n, namespace, [c()]), "kind": "DaemonSet"}
g = run(FLOOR, [ns("agent"), ns("security"), ns("datadog"), ds("falco", "security"),
                ds("datadog-agent", "datadog"), deploy("promo-mascot", "agent", [c()])],
        operation="DELETE", user="student")
for n in ("agent", "security", "datadog"):
    expect(f"the {n} namespace cannot be deleted", g, n, "fail", FLOOR_NS_MSG)
expect("Falco's DaemonSet in security cannot be deleted", g, "falco", "fail", FLOOR_WL_MSG)
expect("the Datadog agent DaemonSet cannot be deleted", g, "datadog-agent", "fail", FLOOR_WL_MSG)
expect("the student can still clean up the villain in agent (Challenge 2)", g, "promo-mascot", "ignored")
g = run(FLOOR, [ds("datadog-agent", "datadog")], operation="DELETE", user="datadog-operator")
expect("the Datadog operator may replace the DaemonSet it owns", g, "datadog-agent", "pass")

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
    pod("rogue-init", "agent", [c("x")], init=[env("OPENAI_API_BASE", "https://api.openai.com/v1")]),
    pod("guard-proxy-impostor-6d9f", "agent", [env("OPENAI_BASE_URL", "https://api.openai.com/v1")]),
    pod("agentgateway-impostor-0", "agent", [env("ANTHROPIC_BASE_URL", "https://api.anthropic.com")]),
    pod("guard-proxy-6d9f", "agent", [c("x", env=[{"name": "AGENT_URL", "value": "http://agentgateway.agent.svc.cluster.local:3000"}])]),
    deploy("rogue-deploy", "agent", [env("OPENAI_BASE_URL", "https://api.openai.com/v1")]),
    pod("other-ns", "apps", [env("OPENAI_BASE_URL", "https://api.openai.com/v1")])])
BYPASS = "This pod sets an LLM endpoint pointing at a public API."
expect("OPENAI_BASE_URL at api.openai.com is reported", g, "rogue-openai", "fail", BYPASS)
expect("ANTHROPIC_BASE_URL at api.anthropic.com is reported", g, "rogue-anthropic", "fail", BYPASS)
expect("OPENAI_API_BASE at api.openai.com is reported", g, "rogue-legacy", "fail", BYPASS)
expect("a base URL pointed at guard-proxy passes", g, "routed", "pass")
expect("an init container is judged like any other (#333)", g, "rogue-init", "fail", BYPASS)
# #333: the name exemption these replace let any pod named guard-proxy-* or agentgateway* through unseen.
expect("a pod NAMED like guard-proxy gets no pass for the name (#333)", g, "guard-proxy-impostor-6d9f", "fail", BYPASS)
expect("a pod NAMED like agentgateway gets no pass for the name (#333)", g, "agentgateway-impostor-0", "fail", BYPASS)
expect("guard-proxy as deployed passes on its own env, with no exemption", g, "guard-proxy-6d9f", "pass")
expect("Deployments are not judged (Pods only, as the ClusterPolicy was)", g, "rogue-deploy", "ignored")
expect("only the agent namespace is in scope", g, "other-ns", "ignored")

print("== restrict-agent-spawned-workloads: the bypass deny-llm-endpoint-bypass cannot see (#490) ==")
SPAWN = POL / "restrict-agent-spawned-workloads.yaml"
AS_IDENTITY = "may not run as a ServiceAccount that holds Bedrock credentials"
AS_LABEL = "may not carry a label that a NetworkPolicy trusts"


def runs_as(obj, sa, field="serviceAccountName"):
    spec = obj["spec"]["template"]["spec"] if obj["kind"] == "Deployment" else obj["spec"]
    spec[field] = sa
    return obj


CONSOLE = {"app.kubernetes.io/name": "console"}
# The peers gitops/ai-layer/chat-path-ingress.yaml trusts (#552): each one opens a port on the chat path around guard-proxy.
TRUSTED = ("guard-proxy", "workshop-agent", "agentgateway")
# No env var at all: the SDK's default endpoint (or Bedrock's default regional hostname) needs none.
g = run(SPAWN, [runs_as(pod("as-agent-sa", "agent", [c()]), "agent-sa"),
                runs_as(pod("as-agentgateway", "agent", [c()]), "agentgateway"),
                runs_as(pod("as-web-terminal", "agent", [c()]), "web-terminal"),
                runs_as(pod("as-agent-sa-deprecated", "agent", [c()]), "agent-sa", field="serviceAccount"),
                runs_as(deploy("deploy-as-agent-sa", "agent", [c()]), "agent-sa"),
                pod("console-impostor", "agent", [c()], labels=CONSOLE),
                deploy("deploy-console-impostor", "agent", [c()], labels=CONSOLE),
                *[pod(f"{name}-impostor", "agent", [c()], labels={"app.kubernetes.io/name": name}) for name in TRUSTED],
                pod("plain", "agent", [c()], labels={"app": "plain"}),
                runs_as(pod("elsewhere", "apps", [c()]), "agent-sa")], user="agent-sa")
expect("agent-sa may not start a pod as agent-sa (Bedrock over PrivateLink)", g, "as-agent-sa", "fail", AS_IDENTITY)
expect("nor as agentgateway, the gateway's Bedrock identity", g, "as-agentgateway", "fail", AS_IDENTITY)
expect("nor as web-terminal, the tutor's", g, "as-web-terminal", "fail", AS_IDENTITY)
expect("the deprecated serviceAccount field is read too", g, "as-agent-sa-deprecated", "fail", AS_IDENTITY)
expect("a Deployment is refused at the Deployment (autogen)", g, "deploy-as-agent-sa", "fail", AS_IDENTITY)
expect("a pod labelled like the console is refused (its egress is open)", g, "console-impostor", "fail", AS_LABEL)
expect("so is a Deployment whose template is labelled like it", g, "deploy-console-impostor", "fail", AS_LABEL)
expect("a pod labelled like guard-proxy is refused (agentgateway :3000 admits it: the agent, unguarded)", g,
       "guard-proxy-impostor", "fail", AS_LABEL)
expect("a pod labelled like workshop-agent is refused (agentgateway :3002 admits it: the model, unguarded)", g,
       "workshop-agent-impostor", "fail", AS_LABEL)
expect("a pod labelled like agentgateway is refused (workshop-agent :8080 admits it)", g,
       "agentgateway-impostor", "fail", AS_LABEL)
expect("a pod on the default ServiceAccount with ordinary labels passes", g, "plain", "pass")
expect("outside the agent namespace no association exists, so it is not in scope", g, "elsewhere", "ignored")
g = run(SPAWN, [kp.C2_MANIFEST], user="agent-sa")
expect("C2's villain Deployment is not this policy's business (the registry wall stays the lesson)", g,
       "promo-mascot", "pass")
# An UPDATE is judged the same: a pod's images are mutable, so patching workshop-mcp's own pod is a new workload.
g = run(SPAWN, [runs_as(pod("workshop-mcp-7c9d", "agent", [c()]), "agent-sa")], operation="UPDATE", user="agent-sa")
expect("agent-sa may not change a pod that already runs as agent-sa", g, "workshop-mcp-7c9d", "fail", AS_IDENTITY)
g = run(SPAWN, [runs_as(pod("as-agent-sa", "agent", [c()]), "agent-sa")], user="agentgateway")
expect("any agent-namespace identity is held to it, not only agent-sa", g, "as-agent-sa", "fail", AS_IDENTITY)
# The guarded path itself: the identities that really create these pods are not the agent's.
for who, obj, label in (
        ("replicaset-controller", runs_as(pod("workshop-agent-5f6b", "agent", [c()]), "agent-sa"),
         "the ReplicaSet controller creating the agent's own pod"),
        ("kagent", runs_as(deploy("workshop-agent", "agent", [c()]), "agent-sa"),
         "the kagent controller writing the workshop-agent Deployment"),
        ("argocd", runs_as(deploy("agentgateway", "agent", [c()], labels={"app.kubernetes.io/name": "agentgateway"}),
                           "agentgateway"), "Argo CD syncing agentgateway"),
        ("argocd", deploy("console", "agent", [c()], labels=CONSOLE), "Argo CD syncing the console"),
        ("web-terminal", runs_as(pod("student-pod", "agent", [c()]), "agent-sa"), "the attendee's terminal"),
        ("admin", runs_as(pod("operator-pod", "agent", [c()]), "agent-sa"), "the operator")):
    g = run(SPAWN, [obj], user=who)
    expect(f"{label} is not judged", g, obj["metadata"]["name"], "ignored")

print("== verify-image-signatures: a real signed image, verified offline-capable with the workshop key ==")
SIG = POL / "verify-image-signatures.yaml"
g = run(SIG, [pod("ours-signed", "agent", [c(SIGNED)]),
              pod("third-party", "agent", [c("docker.io/library/nginx:1.27-alpine")])])
expect("our signed image passes against policies/cosign/watch-it-burn.pub", g, "ours-signed", "pass")
expect("a third-party image is not asked for our signature", g, "third-party", "pass")
g = run(SIG, [pod("llm-guard", "agent", [c(GUARD)]), pod("llm-guard-cache", "agent", [c(GUARD_CACHE)])])
expect(f"lab-platform's llm-guard ({GUARD.split('@')[0]}) passes against the same key", g, "llm-guard", "pass")
# The fixture's ECR account is no one's, so Kyverno's read of the guard there is refused. That it reads there at
# all is what says the cache path is in scope; a reference out of scope is never fetched.
expect("the guard at an ECR cache path is in scope: Kyverno reads its manifest from the cache", g, "llm-guard-cache",
       "error", f"{CACHE.split('/')[0]}/v2/lp-shared/peopleforrester/lab-platform/llm-guard/manifests/")
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
        g = run(wrong, [pod("ours-signed", "agent", [c(SIGNED)]), pod("llm-guard", "agent", [c(GUARD)]),
                        pod("mirror", "agent", [c(MIRROR)]), pod("villain", "agent", [c(VILLAIN)])])
        expect("the same image under a different key fails with the named message", g, "ours-signed", "fail",
               "must carry a valid cosign signature")
        expect("so does lab-platform's llm-guard", g, "llm-guard", "fail", "must carry a valid cosign signature")
        # Under a key that signed nothing, an image in scope fails; these pass because they are out of it.
        expect(f"an unsigned lab-platform mirror/ copy ({MIRROR.split('@')[0]}) is not in scope", g, "mirror", "pass")
        expect("nor is a promo/ villain, which restrict-image-registries refuses by path", g, "villain", "pass")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All Kyverno CEL policy checks passed.")
