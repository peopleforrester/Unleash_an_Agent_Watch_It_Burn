<!-- ABOUTME: Grounded research spike comparing the OSS input/output guardrail landscape as of June 2026 for the workshop. -->
<!-- ABOUTME: Decides keep/switch/augment for LLM Guard vs NeMo Guardrails, Llama/Prompt Guard, Guardrails AI, Invariant; maps every pick to the 4-5 attack scenarios and the determinism rule. -->

# Guardrails Landscape 2026, Research Spike (input + output sanitization)

## Verification Method

Web research against official vendor docs, GitHub repos, Hugging Face model cards, and one
independent benchmark, dated **2026-06-19**. No training data was trusted for versions,
licenses, model sizes, or footprint. Each material claim carries its source URL inline.
This spike compares against the settled pick in `research/03-llm-guard.md` and the wiring in
`agent/GATEWAY-NOTES.md`; it does not re-derive LLM Guard's API surface (that is verified there).

Sources consulted:
- NeMo Guardrails repo (license, version): https://github.com/NVIDIA-NeMo/Guardrails
- NeMo Guardrails overview: https://docs.nvidia.com/nemo/guardrails/latest/about/overview.html
- NeMo jailbreak heuristics (gpt2-large perplexity, port 1337 server): https://docs.nvidia.com/nemo/guardrails/latest/user-guides/jailbreak-detection-heuristics/index.html
- NeMo JailbreakDetect NIM tutorial: https://docs.nvidia.com/nemo/guardrails/latest/getting-started/tutorials/nemoguard-jailbreakdetect-deployment.html
- NeMo self-check rails (LLM-as-judge): https://docs.nvidia.com/nemo/guardrails/latest/configure-rails/guardrail-catalog/self-check.html
- NemoGuard 8B Content Safety / Topic Control 48 GB GPU: https://docs.nvidia.com/rag/2.5.0/nemo-guardrails.html (and NVIDIA model cards on build.nvidia.com)
- Llama Prompt Guard 2 model card (86M/22M, mDeBERTa, A100 latency): https://github.com/meta-llama/PurpleLlama/blob/main/Llama-Prompt-Guard-2/86M/MODEL_CARD.md
- Prompt Guard 2 license (Llama 4 Community License): https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M and https://www.llama.com/llama4/license/
- Llama Guard 4 12B (Llama 4 Community License): https://huggingface.co/meta-llama/Llama-Guard-4-12B
- Guardrails AI (Apache 2.0, Hub validators): https://guardrailsai.com/hub and https://github.com/guardrails-ai
- Invariant Labs acquired by Snyk: https://snyk.io/news/snyk-acquires-invariant-labs-to-accelerate-agentic-ai-security-innovation/
- Bedrock Guardrails pricing $0.15 / 1k text units, model-agnostic: https://aws.amazon.com/bedrock/guardrails/ and https://aws.amazon.com/bedrock/pricing/
- NeuralTrust CPU latency benchmark (DeBERTa-v3 vs Llama-Guard-86M vs Lakera): https://neuraltrust.ai/blog/prevent-prompt-injection-attacks-firewall-comparison
- Microsoft Presidio (MIT, regex + NER PII): https://github.com/microsoft/presidio
- agentgateway LLM token rate-limiting: https://agentgateway.dev/docs/standalone/latest/configuration/resiliency/rate-limits/

---

## RECOMMENDATION (read first)

**KEEP LLM Guard as the engine, AUGMENT the input path, do NOT switch to NeMo Guardrails, and
do NOT adopt Bedrock Guardrails.**

- **Output sanitization (exfil beat):** keep exactly what is wired. LLM Guard output `Regex`
  scanner on the sentinels is the provably model-free, deterministic control the spec section 3
  demands. Nothing in the 2026 landscape beats a regex for matching a known `FAKE-...-sentinel-...`
  string, and everything else (Llama Guard, NeMo content-safety, Bedrock) is a probabilistic
  classifier that would *violate* the determinism rule. No change.
- **Input sanitization (cost + injection beat):** keep LLM Guard as the host, but be explicit that
  the cheap deterministic part is the block-list (`Regex` / `BanSubstrings` on `delete` intent), and
  the ML part is the `PromptInjection` DeBERTa classifier. **Optionally** offer Meta's
  **Llama Prompt Guard 2 22M** as a lighter, faster drop-in classifier than LLM Guard's default
  DeBERTa, but only if footprint pressure demands it and the Llama 4 Community License is acceptable
  for a public workshop repo (see Risk 3). Default stays LLM Guard's own classifier.
- **Avoiding Bedrock Guardrails is sound.** It is proprietary, per-call metered ($0.15 / 1k text
  units), and it would put the guardrail *inside* the same vendor stack the talk is critiquing. The
  OSS equivalences below cover every function it offers. Confirmed.
- **Augment with three "old problem" firewall pieces we are light on:** (1) token/cost rate-limiting
  at the gateway (agentgateway supports it natively, ties straight into the wasted-token-DoS thesis),
  (2) output schema/JSON validation for any structured tool output, (3) keep MCP authz (already
  planned) framed as the agent-firewall. These are the "proxies, firewalls, metering, rate limiting"
  beat in spec section 2 made real.

Rationale in one line: the workshop's thesis is *deterministic where required, model-based where it
must be, and the boring controls still apply*. LLM Guard already lands that. NeMo Guardrails, Llama
Guard, and Bedrock are all heavier and more probabilistic, and the two NVIDIA/Meta options carry
GPU or license costs that break the per-attendee t3.large constraint or the OSS preference.

---

## Verified

### NVIDIA NeMo Guardrails, the option Michael named

- **License: Apache 2.0.** The core toolkit is genuinely open source.
  Source: https://github.com/NVIDIA-NeMo/Guardrails
- **Version: current 0.21.x / 0.22.0** as of access date. Actively maintained.
  Source: GitHub releases (same repo).
- **The core library is a CPU-runnable Python orchestrator.** `pip install nemoguardrails`,
  Python 3.10-3.13. It does NOT itself require a GPU. Source:
  https://docs.nvidia.com/nemo/guardrails/latest/about/overview.html
- **BUT its useful rails fall into three buckets, and all three are bad fits here:**
  1. **Self-check input/output rails** make a **separate LLM call** to judge each prompt/response.
     That is the literal **LLM-as-judge** pattern the spec section 3 bans for our guardrail, and it
     *adds* token cost on every request, the opposite of the input-sanitization cost-saving beat.
     Source: https://docs.nvidia.com/nemo/guardrails/latest/configure-rails/guardrail-catalog/self-check.html
  2. **Jailbreak-detection heuristics** (length-per-perplexity, prefix/suffix perplexity) compute
     perplexity with **gpt2-large**, and the recommended deployment is a **separate heuristics server
     on port 1337**. gpt2-large is ~1.5 GB of weights; it is not deterministic, and it is one more
     model + one more service per attendee node. Source:
     https://docs.nvidia.com/nemo/guardrails/latest/user-guides/jailbreak-detection-heuristics/index.html
  3. **NemoGuard safety models** (Llama 3.1 NemoGuard 8B Content Safety, Topic Control, JailbreakDetect)
     are the accurate path, and each **requires ~48 GB of GPU memory (H100/A100-class)**. This is a
     hard **non-starter** on a t3.large CPU node. Source:
     https://docs.nvidia.com/rag/2.5.0/nemo-guardrails.html and the NVIDIA model cards.
- **Net:** NeMo's CPU-only modes are either an LLM-as-judge (banned, and *increases* cost) or a
  gpt2-large perplexity server (heavy, non-deterministic, extra footprint). Its strong modes need a
  GPU we do not have per attendee. NeMo is built for the NIM/GPU ecosystem; on a CPU node it is a
  worse LLM Guard. **Do not switch.**

### Meta Llama Guard 4 and Llama Prompt Guard 2

- **Llama Guard 4 = 12B params, multimodal safety classifier.** Far too large for a t3.large; it is a
  GPU model. Also it does content-category safety (toxicity/violence/etc.), which is **not** our
  threat model (we are blocking *secret/PII exfil* and *delete intent*, not hate speech). Skip.
  License: **Llama 4 Community License** (not OSI-open-source; has acceptable-use restrictions).
  Source: https://huggingface.co/meta-llama/Llama-Guard-4-12B
- **Llama Prompt Guard 2** is the relevant one for the **input** beat. Two sizes:
  **86M** (mDeBERTa-base) and **22M** (DeBERTa-xsmall). Binary classifier: `benign` vs `malicious`
  (jailbreak + prompt injection). **CPU-runnable** (small DeBERTa models). Reported latency 92.4 ms
  (86M) / 19.3 ms (22M) at 512 tokens **on A100**; CPU will be slower but still viable for these
  sizes. Source:
  https://github.com/meta-llama/PurpleLlama/blob/main/Llama-Prompt-Guard-2/86M/MODEL_CARD.md
- **License: Llama 4 Community License**, copyright Meta, with an Acceptable Use Policy. This is
  **NOT** a clean OSS license like LLM Guard's MIT. For a public workshop repo Michael takes pride in
  shipping as open source, this is a real distinction (see Risk 3). Sources:
  https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M , https://www.llama.com/llama4/license/

### Independent CPU benchmark (the footprint-honest data point)

NeuralTrust's prompt-injection firewall comparison on CPU (proprietary airline dataset):

| Model | F1 | CPU latency | Size | Runs on CPU? |
|---|---|---|---|---|
| DeBERTa-v3 (= ProtectAI model LLM Guard uses) | 0.64 | **286 ms** | (DeBERTa-base) | YES |
| Llama-Guard-86M (Prompt Guard family) | 0.70 | **304 ms** | 86M | YES |
| NeuralTrust-118M | 0.87 | 39 ms | 118M | YES (vendor model) |
| Lakera Guard | 0.30 | 61 ms | API only | NO (SaaS) |

Source: https://neuraltrust.ai/blog/prevent-prompt-injection-attacks-firewall-comparison
(Treat absolute F1 as vendor-flavored, the benchmark is the vendor's own; the *relative* CPU-latency
and the "these DeBERTa-class models all run on CPU at a few hundred ms" point is the load-bearing
takeaway.) The honest read: LLM Guard's DeBERTa and Meta's Prompt Guard are in the **same CPU latency
class (~300 ms)**, so swapping to Prompt Guard buys footprint/accuracy at the margin, not a category
change. Prompt Guard 2 **22M** is the only thing materially faster (~75% less compute per its card),
which is the sole reason to consider it.

### Guardrails AI

- **License: Apache 2.0.** Actively maintained (0.9.x / 0.10.x in early-mid 2026, ~6.8k stars).
  Sources: https://github.com/guardrails-ai , https://guardrailsai.com/hub
- **What it is genuinely good at: output structure validation.** RAIL / JSON-Schema validation with
  automatic re-prompting when the model returns non-conforming output, plus a Hub of 70+ validators
  (PII, regex match, competitor mention, etc.). Source: https://guardrailsai.com/hub
- **Fit here:** NOT a replacement for LLM Guard's exfil regex (overkill, and re-prompting on failure
  is the wrong action for a hard block). But it is the **best-known OSS answer for the "output schema
  validation" gap** we are currently missing, if/when the agent emits structured tool payloads we
  want to validate. Optional augment, not core.

### Invariant Labs / Guardrails, MCP angle

- **Acquired by Snyk (announced June 2025), folded into Snyk's AI Trust Platform.** The original OSS
  `invariant` guardrails project still exists, but the team and roadmap now sit inside a commercial
  vendor; "Evo" / broader availability is gated. Source:
  https://snyk.io/news/snyk-acquires-invariant-labs-to-accelerate-agentic-ai-security-innovation/
- Their genuine contribution is **MCP-specific security** (they coined "tool poisoning" and "MCP rug
  pulls"). That is directly relevant to **beat 3 (bad MCP / excessive agency)** as a *narrative
  reference* and threat vocabulary. But for enforcement we already use agentgateway `mcpAuthorization`
  + kagent `toolNames` allowlist (`agent/GATEWAY-NOTES.md` §3). Adopting an acquired-into-a-vendor
  tool as a runtime dependency cuts against the OSS preference. **Cite for vocabulary, do not adopt.**

### AWS Bedrock Guardrails, why avoiding it is correct

- **Proprietary, model-agnostic, per-call metered: $0.15 per 1,000 text units** (~1,000 chars), each
  filter type billed separately. Sources: https://aws.amazon.com/bedrock/guardrails/ ,
  https://aws.amazon.com/bedrock/pricing/
- Three reasons to avoid it for THIS workshop, beyond Michael's OSS preference:
  1. **It is the thing the talk critiques.** Putting the guardrail inside the same proprietary cloud
     stack undermines the "you own this, take it home, it's open source" payoff (spec section 1).
  2. **It costs money on the input path**, directly fighting the input-sanitization *cost-saving*
     beat. A free local block-list that stops spend before the LLM is the whole point.
  3. **It is a black box** for a teaching demo. The value of LLM Guard `Regex` is attendees can read
     the rule and see exactly why the sentinel was caught. Bedrock Guardrails cannot show that.
- **OSS equivalences (so avoiding Bedrock loses nothing):**
  - Bedrock content filters / denied topics  ->  LLM Guard `BanTopics` / `BanSubstrings` /
    `Toxicity`, or NeMo self-check (if you wanted LLM-judge; we do not).
  - Bedrock prompt-attack filter  ->  LLM Guard `PromptInjection` (DeBERTa) or Llama Prompt Guard 2.
  - Bedrock sensitive-info / PII filter + regex  ->  LLM Guard `Sensitive` (Presidio NER + regex) and
    `Regex`; deterministic redaction equivalent is **Microsoft Presidio (MIT)** directly, which is
    what LLM Guard already wraps. Source: https://github.com/microsoft/presidio
  - Bedrock contextual-grounding  ->  not in our threat model; skip.

---

## The "what else should a June-2026 agentic stack have" answer

We are well covered on the three named guardrails. Honest gaps against a modern agentic firewall
stack, mapped to the beats:

1. **Token / cost rate-limiting and budget caps (we should add, low cost).** This is the literal
   "rate limiting / metering" line in spec section 2 and the wasted-token-DoS thesis.
   **agentgateway supports LLM token-based rate limits natively** (not just request-count), so this
   is a config addition on the gateway already in the stack, not a new component. It also gives a
   *second*, deterministic cost control alongside the input block-list: even if a prompt slips the
   classifier, the token budget caps the burn. Maps to: the cost counter beat + Cluster 1 "minimal
   floor". Source: https://agentgateway.dev/docs/standalone/latest/configuration/resiliency/rate-limits/

2. **Output schema / structured-output validation (optional augment).** If any tool call returns
   structured JSON the agent or downstream consumes, validate it against a schema and reject malformed
   output. Best OSS fit: **Guardrails AI** (JSON-Schema validators) or a plain `pydantic` model in the
   guard-proxy. Not needed for the sentinel-string exfil beat (regex covers that), but it is the
   standard "response firewall" piece and cheap to add to the proxy. Maps to: output-sanitization beat.

3. **A dedicated prompt-injection model is already present** (LLM Guard's DeBERTa). The only open
   question is whether to swap in **Prompt Guard 2 22M** for footprint. Decision: keep LLM Guard's
   default; treat Prompt Guard 22M as a documented fallback if RAM/latency on t3.large proves tight.

4. **Content/AI "firewall" framing.** We do not need a separate product. The *combination* already in
   the design, input block-list + injection classifier + output regex + MCP authz + (new) token rate
   limit, IS the Swiss-cheese AI firewall the 2026 literature describes. Frame it that way in the
   governance map; do not add a vendor "AI firewall" box.

5. **Deterministic PII redaction beyond the sentinel (optional).** If the talk wants to show PII
   (not just secret) exfil being redacted deterministically, **Microsoft Presidio (MIT)** regex
   recognizers are the model-free option; LLM Guard's `Sensitive` uses Presidio's NER which loads a
   model and breaks the RAM budget (`research/03-llm-guard.md` Risk 5). Keep PII out of the default
   path; if added, use Presidio regex recognizers, not the NER scanner.

---

## Mapping to the attack scenarios + the determinism rule

| Beat / attack | Control | Engine | Deterministic? | Spec-compliant? |
|---|---|---|---|---|
| Output exfil (secret sentinel) | LLM Guard output `Regex` on `FAKE-...-sentinel-...` | pure regex | **YES, model-free** | YES (section 3 rule satisfied) |
| Input injection + cost (delete intent) | block-list (`Regex`/`BanSubstrings`) + `PromptInjection` DeBERTa | regex (det.) + ML classifier | block-list YES; classifier NO | YES (classifier explicitly allowed, must NOT be called deterministic in attendee copy) |
| Bad MCP / excessive agency | agentgateway `mcpAuthorization` + kagent `toolNames` | CEL allow/deny | YES (rule eval) | YES; cite Invariant's "tool poisoning" vocab |
| Wasted-token DoS / cost | agentgateway LLM **token rate-limit** + input block-list | counter + regex | YES | NEW augment, deterministic, no LLM |
| (optional) structured output abuse | Guardrails AI / pydantic JSON-Schema | schema validation | YES | optional augment |

Determinism rule honored: the only non-deterministic guard in the default path is the **input**
prompt-injection classifier, which the spec section 3 explicitly permits ("model-based; that's
acceptable and is the cost-saving point") provided attendee copy never calls it deterministic. The
**output** exfil guard stays pure regex. Every augment proposed above is deterministic.

---

## Unverified / Could not confirm

- **Prompt Guard 2 CPU latency on a t3.large specifically.** Card reports A100 numbers only
  (92.4 ms / 19.3 ms). The NeuralTrust benchmark gives ~300 ms CPU for the 86M class but on different
  hardware. If Prompt Guard 22M is adopted, **measure CPU latency on the actual node at build** before
  pinning. Source gap noted on the model card.
- **Exact current Guardrails AI version.** Sources gave 0.9.2 (March 2026) and 0.10.0 (April 2026).
  Pin at build if adopted; not load-bearing since it is at most an optional augment.
- **agentgateway token-rate-limit on OSS v1.2.1 with a kagent A2A backend.** Native token rate-limit
  is documented for LLM-provider backends; whether it meters tokens through the A2A/JSON-RPC path the
  same way is the same open question as the existing prompt-guard `[SPIKE]` in `agent/GATEWAY-NOTES.md`
  #2. Verify on the live cluster before promising it live; otherwise enforce the cap in the guard-proxy.
- **NeMo 0.22.0 exact contents.** Release version confirmed present; did not enumerate 0.22.0 changes
  because NeMo is not recommended, the version is recorded for completeness only.

---

## Risks for the build

1. **Do not let "add a guardrail tool" creep expand the footprint.** Every new model-backed component
   (NeMo gpt2-large server, Prompt Guard, NemoGuard) is RAM on a t3.large that the spike in
   `research/03-llm-guard.md` Risk 5 already flagged as tight. The recommendation deliberately adds
   only **config** (agentgateway token limit) and **optional** pure-Python validation (pydantic /
   Guardrails AI), not new model servers. Hold that line.
2. **NeMo is a trap for this audience.** It is the most famous name and Michael asked about it, so the
   talk should *address* it explicitly: "NeMo Guardrails is Apache-2.0 and excellent, but its accurate
   rails want a 48 GB GPU and its CPU rails are an LLM-as-judge that costs tokens, the opposite of our
   cost beat." That is a teaching moment, not a dependency.
3. **Llama Prompt Guard / Llama Guard license is NOT clean OSS.** It is the Llama 4 Community License
   with an Acceptable Use Policy, copyright Meta. If we ship Prompt Guard weights or pull them at build
   in a repo we promote as open source, call out the license distinction in the repo. LLM Guard (MIT)
   and its default DeBERTa classifier (Apache/MIT-class ProtectAI model) avoid this entirely, which is
   another reason to keep them as default.
4. **Bedrock Guardrails temptation under time pressure.** It is one API call and would "just work."
   Resist: it is proprietary, metered, a black box, and it contradicts the talk's open-source and
   cost theses. The OSS equivalence table above means avoiding it costs no capability.
5. **Output schema validation is genuinely optional.** Do not build it unless a structured tool
   payload actually needs guarding; the exfil beat does not. Listed so it is a conscious decision, not
   an omission.
