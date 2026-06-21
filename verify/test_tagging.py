# ABOUTME: Render-gate check for the AWS tagging/naming convention (collision avoidance in the shared
# ABOUTME: accen-dev account). Every cluster name starts with watch-it-burn-; every resource is tagged ours.
# Provisioning is Terraform (infra/terraform/), so these assertions read the Terraform + fleet driver.
import pathlib, sys
REPO = pathlib.Path(__file__).resolve().parents[1]
TF = REPO / "infra" / "terraform"
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

lab_vpc = (TF / "lab-vpc" / "main.tf").read_text()
cluster = (TF / "cluster" / "main.tf").read_text()
fleet = (TF / "fleet" / "fleet.sh").read_text()

# Every Terraform root tags all resources project=watch-it-burn via provider default_tags.
for name, txt in [("lab-vpc", lab_vpc), ("cluster", cluster)]:
    check(f"{name}/main.tf default_tags set project=watch-it-burn",
          "default_tags" in txt and 'project   = "watch-it-burn"' in txt)
# The per-attendee cluster also carries an attendee=<name> tag (propagates to its EC2/EBS).
check("cluster/main.tf tags each cluster with attendee=<name>", 'attendee  = var.name' in cluster)

# Cluster names start with watch-it-burn- (the collision boundary): the fleet generates
# watch-it-burn-attendee-NNN and refuses any name that is not watch-it-burn-*.
check("fleet names attendee clusters watch-it-burn-attendee-*",
      'NAME_PREFIX="watch-it-burn-attendee"' in fleet)
check("fleet refuses any non-watch-it-burn cluster name (cannot touch co-tenant Packt)",
      "assert_ours" in fleet and "watch-it-burn-*" in fleet)

# Independent-cluster model: no hub/spoke naming anywhere in the provisioning.
joined = lab_vpc + cluster + fleet
check("no hub/spoke naming remains (independent-cluster model)",
      "watch-it-burn-spoke" not in joined and "watch-it-burn-hub" not in joined)
check("no stale 'unleash-an-agent' tag value remains", "unleash-an-agent" not in joined)
# One shared lab VPC (not one per cluster): the cluster module takes vpc_id as an input.
check("attendee clusters share the one lab VPC (cluster takes vpc_id as input)",
      'variable "vpc_id"' in cluster and "module \"vpc\"" in lab_vpc)

# AWS-resource scripts tag what they create and stay name-scoped (cannot touch Packt resources).
s3 = (REPO / "games/eso-s3-exfil/s3-hoop-setup.sh").read_text()
check("s3 hoop setup tags the bucket project=watch-it-burn",
      "put-bucket-tagging" in s3 and "watch-it-burn" in s3)
trophy = (REPO / "games/eso-s3-exfil/plant-trophy.sh").read_text()
check("trophy secret created with project=watch-it-burn tag",
      "create-secret" in trophy and "Key=project,Value=watch-it-burn" in trophy)
teardown = (REPO / "teardown/teardown.sh").read_text()
check("teardown is prefix-scoped to watch-it-burn (cannot hit the co-tenant Packt clusters)",
      'CLUSTER_PREFIX' in teardown and "watch-it-burn" in teardown
      and 'refusing prefix' in teardown)
check("tagging convention doc exists", (REPO / "infra/TAGGING.md").exists())
check("shared-VPC doc exists (one VPC, not per-cluster)", (REPO / "infra/shared-vpc/README.md").exists())
check("Terraform provisioning README exists", (TF / "README.md").exists())

if failures:
    print(f"\nFAILED: {len(failures)} check(s)"); sys.exit(1)
print("\nAll tagging/naming convention checks passed.")
