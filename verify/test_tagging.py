# ABOUTME: Render-gate check for the AWS tagging/naming convention (collision avoidance in the shared
# ABOUTME: accen-dev account). Every cluster name starts with watch-it-burn-; every resource is tagged ours.
import pathlib, sys, yaml
REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

CLUSTERS = [
    "infra/test-cluster/cluster.yaml",
    "infra/hub-cluster/cluster.yaml",
    "infra/burn-clusters/cluster.yaml",
    "infra/spoke-cluster/cluster.yaml",
]
for rel in CLUSTERS:
    cfg = yaml.safe_load((REPO / rel).read_text())
    md = cfg.get("metadata", {})
    name = md.get("name", "")
    tags = md.get("tags", {}) or {}
    check(f"{rel}: cluster name starts with watch-it-burn-", name.startswith("watch-it-burn-"))
    check(f"{rel}: metadata.tags project=watch-it-burn", tags.get("project") == "watch-it-burn")
    # every managed nodegroup carries the project tag too (propagates to EC2/ASG)
    ngs = cfg.get("managedNodeGroups", []) or []
    check(f"{rel}: every nodegroup tagged project=watch-it-burn",
          bool(ngs) and all((ng.get("tags", {}) or {}).get("project") == "watch-it-burn" for ng in ngs))

# No stale tag key or pre-rename cluster names linger in the cluster configs.
joined = "\n".join((REPO / rel).read_text() for rel in CLUSTERS)
check("no stale 'unleash-an-agent' tag value remains", "unleash-an-agent" not in joined)
check("no pre-rename 'workshop-hub'/'workshop-spoke-' cluster names remain",
      "name: workshop-hub" not in joined and "name: workshop-spoke-" not in joined)

# AWS-resource scripts tag what they create and stay name-scoped (cannot touch Packt resources).
s3 = (REPO / "games/eso-s3-exfil/s3-hoop-setup.sh").read_text()
check("s3 hoop setup tags the bucket project=watch-it-burn",
      "put-bucket-tagging" in s3 and "watch-it-burn" in s3)
trophy = (REPO / "games/eso-s3-exfil/plant-trophy.sh").read_text()
check("trophy secret created with project=watch-it-burn tag",
      "create-secret" in trophy and "Key=project,Value=watch-it-burn" in trophy)
spoke_readme = (REPO / "infra/spoke-cluster/README.md").read_text()
check("spoke teardown is name-scoped to watch-it-burn-spoke (cannot hit Packt)",
      'delete cluster --name "watch-it-burn-spoke-' in spoke_readme)
check("tagging convention doc exists", (REPO / "infra/TAGGING.md").exists())

if failures:
    print(f"\nFAILED: {len(failures)} check(s)"); sys.exit(1)
print("\nAll tagging/naming convention checks passed.")
