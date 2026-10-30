# ABOUTME: Offline gate for arming by parameter (#638, lab-platform#310): policies/kyverno's Kustomization lists every
# ABOUTME: policy file, and the two policies the arm parameter patches to Deny exist and ship at Audit.
#
# Why. Since lab-platform#312, labctl event up arms the admin role's clusters by setting lab-platform.yaml's arm
# parameter on their lab-bootstrap root; kyverno-policies then patches require-resource-limits and
# restrict-image-registries to [Deny] with kustomize over policies/kyverno. Argo CD builds that directory from its
# Kustomization, so a policy file added there and left off the list would sync to no cluster and no error would say
# so. test_bootstrap_chart_render.py renders the armed root and applies the patches with the pinned kubectl.
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, ARM_PARAMETER, CHART, CONFIG, REPO, deploys, profiles  # noqa: E402

failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


POL = REPO / "policies/kyverno"
LIVE_TOGGLE = ("require-resource-limits", "restrict-image-registries")

print("== policies/kyverno is a kustomize base of every policy file ==")
kust = yaml.safe_load((POL / "Kustomization").read_text(encoding="utf-8"))
check("Kustomization is a kustomize.config.k8s.io/v1beta1 Kustomization",
      kust.get("apiVersion") == "kustomize.config.k8s.io/v1beta1" and kust.get("kind") == "Kustomization")
files = sorted(p.name for p in POL.glob("*.yaml"))
check(f"its resources are exactly the directory's {len(files)} *.yaml files, each once",
      sorted(kust.get("resources") or []) == files and len(set(kust["resources"])) == len(kust["resources"]))
check("it holds resources only: no patch or transformer changes a policy for every profile",
      sorted(kust) == ["apiVersion", "kind", "resources"])
check("no other kustomization file sits beside it (kustomize refuses a directory with two)",
      not any((POL / n).exists() for n in ("kustomization.yaml", "kustomization.yml")))

print("== the two live-toggle policies ship at Audit ==")
by_name = {d["metadata"]["name"]: (f, d) for f in files for d in yaml.safe_load_all((POL / f).read_text(encoding="utf-8"))
           if d}
for name in LIVE_TOGGLE:
    f, d = by_name.get(name, ("", {}))
    check(f"{name} is a ValidatingPolicy in {f or 'no file'} at [Audit]",
          d.get("kind") == "ValidatingPolicy" and d.get("apiVersion") == "policies.kyverno.io/v1"
          and d["spec"].get("validationActions") == ["Audit"])

print("== the arm parameter reaches the profiles that install the policies ==")
app = yaml.safe_load((APPS / "kyverno-policies.yaml").read_text(encoding="utf-8"))
check("kyverno-policies syncs policies/kyverno", app["spec"]["source"].get("path") == "policies/kyverno")
cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
key, _, sub = ARM_PARAMETER.partition(".")
check(f"lab-platform.yaml's arm parameter {ARM_PARAMETER} is a value the chart declares",
      cfg["arm"]["parameter"] == ARM_PARAMETER
      and sub in (yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8")).get(key) or {}))
check("the admin profile, the role lab-platform arms, installs kyverno-policies", deploys("admin", "kyverno-policies"))
check("no profile's values file sets the action itself, so only the arm step arms",
      all("guardrails" not in (yaml.safe_load((CHART / f"values-{p}.yaml").read_text(encoding="utf-8")) or {})
          for p in profiles() + ["local-inference"]))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All guardrails arm checks passed.")
