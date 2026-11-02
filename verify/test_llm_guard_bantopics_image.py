# ABOUTME: Static gate for #719: BanTopics may enter llm-guard-scanners only with an image known to bake the zero-shot
# ABOUTME: model, loaded from /home/user/models/zero-shot; images/llm-guard pins llm-guard-cpu-offline 31962f2, src/ unchanged.
"""Why this exists (#719, #455, lab-platform#341).

The on-topic guard (#455) waits on LLM Guard's BanTopics scanner, which needs the zero-shot model
deberta-v3-base-zeroshot-v2.0 at revision 8e7e5af5 baked into the image. The deployed image is lab-platform's
llm-guard:v1 (#652, sha256:6cdbf3a2... since #730), which carries only the prompt-injection model. lazy_load is off,
so a BanTopics entry in llm-guard-scanners with that image would stop LLM Guard at start, and guard-proxy fails
closed on every prompt. Two images bake the model at /home/user/models/zero-shot (WIB_ZS_MODEL_DIR):
llm-guard-cpu-offline's cpu.5, signed with the workshop key on 2026-11-01, and lab-platform's rebuild under
lab-platform#341, which is not built yet. Which one BanTopics runs in is the question #719 asks.

So the gate here is an allow-list, not a deny-list: BanTopics in scanners.yml fails unless the llm-guard image is
pinned at a digest known to bake the model, and its model_path must be that directory. An unknown digest fails
too, because an image this repo has not checked could lack the model as v1 does. lab-platform#341's digest joins
BAKES_ZERO_SHOT when it is built. The gate is checked against the repo's files and against copies with BanTopics
added, so it is shown to fire. The rest holds the submodule pin #719 moved: images/llm-guard at 31962f2, the commit
lab-platform's build reads since lab-platform 27f4a49 and the one cpu.5 was built from. Its Dockerfile bakes both
models at the paths the scanners use, and its src/ is the same tree as at f2fcb8f, the commit llm-guard:v1 was
built from.
"""
from __future__ import annotations

import copy
import pathlib
import re
import subprocess
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, REPO, kustomize_images  # noqa: E402

PIN = "31962f2074f758a2e9e06a9a91b4d758bcd56f03"
V1_SOURCE = "f2fcb8f4676c62319b50d95a23320aaa12d5a13d"
ZS_DIR = "/home/user/models/zero-shot"
PI_DIR = "/home/user/models/prompt-injection"
ZS_IMAGE_DIGEST = "sha256:c01ca9644bb1c93601a1b333339a3a2aacd63a287e057a4a124f5f08b33c7ca8"
CPU5 = "sha256:4c66fd0f0846c2c829952e562fd076f37ca8f7e41fb6ecfbb5a1f28cb8579791"
V1 = "sha256:6cdbf3a2272d1bc5e9ed0fbffc3d644d4109e9df3c709458e25ffd108ecf72ad"
# llm-guard images known to bake the zero-shot model at ZS_DIR. cpu.5 is built from images/llm-guard at PIN.
BAKES_ZERO_SHOT = {CPU5}
SUB = REPO / "images/llm-guard"
AI = REPO / "gitops/ai-layer"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def bantopics_problems(scanners: dict, digest: str) -> list[str]:
    """What stops a BanTopics entry from loading in the image pinned at digest; empty when there is none."""
    out: list[str] = []
    for s in scanners.get("input_scanners") or []:
        if s.get("type") != "BanTopics":
            continue
        if digest not in BAKES_ZERO_SHOT:
            out.append(f"the pinned llm-guard image {digest[:19]}... is not known to bake the zero-shot model")
        path = (s.get("params") or {}).get("model_path")
        if path != ZS_DIR:
            out.append(f"BanTopics model_path is {path!r}, not {ZS_DIR}")
    return out


docs = [d for f in yaml.safe_load((AI / "kustomization.yaml").read_text(encoding="utf-8"))["resources"]
        for d in yaml.safe_load_all((AI / f).read_text(encoding="utf-8")) if d]
cm = next(d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "llm-guard-scanners")
scanners = yaml.safe_load(cm["data"]["scanners.yml"])
dep = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "llm-guard")
container = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "llm-guard-api")
# The image is set either by the ai-layer Application's kustomize.images (lab-platform's, #652) or, for a
# watch-it-burn image, named in the Deployment itself; the digest is read from whichever sets it.
entry = next((i for i in kustomize_images(yaml.safe_load((APPS / "ai-layer.yaml").read_text(encoding="utf-8")))
              if i.get("name") == container["image"]), None)
digest = entry["digest"] if entry else container["image"].partition("@")[2]

print("== BanTopics runs only in an image known to bake the zero-shot model ==")
check("the llm-guard image is pinned by digest", digest.startswith("sha256:"), container["image"])
problems = bantopics_problems(scanners, digest)
check("llm-guard-scanners and the pinned image agree on BanTopics", not problems, "; ".join(problems))

with_bt = copy.deepcopy(scanners)
with_bt["input_scanners"].append({"type": "BanTopics", "params": {"topics": ["violence"], "threshold": 0.5,
                                                                   "model_path": ZS_DIR}})
check("the gate fires on BanTopics added while lab-platform's llm-guard:v1 (6cdbf3a2) is pinned",
      bool(bantopics_problems(with_bt, V1)))
check("the gate fires on BanTopics with an image digest this repo has not checked",
      bool(bantopics_problems(with_bt, "sha256:" + "0" * 64)))
check("the gate passes the same entry with cpu.5 (4c66fd0f), which bakes the model",
      not bantopics_problems(with_bt, CPU5))
hub = copy.deepcopy(with_bt)
hub["input_scanners"][-1]["params"]["model_path"] = "MoritzLaurer/deberta-v3-base-zeroshot-v2.0"
check("the gate fires on a BanTopics model_path that is not the baked directory",
      bool(bantopics_problems(hub, CPU5)))
bare = copy.deepcopy(with_bt)
del bare["input_scanners"][-1]["params"]["model_path"]
check("the gate fires on a BanTopics entry with no model_path, which would reach the Hub",
      bool(bantopics_problems(bare, CPU5)))

print("== images/llm-guard pins llm-guard-cpu-offline 31962f2 ==")
tree = subprocess.run(["git", "-C", str(REPO), "ls-tree", "HEAD", "images/llm-guard"],
                      capture_output=True, text=True, check=True).stdout.split()
check(f"the gitlink is {PIN[:7]}, the commit lab-platform's build reads since lab-platform 27f4a49",
      tree[:1] == ["160000"] and tree[2:3] == [PIN], " ".join(tree))
head = subprocess.run(["git", "-C", str(SUB), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
check("the submodule is checked out at the gitlink (verify/ensure-submodules.sh)", head == PIN, head)
same = subprocess.run(["git", "-C", str(SUB), "diff", "--quiet", V1_SOURCE, PIN, "--", "src"],
                      capture_output=True, text=True)
check(f"its src/ is the same tree as at {V1_SOURCE[:7]}, which llm-guard:v1 was built from, so the move "
      "changes no API file", same.returncode == 0, same.stderr.strip() or f"exit {same.returncode}")

dockerfile = (SUB / "Dockerfile").read_text(encoding="utf-8")
check(f"its Dockerfile bakes the prompt-injection model at {PI_DIR}, where llm-guard-scanners loads it",
      re.search(rf"^ENV WIB_PI_MODEL_DIR={re.escape(PI_DIR)}$", dockerfile, re.M) is not None)
check(f"its Dockerfile bakes the zero-shot model at {ZS_DIR} (WIB_ZS_MODEL_DIR), the path lab-platform#341 uses",
      re.search(rf"^ENV WIB_ZS_MODEL_DIR={re.escape(ZS_DIR)}$", dockerfile, re.M) is not None)
check("it takes the zero-shot weights from the scratch image llm-guard-model-zeroshot-8e7e5af5, by digest",
      re.search(rf"^ARG ZERO_SHOT_IMAGE=\S+:llm-guard-model-zeroshot-8e7e5af5@{ZS_IMAGE_DIGEST}$", dockerfile, re.M)
      is not None)
check("the scratch image's build context, model-zero-shot/, is in the checkout",
      (SUB / "model-zero-shot/Dockerfile").is_file() and (SUB / "model-zero-shot/LICENSE.model").is_file())
sub_cfg = yaml.safe_load((SUB / "config/scanners.yml").read_text(encoding="utf-8"))
sub_bt = [s for s in sub_cfg.get("input_scanners") or [] if s.get("type") == "BanTopics"]
check("its default config loads BanTopics from ${WIB_ZS_MODEL_DIR}",
      [(s.get("params") or {}).get("model_path") for s in sub_bt] == ["${WIB_ZS_MODEL_DIR}"], str(sub_bt))

print("== images.lock records the zero-shot images by the digests #719 names (#603) ==")
lock = {ln.split()[0]: ln.split()[1:] for ln in (REPO / "images.lock").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")}
for ref, want in (("ghcr.io/peopleforrester/watch-it-burn:llm-guard-0.3.16-cpu.5", CPU5),
                  ("ghcr.io/peopleforrester/watch-it-burn:llm-guard-model-zeroshot-8e7e5af5", ZS_IMAGE_DIGEST)):
    check(f"{ref.rsplit(':', 1)[1]} has a row at {want[:15]}...", lock.get(ref, [])[:1] == [want], str(lock.get(ref)))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All BanTopics image checks passed.")
