# ABOUTME: Render gate for #252: every generated ConfigMap and Secret in gitops/ai-layer carries a content
# ABOUTME: hash, every workload reference resolves to it, and a content change changes the workload spec.
#
# Why. A change to lab.html, console.conf or proxy.py used to reach a running cluster only after someone
# deleted the pod by hand (four consoles cycled by hand on 2026-09-06). With the hash suffix, kustomize
# rewrites the references it owns, the Deployment spec changes with the content, and Argo CD rolls the
# pod. This test is what keeps that automatic: it fails if the hash is ever disabled again, and it fails
# if any reference is left pointing at a bare generator name.
import pathlib, re, shutil, subprocess, sys, tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
AI_LAYER = REPO / "gitops/ai-layer"
failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


def render(path):
    out = subprocess.run(["kubectl", "kustomize", str(path)], capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def generator_names(path):
    k = yaml.safe_load((path / "kustomization.yaml").read_text())
    return [g["name"] for key in ("configMapGenerator", "secretGenerator") for g in k.get(key, [])]


def references(doc):
    """Every configMap/secret name a workload spec refers to, wherever kustomize would rewrite it."""
    names = set()

    def walk(o):
        if isinstance(o, dict):
            for key in ("configMap", "secret", "configMapRef", "secretRef", "configMapKeyRef", "secretKeyRef"):
                v = o.get(key)
                if isinstance(v, dict) and "name" in v:
                    names.add(v["name"])
            if "secretName" in o and isinstance(o["secretName"], str):
                names.add(o["secretName"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return names


docs = render(AI_LAYER)
gens = generator_names(AI_LAYER)
hashed = re.compile(r"^(" + "|".join(map(re.escape, gens)) + r")-[a-z0-9]{10}$")
rendered_gen_names = [d["metadata"]["name"] for d in docs if d["kind"] in ("ConfigMap", "Secret")
                      and any(d["metadata"]["name"] == g or d["metadata"]["name"].startswith(g + "-") for g in gens)]

print("== generated objects carry a content hash ==")
check("every generated ConfigMap/Secret name ends in a kustomize hash",
      rendered_gen_names and all(hashed.match(n) for n in rendered_gen_names))
check(f"all {len(gens)} generators are rendered", len(rendered_gen_names) == len(gens))

print("== every workload reference resolves to a hashed object ==")
workloads = [d for d in docs if d["kind"] in ("Deployment", "DaemonSet", "StatefulSet", "Job", "CronJob")]
bare = sorted({n for d in workloads for n in references(d) if n in gens})
check("no workload references a bare generator name", not bare)
dangling = sorted({n for d in workloads for n in references(d) if hashed.match(n) and n not in rendered_gen_names})
check("no workload references a hash that is not rendered", not dangling)

print("== a content change changes the workload spec ==")
with tempfile.TemporaryDirectory(dir=REPO) as tmp:
    copy = pathlib.Path(tmp) / "ai-layer"
    shutil.copytree(AI_LAYER, copy)
    lab = copy / "web/lab.html"
    lab.write_text(lab.read_text() + "\n<!-- rollout probe -->\n")
    before = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "console")["spec"]["template"]
    after = next(d for d in render(copy) if d["kind"] == "Deployment" and d["metadata"]["name"] == "console")["spec"]["template"]
    check("editing lab.html changes the console pod template (so Argo CD rolls it)", before != after)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All ai-layer rollout checks passed.")
