# ABOUTME: Render gate for the facts the Istio ambient evaluation (#238) rests on: the mesh enrols nothing,
# ABOUTME: the tool pod can reach guard-proxy's /toggle, and why enrolling `agent` is not a one-label change.
"""Why this exists (#238).

The tour used to say the mesh "encrypts all traffic between containers inside the cluster, automatically",
and no file has ever enrolled a namespace (#482 reworded it). docs/research/2026-10-24-istio-ambient-evaluation.md weighs keeping
the five Istio apps for a challenge against dropping them. Its answer depends on the facts below:

- nothing is enrolled, so today the mesh changes no traffic;
- the agent's tool pod can call guard-proxy, whose /toggle switches the guards. The console's public
  /a2a/ route used to forward every guard-proxy path too; #481 removed it, so the tool pod's in-cluster
  call is the path a waypoint policy would close;
- the ServiceAccounts are shared, so an identity rule cannot single out the console or tell the agent
  from its tool pod;
- STRICT plus an ip-target NLB, the apps ingress ports and the missing Gateway API CRDs are why enrolling
  is a build, not a label.

If any check here fails, the matching section of the evaluation is out of date. Re-read it then.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
EVALUATION = "docs/research/2026-10-24-istio-ambient-evaluation.md"
LABEL = "istio.io/dataplane-mode"

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


# --- section 1: no namespace or workload is enrolled in ambient ---------------------------------------
# A text scan, not a YAML walk: Helm templates and shell scripts do not parse as YAML, and a label set in
# one of them enrols a namespace just the same. Comment lines are exempt, which is where
# peer-authentication.yaml's own "verify-at-build" note says the label still has to be added.
enrolled = []
for root in ("gitops", "security", "policies", "infra", "challenges", "scripts", "teardown", "verify"):
    for path in sorted((REPO / root).rglob("*")):
        if not path.is_file() or path.suffix not in (".yaml", ".yml", ".sh", ".tpl", ".tf"):
            continue
        live = [ln for ln in path.read_text(errors="replace").splitlines() if not ln.lstrip().startswith("#")]
        if any(LABEL in ln for ln in live):
            enrolled.append(str(path.relative_to(REPO)))
check(f"no manifest or script sets {LABEL}", not enrolled,
      f"{enrolled}: the mesh may now capture traffic; re-read sections 1, 3 and 4 of {EVALUATION}")
ns_docs = docs("gitops/namespaces/namespaces.yaml")
check("no Namespace object carries the label", not any(has_key(d, LABEL) for d in ns_docs) and len(ns_docs) > 0)

# While nothing is enrolled, the student pages say so (#482, question 702): the tour no longer claims the mesh
# encrypts traffic and hands the student the command that shows the label is missing, and C1's README no longer
# lists mesh mTLS as one of its controls. Enrolling a namespace fails the check above first; rewrite both then.
lab = (REPO / "gitops/ai-layer/web/lab.html").read_text()
mesh_li = re.search(r'<li data-full><a href="https://istio\.io/[^"]*"[^>]*>Istio ambient mesh</a>(.*?)</li>', lab, re.S)
tour = " ".join(mesh_li.group(1).split()) if mesh_li else ""
check("the tour says the mesh is installed but enrols no namespace",
      "no namespace is enrolled" in tour and "not encrypting anything" in tour
      and f"kubectl get ns -L {LABEL}" in tour and "encrypts all traffic" not in tour, tour or "no Istio tour bullet")
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
AI = docs("gitops/ai-layer/resources.yaml") + docs("gitops/workshop-agent/agent.yaml")  # #707


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

# --- section 3: why enrolling `agent` and `apps` is a build, not a label --------------------------------------
pa = {d["metadata"]["namespace"]: d for d in docs("security/istio/peer-authentication.yaml")
      if d.get("kind") == "PeerAuthentication"}
check("STRICT mTLS is what agent would get on enrolment",
      pa.get("agent", {}).get("spec", {}).get("mtls", {}).get("mode") == "STRICT")
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
check("apps ingress admits neither HBONE 15008 nor the probe SNAT address", 15008 not in ports and
      not any("169.254.7.127" in str(r) for r in ingress), f"ports={sorted(ports)}")

# --- section 2.4: what a waypoint challenge would still need ------------------------------------------------
gw_api = [str(p.relative_to(REPO)) for root in ("gitops", "infra") for p in (REPO / root).rglob("*")
          if p.is_file() and "gateway.networking.k8s.io" in p.read_text(errors="replace")]
check("nothing installs the Gateway API CRDs a waypoint needs", not gw_api,
      f"{gw_api}: update section 2.4 of {EVALUATION}")
role = one(AI, "ClusterRole", "console-terminal").get("rules", [])
istio_write = [r for r in role if any(g in ("security.istio.io", "*") for g in r.get("apiGroups", []))
               and set(r.get("verbs", [])) & {"create", "update", "patch"}]
check("the student's terminal cannot write Istio security policy", not istio_write, f"{istio_write}")

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("\nPASS: the mesh enrols nothing, and the facts behind the #238 evaluation still hold")
