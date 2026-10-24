# ABOUTME: Fails when guard-proxy's C2 badge (/controls infra.kyverno) reads a different object than the one
# ABOUTME: the workshop deploys and the guard-proxy-reader ClusterRole grants, or misreads its Deny action.
#
# Why (#487). The policy moved to a policies.kyverno.io ValidatingPolicy (#206) while proxy.py kept GETting
# the retired kyverno.io ClusterPolicy and testing failureAction == Enforce. That read 404s, so C2 was dark
# on every cluster, even with admission denying the villain image. This pins the read to the deployed
# policy's group, version and name, to the RBAC grant, and to the value the Beat-1 toggle writes.
import importlib.util
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard_proxy_c2", REPO / "gitops" / "ai-layer" / "guard-proxy" / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)

POLICY = REPO / "policies" / "kyverno" / "restrict-image-registries.yaml"
RES = REPO / "gitops" / "ai-layer" / "resources.yaml"
TOGGLE = REPO / "challenges" / "01-cncf-wall" / "toggle-kyverno-enforce.sh"

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def controls(objects):
    """read_controls() against a fake API that serves `objects` by path and 404s (None) on the rest."""
    reads = []

    def fake_get(path):
        reads.append(path)
        return objects.get(path)

    proxy._k8s_get = fake_get
    proxy._controls_cache["val"] = None
    return proxy.read_controls(), reads


pol = yaml.safe_load(POLICY.read_text())
group, version = pol["apiVersion"].split("/")
name = pol["metadata"]["name"]
want_path = f"/apis/{group}/{version}/validatingpolicies/{name}"
check(f"the deployed policy is a ValidatingPolicy ({pol['apiVersion']} {pol['kind']})",
      pol["kind"] == "ValidatingPolicy")

# The path proxy.py reads for C2 is the deployed object's group, version and name.
_, reads = controls({})
kyverno_reads = [p for p in reads if "kyverno" in p]
check(f"C2 reads exactly {want_path} (got {kyverno_reads})", kyverno_reads == [want_path])

# guard-proxy-reader may get that object: same group, plural and name, verb get.
docs = [d for d in yaml.safe_load_all(RES.read_text()) if d]
roles = [d for d in docs if d.get("kind") == "ClusterRole" and d["metadata"]["name"] == "guard-proxy-reader"]
check("guard-proxy-reader ClusterRole is present", len(roles) == 1)
granted = any(group in r.get("apiGroups", []) and "validatingpolicies" in r.get("resources", [])
              and name in r.get("resourceNames", []) and "get" in r.get("verbs", [])
              for role in roles for r in role.get("rules", []))
check(f"guard-proxy-reader grants get on {group} validatingpolicies/{name}", granted)

# The armed value is the one the Beat-1 toggle (and fleet.sh arm_infra_guardrails through it) writes.
toggle = TOGGLE.read_text()
m = re.search(r'^ACTION="(\w+)"', toggle, re.M)
armed = m.group(1) if m else None
check(f"the toggle arms with validationActions [{armed}], the value C2 tests", armed == "Deny")
check("the toggle replaces /spec/validationActions", "/spec/validationActions" in toggle)


def vp(actions):
    return {want_path: {"apiVersion": pol["apiVersion"], "kind": "ValidatingPolicy",
                        "metadata": {"name": name}, "spec": {"validationActions": actions}}}


cases = [
    ("the shipped policy (Audit) is not armed", vp(pol["spec"]["validationActions"]), False),
    ("validationActions [Deny] lights C2", vp(["Deny"]), True),
    ("validationActions [Audit] does not", vp(["Audit"]), False),
    ("validationActions [Deny, Audit] lights C2", vp(["Deny", "Audit"]), True),
    ("validationActions [Warn] does not", vp(["Warn"]), False),
    ("a policy with no validationActions does not", {want_path: {"spec": {}}}, False),
    ("a string, not a list, does not", vp("DenyAudit"), False),
    ("an absent policy (404) does not", {}, False),
]
check("the shipped policy starts in Audit", pol["spec"]["validationActions"] == ["Audit"])
for label, objects, want in cases:
    got, _ = controls(objects)
    check(f"{label} (kyverno={got['kyverno']})", got["kyverno"] is want)

# The retired ClusterPolicy, even Enforcing, is not what the cluster runs and must not light the badge.
retired = {"/apis/kyverno.io/v1/clusterpolicies/restrict-image-registries":
           {"spec": {"rules": [{"validate": {"failureAction": "Enforce"}}]}}}
got, _ = controls(retired)
check("an Enforcing kyverno.io ClusterPolicy alone does not light C2", got["kyverno"] is False)

print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'C2 reads the deployed ValidatingPolicy.'}")
sys.exit(1 if failures else 0)
