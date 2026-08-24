# ABOUTME: Render-gate check for attack-2 (villain app): the registry allowlist (Enforce, apps) permits
# ABOUTME: only trusted registries, and the villain image lives on a public user namespace it refuses.
import pathlib, sys, yaml
REPO = pathlib.Path(__file__).resolve().parents[1]
pol = yaml.safe_load((REPO/"policies/kyverno/restrict-image-registries.yaml").read_text())
docs = list(yaml.safe_load_all((REPO/"games/villain-apps/deploy-villain.yaml").read_text()))
dep = next(d for d in docs if d and d.get("kind")=="Deployment")
img = dep["spec"]["template"]["spec"]["containers"][0]["image"]
rule = pol["spec"]["rules"][0]
allow = rule["validate"]["pattern"]["spec"]["containers"][0]["image"]
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

# Kyverno 1.18 rule-level validate.failureAction (spec.validationFailureAction is deprecated)
# Audit is CORRECT by default, not a regression. Round 1 has to actually deploy the villain image
# (that is the "watch it burn" beat); Round 2/3 flip this to Enforce live via toggle-kyverno-enforce.sh,
# with an ArgoCD ignoreDifferences on failureAction so the flip is not self-healed away. Install first,
# enforce last: a guardrail set to Enforce before the thing it guards exists rejects that thing's own
# pods. The real invariant is that the policy ships as Audit AND the live flip exists.
check("registry policy ships as Audit so Round 1 can burn",
      rule["validate"].get("failureAction") == "Audit")
_toggle = REPO / "challenges/01-cncf-wall/toggle-kyverno-enforce.sh"
check("a live toggle to Enforce exists for Round 2/3",
      _toggle.exists() and "Enforce" in _toggle.read_text())
check("registry policy scoped to apps namespace", "apps" in rule["match"]["any"][0]["resources"]["namespaces"])
check("allowlist permits docker.io/library only (not arbitrary docker.io users)",
      "docker.io/library/*" in allow and "docker.io/*" not in allow)
check("villain image is on a public docker.io user namespace (not library)",
      img.startswith("docker.io/") and not img.startswith("docker.io/library/"))
check("villain image is NOT in the allowlist -> C2 refuses it",
      not any(img.startswith(p.strip().rstrip("*")) for p in allow.split("|")))
check("villain deploys to the apps namespace", dep["metadata"]["namespace"] == "apps")
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll villain-app (attack-2) checks passed.")
