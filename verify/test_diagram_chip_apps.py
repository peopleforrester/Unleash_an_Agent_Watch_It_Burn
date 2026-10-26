# ABOUTME: Holds every component chip on the build diagram (diagram.html) to an Argo CD Application in
# ABOUTME: gitops/bootstrap/apps, so a removed app cannot leave a chip behind that never lights up (#478).
"""Why this exists (#478).

Each chip on diagram.html carries a key `k` that the live status view matches against the components it
reports running. The keys name an Application in gitops/bootstrap/apps, either by its name or by its file (`istio`
covers the five Istio Applications in istio.yaml). When #478 removed the `rbac` and `resource-quotas` apps,
their chips would otherwise have stayed on the page as components that are never up. Argo CD itself is
installed by deploy-full-idp.sh, not by an Application, so `argocd` is the one key with no manifest.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f": {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


html = (REPO / "gitops/ai-layer/web/diagram.html").read_text(encoding="utf-8")
chips = re.search(r"var CHIPS = \[(.*?)\n  \];", html, re.S)
check("diagram.html declares CHIPS", chips is not None)
keys = set(re.findall(r"\bk:'([^']+)'", chips.group(1))) if chips else set()
check("CHIPS carry keys", bool(keys))

apps = set()
for f in (REPO / "gitops/bootstrap/apps").glob("*.yaml"):
    apps.add(f.stem)
    for doc in yaml.safe_load_all(f.read_text(encoding="utf-8")):
        if doc and doc.get("kind") == "Application":
            apps.add(doc["metadata"]["name"])

stale = sorted(keys - apps - {"argocd"})
check("every chip key names an Application in gitops/bootstrap/apps", not stale, f"{stale}")
check("no chip for the removed rbac or resource-quotas apps", not keys & {"rbac", "resource-quotas"})
check("the rbac and resource-quotas apps stay removed", not apps & {"rbac", "resource-quotas"})

if failures:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
print("\nall diagram chip checks passed")
