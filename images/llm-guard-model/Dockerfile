# ABOUTME: The prompt-injection classifier weights as an image, so the guard build does not depend on
# ABOUTME: Hugging Face staying reachable. Contents only: no shell, no libc, nothing to execute.
#
# WHY (#414)
#
# images/llm-guard/Dockerfile used to fetch protectai/deberta-v3-base-prompt-injection-v2 from
# huggingface.co at build time. Runtime was already safe, because the weights are baked in and the Hub
# is switched off, but a rebuild was not: Palo Alto Networks archived the upstream project on
# 2026-07-08 and the archive notice covers the Hugging Face models as well as the code. Nothing obliges
# them to keep that org alive.
#
# So the weights live here, in the registry we already publish to, pinned by digest like everything
# else, and the guard image copies them across with COPY --from. No new tooling, no download step in
# the build, and the digest is enforced by the builder rather than checked afterwards.
#
# PROVENANCE, verified 2026-09-27
#
#   repo      protectai/deberta-v3-base-prompt-injection-v2   (Apache-2.0)
#   revision  90c9989b1a342275dd0d1a95aad283c04e075671
#   files     model.onnx  sha256 f0ea7f239f765aedbde7c9e163a7cb38a79c5b8853d3f76db5152172047b228c
#             spm.model   sha256 c679fbf93643d19aab7ee10c0b99e460bdbc02fedf34b92b05af343b4af586fd
#
# Both hashes were read from the Hugging Face API for that revision AND computed from the files inside
# llm-guard-0.3.16-cpu.2, and they agree. That is what establishes which revision we actually ship,
# rather than which one was current when somebody ran a download.
#
# Apache-2.0 requires the license and any NOTICE to travel with a redistributed work, so LICENSE.model
# sits beside the weights in this image.
#
# Build and push (from the repo root):
#   docker build -t ghcr.io/peopleforrester/watch-it-burn:llm-guard-model-90c9989b images/llm-guard-model
#   docker push ghcr.io/peopleforrester/watch-it-burn:llm-guard-model-90c9989b
#
# The source of the weights is the previous guard image rather than the Hub, on purpose: it copies the
# exact bytes we have already tested and pushed, and it needs no network at all.
ARG MODEL_SOURCE=ghcr.io/peopleforrester/watch-it-burn:llm-guard-0.3.16-cpu.2@sha256:9fe5d2ae3a83ecf2d2242f1a20bc3008ce7c8d19ddbe62516db06905ac9fe135
FROM ${MODEL_SOURCE} AS source

FROM scratch

LABEL org.opencontainers.image.source=https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn
LABEL org.opencontainers.image.description="deberta-v3-base-prompt-injection-v2 ONNX weights, revision 90c9989b1a342275dd0d1a95aad283c04e075671, mirrored"
LABEL org.opencontainers.image.licenses=Apache-2.0
LABEL org.opencontainers.image.title="llm-guard prompt-injection classifier weights"

COPY --from=source /home/user/models/prompt-injection /model
COPY LICENSE.model /LICENSE
