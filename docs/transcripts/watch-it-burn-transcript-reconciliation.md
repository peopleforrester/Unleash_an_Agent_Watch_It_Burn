<!-- ABOUTME: Reconciles the two planning-transcript reference docs against the current canonical spec + repo state. -->
<!-- ABOUTME: Source docs are archive-on-close; this tracks which of their [OPEN]/[DIVERGENCE] items are now settled. -->

# Watch it Burn: Transcript Reconciliation

**Date:** 2026-06-24
**Reconciles:** `watch-it-burn-runofshow-from-transcript.md` (run-of-show & challenges) and
`watch-it-burn-infra-ops-addendum.md` (plumbing) against the canonical spec
(`facilitation/runbook.md`, `facilitation/slides-outline.md`, `facilitation/WHITNEY-START-HERE.md`,
`docs/STACK-WALKTHROUGH.md`) and the built repo.

**Bottom line:** most items are handled. The transcript's biggest flagged divergence (round-to-defense
mapping) is already the canonical model. Five items remain genuinely open, and all five are ops or
delivery calls for Michael/Whitney, not build gaps. The two source docs can be archived once those close.

---

## Run-of-show doc (`watch-it-burn-runofshow-from-transcript.md`)

| Item | Status | Evidence / resolution |
|---|---|---|
| **A. `[DIVERGENCE]` round→defense mapping** | **RESOLVED** | The canonical model already IS the transcript's model: Cluster 1 no guardrails (burn, cost counter, fork bomb) → Cluster 2 CNCF infra guardrails → Cluster 3 each attendee's own cluster with AI guardrails (input/output/MCP). See `facilitation/runbook.md` (0:10 C1, 0:25 C2, 0:45 C3), `facilitation/WHITNEY-START-HERE.md`. **LLM Guard lives in C3** (`gitops/ai-layer/resources.yaml`). **NeMo was explicitly dropped** (`research/07-guardrails-landscape-2026.md`: keep LLM Guard as the engine, do not switch to NeMo). The "attendee-configured cluster" = Cluster 3 (per-attendee take-home). No reconciliation left. |
| **B. Infra-vs-AI time balance** | **ADDRESSED (structure); delivery judgment stands** | The runbook deliberately gives the AI half the largest block: C1 = 15 min, C2 = 20 min, C3 (AI) = 45 min. The AI content is built (beat-2 input/output sanitization, beat-3 MCP authz, free-play). Whitney's "do we have an hour of AI" concern is answered by the 45-minute C3 plus optional beats. Remaining: a delivery-time judgment, not a build gap. |
| **C. Challenge 1 framing (at-rest vs in-transit)** | **RESOLVED (both shown)** | Both defenses are in the stack. NetworkPolicy default-deny egress blocks the push to S3 (validated live: S3 BLOCKED, DNS OK). Istio ambient STRICT mTLS covers in-transit (`docs/STACK-WALKTHROUGH.md:41`). The exfil game is the at-rest-secret → S3 path; mTLS is the in-transit story. No single-choice needed: the build demos both. |
| **D. mTLS scope-add** | **IN** | Istio 1.30.1 ambient, PeerAuthentication STRICT, mTLS certs are SPIFFE SVIDs (`docs/STACK-WALKTHROUGH.md:41,102-104`). In scope alongside NetworkPolicy. |
| **E. Fork bomb keep/placement** | **RESOLVED (mechanism); placement = Cluster 1** | Prevention is `podPidsLimit=1024` (config), detection is Falco -> Talon (terminate in ~4s), both validated live (see `PROJECT_STATE.md`). The teaching point (sometimes the fix is config/counting, not a flashy tool, and Falco still detects) is the settled story. Placement: Cluster 1, the shared burn (`facilitation/runbook.md`, `WHITNEY-START-HERE.md`: "the fork bomb kills it" at C1). Confirm with M/W, but it is effectively decided. |
| **F. Streaming to front of room** | **BUILT, optional, default-OFF + moderated** | `gitops/apps/customer-stream.yaml` + the prompt-stream display; `verify/test_stream.py` asserts capture is moderated and default OFF (code-of-conduct gate). In, but gated. |
| **G. Round-3 abrupt end** | **RECONCILED by architecture; confirm beat** | The shared cluster that dies abruptly is Cluster 1 (the shared room bot), not Cluster 3. Cluster 3 is per-attendee and independent (take-home), so one attendee wrecking theirs moves only them to an instructor C3 (`facilitation/runbook.md`). The "first attendee kills it for everyone" beat is the C1 burn. Confirm the intended ending beat with M/W. |
| SETTLED checklist (cold open, bottom-up intro, shared bot, linear progression, prompts-forward, the three challenges, Harbor+signing, prompt interface, two views) | **CONFIRMED still settled** | Matches `facilitation/` + `docs/BUILD-SPEC.md`. No conflicts. |
| Glossary item **BFO** | **STILL UNCLEAR** | Flag for Michael/Whitney to confirm what BFO referred to. |

## Infra/ops addendum (`watch-it-burn-infra-ops-addendum.md`)

| Item | Status | Evidence / resolution |
|---|---|---|
| **§1 Credential distribution** | **BUILT** | `lab-distribution/` v2: Railway app, email-keyed, hands each attendee console URL + Datadog + AWS creds, idempotent re-retrieve by email. Deployed live at `provisioning.agenticburn.com`. Sample keys resolved (Tara's `generate_accounts_csv.sh` + Whitney's keys; `scripts/merge_pool.py`). |
| **§1 ~40-minute auto-teardown** | **OPEN (verify/wire)** | Cluster teardown is currently the Terraform fleet (`teardown/teardown.sh`, prefix-scoped, scripted), not a 40-minute auto-expiry tied to credential issue. Confirm whether the ~40-min auto-teardown is required for the run or whether scripted teardown at the end suffices. (Separately: the Datadog trial orgs expire ~14 days, a different clock.) |
| **§1 attendee count 60 vs 70** | **OPEN (Michael's call)** | Fleet model supports it (EKS cluster quota 100; EC2 vCPU quota is the real limit, increase requested). Pick the exact count. |
| **§2 one Datadog account wired into provisioning** | **OPEN (real remaining technical item)** | The install method is decided (Datadog Operator; `research/32`, `research/34`) and creds are distributed to attendees (`merge_pool.py`). What is NOT yet wired: the provisioning process auto-injecting a working Datadog API key as a per-cluster secret so the Datadog Agent reports without manual steps. This is the gating test. Manual injection into one cluster is the acceptable interim. |
| **§2 owner (Datadog-into-provisioning)** | **OPEN** | Decide Michael vs Whitney for getting the account into provisioning vs pointing Datadog. |
| **§3 1Password sharing** | **OPEN (Michael, external)** | Not in repo. Michael to stand up the shared 1Password and notify. (Repo-side: clusters get the credential as a Secret via the ESO path.) |
| **§4 Apex/Relay deploy + DNS + terminal console** | **DONE** | `agenticburn.com` apex landing live; the "Relay" = the apex Caddy wildcard router (`railway/apex/`); Namecheap DNS set; `walkthrough.agenticburn.com` and `provisioning.agenticburn.com` live (HTTP 200). Terminal console (ttyd web-terminal + `console.html`) built (`gitops/ai-layer/`, `images/web-terminal/`). |
| **§5 research-spike orchestration** | **DONE / ongoing** | Exactly the executed process: spikes researched with multi-agent validation, written to `research/`, linked back to the issues (e.g. `research/28-34`, issues #9-17). Continues as Whitney files new spikes. |

---

## Still genuinely open (all ops/delivery calls, not build gaps)

1. **Datadog account auto-wired into cluster provisioning** + decide the owner (§2). The one real technical item.
2. **~40-minute auto-teardown** vs scripted end-of-run teardown: confirm requirement and wire if needed (§1).
3. **Attendee count: 60 or 70** (§1): Michael's call.
4. **Shared 1Password** stood up by Michael (§3).
5. **Confirm the delivery beats** (no build needed): fork-bomb placement on C1 (E), the C1 shared-cluster abrupt-end (G), streaming in/out for the live run (F), and the **BFO** glossary term.

## Archiving

Both source docs carry a "CAPTURED RECONCILIATION REFERENCE" banner pointing here. When items 1-5 above
close, move all three files to `docs/transcripts/archive/` (or mark them `[ARCHIVED]` in their banners).
Until then they stay as the live reconciliation trail.
