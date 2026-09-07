# ABOUTME: Static gate for the permanent Argo CD drift found on 2026-09-06 (#254): defaults the API strips,
# ABOUTME: Kyverno fields the webhook writes back, CRD labels the chart renders empty, and pods a policy denies.
#
# Why. converge can only declare a cluster converged when every Application is Synced. Five apps were
# OutOfSync on every fresh cluster for reasons that live in the manifests, not the clusters, so health
# was permanently false and a real failure (customer-stream denied by require-labels, the C1 target
# never deployed on attendee clusters) hid inside the noise. Each cause below is a manifest property.
import pathlib, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


def docs(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


print("== roots carry no default the API server strips ==")
for root in sorted((REPO / "gitops/bootstrap").glob("*/*.yaml")):
    d = docs(root)[0]
    dirs = [s.get("directory", {}) for s in d["spec"]["sources"]]
    check(f"{root.parent.name}: no 'recurse: false' (default; live never carries it)", all("recurse" not in x for x in dirs))

print("== every root ignores the finalizers a chart adds to its child Applications ==")
for root in sorted((REPO / "gitops/bootstrap").glob("*/*.yaml")):
    d = docs(root)[0]
    ign = d["spec"].get("ignoreDifferences", [])
    check(f"{root.parent.name}: ignores Application /metadata/finalizers",
          any(i.get("kind") == "Application" and "/metadata/finalizers" in i.get("jsonPointers", []) for i in ign))
    check(f"{root.parent.name}: RespectIgnoreDifferences is set",
          "RespectIgnoreDifferences=true" in d["spec"]["syncPolicy"].get("syncOptions", []))

print("== every Kyverno validate rule states the defaults the webhook writes back ==")
for pol in sorted(list((REPO / "policies/kyverno").glob("*.yaml")) + list((REPO / "policies/floor").glob("*.yaml"))):
    for d in docs(pol):
        if d.get("kind") != "ClusterPolicy":
            continue
        for rule in d["spec"].get("rules", []):
            if "validate" not in rule:
                continue
            check(f"{pol.name}/{rule['name']}: skipBackgroundRequests and allowExistingViolations present",
                  rule.get("skipBackgroundRequests") is True and rule["validate"].get("allowExistingViolations") is True)

print("== workloads in the apps namespace carry the labels require-labels demands ==")
required = set()
for d in docs(REPO / "policies/kyverno/require-labels.yaml"):
    for rule in d["spec"]["rules"]:
        required |= set(rule["validate"]["pattern"]["metadata"]["labels"].keys())
check("require-labels demands app and version", required == {"app", "version"})
for mf in sorted((REPO / "gitops/manifests").rglob("*.yaml")):
    for d in docs(mf):
        if d.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet") or d["metadata"].get("namespace") != "apps":
            continue
        labels = d["spec"]["template"]["metadata"].get("labels", {})
        check(f"{mf.relative_to(REPO)} {d['metadata']['name']}: pod template has {sorted(required)}", required <= set(labels))
        # require-probes is Enforce in apps as well: every container needs both probes or the pod is denied.
        cs = d["spec"]["template"]["spec"]["containers"]
        check(f"{mf.relative_to(REPO)} {d['metadata']['name']}: every container has readiness and liveness probes",
              all("readinessProbe" in c and "livenessProbe" in c for c in cs))

print("== every apps-namespace Service port is admitted by the apps ingress policy ==")
pol = docs(REPO / "policies/network-policies/per-namespace/apps-allow-ingress.yaml")[0]
allowed = {int(pp["port"]) for rule in pol["spec"]["ingress"] for pp in rule.get("ports", [])}
for mf in sorted((REPO / "gitops/manifests").rglob("*.yaml")):
    for d in docs(mf):
        if d.get("kind") != "Service" or d["metadata"].get("namespace") != "apps":
            continue
        ports = {int(pp.get("targetPort", pp["port"])) for pp in d["spec"]["ports"] if str(pp.get("targetPort", pp["port"])).isdigit()}
        check(f"{mf.relative_to(REPO)} {d['metadata']['name']}: target ports {sorted(ports)} allowed by allow-ingress-controller", ports <= allowed)

print("== the kyverno app ignores the CRD labels its chart renders empty ==")
k = docs(REPO / "gitops/apps/kyverno.yaml")[0]
ign = k["spec"].get("ignoreDifferences", [])
check("ignoreDifferences covers CustomResourceDefinition /metadata/labels",
      any(i.get("kind") == "CustomResourceDefinition" and "/metadata/labels" in i.get("jsonPointers", []) for i in ign))
check("RespectIgnoreDifferences is a sync option", "RespectIgnoreDifferences=true" in k["spec"]["syncPolicy"].get("syncOptions", []))
check("the kyverno app compares server-side (CRD defaults the API strips)",
      k["metadata"].get("annotations", {}).get("argocd.argoproj.io/compare-options") == "ServerSideDiff=true")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All permanent-drift checks passed.")
