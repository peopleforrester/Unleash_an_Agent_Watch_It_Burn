# ABOUTME: LLM Guard API image with the PromptInjection classifier shipped as a local directory and Hugging
# ABOUTME: Face set to offline, so a cluster whose egress is already default-denied (Challenge 1) still scans (#241).
#
# The upstream image lazy-loads protectai/deberta-v3-base-prompt-injection-v2 from huggingface.co on the
# FIRST scan. In the workshop that first scan is Challenge 6, which every attendee reaches after applying
# Challenge 1's default-deny NetworkPolicy, so the download fails and guard-proxy (fail-closed) refuses
# every prompt for the rest of the lab.
#
# A cached Hub snapshot is not enough: the API forces use_onnx=True and optimum's ONNX loader lists the
# repo tree over the network even with HF_HUB_OFFLINE set. The API's `model_path` scanner parameter loads
# from a plain directory with local_files_only, which never touches the Hub. So the model lives at
# /home/user/models/prompt-injection (tokenizer files plus model.onnx at the top level, because
# `model_path` also clears the onnx subfolder) and scanners.yml points PromptInjection at it.
#
# Build and push (from the repo root):
#   docker build -t ghcr.io/peopleforrester/watch-it-burn:llm-guard-0.3.16-offline.2 images/llm-guard
#   docker push ghcr.io/peopleforrester/watch-it-burn:llm-guard-0.3.16-offline.2
FROM ghcr.io/peopleforrester/watch-it-burn:llm-guard-0.3.16

USER user
ENV WIB_PI_MODEL_DIR=/home/user/models/prompt-injection
RUN python - <<'PY'
import os, shutil
from huggingface_hub import snapshot_download
from llm_guard.input_scanners.prompt_injection import V2_MODEL
d = os.environ["WIB_PI_MODEL_DIR"]
# Exactly the model this llm-guard version defaults to, tokenizer files plus its ONNX export.
p = snapshot_download(repo_id=V2_MODEL.path, local_dir=d,
                      allow_patterns=["*.json", "spm.model", "onnx/model.onnx*"])
for f in os.listdir(os.path.join(d, "onnx")):
    if f.startswith("model.onnx"):
        shutil.move(os.path.join(d, "onnx", f), os.path.join(d, f))
print("model dir:", sorted(os.listdir(d)))
PY

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1
