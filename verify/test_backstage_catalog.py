# ABOUTME: Render gate for Backstage (#244): the catalog is valid and complete, every non-infrastructure pod is
# ABOUTME: found by exactly one entity, and the deployment, routing, RBAC and image base agree with each other.
"""Why this exists (#244).

The catalog is hand-written YAML that claims to describe the cluster, and the cluster changes underneath it.
A Component whose label selector names a label no pod carries shows an empty Kubernetes tab, which looks
exactly like a workload that is down. So the selectors are checked against the labels the manifests in this
repo actually put on each pod template, and every Deployment outside infrastructure must be claimed by
exactly one Component.

The real image was run against this catalog on 2026-10-24 (all 40 entities ingested with no processing
errors, guest sign-in, the Kubernetes tab against a stand-in API server). That run needs a container
runtime; what is checked here is what can drift without one.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
BS = REPO / "backstage"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def docs(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if isinstance(d, dict)]


kust = docs(BS / "kustomization.yaml")[0]
config = docs(BS / "app-config.yaml")[0]
gen = {g["name"]: g for g in kust["configMapGenerator"]}
catalog_files = gen["backstage-catalog"]["files"]

print("== the mounted catalog and the configured locations are the same list ==")
mounted = sorted(pathlib.Path(f).name for f in catalog_files)
located = sorted(pathlib.Path(loc["target"]).name for loc in config["catalog"]["locations"])
check(f"every catalog file is a location and every location is mounted ({mounted} vs {located})", mounted == located)
check("every location is under the mount path", all(loc["target"].startswith("/app/catalog/") for loc in config["catalog"]["locations"]))
on_disk = sorted(p.name for p in (BS / "catalog").glob("*.yaml"))
check(f"no catalog file on disk is left out of the ConfigMap ({on_disk})", on_disk == mounted)

entities: dict[tuple[str, str], dict] = {}
dupes = []
for f in catalog_files:
    for e in docs(BS / f):
        key = (e["kind"].lower(), e["metadata"]["name"])
        if key in entities:
            dupes.append(key)
        entities[key] = e

print("== every entity is well formed ==")
allowed = {k.lower() for k in config["catalog"]["rules"][0]["allow"]}
NAME = re.compile(r"^[a-z0-9A-Z]([-_.]?[a-z0-9A-Z])*$")
check("no entity is defined twice", not dupes)
check("every entity is backstage.io/v1alpha1", all(e["apiVersion"] == "backstage.io/v1alpha1" for e in entities.values()))
bad_kind = [k for k in entities if k[0] not in allowed]
check(f"every kind is allowed by catalog.rules ({bad_kind})", not bad_kind)
bad_name = [n for _, n in entities if not NAME.match(n) or len(n) > 63]
check(f"every name is a valid entity name ({bad_name})", not bad_name)
no_desc = [k for k, e in entities.items() if not e["metadata"].get("description")]
check(f"every entity says what it is ({no_desc})", not no_desc)


def ref(value: str, default_kind: str) -> tuple[str, str]:
    kind, _, name = value.rpartition(":")
    return ((kind or default_kind).lower(), name.split("/")[-1])


print("== every relation points at something in the catalog ==")
dangling = []
for (kind, name), e in entities.items():
    spec = e.get("spec", {})
    refs = []
    if "owner" in spec:
        refs.append(ref(spec["owner"], "group"))
    if "system" in spec:
        refs.append(ref(spec["system"], "system"))
    if "domain" in spec:
        refs.append(ref(spec["domain"], "domain"))
    if "parent" in spec:
        refs.append(ref(spec["parent"], "group"))
    refs += [ref(c, "group") for c in spec.get("children", [])]
    refs += [ref(a, "api") for a in spec.get("providesApis", []) + spec.get("consumesApis", [])]
    refs += [ref(d, "component") for d in spec.get("dependsOn", [])]
    dangling += [(f"{kind}:{name}", r) for r in refs if r not in entities]
check(f"no dangling relation ({dangling})", not dangling)

print("== the request in #244 is all there ==")
named = ["unicorn-party", "hedgehog-party", "wombat-party", "spider-party", "mantis-shrimp-party", "customer-stream",
         "workshop-agent", "workshop-mcp", "evil-mcp", "guard-proxy", "console", "web-terminal",
         "provisioning-app", "apex-router", "backstage"]
missing = [n for n in named if ("component", n) not in entities]
check(f"every workload the issue names has a Component ({missing})", not missing)
for system in ("provisioning", "apex-router"):
    s = entities.get(("system", system), {})
    check(f"{system} is a System tagged external", "external" in s.get("metadata", {}).get("tags", []))
    k8s = [n for (k, n), e in entities.items() if k == "component" and e["spec"].get("system") == system
           and any(a.startswith("backstage.io/kubernetes") for a in e["metadata"].get("annotations", {}))]
    check(f"{system} runs off-cluster, so nothing in it asks the Kubernetes plugin for pods ({k8s})", not k8s)
bb_owners = {e["spec"]["owner"] for (k, _), e in entities.items() if k == "component" and e["spec"].get("system") == "burritobot"}
check(f"BurritoBot's page shows both columns of the tour table ({sorted(bb_owners)})",
      {"burritobot-developers", "platform-team"} <= bb_owners)
check("the agent is the developers'", entities[("component", "workshop-agent")]["spec"]["owner"] == "burritobot-developers")
check("guard-proxy is the platform team's", entities[("component", "guard-proxy")]["spec"]["owner"] == "platform-team")


def parse_selector(sel: str):
    """Equality (k=v) and set-based (k in (a,b)) terms, comma-separated, as the Kubernetes API takes them."""
    terms, rest = [], sel.strip()
    while rest:
        m = re.match(r"([\w./-]+)\s+in\s+\(([^)]*)\)\s*(,|$)", rest) or re.match(r"([\w./-]+)\s*=\s*([\w.-]+)\s*(,|$)", rest)
        if not m:
            raise ValueError(f"cannot parse selector {sel!r}")
        terms.append((m.group(1), {v.strip() for v in m.group(2).split(",")}))
        rest = rest[m.end():].strip()
    return terms


def matches(sel: str, labels: dict) -> bool:
    return all(labels.get(k) in vals for k, vals in parse_selector(sel))


print("== every non-infrastructure pod is found by exactly one Component ==")
# (where, namespace, name, pod labels). The ai-layer namespace comes from its kustomization.
pods = []
for d in sorted((REPO / "gitops/manifests").glob("demo-app-*")) + [REPO / "gitops/manifests/customer-stream"]:
    for f in sorted(d.glob("*.yaml")):
        for o in docs(f):
            if o.get("kind") == "Deployment":
                pods.append((o["metadata"]["namespace"], o["metadata"]["name"], o["spec"]["template"]["metadata"]["labels"]))
ai = REPO / "gitops/ai-layer"
ai_kust = docs(ai / "kustomization.yaml")[0]
for f in ai_kust["resources"]:
    for o in docs(ai / f):
        if o.get("kind") == "Deployment":
            pods.append((ai_kust["namespace"], o["metadata"]["name"], o["spec"]["template"]["metadata"]["labels"]))
        if o.get("kind") == "Agent":
            # kagent's operator creates the Deployment and labels the pod kagent=<agent name>.
            pods.append((ai_kust["namespace"], o["metadata"]["name"], {"kagent": o["metadata"]["name"]}))
for o in docs(BS / "k8s/backstage.yaml") + docs(BS / "k8s/postgres.yaml"):
    if o.get("kind") == "Deployment":
        pods.append((o["metadata"]["namespace"], o["metadata"]["name"], o["spec"]["template"]["metadata"]["labels"]))
check(f"the scan found the workloads it should ({len(pods)})", len(pods) >= 16)

selectors = []
for (kind, name), e in entities.items():
    ann = e["metadata"].get("annotations", {})
    if "backstage.io/kubernetes-label-selector" in ann:
        selectors.append((f"{kind}:{name}", ann.get("backstage.io/kubernetes-namespace"), ann["backstage.io/kubernetes-label-selector"]))
check("every selector names its namespace", all(ns for _, ns, _ in selectors))
for ns, name, labels in pods:
    owners = [who for who, sns, sel in selectors if sns == ns and matches(sel, labels)]
    check(f"{ns}/{name} is claimed by exactly one entity ({owners})", len(owners) == 1)
empty = [who for who, sns, sel in selectors if not any(ns == sns and matches(sel, lb) for ns, _, lb in pods)]
check(f"no selector matches nothing, which would show an empty Kubernetes tab ({empty})", not empty)

print("== the application ships on attendee, full and admin, and not on burn ==")
app = docs(REPO / "gitops/apps/backstage.yaml")[0]
check("the Application deploys backstage/", app["spec"]["source"]["path"] == "backstage")
for profile in ("attendee/app-of-apps-attendee.yaml", "full/app-of-apps.yaml", "admin/app-of-apps-admin.yaml"):
    root = docs(REPO / "gitops/bootstrap" / profile)[0]
    src = next(s for s in root["spec"]["sources"] if s["path"] == "gitops/apps")
    check(f"{profile} does not exclude it", "backstage" not in (src.get("directory") or {}).get("exclude", ""))
burn = docs(REPO / "gitops/bootstrap/burn/app-of-apps-burn.yaml")[0]
burn_src = next(s for s in burn["spec"]["sources"] if s["path"] == "gitops/apps")
check("the burn profile's include list leaves it out", "backstage" not in burn_src["directory"]["include"])
check("templates and the test service are not deployed", all("templat" not in r for r in kust["resources"]))

print("== backstage-<cluster> reaches the Service, and the fleet publishes the same hosts the console serves ==")
conf = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")
served = re.search(r"server_name ~\^\(([^)]*)\)-\[a-z0-9-\]\+", conf).group(1).split("|")
fleet = re.search(r'readonly WIB_SERVICE_HOSTS="([^"]*)"', (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")).group(1).split()
check(f"console server_name and fleet.sh WIB_SERVICE_HOSTS list the same services ({served} vs {fleet})", sorted(served) == sorted(fleet))
check("backstage is one of them", "backstage" in served)
check("the backstage host proxies to the backstage Service on 80",
      re.search(r'"~\^backstage-\[a-z0-9-\]\+\\\.agenticburn\\\.com\$"\s+http://backstage\.backstage\.svc\.cluster\.local:80;', conf) is not None)
svc = next(o for o in docs(BS / "k8s/backstage.yaml") if o["kind"] == "Service")
check("that Service exists and listens on 80", svc["metadata"]["name"] == "backstage" and svc["spec"]["ports"][0]["port"] == 80)
for page in ("gitops/ai-layer/web/platform.html", "gitops/ai-layer/web/lab.html"):
    check(f"{page} links backstage-<cluster>", 'data-svc="backstage"' in (REPO / page).read_text(encoding="utf-8"))
check("the terminal's platform command lists it",
      "backstage-${_h}" in (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_text(encoding="utf-8"))

print("== the public portal reads only what it needs ==")
role = next(o for o in docs(BS / "k8s/backstage-rbac.yaml") if o["kind"] == "ClusterRole")
granted = {r for rule in role["rules"] for r in rule["resources"]}
verbs = {v for rule in role["rules"] for v in rule["verbs"]}
check(f"read verbs only ({sorted(verbs)})", verbs <= {"get", "list", "watch"})
check("no pod logs, ConfigMaps or Secrets", not granted & {"pods/log", "configmaps", "secrets"})
wanted = set(config["kubernetes"]["objectTypes"])
check(f"every object type the plugin asks for is granted ({sorted(wanted - granted)})", wanted <= granted)
cluster = config["kubernetes"]["clusterLocatorMethods"][0]["clusters"][0]
check("the cluster is this one, read with the pod's own service account",
      cluster["url"] == "https://kubernetes.default.svc" and cluster["authProvider"] == "serviceAccount"
      and "serviceAccountToken" not in cluster)
check("no token Secret is created", all(o.get("type") != "kubernetes.io/service-account-token" for o in docs(BS / "k8s/backstage-rbac.yaml")))

print("== Postgres admits Backstage and nothing else ==")
pg = docs(BS / "k8s/postgres.yaml")
netpol = next(o for o in pg if o["kind"] == "NetworkPolicy")
pg_dep = next(o for o in pg if o["kind"] == "Deployment")
bs_dep = next(o for o in docs(BS / "k8s/backstage.yaml") if o["kind"] == "Deployment")
check("the policy selects the Postgres pod", netpol["spec"]["podSelector"]["matchLabels"].items() <= pg_dep["spec"]["template"]["metadata"]["labels"].items())
check("it governs ingress", netpol["spec"]["policyTypes"] == ["Ingress"])
peers = [p for rule in netpol["spec"]["ingress"] for p in rule["from"]]
check("its only peer is the Backstage pod, by label",
      len(peers) == 1 and set(peers[0]) == {"podSelector"}
      and peers[0]["podSelector"]["matchLabels"].items() <= bs_dep["spec"]["template"]["metadata"]["labels"].items())
check("the Backstage config points at that Service", config["backend"]["database"]["connection"]["host"]
      == next(o for o in pg if o["kind"] == "Service")["metadata"]["name"])

print("== the image is built on a Node whose node-fetch can read the API server ==")
df = (REPO / "images/watch-it-burn-backstage/packages/backend/Dockerfile").read_text(encoding="utf-8")
m = re.search(r"^FROM node:(\d+)\.(\d+)\.(\d+)-", df, re.M)
check("the base is pinned to a Node version", m is not None)
check("and it is 24.22 or later (24.17.0 fails every Kubernetes tab with 'Premature close')",
      m is not None and tuple(map(int, m.groups())) >= (24, 22, 0))
check("by digest too", re.search(r"^FROM node:\S+@sha256:[0-9a-f]{64}", df, re.M) is not None)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll Backstage checks passed.")
