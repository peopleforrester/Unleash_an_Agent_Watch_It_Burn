# ABOUTME: The Falco badge is lit only where Falco is on the cluster: guard-proxy may read the DaemonSet,
# ABOUTME: the page needs /controls to report it, and the hostname override lives exactly as long as the pin needs it.
"""Pins #486.

The Community cluster runs the burn profile, which installs no Falco. A guard-proxy that answers
falco:true everywhere would light a detection badge for a detector that is not there, so /controls has
to measure Falco the way it measures every other control: by reading the object. Three things have to
agree for that to work, and each one lives in a different file:

- RBAC: guard-proxy-reader may `get` the one DaemonSet the Falco chart creates, and nothing wider.
- The name: that DaemonSet is security/falco, which is what the Falco Application renders.
- The page: the Falco badge needs infra.falco, not only KubeArmor, or a measured false is thrown away.

The pinned guard-proxy (the submodule) still hardcodes falco:true. Until it moves, burritbot.html keeps
its hostname override for the Community cluster. The last check ties the two together, so the bump that
brings in the measurement fails here until the override is dropped, and dropping the override early
fails here too.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
RES = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if isinstance(d, dict)]
FALCO_APP = yaml.safe_load((REPO / "gitops/apps/falco.yaml").read_text())
BB = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
SMOKE = (REPO / "verify/browser-smoke.py").read_text(encoding="utf-8")
PROXY = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text(encoding="utf-8")

FALCO_NS = "security"
FALCO_DS = "falco"
FALCO_PATH = f"/apis/apps/v1/namespaces/{FALCO_NS}/daemonsets/{FALCO_DS}"
OVERRIDE = "if(bd.key==='falco' && community) on = false;"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def obj(kind: str, name: str) -> dict:
    hits = [d for d in RES if d.get("kind") == kind and (d.get("metadata") or {}).get("name") == name]
    return hits[0] if len(hits) == 1 else {}


print("== guard-proxy-reader may read the Falco DaemonSet, and only that ==")
cr = obj("ClusterRole", "guard-proxy-reader")
ds_rules = [r for r in cr.get("rules", []) if "daemonsets" in r.get("resources", [])]
check("the ClusterRole has exactly one DaemonSet rule", len(ds_rules) == 1)
rule = ds_rules[0] if ds_rules else {}
check("it is in the apps group only", rule.get("apiGroups") == ["apps"])
check("it names the falco DaemonSet only", rule.get("resourceNames") == [FALCO_DS])
check("it is get-only", rule.get("verbs") == ["get"])
check("it grants no other resource", rule.get("resources") == ["daemonsets"])
crb = obj("ClusterRoleBinding", "guard-proxy-reader")
check("the ClusterRole is bound to guard-proxy-reader in agent",
      crb.get("roleRef", {}).get("name") == "guard-proxy-reader"
      and {"kind": "ServiceAccount", "name": "guard-proxy-reader", "namespace": "agent"} in crb.get("subjects", []))
# The bundle sets `namespace: agent`, which rewrites a namespaced Role's namespace, so a Role in `security`
# written here would land in agent and grant nothing on the DaemonSet. No such Role may sneak in.
check("no namespaced Role in this bundle claims the security namespace",
      not any(d.get("kind") in ("Role", "RoleBinding") and (d.get("metadata") or {}).get("namespace") == FALCO_NS
              for d in RES))
for r in cr.get("rules", []) + obj("Role", "guard-proxy-reader").get("rules", []):
    what = "/".join(r.get("resources", []))
    check(f"guard-proxy-reader stays get-only on named objects ({what})",
          r.get("verbs") == ["get"] and bool(r.get("resourceNames")))

print("== the DaemonSet guard-proxy reads is the one the Falco Application renders ==")
spec = FALCO_APP.get("spec", {})
helm = (spec.get("source") or {}).get("helm") or {}
values = helm.get("valuesObject") or {}
check("Falco is deployed into security", (spec.get("destination") or {}).get("namespace") == FALCO_NS)
check("the Falco chart is the source", (spec.get("source") or {}).get("chart") == "falco")
# The chart names its DaemonSet falco.fullname: the release name when it contains "falco". The release
# name is the Application name unless helm.releaseName overrides it.
release = helm.get("releaseName") or FALCO_APP.get("metadata", {}).get("name")
check("the release is named falco", release == FALCO_DS)
check("no name override changes the DaemonSet name",
      not any(k in values for k in ("fullnameOverride", "nameOverride")))

print("== the page lights Falco from /controls, never from KubeArmor alone ==")
check("the Falco badge reads infra.falco", "{src:'infra', key:'falco'," in BB and "pairWith:'kubearmor'" in BB)
check("pairing keeps the measured value instead of replacing it",
      "if(bd.pairWith) on = on && infra[bd.pairWith]===true;" in BB)
check("the old copy-KubeArmor rule is gone", "if(bd.pairWith) on = infra[bd.pairWith]===true;" not in BB)
check("the browser smoke expects Falco only when /controls reports it",
      re.search(r'infra\.get\("kubearmor"\) is True and infra\.get\("falco"\) is True', SMOKE) is not None)

print("== the hostname override lives exactly as long as the pinned guard-proxy needs it ==")
hardcoded = re.search(r'^\s*out\["falco"\]\s*=\s*True\s*$', PROXY, re.M) is not None
measured = FALCO_PATH in PROXY
check("the pinned proxy.py either hardcodes Falco or reads the DaemonSet, not both or neither",
      hardcoded != measured)
if hardcoded:
    check("proxy.py still hardcodes falco:true, so the Community override must stay", OVERRIDE in BB)
else:
    check("proxy.py measures the falco DaemonSet, so the Community override must go", OVERRIDE not in BB)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All Falco badge checks passed.")
