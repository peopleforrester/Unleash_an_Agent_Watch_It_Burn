# ABOUTME: Renders each Application the lab-bootstrap root ships, every source as Argo CD would, and lists its images.
# ABOUTME: Shared by test_no_docker_hub_render.py (#805) and test_images_lock_render.py (#603), which both need it.
"""Each apps/ file is rendered alone by the root, with imageRegistry at its default, and each of the Application's
sources is then rendered as Argo CD would: an upstream or in-repo chart with the root's helm values, a kustomization
built by kustomize, a directory as its files. A source's documents come back as parsed YAML.

An apps/ file can hold more than one Application (istio.yaml holds five), and each is rendered. A Helm test hook
(helm.sh/hook: test) is not a pull: Argo CD does not run Helm test hooks. Images an operator has compiled in, such
as the Datadog agent's, appear in no render."""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import chart_fetch  # noqa: E402
from bootstrap_chart import APPS, CHART, REPO, kustomize_images, set_image  # noqa: E402
from docker_hub import image_fields  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"
Check = Callable[[str, bool, str], None]


def load_all(text: str) -> list:
    """Charts emit tags the safe loader rejects; only the shape matters here."""
    return [d for d in yaml.load_all(text, Loader=yaml.BaseLoader) if d]


def test_hook(doc) -> bool:
    hooks = ((doc.get("metadata") or {}).get("annotations") or {}).get("helm.sh/hook", "")
    return "test" in [h.strip() for h in hooks.split(",")] or "test-success" in hooks or "test-failure" in hooks


def pulled_images(docs: list, images: list) -> Iterator[tuple[str, str, str]]:
    """(kind/name, where, reference) for each image field Argo CD would hand the cluster in these documents, with the
    Application's kustomize.images applied. A Helm test hook's are left out, and so is a ConfigMap's: its data is
    what a program reads, not what a kubelet pulls. istiod's sidecar-injector ConfigMap names `proxyv2`, which the
    injector joins to registry.istio.io/release only for a sidecar or a waypoint, and the mesh here runs neither."""
    for d in docs:
        if not isinstance(d, dict) or test_hook(d) or d.get("kind") == "ConfigMap":
            continue
        obj = f"{d.get('kind')}/{(d.get('metadata') or {}).get('name')}"
        for where, ref in image_fields(d):
            yield obj, where, set_image(ref, images)


class Renderer:
    """Renders apps/ files with the given helm and kubectl, reporting each step through check(name, ok, detail)."""

    def __init__(self, helm: str, kubectl: str, check: Check):
        self.helm, self.kubectl, self.check = helm, kubectl, check
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="app-render-"))
        self.pulled: dict[tuple[str, str, str], pathlib.Path] = {}
        self.charts = 0

    def close(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    @staticmethod
    def apps() -> list[str]:
        return sorted(p.stem for p in APPS.glob("*.yaml"))

    def root_render(self, name: str) -> list[dict] | None:
        """Every Application the root renders from this apps/ file: istio.yaml holds five."""
        r = subprocess.run([self.helm, "template", "lab-bootstrap", str(CHART), "--set", f"revision={COMMIT}",
                            "--set", f"apps={{{name}}}"], capture_output=True, text=True)
        self.check(f"{name}: the root renders it alone", r.returncode == 0, r.stderr.strip()[:200])
        if r.returncode:
            return None
        apps = [d for d in yaml.safe_load_all(r.stdout) if d and d.get("kind") == "Application"]
        self.check(f"{name}: the root renders an Application from it", bool(apps), "")
        return apps or None

    def upstream_chart(self, src: dict) -> pathlib.Path | str:
        """The app's chart, from the host artifact cache by its charts.lock sum, pulled once on a miss (#1028,
        #1118); on failure, the error, in Helm's words where Helm failed."""
        key = (src["repoURL"], src["chart"], str(src["targetRevision"]))
        if key not in self.pulled:
            try:
                self.pulled[key] = chart_fetch.pull(self.helm, *key)
            except chart_fetch.ChartFetchError as e:
                return str(e)
        return self.pulled[key]

    def helm_render(self, name: str, app: dict, src: dict, chart: pathlib.Path, n: int) -> list | None:
        helm = src.get("helm") or {}
        args = []
        for vf in helm.get("valueFiles", []):
            args += ["-f", str(REPO / vf.removeprefix("$values/"))]
        for key in ("values", "valuesObject"):
            if helm.get(key) is not None:
                f = self.work / f"{name.replace('/', '-')}-{n}-{key}.yaml"
                f.write_text(helm[key] if isinstance(helm[key], str) else yaml.safe_dump(helm[key]), encoding="utf-8")
                args += ["-f", str(f)]
        r = subprocess.run([self.helm, "template", helm.get("releaseName", app["metadata"]["name"]), str(chart),
                            "-n", app["spec"]["destination"]["namespace"], "--include-crds", *args],
                           capture_output=True, text=True)
        self.check(f"{name}: chart {src.get('chart') or src['path']} renders with the root's values",
                   r.returncode == 0, r.stderr.strip()[:300])
        return load_all(r.stdout) if r.returncode == 0 else None

    def source_docs(self, name: str, app: dict, src: dict, n: int) -> list | None:
        """One source of the Application, as the documents Argo CD would apply; None (and a FAIL) if it cannot be."""
        if "chart" in src:
            chart = self.upstream_chart(src)
            if not isinstance(chart, pathlib.Path):
                self.check(f"{name}: chart {src['chart']} {src['targetRevision']} is fetched", False, chart)
                return None
            self.charts += 1
            return self.helm_render(name, app, src, chart, n)
        if "path" not in src:
            return []  # a $values ref source: it holds value files, which the chart source reads
        path = REPO / src["path"]
        if (path / "Chart.yaml").exists():
            self.charts += 1
            return self.helm_render(name, app, src, path, n)
        if (path / "kustomization.yaml").exists():
            r = subprocess.run([self.kubectl, "kustomize", str(path)], capture_output=True, text=True)
            self.check(f"{name}: {src['path']} builds with kustomize", r.returncode == 0, r.stderr.strip()[:300])
            return load_all(r.stdout) if r.returncode == 0 else None
        files = sorted(path.rglob("*.yaml") if (src.get("directory") or {}).get("recurse") else path.glob("*.yaml"))
        docs = []
        for f in files:
            try:
                docs += load_all(f.read_text(encoding="utf-8"))
            except yaml.YAMLError as e:
                self.check(f"{name}: {f.relative_to(REPO)} parses", False, str(e)[:200])
                return None
        return docs

    def app(self, name: str) -> list[tuple[list, list]] | None:
        """(kustomize.images, documents) for each source of each Application an apps/ file holds; None when any step
        failed."""
        apps = self.root_render(name)
        if apps is None:
            return None
        out = []
        for app in apps:
            spec = app["spec"]
            label = name if len(apps) == 1 else f"{name}/{app['metadata']['name']}"
            for n, src in enumerate([spec["source"]] if "source" in spec else spec["sources"]):
                docs = self.source_docs(label, app, src, n)
                if docs is None:
                    return None
                out.append((kustomize_images(app), docs))
        return out
