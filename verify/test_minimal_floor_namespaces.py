# ABOUTME: Render gate for the minimal-floor's namespace lists: every namespace a platform component runs in
# ABOUTME: is protected from deletion, and its workloads too, except agent, where the lab deletes the villain.
#
# Why (#477). The floor's header said it protected ArgoCD, Kyverno, Falco and the agent, but its lists were
# written by hand from what the namespaces were once called. Falco moved to `security` (`falco` holds only
# Talon), BurritoBot runs in `agent`, and Datadog in `datadog`; none of the three was on either list. The
# lists are checked here against where each Application actually deploys, so the next move fails here.
#
# Offline: PyYAML and the repo only. The CEL verdicts themselves are in test_kyverno_cel_policies.py.
import pathlib, re, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
APPS = REPO / "gitops/bootstrap/apps"
FLOOR = REPO / "policies/floor/minimal-floor.yaml"
failures = []

# The platform components the floor exists to keep alive, by the Application that ships each one.
PLATFORM_APPS = ("kyverno", "falco", "falcosidekick", "falco-talon", "kagent", "ai-layer", "prometheus",
                 "datadog-operator", "datadog-agent-cr")
# Workloads in `agent` stay deletable: Challenge 2 has the student clean up the villain Deployment there.
# What Argo CD owns in `agent` is guarded by block-argocd-drift instead.
WORKLOADS_DELETABLE = {"agent"}


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


def app(name):
    return yaml.safe_load((APPS / f"{name}.yaml").read_text())


def dest_ns(name):
    return app(name)["spec"]["destination"]["namespace"]


floor = yaml.safe_load(FLOOR.read_text())
rules = floor["spec"]["matchConstraints"]["resourceRules"]
ns_rule = [r for r in rules if r["resources"] == ["namespaces"]]
check("the floor has one namespace-DELETE rule", len(ns_rule) == 1, f"got {len(ns_rule)}")
protected_ns = set(ns_rule[0].get("resourceNames", [])) if ns_rule else set()

conds = {m["name"]: m["expression"] for m in floor["spec"]["matchConditions"]}
m = re.search(r"request\.namespace in \[(.*?)\]", conds.get("namespace-or-platform-workload", ""), re.S)
check("the workload condition names its namespaces in one list", m is not None)
workload_ns = set(re.findall(r"'([^']+)'", m.group(1))) if m else set()

print("== every platform namespace is protected ==")
for a in PLATFORM_APPS:
    ns = dest_ns(a)
    check(f"{a} runs in {ns}, which cannot be deleted", ns in protected_ns, f"namespace list: {sorted(protected_ns)}")
    if ns in WORKLOADS_DELETABLE:
        check(f"{a}'s namespace {ns} keeps its workloads deletable", ns not in workload_ns)
    else:
        check(f"{a}'s workloads in {ns} cannot be deleted", ns in workload_ns, f"workload list: {sorted(workload_ns)}")
check("argocd itself is protected", "argocd" in protected_ns and "argocd" in workload_ns)
check("every workload-protected namespace is also a protected namespace",
      workload_ns <= protected_ns, f"only in the workload list: {sorted(workload_ns - protected_ns)}")

print("== the reason agent workloads stay deletable still holds ==")
lab = (REPO / "challenges/LAB-TEXT.md").read_text()
check("the lab still has the student delete the villain Deployment in agent",
      "kubectl -n agent delete deploy promo-mascot" in lab)
drift = yaml.safe_load((REPO / "policies/kyverno/block-argocd-drift.yaml").read_text())
check("block-argocd-drift still guards Argo-managed Deployments cluster-wide",
      any("deployments" in r.get("resources", []) and "DELETE" in r.get("operations", [])
          for r in drift["spec"]["matchConstraints"]["resourceRules"]))

print("== the Datadog operator exemption names the operator's real ServiceAccount ==")
op = app("datadog-operator")
values = op["spec"]["source"].get("helm", {}).get("valuesObject", {})
sa_override = values.get("fullnameOverride") or values.get("nameOverride") or (values.get("serviceAccount") or {}).get("name")
check("the operator chart keeps its default ServiceAccount name", not sa_override, f"override: {sa_override!r}")
sa = f"system:serviceaccount:{dest_ns('datadog-operator')}:{op['metadata']['name']}"
pc = {v["name"]: v["expression"] for v in floor["spec"]["variables"]}.get("platformController", "")
check(f"{sa} may replace the workloads it owns", f"'{sa}'" in pc)

print("== the burn cluster has no floor, as the floor's comments say ==")
sys.path.insert(0, str(REPO / "verify"))
from bootstrap_chart import app_names  # noqa: E402
picked = set(app_names("burn"))
for absent in ("minimal-floor", "kyverno"):
    check(f"the burn profile does not list {absent}", absent not in picked)

print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'All minimal-floor namespace checks passed.'}")
sys.exit(1 if failures else 0)
