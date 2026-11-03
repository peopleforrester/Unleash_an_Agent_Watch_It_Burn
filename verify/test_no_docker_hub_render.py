# ABOUTME: Renders every source of every Application the lab-bootstrap root ships, Helm charts included, and fails
# ABOUTME: on any image Argo CD would hand the cluster from Docker Hub, by name or by having no registry (#714, #805).
# SUITE: e2e (needs helm, kubectl kustomize, and the network for each app's upstream chart)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Why this exists (#805, from #714).

#714 removes every Docker Hub pull: a cluster pulls only from ghcr.io copies. A chart app names its images in the
chart, not here, so a file sweep cannot see them, and test_enforce_floor's registry check leaves chart apps out. A
chart bump that brings a docker.io/ image, or a bare one, would pass every offline test and be pulled anonymously
from Docker Hub on the first node of a fresh cluster.

This asks Helm and kustomize what each app hands Argo CD. Each apps/ file is rendered alone by the root, with
imageRegistry at its default, and each of the Application's sources is then rendered as Argo CD would: an
upstream or in-repo chart with the root's helm values, a kustomization with the Application's kustomize.images, a
directory as its files. In what comes out, it judges every image field (pod specs, and custom resources such as
KubeArmorConfig and Prometheus that hold an image for an operator to run) and every string a container's args, env
and command hand a program, so an operator flag naming docker.io is caught too.

A Helm test hook (helm.sh/hook: test) is left out: Argo CD does not run Helm test hooks, so nothing pulls its image.
Images an operator has compiled in, such as the Datadog agent's, appear in no render; the live check in decisions.md
(#714, Not yet run on a cluster) lists what a cluster actually pulls. test_no_docker_hub.py holds the files here.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, CHART, REPO, kustomize_images, set_image  # noqa: E402
from docker_hub import docker_hub, image_fields, names_hub  # noqa: E402

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

COMMIT = "0123456789abcdef0123456789abcdef01234567"
WORK = pathlib.Path(tempfile.mkdtemp(prefix="no-docker-hub-"))
CONTAINER_LISTS = ("containers", "initContainers", "ephemeralContainers")
pulled: dict[tuple[str, str, str], pathlib.Path] = {}


def load_all(text: str) -> list:
    """Charts emit tags the safe loader rejects; only the shape matters here."""
    return [d for d in yaml.load_all(text, Loader=yaml.BaseLoader) if d]


def test_hook(doc) -> bool:
    hooks = ((doc.get("metadata") or {}).get("annotations") or {}).get("helm.sh/hook", "")
    return "test" in [h.strip() for h in hooks.split(",")] or "test-success" in hooks or "test-failure" in hooks


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
        if not isinstance(d, dict) or test_hook(d):
            continue
        obj = f"{d.get('kind')}/{(d.get('metadata') or {}).get('name')}"
        for where, ref in image_fields(d):
            ref = set_image(ref, images)
            if docker_hub(ref):
                bad.append(f"{obj}: {where}: {ref}")
        bad += [f"{obj}: {where}: {s[:120]}" for where, s in container_strings(d) if names_hub(s)]
    return bad


def root_render(name: str) -> dict | None:
    r = subprocess.run([HELM, "template", "lab-bootstrap", str(CHART), "--set", f"revision={COMMIT}",
                        "--set", f"apps={{{name}}}"], capture_output=True, text=True)
    check(f"{name}: the root renders it alone", r.returncode == 0, r.stderr.strip()[:200])
    if r.returncode:
        return None
    return next((d for d in yaml.safe_load_all(r.stdout) if d and d.get("kind") == "Application"), None)


def upstream_chart(src: dict) -> pathlib.Path | str:
    """The app's chart, pulled once into WORK; on failure, Helm's error."""
    key = (src["repoURL"], src["chart"], str(src["targetRevision"]))
    if key not in pulled:
        repo, chart, ver = key
        dest = WORK / f"{chart}-{len(pulled)}"
        ref = ([f"oci://{repo.removeprefix('oci://').rstrip('/')}/{chart}"] if not repo.startswith("http")
               else [chart, "--repo", repo])
        r = subprocess.run([HELM, "pull", *ref, "--version", ver, "--untar", "--untardir", str(dest)],
                           capture_output=True, text=True)
        if r.returncode:
            return r.stderr.strip()[:200]
        pulled[key] = dest / chart
    return pulled[key]


def helm_render(name: str, app: dict, src: dict, chart: pathlib.Path, n: int) -> list | None:
    helm = src.get("helm") or {}
    args = []
    for vf in helm.get("valueFiles", []):
        args += ["-f", str(REPO / vf.removeprefix("$values/"))]
    for key in ("values", "valuesObject"):
        if helm.get(key) is not None:
            f = WORK / f"{name}-{n}-{key}.yaml"
            f.write_text(helm[key] if isinstance(helm[key], str) else yaml.safe_dump(helm[key]), encoding="utf-8")
            args += ["-f", str(f)]
    r = subprocess.run([HELM, "template", helm.get("releaseName", app["metadata"]["name"]), str(chart),
                        "-n", app["spec"]["destination"]["namespace"], "--include-crds", *args],
                       capture_output=True, text=True)
    check(f"{name}: chart {src.get('chart') or src['path']} renders with the root's values", r.returncode == 0,
          r.stderr.strip()[:300])
    return load_all(r.stdout) if r.returncode == 0 else None


def source_docs(name: str, app: dict, src: dict, n: int) -> list | None:
    """One source of the Application, as the documents Argo CD would apply; None (and a FAIL) if it cannot be."""
    if "chart" in src:
        chart = upstream_chart(src)
        if not isinstance(chart, pathlib.Path):
            check(f"{name}: chart {src['chart']} {src['targetRevision']} is fetched", False, chart)
            return None
        return helm_render(name, app, src, chart, n)
    if "path" not in src:
        return []  # a $values ref source: it holds value files, which the chart source reads
    path = REPO / src["path"]
    if (path / "Chart.yaml").exists():
        return helm_render(name, app, src, path, n)
    if (path / "kustomization.yaml").exists():
        r = subprocess.run([KUBECTL, "kustomize", str(path)], capture_output=True, text=True)
        check(f"{name}: {src['path']} builds with kustomize", r.returncode == 0, r.stderr.strip()[:300])
        return load_all(r.stdout) if r.returncode == 0 else None
    files = sorted(path.rglob("*.yaml") if (src.get("directory") or {}).get("recurse") else path.glob("*.yaml"))
    docs = []
    for f in files:
        try:
            docs += load_all(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            check(f"{name}: {f.relative_to(REPO)} parses", False, str(e)[:200])
            return None
    return docs


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

apps = sorted(p.stem for p in APPS.glob("*.yaml"))
print(f"== every source of every Application, {len(apps)} apps/ files ==")
charts = 0
for name in apps:
    app = root_render(name)
    if app is None:
        continue
    spec = app["spec"]
    images = kustomize_images(app)
    bad: list[str] = []
    for n, src in enumerate([spec["source"]] if "source" in spec else spec["sources"]):
        docs = source_docs(name, app, src, n)
        if docs is None:
            bad = None
            break
        charts += "chart" in src or ("path" in src and (REPO / src["path"] / "Chart.yaml").exists())
        bad += hub_refs(docs, images)
    if bad is not None:
        check(f"{name}: nothing it renders pulls from Docker Hub", not bad, "\n      ".join([""] + bad[:20]))
# Fifteen apps/ files source a chart today; a reading far below that means the chart sources stopped being read.
check(f"the chart sources are read ({charts} rendered)", charts >= 15)

shutil.rmtree(WORK, ignore_errors=True)
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("No Application renders a Docker Hub image.")
