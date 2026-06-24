<!-- ABOUTME: Reconciles the two planning-transcript reference docs against the current canonical spec + repo state. -->
<!-- ABOUTME: Source docs are archive-on-close; this tracks which of their [OPEN]/[DIVERGENCE] items are now settled. -->

# Watch it Burn: Transcript Reconciliation

**Date:** 2026-06-24
**Reconciles:** `watch-it-burn-runofshow-from-transcript.md` (run-of-show & challenges) and
`watch-it-burn-infra-ops-addendum.md` (plumbing) against the canonical spec
(`facilitation/runbook.md`, `facilitation/slides-outline.md`, `facilitation/WHITNEY-START-HERE.md`,
`docs/STACK-WALKTHROUGH.md`) and the built repo.

**Bottom line:** most items are handled. The transcript's biggest flagged divergence (round-to-defense
mapping) is already the canonical model. After Michael's 2026-06-24 decisions (teardown = manual trigger;
count = 60; 1Password = done), two needed tasks remain: (1) AUTO-wire a Datadog account into provisioning
(manual rejected) and decide its owner, and (2) build and integrate ALL run-of-show beats per the
transcript (not confirm-only). The two source docs can be archived once those two close.

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
| **§1 teardown** | **SETTLED (2026-06-24): manual trigger** | No 40-minute auto-expiry timer. Teardown is `teardown/teardown.sh` (prefix-scoped, brings the fleet to $0), run manually by Michael (typically at the end of the run). The transcript's "~40 min auto-teardown" idea is dropped. Implication: leaked attendee creds live until manual teardown, so if blast-radius matters, mitigate via short IAM session lifetimes, not cluster auto-destroy. |
| **§1 attendee count** | **SETTLED (2026-06-24): 60** | Count is indeterminate, so plan for 60. Fleet model supports it (EKS cluster quota 100; EC2 vCPU quota is the real limit, increase requested). |
| **§2 one Datadog account auto-wired into provisioning** | **OPEN: REQUIRED, must auto-wire (manual interim REJECTED by Michael 2026-06-24)** | The install method is decided (Datadog Operator; `research/32`, `research/34`) and creds are distributed to attendees (`merge_pool.py`). NOT yet wired: the provisioning process auto-injecting a working Datadog API key as a per-cluster `datadog-secret` so the Datadog Agent reports with zero manual steps. Manual-into-one-cluster is NOT acceptable; spawning the fleet must "just work." Key design fork to resolve first: does each cluster report to (a) the attendee's own trial org from the pool row, (b) a single shared org Whitney watches for full visibility, or (c) both? Mechanism options: Terraform var -> k8s Secret in the cluster module; or ESO pulling the key from AWS Secrets Manager (matches the existing ESO + Pod Identity pattern); or the fleet driver seeding it per cluster from `pool.csv`. See "needed tasks" below. |
| **§2 owner (Datadog-into-provisioning)** | **OPEN** | Decide Michael vs Whitney for getting the account into provisioning vs pointing Datadog. |
| **§3 1Password sharing** | **DONE (2026-06-24)** | Shared 1Password is set up. Repo-side, clusters get the credential as a Secret via the ESO path. |
| **§4 Apex/Relay deploy + DNS + terminal console** | **DONE** | `agenticburn.com` apex landing live; the "Relay" = the apex Caddy wildcard router (`railway/apex/`); Namecheap DNS set; `walkthrough.agenticburn.com` and `provisioning.agenticburn.com` live (HTTP 200). Terminal console (ttyd web-terminal + `console.html`) built (`gitops/ai-layer/`, `images/web-terminal/`). |
| **§5 research-spike orchestration** | **DONE / ongoing** | Exactly the executed process: spikes researched with multi-agent validation, written to `research/`, linked back to the issues (e.g. `research/28-34`, issues #9-17). Continues as Whitney files new spikes. |

---

## Needed tasks (post-2026-06-24 decisions)

Settled and removed from the open list: teardown (manual trigger), attendee count (60), 1Password (done).

1. **Datadog account AUTO-wired into cluster provisioning** + decide the owner (§2). REQUIRED; manual
   injection is explicitly NOT an acceptable interim. Resolve the org fork (attendee trial org vs shared
   org vs both), then build the auto-injection (Terraform-var -> Secret, ESO from AWS Secrets Manager, or
   fleet-driver seeding from `pool.csv`) so spawning the fleet wires Datadog with zero manual steps.
2. **Build and integrate ALL run-of-show beats** (Michael 2026-06-24: not confirm-only; build them all,
   per the transcript). Audit every beat against the runbook + slides and ensure each is built and placed:
   - Challenge 1 customer-data exfil to S3 (NetworkPolicy default-deny egress + Istio ambient mTLS). Built; confirm both paths are demoed in the runbook.
   - Challenge 2 malicious deploy (Kyverno Harbor-only + signing/attestation). Built; the in-Harbor bypass as the optional motivator.
   - Challenge 3 Easter-egg secret grep. Built; placed in the round.
   - Challenge 4 fork bomb on Cluster 1 (PID-limit prevents, Falco/Talon detects). Built/validated; lock placement in the runbook.
   - Cluster-1 shared abrupt-end ending beat. Wire as the explicit C1 climax.
   - Front-of-room streaming display (moderated, default-OFF). Built; decide on/off for the live run and wire the cue.
   - Prompt library / interface (clickable inject, instructor-vs-attendee views, dropdown per round). Confirm built and placed.
   - **BFO** glossary term: still unresolved; confirm what it referred to.

## Archiving

Both source docs carry a "CAPTURED RECONCILIATION REFERENCE" banner pointing here. When items 1-5 above
close, move all three files to `docs/transcripts/archive/` (or mark them `[ARCHIVED]` in their banners).
Until then they stay as the live reconciliation trail.
