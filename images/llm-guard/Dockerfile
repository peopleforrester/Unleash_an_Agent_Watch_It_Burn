# ABOUTME: LLM Guard API image with the PromptInjection classifier baked in and Hugging Face set to
# ABOUTME: offline, so a cluster whose egress is already default-denied (Challenge 1) can still scan (#241).
#
# The upstream image lazy-loads protectai/deberta-v3-base-prompt-injection-v2 from huggingface.co on the
# FIRST scan. In the workshop that first scan is Challenge 6, which every attendee reaches after applying
# Challenge 1's default-deny NetworkPolicy, so the download fails and guard-proxy (fail-closed) refuses
# every prompt for the rest of the lab. Downloading at build time and forbidding network lookups at run
# time removes the internet from the scanner's path entirely, and spares Hugging Face sixty simultaneous
# anonymous pulls on workshop morning.
#
# Build and push (from the repo root):
#   docker build -t ghcr.io/peopleforrester/watch-it-burn:llm-guard-0.3.16-offline images/llm-guard
#   docker push ghcr.io/peopleforrester/watch-it-burn:llm-guard-0.3.16-offline
FROM ghcr.io/peopleforrester/watch-it-burn:llm-guard-0.3.16

USER user
# Instantiating the scanner pulls exactly the model this llm-guard version defaults to, into the same
# cache path the running service reads, so there is no model name to keep in sync by hand.
RUN python -c "from llm_guard.input_scanners import PromptInjection; PromptInjection(); print('classifier cached')"

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1
