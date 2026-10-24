# ABOUTME: Render-gate check for attack-2 (villain app): the registry allowlist (apps + agent) permits
# ABOUTME: only trusted registries, and the villain image lives on a public user namespace it refuses.
import pathlib, sys, yaml
from registry_allowlist import allowed, prefixes
REPO = pathlib.Path(__file__).resolve().parents[1]
pol = yaml.safe_load((REPO/"policies/kyverno/restrict-image-registries.yaml").read_text())
docs = list(yaml.safe_load_all((REPO/"games/villain-apps/deploy-villain.yaml").read_text()))
dep = next(d for d in docs if d and d.get("kind")=="Deployment")
img = dep["spec"]["template"]["spec"]["containers"][0]["image"]
spec = pol["spec"]
# The allow-list is a CEL list of registry prefixes; ECR is a separate host-anchored regex (#206).
allow = prefixes()
ns_values = [v for e in spec["matchConstraints"].get("namespaceSelector", {}).get("matchExpressions", [])
             if e.get("key") == "kubernetes.io/metadata.name" and e.get("operator") == "In" for v in e["values"]]
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

check("it is a Kyverno CEL ValidatingPolicy, not the deprecated ClusterPolicy (#206)",
      pol["apiVersion"] == "policies.kyverno.io/v1" and pol["kind"] == "ValidatingPolicy")
# Audit is CORRECT by default, not a regression. Round 1 has to actually deploy the villain image
# (that is the "watch it burn" beat); Round 2/3 flip this to Deny live via toggle-kyverno-enforce.sh,
# with an ArgoCD ignoreDifferences on /spec/validationActions so the flip is not self-healed away. Install
# first, enforce last: a guardrail set to Deny before the thing it guards exists rejects that thing's own
# pods. The real invariant is that the policy ships as Audit AND the live flip exists.
check("registry policy ships as Audit so Round 1 can burn", spec.get("validationActions") == ["Audit"])
_toggle = REPO / "challenges/01-cncf-wall/toggle-kyverno-enforce.sh"
_tt = _toggle.read_text() if _toggle.exists() else ""
check("a live toggle to Deny exists for Round 2/3",
      "validatingpolicy" in _tt and "/spec/validationActions" in _tt and '"Deny"' in _tt.replace('\\"', '"'))
check("registry policy scoped to apps namespace", "apps" in ns_values)
check("and to agent, where deploy_app lands the villain", "agent" in ns_values)
check("it judges Pods, so autogen extends it to the villain Deployment",
      spec["matchConstraints"]["resourceRules"] == [{"apiGroups": [""], "apiVersions": ["v1"],
                                                     "operations": ["CREATE", "UPDATE"], "resources": ["pods"]}])
check("autogen is not switched off", "autogen" not in spec)
check("allowlist permits docker.io/library only (not arbitrary docker.io users)",
      "docker.io/library/" in allow and "docker.io/" not in allow)
check("villain image is on a public docker.io user namespace (not library)",
      img.startswith("docker.io/") and not img.startswith("docker.io/library/"))
check("villain image is NOT in the allowlist (nor ECR) -> C2 refuses it", not allowed(img))
check("villain deploys to the apps namespace", dep["metadata"]["namespace"] == "apps")
# The run-of-show reads the refusal aloud and the lab quotes it; Kyverno prefixes it with the policy name.
msg = " ".join(spec["validations"][0]["message"].split())
check("the deny message is the one the lab and run-of-show quote",
      msg.startswith("Images must come from allowed registries:"))
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll villain-app (attack-2) checks passed.")
