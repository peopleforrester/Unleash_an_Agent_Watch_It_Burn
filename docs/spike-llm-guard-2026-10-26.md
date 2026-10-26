# Is LLM Guard still the right technology? (#128, 2026-10-26)

**Finding: keep LLM Guard, and keep its scanner config as it is.** No replacement is named. The one candidate
worth measuring is Meta's Llama Prompt Guard 2 (86M) as the input classifier behind the same
`/analyze/prompt` call, and it cannot be measured until someone with a Hugging Face account is granted the
gated weights. LlamaFirewall's AlignmentCheck, which the 2026-09-03 comment on #128 recommended prototyping,
fails the issue's first constraint and is dropped.

Every upstream fact below was read live on 2026-10-26 with the command given, so it can be re-run rather than
believed. Measurements are from `verify/injection_config_matrix.py`, re-runnable, and the deployed config is
held by `verify/test_injection_classifier.py` in the E2E tools tier.

## Q1. Is LLM Guard maintained, and what is its current release?

No. It is archived, and 0.3.16 is the last release.

```bash
curl -s https://api.github.com/repos/protectai/llm-guard        # archived: true, pushed_at 2026-07-08T23:58:40Z, 3,218 stars
curl -s https://pypi.org/pypi/llm-guard/json                     # version 0.3.16, uploaded 2025-05-19T12:12:58
curl -s https://huggingface.co/api/models/protectai/deberta-v3-base-prompt-injection-v2/commits/main
```

The classifier's weights are older than the package. The model repo's last two commits (2026-07-08 and
2026-07-09, the latter `90c9989b`, the revision the offline image mirrors) only edit the README to add the
archive notice. `onnx/model.onnx` has the same LFS oid (`f0ea7f239f765aed…`, 738,563,188 bytes) at `90c9989b`
and at `89b085cd`, the revision llm-guard 0.3.16 pins, which is dated 2024-04-23. So the detector we run was
trained in April 2024 and nothing upstream will retrain it.

What this costs us is unchanged from the 2026-09-07 review on the issue: no security patches on software in the
request path (the image build already cut its CVEs from 916 to 24, #413/#415), a detector frozen against newer
injection technique, and narration that presents it as a current recommendation (`agent/GATEWAY-NOTES.md`).

## Q2. What else could a workshop self-host in-cluster?

The constraints from the issue: in-cluster with no vendor account and no egress, fast enough to sit inline, and a
verdict an attendee can read.

| Candidate | Upstream state, 2026-10-26 | Self-hosted, no account? | Fit |
|---|---|---|---|
| **LLM Guard** (what we run) | archived; 0.3.16, 2025-05-19 | yes, and already packaged offline (`llm-guard-cpu-offline`) | carries C5 and C6 today |
| **LlamaFirewall** (`meta-llama/PurpleLlama`) | repo pushed 2026-10-12, 4,448 stars; `LlamaFirewall/` last commit 2026-08-18; PyPI `llamafirewall` **1.0.3, 2025-05-29**, no release since | **AlignmentCheck: no.** PromptGuard scanner: only after gated access | see below |
| **Llama Prompt Guard 2 86M / 22M** (the classifier inside LlamaFirewall) | weights dated 2025-04-29; HF `gated: manual`; Llama 4 Community License | yes, once the weights are mirrored the way #414 mirrors ours | the one to measure |
| **NeMo Guardrails** (`NVIDIA-NeMo/Guardrails`, moved from `NVIDIA/NeMo-Guardrails`) | v0.24.1, 2026-09-16; pushed 2026-10-24 | yes (library) | a rails framework, not a scan endpoint; not measured |
| **Guardrails AI** (`guardrails-ai/guardrails`) | v0.11.0, 2026-08-14; pushed 2026-10-25 | yes (library, Hub validators) | validator-shaped; not measured |
| **LiteLLM content filter** | in the MIT tree (09-22 research, report 01) | yes | pattern-based, not a classifier |
| `deadbits/vigil-llm` | last push 2024-01-31 | yes | stale |

**Why AlignmentCheck is out.** It is what made LlamaFirewall attractive (it judges whether an agent's
trajectory has drifted from the user's goal, which is C6's attack exactly), but it is an LLM-as-judge. Its base
class, `LlamaFirewall/src/llamafirewall/scanners/custom_check_scanner.py`, defaults to
`model_name="meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"`, `api_base_url="https://api.together.xyz/v1"`
and `api_key_env_var="TOGETHER_API_KEY"`. That is a vendor account and egress by default, and self-hosting the
judge means serving a 400B-parameter mixture-of-experts model next to each attendee's cluster, on nodes with no
GPU. Pointing it at Bedrock instead would make it a second paid model call per prompt and non-deterministic,
which is the opposite of C6's "the guard decides before any token is spent". The 2026-09-03 comment's table
also listed all three frameworks as self-hostable with no vendor account; for AlignmentCheck that does not hold.

**Why Prompt Guard 2 is the one to measure, not to adopt.** It is a DeBERTa-class classifier with a 512-token
window, the same shape as ours, so it would sit behind the same `/analyze/prompt` call with no proxy change. Its
weights are newer (2025-04-29 against 2024-04-23), and Meta publishes better numbers for it, but that is Meta's
benchmark, not our beats. Two things stand between it and a measurement: the weights are gated (`manual`
approval on Hugging Face, so a person must request them), and its license requires attribution ("Built with
Llama") wherever it is redistributed, including our mirrored model image.

## Q3. Are its scanners the right ones for our two beats?

**Output (C5, and C7's sentinel):** yes, and it was never really LLM Guard's: the `Regex` scanner runs one
alternation we wrote, deterministic, with no model. It does not age. agentgateway's `promptGuard.response.regex`
could carry the same patterns (spike 2026-09-21), so this half has a second home if we ever need one.

**Input (C6):** the classifier is load-bearing. The ticket on `lab.html` contains none of guard-proxy's
`BLOCK_LIST` terms (checked against the default list in `proxy.py` at the pinned submodule commit), so with the
input guards on, `PromptInjection` alone refuses it. It does, every time, at risk 1.0. It is the right scanner
for the beat as written; its limits are in Q4.

## Q4. Is our scanner config current, or the original defaults?

Neither. LLM Guard has three different "defaults" for this scanner, and ours matches only the docs example.

| Setting | Ours (`llm-guard-scanners`) | Library (0.3.16 `__init__`) | API's shipped `scanners.yml` at v0.3.16 | Docs example |
|---|---|---|---|---|
| `threshold` | 0.5 | 0.92 | 0.92 | 0.5 |
| `match_type` | `full` (unset) | `full` | `truncate_head_tail` | `full` |
| `model_max_length` | 512 (unset, pipeline default) | 512 | 256 | 512 |
| `scan_prompt_timeout` | 10 s | n/a | 30 s | n/a |
| `lazy_load` | false (#241) | n/a | true | n/a |

This corrects the 2026-09-03 comment, which called 0.5 "the llm-guard default". Upstream's `main` differs from
the v0.3.16 tag only by adding `EmotionDetection`, which we do not run.

### Measured, 2026-10-26, one pinned core (the pod's CPU limit)

`OMP_NUM_THREADS=1 taskset -c 5 python3 verify/injection_config_matrix.py`. Thirteen prompts: C6's ticket; the
same payload after ~3,700 characters of plausible ticket text; the payload in the middle of that text; the
payload reworded without the "ignore previous instructions" register; the ticket without its payload; eight
menu asks from `topic_cases.ON_TOPIC`.

| Config | C6 ticket | payload at the end | payload in the middle | reworded | false positives | slowest scan |
|---|---|---|---|---|---|---|
| **ours: 0.5 full** | refused | **passed** | **passed** | **passed** | 0 of 9 | 3.9 s |
| library: 0.92 full | refused | passed | passed | passed | 0 of 9 | 3.1 s |
| API: 0.92 truncate_head_tail 256 | refused | refused | passed | passed | 0 of 9 | 0.7 s |
| 0.5 chunks | refused | refused | refused | passed | 0 of 9 | **11.1 s** |
| 0.5 sentence | refused | refused | refused | passed | 0 of 9 | **15.8 s** |

What the numbers say:

1. **The threshold does not matter on these prompts.** Every score was 1.0 or at or below 0.0 (risk -0.9 to
   -1.0), so 0.5 and 0.92 gave identical verdicts. Keep 0.5.
2. **`full` reads only the first 512 tokens.** A payload placed after ~3,700 characters of padding passes. That
   is a real bypass, and it is also a teachable one: a classifier has a context window, and an attacker who
   knows it pads.
3. **The fixes cost the beat its timing.** `chunks` and `sentence` read the whole prompt and catch both padded
   placements, but on one core they took 11 s and 16 s on a 4,000-character prompt, past the 10 s
   `scan_prompt_timeout`. The API answers 408, guard-proxy fails closed, and the attendee sees "prompt injection
   detected" for what was really a timeout, which would equally refuse a long innocent prompt. Upstream's own
   `truncate_head_tail` is fast and catches a payload at the end, but not one in the middle.
4. **Rewording beats every configuration.** The payload rewritten as a polite "note for the assistant" passed all
   five. (An earlier wording of the same idea was caught under `chunks` and `sentence`, so this is hit-or-miss,
   not never.) The classifier keys on the injection register, and a 2024 model will not learn newer phrasing.
   This is the honest version of C6's lesson: the guard stops the textbook attack, and the textbook is public.
5. **Zero false positives** on the menu asks and the clean ticket in every configuration measured here.
   `verify/test_injection_classifier.py` extends that to all 31 on-topic and vague asks in `topic_cases`.

**Config decision: no change.** The deployed config refuses the beat as written in under a second with no false
positives, and every alternative either changes nothing (threshold), trades a fast verdict for a timeout that
reads as a block (`chunks`, `sentence`), or closes one padding placement and not the other
(`truncate_head_tail`). The limits in points 2 and 4 are better narrated than configured away.

## Explainability: the verdict the attendee sees

The constraint the issue sets for any replacement, a verdict an attendee can read, is one we do not meet today,
and it is guard-proxy's doing, not LLM Guard's. `/analyze/prompt` returns `{"is_valid": false, "scanners":
{"PromptInjection": 1.0}}`. `input_allowed()` in `proxy.py` keeps only `is_valid`, so the attendee reads
"blocked by the input guardrail" with no scanner name and no score, while the block-list stage does name the
term it matched. Surfacing the scanner and score is a guard-proxy change and belongs in
`guard-proxy-agenticburn`; given point 1, the score will almost always read 1.0, so the scanner name is the
useful half.

## What would change this finding

- Prompt Guard 2 measured on `verify/injection_config_matrix.py`'s prompts with fewer misses at the same speed:
  swap the input classifier, keep everything else.
- A CVE in llm-guard's own code (zero advisories against it as of the 09-22 research) or in a pinned dependency
  that the image cannot bump without a source change: re-cost the fork against Prompt Guard 2 behind a thin
  scan endpoint.
- The workshop moving to nodes with a GPU, or to a model that can judge trajectories cheaply: revisit
  AlignmentCheck-style checks for C6.
