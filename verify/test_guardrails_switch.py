# ABOUTME: Offline gate for the KubeCon guardrails switch (#774): both KubeCon profiles start with the four Kubernetes
# ABOUTME: guardrails off, guardrails-on and guardrails-off switch them on both clusters, and Kyverno denies external registries.
"""Michael's spec on #774 (2026-11-01):

1. Both clusters start with the four Kubernetes guardrails OFF (community/attackme and private).
2. One guardrails-on command arms BOTH clusters, run from either one's terminal, Kyverno to Enforce included, so
   external registries are denied. It is not per-cluster.
3. The badges come up the way they do when a control arms (guard-proxy's /controls), as each guardrail turns on.

What is checked here, without a cluster:
  * the two KubeCon profiles: burn and admin with exactly the breakout's differences, nothing selfHeal would arm, and
    fleet.sh picking them from event.sh, so the 2-hour workshop keeps burn and admin;
  * the registry policies: deny-external-registries for what the agent creates, registry.burritobot.co trusted by both;
  * the Argo CD Applications that let the switch's flips hold;
  * the terminal's guardrails-on and guardrails-off, run against a kubectl that plays two clusters: each prints every
    command it runs, switches all four on both, fails loudly when the other cluster is not linked or a flip does not
    hold, and touches the other cluster only within the guardrails-switch grant;
  * the objects it switches are the ones the chat page's badges read (guard-proxy's proxy.py);
  * fleet.sh guardrails-link, against fake aws and kubectl: each cluster gets the other's endpoint and token;
  * the internal registry: read-only through the console, pinned images, reachable in-cluster from the console alone.
The Kyverno CLI cases for deny-external-registries are in verify/test_breakout_registry_policy.py (tools tier).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, CHART, KUBECON_PROFILES, REPO, app_names, deploys, values  # noqa: E402
import registry_allowlist  # noqa: E402

# Offline means offline (#859): every subprocess below gets aws, kubectl, eksctl, terraform and helm as stubs that
# log the call and fail, even when the test is run by hand (verify/no_cloud.py). The last check reads the log.
import no_cloud  # noqa: E402
no_cloud.setup()

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def docs(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


ENTRYPOINT = REPO / "gitops/ai-layer/web-terminal/entrypoint.sh"
FLEET = REPO / "infra/terraform/fleet/fleet.sh"
BREAKOUT = REPO / "policies/kyverno-breakout/deny-external-registries.yaml"
SWITCH = REPO / "gitops/guardrails-switch/guardrails-switch.yaml"
REGISTRY = REPO / "gitops/internal-registry/internal-registry.yaml"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
FIXES = next(d for d in docs(RESOURCES) if d.get("kind") == "ConfigMap"
             and d["metadata"]["name"] == "challenge-fixes")["data"]
FOUR = ("rbac", "kyverno", "kubearmor", "egress")

print("== the two KubeCon profiles: burn and admin with the breakout's differences only ==")
community, private = app_names("kubecon-community"), app_names("kubecon-private")
check("kubecon-community stands in for burn and kubecon-private for admin",
      KUBECON_PROFILES == {"kubecon-community": "burn", "kubecon-private": "admin"})
check("kubecon-community is burn plus the Kyverno engine, its two registry policies and the switch's identity",
      set(community) == set(app_names("burn")) | {"kyverno", "kyverno-registry-policy", "kyverno-breakout",
                                                   "guardrails-switch"},
      str(sorted(set(community) ^ set(app_names("burn")))))
check("kubecon-private is admin without the two apps that arm egress and KubeArmor, plus the breakout's three",
      set(private) == (set(app_names("admin")) - {"network-policies", "kubearmor-policies"})
      | {"kyverno-breakout", "guardrails-switch", "internal-registry"},
      str(sorted(set(private) ^ set(app_names("admin")))))
for p in KUBECON_PROFILES:
    check(f"{p}: lists no app that would arm a guardrail from git (network-policies, kubearmor-policies)",
          not {"network-policies", "kubearmor-policies"} & set(app_names(p)))
    check(f"{p}: installs the KubeArmor and Kyverno engines the switch arms through",
          deploys(p, "kubearmor") and deploys(p, "kyverno"))
    check(f"{p}: installs deny-external-registries and the switch's identity",
          deploys(p, "kyverno-breakout") and deploys(p, "guardrails-switch"))
    check(f"{p}: takes restrict-image-registries from exactly one Application",
          deploys(p, "kyverno-policies") != deploys(p, "kyverno-registry-policy"))
    check(f"{p}: sets no guardrails action, so nothing arms at bootstrap", "guardrails" not in values(p))
check("only kubecon-community takes restrict-image-registries alone, so the room meets no other admission policy",
      [p for p in ("attendee", "burn", "admin", "full", "local-inference", *KUBECON_PROFILES)
       if deploys(p, "kyverno-registry-policy")] == ["kubecon-community"])
check("the internal registry runs on the private cluster only",
      [p for p in ("attendee", "burn", "admin", "full", "local-inference", *KUBECON_PROFILES)
       if deploys(p, "internal-registry")] == ["kubecon-private"])
check("kubecon-private keeps C7 at agentgateway's rule, as admin does",
      values("kubecon-private").get("c7Control") == "gateway" == values("admin").get("c7Control"))
check("no workshop profile lists a breakout app",
      not any(deploys(p, a) for p in ("attendee", "burn", "admin", "full", "local-inference")
              for a in ("kyverno-breakout", "kyverno-registry-policy", "guardrails-switch", "internal-registry")))
check("the workshop's admin profile still arms egress and KubeArmor from git",
      deploys("admin", "network-policies") and deploys("admin", "kubearmor-policies"))

print("== fleet.sh picks the profiles from the event; the workshop keeps burn and admin ==")


def fleet(expr: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f"source '{FLEET}' >/dev/null 2>&1; {expr}"], cwd=FLEET.parent,
                          capture_output=True, text=True, timeout=60, env={**os.environ, **(env or {})})


event = (REPO / "infra/terraform/fleet/event.sh").read_text(encoding="utf-8")
check("event.sh sets the roster's profiles to kubecon for KubeCon NA 2026",
      'WIB_ROSTER_PROFILES="${WIB_ROSTER_PROFILES:-kubecon}"' in event and "kubecon-na-2026" in event)
for setting, community_p, admin_p in (("kubecon", "kubecon-community", "kubecon-private"),
                                      ("workshop", "burn", "admin")):
    got = [fleet(f"bootstrap_profile_for_role {r}", {"WIB_ROSTER_PROFILES": setting}).stdout for r in ("community", "admin")]
    check(f"WIB_ROSTER_PROFILES={setting}: community gets {community_p}, admin gets {admin_p}",
          got == [community_p, admin_p], str(got))
bad = fleet("bootstrap_profile_for_role admin", {"WIB_ROSTER_PROFILES": "kubeconn"})
check("a misspelt WIB_ROSTER_PROFILES is refused by name, not built with some default",
      bad.returncode != 0 and not bad.stdout and "kubeconn" in bad.stderr, bad.stderr)
src = FLEET.read_text(encoding="utf-8")
inst = re.search(r"^cmd_instructors\(\) \{\n.*?^\}\n", src, re.S | re.M).group(0)
check("instructors up links the pair once it has built both, on the KubeCon profiles only",
      'if [[ -z "${WIB_NO_BOOTSTRAP:-}" && "${WIB_ROSTER_PROFILES:-}" == "kubecon" ]]' in inst
      and "cmd_guardrails_link || _rc=1" in inst)
check("bootstrap arms Kyverno on admin and full only, so neither KubeCon profile is armed before guardrails-on",
      '[[ "${profile}" == "full" || "${profile}" == "admin" ]] && arm_infra_guardrails' in src)
check("fleet.sh dispatches guardrails-link", "guardrails-link) cmd_guardrails_link" in src)

print("== the registry policies ==")
pol = docs(BREAKOUT)[0]
spec = pol["spec"]
var = {v["name"]: v["expression"] for v in spec["variables"]}
check("deny-external-registries is a ValidatingPolicy that ships at [Audit]",
      pol["kind"] == "ValidatingPolicy" and pol["apiVersion"] == "policies.kyverno.io/v1"
      and spec["validationActions"] == ["Audit"])
check("it is evaluated at admission only: it reads request.userInfo",
      spec["evaluation"] == {"admission": {"enabled": True}, "background": {"enabled": False}})
check("it matches Pods on CREATE and UPDATE in the agent namespace (autogen covers Deployments and the rest)",
      spec["matchConstraints"] == {"resourceRules": [{"apiGroups": [""], "apiVersions": ["v1"],
                                                      "operations": ["CREATE", "UPDATE"], "resources": ["pods"]}],
                                   "namespaceSelector": {"matchExpressions": [{
                                       "key": "kubernetes.io/metadata.name", "operator": "In", "values": ["agent"]}]}})
agent_roles = [d for d in docs(RESOURCES) if d.get("kind") == "Role"] + \
    [d for d in yaml.safe_load_all(FIXES["c8-broad-role.yaml"]) if d]
check("every Role an agent identity is bound to lives in agent, so agent is the one namespace it can create in",
      {d["metadata"].get("namespace", "agent") for d in agent_roles if d["metadata"]["name"] == "workshop-agent"}
      == {"agent"})
cond = " ".join(c["expression"] for c in spec["matchConditions"])
check("it applies to the agent namespace's identities, the presenters' terminal excepted",
      "startsWith('system:serviceaccount:agent:')" in cond and "!= 'system:serviceaccount:agent:web-terminal'" in cond)
check("the one registry it trusts is registry.burritobot.co", var.get("internalRegistry") == "'registry.burritobot.co/'")
check("it reads init containers as well as containers",
      "initContainers" in var.get("containers", "") and "containers" in var.get("containers", ""))
check("it names the internal registry in its message", "registry.burritobot.co" in spec["validations"][0]["message"])
check("policies/kyverno-breakout holds that policy, the room sweep and its grant, and no kustomization, so Argo CD "
      "reads it as a directory",
      sorted(p.name for p in BREAKOUT.parent.iterdir()) == ["deny-external-registries.yaml",
                                                             "remove-untrusted-room-workloads-rbac.yaml",
                                                             "remove-untrusted-room-workloads.yaml"])

print("== the room sweep (#990): guardrails-on takes the room's untrusted workloads off the cluster ==")
SWEEP = BREAKOUT.parent / "remove-untrusted-room-workloads.yaml"
dpol = docs(SWEEP)[0]
dspec = dpol["spec"]
dvar = {v["name"]: v["expression"] for v in dspec["variables"]}
dcond = {c["name"]: " ".join(c["expression"].split()) for c in dspec["conditions"]}
check("remove-untrusted-room-workloads is a DeletingPolicy that runs every minute and deletes in the background",
      dpol["kind"] == "DeletingPolicy" and dpol["apiVersion"] == "policies.kyverno.io/v1"
      and dspec["schedule"] == "* * * * *" and dspec["deletionPropagationPolicy"] == "Background")
check("it matches the workload kinds in the agent namespace alone, as deny-external-registries does",
      dspec["matchConstraints"]["namespaceSelector"] == spec["matchConstraints"]["namespaceSelector"]
      and sorted(r for rule in dspec["matchConstraints"]["resourceRules"] for r in rule["resources"])
      == ["cronjobs", "daemonsets", "deployments", "jobs", "pods", "replicasets", "statefulsets"])
check("it deletes only while deny-external-registries reads Deny, so nothing goes at the Audit start state",
      dcond.get("guardrails-on") == 'resource.Get("policies.kyverno.io/v1", "validatingpolicies", "", '
      "\"deny-external-registries\") .spec.validationActions.exists(a, a == 'Deny')", str(dcond.get("guardrails-on")))
check("and reads that policy last, after the cheap conditions",
      list(dcond) == ["deployed-for-the-room", "runs-an-untrusted-image", "guardrails-on"], str(list(dcond)))
mcp_src = (REPO / "gitops/ai-layer/workshop-mcp-server.py").read_text(encoding="utf-8")
check("the room's workloads are known by the label deploy_app stamps on every one, burritobot.co/workload",
      'WORKLOAD_LABEL = "burritobot.co/workload"' in mcp_src
      and "'burritobot.co/workload' in variables.pod" in dcond.get("deployed-for-the-room", ""))
check("an owned object (a Deployment's ReplicaSet, its Pods) is left to go with its owner",
      "ownerReferences.orValue([]).size() == 0" in dcond.get("deployed-for-the-room", ""))
check("the one registry it keeps is the one deny-external-registries trusts",
      dvar.get("internalRegistry") == var.get("internalRegistry") == "'registry.burritobot.co/'")
check("it reads init containers as well as containers",
      "initContainers" in dvar.get("containers", "") and "containers" in dvar.get("containers", ""))


def pod_labels(d: dict) -> dict:
    """The labels on the pods a workload in git makes."""
    if d.get("kind") == "Pod":
        return (d.get("metadata") or {}).get("labels") or {}
    s = d.get("spec") or {}
    if d.get("kind") == "CronJob":
        s = ((s.get("jobTemplate") or {}).get("spec")) or {}
    return (((s.get("template") or {}).get("metadata")) or {}).get("labels") or {}


WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob", "Pod"}
platform_workloads, labelled = 0, []
for f in sorted((REPO / "gitops").rglob("*.yaml")):
    try:
        found = [d for d in yaml.safe_load_all(f.read_text(encoding="utf-8")) if isinstance(d, dict)]
    except yaml.YAMLError:
        continue  # a Helm template; the chart's own tests render it
    for d in found:
        if d.get("kind") in WORKLOAD_KINDS:
            platform_workloads += 1
            if "burritobot.co/workload" in pod_labels(d):
                labelled.append(f"{f.relative_to(REPO)}: {d['kind']}/{d['metadata']['name']}")
check("no platform workload in git carries the room label, so none can match",
      platform_workloads > 10 and not labelled, f"{platform_workloads} workloads; labelled: {labelled}")
grant = docs(BREAKOUT.parent / "remove-untrusted-room-workloads-rbac.yaml")
check("its grant is one ClusterRole, aggregated into Kyverno's cleanup controller",
      len(grant) == 1 and grant[0]["kind"] == "ClusterRole"
      and grant[0]["metadata"]["labels"] == {"rbac.kyverno.io/aggregate-to-cleanup-controller": "true"})
DGRANT = {(r["apiGroups"][0], res, n): set(r["verbs"]) for r in grant[0]["rules"] for res in r["resources"]
          for n in (r.get("resourceNames") or ["*"])}
check("which reads deny-external-registries by name and deletes only the kinds the policy matches",
      DGRANT == {("policies.kyverno.io", "validatingpolicies", "deny-external-registries"): {"get"},
                 **{("apps", k, "*"): {"get", "list", "watch", "delete"}
                    for k in ("deployments", "statefulsets", "daemonsets", "replicasets")},
                 **{("batch", k, "*"): {"get", "list", "watch", "delete"} for k in ("jobs", "cronjobs")},
                 ("", "pods", "*"): {"get", "list", "watch", "delete"}}, str(DGRANT))
check("deny-external-registries' own comment points at the sweep for what was running before the flip",
      "remove-untrusted-room-workloads" in BREAKOUT.read_text(encoding="utf-8"))
check("restrict-image-registries trusts the internal registry too (#775's image passes it at Deny)",
      "registry.burritobot.co/" in registry_allowlist.prefixes()
      and registry_allowlist.allowed("registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0"))
rir = docs(REPO / "policies/kyverno/restrict-image-registries.yaml")[0]
check("and its message says so", "registry.burritobot.co" in rir["spec"]["validations"][0]["message"])
check("a lookalike host is not the internal registry",
      not registry_allowlist.allowed("registry.burritobot.co.evil.example/x:1"))

print("== the Applications that let the switch's flips hold ==")
for app_file, policy in (("kyverno-breakout", "deny-external-registries"),
                         ("kyverno-registry-policy", "restrict-image-registries")):
    app = yaml.safe_load((APPS / f"{app_file}.yaml").read_text(encoding="utf-8"))
    sp = app["spec"]
    check(f"{app_file}: ignores drift on {policy}'s /spec/validationActions, and only that",
          sp.get("ignoreDifferences") == [{"group": "policies.kyverno.io", "kind": "ValidatingPolicy", "name": policy,
                                           "jsonPointers": ["/spec/validationActions"]}])
    check(f"{app_file}: honours the ignore on sync too", "RespectIgnoreDifferences=true" in sp["syncPolicy"]["syncOptions"])
    check(f"{app_file}: selfHeal stays on for every other field", sp["syncPolicy"]["automated"]["selfHeal"] is True)
reg_app = yaml.safe_load((APPS / "kyverno-registry-policy.yaml").read_text(encoding="utf-8"))["spec"]["source"]
check("kyverno-registry-policy reads restrict-image-registries.yaml alone, as a directory source",
      reg_app["path"] == "policies/kyverno" and reg_app.get("directory") == {"include": "restrict-image-registries.yaml"}
      and "kustomize" not in reg_app)
for app_file, path in (("kyverno-breakout", "policies/kyverno-breakout"), ("guardrails-switch", "gitops/guardrails-switch"),
                       ("internal-registry", "gitops/internal-registry")):
    src_ = yaml.safe_load((APPS / f"{app_file}.yaml").read_text(encoding="utf-8"))["spec"]["source"]
    check(f"{app_file}: syncs {path}", src_["path"] == path and (REPO / path).is_dir())

print("== the switch's identity on each cluster: the four guardrails' objects and nothing else ==")
sw = docs(SWITCH)
by = {(d["kind"], d["metadata"].get("namespace"), d["metadata"]["name"]): d for d in sw}
check("its own namespace, guardrails-switch", ("Namespace", None, "guardrails-switch") in by)
tok = by.get(("Secret", "guardrails-switch", "guardrails-switch-token"), {})
check("a long-lived token for the guardrails-switch ServiceAccount",
      tok.get("type") == "kubernetes.io/service-account-token"
      and tok["metadata"]["annotations"] == {"kubernetes.io/service-account.name": "guardrails-switch"}
      and ("ServiceAccount", "guardrails-switch", "guardrails-switch") in by)
role = by[("Role", "agent", "guardrails-switch")]
crole = by[("ClusterRole", None, "guardrails-switch")]
GRANT: dict[tuple[str, str, str], set[str]] = {}
for scope, rules in (("agent", role["rules"]), ("", crole["rules"])):
    for r in rules:
        for res in r["resources"]:
            for name in r.get("resourceNames") or ["*"]:
                GRANT.setdefault((scope, res, name), set()).update(r["verbs"])
check("the grant: the workshop-agent Role (get, patch, escalate), the two registry policies (get, patch), and "
      "KubeArmor policies and NetworkPolicies in agent (get, create, patch, delete)",
      GRANT == {("agent", "roles", "workshop-agent"): {"get", "patch", "escalate"},
                ("agent", "kubearmorpolicies", "*"): {"get", "create", "patch", "delete"},
                ("agent", "networkpolicies", "*"): {"get", "create", "patch", "delete"},
                ("", "validatingpolicies", "restrict-image-registries"): {"get", "patch"},
                ("", "validatingpolicies", "deny-external-registries"): {"get", "patch"}}, str(GRANT))
bindings = [d for d in sw if d["kind"] in ("RoleBinding", "ClusterRoleBinding")]
check("both bindings name the guardrails-switch ServiceAccount alone",
      len(bindings) == 2 and all(b["subjects"] == [{"kind": "ServiceAccount", "name": "guardrails-switch",
                                                    "namespace": "guardrails-switch"}] for b in bindings))
everything = [d for path in sorted(REPO.glob("gitops/**/*.yaml")) if path.is_file() and "templates" not in path.parts
              and "guard-proxy" not in path.parts for d in docs(path)]
agent_grants = [d for d in everything if d.get("kind") in ("RoleBinding", "Role")
                and (d.get("metadata") or {}).get("namespace") == "guardrails-switch"]
check("no Role or RoleBinding lives in guardrails-switch, so no agent identity reads the peer's token",
      not agent_grants, str([d["metadata"]["name"] for d in agent_grants]))
term = next(d for d in docs(RESOURCES) if d.get("kind") == "ClusterRole" and d["metadata"]["name"] == "console-terminal")
check("the terminal's own ClusterRole reads Secrets everywhere, which is how guardrails-on reads guardrails-peer",
      any("*" in r["resources"] and "get" in r["verbs"] for r in term["rules"]))
for f, kinds in (("c1-network-policy.yaml", {"NetworkPolicy"}), ("c3-kubearmor-policy.yaml", {"KubeArmorPolicy"}),
                 ("c5-scoped-role.yaml", {"Role"}), ("c8-broad-role.yaml", {"Role"})):
    ds = [d for d in yaml.safe_load_all(FIXES[f]) if d]
    check(f"~/challenges/{f} holds only {sorted(kinds)} in agent",
          {d["kind"] for d in ds} == kinds and {d["metadata"]["namespace"] for d in ds} == {"agent"})

print("== the badges read the objects the switch turns on (guard-proxy's /controls) ==")
proxy = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text(encoding="utf-8")
c1 = [d["metadata"]["name"] for d in yaml.safe_load_all(FIXES["c1-network-policy.yaml"]) if d]
c3 = yaml.safe_load(FIXES["c3-kubearmor-policy.yaml"])
for what, path in (("the egress badge: agent-egress-allowlist, in the staged egress set",
                    "/networkpolicies/agent-egress-allowlist"),
                   ("the Kyverno badge: restrict-image-registries", "/validatingpolicies/restrict-image-registries"),
                   ("the KubeArmor badge: block-recipe-snoop, the staged KubeArmor policy",
                    "/kubearmorpolicies/block-recipe-snoop"),
                   ("the RBAC badge: the workshop-agent Role the staged Roles replace", "/roles/workshop-agent")):
    check(what, path in proxy)
check("the staged files carry those names", "agent-egress-allowlist" in c1 and c3["metadata"]["name"] == "block-recipe-snoop")

print("== guardrails-on and guardrails-off, run against a kubectl that plays two clusters ==")
FAKE = r'''#!/usr/bin/env python3
import base64, json, os, sys
a = sys.argv[1:]
peer = "--kubeconfig" in a
if peer:
    i = a.index("--kubeconfig"); a = a[:i] + a[i + 2:]
    j = a.index("--context"); ctx = a[j + 1]; a = a[:j] + a[j + 2:]
else:
    ctx = "this"
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps({"cluster": ctx, "args": a}) + "\n")
state = json.load(open(os.environ["STATE"]))
mode = os.environ.get("MODE", "linked")
if "guardrails-peer" in a:
    if mode == "unlinked":
        sys.stderr.write('Error from server (NotFound): secrets "guardrails-peer" not found\n'); sys.exit(1)
    key = a[-1]
    print(base64.b64encode(b"apiVersion: v1\nkind: Config\n" if "kubeconfig" in key else b"watch-it-burn-community").decode())
    sys.exit(0)
if mode == "peer-down" and ctx != "this":
    sys.stderr.write("Unable to connect to the server\n"); sys.exit(1)
if "patch" in a and "validatingpolicy" in a:
    if not (mode == "peer-kyverno-stuck" and ctx != "this"):
        state.setdefault(ctx, {})[a[a.index("validatingpolicy") + 1]] = json.loads(a[a.index("-p") + 1])[0]["value"][0]
elif "get" in a and "validatingpolicy" in a:
    sys.stdout.write(state.get(ctx, {}).get(a[a.index("validatingpolicy") + 1], "Audit"))
json.dump(state, open(os.environ["STATE"], "w"))
'''
helpers = dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', ENTRYPOINT.read_text(encoding="utf-8"), re.S))
check("the terminal ships guardrails-on and guardrails-off", {"guardrails-on", "guardrails-off"} <= set(helpers))


def run(cmd: str, mode: str = "linked", args: tuple[str, ...] = ()) -> tuple[subprocess.CompletedProcess, list[dict], list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        home, fakebin = pathlib.Path(tmp, "home"), pathlib.Path(tmp, "bin")
        home.mkdir(); fakebin.mkdir()  # noqa: E702
        (home / "challenges").mkdir()
        for name, body in FIXES.items():
            (home / "challenges" / name).write_text(body)
        for name, body in helpers.items():
            (home / name).write_text(body + "\n")
        (fakebin / "kubectl").write_text(FAKE)
        (fakebin / "kubectl").chmod(0o755)
        calls, state = pathlib.Path(tmp, "calls"), pathlib.Path(tmp, "state")
        state.write_text("{}")
        env = {**os.environ, "HOME": str(home), "PATH": f"{fakebin}:{os.environ['PATH']}", "CALLS": str(calls),
               "STATE": str(state), "MODE": mode}
        r = subprocess.run(["bash", str(home / cmd), *args], env=env, capture_output=True, text=True, timeout=60)
        ran = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        shown = [line[2:] for line in (r.stdout + r.stderr).splitlines() if line.startswith("$ ")]
        replay = pathlib.Path(tmp, "replay")
        renv = {**env, "CALLS": str(replay), "STATE": str(pathlib.Path(tmp, "state2"))}
        pathlib.Path(tmp, "state2").write_text("{}")
        for line in shown:
            subprocess.run(["bash", "-c", line], env=renv, capture_output=True, text=True, timeout=60)
        replayed = [json.loads(line) for line in replay.read_text().splitlines()] if replay.exists() else []
        peer_cfg = (home / ".kube/peer")
        mode_bits = oct(peer_cfg.stat().st_mode & 0o777) if peer_cfg.exists() else ""
        return r, ran, [json.dumps(c) for c in replayed] + [f"peer-mode {mode_bits}"]


def touched(ran: list[dict], cluster: str) -> dict[str, list[list[str]]]:
    """What the run did to one cluster, by guardrail."""
    out: dict[str, list[list[str]]] = {g: [] for g in FOUR}
    for c in ran:
        if c["cluster"] != cluster:
            continue
        a = " ".join(c["args"])
        g = ("rbac" if "-role.yaml" in a else "kubearmor" if "kubearmor" in a else "egress" if "network-policy" in a
             else "kyverno" if "validatingpolicy" in a else None)
        if g:
            out[g].append(c["args"])
    return out


for st in ("on", "off"):
    r, ran, extra = run(f"guardrails-{st}")
    out = r.stdout + r.stderr
    check(f"guardrails-{st}: exits 0 and says both clusters switched",
          r.returncode == 0 and f"watch-it-burn-community: all four Kubernetes guardrails are {st}." in r.stdout, out)
    here, there = touched(ran, "this"), touched(ran, "watch-it-burn-community")
    check(f"guardrails-{st}: switches each of the four on this cluster and on the other one",
          all(here[g] for g in FOUR) and all(there[g] for g in FOUR), json.dumps({"here": here, "there": there})[:400])
    check(f"guardrails-{st}: does the same to both clusters", here == there)
    order = [g for c in ran for g in FOUR if touched([c], c["cluster"])[g]]
    firsts = [g for i, g in enumerate(order) if g not in order[:i]]
    check(f"guardrails-{st}: one guardrail at a time across both clusters, RBAC, Kyverno, KubeArmor, egress",
          firsts == list(FOUR), str(firsts))
    shown_calls = extra[:-1]
    check(f"guardrails-{st}: every line it prints, run by bash, makes the call it made, in order",
          shown_calls == [json.dumps(c) for c in ran] and len(ran) > 8,
          f"\n    shown: {shown_calls[:3]}\n    ran:   {[json.dumps(c) for c in ran][:3]}")
    check(f"guardrails-{st}: the other cluster's kubeconfig is written for the student alone", extra[-1] == "peer-mode 0o600",
          extra[-1])
    lines = [line for line in r.stdout.splitlines() if not line.startswith("$ ")]
    check(f"guardrails-{st}: says what each guardrail now does, one line each, no challenge number",
          len(lines) == 5 and not re.search(r"Challenge [0-9]|\(C[0-9]\)", r.stdout) and "—" not in r.stdout, str(lines))
    want = "Deny" if st == "on" else "Audit"
    pats = [c for c in ran if "patch" in c["args"]]
    check(f"guardrails-{st}: sets restrict-image-registries and deny-external-registries to [{want}] on both",
          sorted((c["cluster"], c["args"][c["args"].index("validatingpolicy") + 1]) for c in pats)
          == sorted((cl, p) for cl in ("this", "watch-it-burn-community")
                    for p in ("restrict-image-registries", "deny-external-registries"))
          and all(f'"value":["{want}"]' in c["args"][-1] for c in pats))
    files = {"on": ("c5-scoped-role.yaml", "c3-kubearmor-policy.yaml", "c1-network-policy.yaml"),
             "off": ("c8-broad-role.yaml", "c3-kubearmor-policy.yaml", "c1-network-policy.yaml")}[st]
    verbs = {"on": ("apply", "apply", "apply"), "off": ("apply", "delete", "delete")}[st]
    for f, v in zip(files, verbs):
        check(f"guardrails-{st}: {v}s ~/challenges/{f} on both clusters",
              sum(1 for c in ran if c["args"][0] == v and c["args"][-1].endswith(f"/challenges/{f}")) == 2)
    # Each call on the other cluster, as the RBAC request it makes, inside the guardrails-switch grant.
    need = set()
    for c in ran:
        if c["cluster"] == "this":
            continue
        a = c["args"]
        if a[0] == "patch" or (a[0] == "get" and "validatingpolicy" in a):
            need.add(("", "validatingpolicies", a[2], "patch" if a[0] == "patch" else "get"))
        elif a[0] in ("apply", "delete"):
            for d in yaml.safe_load_all(FIXES[a[-1].rsplit("/", 1)[1]]):
                if not d:
                    continue
                res = {"Role": "roles", "KubeArmorPolicy": "kubearmorpolicies", "NetworkPolicy": "networkpolicies"}[d["kind"]]
                name = d["metadata"]["name"] if res == "roles" else "*"
                for verb in (("get", "patch", "create") if a[0] == "apply" else ("delete",)):
                    if res == "roles" and verb == "create":
                        continue  # the Role exists from git; apply patches it
                    need.add(("agent", res, name, verb))
                if res == "roles":
                    need.add(("agent", res, name, "escalate"))
    missing = sorted(n for n in need if n[3] not in GRANT.get(n[:3], set()))
    check(f"guardrails-{st}: everything it asks of the other cluster is inside the guardrails-switch grant",
          not missing and bool(need), str(missing))

r, ran, _ = run("guardrails-on", mode="unlinked")
check("unlinked: guardrails-on still arms this cluster, then fails, saying how to link it",
      r.returncode == 1 and all(touched(ran, "this")[g] for g in FOUR)
      and "not linked to the other KubeCon cluster" in r.stdout and "fleet.sh guardrails-link" in r.stdout, r.stdout)
check("unlinked: and touches no other cluster", {c["cluster"] for c in ran} == {"this"})
r, ran, _ = run("guardrails-on", mode="peer-down")
check("the other cluster unreachable: guardrails-on fails and names each guardrail it missed there",
      r.returncode == 1 and all(f"{g} on watch-it-burn-community" in r.stdout for g in FOUR), r.stdout)
r, ran, _ = run("guardrails-on", mode="peer-kyverno-stuck")
check("a Kyverno flip that does not hold on the other cluster fails, naming it",
      r.returncode == 1 and "kyverno on watch-it-burn-community" in r.stdout
      and "rbac on watch-it-burn-community" not in r.stdout, r.stdout)
r, ran, _ = run("guardrails-on", args=("soon",))
check("guardrails-on refuses a pause that is not a number of seconds, and touches nothing",
      r.returncode == 2 and "Usage: guardrails-on" in r.stdout and not ran, r.stdout)
r, ran, _ = run("guardrails-on", args=("0",))
check("guardrails-on 0 is the default, no pause", r.returncode == 0)
check("guards-status names the switch", "guardrails-on / guardrails-off" in helpers.get("guards-status", ""))
check("the C7 control still finds agentgateway's rule on the KubeCon private cluster",
      '[ "$r" = admin ] || [ "$r" = kubecon-private ]' in helpers[".guardlib"])

print("== fleet.sh guardrails-link, against fake aws and kubectl ==")
FAKE_AWS = r'''#!/usr/bin/env bash
# aws eks update-kubeconfig --kubeconfig <f> --name <n> --region <r>
args=("$@"); out=""; name=""
for ((i=0; i<${#args[@]}; i++)); do
  [[ "${args[$i]}" == --kubeconfig ]] && out="${args[$((i+1))]}"
  [[ "${args[$i]}" == --name ]] && name="${args[$((i+1))]}"
done
cat > "$out" <<EOF
apiVersion: v1
kind: Config
clusters:
- name: arn:aws:eks:us-west-2:111122223333:cluster/${name}
  cluster: {server: "https://${name}.eks.example", certificate-authority-data: "Q0EtJHtuYW1lfQ=="}
contexts:
- name: arn:aws:eks:us-west-2:111122223333:cluster/${name}
  context: {cluster: "arn:aws:eks:us-west-2:111122223333:cluster/${name}", user: u}
current-context: arn:aws:eks:us-west-2:111122223333:cluster/${name}
users:
- name: u
  user: {token: x}
EOF
'''
FAKE_KUBECTL_LINK = r'''#!/usr/bin/env python3
import base64, json, os, re, sys, yaml
a = sys.argv[1:]
cfg = yaml.safe_load(open(os.environ["KUBECONFIG"]))
ctx = a[a.index("--context") + 1] if "--context" in a else cfg.get("current-context", "")
cl = {c["name"]: c["cluster"] for c in cfg.get("clusters", [])}
ct = {c["name"]: c["context"] for c in cfg.get("contexts", [])}
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps({"ctx": ctx, "args": a}) + "\n")
if a[:2] == ["config", "current-context"]:
    print(cfg["current-context"]); sys.exit(0)
if a[:2] == ["config", "view"]:
    c = cl[ct[ctx]["cluster"]]
    print(c["server"] if "server" in a[-1] else c["certificate-authority-data"], end=""); sys.exit(0)
name = ctx.rsplit("/", 1)[-1]
if "get" in a and "guardrails-switch-token" in a:
    print(base64.b64encode(f"token-of-{name}".encode()).decode(), end=""); sys.exit(0)
if a[:3] == ["auth", "can-i", "patch"] or ("auth" in a and "can-i" in a):
    user = {u["name"]: u["user"] for u in cfg["users"]}[ct[ctx]["user"]]
    ok = user.get("token", "").startswith("token-of-") and os.environ.get("CANI", "yes") == "yes"
    print("yes" if ok else "no"); sys.exit(0 if ok else 1)
if "create" in a and "secret" in a:
    kc = open(next(x[len("--from-file=kubeconfig="):] for x in a if x.startswith("--from-file=kubeconfig="))).read()
    peer = next(x[len("--from-literal=name="):] for x in a if x.startswith("--from-literal=name="))
    print(yaml.safe_dump({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "guardrails-peer",
          "namespace": "guardrails-switch"}, "data": {"kubeconfig": base64.b64encode(kc.encode()).decode(),
          "name": base64.b64encode(peer.encode()).decode()}})); sys.exit(0)
if "apply" in a:
    doc = yaml.safe_load(sys.stdin.read())
    store = os.environ["STORE"]
    with open(os.path.join(store, name), "w") as f:
        json.dump(doc, f)
    sys.exit(0)
sys.exit(1)
'''
with tempfile.TemporaryDirectory() as tmp:
    fakebin = pathlib.Path(tmp, "bin"); fakebin.mkdir()  # noqa: E702
    store = pathlib.Path(tmp, "store"); store.mkdir()  # noqa: E702
    (fakebin / "aws").write_text(FAKE_AWS); (fakebin / "aws").chmod(0o755)  # noqa: E702
    (fakebin / "kubectl").write_text(FAKE_KUBECTL_LINK); (fakebin / "kubectl").chmod(0o755)  # noqa: E702
    calls = pathlib.Path(tmp, "calls")

    def link(cani: str = "yes", *names: str) -> subprocess.CompletedProcess:
        env = {"PATH": f"{fakebin}:{os.environ['PATH']}", "CALLS": str(calls), "STORE": str(store), "CANI": cani,
               "WIB_LINK_TOKEN_WAIT": "0", "WIB_LINK_TOKEN_TRIES": "1", "KUBECONFIG": "/nonexistent-shared-config"}
        return fleet("cmd_guardrails_link " + " ".join(names), env)

    r = link()
    written = {p.name: json.load(open(p)) for p in store.iterdir()}
    check("guardrails-link links both ways and says so", r.returncode == 0 and "linked;" in (r.stdout + r.stderr),
          r.stdout + r.stderr)
    check("each cluster gets a guardrails-switch/guardrails-peer Secret",
          sorted(written) == ["watch-it-burn-community", "watch-it-burn-private"]
          and all(d["metadata"] == {"name": "guardrails-peer", "namespace": "guardrails-switch"} for d in written.values()))
    for here, there in (("watch-it-burn-community", "watch-it-burn-private"),
                        ("watch-it-burn-private", "watch-it-burn-community")):
        d = written.get(here, {}).get("data", {})
        kc = yaml.safe_load(base64.b64decode(d.get("kubeconfig", "")).decode() or "{}") or {}
        check(f"{here}'s peer is {there}: its endpoint, its CA and its guardrails-switch token, in namespace agent",
              base64.b64decode(d.get("name", "")).decode() == there
              and kc.get("clusters", [{}])[0].get("cluster", {}).get("server") == f"https://{there}.eks.example"
              and kc["users"][0]["user"] == {"token": f"token-of-{there}"}
              and kc["current-context"] == there and kc["contexts"][0]["context"]["namespace"] == "agent", str(kc)[:300])
    every = [json.loads(line) for line in calls.read_text().splitlines()]
    check("every kubectl call names its context, or reads its own isolated kubeconfig",
          all("--context" in c["args"] or c["args"][:2] == ["config", "current-context"] for c in every),
          str([c for c in every if "--context" not in c["args"]][:2]))
    for p in store.iterdir():
        p.unlink()
    r = link("no")
    check("a token that cannot patch restrict-image-registries is never written, and the link fails",
          r.returncode != 0 and not list(store.iterdir()) and "NOT linked" in (r.stdout + r.stderr), r.stdout + r.stderr)
    r = link("yes", "watch-it-burn-community", "watch-it-burn-community")
    check("guardrails-link refuses one cluster linked to itself", r.returncode == 2)

print("== the internal registry: read-only through the console, pinned, the console's alone in-cluster ==")
reg = docs(REGISTRY)
dep = next(d for d in reg if d["kind"] == "Deployment")
images = [c["image"] for c in dep["spec"]["template"]["spec"]["containers"]]
check("Distribution and the seed tool, each from its own ghcr.io publication, pinned by digest",
      [i.split(":", 1)[0] for i in images] == ["ghcr.io/distribution/distribution", "ghcr.io/regclient/regctl"]
      and all("@sha256:" in i for i in images), str(images))
lock = (REPO / "images.lock").read_text(encoding="utf-8")
seed = next(d for d in reg if d["kind"] == "ConfigMap")["data"]["images.txt"]
rows = [line.split() for line in seed.splitlines() if line.strip() and not line.startswith("#")]
check("every seed row copies an image images.lock pins, by digest, to a burritobot/ path",
      rows and all(len(r) == 2 and "@sha256:" in r[0] and r[0] in lock and r[1].startswith("burritobot/") for r in rows))
check("Challenge 3's image is seeded at the path #775 names",
      any(r[1].startswith("burritobot/maintenance-shell:") for r in rows))
reg_env = {e["name"]: e.get("value") for e in dep["spec"]["template"]["spec"]["containers"][0].get("env", [])}
check("the registry's Location headers are relative, so the seed's in-pod push stays on localhost "
      "(a public REGISTRY_HTTP_HOST sent its PATCH out to the read-only public name, which answered 405)",
      reg_env.get("REGISTRY_HTTP_RELATIVEURLS") == "true" and "REGISTRY_HTTP_HOST" not in reg_env, str(reg_env))
# The relative Locations only keep the seed on localhost while the seed itself pushes there (#906, #919).
seed_sh = next(d for d in reg if d["kind"] == "ConfigMap")["data"]["seed.sh"]
check("the seed copies to localhost:5000, never to the public name",
      "localhost:5000/${dst}" in seed_sh and "registry.burritobot.co" not in seed_sh)
# A ConfigMap change restarts no pod, so the pod template carries the seed's checksum and a new pin rolls it (#775).
seed_sum = hashlib.sha256((seed + seed_sh).encode("utf-8")).hexdigest()
pod_notes = dep["spec"]["template"]["metadata"].get("annotations") or {}
check("the pod template's burritobot.co/seed-checksum is the sha256 of images.txt then seed.sh, so a new pin rolls "
      "the pod (set it to the value shown when this fails)",
      pod_notes.get("burritobot.co/seed-checksum") == seed_sum,
      f"has {pod_notes.get('burritobot.co/seed-checksum')!r}, want {seed_sum!r}")
np = next(d for d in reg if d["kind"] == "NetworkPolicy")
check("in-cluster, only the console reaches the registry",
      np["spec"]["ingress"] == [{"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "agent"}},
                                           "podSelector": {"matchLabels": {"app.kubernetes.io/name": "console"}}}],
                                 "ports": [{"protocol": "TCP", "port": 5000}]}])
conf = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")
srv = conf.split("server_name ~^registry(-[a-z0-9-]+)?\\.(?:agenticburn\\.com|burritobot\\.co)$;", 1)
check("the console serves registry-<cluster> and the bare registry name on both domains", len(srv) == 2)
body = srv[1].split("\n}\n", 1)[0] if len(srv) == 2 else ""
check("read-only: GET (and HEAD) alone reach the registry", "limit_except GET { deny all; }" in body)
check("it proxies to the registry Service, resolved per request",
      "set $wib_registry http://registry.registry.svc.cluster.local:5000;" in body and "proxy_pass $wib_registry;" in body)
check("fleet.sh publishes registry-<cluster> on the cluster holding the shared admin host alone (#931)",
      'readonly WIB_REGISTRY_HOSTS="registry"' in src
      and 'if [[ "${host}" == "${SHARED_ADMIN_HOST:-}" ]]; then svcs+=" ${WIB_REGISTRY_HOSTS}"; fi' in src)
hosts = fleet("emit_service_hosts burritobot-private.agenticburn.com lb.example").stdout
check("burritobot-private's rows include registry-burritobot-private",
      "registry-burritobot-private.agenticburn.com  lb.example:443" in hosts, hosts)
community_hosts = fleet("emit_service_hosts attackme.agenticburn.com lb.example").stdout
check("attackme's rows carry no registry-attackme, which has no registry behind it and answered 502 (#931)",
      "support-attackme.agenticburn.com  lb.example:443" in community_hosts
      and not any(r.startswith("registry") for r in community_hosts.splitlines()), community_hosts)
bare = [fleet(f"bare_rows {h} lb.example").stdout for h in ("burritobot-private.agenticburn.com", "attackme.agenticburn.com")]
check("the bare registry.burritobot.co row rides the private cluster's LB alone, the name both clusters' nodes pull by",
      bare == ["registry.burritobot.co  lb.example:443\n", ""], str(bare))
check("routes writes it beside each roster cluster's rows, so a promoted standby takes it with them",
      'bare_rows "$(public_host_for "${name}")" "${h}" >> "${tmp}"' in src)

print()
print("== offline means offline ==")
_calls = no_cloud.calls()
check("no check above called aws, kubectl, eksctl, terraform or helm", not _calls)
if _calls:
    print("".join(f"        {line}\n" for line in _calls.splitlines()), end="")

if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All guardrails switch checks passed.")
