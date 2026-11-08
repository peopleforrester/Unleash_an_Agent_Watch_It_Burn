# ABOUTME: Offline gate for #959: the Gateway API CRDs an Istio waypoint needs are vendored at v1.5.1, the version the
# ABOUTME: pinned Istio builds against, and the gateway-api Application installs them before Istio wherever Istio runs.
"""Why this exists (#959).

The C1 stage-2b fix (#727) builds its forced egress proxy as an Istio ambient egress waypoint, a Gateway of class
istio-waypoint (gitops/egress-waypoint/egress-waypoint.yaml, #861). On 2026-11-06 watch-it-burn-private had no
gateway.networking.k8s.io CRD, so the waypoint could not be applied. This holds the install offline:

- gitops/gateway-api/standard-install.yaml is the v1.5.1 release asset, byte for byte (its SHA-256 is the digest GitHub
  publishes for it; test_gateway_api_crds_upstream.py checks that against the release in the tools tier);
- it is the standard channel, v1.5.1 on every CRD, and serves the Gateway and GatewayClass versions the fix uses;
- v1.5.1 is the Gateway API Istio 1.30.4 builds against, so an Istio bump fails here until the pair is re-read;
- the gateway-api Application syncs the directory at the root's revision, server-side, in a wave before every Istio
  Application, on every profile that lists istio and on no other.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, REPO, REPO_URL, REVISION, all_profiles, app_names  # noqa: E402

DIR = REPO / "gitops/gateway-api"
BUNDLE = DIR / "standard-install.yaml"
VERSION = "v1.5.1"
# The digest GitHub publishes for the v1.5.1 release's standard-install.yaml (read 2026-11-06).
SHA256 = "751002b3b91a87f7ae3bd2517c79a47a8d7ed6702901808a1cf9bd97d284f9b8"
# Istio's pin -> the sigs.k8s.io/gateway-api version in istio/istio's go.mod at that tag (1.30.4: v1.5.1, read 2026-11-06).
ISTIO_GATEWAY_API = {"1.30.4": VERSION}
CRDS = ["backendtlspolicies", "gatewayclasses", "gateways", "grpcroutes", "httproutes", "listenersets",
        "referencegrants", "tlsroutes"]
FIX = REPO / "gitops/egress-waypoint/egress-waypoint.yaml"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== the vendored bundle is the v1.5.1 standard-channel release asset ==")
raw = BUNDLE.read_bytes()
digest = hashlib.sha256(raw).hexdigest()
check(f"{BUNDLE.relative_to(REPO)} has the release digest {SHA256[:12]}", digest == SHA256, f"got {digest}")
docs = [d for d in yaml.safe_load_all(raw.decode("utf-8")) if d]
crds = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "CustomResourceDefinition"}
check(f"it defines the eight standard-channel CRDs {CRDS}",
      sorted(crds) == [f"{n}.gateway.networking.k8s.io" for n in CRDS], f"{sorted(crds)}")
ann = {n: (d["metadata"].get("annotations") or {}) for n, d in crds.items()}
check(f"every CRD is bundle-version {VERSION}, standard channel",
      all(a.get("gateway.networking.k8s.io/bundle-version") == VERSION
          and a.get("gateway.networking.k8s.io/channel") == "standard" for a in ann.values()), f"{ann}")
others = sorted(f"{d['kind']}/{d['metadata']['name']}" for d in docs if d.get("kind") != "CustomResourceDefinition")
check("the rest is the release's safe-upgrades admission policy and its binding, and no workload",
      others == ["ValidatingAdmissionPolicy/safe-upgrades.gateway.networking.k8s.io",
                 "ValidatingAdmissionPolicyBinding/safe-upgrades.gateway.networking.k8s.io"], f"{others}")
check("no document in it names an image", b"image:" not in raw)


def served(name: str) -> set[str]:
    return {v["name"] for v in (crds.get(name) or {}).get("spec", {}).get("versions", []) if v.get("served")}


print("== the C1 fix's waypoint is a resource the bundle serves ==")
fix = [d for d in yaml.safe_load_all(FIX.read_text(encoding="utf-8")) if d]
gw = next((d for d in fix if d.get("kind") == "Gateway"), {})
group, _, version = str(gw.get("apiVersion", "")).partition("/")
check(f"egress-waypoint.yaml's Gateway is {gw.get('apiVersion')}, which gateways.gateway.networking.k8s.io serves",
      group == "gateway.networking.k8s.io" and version in served("gateways.gateway.networking.k8s.io"))
check("its class is istio-waypoint, which istiod creates once GatewayClass is served at v1",
      (gw.get("spec") or {}).get("gatewayClassName") == "istio-waypoint"
      and "v1" in served("gatewayclasses.gateway.networking.k8s.io"))

print("== the pair with Istio ==")
istio = [d for d in yaml.safe_load_all((APPS / "istio.yaml").read_text(encoding="utf-8")) if d]
pins = {str(d["spec"]["source"]["targetRevision"]) for d in istio if d["spec"]["source"].get("chart")}
pin = next(iter(pins)) if len(pins) == 1 else None
check(f"Istio is on one pin ({sorted(pins)}), and the CRDs are the Gateway API that pin builds against",
      pin is not None and ISTIO_GATEWAY_API.get(pin) == VERSION,
      f"Istio {pin}: read sigs.k8s.io/gateway-api in istio/istio's go.mod at that tag, then move {BUNDLE.name}, "
      "ISTIO_GATEWAY_API here and the upstream test together")

print("== the gateway-api Application ==")
kust = yaml.safe_load((DIR / "kustomization.yaml").read_text(encoding="utf-8"))
check("gitops/gateway-api/kustomization.yaml builds the bundle and nothing else",
      kust.get("resources") == ["standard-install.yaml"] and set(kust) == {"apiVersion", "kind", "resources"})
text = (APPS / "gateway-api.yaml").read_text(encoding="utf-8")
app = yaml.safe_load(text)
src = app["spec"]["source"]
check("it is one Application named gateway-api, in argocd",
      len([d for d in yaml.safe_load_all(text) if d]) == 1 and app["kind"] == "Application"
      and app["metadata"] == {**app["metadata"], "name": "gateway-api", "namespace": "argocd"})
check("it syncs gitops/gateway-api from this repo at the root's revision",
      src == {"repoURL": REPO_URL, "targetRevision": REVISION, "path": "gitops/gateway-api"})
check("server-side, since the HTTPRoute CRD nearly fills a client-side apply's annotation limit",
      "ServerSideApply=true" in app["spec"]["syncPolicy"].get("syncOptions", []))
wave = lambda d: int(d["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"])  # noqa: E731
check(f"its wave ({wave(app)}) is before every Istio Application's, so a fresh istiod starts with the CRDs present",
      all(wave(app) < wave(d) for d in istio), f"{[(d['metadata']['name'], wave(d)) for d in istio]}")
takers = [p for p in all_profiles() if "gateway-api" in app_names(p)]
meshed = [p for p in all_profiles() if "istio" in app_names(p)]
check(f"the profiles that list it are exactly those that list istio {meshed}", takers == meshed, f"{takers}")
check("attendee, admin and full are among them (#959)", {"attendee", "admin", "full"} <= set(takers))

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print(f"\nPASS: the Gateway API {VERSION} CRDs ship before Istio on every profile that runs it")
