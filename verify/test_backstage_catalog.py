# ABOUTME: Render gate for Backstage (#244): the catalog is valid and complete, every non-infrastructure pod is
# ABOUTME: found by exactly one entity, and the deployment, routing, RBAC and image base agree with each other.
"""Why this exists (#244).

The catalog is hand-written YAML that claims to describe the cluster, and the cluster changes underneath it.
A Component whose label selector names a label no pod carries shows an empty Kubernetes tab, which looks
exactly like a workload that is down. So the selectors are checked against the labels the manifests in this
repo actually put on each pod template, and every Deployment outside infrastructure must be claimed by
exactly one Component.

The real image was run against this catalog on 2026-10-24 (all 40 entities ingested with no processing
errors, guest sign-in, the Kubernetes tab against a stand-in API server), and the rebuilt
backstage-1.52.0-node24.22.2 image on 2026-11-01 (45 entities with the six Locations, 19 Components, no processing
errors, guest sign-in, the frontend served). Those runs need a container runtime; what is checked here is what can
drift without one.
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

print("== every source link points at a file this repo has ==")
SRC = re.compile(r"^url:https://github\.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/(?:tree|blob)/staging/(.+?)/?$")
gone = []
for (kind, name), e in entities.items():
    loc = e["metadata"].get("annotations", {}).get("backstage.io/source-location", "")
    m = SRC.match(loc)
    if m and not (REPO / m.group(1)).exists():
        gone.append(f"{kind}:{name} -> {m.group(1)}")
check(f"no source-location names a path that is not in the repo ({gone})", not gone)

print("== the request in #244 is all there ==")
# customer-stream is not here: #473 removed the app on 2026-10-26. The support desk (#640) and the weather feed
# (#642) arrived after the issue was written and are catalogued like the rest.
named = ["unicorn-party", "hedgehog-party", "wombat-party", "spider-party", "mantis-shrimp-party",
         "workshop-agent", "workshop-mcp", "evil-mcp", "guard-proxy", "llm-guard", "agentgateway", "console",
         "web-terminal", "fake-ticket", "weather-feed", "argocd-managed-app", "provisioning-app", "apex-router",
         "backstage"]
check("customer-stream, removed by #473, is not catalogued", ("component", "customer-stream") not in entities)
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
for d in sorted((REPO / "gitops/manifests").glob("demo-app-*")):
    for f in sorted(d.glob("*.yaml")):
        for o in docs(f):
            if o.get("kind") == "Deployment":
                pods.append((o["metadata"]["namespace"], o["metadata"]["name"], o["spec"]["template"]["metadata"]["labels"]))
# The AI layer and, since #707, the Agent's own bundle. Both set the namespace in their kustomization. Jobs (the
# ordering gates) are infrastructure and not catalogued.
for bundle in (REPO / "gitops/ai-layer", REPO / "gitops/workshop-agent"):
    kz = docs(bundle / "kustomization.yaml")[0]
    for f in kz["resources"]:
        for o in docs(bundle / f):
            if o.get("kind") == "Deployment":
                pods.append((kz["namespace"], o["metadata"]["name"], o["spec"]["template"]["metadata"]["labels"]))
            if o.get("kind") == "Agent":
                # kagent's operator creates the Deployment and labels the pod kagent=<agent name>.
                pods.append((kz["namespace"], o["metadata"]["name"], {"kagent": o["metadata"]["name"]}))
for o in docs(BS / "k8s/backstage.yaml") + docs(BS / "k8s/postgres.yaml"):
    if o.get("kind") == "Deployment":
        pods.append((o["metadata"]["namespace"], o["metadata"]["name"], o["spec"]["template"]["metadata"]["labels"]))
check(f"the scan found the workloads it should ({len(pods)})", len(pods) >= 18)
check("the Agent is among them", any(n == "workshop-agent" and "kagent" in lb for _, n, lb in pods))

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
sys.path.insert(0, str(REPO / "verify"))
from bootstrap_chart import all_profiles, app_names, profiles  # noqa: E402

app = docs(REPO / "gitops/bootstrap/apps/backstage.yaml")[0]
check("the Application deploys backstage/ at the root's revision",
      app["spec"]["source"]["path"] == "backstage" and app["spec"]["source"]["targetRevision"] == "{{ .Values.revision }}")
check("into the backstage namespace", app["spec"]["destination"]["namespace"] == "backstage")
check("which the namespaces app creates", any(o.get("kind") == "Namespace" and o["metadata"]["name"] == "backstage"
                                              for o in docs(REPO / "gitops/namespaces/namespaces.yaml")))
want_on = {"attendee", "full", "admin"}
on = {p for p in profiles() if "backstage" in app_names(p)}
check(f"of the profiles lab-platform presents, exactly {sorted(want_on)} list it ({sorted(on)})", on == want_on)
# local-inference (#394) is deploy-only and is the full build plus vllm-qwen3, so it takes what full takes.
deploy_only = sorted(set(all_profiles()) - set(profiles()))
check(f"each deploy-only profile {deploy_only} lists it as full does",
      all(("backstage" in app_names(p)) == ("backstage" in app_names("full")) for p in deploy_only))
check("templates and the test service are not deployed", all("templat" not in r for r in kust["resources"]))

print("== backstage-<cluster> reaches the Service, and the fleet publishes the same hosts the console serves ==")
conf = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")
served = re.search(r"server_name ~\^\(([^)]*)\)-\[a-z0-9-\]\+", conf).group(1).split("|")
fleet = re.search(r'readonly WIB_SERVICE_HOSTS="([^"]*)"', (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")).group(1).split()
check(f"console server_name and fleet.sh WIB_SERVICE_HOSTS list the same services ({served} vs {fleet})", sorted(served) == sorted(fleet))
check("backstage is one of them", "backstage" in served)
check("the backstage host, on both domains (#651), proxies to the backstage Service on 80",
      re.search(r'"~\^backstage-\[a-z0-9-\]\+\\\.\(\?:agenticburn\\\.com\|burritobot\\\.co\)\$"\s+'
                r'http://backstage\.backstage\.svc\.cluster\.local:80;', conf) is not None)
svc = next(o for o in docs(BS / "k8s/backstage.yaml") if o["kind"] == "Service")
check("that Service exists and listens on 80", svc["metadata"]["name"] == "backstage" and svc["spec"]["ports"][0]["port"] == 80)
for page in ("gitops/ai-layer/web/platform.html", "gitops/ai-layer/web/lab.html"):
    check(f"{page} links backstage-<cluster>", 'data-svc="backstage"' in (REPO / page).read_text(encoding="utf-8"))
for term in ("gitops/ai-layer/web-terminal/entrypoint.sh", "images/web-terminal/entrypoint.sh"):
    check(f"{term}: the terminal's platform command lists it",
          "backstage-${_h}" in (REPO / term).read_text(encoding="utf-8"))
ident = (REPO / "infra/datadog-cluster-identity.sh").read_text(encoding="utf-8")
m = re.search(r'^readonly IDENTITY_ONLY_NAMESPACES="([^"]*)"', ident, re.M)
check("cluster-identity is written to the backstage namespace, which names the cluster on every Kubernetes tab",
      m is not None and "backstage" in m.group(1).split())
nm = re.search(r'^readonly NAMESPACES="([^"]*)"', ident, re.M)
check("and datadog-admin-secret is not: the portal is public",
      nm is not None and "backstage" not in nm.group(1).split())

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

print("== Postgres runs lab-platform's mirror/ copy, not Docker Hub's (#714) ==")
from bootstrap_chart import APPS, IMAGE_REGISTRY, kustomize_images  # noqa: E402
from mirror_copies import COPIES  # noqa: E402

pg_image = pg_dep["spec"]["template"]["spec"]["containers"][0]["image"]
check(f"postgres.yaml names the kustomize image postgres, which the Application sets ({pg_image})", pg_image == "postgres")
entries = kustomize_images(yaml.safe_load((APPS / "backstage.yaml").read_text(encoding="utf-8")))
copy = next(c for c in COPIES if "/library/postgres:" in c.upstream)
check(f"the backstage Application sets it, alone, to {copy.path} by its digest, at the root's registry",
      entries == [{"name": "postgres", "newName": f"{IMAGE_REGISTRY}/{copy.path.rsplit(':', 1)[0]}",
                   "newTag": copy.tag, "digest": copy.digest}])

print("== the image is built on a Node whose node-fetch can read the API server ==")
df = (REPO / "images/watch-it-burn-backstage/packages/backend/Dockerfile").read_text(encoding="utf-8")
m = re.search(r"^FROM node:(\d+)\.(\d+)\.(\d+)-", df, re.M)
check("the base is pinned to a Node version", m is not None)
check("and it is 24.22 or later (24.17.0 fails every Kubernetes tab with 'Premature close')",
      m is not None and tuple(map(int, m.groups())) >= (24, 22, 0))
check("by digest too", re.search(r"^FROM node:\S+@sha256:[0-9a-f]{64}", df, re.M) is not None)

print("== the Deployment runs our image, by digest, under a tag that names what is inside ==")
APP = REPO / "images/watch-it-burn-backstage"
bs_version = __import__("json").loads((APP / "backstage.json").read_text(encoding="utf-8"))["version"]
image = bs_dep["spec"]["template"]["spec"]["containers"][0]["image"]
im = re.fullmatch(r"ghcr\.io/peopleforrester/watch-it-burn:backstage-(\d+\.\d+\.\d+)-node(\d+\.\d+\.\d+)@sha256:[0-9a-f]{64}", image)
check(f"ghcr.io/peopleforrester/watch-it-burn:backstage-<backstage>-node<node>@sha256:... ({image})", im is not None)
check(f"the tag's Backstage version is backstage.json's ({bs_version})", im is not None and im.group(1) == bs_version)
check("the tag's Node version is the Dockerfile's base", im is not None and m is not None and im.group(2) == ".".join(m.groups()))
policy = (REPO / "policies/kyverno/verify-image-signatures.yaml").read_text(encoding="utf-8")
check("verify-image-signatures holds it to the workshop key (its glob covers watch-it-burn:*)",
      '- glob: "ghcr.io/peopleforrester/watch-it-burn*"' in policy and image.startswith("ghcr.io/peopleforrester/watch-it-burn:"))
lock_rows = [l.split() for l in (REPO / "images.lock").read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
check("images.lock records it with its build context",
      any(r[0] == image and r[2] == "repo:peopleforrester/Unleash_an_Agent_Watch_It_Burn/images/watch-it-burn-backstage" for r in lock_rows))

print("== the two Dependabot advisories are out of the lockfile ==")
# GHSA-xcx6-jx8p-x3h5 (@azure/msal-node >= 5.0.0-beta.0 < 7.1.0) and GHSA-86w9-cpqp-85rv / CVE-2026-85393 (node-forge
# <= 1.4.0, fixed in 1.4.1 per forge's CHANGELOG). Every resolved copy must be at or above the fix.
lock = (APP / "yarn.lock").read_text(encoding="utf-8")


def resolved(pkg: str) -> list[tuple[int, ...]]:
    vs = re.findall(r'^"' + re.escape(pkg) + r'@npm:[^\n]*\n  version: (\d+)\.(\d+)\.(\d+)', lock, re.M)
    return [tuple(map(int, v)) for v in vs]


for pkg, floor in (("@azure/msal-node", (7, 1, 0)), ("node-forge", (1, 4, 1))):
    vs = resolved(pkg)
    check(f"{pkg}: every resolved copy is at or above {'.'.join(map(str, floor))} ({vs})", bool(vs) and all(v >= floor for v in vs))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll Backstage checks passed.")
