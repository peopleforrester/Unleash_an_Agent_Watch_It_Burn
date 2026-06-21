# ABOUTME: Render-gate check for attack-1 (exfil) control: the apps egress allowlist permits DNS + in-VPC
# ABOUTME: only, and NO network policy opens internet egress (0.0.0.0/0) -> the S3 PutObject has no path.
import pathlib, sys, yaml
REPO = pathlib.Path(__file__).resolve().parents[1]
NETPOL = REPO / "policies" / "network-policies"
allowlist = yaml.safe_load((NETPOL / "per-namespace" / "apps-egress-allowlist.yaml").read_text())
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

check("egress allowlist is a NetworkPolicy with Egress policyType",
      allowlist["kind"] == "NetworkPolicy" and "Egress" in allowlist["spec"]["policyTypes"])
ports = [p["port"] for rule in allowlist["spec"]["egress"] for p in rule.get("ports", [])]
check("DNS egress (port 53) allowed", 53 in ports)
cidrs = [t["ipBlock"]["cidr"] for rule in allowlist["spec"]["egress"] for t in rule.get("to", []) if "ipBlock" in t]
check("egress restricted to an in-VPC CIDR (not the internet)", cidrs and all(c != "0.0.0.0/0" for c in cidrs))

# Invariant across ALL network policies: nothing opens internet egress (that is what blocks the S3 exfil).
internet = []
for f in NETPOL.rglob("*.yaml"):
    for doc in yaml.safe_load_all(f.read_text()):
        if not doc or doc.get("kind") != "NetworkPolicy":
            continue
        for rule in doc.get("spec", {}).get("egress", []) or []:
            for t in rule.get("to", []) or []:
                if t.get("ipBlock", {}).get("cidr") == "0.0.0.0/0":
                    internet.append(f.name)
check("no NetworkPolicy opens internet egress (0.0.0.0/0) -> S3 path denied", not internet)

# The NetworkPolicies are inert unless the VPC-CNI addon enforces them. The live gate run on
# watch-it-burn-test found S3 reachable because enableNetworkPolicy was unset on the addon.
for rel in ["infra/test-cluster/cluster.yaml", "infra/attendee-cluster/cluster.yaml", "infra/burn-clusters/cluster.yaml"]:
    cfg = yaml.safe_load((REPO / rel).read_text())
    vpccni = next((a for a in cfg.get("addons", []) if a.get("name") == "vpc-cni"), {})
    cv = str(vpccni.get("configurationValues", ""))
    check(f"{rel}: vpc-cni addon enables NetworkPolicy enforcement",
          "enableNetworkPolicy" in cv and "true" in cv)

if failures: print(f"\nFAILED: {len(failures)}: {internet}"); sys.exit(1)
print("\nAll egress-control checks passed.")
