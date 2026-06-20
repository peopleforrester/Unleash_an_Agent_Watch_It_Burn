# ABOUTME: Render-gate check for the Istio service mesh: ambient apps pinned to 1.30.1 + STRICT mTLS
# ABOUTME: (whose certs are SPIFFE identities). Structural, no cluster needed.
import pathlib, sys, yaml
REPO = pathlib.Path(__file__).resolve().parents[1]
apps = [d for d in yaml.safe_load_all((REPO/"gitops/apps/istio.yaml").read_text()) if d]
pa = [d for d in yaml.safe_load_all((REPO/"security/istio/peer-authentication.yaml").read_text()) if d]
byname = {a["metadata"]["name"]: a for a in apps}
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None
for n in ("istio-base", "istio-cni", "istiod", "ztunnel", "istio-mesh-config"):
    check(f"app present: {n}", n in byname)
helm_apps = [a for a in apps if a["spec"]["source"].get("chart")]
check("all istio charts pinned to 1.30.1", all(a["spec"]["source"]["targetRevision"] == "1.30.1" for a in helm_apps))
check("cni + istiod use ambient profile",
      byname["istio-cni"]["spec"]["source"]["helm"]["valuesObject"].get("profile") == "ambient"
      and byname["istiod"]["spec"]["source"]["helm"]["valuesObject"].get("profile") == "ambient")
strict = {d["metadata"]["namespace"]: d for d in pa if d.get("kind") == "PeerAuthentication"}
check("STRICT mTLS in agent + apps namespaces",
      strict.get("agent", {}).get("spec", {}).get("mtls", {}).get("mode") == "STRICT"
      and strict.get("apps", {}).get("spec", {}).get("mtls", {}).get("mode") == "STRICT")
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll mesh checks passed.")
