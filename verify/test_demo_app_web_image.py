# ABOUTME: Static gate for #715: the five demo apps run lab-platform's web image by digest, set through each Application's
# ABOUTME: kustomize.images at the root's registry, reading a web.yaml that serves their page, and nothing pulls Docker Hub nginx.
"""Why this exists (#715, lab-platform#335).

The five demo apps pulled docker.io/library/nginx:1.27-alpine straight from Docker Hub: five pulls per cluster during
an event, on the shared anonymous quota. lab-platform's docs/supply-chain.md replaces them with its `web` image, a Go
static file server on base-static that reads one routes file, web.yaml, in place of an nginx config, and its
deploy/watch-it-burn/images.tsv pins the image by digest. A lab-platform image takes the registry the root passes down
(#622), and a demo app's directory is a plain manifest that cannot, so each Deployment names the kustomize image `web`
and its gitops/bootstrap/apps file sets it, as ai-layer.yaml does llm-guard (#652).

These checks hold what the files can show: the reference and its digest, the images.lock row, that the policy admits
it at ghcr.io and through an ECR cache, and the contract the image needs, read from lab-platform's cmd/web and
internal/webserve: NETWORK_BOUNDARY=sandbox (it refuses an all-interfaces bind without it), web.yaml at
/etc/web/web.yaml, the page under the file's root, and the port the file listens on. test_bootstrap_chart_render.py
builds each bundle as Argo CD does and checks the image the Deployment ends up with.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, REPO, kustomize_images, set_image  # noqa: E402
from registry_allowlist import allowed  # noqa: E402

DIGEST = "sha256:73cd15652cb8b8eb706bd43f8877541db7f7c9e5f810ef0739636a27fc34fbd9"
WANT = f"web={IMAGE_REGISTRY}/web@{DIGEST}"
REF = f"{LAB_PLATFORM_GHCR}/web@{DIGEST}"
CACHE = "123456789012.dkr.ecr.us-west-2.amazonaws.com/lp-shared/peopleforrester/lab-platform"
DEMO = ("hedgehog", "mantis-shrimp", "spider", "unicorn", "wombat")
# What the routes file says, the shape of lab-platform's internal/webserve/testdata/demo-app.web.yaml: the page and
# a health path, nothing else.
ROUTES = {"listen": ":8080", "root": "/srv/www",
          "routes": [{"path": "/", "file": "index.html"}, {"path": "/healthz", "text": "ok\n"}]}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def docs(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


web_files = []
for app in DEMO:
    name = f"demo-app-{app}"
    mdir = REPO / f"gitops/manifests/{name}"
    print(f"== {name} ==")
    application = docs(APPS / f"{name}.yaml")[0]
    images = ((application["spec"]["source"].get("kustomize") or {}).get("images")) or []
    check(f"its Application's kustomize.images is the one entry {WANT}", images == [WANT], str(images))
    entries = kustomize_images(application)
    check("it parses as `kustomize edit set image` reads it: name web, the registry path and the digest, no tag",
          entries == [{"name": "web", "newName": f"{IMAGE_REGISTRY}/web", "digest": DIGEST}], str(entries))

    kust = yaml.safe_load((mdir / "kustomization.yaml").read_text(encoding="utf-8"))
    check("kustomization.yaml lists the page, the Deployment and the Service",
          kust.get("resources") == ["configmap.yaml", "deployment.yaml", "service.yaml"], str(kust.get("resources")))
    check("and sets no images of its own that could override the Application's", "images" not in kust)
    gen = kust.get("configMapGenerator") or []
    check(f"it generates {name}-web in apps from web.yaml alone",
          [(g.get("name"), g.get("namespace"), g.get("files")) for g in gen] == [(f"{name}-web", "apps", ["web.yaml"])],
          str(gen))
    listed = set(kust.get("resources") or []) | {"kustomization.yaml", "web.yaml"}
    stray = sorted(p.name for p in mdir.iterdir() if p.name not in listed)
    check(f"no file in the directory is left out of the build {stray}", not stray)

    routes = yaml.safe_load((mdir / "web.yaml").read_text(encoding="utf-8"))
    check("web.yaml listens on :8080, roots at /srv/www and serves index.html at / and ok at /healthz",
          routes == ROUTES, str(routes))
    web_files.append((mdir / "web.yaml").read_text(encoding="utf-8"))

    page = next(d for d in docs(mdir / "configmap.yaml") if d.get("kind") == "ConfigMap")
    check(f"{page['metadata']['name']} carries the index.html web.yaml serves", "index.html" in (page.get("data") or {}))

    dep = next(d for d in docs(mdir / "deployment.yaml") if d.get("kind") == "Deployment")
    pod = dep["spec"]["template"]["spec"]
    cs = pod["containers"]
    check("one container, named by the kustomize image web alone", len(cs) == 1 and cs[0].get("image") == "web",
          str([c.get("image") for c in cs]))
    c = cs[0]
    check("set as Argo CD sets it, the container runs lab-platform's web by digest",
          set_image(c["image"], [{**e, "newName": e["newName"].replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR)}
                                 for e in entries]) == REF)
    env = {e["name"]: e.get("value") for e in c.get("env") or []}
    check("NETWORK_BOUNDARY=sandbox, without which the image refuses the all-interfaces bind web.yaml names",
          env.get("NETWORK_BOUNDARY") == "sandbox", str(env))
    check("no command or args override the image's entrypoint, which reads /etc/web/web.yaml",
          "command" not in c and "args" not in c and "WEB_CONFIG" not in env)
    port = int(ROUTES["listen"].rsplit(":", 1)[1])
    check(f"it declares the port web.yaml listens on, {port}, as http",
          c.get("ports") == [{"name": "http", "containerPort": port, "protocol": "TCP"}], str(c.get("ports")))
    for probe in ("readinessProbe", "livenessProbe"):
        check(f"its {probe} asks /healthz on http", (c.get(probe) or {}).get("httpGet") == {"path": "/healthz",
                                                                                             "port": "http"})
    vols = {v["name"]: (v.get("configMap") or {}).get("name") for v in pod.get("volumes") or []}
    mounts = {m["mountPath"]: m for m in c.get("volumeMounts") or []}
    check(f"{name}-html is mounted read-only at web.yaml's root",
          vols.get((mounts.get(ROUTES["root"]) or {}).get("name")) == f"{name}-html"
          and (mounts.get(ROUTES["root"]) or {}).get("readOnly") is True)
    check(f"{name}-web is mounted read-only at /etc/web, where the image reads web.yaml",
          vols.get((mounts.get("/etc/web") or {}).get("name")) == f"{name}-web"
          and (mounts.get("/etc/web") or {}).get("readOnly") is True)
    check("no volume is left over from nginx (cache, run, tmp)", set(vols) == {"html", "web"}, str(sorted(vols)))
    sc = c.get("securityContext") or {}
    check("the container writes nothing: read-only root filesystem, no privilege escalation, every capability dropped",
          sc.get("readOnlyRootFilesystem") is True and sc.get("allowPrivilegeEscalation") is False
          and sc.get("capabilities") == {"drop": ["ALL"]})
    check("the pod runs as a non-root uid", (pod.get("securityContext") or {}).get("runAsNonRoot") is True)

    svc = next(d for d in docs(mdir / "service.yaml") if d.get("kind") == "Service")
    check("its Service keeps port 80, which the console proxies to, and targets the container's port",
          [(p.get("port"), p.get("targetPort")) for p in svc["spec"]["ports"]] == [(80, port)],
          str(svc["spec"]["ports"]))

print("== the five read one routes file ==")
check("web.yaml is the same file in all five directories", len(set(web_files)) == 1)

print("== restrict-image-registries admits the reference, as it does lab-platform's llm-guard ==")
check(f"at the root's default registry: {REF}", allowed(REF))
check("through an ECR pull-through cache, a root's other imageRegistry", allowed(f"{CACHE}/web@{DIGEST}"))

print("== images.lock records it ==")
lock = {ln.split()[0]: ln.split()[1:] for ln in (REPO / "images.lock").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")}
check("the kustomize image name web has a row naming the reference and lab-platform's cmd/web",
      lock.get("web", [])[:2] == [REF, "repo:peopleforrester/lab-platform/cmd/web"], str(lock.get("web")))
check("no row is left for docker.io/library/nginx:1.27-alpine, which nothing pulls now",
      "docker.io/library/nginx:1.27-alpine" not in lock)

print("== nothing under gitops/ pulls docker.io/library/nginx ==")
files = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "gitops"], check=True,
                       capture_output=True).stdout.decode().split("\0")
pulls = []
for f in files:
    p = REPO / f
    if not f or not p.is_file():
        continue
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        code = line.split("#", 1)[0]
        if re.search(r"(docker\.io/)?library/nginx", code) or re.search(r"image:\s*['\"]?nginx[:@\s'\"]", code + " "):
            pulls.append(f"{f}:{i}")
check(f"no tracked file under gitops/ names Docker Hub nginx outside a comment {pulls}", not pulls)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All demo app web image checks passed.")
