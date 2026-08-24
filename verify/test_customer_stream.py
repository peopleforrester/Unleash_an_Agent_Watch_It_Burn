# ABOUTME: Render-gate check for the Beat-1 exfil target: a fake-customer-data stream (generator->consumer)
# ABOUTME: in apps, emitting obviously-FAKE records, on an allowed registry (so the target itself runs).
import pathlib, sys, yaml
REPO = pathlib.Path(__file__).resolve().parents[1]
docs = [d for d in yaml.safe_load_all((REPO/"gitops/manifests/customer-stream/stream.yaml").read_text()) if d]
deps = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "Deployment"}
cm = next(d for d in docs if d.get("kind") == "ConfigMap")
gen = cm["data"]["generator.py"]
burn = (REPO/"gitops/bootstrap/app-of-apps-burn.yaml").read_text()
app = yaml.safe_load((REPO/"gitops/apps/customer-stream.yaml").read_text())
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

check("generator + consumer deployments exist", "customer-generator" in deps and "customer-consumer" in deps)
check("both deploy to the apps namespace", all(d["metadata"]["namespace"]=="apps" for d in deps.values()))
check("records are obviously FAKE (no real PII)", "FAKE-CUSTOMER" in gen and "FAKE-SSN-sentinel" in gen and "example.invalid" in gen)
imgs = [d["spec"]["template"]["spec"]["containers"][0]["image"] for d in deps.values()]
# The images were mirrored to GHCR, so hardcoding docker.io/library here asserted a registry the repo
# had deliberately stopped using. Read the allow-list from the policy itself: the invariant is that the
# exfil TARGET is not blocked by the same rule that blocks the villain, whatever the allow-list says
# today. A hardcoded registry silently stops testing that the moment the mirror changes.
import fnmatch
_pol = yaml.safe_load((REPO/"policies/kyverno/restrict-image-registries.yaml").read_text())
_allow = _pol["spec"]["rules"][0]["validate"]["pattern"]["spec"]["containers"][0]["image"]
_globs = [g.strip() for g in _allow.split("|")]
def _permitted(i):
    return any(fnmatch.fnmatch(i, g) for g in _globs)
_blocked = [i for i in imgs if not _permitted(i)]
check(f"target runs on a registry the policy ALLOWS so it is not itself blocked ({len(_blocked)} blocked)",
      not _blocked)
check("customer-stream ArgoCD app targets apps", app["spec"]["destination"]["namespace"] == "apps")
check("exfil target present on Cluster 1 (in the burn include)", "customer-stream" in burn)
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll customer-stream (attack-1 target) checks passed.")
