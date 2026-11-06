# ABOUTME: Render gate for what the Istio ambient mesh carries (#471): the console and guard-proxy are enrolled and
# ABOUTME: nothing else is, no Ingress rule refuses their mesh traffic, and the pages say exactly that.
"""Why this exists (#238, #471).

For months the mesh enrolled nothing while the tour said it "encrypts all traffic between containers inside
the cluster, automatically". #482 made the tour admit that, and on #471 Michael chose to keep Istio and
enroll an application in it (question 947). The console and guard-proxy pods are enrolled: that hop carries
every chat message, and neither pod sits behind an Ingress NetworkPolicy. These checks hold that state:

- exactly those two pod templates carry the ambient label, and no namespace does;
- no Ingress NetworkPolicy selects an enrolled pod without admitting HBONE port 15008, which is how mesh
  traffic arrives (agentgateway and workshop-agent are behind port-exact rules, so they stay out);
- agent's PeerAuthentication is PERMISSIVE, because the console is an ip-target NLB that the room reaches
  from outside the mesh;
- the tour, and C1's README, say no more than that.

The facts behind docs/research/2026-10-24-istio-ambient-evaluation.md (shared ServiceAccounts, the tool
pod's reach to /toggle, what a waypoint would need) are checked further down. If one fails, the matching
section of the evaluation is out of date. Re-read it then.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
EVALUATION = "docs/research/2026-10-24-istio-ambient-evaluation.md"
LABEL = "istio.io/dataplane-mode"
RESOURCES = "gitops/ai-layer/resources.yaml"
ENROLLED = ("console", "guard-proxy")  # Deployment names in RESOURCES (#471, question 947)
HBONE = 15008

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


def docs(rel: str) -> list[dict]:
    return [d for d in yaml.safe_load_all((REPO / rel).read_text()) if isinstance(d, dict)]


def one(found: list[dict], kind: str, name: str) -> dict:
    hit = [d for d in found if d.get("kind") == kind and d.get("metadata", {}).get("name") == name]
    check(f"{kind}/{name} is declared exactly once", len(hit) == 1)
    return hit[0] if hit else {}


def has_key(node, key: str) -> bool:
    if isinstance(node, dict):
        return key in node or any(has_key(v, key) for v in node.values())
    if isinstance(node, list):
        return any(has_key(v, key) for v in node)
    return False


AI = docs(RESOURCES) + docs("gitops/workshop-agent/agent.yaml")  # #707

# --- enrolment: the console and guard-proxy, nothing else ------------------------------------------------
# A text scan, not a YAML walk: Helm templates and shell scripts do not parse as YAML, and a label set in
# one of them enrols a workload just the same. Comment lines are exempt.
carriers = []
for root in ("gitops", "security", "policies", "infra", "challenges", "scripts", "teardown", "verify"):
    for path in sorted((REPO / root).rglob("*")):
        if not path.is_file() or path.suffix not in (".yaml", ".yml", ".sh", ".tpl", ".tf"):
            continue
        live = [ln for ln in path.read_text(errors="replace").splitlines() if not ln.lstrip().startswith("#")]
        if any(LABEL in ln for ln in live):
            carriers.append(str(path.relative_to(REPO)))
check(f"only {RESOURCES} sets {LABEL}", carriers == [RESOURCES],
      f"{carriers}: a new workload may be in the mesh; check its Ingress rules and the tour")

enrolled_labels: dict[str, dict] = {}
for d in AI:
    labels = d.get("spec", {}).get("template", {}).get("metadata", {}).get("labels") or {}
    if LABEL in labels:
        enrolled_labels[d["metadata"]["name"]] = labels
check("the console and guard-proxy pod templates, and only they, are enrolled",
      sorted(enrolled_labels) == sorted(ENROLLED)
      and all(v[LABEL] == "ambient" for v in enrolled_labels.values()), f"{enrolled_labels}")
ns_docs = docs("gitops/namespaces/namespaces.yaml")
check("no Namespace object carries the label, so enrolment stays per pod",
      not any(has_key(d, LABEL) for d in ns_docs) and len(ns_docs) > 0)

# Mesh traffic reaches an enrolled pod on HBONE port 15008 (istio.io/latest/docs/ambient/usage/networkpolicy/).
# An Ingress rule that admits only the app's own ports refuses it, so no such rule may select an enrolled pod.
policies = [(str(p.relative_to(REPO)), d) for p in sorted((REPO / "policies/network-policies").rglob("*.yaml"))
            for d in docs(str(p.relative_to(REPO)))]
policies += [("gitops/ai-layer/chat-path-ingress.yaml", d) for d in docs("gitops/ai-layer/chat-path-ingress.yaml")]
blocking = []
for rel, d in policies:
    if d.get("kind") != "NetworkPolicy" or d.get("metadata", {}).get("namespace", "agent") != "agent":
        continue
    spec = d.get("spec", {})
    if "Ingress" not in spec.get("policyTypes", []):
        continue
    want = (spec.get("podSelector") or {}).get("matchLabels") or {}
    admits = any(not r.get("ports") or any(p.get("port") == HBONE for p in r["ports"]) for r in spec.get("ingress", []))
    for name, labels in enrolled_labels.items():
        if all(labels.get(k) == v for k, v in want.items()) and not admits:
            blocking.append(f"{rel}:{d['metadata']['name']} selects {name}")
check(f"no Ingress NetworkPolicy in agent selects an enrolled pod without admitting {HBONE}", not blocking,
      f"{blocking}")

# The pages say what is enrolled (#482 made the tour stop claiming more; #471 enrolled the hop).
lab = (REPO / "gitops/ai-layer/web/lab.html").read_text()
mesh_li = re.search(r'<li data-full><a href="https://istio\.io/[^"]*"[^>]*>Istio ambient mesh</a>(.*?)</li>', lab, re.S)
tour = " ".join(re.sub(r"<[^>]+>", "", mesh_li.group(1)).split()) if mesh_li else ""
check("the tour names the enrolled hop and how to see it, and claims nothing wider",
      "console" in tour and "guard-proxy" in tour and "mutual TLS" in tour
      and f"kubectl get pods -n agent -L {LABEL}" in tour and "connection complete" in tour
      and "encrypts all traffic" not in tour and "no namespace is enrolled" not in tour, tour or "no Istio tour bullet")
c1 = (REPO / "challenges/c1-exfil-s3/README.md").read_text()
check("C1's README does not list mesh mTLS as a control", not re.search(r"(?i)istio.*mtls|mtls.*istio", c1))

# --- section 2.1: the tool pod can reach guard-proxy's /toggle; the public /a2a/ route is gone (#481) ------
intra = one(docs("policies/network-policies/per-namespace/agent-allow-intra-namespace.yaml"),
            "NetworkPolicy", "agent-allow-intra-namespace").get("spec", {})
egress = intra.get("egress", [])
check("C1's agent-allow-intra-namespace lets every agent pod reach every agent pod on any port",
      intra.get("podSelector") == {} and any(r.get("to") == [{"podSelector": {}}] and not r.get("ports")
                                             for r in egress), f"{egress}")
beat = (REPO / "verify/beat-02.sh").read_text()
check("the guard toggles have been called over the Service, from another pod, with no credential",
      'PROXY="http://guard-proxy.${NS}:8080"' in beat and '"${PROXY}/toggle?' in beat)
conf = (REPO / "gitops/ai-layer/console.conf").read_text()
a2a = re.search(r"(?m)^\s*location\s+[^{]*/a2a", conf)
check("console's public /a2a/ route is gone (#481), so /toggle is reachable only from inside the cluster",
      a2a is None, f"{a2a.group(0).strip() if a2a else ''}: update section 2.1 and recommendation 4 of {EVALUATION}")

# --- section 2.3: identities are shared ---------------------------------------------------------------------


def sa(kind: str, name: str) -> str:
    spec = one(AI, kind, name).get("spec", {})
    if kind == "Agent":
        return spec.get("declarative", {}).get("deployment", {}).get("serviceAccountName") or "default"
    return spec.get("template", {}).get("spec", {}).get("serviceAccountName") or "default"


for name in ("console", "llm-guard", "evil-mcp-shim"):
    account = sa("Deployment", name)
    check(f"{name} runs as the namespace default ServiceAccount", account == "default",
          f"{account}: the identity table in section 2.3 of {EVALUATION} has changed")
check("workshop-agent runs as agent-sa, and workshop-mcp as its own workshop-mcp (#553)",
      sa("Agent", "workshop-agent") == "agent-sa" and sa("Deployment", "workshop-mcp") == "workshop-mcp",
      f"the identity table in section 2.3 of {EVALUATION} has changed")
check("guard-proxy runs as guard-proxy-reader", sa("Deployment", "guard-proxy") == "guard-proxy-reader")

# --- section 3: why agent is PERMISSIVE and apps is not enrolled ---------------------------------------------
pa = {d["metadata"]["namespace"]: d for d in docs("security/istio/peer-authentication.yaml")
      if d.get("kind") == "PeerAuthentication"}
check("agent's mTLS mode is PERMISSIVE, so callers outside the mesh still reach the enrolled pods",
      pa.get("agent", {}).get("spec", {}).get("mtls", {}).get("mode") == "PERMISSIVE")
check("no PeerAuthentication names a namespace with nothing enrolled", sorted(pa) == ["agent"], f"{sorted(pa)}")
kust = yaml.safe_load((REPO / "gitops/ai-layer/kustomization.yaml").read_text())
svc = one(AI, "Service", "console")
ann = svc.get("metadata", {}).get("annotations", {})
check("the console is an ip-target NLB in agent, so its traffic arrives from outside the mesh",
      kust.get("namespace") == "agent" and svc.get("spec", {}).get("type") == "LoadBalancer"
      and ann.get("service.beta.kubernetes.io/aws-load-balancer-nlb-target-type") == "ip")
deny = one(docs("policies/network-policies/default-deny.yaml"), "NetworkPolicy", "default-deny-all")
check("apps is default-deny on ingress", "Ingress" in deny.get("spec", {}).get("policyTypes", []))
ingress = one(docs("policies/network-policies/per-namespace/apps-allow-ingress.yaml"),
              "NetworkPolicy", "allow-ingress-controller").get("spec", {}).get("ingress", [])
ports = {p.get("port") for r in ingress for p in r.get("ports", [])}
check("apps ingress admits neither HBONE 15008 nor the probe SNAT address, so apps stays out of the mesh",
      HBONE not in ports and not any("169.254.7.127" in str(r) for r in ingress), f"ports={sorted(ports)}")

# --- section 2.4: what a waypoint challenge would still need ------------------------------------------------
# The first step, the Gateway API CRDs, is done (#959): gitops/gateway-api is the only place that defines them, and
# section 2.4 says so. verify/test_gateway_api_crds.py holds the install itself.
gw_api = sorted(str(p.relative_to(REPO)) for root in ("gitops", "infra") for p in (REPO / root).rglob("*")
                if p.is_file() and re.search(r"(?m)^  group: gateway\.networking\.k8s\.io$", p.read_text(errors="replace")))
check("the Gateway API CRDs a waypoint needs are defined in gitops/gateway-api alone",
      gw_api == ["gitops/gateway-api/standard-install.yaml"], f"{gw_api}: update section 2.4 of {EVALUATION}")
section = (REPO / EVALUATION).read_text(encoding="utf-8")
check("section 2.4 marks the Gateway API CRD step done and names the gateway-api Application",
      "~~Install the Gateway API CRDs~~ (done in #959)" in section and "the `gateway-api` Application" in section,
      f"update section 2.4 of {EVALUATION}")
role = one(AI, "ClusterRole", "console-terminal").get("rules", [])
istio_write = [r for r in role if any(g in ("security.istio.io", "*") for g in r.get("apiGroups", []))
               and set(r.get("verbs", [])) & {"create", "update", "patch"}]
check("the student's terminal cannot write Istio security policy", not istio_write, f"{istio_write}")

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("\nPASS: the mesh carries the console-to-guard-proxy hop and nothing else, and the pages say so")
