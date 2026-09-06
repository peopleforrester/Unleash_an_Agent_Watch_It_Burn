# ABOUTME: Render gate for the Kyverno resource-limits floor: every container of every workload that any
# ABOUTME: Helm or kustomize Application ships must carry CPU and memory limits, or Enforce denies it.
#
# Why. require-resource-limits is Enforce on the full profile from bootstrap. Three times on 2026-09-06 a
# chart shipped a container without limits and the whole app was denied: Prometheus (operator, exporters,
# config-reloader), the Datadog agents, then cert-manager's webhook and cainjector, which took the console
# certificate and every full-profile console down with it. Kyverno decides this at admission from the
# rendered manifests, so the same decision can be made here, before a cluster exists.
import json, pathlib, subprocess, sys, tempfile

import yaml


def load_all(text):
    """Tolerant loader: charts emit tags the safe loader rejects; only the shape matters here."""
    return [d for d in yaml.load_all(text, Loader=yaml.BaseLoader) if d]

REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []
WORKLOADS = ("Deployment", "DaemonSet", "StatefulSet", "Job", "CronJob")
# Argo CD hook Jobs and CRD-driven workloads the OPERATORS create are checked where they are declared;
# the operator-created ones (Prometheus StatefulSet, Datadog agents) are covered by their CRs' values.


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


def helm_render(app):
    src = app["spec"].get("source") or app["spec"]["sources"][0]
    chart, repo, ver = src["chart"], src["repoURL"], str(src["targetRevision"])
    helm = src.get("helm", {})
    with tempfile.TemporaryDirectory() as tmp:
        vals = pathlib.Path(tmp) / "values.yaml"
        if "valuesObject" in helm:
            vals.write_text(yaml.safe_dump(helm["valuesObject"]))
        elif "values" in helm:
            vals.write_text(helm["values"])
        else:
            vals.write_text("{}")
        extra = []
        for vf in helm.get("valueFiles", []):
            extra += ["-f", str(REPO / vf.replace("$values/", ""))]
        cmd = ["helm", "template", app["metadata"]["name"], chart, "--repo", repo, "--version", ver,
               "-n", app["spec"]["destination"].get("namespace", "default"), "-f", str(vals), "--include-crds"] + extra
        if repo.startswith("oci://") or "ghcr.io" in repo:
            oci = repo if repo.startswith("oci://") else f"oci://{repo}"
            cmd = ["helm", "template", app["metadata"]["name"], f"{oci.rstrip('/')}/{chart}", "--version", ver,
                   "-n", app["spec"]["destination"].get("namespace", "default"), "-f", str(vals)] + extra
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr.strip().splitlines()[-1][:160] if r.stderr.strip() else "helm failed"
        return load_all(r.stdout), None


def missing_limits(docs):
    out = []
    for d in docs:
        if not isinstance(d, dict) or d.get("kind") not in WORKLOADS:
            continue
        spec = d["spec"]
        tpl = spec.get("jobTemplate", {}).get("spec", {}).get("template") if d["kind"] == "CronJob" else spec.get("template")
        if not tpl:
            continue
        for c in tpl.get("spec", {}).get("containers", []):
            lim = (c.get("resources") or {}).get("limits") or {}
            if not (lim.get("cpu") and lim.get("memory")):
                out.append(f"{d['kind']}/{d['metadata']['name']}:{c['name']}")
    return out


apps = []
for f in sorted((REPO / "gitops/apps").glob("*.yaml")):
    for d in yaml.safe_load_all(f.read_text()):
        if isinstance(d, dict) and d.get("kind") == "Application":
            apps.append((f.name, d))

print("== Helm chart applications ==")
for fname, app in apps:
    src = app["spec"].get("source") or app["spec"]["sources"][0]
    if "chart" not in src:
        continue
    docs, err = helm_render(app)
    if docs is None:
        check(f"{fname}: renders ({err})", False)
        continue
    miss = missing_limits(docs)
    check(f"{fname}: every container has cpu+memory limits" + (f" MISSING {miss}" if miss else ""), not miss)

print("== kustomize and plain-directory applications ==")
for fname, app in apps:
    src = app["spec"].get("source") or app["spec"]["sources"][0]
    if "chart" in src or "path" not in src:
        continue
    path = REPO / src["path"]
    if (path / "kustomization.yaml").exists():
        r = subprocess.run(["kubectl", "kustomize", str(path)], capture_output=True, text=True)
        docs = load_all(r.stdout) if r.returncode == 0 else None
    else:
        docs = []
        for mf in sorted(path.rglob("*.yaml")) if src.get("directory", {}).get("recurse") else sorted(path.glob("*.yaml")):
            try:
                docs += [d for d in load_all(mf.read_text()) if isinstance(d, dict)]
            except yaml.YAMLError:
                pass
    if docs is None:
        check(f"{fname}: renders", False)
        continue
    miss = missing_limits(docs)
    check(f"{fname}: every container has cpu+memory limits" + (f" MISSING {miss}" if miss else ""), not miss)

print("== every image comes from a registry restrict-image-registries allows ==")
import fnmatch
pol = next(d for d in yaml.safe_load_all((REPO / "policies/kyverno/restrict-image-registries.yaml").read_text()) if d)
pattern = pol["spec"]["rules"][0]["validate"]["pattern"]["spec"]["containers"][0]["image"]
globs = [g.strip() for g in pattern.split("|")]


def image_ok(img):
    ref = img if "/" in img.split(":")[0] else f"docker.io/library/{img}"
    return any(fnmatch.fnmatch(ref, g) for g in globs)


def images(docs):
    out = []
    for d in docs:
        if not isinstance(d, dict) or d.get("kind") not in WORKLOADS:
            continue
        spec = d["spec"]
        tpl = spec.get("jobTemplate", {}).get("spec", {}).get("template") if d["kind"] == "CronJob" else spec.get("template")
        for c in (tpl or {}).get("spec", {}).get("containers", []) + (tpl or {}).get("spec", {}).get("initContainers", []):
            if c.get("image"):
                out.append(c["image"])
    return out


for fname, app in apps:
    src = app["spec"].get("source") or app["spec"]["sources"][0]
    if "chart" in src or "path" not in src:
        continue
    path = REPO / src["path"]
    docs = []
    for mf in sorted(path.rglob("*.yaml")):
        try:
            docs += [d for d in load_all(mf.read_text()) if isinstance(d, dict)]
        except yaml.YAMLError:
            pass
    bad = sorted({i for i in images(docs) if not image_ok(i)})
    check(f"{fname}: images from allowed registries" + (f" BAD {bad}" if bad else ""), not bad)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All enforce-floor checks passed.")
