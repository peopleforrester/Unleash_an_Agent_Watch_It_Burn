# ABOUTME: Renders every source of every Application the lab-bootstrap root ships, Helm charts included, and fails
# ABOUTME: on any image Argo CD would hand the cluster from Docker Hub, by name or by having no registry (#714, #805).
# SUITE: e2e (needs helm, kubectl kustomize, and the network for each app's upstream chart)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Why this exists (#805, from #714).

#714 removes every Docker Hub pull: a cluster pulls only from ghcr.io copies. A chart app names its images in the
chart, not here, so a file sweep cannot see them, and test_enforce_floor's registry check leaves chart apps out. A
chart bump that brings a docker.io/ image, or a bare one, would pass every offline test and be pulled anonymously
from Docker Hub on the first node of a fresh cluster.

This asks Helm and kustomize what each app hands Argo CD, through verify/app_render.py. Each apps/ file is rendered alone by the root, with
imageRegistry at its default, and each of the Application's sources is then rendered as Argo CD would: an
upstream or in-repo chart with the root's helm values, a kustomization with the Application's kustomize.images, a
directory as its files. In what comes out, it judges every image field (pod specs, and custom resources such as
KubeArmorConfig and Prometheus that hold an image for an operator to run) and every string a container's args, env
and command hand a program, so an operator flag naming docker.io is caught too.

A Helm test hook (helm.sh/hook: test) is left out: Argo CD does not run Helm test hooks, so nothing pulls its image.
A ConfigMap's image fields are left out too: istiod's injector names `proxyv2`, which it joins to its hub only for a
sidecar or a waypoint. Every Application of an apps/ file is read, so istio.yaml's istiod, CNI and ztunnel are (#603).
Images an operator has compiled in, such as the Datadog agent's, appear in no render; the live check in decisions.md
(#714, Not yet run on a cluster) lists what a cluster actually pulls. test_no_docker_hub.py holds the files here.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from app_render import Renderer, load_all, pulled_images, test_hook  # noqa: E402
from docker_hub import docker_hub, names_hub  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


HELM = shutil.which("helm")
KUBECTL = shutil.which("kubectl")
if not HELM or not KUBECTL:
    print("FAIL: helm and kubectl must be on PATH (run through verify/run-e2e-tools.sh, which puts the pinned ones "
          "first)", file=sys.stderr)
    sys.exit(1)
version = subprocess.run([HELM, "version", "--short"], capture_output=True, text=True).stdout.strip()
check(f"helm is the pinned v4.2.1 ({version})", version.startswith("v4.2.1"))

CONTAINER_LISTS = ("containers", "initContainers", "ephemeralContainers")


def container_strings(node, where: str = ""):
    """(where, string) for each string in a container's args, command and env values, anywhere in a document."""
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{where}.{k}" if where else str(k)
            if k in CONTAINER_LISTS and isinstance(v, list):
                for i, c in enumerate(v):
                    if not isinstance(c, dict):
                        continue
                    at = f"{here}[{i}]({c.get('name', '?')})"
                    for key in ("args", "command"):
                        for s in c.get(key) or []:
                            if isinstance(s, str):
                                yield f"{at}.{key}", s
                    for e in c.get("env") or []:
                        if isinstance(e, dict) and isinstance(e.get("value"), str):
                            yield f"{at}.env.{e.get('name')}", e["value"]
            yield from container_strings(v, here)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from container_strings(v, f"{where}[{i}]")


def hub_refs(docs: list, images: list) -> list[str]:
    """What in these rendered documents pulls from Docker Hub, each as kind/name: where: reference."""
    bad = []
    for d in docs:
        bad += [f"{obj}: {where}: {ref}" for obj, where, ref in pulled_images([d], images) if docker_hub(ref)]
        if isinstance(d, dict) and not test_hook(d):
            obj = f"{d.get('kind')}/{(d.get('metadata') or {}).get('name')}"
            bad += [f"{obj}: {where}: {s[:120]}" for where, s in container_strings(d) if names_hub(s)]
    return bad


print("== the judgement, on documents shaped like a render ==")
FIXTURE = load_all("""
kind: Deployment
metadata: {name: web}
spec: {template: {spec: {containers: [{name: web, image: "nginx:1.27"}]}}}
---
kind: Deployment
metadata: {name: operator}
spec:
  template:
    spec:
      initContainers: [{name: init, image: "ghcr.io/x/init:1"}]
      containers:
      - name: operator
        image: "quay.io/x/operator:1"
        args: ["--reloader=docker.io/x/reloader:1"]
        env: [{name: RELATED_IMAGE_AGENT, value: "index.docker.io/x/agent:1"}]
---
kind: KubeArmorConfig
metadata: {name: cr}
spec: {kubearmorImage: {image: "kubearmor/kubearmor:stable"}}
---
kind: Pod
metadata: {name: test-connection, annotations: {helm.sh/hook: test}}
spec: {containers: [{name: wget, image: busybox}]}
---
kind: Deployment
metadata: {name: clean}
spec: {template: {spec: {containers: [{name: c, image: "ghcr.io/peopleforrester/lab-platform/mirror/x:1-abc"}]}}}
""")
found = hub_refs(FIXTURE, [])
check("a bare image, an operator flag, an env image and a custom resource's image are each found", found == [
    "Deployment/web: spec.template.spec.containers[0].image: nginx:1.27",
    "Deployment/operator: spec.template.spec.containers[0](operator).args: --reloader=docker.io/x/reloader:1",
    "Deployment/operator: spec.template.spec.containers[0](operator).env.RELATED_IMAGE_AGENT: index.docker.io/x/agent:1",
    "KubeArmorConfig/cr: spec.kubearmorImage.image: kubearmor/kubearmor:stable"], str(found))
check("a kustomize.images entry is judged as Argo CD deploys it, not as named",
      hub_refs(FIXTURE[:1], [{"name": "nginx", "newName": "ghcr.io/x/nginx", "newTag": "1.27"}]) == [])
INJECTOR = load_all("""
kind: ConfigMap
metadata: {name: istio-sidecar-injector}
data: {values: '{"global": {"hub": "registry.istio.io/release", "proxy": {"image": "proxyv2"}}}'}
""")
check("a ConfigMap's values string is data, not a pull (istiod's injector names proxyv2)", hub_refs(INJECTOR, []) == [])

renderer = Renderer(HELM, KUBECTL, check)
apps = renderer.apps()
print(f"== every source of every Application, {len(apps)} apps/ files ==")
for name in apps:
    rendered = renderer.app(name)
    if rendered is None:
        continue
    bad = [b for images, docs in rendered for b in hub_refs(docs, images)]
    check(f"{name}: nothing it renders pulls from Docker Hub", not bad, "\n      ".join([""] + bad[:20]))
# Fifteen apps/ files source a chart today; a reading far below that means the chart sources stopped being read.
check(f"the chart sources are read ({renderer.charts} rendered)", renderer.charts >= 15)

renderer.close()
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("No Application renders a Docker Hub image.")
