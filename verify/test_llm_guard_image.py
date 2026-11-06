# ABOUTME: Static gate for #652 and #895: the llm-guard Deployment runs lab-platform's llm-guard:v1, rebuilt under
# ABOUTME: lab-platform#341, by digest through the ai-layer Application's kustomize.images at the root's registry.
"""Why this exists (#652, #719, then #895).

lab-platform builds, reads back and signs the LLM Guard API image from pinned inputs, so this repo runs its
`llm-guard:v1` in place of the watch-it-burn build (#652). That v1 carried only the prompt-injection model, and #455's
BanTopics scanner needs the zero-shot model too, so question 1041 (#719) ran llm-guard-cpu-offline's cpu.5 until
lab-platform#341 posted a signed rebuild. It did on 2026-11-05: v1 at sha256:46b3d202... bakes both models, at the
directories cpu.5 used, and carries OpenTelemetry past GHSA-xcq7-p3pf-p88h, and #895 moved the guard back to it. A
lab-platform image takes the registry the root passes down (#622), and resources.yaml is a plain kustomize manifest
that cannot, so the container names the kustomize image `llm-guard` and gitops/bootstrap/apps/ai-layer.yaml sets it.
These checks hold the parts a file can show: the reference and its digest, that the placeholder names this container
alone (kustomize matches on the name), and the contract lab-platform's image was verified with: NETWORK_BOUNDARY=sandbox
(its entrypoint binds loopback without it), one worker, the scanners ConfigMap at /home/user/app/config, AUTH_TOKEN,
uid 1000, port 8000, /healthz and the prompt-injection model directory. test_llm_guard_bantopics_image.py holds the
zero-shot one, and test_bootstrap_chart_render.py builds the bundle as Argo CD does and checks the image the
Deployment ends up with.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, IMAGE_REGISTRY, REPO, kustomize_images  # noqa: E402

# lab-platform#341's rebuild of llm-guard:v1, signed with the workshop key on 2026-11-05 (#895).
DIGEST = "sha256:46b3d20203147d36d2e023c01bfd889f27f1c3900246777abe48cb16d0f3881a"
WANT = f"llm-guard={IMAGE_REGISTRY}/llm-guard:v1@{DIGEST}"
AI = REPO / "gitops/ai-layer"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def containers(doc: dict) -> list[dict]:
    spec = (((doc.get("spec") or {}).get("template") or {}).get("spec")) or {}
    return list(spec.get("containers") or []) + list(spec.get("initContainers") or [])


kust = yaml.safe_load((AI / "kustomization.yaml").read_text(encoding="utf-8"))
docs = [d for f in kust["resources"] for d in yaml.safe_load_all((AI / f).read_text(encoding="utf-8")) if d]
app = yaml.safe_load((APPS / "ai-layer.yaml").read_text(encoding="utf-8"))

print("== the ai-layer Application sets llm-guard to lab-platform's image, by digest ==")
images = ((app["spec"]["source"].get("kustomize") or {}).get("images")) or []
check(f"kustomize.images is the one entry {WANT}", images == [WANT], str(images))
check("it parses as `kustomize edit set image` reads it: name, registry path, tag v1 and the digest",
      kustomize_images(app) == [{"name": "llm-guard", "newName": f"{IMAGE_REGISTRY}/llm-guard", "newTag": "v1",
                                 "digest": DIGEST}], str(kustomize_images(app)))
check("the bundle sets no images of its own that could override it", "images" not in kust)

print("== the placeholder names the llm-guard container and nothing else ==")
named = [(d["kind"], d["metadata"]["name"], c["name"]) for d in docs for c in containers(d)
         if c.get("image", "").split("@")[0].split(":")[0] == "llm-guard"]
check("exactly one container is named by the kustomize image llm-guard: the llm-guard Deployment's llm-guard-api",
      named == [("Deployment", "llm-guard", "llm-guard-api")], str(named))
old = [str(p.relative_to(REPO)) for p in sorted((REPO / "gitops").rglob("*.yaml"))
       if "watch-it-burn:llm-guard" in p.read_text(encoding="utf-8")]
check(f"no file under gitops/ still names a watch-it-burn llm-guard build, cpu.5 included {old}", not old)

print("== the Deployment keeps the contract lab-platform's image was verified with ==")
dep = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "llm-guard")
pod = dep["spec"]["template"]["spec"]
c = next(x for x in pod["containers"] if x["name"] == "llm-guard-api")
env = {e["name"]: e for e in c.get("env") or []}
check("APP_WORKERS is 1: one API process, so the two classifiers are loaded once, not once per worker",
      env.get("APP_WORKERS", {}).get("value") == "1", str(env.get("APP_WORKERS")))
check("NETWORK_BOUNDARY=sandbox, so the entrypoint binds the pod's address rather than loopback",
      env.get("NETWORK_BOUNDARY", {}).get("value") == "sandbox", str(env.get("NETWORK_BOUNDARY")))
check("AUTH_TOKEN comes from the llm-guard-auth Secret",
      (env.get("AUTH_TOKEN", {}).get("valueFrom") or {}).get("secretKeyRef") == {"name": "llm-guard-auth", "key": "token"})
check("no command or args override the image's entrypoint", "command" not in c and "args" not in c)
check("it listens on 8000", c.get("ports") == [{"name": "http", "containerPort": 8000}])
for probe in ("startupProbe", "readinessProbe"):
    check(f"its {probe} asks /healthz on that port",
          (c.get(probe) or {}).get("httpGet") == {"path": "/healthz", "port": "http"})
sc = pod.get("securityContext") or {}
check("it runs as uid and gid 1000, the image's user", sc.get("runAsUser") == 1000 and sc.get("runAsGroup") == 1000
      and sc.get("runAsNonRoot") is True)
vols = {v["name"]: v for v in pod.get("volumes") or []}
mounts = {m["mountPath"]: m for m in c.get("volumeMounts") or []}
cfg = mounts.get("/home/user/app/config") or {}
check("the llm-guard-scanners ConfigMap is mounted read-only at /home/user/app/config",
      cfg.get("readOnly") is True and (vols.get(cfg.get("name"), {}).get("configMap") or {}).get("name")
      == "llm-guard-scanners")
cm = next(d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "llm-guard-scanners")
scanners = yaml.safe_load(cm["data"]["scanners.yml"])
pi = next((s for s in scanners["input_scanners"] if s["type"] == "PromptInjection"), {})
check("PromptInjection loads the classifier from /home/user/models/prompt-injection, where the image has it",
      (pi.get("params") or {}).get("model_path") == "/home/user/models/prompt-injection")

print("== images.lock records the digest the Application pins (#730) ==")
lock = {ln.split()[0]: ln.split()[1:] for ln in (REPO / "images.lock").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")}
check("the kustomize image name llm-guard has a row naming lab-platform's reference at that digest",
      lock.get("llm-guard", [])[:2] == [f"ghcr.io/peopleforrester/lab-platform/llm-guard@{DIGEST}",
                                        "repo:peopleforrester/lab-platform/deploy/images"], str(lock.get("llm-guard")))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All LLM Guard image checks passed.")
