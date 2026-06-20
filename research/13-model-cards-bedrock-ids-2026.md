<!-- ABOUTME: Grounded spike refreshing model-card safety numbers (Haiku 4.5 / Sonnet 4.6 / Opus 4.8) and resolving the real Bedrock inference-profile IDs per tier. -->
<!-- ABOUTME: Companion to research/10-model-cards-2026.md; adds Opus 4.8 and replaces the <DATE> placeholders in gitops/ai-layer/resources.yaml with verified ids. -->

# Model Cards + Bedrock Inference-Profile IDs, Per Tier (2026 refresh)

Two questions for the workshop, settled here with primary sources:

1. The published safety numbers (prompt injection / agentic / malicious use + ASL) for the three
   tiers the demo can run on, with Opus 4.8 added to the existing Haiku 4.5 / Sonnet 4.6 set in
   `research/10-model-cards-2026.md`.
2. The real Bedrock inference-profile IDs for each tier, to replace the `<DATE>` placeholders in
   `gitops/ai-layer/resources.yaml`.

## Verification Method

Primary sources, dated 2026-06-20. System-card numbers were extracted directly from Anthropic's
`www-cdn.anthropic.com` PDFs (the Opus 4.8 card, 246 pp, was downloaded and parsed locally; numbers
quoted below are from the in-text tables, not bar charts). Bedrock IDs were taken from the official
AWS `docs.aws.amazon.com` model-card pages AND confirmed against a **live** `aws bedrock
list-inference-profiles` / `get-inference-profile` call in `us-west-2` (profile `accen-dev`, the
workshop account). No numbers were invented. Bar-chart-only figures are marked **BAR-CHART-ONLY**.

Load-bearing sources:

- Anthropic System Cards hub: https://www.anthropic.com/system-cards
- Claude Haiku 4.5 System Card (Oct 2025): https://www-cdn.anthropic.com/7aad69bf12627d42234e01ee7c36305dc2f6a970.pdf
- Claude Sonnet 4.6 System Card (Feb 2026): https://www-cdn.anthropic.com/bbd8ef16d70b7a1665f14f306ee88b53f686aa75/Claude%20Sonnet%204.6%20System%20Card.pdf
- Claude Opus 4.8 System Card (May 28, 2026): https://www-cdn.anthropic.com/0b4915911bb0d19eca5b5ee635c80fef830a37ea.pdf
- AWS Bedrock model card, Sonnet 4.6: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-6.html
- AWS Bedrock model card, Opus 4.8: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-4-8.html
- Gray Swan Agent Red Teaming benchmark (Zou et al. 2025): arXiv:2507.20526

---

## 1. Safety numbers per tier

### ASL / RSP level

| Tier | ASL framing (quotable) |
|---|---|
| Haiku 4.5 | Deployed under **ASL-2**; card says it "remained well below ASL-3 thresholds across all domains." |
| Sonnet 4.6 | Deployed under the **ASL-3** Security Standard (same standard as Opus 4.6). |
| Opus 4.8 | RSP-evaluated; the card states its mitigations are "**equal to or stronger than our historical ASL-3 protections** and sufficient to make catastrophic risk ... very low but not negligible." It does NOT print a bare "deployed under ASL-N" sentence; cite the ASL-3-protections phrasing, not a clean label. |

### Prompt-injection / agentic-safety figures

**Haiku 4.5** (internal attack-prevention score, higher is better; from card 10):
- Computer use: 72.2% without safeguards / **92.4% with safeguards**
- MCP: **92.5%** (no safeguards); Tool use: **93.4%** (no safeguards)
- Agentic-coding malicious-use safety: **100%** (no mitigations)
- Gray Swan ART: "some of the best scores among the 25 model variants evaluated" -- per-k % are **BAR-CHART-ONLY.**

**Sonnet 4.6** (Shade adaptive ASR, lower is better; from card 10):
- Coding: **0.0% ASR** with safeguards + extended thinking (headline); 0.1% @1 / 7.5% @200 standard, no safeguards
- Computer use: 12.0% @1 / 42.9% @200 (extended thinking, no safeguards) -- weakest surface
- Browser use (Best-of-N): 1.29% scenarios / 0.24% attempts (no safeguards); 0.51% / 0.08% (safeguards)
- Malicious computer use refusal: **99.38%**; agentic-coding malicious refusal: **100%**

**Opus 4.8** (NEW; all from in-text tables of the May 28, 2026 card):
- Gray Swan ART (probability attacker succeeds, lower is better): Opus 4.8 "achieved robustness
  between that of Opus 4.7 and Sonnet 4.6 with extended thinking enabled (**9.6%** vs 6.0% and 15.9%
  at k=100) and without (**14.4%** vs 4.8% and 20.7% at k=100)." Card warns the benchmark is now
  "saturated ... measurements noisy at such low attack success rates."
- Shade coding ASR (lower is better), with thinking: **7.03% @1 / 57.5% @200 without safeguards;
  2.09% @1 / 37.5% @200 with safeguards.** Without thinking, safeguards cut per-attempt ASR 17.44% -> 4.11%.
- Shade computer use ASR, with thinking: **7.14% @1 / 50.0% @200 (no safeguards); 5.11% @1 / 57.1%
  @200 (with safeguards).**
- Live bug-bounty browser use (Gray Swan, 12 scenarios), with thinking: **62.8% scenarios / 31.5%
  attempts without safeguards; 3.9% / 0.5% with safeguards** (vs Sonnet 4.6 at 46.5% / 23.6% with safeguards).
- Malicious use of Claude Code: refusal **95.08%** on the 61-prompt malicious set; **92.12%** success
  on dual-use/benign.
- Malicious computer use refusal: **81.70%** (vs Opus 4.7 89.29%, Sonnet 4.6 84.82%) -- Opus 4.8
  "scored worse than recent models" here.
- Over-refusal: 0.36% API / 0.49% claude.ai. Single-turn harmless rate: 99.90% API / 99.99% claude.ai.

### The caveat the cards hand the workshop (the thesis, restated by the vendor)

Opus 4.8 makes the point more bluntly than any prior card. Verbatim:

- "we found Opus 4.8 to be **somewhat less robust than Opus 4.7** in several agentic contexts (such
  as vulnerability to prompt injection attacks). However, **the application of our safeguards closes
  the gap** between the models in practice."
- The bug-bounty numbers are "before our additional safeguards ... these add non-trivial uplift."
- "We continue to deploy additional safeguards with **probes -- lightweight detectors trained on
  internal model representations -- by default** to most of our agentic products to further protect
  our users against prompt injection."
- Robustness numbers "reflect the robustness of the models themselves and are **a lower bound for the
  practical robustness of the deployed systems built around them**."

That is the whole thesis: a newer, more capable frontier model regressed on injection robustness, and
the vendor's own fix is an external detection layer, not the model. The model is not the control.

---

## 2. Bedrock inference-profile IDs per tier (RESOLVED)

The `<DATE>` placeholders in `gitops/ai-layer/resources.yaml` are **wrong for Sonnet and Opus**. Only
Haiku 4.5 carries a date stamp. Sonnet 4.6, Opus 4.8 (and Opus 4.7, Fable 5) use **non-date-stamped**
inference-profile IDs. Confirmed two ways: the AWS docs Programmatic Access tables, and a live
`list-inference-profiles` in `us-west-2` where all three resolve **ACTIVE / SYSTEM_DEFINED**.

| Tier | Geo (US) inference-profile ID | Global form | Base model ID |
|---|---|---|---|
| Haiku 4.5 | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` | `anthropic.claude-haiku-4-5` |
| Sonnet 4.6 | `us.anthropic.claude-sonnet-4-6` | `global.anthropic.claude-sonnet-4-6` | `anthropic.claude-sonnet-4-6` |
| Opus 4.8 | `us.anthropic.claude-opus-4-8` | `global.anthropic.claude-opus-4-8` | `anthropic.claude-opus-4-8` |

These are **system-defined, account-independent** (SYSTEM_DEFINED, not per-account ARNs), so the same
literal string works on any account with model access enabled for that tier. The earlier YAML note
("exact date-stamped inference-profile ids come from `aws bedrock list-inference-profiles`") was the
right instinct but the wrong assumption about format: Sonnet/Opus have **no date stamp at all**, so
the `<DATE>` placeholder should be deleted, not filled.

Geo variants exist for all three: `eu.`, `jp.`, `au.` (and `global.`). The cluster runs in
`us-west-2`, so the `us.` profile is correct (us-west-2 is a valid source region for all three US geo
profiles). Note: neither Sonnet 4.6 nor Opus 4.8 supports In-Region inference in us-west-2 -- only Geo
and Global -- so the `us.` (Geo) or `global.` profile is mandatory; the bare base model ID will not
work cross-region. Opus 4.8 also has no In-Region endpoint URL at all (N/A in the AWS table).

### YAML fix (replaces the placeholders in `gitops/ai-layer/resources.yaml`)

```yaml
#   model: us.anthropic.claude-sonnet-4-6        # Sonnet 4.6 (mid tier)  -- no date stamp
#   model: us.anthropic.claude-opus-4-8          # Opus 4.8 (frontier)    -- no date stamp
```

Fable 5 is also live on Bedrock now (`us.anthropic.claude-fable-5` / `global.anthropic.claude-fable-5`
resolve ACTIVE), which reverses the YAML's "conditional on its Bedrock availability returning" note --
if the comparison wants a Fable tier, the ID is available.

---

## VERDICT

For slides, cite **one Opus 4.8 number** as the dramatic puncture: the browser-use bug bounty,
**62.8% of scenarios attacked without safeguards, dropping to 3.9% only once Anthropic's external
probes are switched on** -- a frontier model the vendor itself calls "less robust than Opus 4.7,"
rescued by a detection layer that is not the model. Pair it with the Haiku MCP attack-prevention
**92.5%** (Beat 5, the allowlist beat) from card 10. The IDs are settled: drop the `<DATE>`
placeholders; Sonnet and Opus take un-stamped `us.anthropic.claude-sonnet-4-6` /
`us.anthropic.claude-opus-4-8`. No further Bedrock lookup needed -- they are system-defined and
account-independent.
