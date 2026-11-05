# ABOUTME: Offline gate for which Kyverno CEL policies each profile installs (#467), the set the live check
# ABOUTME: test_kyverno_cel_live.py holds a cluster to, read from the cluster's own lab-platform/profile label.
"""Why (#467). test_kyverno_cel_live.py counted eleven policies, every file in policies/kyverno and policies/floor.
The two clusters a dispatched run has are the KubeCon pair (#774), and neither holds those eleven:
kubecon-community syncs restrict-image-registries alone (kyverno-registry-policy) and deny-external-registries
(kyverno-breakout), and kubecon-private adds deny-external-registries to the eleven. The live check now asks
bootstrap_chart.kyverno_policies for the profile the cluster's root names. This holds that answer, without a cluster:

  * attendee, full and admin get the eleven, every policy file in policies/kyverno and policies/floor, as before;
    admin is what watch-it-burn-private runs (run 17286 read it off the cluster on 2026-11-05);
  * kubecon-private gets those eleven and deny-external-registries;
  * kubecon-community gets exactly restrict-image-registries and deny-external-registries, each from its app;
  * burn installs no Kyverno policy, and watch-it-burn-community runs burn, so the live check has no wall there;
  * the Kustomization the kyverno-policies app builds names every policy file in policies/kyverno;
  * the label the live check reads is the one infra/deploy-full-idp.sh puts on lab-bootstrap, valued the profile.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import REPO, all_profiles, deploy_root, kyverno_policies  # noqa: E402

LIVE = REPO / "verify/test_kyverno_cel_live.py"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def names(files: list[pathlib.Path]) -> set[str]:
    out = set()
    for f in files:
        for d in yaml.safe_load_all(f.read_text(encoding="utf-8")):
            if d and d.get("kind") in ("ValidatingPolicy", "ImageValidatingPolicy"):
                out.add(d["metadata"]["name"])
    return out


def flat(profile: str) -> dict[str, str]:
    return {p: app for kind in kyverno_policies(profile).values() for p, app in kind.items()}


workshop = names(sorted((REPO / "policies/kyverno").glob("*.yaml")) + sorted((REPO / "policies/floor").glob("*.yaml")))
breakout = names(sorted((REPO / "policies/kyverno-breakout").glob("*.yaml")))

print("== the policy files ==")
check("policies/kyverno and policies/floor hold eleven policies", len(workshop) == 11, f"they hold {sorted(workshop)}")
check("policies/kyverno-breakout holds deny-external-registries alone", breakout == {"deny-external-registries"},
      f"it holds {sorted(breakout)}")

print("== each profile's set ==")
for profile in ("attendee", "full", "admin"):
    got = flat(profile)
    check(f"{profile} installs the eleven", set(got) == workshop, f"got {sorted(got)}")
got = flat("kubecon-private")
check("kubecon-private installs the eleven and deny-external-registries", set(got) == workshop | breakout,
      f"got {sorted(got)}")
check("kubecon-private's deny-external-registries comes from kyverno-breakout",
      got.get("deny-external-registries") == "kyverno-breakout", f"got {got.get('deny-external-registries')}")
got = flat("kubecon-community")
want = {"restrict-image-registries": "kyverno-registry-policy", "deny-external-registries": "kyverno-breakout"}
check("kubecon-community installs restrict-image-registries and deny-external-registries, each from its app",
      got == want, f"got {got}")
check("burn installs no Kyverno policy", flat("burn") == {}, f"got {flat('burn')}")
for profile in all_profiles():
    got = flat(profile)
    if got:
        check(f"{profile} installs restrict-image-registries, which the live check's C2 steps need",
              "restrict-image-registries" in got)

print("== what kyverno-policies builds ==")
kustomization = yaml.safe_load((REPO / "policies/kyverno/Kustomization").read_text(encoding="utf-8"))
listed = names([REPO / "policies/kyverno" / r for r in kustomization["resources"]])
on_disk = names(sorted((REPO / "policies/kyverno").glob("*.yaml")))
check("the Kustomization lists every policy file in policies/kyverno", listed == on_disk,
      f"missing {sorted(on_disk - listed)}")

print("== the label the live check reads ==")
live = LIVE.read_text(encoding="utf-8")
check("the live check reads lab-bootstrap's lab-platform/profile label",
      'PROFILE_LABEL = "lab-platform/profile"' in live and "applications.argoproj.io/lab-bootstrap" in live)
check("the live check takes its policy set from bootstrap_chart.kyverno_policies", "kyverno_policies(profile)" in live)
for profile in ("attendee", "full", "admin", "burn", "kubecon-community", "kubecon-private"):
    root = deploy_root(profile)
    label = ((root.get("metadata") or {}).get("labels") or {}).get("lab-platform/profile")
    check(f"deploy-full-idp.sh labels the {profile} root lab-platform/profile={profile}", label == profile,
          f"got {label!r}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All Kyverno profile policy checks passed.")
