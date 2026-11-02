# ABOUTME: Static gate for #719 (question 1041): the llm-guard Deployment runs llm-guard-cpu-offline's cpu.5 by digest, set
# ABOUTME: through the ai-layer Application's kustomize.images, with the contract that image was built for.
"""Why this exists (#652, then #719).

#652 moved the guard to lab-platform's llm-guard:v1, which carries only the prompt-injection model. #455's BanTopics
scanner needs the zero-shot model too, and question 1041 (#719) moved the guard to llm-guard-cpu-offline's
llm-guard-0.3.16-cpu.5, which bakes both and is signed with the workshop key, until lab-platform#341 posts a signed
rebuild with the same model path. The container still names the kustomize image `llm-guard` and
gitops/bootstrap/apps/ai-layer.yaml sets it, so that return is one entry. cpu.5 is a public watch-it-burn image, so the
entry names ghcr.io literally rather than the root's imageRegistry, which is lab-platform's (#622). These checks hold
the reference and its digest, that the placeholder names this container alone (kustomize matches on the name), and
the contract cpu.5 was built for (images/llm-guard/Dockerfile at 31962f2): one worker, the scanners ConfigMap at
/home/user/app/config, AUTH_TOKEN, uid 1000, port 8000, /healthz and the two model directories. NETWORK_BOUNDARY,
which only lab-platform's entrypoint reads, stays for the return. test_bootstrap_chart_render.py builds the bundle as
Argo CD does and checks the image the Deployment ends up with.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, REPO, kustomize_images  # noqa: E402

DIGEST = "sha256:4c66fd0f0846c2c829952e562fd076f37ca8f7e41fb6ecfbb5a1f28cb8579791"
NAME = "ghcr.io/peopleforrester/watch-it-burn"
TAG = "llm-guard-0.3.16-cpu.5"
WANT = f"llm-guard={NAME}:{TAG}@{DIGEST}"
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

print("== the ai-layer Application sets llm-guard to llm-guard-cpu-offline's cpu.5, by digest ==")
images = ((app["spec"]["source"].get("kustomize") or {}).get("images")) or []
check(f"kustomize.images is the one entry {WANT}", images == [WANT], str(images))
check(f"it parses as `kustomize edit set image` reads it: name, {NAME}, tag {TAG} and the digest",
      kustomize_images(app) == [{"name": "llm-guard", "newName": NAME, "newTag": TAG, "digest": DIGEST}],
      str(kustomize_images(app)))
check("the bundle sets no images of its own that could override it", "images" not in kust)

print("== the placeholder names the llm-guard container and nothing else ==")
named = [(d["kind"], d["metadata"]["name"], c["name"]) for d in docs for c in containers(d)
         if c.get("image", "").split("@")[0].split(":")[0] == "llm-guard"]
check("exactly one container is named by the kustomize image llm-guard: the llm-guard Deployment's llm-guard-api",
      named == [("Deployment", "llm-guard", "llm-guard-api")], str(named))
named_elsewhere = [str(p.relative_to(REPO)) for p in sorted((REPO / "gitops").rglob("*.yaml"))
                   if "watch-it-burn:llm-guard" in p.read_text(encoding="utf-8") and p != APPS / "ai-layer.yaml"]
check(f"no other file under gitops/ names a watch-it-burn llm-guard build {named_elsewhere}", not named_elsewhere)

print("== the Deployment keeps the contract cpu.5 was built for ==")
dep = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "llm-guard")
pod = dep["spec"]["template"]["spec"]
c = next(x for x in pod["containers"] if x["name"] == "llm-guard-api")
env = {e["name"]: e for e in c.get("env") or []}
check("APP_WORKERS is 1, the only value cpu.5's entrypoint starts with (#8 there)",
      env.get("APP_WORKERS", {}).get("value") == "1", str(env.get("APP_WORKERS")))
check("NETWORK_BOUNDARY=sandbox stays, so the return to lab-platform's image binds the pod's address",
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
check("the kustomize image name llm-guard has a row naming cpu.5's reference at that digest",
      lock.get("llm-guard", [])[:2] == [f"{NAME}:{TAG}@{DIGEST}", "repo:peopleforrester/llm-guard-cpu-offline"],
      str(lock.get("llm-guard")))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All LLM Guard image checks passed.")
