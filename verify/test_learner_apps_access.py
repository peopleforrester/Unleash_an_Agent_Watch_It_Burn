# ABOUTME: Offline gate for #874: the attendee profile installs lab-platform's learner apps RBAC, exactly what
# ABOUTME: `labctl app-access burn@2.0.0` renders, so a harvested seat's attendee reaches the eight workshop apps.
#
# Why. lab-platform hands a harvested seat's learner an EKS access entry carrying the Kubernetes group
# lab-platform:learner-apps, and the attendee reads each workshop app through the API server's Service proxy. On a
# cluster lab-platform builds, its bootstrap step binds that group (internal/bootstrap/appaccess.go). On a seat this
# repo builds nothing did, so every attendee was refused 403 at the workshop apps step.
#
# The expected objects are rendered here from BURN_APPS by the same rules as lab-platform's Role.AppAccess
# (internal/eventplan/appaccess.go), read at lab-platform main on 2026-11-05: a Role and a RoleBinding named
# lab-platform-learner-apps in each namespace, namespaces sorted, proxy names sorted, get on services/proxy alone,
# the label app.kubernetes.io/managed-by=lab-platform, the one subject Group lab-platform:learner-apps. The test owns
# that list; the manifest has to equal it object for object.
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, REPO, REPO_URL, REVISION, all_profiles, app_names  # noqa: E402

MANIFEST = REPO / "gitops/learner-apps-access/learner-apps-access.yaml"
APP_FILE = APPS / "learner-apps-access.yaml"
NAME = "lab-platform-learner-apps"
GROUP = "lab-platform:learner-apps"
RBAC = "rbac.authorization.k8s.io"
LABELS = {"app.kubernetes.io/managed-by": "lab-platform"}

# lab-platform internal/eventplan/lab.go, burnApps: name, namespace, Service, port.
BURN_APPS = [
    ("grafana", "monitoring", "prometheus-grafana", 80),
    ("argocd", "argocd", "argocd-server", 80),
    ("kagent", "kagent", "kagent-ui", 8080),
    ("hedgehog", "apps", "demo-app-hedgehog", 80),
    ("wombat", "apps", "demo-app-wombat", 80),
    ("unicorn", "apps", "demo-app-unicorn", 80),
    ("spider", "apps", "demo-app-spider", 80),
    ("mantis-shrimp", "apps", "demo-app-mantis-shrimp", 80),
]

failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


def expected() -> list[dict]:
    names: dict[str, list[str]] = {}
    for _, ns, svc, port in BURN_APPS:
        names.setdefault(ns, []).append(f"http:{svc}:{port}")
    out = []
    for ns in sorted(names):
        meta = {"name": NAME, "namespace": ns, "labels": dict(LABELS)}
        out.append({"apiVersion": f"{RBAC}/v1", "kind": "Role", "metadata": dict(meta),
                    "rules": [{"apiGroups": [""], "resources": ["services/proxy"], "verbs": ["get"],
                               "resourceNames": sorted(names[ns])}]})
        out.append({"apiVersion": f"{RBAC}/v1", "kind": "RoleBinding", "metadata": dict(meta),
                    "roleRef": {"apiGroup": RBAC, "kind": "Role", "name": NAME},
                    "subjects": [{"apiGroup": RBAC, "kind": "Group", "name": GROUP}]})
    return out


print("== the manifest is labctl app-access burn@2.0.0, object for object ==")
check(f"{MANIFEST.relative_to(REPO)} exists", MANIFEST.is_file())
docs = [d for d in yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8"))] if MANIFEST.is_file() else []
check("it holds only documents, none empty", bool(docs) and all(isinstance(d, dict) and d for d in docs))
want = expected()
check(f"it holds {len(want)} objects: a Role and a RoleBinding in each of the four app namespaces ({len(docs)} found)",
      len(docs) == len(want))
for i, w in enumerate(want):
    got = docs[i] if i < len(docs) else None
    check(f"object {i + 1} is the {w['kind']} {w['metadata']['namespace']}/{NAME} lab-platform renders", got == w)
check("the namespaces are apps, argocd, kagent and monitoring",
      sorted({d["metadata"]["namespace"] for d in want}) == ["apps", "argocd", "kagent", "monitoring"])
check("the eight proxy names are the eight apps, one each",
      sum(len(d["rules"][0]["resourceNames"]) for d in want if d["kind"] == "Role") == 8 == len(BURN_APPS))

print("== nothing wider than get on the named proxies ==")
kinds = {d.get("kind") for d in docs}
check(f"only Role and RoleBinding, no ClusterRole or ClusterRoleBinding {sorted(map(str, kinds))}",
      kinds == {"Role", "RoleBinding"})
rules = [r for d in docs if d.get("kind") == "Role" for r in d.get("rules") or []]
check("every rule is get on services/proxy in the core group, by resource name",
      bool(rules) and all(r.get("verbs") == ["get"] and r.get("resources") == ["services/proxy"]
                          and r.get("apiGroups") == [""] and r.get("resourceNames") for r in rules))
check("no rule names a wildcard", not any("*" in str(r) for r in rules))
subjects = [s for d in docs if d.get("kind") == "RoleBinding" for s in d.get("subjects") or []]
check(f"every binding's subjects are the one group {GROUP}",
      bool(subjects) and all(s == {"apiGroup": RBAC, "kind": "Group", "name": GROUP} for s in subjects))

print("== the Services the proxy names point at are this repo's ==")
ns_doc = REPO / "gitops/namespaces/namespaces.yaml"
declared_ns = {d["metadata"]["name"] for d in yaml.safe_load_all(ns_doc.read_text(encoding="utf-8")) if d}
for ns in ("apps", "kagent", "monitoring", "argocd"):
    check(f"gitops/namespaces declares {ns}", ns in declared_ns)
for name, ns, svc, port in BURN_APPS:
    if not svc.startswith("demo-app-"):
        continue
    f = REPO / f"gitops/manifests/{svc}/service.yaml"
    s = next((d for d in yaml.safe_load_all(f.read_text(encoding="utf-8")) if d and d.get("kind") == "Service"),
             None) if f.is_file() else None
    ports = [p.get("port") for p in ((s or {}).get("spec") or {}).get("ports") or []]
    check(f"{f.relative_to(REPO)} is the Service {ns}/{svc} on port {port}",
          bool(s) and s["metadata"].get("name") == svc and s["metadata"].get("namespace") == ns and port in ports)
# kube-prometheus-stack names Grafana's Service <release>-grafana, and the release is the Application's name.
prom = yaml.safe_load((APPS / "prometheus.yaml").read_text(encoding="utf-8"))
check("Grafana is prometheus-grafana: the prometheus Application installs kube-prometheus-stack into monitoring "
      "with no releaseName of its own",
      prom["metadata"]["name"] == "prometheus" and prom["spec"]["source"].get("chart") == "kube-prometheus-stack"
      and "releaseName" not in (prom["spec"]["source"].get("helm") or {})
      and prom["spec"]["destination"].get("namespace") == "monitoring")
kagent = yaml.safe_load((APPS / "kagent.yaml").read_text(encoding="utf-8"))
check("kagent-ui is in kagent: the kagent Application installs the kagent chart there",
      kagent["spec"]["source"].get("chart") == "kagent" and kagent["spec"]["destination"].get("namespace") == "kagent")

print("== the Application, and the attendee profile alone ==")
check(f"{APP_FILE.relative_to(REPO)} exists", APP_FILE.is_file())
app = yaml.safe_load(APP_FILE.read_text(encoding="utf-8")) if APP_FILE.is_file() else {}
spec = app.get("spec") or {}
src = spec.get("source") or {}
check("it is the Application learner-apps-access in argocd",
      app.get("kind") == "Application" and app.get("metadata", {}).get("name") == "learner-apps-access"
      and app.get("metadata", {}).get("namespace") == "argocd")
check("it sources gitops/learner-apps-access from this repo at the pinned revision",
      src.get("repoURL") == REPO_URL and src.get("path") == "gitops/learner-apps-access"
      and src.get("targetRevision") == REVISION)
check("it syncs to the cluster it runs on, automated with prune and selfHeal",
      spec.get("destination") == {"server": "https://kubernetes.default.svc"}
      and (spec.get("syncPolicy") or {}).get("automated") == {"prune": True, "selfHeal": True})
ns_app = yaml.safe_load((APPS / "namespaces.yaml").read_text(encoding="utf-8"))


def wave(a: dict) -> int:
    return int(((a.get("metadata") or {}).get("annotations") or {}).get("argocd.argoproj.io/sync-wave", "0"))


check("it syncs after the namespaces Application creates the app namespaces", wave(app) > wave(ns_app))
for profile in all_profiles():
    listed = "learner-apps-access" in app_names(profile)
    check(f"{profile} {'lists' if profile == 'attendee' else 'does not list'} learner-apps-access",
          listed == (profile == "attendee"))

if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("ALL LEARNER APPS ACCESS CHECKS GREEN")
