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
check("target runs on an ALLOWED registry (docker.io/library) so it is not itself blocked",
      all(i.startswith("docker.io/library/") or i.startswith("python:") or i=="python:3.12-slim" for i in imgs))
check("customer-stream ArgoCD app targets apps", app["spec"]["destination"]["namespace"] == "apps")
check("exfil target present on Cluster 1 (in the burn include)", "customer-stream" in burn)
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll customer-stream (attack-1 target) checks passed.")
