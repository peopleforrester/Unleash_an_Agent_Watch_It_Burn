<!-- ABOUTME: Grounded research spike on model cards / system cards for the workshop's Bedrock Claude agent. -->
<!-- ABOUTME: Answers whether Anthropic/AWS cards exist, what safety claims they make, and whether mapping the 4-5 attack scenarios to card claims is a worthwhile narrative beat. -->

# Model Cards Research, Do We Have Them and Should the Workshop Use Them?

Michael asked: "Do we have model cards? Do we need to look at what those model cards include based
on the four or five scenarios we're going to run for testing?"

Short answer up top: **Yes, the cards exist and they are unusually good framing for this talk.** The
relevant Claude system card makes *explicit, numbered* claims about prompt-injection and harmful-
tool-use resistance, which are exactly the behaviors the demo attacks. That is a gift for the core
thesis. The VERDICT at the bottom scopes how much of it belongs in a 2-hour slot.

## Verification Method

Web research, dated 2026-06-19. Every material claim carries a primary-source URL inline. PDF system
cards were fetched and parsed directly from Anthropic's `www-cdn.anthropic.com` origin; AWS claims are
from `docs.aws.amazon.com` and `aws.amazon.com`. No eval numbers were invented. Numbers reported only
as bar-chart figures in the PDFs (no in-text value) are marked **UNVERIFIED** even though the figure
exists. Load-bearing primary sources:

- Anthropic System Cards hub: https://www.anthropic.com/system-cards
- Claude Haiku 4.5 System Card (Oct 2025), 39 pp:
  https://www-cdn.anthropic.com/7aad69bf12627d42234e01ee7c36305dc2f6a970.pdf
- Claude Sonnet 4.6 System Card (Feb 2026), 135 pp:
  https://www-cdn.anthropic.com/bbd8ef16d70b7a1665f14f306ee88b53f686aa75/Claude%20Sonnet%204.6%20System%20Card.pdf
- AWS Bedrock model-card docs hub: https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html
- AWS Bedrock Guardrails prompt-attack docs:
  https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html
- AWS AI Service Cards / Responsible AI hub: https://docs.aws.amazon.com/ai/responsible-ai/

---

## 0. WHICH model are we even carding? (resolve this first)

There is a live discrepancy in the repo that must be settled before any slide cites a card:

- `BUILD-SPEC.md` §5 / §6 / §10 pin the model as **`us.anthropic.claude-haiku-4-5-20251001-v1:0`**
  (described as live-verified working on EKS), and §10 lists "final Claude tier (haiku-4-5 vs a
  larger Claude)" as an *open* decision.
- `agent/kagent-modelconfig-bedrock.yaml` declares **`us.anthropic.claude-sonnet-4-6`** with a
  `verify-at-build` note to confirm the id and region.

These are two different models with two different cards. The talk should cite the card for whatever
model is actually invoked at runtime. Both cards exist (below), so either choice is defensible, but
**pick one and make the YAML, the spec, and the slide agree.** This is a Phase-3 build item, not a
research blocker. Note also a region mismatch (spec uses `us-east-2` IRSA examples; the YAML sets
`bedrock.region: us-east-2`, the cluster account is `us-west-2` per §0) , out of scope here but worth
flagging while we are in these files.

---

## 1. Anthropic Claude system cards (VERIFIED)

Anthropic publishes a **combined "System Card" per model** , one document per model, not separate
per-topic cards, not a single rolled-up "Claude 4.x" card. Both candidate models have their own.
Confirmed against the System Cards hub: https://www.anthropic.com/system-cards

| Model | Card title / date | Direct PDF |
|---|---|---|
| Claude Haiku 4.5 | "System Card: Claude Haiku 4.5", Oct 2025 | https://www-cdn.anthropic.com/7aad69bf12627d42234e01ee7c36305dc2f6a970.pdf |
| Claude Sonnet 4.6 | "System Card: Claude Sonnet 4.6", Feb 2026 | https://www-cdn.anthropic.com/bbd8ef16d70b7a1665f14f306ee88b53f686aa75/Claude%20Sonnet%204.6%20System%20Card.pdf |

Sonnet 4.6 cross-references the Claude Opus 4.6 System Card
(https://anthropic.com/claude-opus-4-6-system-card) for some eval methodology; Haiku 4.5 defers
prompt-injection methodology to the earlier Sonnet 4.5 card. So the candidate cards are not fully
self-contained on method, but the *results* we care about are in-card.

### Safety sections that actually exist in these cards (VERIFIED)

Both cards carry exactly the sections this workshop attacks:

- **Safeguards & harmlessness** , refusal evals and over-refusal (benign false-positive) rates.
- **Agentic safety** , a dedicated top-level section in both cards. Sub-parts:
  - *Malicious use of agents* (agentic coding, Claude Code, malicious computer use).
  - *Prompt injection* within agentic systems (the directly relevant one).
- **Alignment** , Sonnet 4.6 adds "reward hacking & overly agentic actions" and an "overly-agentic
  GUI computer use" subsection, plus sabotage evals (SHADE-Arena).
- **RSP / ASL determination** , the Responsible Scaling Policy safety level.

ASL level (VERIFIED, quotable):
- **Haiku 4.5 is deployed under ASL-2**; the card says it "remained well below ASL-3 thresholds
  across all domains."
- **Sonnet 4.6 is deployed under ASL-3** (same standard as Opus 4.6; released under the ASL-3
  Security Standard for model weights).

### The CRITICAL claims, prompt injection and harmful tool use (VERIFIED, with numbers)

This is the part that makes the talk work. The cards make explicit, numbered claims about exactly the
behaviors the demo will defeat at the infra layer. Shared external benchmark: **Gray Swan "Agent Red
Teaming" (ART)** (Zou et al. 2025, arXiv:2507.20526, with the UK AI Security Institute). Internal
adaptive attacker: **Shade**.

**Claude Haiku 4.5 , internal prompt-injection "attack prevention score"** (higher is better; an
attack "succeeds" when Claude deviates from its task to follow embedded malicious instructions):
- Computer use: 72.2% without safeguards / **92.4% with safeguards**
- MCP: **92.5%** (without safeguards)
- Tool use: **93.4%** (without safeguards)
- Agentic-coding malicious-use safety score: **100%** (no mitigations)
- Gray Swan ART: card says Haiku 4.5 showed "some of the best scores among the 25 model variants
  evaluated." Exact per-k percentages are bar-chart only , **UNVERIFIED numerically.**

**Claude Sonnet 4.6 , Shade adaptive prompt-injection attack success rate (ASR; LOWER is better):**
- Coding: **0.0% ASR with safeguards and extended thinking** (the card's headline robustness claim);
  0.1% at 1 attempt / 7.5% at 200 attempts in standard thinking without safeguards.
- Computer use: 12.0% (1 attempt) / 42.9% (200 attempts) extended-thinking, no safeguards , the
  card's own *weakest* surface; computer-use injection is explicitly NOT solved.
- Browser use (internal Best-of-N): **1.29% of scenarios / 0.24% of attempts** attacked without
  safeguards; **0.51% / 0.08%** with updated safeguards.
- Malicious computer use refusal: **99.38%** (refused all but one of 224 attempts).
- Agentic-coding malicious refusal: **100%** (150 requests, no mitigations).
- Gray Swan ART: "comparable to Claude Opus 4.6"; exact values bar-chart only , **UNVERIFIED
  numerically.**

### The caveat that the cards themselves hand us (VERIFIED, and it is the whole point)

The cards do **not** claim the model is injection-proof. They explicitly frame prompt injection as a
**partially-mitigated, defense-in-depth problem**, and the strong numbers depend on:
1. **Safeguards / classifiers being enabled** (a separate real-time detection layer), and
2. **Extended thinking** being on.

Direct from Sonnet 4.6's alignment section: the model can still fail by "failing to report concerning
prompt injection," and "Many positive safety traits appeared somewhat weaker in GUI computer use."
The card describes a "multi-layered defense strategy (training robustness + real-time detection
classifiers)" , i.e. **Anthropic itself says the model alone is not the control.** That is the
workshop's thesis stated by the vendor in its own safety document.

---

## 2. How AWS Bedrock surfaces "model card" / responsible-AI info (VERIFIED)

The word "model card" means three different things in this stack. Keep them separate or the slide
will be wrong:

1. **Bedrock model card (catalog page).** Per-FM page reachable from Console → Model Catalog → model
   card → Model Detail page. Doc hub: https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html
   Per-model docs exist for the Claude 4.5/4.6 family (e.g. Opus 4.5:
   https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-4-5.html ;
   Haiku 4.5 and Sonnet 4.6 have the analogous `model-card-anthropic-claude-*` doc paths). **Content
   is operational/commercial:** model IDs (incl. `us.`/`eu.`/`global.` cross-region profiles), context
   window, modalities, pricing link, regions, quotas, EULA. It carries **no fairness/bias analysis and
   no AWS-authored safety evals.** For safety it **links out to Anthropic's own card.**
2. **AWS AI Service Cards** (Responsible-AI docs, https://docs.aws.amazon.com/ai/responsible-ai/).
   These are **AWS first-party only** (Nova, Titan, Rekognition, Textract, etc.). **There is NO AI
   Service Card for any Claude model** , the predictable Claude URL 404s. AWS publishes **no service-
   card content on Claude prompt-injection / tool-use / agentic safety**; it defers to Anthropic.
3. **SageMaker Model Cards** , a **customer-authored governance artifact** for *your own* models
   (https://docs.aws.amazon.com/sagemaker/latest/dg/model-cards.html). **Does not apply to Bedrock-
   hosted Claude.** Same words, unrelated mechanism. (Only mention if an attendee asks "how do I card
   my own model?" , it is the OSS-adjacent governance template, see §4.)

So the Bedrock answer is: **AWS hands the safety story straight back to Anthropic's system card.** The
only place AWS *restates* a Claude safety claim is the marketing page
(https://aws.amazon.com/bedrock/anthropic/): "industry-leading resistance to jailbreaks and misuse."
That is a quotable, attackable claim , and it lives one click from where attendees pick the model.

### Bedrock Guardrails is a different layer (VERIFIED, and useful contrast)

**Bedrock Guardrails** is an AWS feature layered *on top of* any FM, distinct from the model's own
training. Its prompt-attack filter explicitly covers three categories , **Jailbreaks, Prompt
Injection, and Prompt Leakage** (leakage is Standard-tier only):
https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html . Protection is
tier-dependent (Standard > Classic) and only filters input the developer **tags** with
`<amazon-bedrock-guardrails-guardContent_...>`. This matters for the talk because Guardrails is
*adjacent to* the workshop's own guard layer (LLM Guard output Regex + input block-list + MCP
allowlist). It is a useful one-line "AWS has a knob here too, and it is also not the cluster control
plane" aside , not a beat to build.

---

## 3. Mapping the 4-5 attack scenarios to card claims

The build's scenarios (BUILD-SPEC §2, ABSTRACT) versus what the card claims:

| # | Attack scenario | Where the demo defeats it | Card claim it contradicts (the "watch anyway" hook) |
|---|---|---|---|
| 1 | Deploy non-compliant workload | CNCF: Kyverno admission (Cluster 1 burns, 2 blocks) | Agentic-coding malicious-use safety **100%** / Claude Code malicious refusal. Card says the model refuses malicious agentic coding , yet the *workload still reaches admission control*, because refusal is about intent the model recognizes, not policy the cluster enforces. |
| 2 | Escalate privileges | CNCF: scoped RBAC (Cluster 1→2) | "Reward hacking & overly agentic actions" / "overly-agentic GUI computer use" (Sonnet 4.6 alignment). The card measures over-agency; RBAC is what actually bounds it. |
| 3 | Modify infra outside Git | CNCF: ArgoCD drift detection (Cluster 1→2) | Same agentic-misuse framing. No card claim covers GitOps drift , a clean illustration that the card's threat model and the platform's threat model do not overlap. |
| 4 | Exfiltrate via agent response | Agent gap: output Regex sanitization (Cluster 3) | Prompt-injection "attack prevention" 72-93% (Haiku) / Shade ASR (Sonnet). The card's *highest-profile* number. "The card reports 90%+ injection resistance , now watch the sentinel leave the building, because the model was never the egress control." |
| 5 | Bad-MCP / excessive agency | Agent gap: kagent `toolNames` allowlist (Cluster 3) | MCP attack-prevention **92.5%** (Haiku). Direct hit: the card scored MCP injection resistance, and the demo shows a rogue MCP tool reached anyway until an *allowlist* (not the model) excluded it. |

The pattern that makes this land: scenarios 4 and 5 map to the card's strongest, most specific,
numbered claims (prompt injection, MCP tool use). Scenarios 1-3 map to the broader agentic-misuse
section. So the cleanest narrative is **two card quotes, not five**: one prompt-injection number and
one MCP/tool-use number, both attached to the Cluster-3 agent-gap beats where the contrast is
sharpest. The CNCF beats (1-3) do not need a card quote each , they make the "the model is irrelevant
here, this is admission control" point on their own.

The vendor's own caveat (§1) is the strongest single line available: Anthropic's card says the model
needs "real-time detection classifiers" layered on , i.e. **the safety document itself concedes the
model is not the control.** That sentence, plus the AWS marketing "industry-leading resistance to
jailbreaks" line, bracket the entire thesis: *model-level safety is not infrastructure governance.*

---

## 4. OSS model-card standards / tooling (relevance check)

Only relevant as a one-line aside if asked. The OSS model-card lineage (Mitchell et al. "Model Cards
for Model Reporting," 2019), Hugging Face model cards (the `README.md` model card on the Hub), and
Google's Model Card Toolkit are *documentation/governance templates for model authors*. They are the
same genre as a SageMaker Model Card (§2.3): you fill them in for a model you ship. They do **not**
describe a hosted Claude's runtime safety and have no bearing on the attack scenarios. Mention only if
an attendee asks "how should I card my own agent/model?" , then the answer is HF card + the
intended-use/limitations structure AWS AI Service Cards also use. **Not a workshop beat.**

---

## VERDICT

**Worthwhile , but as a tight framing device, not a section. Budget about 3-4 minutes, all in the
intro and the regroup, zero new build.**

Do it because:
- The cards exist for *both* candidate models and are primary, citable, and current (Oct 2025 / Feb
  2026). https://www.anthropic.com/system-cards
- The card makes the workshop's argument *for* us: it publishes specific resistance numbers for
  prompt injection (72-93% Haiku attack-prevention) and MCP/tool use (92.5% / 93.4% Haiku), then in
  its own alignment text concedes the model needs external classifiers and is weaker on computer-use
  injection. "The vendor says it resists X; watch it happen at the infra layer anyway" is not a
  rhetorical stretch , it is reading the card aloud.
- AWS structurally reinforces the thesis: Bedrock's "model card" is a commercial catalog page that
  *defers safety to Anthropic*, and AWS publishes *no* AI Service Card for Claude. The hosting layer
  itself says "model safety is upstream, not ours." That is the 80/20 split in documentation form.

Scope guardrails for a 2-hour slot:
- **Intro (~2 min):** one slide, the actual card screenshot, one prompt-injection number + one
  tool-use number + the "needs real-time detection classifiers" caveat. Set the trap.
- **Regroup (~1-2 min):** close the loop on the governance map , add a "model-card claim vs the layer
  that actually stopped it" column. This *strengthens* the existing governance-map artifact rather
  than competing with it.
- **Do NOT** build a card-by-scenario walkthrough of all five; map only scenarios 4 and 5 (the agent-
  gap beats) to specific card numbers. The CNCF beats need no card quote.
- **Resolve §0 first:** cite the card for the model actually invoked. If the model stays Haiku 4.5,
  use Haiku numbers; if it moves to Sonnet 4.6, use the 0.0%-coding-ASR / 99.38%-computer-use-refusal
  numbers (which are even more dramatic to puncture).
- Treat bar-chart-only Gray Swan ART percentages as **UNVERIFIED**; do not put a number on a slide
  that the card only draws as a bar.

Distraction risk if over-scoped: a deep card read competes with the live burn, which is the
brain-melter. Keep it to the bracketing quotes. The cost/wasted-token DoS thesis and the live
dashboard remain the headline; the model card is the *epigraph*, not a chapter.
