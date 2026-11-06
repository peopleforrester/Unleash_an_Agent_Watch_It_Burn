# ABOUTME: Render-gate check for the Istio service mesh: all ambient charts on ONE pinned version + the agent
# ABOUTME: namespace's mTLS mode (the certs are SPIFFE identities). Structural, no cluster needed.
import pathlib, sys, yaml
REPO = pathlib.Path(__file__).resolve().parents[1]
apps = [d for d in yaml.safe_load_all((REPO/"gitops/bootstrap/apps/istio.yaml").read_text()) if d]
pa = [d for d in yaml.safe_load_all((REPO/"security/istio/peer-authentication.yaml").read_text()) if d]
byname = {a["metadata"]["name"]: a for a in apps}
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None
for n in ("istio-base", "istio-cni", "istiod", "ztunnel", "istio-mesh-config"):
    check(f"app present: {n}", n in byname)
helm_apps = [a for a in apps if a["spec"]["source"].get("chart")]
# The version lives here as a single constant rather than four literals. Bumping istio means editing
# this line and gitops/bootstrap/apps/istio.yaml, and the check below catches the case that actually breaks a
# mesh: base, cni, istiod and ztunnel drifting apart from each other.
ISTIO_VERSION = "1.30.4"
_revs = {a["spec"]["source"]["targetRevision"] for a in helm_apps}
check(f"all istio charts pinned to {ISTIO_VERSION}", _revs == {ISTIO_VERSION})
check("no istio chart has drifted from the others", len(_revs) == 1)
check("cni + istiod use ambient profile",
      byname["istio-cni"]["spec"]["source"]["helm"]["valuesObject"].get("profile") == "ambient"
      and byname["istiod"]["spec"]["source"]["helm"]["valuesObject"].get("profile") == "ambient")
# PERMISSIVE in agent, where the console, guard-proxy (#471) and the weather feed (#980) are enrolled: mutual TLS
# between the first two, and the NLB and unenrolled callers still get in. No policy for a namespace with nothing enrolled (verify/test_mesh_enrollment.py).
modes = {d["metadata"]["namespace"]: d.get("spec", {}).get("mtls", {}).get("mode")
         for d in pa if d.get("kind") == "PeerAuthentication"}
check("PERMISSIVE mTLS in agent, and no policy elsewhere", modes == {"agent": "PERMISSIVE"})
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll mesh checks passed.")
