# ABOUTME: Every place that names the deployed kagent agrees: the chart gitops/apps/kagent.yaml and kagent-crds.yaml
# ABOUTME: pin, the VERSIONS.lock kagent line, and the working docs that state the current version.
#
# Why (#556). 20aee62 (2026-09-10) moved kagent and kagent-crds from 0.9.9 to 0.10.1 and nothing else moved:
# VERSIONS.lock went on recording chart 0.9.9 / app v0.9.9, and the walkthrough, the build spec, the recreation
# spec and the tech status went on calling 0.9.9 current for six weeks. It is the drift #495 and #506 fixed for
# agentgateway, and test_agentgateway_config.py holds that one; this holds kagent the same way.
import pathlib, re, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


def target_revision(rel):
    return str(yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))["spec"]["source"]["targetRevision"])


print("== the controller and its CRDs are one version ==")
chart = target_revision("gitops/apps/kagent.yaml")
crds = target_revision("gitops/apps/kagent-crds.yaml")
check(f"gitops/apps/kagent-crds.yaml pins {chart}, the chart gitops/apps/kagent.yaml deploys (found {crds})",
      crds == chart)

print("== VERSIONS.lock records the chart we deploy ==")
lock_lines = [l for l in (REPO / "VERSIONS.lock").read_text(encoding="utf-8").splitlines() if re.match(r"^kagent\s", l)]
check("VERSIONS.lock has one kagent line", len(lock_lines) == 1, f"{lock_lines}")
lock = lock_lines[0] if lock_lines else ""
c = re.search(r"\bchart (\S+)", lock)
a = re.search(r"\bapp (v\S+)", lock)
check(f"VERSIONS.lock records kagent chart {chart} (found {c.group(1) if c else None})", c is not None and c.group(1) == chart)
# kagent releases the chart and the controller image under one tag, so the app version is the chart's with a v.
check(f"VERSIONS.lock records kagent app v{chart} (found {a.group(1) if a else None})", a is not None and a.group(1) == f"v{chart}")

print("== the working docs name the version we deploy ==")
# Each of these states the deployed kagent. A line may name an older release only beside the deployed one, as
# history ("moved from 0.9.9"). decisions.md, the PRDs and the dated research notes are records and are not checked.
CURRENT_DOCS = (
    "docs/STACK-WALKTHROUGH.md",
    "docs/BUILD-SPEC.md",
    "docs/MASTER-RECREATION-SPEC.md",
    "docs/TECH-STATUS.md",
    "docs/UPGRADE-INVENTORY.md",
)
# The releases these docs have called current before. 0.9.x is the only line kagent has been pinned to besides
# the current one, and no other component in these docs is on a 0.9.x version.
STALE = re.compile(r"\b0\.9\.\d+\b")
for rel in CURRENT_DOCS:
    lines = (REPO / rel).read_text(encoding="utf-8").splitlines()
    check(f"{rel} names kagent {chart}", any("kagent" in l and re.search(rf"\b{re.escape(chart)}\b", l) for l in lines))
    stale = [i for i, l in enumerate(lines, 1) if STALE.search(l) and not re.search(rf"\b{re.escape(chart)}\b", l)]
    check(f"{rel} names 0.9.x only beside {chart} (lines {stale})", not stale)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll kagent version pin checks passed.")
