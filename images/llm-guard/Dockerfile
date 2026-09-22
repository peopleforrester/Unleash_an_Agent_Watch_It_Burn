# ABOUTME: LLM Guard API image: multi-stage, CPU-only torch, vendored upstream source, and the
# ABOUTME: PromptInjection classifier baked in with Hugging Face offline so a default-deny cluster scans.
#
# THREE PROBLEMS THIS IMAGE SOLVES
#
# 1. Offline scanning (#241). The upstream image lazy-loads
#    protectai/deberta-v3-base-prompt-injection-v2 from huggingface.co on the FIRST scan. In the
#    workshop that first scan is Challenge 6, which every attendee reaches AFTER applying Challenge 1's
#    default-deny NetworkPolicy, so the download fails and guard-proxy (fail-closed) refuses every
#    prompt for the rest of the lab. A cached Hub snapshot is not enough: the API forces use_onnx=True
#    and optimum's ONNX loader lists the repo tree over the network even with HF_HUB_OFFLINE set. The
#    scanner's `model_path` parameter loads from a plain directory with local_files_only and never
#    touches the Hub, so the model lives at /home/user/models/prompt-injection with the tokenizer files
#    and model.onnx at the TOP level (model_path also clears the onnx subfolder), and the scanners.yml
#    in gitops/ai-layer/resources.yaml points PromptInjection at it.
#
# 2. Weight (#413). The build before this one derived FROM laiyer/llm-guard-api and measured 4,211 MB
#    compressed, of which 2,748 MB was fifteen NVIDIA CUDA packages and 555 MB was the CUDA-linked
#    torch build. This fleet runs t3.2xlarge nodes with no GPU, and llm_guard/transformers_helpers.py
#    selects CUDAExecutionProvider only when a GPU is present, so that payload was never loaded.
#    Deleting it in a later layer could not have helped, because a layer cannot remove bytes an earlier
#    layer added, which is why this builds from python:3.12-slim rather than wrapping another image.
#    The fix is a resolver change, not a source change: the `[cpu]` extra only selects the optimum
#    variant and does NOT control which torch build is resolved, while the default PyPI torch wheel
#    declares the NVIDIA wheels as hard dependencies. Installing torch from PyTorch's CPU index first
#    satisfies llm-guard's `torch>=2.4.0` and keeps the rest of the resolve away from CUDA.
#
# 3. The compiler in a security scanner (#415). build-essential is needed to BUILD and not to RUN, and
#    it drags in linux-libc-dev, whose CVE-2026-43185 (CRITICAL, no fix available) was the last
#    critical finding in the image. For the same layer reason as above, an apt-get purge later in the
#    file removes nothing: pip's install sits in a layer between them. So the compiler lives in a
#    builder stage and never reaches the runtime image, which carries only libgomp1.
#
# WHY THE SOURCE IS VENDORED
#
# src/ holds llm_guard_api at tag v0.3.16, copied verbatim from protectai/llm-guard, MIT, with its
# LICENSE alongside as LICENSE.upstream. Protect AI archived that repository on 2026-07-08 after Palo
# Alto Networks acquired them, so building from a clone of it is a dependency on somebody else's
# archived repository staying reachable. 40 KB of Python removes that. See #414 for the same argument
# applied to the model weights, which are still fetched at build time here.
#
# Build and push (from the repo root):
#   docker build -t ghcr.io/peopleforrester/watch-it-burn:llm-guard-0.3.16-cpu.2 images/llm-guard
#   docker push ghcr.io/peopleforrester/watch-it-burn:llm-guard-0.3.16-cpu.2

# ---------------------------------------------------------------------------------------------------
# Builder: compilers, the full install, and the model download. None of this stage ships.
# ---------------------------------------------------------------------------------------------------
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# A virtualenv at a fixed path is what makes the runtime stage a plain directory copy. It is built as
# the same uid that will run it, so no ownership rewrite is needed on the way across.
ENV VIRTUAL_ENV=/home/user/.venv \
    PATH=/home/user/.venv/bin:$PATH
RUN python -m venv "$VIRTUAL_ENV"

WORKDIR $HOME/app
COPY --chown=user:user src/pyproject.toml ./
COPY --chown=user:user src/app ./app

# torch FIRST, from PyTorch's CPU index. This is the size fix: it satisfies llm-guard's `torch>=2.4.0`
# with a 159 MB wheel instead of a 555 MB one and keeps the fifteen NVIDIA packages and triton out of
# the resolve below. Pinned, because an unpinned reinstall from PyPI would silently put CUDA back.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir ".[cpu]"

RUN python -m spacy download en_core_web_sm

# The classifier, baked in. Exactly the model this llm-guard version defaults to (V2_MODEL), tokenizer
# files plus its ONNX export, moved to the top level because model_path clears the onnx subfolder.
ENV WIB_PI_MODEL_DIR=/home/user/models/prompt-injection
RUN python - <<'PY'
import os, shutil
from huggingface_hub import snapshot_download
from llm_guard.input_scanners.prompt_injection import V2_MODEL
d = os.environ["WIB_PI_MODEL_DIR"]
snapshot_download(repo_id=V2_MODEL.path, local_dir=d,
                  allow_patterns=["*.json", "spm.model", "onnx/model.onnx*"])
for f in os.listdir(os.path.join(d, "onnx")):
    if f.startswith("model.onnx"):
        shutil.move(os.path.join(d, "onnx", f), os.path.join(d, f))
print("model dir:", sorted(os.listdir(d)))
PY

# ---------------------------------------------------------------------------------------------------
# Runtime: no compiler, no headers, no pip cache. Only what serves a request.
# ---------------------------------------------------------------------------------------------------
FROM python:3.12-slim

LABEL org.opencontainers.image.source=https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn
LABEL org.opencontainers.image.description="LLM Guard API v0.3.16, CPU-only torch, prompt-injection classifier baked in for offline scanning"
LABEL org.opencontainers.image.licenses=MIT

# libgomp1 is the one runtime library the compiler used to bring along. onnxruntime and torch want
# OpenMP; torch bundles its own copy in torch/lib, and this covers anything that looks for the system
# one. About 150 KB against build-essential's ~200 MB and its kernel headers.
#
# The upgrade is not optional, and the reason is worth keeping. The single-stage build installed
# build-essential, which depends on dpkg-dev, which depends on perl, and that incidentally upgraded
# perl-base to the version carrying three CRITICAL fixes. Dropping the compiler dropped that accident
# too, and the multi-stage image came back with three criticals the single-stage one did not have.
# Security updates in the base now happen on purpose rather than as a side effect of installing gcc.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    libgomp1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    VIRTUAL_ENV=/home/user/.venv \
    PATH=/home/user/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR $HOME/app

COPY --from=builder --chown=user:user /home/user/.venv /home/user/.venv
COPY --from=builder --chown=user:user /home/user/models /home/user/models

COPY --chown=user:user src/app ./app
COPY --chown=user:user src/pyproject.toml ./pyproject.toml
COPY --chown=user:user src/LICENSE.upstream ./LICENSE.upstream
# A default config so the image runs standalone. In the cluster this path is a ConfigMap mount
# (gitops/ai-layer/resources.yaml) and the file below is shadowed.
COPY --chown=user:user src/config/scanners.yml ./config/scanners.yml
COPY --chown=user:user --chmod=755 src/entrypoint.sh ./entrypoint.sh

# Nothing reaches the Hub at runtime. The scanner loads from WIB_PI_MODEL_DIR with local_files_only.
ENV WIB_PI_MODEL_DIR=/home/user/models/prompt-injection \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    PYTHONPATH=$HOME/app

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
