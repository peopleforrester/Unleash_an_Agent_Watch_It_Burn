# ABOUTME: Every place that names the EKS version the fleet builds agrees with the one place that sets it: the
# ABOUTME: kubernetes_version default in infra/terraform/aws/cluster/main.tf, which fleet.sh never overrides.
#
# Why (#605). 2f885d1 (2026-09-10, PRD #389 tier 3) moved that default from 1.35 to 1.36 and nothing else moved:
# VERSIONS.lock went on saying 1.35 "stays pinned for the event", and the build spec, the recreation spec and the
# tech status went on calling 1.35 the cluster version, while every cluster built after it came up on 1.36. The
# Terraform default is what CreateCluster receives, so it is the source and every other copy is held to it, as
# test_kyverno_version_pins.py holds the Kyverno copies to the chart the Application pins.
#
# VERSIONS.lock's LIVE-VALIDATED section records the version one cluster had on 2026-06-22; that is history and
# is not checked. The "Kubernetes version" section is the pin.
import pathlib, re, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


main_tf = (REPO / "infra/terraform/aws/cluster/main.tf").read_text()
var = re.search(r'variable "kubernetes_version" \{[^}]*?default\s*=\s*"([^"]+)"', main_tf, re.S)
check("infra/terraform/aws/cluster/main.tf gives kubernetes_version a default", var is not None)
built = var.group(1) if var else None
check("the cluster module passes var.kubernetes_version to the EKS module",
      re.search(r"^\s*kubernetes_version\s*=\s*var\.kubernetes_version\s*$", main_tf, re.M) is not None)

# fleet.sh is the only thing that runs the cluster root; an override there would make the default a lie.
fleet = (REPO / "infra/terraform/fleet/fleet.sh").read_text()
check("fleet.sh does not override kubernetes_version", "kubernetes_version" not in fleet)

print("== VERSIONS.lock pins the version the fleet builds ==")
lock = (REPO / "VERSIONS.lock").read_text()
section = re.search(r"^## Kubernetes version\b.*?(?=^## |\Z)", lock, re.M | re.S)
check("VERSIONS.lock has a Kubernetes version section", section is not None)
pins = re.findall(r"^eks-kubernetes\s+(\d+\.\d+)\b", section.group(0) if section else "", re.M)
check(f"the Kubernetes version section pins eks-kubernetes {built}, the Terraform default", pins == [built],
      f"got {pins}")

print("== the working docs name the EKS version the fleet builds ==")
# Each states the current cluster version. decisions.md, PROJECT_STATE.md, the PRDs, UPGRADE-INVENTORY.md (a dated
# inventory) and the research notes are records and are not checked.
DOCS = {
    "docs/BUILD-SPEC.md": [r"\bEKS `(\d+\.\d+)`"],
    "docs/MASTER-RECREATION-SPEC.md": [r"\bEKS is pinned to (\d+\.\d+)\b", r'`kubernetes_version="(\d+\.\d+)"`'],
    "docs/TECH-STATUS.md": [r"Terraform cluster configs \((\d+\.\d+),"],
}
for rel, patterns in DOCS.items():
    text = (REPO / rel).read_text(encoding="utf-8")
    for pat in patterns:
        found = re.findall(pat, text)
        check(f"{rel} names EKS {built} where it says {pat!r}", found and all(v == built for v in found),
              f"got {found}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll EKS version pin checks passed.")
