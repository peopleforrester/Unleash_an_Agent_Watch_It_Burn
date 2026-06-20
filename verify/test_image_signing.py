# ABOUTME: Render-gate check for the Harbor/cosign upgrade: Harbor is allowlisted, and Harbor images
# ABOUTME: (only) must be cosign-signed (Enforce), so public demo images still run.
import pathlib, sys, yaml
REPO = pathlib.Path(__file__).resolve().parents[1]
allow = yaml.safe_load((REPO/"policies/kyverno/restrict-image-registries.yaml").read_text())
verify = yaml.safe_load((REPO/"policies/kyverno/verify-image-signatures.yaml").read_text())
allow_pat = allow["spec"]["rules"][0]["validate"]["pattern"]["spec"]["containers"][0]["image"]
vi = verify["spec"]["rules"][0]["verifyImages"][0]
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

check("registry allowlist now permits Harbor", "harbor.agenticburn.com/*" in allow_pat)
check("allowlist still permits the public demo registries (docker.io/library)", "docker.io/library/*" in allow_pat)
check("verifyImages is Enforce", vi.get("failureAction") == "Enforce")
check("verifyImages is scoped to Harbor only (public images unaffected)",
      vi["imageReferences"] == ["harbor.agenticburn.com/*"])
check("verifyImages has a keyless attestor", "keyless" in str(vi.get("attestors", "")))
check("sign-and-push uses cosign", "cosign sign" in (REPO/"infra/harbor/sign-and-push.sh").read_text())
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll image-signing (Harbor/cosign) checks passed.")
