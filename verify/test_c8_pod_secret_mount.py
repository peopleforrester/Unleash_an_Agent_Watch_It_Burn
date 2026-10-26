# ABOUTME: Holds #606: under c8-scoped-role.yaml agent-sa reads only ceo-personal-record through the API, and
# ABOUTME: restrict-agent-spawned-workloads refuses it every other Secret mounted in, or read through env by, a pod.
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
# #604 measured that gap open: a pod agent-sa created on the default ServiceAccount, mounting terminal-auth as a
# volume and through a secretKeyRef env var, was refused by none of the workshop policies. #606 closes it in
# restrict-agent-spawned-workloads, which refuses a workload created by an agent-namespace identity (web-terminal
# aside) that references any Secret but ceo-personal-record, the one the scoped Role reads. This test runs that
# with the same Kyverno engine the admission controller runs (the CLI pinned to the deployed v1.19.1, #572):
#
#   Part 1, RBAC (parsed from the Role). c8-scoped-role.yaml grants create on pods and scopes Secret reads to
#   get on ceo-personal-record, and the policy's allowed list is that same resourceNames list.
#
#   Part 2, admission (run through every workshop policy). #604's pod is refused, by restrict-agent-spawned-
#   workloads alone and on the Secret; the other ten still pass it or do not match it.
#
#   Part 3, every route on its own. A secret volume, a projected volume's secret source, an env secretKeyRef and an
#   envFrom secretRef, in a container or an init container, for each Secret a pod in agent can mount
#   (terminal-auth, console-tls, llm-guard-auth), is refused with the matching message; so is a Deployment at the
#   Deployment (autogen), and an UPDATE. The same routes to ceo-personal-record pass every policy, as do a pod
#   with a ConfigMap volume or an imagePullSecret, and the attendee's terminal and the operator are not judged.
#
# The AWS credentials Secret #604 names as an example is out of reach anyway: #584 moved student-aws-creds to
# namespace student-creds, and a pod mounts only Secrets from its own namespace.
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

SPAWN = POL / "restrict-agent-spawned-workloads.yaml"
policy = yaml.safe_load(SPAWN.read_text())
variables = {v["name"]: v["expression"] for v in policy["spec"].get("variables") or []}
allowed = yaml.safe_load(variables.get("readableSecrets", "[]"))
check("restrict-agent-spawned-workloads allows exactly the Secrets the scoped Role reads",
      allowed == secrets.get("resourceNames"), f"policy allows {allowed!r}, the Role reads {secrets.get('resourceNames')!r}")

# --- Part 2: #604's pod, through every workshop policy ------------------------------------------------------
LIMITS = {"limits": {"cpu": "100m", "memory": "64Mi"}}
AS_VOLUME = "may not mount a Secret other than ceo-personal-record"
AS_ENV = "may not take an env var from a Secret other than ceo-personal-record"


def container(name="c", env=None, env_from=None, mounts=None):
    return {"name": name, "image": "docker.io/library/busybox:1.36", "resources": LIMITS,
            "command": ["sh", "-c", "cat /stolen/*; env"],
            **({"env": env} if env else {}), **({"envFrom": env_from} if env_from else {}),
            **({"volumeMounts": mounts} if mounts else {})}


def pod(name, containers, volumes=None, init=None, sa="default", labels=None, **extra):
    spec = {"serviceAccountName": sa, "containers": containers, **extra}
    if volumes:
        spec["volumes"] = volumes
    if init:
        spec["initContainers"] = init
    return {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": name, "namespace": "agent", "labels": labels or {"app": "exfil"}}, "spec": spec}


def deployment(p):
    meta = p["metadata"]
    return {"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": meta["name"], "namespace": "agent", "labels": meta["labels"]},
            "spec": {"replicas": 1, "selector": {"matchLabels": meta["labels"]},
                     "template": {"metadata": {"labels": meta["labels"]}, "spec": p["spec"]}}}


MOUNT = [{"name": "stolen", "mountPath": "/stolen", "readOnly": True}]


def secret_volume(secret):
    return [{"name": "stolen", "secret": {"secretName": secret}}]


def projected_volume(secret):
    return [{"name": "stolen", "projected": {"sources": [{"configMap": {"name": "cluster-identity"}},
                                                         {"secret": {"name": secret}}]}}]


def key_ref(secret, key="k"):
    return [{"name": "PW", "valueFrom": {"secretKeyRef": {"name": secret, "key": key}}}]


def exfil(name, secret="terminal-auth", key="TTYD_CREDENTIAL", sa="default", labels=None):
    """#604's pod: default ServiceAccount, an allowed image, resource limits, an ordinary label, reading one
    Secret both as a mounted volume and through a secretKeyRef env var."""
    return pod(name, [container(env=key_ref(secret, key), mounts=MOUNT)], volumes=secret_volume(secret),
               sa=sa, labels=labels)


ALL_POLICIES = sorted(POL.glob("*.yaml")) + [FLOOR]
print("\n== Part 2: #604's pod, mounting terminal-auth, through every workshop policy ==")
denied = {}
for p in ALL_POLICIES:
    res, msg = verdict(run(p, [exfil("exfil-terminal-auth")]), "exfil-terminal-auth")
    if res == "cli-error":
        check(f"{p.name} evaluates the pod", False, f"kyverno CLI failed: {msg}")
    elif res == "fail":
        denied[p.name] = msg
check("restrict-agent-spawned-workloads refuses the Secret-mounting pod, on the Secret",
      AS_VOLUME in denied.get(SPAWN.name, "") or AS_ENV in denied.get(SPAWN.name, ""), repr(denied))
check("and it is the only policy that refuses it (the others still pass it or do not match it)",
      list(denied) == [SPAWN.name], f"refused by: {sorted(denied)}")

# --- Part 3: every route on its own, each Secret, and what stays admitted -------------------------------------
print("\n== Part 3: each route to a Secret the Role does not read is refused ==")
# The Secrets a pod in agent can mount, besides ceo-personal-record: the shared terminal credential (fleet.sh),
# the console's certificate (resources.yaml) and the llm-guard token (ai-layer's kustomization secretGenerator).
OTHERS = ("terminal-auth", "console-tls", "llm-guard-auth")


def routes(secret, tag):
    """One pod per route, each reading `secret` that one way and no other."""
    return [
        (f"{tag}-volume", AS_VOLUME, pod(f"{tag}-volume", [container(mounts=MOUNT)], volumes=secret_volume(secret))),
        (f"{tag}-projected", AS_VOLUME,
         pod(f"{tag}-projected", [container(mounts=MOUNT)], volumes=projected_volume(secret))),
        (f"{tag}-keyref", AS_ENV, pod(f"{tag}-keyref", [container(env=key_ref(secret))])),
        (f"{tag}-envfrom", AS_ENV, pod(f"{tag}-envfrom", [container(env_from=[{"secretRef": {"name": secret}}])])),
        (f"{tag}-init-keyref", AS_ENV,
         pod(f"{tag}-init-keyref", [container()], init=[container("init", env=key_ref(secret))])),
        (f"{tag}-init-envfrom", AS_ENV,
         pod(f"{tag}-init-envfrom", [container()], init=[container("init", env_from=[{"secretRef": {"name": secret}}])])),
    ]


for secret in OTHERS:
    cases = routes(secret, secret)
    got = run(SPAWN, [obj for _, _, obj in cases])
    for name, want, _ in cases:
        res, msg = verdict(got, name)
        check(f"{name}: refused with the {'mount' if want == AS_VOLUME else 'env'} message",
              res == "fail" and want in msg, f"got {res}: {msg!r}")

dep = deployment(exfil("deploy-terminal-auth"))
res, msg = verdict(run(SPAWN, [dep]), "deploy-terminal-auth")
check("a Deployment whose template mounts terminal-auth is refused at the Deployment (autogen)",
      res == "fail" and (AS_VOLUME in msg or AS_ENV in msg), f"got {res}: {msg!r}")
res, msg = verdict(run(SPAWN, [exfil("exfil-update")], operation="UPDATE"), "exfil-update")
check("an UPDATE that references terminal-auth is refused too", res == "fail" and (AS_VOLUME in msg or AS_ENV in msg),
      f"got {res}: {msg!r}")
mixed = pod("ceo-volume-terminal-env", [container(env=key_ref("terminal-auth"), mounts=MOUNT)],
            volumes=secret_volume("ceo-personal-record"))
res, msg = verdict(run(SPAWN, [mixed]), "ceo-volume-terminal-env")
check("mounting ceo-personal-record buys no pass for a terminal-auth env var beside it", res == "fail" and AS_ENV in msg,
      f"got {res}: {msg!r}")
WORKSHOP_MCP = ("system:serviceaccount:agent:workshop-mcp",
                ["system:serviceaccounts", "system:serviceaccounts:agent", "system:authenticated"])
res, msg = verdict(run(SPAWN, [exfil("exfil-from-shell")], user=WORKSHOP_MCP), "exfil-from-shell")
check("workshop-mcp, the identity the agent's run_shell holds, is refused the same pod",
      res == "fail" and (AS_VOLUME in msg or AS_ENV in msg), f"got {res}: {msg!r}")

print("\n== Part 3: ceo-personal-record, and pods that read no Secret, are still admitted by every policy ==")
admitted = routes("ceo-personal-record", "ceo") + [
    ("ceo-both", None, exfil("ceo-both", secret="ceo-personal-record", key="record")),
    ("configmap-volume", None, pod("configmap-volume", [container(mounts=MOUNT)],
                                   volumes=[{"name": "stolen", "configMap": {"name": "cluster-identity"}}])),
    ("pull-secret", None, pod("pull-secret", [container()], imagePullSecrets=[{"name": "harbor-pull"}])),
    ("plain", None, pod("plain", [container()])),
]
for p in ALL_POLICIES:
    got = run(p, [obj for _, _, obj in admitted])
    if "__cli__" in got:
        check(f"{p.name} evaluates the pods", False, f"kyverno CLI failed: {got['__cli__'][1]}")
        continue
    refused = {name: verdict(got, name) for name, _, _ in admitted if verdict(got, name)[0] not in ("pass", "ignored")}
    check(f"{p.name} admits every ceo-personal-record route and the Secret-free pods", not refused, repr(refused))
    if p == SPAWN:
        # Evaluated, not merely unmatched: an "ignored" here would make the line above say nothing.
        unjudged = [name for name, _, _ in admitted if verdict(got, name)[0] != "pass"]
        check("restrict-agent-spawned-workloads judges each of them and returns pass", not unjudged, repr(unjudged))

print("\n== Part 3: only the agent's identities are judged ==")
WEB_TERMINAL = ("system:serviceaccount:agent:web-terminal",
                ["system:serviceaccounts", "system:serviceaccounts:agent", "system:authenticated"])
ADMIN = ("kubernetes-admin", ["system:masters", "system:authenticated"])
RS_CONTROLLER = ("system:serviceaccount:kube-system:replicaset-controller",
                 ["system:serviceaccounts", "system:serviceaccounts:kube-system", "system:authenticated"])
for who, label in ((WEB_TERMINAL, "the attendee's terminal"), (ADMIN, "the operator"),
                   (RS_CONTROLLER, "the ReplicaSet controller creating a Deployment's pod")):
    res, msg = verdict(run(SPAWN, [exfil("not-the-agent")], user=who), "not-the-agent")
    check(f"{label} mounting terminal-auth is not judged", res == "ignored", f"got {res}: {msg!r}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All #606 checks passed: the scoped Role closes the API read, and admission closes the pod mount.")
