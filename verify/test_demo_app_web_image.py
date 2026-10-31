# ABOUTME: Static gate for #668: the five demo apps run lab-platform's web:v1 by digest, set through each app file's
# ABOUTME: kustomize.images at the root's registry, on 8080 with NETWORK_BOUNDARY=sandbox and a web.yaml it can parse.
"""Why this exists (#668, lab-platform#278).

The demo apps moved from nginx to lab-platform's `web`, a Go static server that reads one routes file. A
lab-platform image takes the registry the root passes down (#622), and a plain directory source cannot take it, so
each `gitops/manifests/demo-app-<name>/` is a kustomization, its container names the kustomize image `web`, and its
app file sets that name. These checks hold what a file can show:
- the reference and its digest;
- that the kustomization lists every manifest in the directory, so a new file is not left out of the sync;
- the contract the image was measured with on 2026-10-31: NETWORK_BOUNDARY=sandbox (it refuses an all-interfaces
  bind without it), 8080, the page alone under /srv/www and the routes file at /etc/web/web.yaml;
- that web.yaml uses only fields lab-platform's parser accepts.
test_demo_app_web_serve.py runs the pinned image's binary on each app's web.yaml.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, IMAGE_REGISTRY, kustomize_images  # noqa: E402
from web_image import (DEMO_APPS, DIGEST, HOST_FIELDS, REPO, ROUTE_FIELDS, TOP_FIELDS, demo_dir,  # noqa: E402
                       demo_docs, demo_files)

WANT = f"web={IMAGE_REGISTRY}/web:v1@{DIGEST}"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def containers(doc: dict) -> list[dict]:
    spec = (((doc.get("spec") or {}).get("template") or {}).get("spec")) or {}
    return list(spec.get("containers") or []) + list(spec.get("initContainers") or [])


for app in DEMO_APPS:
    name = f"demo-app-{app}"
    d = demo_dir(app)
    print(f"== {name} ==")
    appfile = yaml.safe_load((APPS / f"{name}.yaml").read_text(encoding="utf-8"))
    src = appfile["spec"]["source"]
    check(f"its app file sources {d.relative_to(REPO)}", src.get("path") == str(d.relative_to(REPO)))
    images = (src.get("kustomize") or {}).get("images") or []
    check(f"kustomize.images is the one entry {WANT}", images == [WANT], str(images))
    check("it parses as `kustomize edit set image` reads it: name web, registry path, tag v1 and the digest",
          kustomize_images(appfile) == [{"name": "web", "newName": f"{IMAGE_REGISTRY}/web", "newTag": "v1",
                                         "digest": DIGEST}], str(kustomize_images(appfile)))

    kust = yaml.safe_load((d / "kustomization.yaml").read_text(encoding="utf-8"))
    on_disk = sorted(p.name for p in d.glob("*.yaml") if p.name != "kustomization.yaml")
    check(f"kustomization.yaml lists every manifest in the directory {on_disk}",
          sorted(kust.get("resources") or []) == on_disk, str(kust.get("resources")))
    check("the bundle sets no images, patches or name changes of its own",
          not set(kust) - {"apiVersion", "kind", "resources"}, str(sorted(kust)))

    docs = demo_docs(app)
    named = [(x["kind"], x["metadata"]["name"], c["name"]) for x in docs for c in containers(x)
             if c.get("image", "").split("@")[0].split(":")[0] == "web"]
    check(f"exactly one container is named by the kustomize image web: {name}'s own",
          named == [("Deployment", name, name)], str(named))
    others = [c.get("image") for x in docs for c in containers(x) if c.get("image") != "web"]
    check("no other container, and no nginx", not others, str(others))

    dep = next(x for x in docs if x["kind"] == "Deployment")
    pod = dep["spec"]["template"]["spec"]
    c = pod["containers"][0]
    env = {e["name"]: e for e in c.get("env") or []}
    check("NETWORK_BOUNDARY=sandbox, so web binds the pod's interfaces rather than exiting",
          env.get("NETWORK_BOUNDARY", {}).get("value") == "sandbox", str(env.get("NETWORK_BOUNDARY")))
    check("no command or args override the image's entrypoint", "command" not in c and "args" not in c)
    check("it listens on 8080", [p.get("containerPort") for p in c.get("ports") or []] == [8080], str(c.get("ports")))
    check("readiness asks / on 8080", (c.get("readinessProbe") or {}).get("httpGet") == {"path": "/", "port": 8080})
    check("liveness asks /healthz on 8080",
          (c.get("livenessProbe") or {}).get("httpGet") == {"path": "/healthz", "port": 8080})
    sc = pod.get("securityContext") or {}
    check("it runs as uid 1000, non-root", sc.get("runAsUser") == 1000 and sc.get("runAsNonRoot") is True)

    cm = next(x for x in docs if x["kind"] == "ConfigMap")
    vols = {v["name"]: (v.get("configMap") or {}) for v in pod.get("volumes") or []}
    mounts = {m["mountPath"]: m for m in c.get("volumeMounts") or []}
    check("the mounts are /srv/www and /etc/web and nothing nginx needed", set(mounts) == {"/srv/www", "/etc/web"},
          str(sorted(mounts)))
    for path, key in (("/srv/www", "index.html"), ("/etc/web", "web.yaml")):
        m = mounts.get(path) or {}
        v = vols.get(m.get("name"), {})
        check(f"{path} holds {key} alone, from {cm['metadata']['name']}, read-only",
              m.get("readOnly") is True and v.get("name") == cm["metadata"]["name"]
              and v.get("items") == [{"key": key, "path": key}], f"{m} {v}")

    files = demo_files(app)
    check("the ConfigMap holds index.html and web.yaml", set(files) == {"index.html", "web.yaml"}, str(sorted(files)))
    web = yaml.safe_load(files.get("web.yaml", "")) or {}
    check("web.yaml listens on :8080 with no TLS listener", web.get("listen") == ":8080" and "tls" not in web)
    check("web.yaml's root is /srv/www", web.get("root") == "/srv/www")
    check(f"web.yaml uses only top-level fields lab-platform's parser accepts {sorted(TOP_FIELDS)}",
          set(web) <= TOP_FIELDS, str(sorted(web)))
    routes = web.get("routes") or []
    bad = [r for r in routes if not set(r) <= ROUTE_FIELDS] + [h for h in web.get("hosts") or []
                                                               if not set(h) <= HOST_FIELDS]
    check("every route uses only fields the parser accepts", not bad, str(bad))
    check("the routes are / to index.html and /healthz answering ok",
          routes == [{"path": "/", "file": "index.html"}, {"path": "/healthz", "text": "ok\n"}], str(routes))

    svc = next(x for x in docs if x["kind"] == "Service")
    ports = svc["spec"]["ports"]
    check("the Service keeps port 80, which console.conf's host map names, and targets 8080",
          [(p.get("port"), p.get("targetPort")) for p in ports] == [(80, 8080)], str(ports))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All demo app web image checks passed.")
