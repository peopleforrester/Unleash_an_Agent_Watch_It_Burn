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

check("registry policy is Enforce", pol["spec"].get("validationFailureAction") == "Enforce")
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
