<!-- ABOUTME: Planning-transcript-derived run-of-show & challenge spec, captured verbatim as a reconciliation reference. -->
<!-- ABOUTME: Live status of every [OPEN]/[DIVERGENCE] item is in watch-it-burn-transcript-reconciliation.md; archive this once they close. -->

> **CAPTURED RECONCILIATION REFERENCE (2026-06-24).** This is a planning-transcript-derived spec, kept
> verbatim below. It is NOT the canonical spec. The canonical run-of-show is `facilitation/runbook.md` +
> `facilitation/slides-outline.md` + `docs/STACK-WALKTHROUGH.md`. The current status of every `[OPEN]` and
> `[DIVERGENCE]` item in this file is tracked in `watch-it-burn-transcript-reconciliation.md`. Archive this
> file once all items there are closed.

---

# Watch it Burn — Run of Show & Spec Notes

> **Source:** Walk-and-talk planning transcript with Whitney Lee (date unspecified; pre-June 29).
> **Status legend:** `[SETTLED]` = decided in this conversation · `[OPEN]` = unresolved / disputed · `[DIVERGENCE]` = conflicts with prior settled spec, must reconcile.
> **ASR note:** Source audio was heavily garbled. Technical terms below are decoded — see Glossary at bottom for the mapping. Treat decoded terms as interpretation, not verbatim.

---

## 0. TL;DR for Claude Code

The workshop is a three-round (three-cluster) progression where attendees attack a burrito-ordering AI agent and observe which guardrails catch what. Each round adds a layer of defense. Most of the *flow* is settled; the *round-to-defense mapping* and the *infra-vs-AI time balance* are not. Build against Section 4 (challenges) and Section 5 (UI), and surface Section 8 (open items) before generating anything that assumes them resolved.

---

## 1. Cold open / framing `[SETTLED]`

- Open with a real-world story: earlier this year (≈March) a popular burrito company's AI ordering assistant was jailbroken — a user got it to solve a reverse-linked-list problem in Python, then asked it about Euler's number, and it complied. Screenshot got millions of views.
- **Show the screenshot.** Do **not** say the company's name out loud (room is recorded). Referring to something someone else publicly posted is fine; just don't name it in speech.
- Thesis of the open: even a jailbreak that does no direct damage is reputationally embarrassing without lockdown.
- Transition line: "Here's the environment we're running — the cluster we're running at the IDP."

## 2. Environment intro `[SETTLED]`

- Walk the stack **bottom-to-top**.
- **Omit security technologies from the intro** unless they're actually being demoed. cert-manager and similar "basic necessities" can be mentioned as running, but explicitly framed as *not* prevention/detection.
- Hold the security framing until after the first attack interaction.
- Start with **one shared bot for the whole room** (no per-attendee cluster yet). This is the "burrito box" with no guardrails — attendees interrupt it, act up, and run the challenges.

## 3. Round / cluster model `[SETTLED — flow]` `[DIVERGENCE — mapping]`

- **Progression is LINEAR, not interleaved.** Run all challenges in a round, *then* advance to the next cluster. (Whitney floated interleaving challenge→solution→challenge; Michael rejected it. Decided: finish round, show what failed, move to next cluster with the next defense layer activated.)
- Carry the **attack prompts forward** between rounds so you can re-run a round-1 attack against round-2 defenses live ("does this get caught in phase two?"). This is *why* the prompt-capture/library matters (Section 5).
- Round model as stated in this transcript:
  - **Round 1 / Cluster 1 — no response.** Fully unblocked cluster. Attendees destroy it / go willy-nilly. No guardrails, no solutions implemented.
  - **Round 2 / Cluster 2 — infrastructure guardrails.** Respond with infra-layer defenses (NetworkPolicy, Kyverno, supply-chain, PID limits, Falco/Talon).
  - **Round 3 / Cluster 3 — AI guardrails.** Respond with AI-layer defenses.

> `[DIVERGENCE]` This infra-Round-2 / AI-Round-3 split does **not** match the prior settled spec of *no guardrails → CNCF OSS guardrails (LLM Guard, NeMo) → attendee-configured cluster*. Under the transcript's model, LLM Guard / NeMo and the attendee-configured cluster have no clean home. **Reconcile before building.** See Section 8, item A.

## 4. Challenge spec

Core round contains **three challenges**, with a **fork bomb** as a contested fourth/finale. Each challenge needs an attack *and* a corresponding defense to demo.

### Challenge 1 — Customer data exfiltration `[SETTLED — intent]` `[OPEN — mechanism]`
- **Goal:** get customer data (names, addresses from the burrito app) out to an attacker-controlled S3 bucket.
- **Attack mechanism — disputed:**
  - Michael: attack on **data at rest** — a secret/credential sits in a ConfigMap or Secret (or plain text), unencrypted/unsecured; attacker copies it and pushes to S3.
  - Whitney: framed it as data **in transit** — an established flow between two apps that gets siphoned.
  - Needs a single decision. `[OPEN]`
- **Defense(s) to demo:**
  - **NetworkPolicy** default-deny egress (blocks the push to S3, and blocks app-to-app exfil).
  - Possibly also **mTLS** (+ service-mesh / SPIFFE-style identity) to show in-transit protection.
  - Whitney wants both shown ("otherwise why are we talking it through"). Michael notes mTLS-path was discussed verbally but is **off the abstract** — scope-add risk. `[OPEN]`

### Challenge 2 — Deploy a malicious app `[SETTLED]`
- **Goal:** get the agent to deploy a villain/malicious workload.
- **Defense:** supply-chain controls — Kyverno policy that only permits images pulled from the **internal Harbor registry**, and only if **signed + attested** (provenance).
- **Known bypass to optionally expose:** if an attacker gets a malicious image *into* Harbor, Kyverno will still deploy it unless signing/attestation is enforced. Optionally let attendees attempt this if time allows — it motivates why signing+attestation is needed on top of registry restriction.

### Challenge 3 — Easter-egg / secret retrieval `[SETTLED]`
- **Goal:** an "Easter egg" file (e.g., a planted secret/password) sits on the filesystem; attendee gets the agent to fetch/grep it.
- This is the third challenge inside the round. Chosen over the alternative framings discussed.

### Challenge 4 — Fork bomb (cluster kill) `[OPEN — keep/placement]`
- **Goal:** dramatic — the agent runs a fork bomb and kills the cluster.
- **Core tension (this is the real debate in the transcript):**
  - Whitney loves the drama of killing the cluster but wants every challenge to map to a tool that *prevents* the attack at execution level. The fork bomb **cannot be prevented** by Falco or Talon — only **detected**.
  - Actual prevention is **per-pod PID limits** (kernel/Pod-Security config that caps PIDs per process) via Kyverno + Pod Security — i.e. "simple counting," a config change, not a flashy tool.
  - Michael's counter-story (the one that resolves it): the teaching point is that *sometimes the fix is just a config / simple counting, not a big technology* — and Falco still **detects** the attempt even when prevention is config-based, so you still get the "you are being attacked" signal.
- **Placement options discussed (undecided):**
  - Keep as the dramatic **round-3 finale** on the shared cluster (first attendee to land it kills it for everyone → abrupt end). `[OPEN]`
  - OR move to **round 1** as the last challenge.
- **Resolution lean:** PID-limit + Falco-detection is the intended story; fork bomb stays as the dramatic device. Confirm placement. `[OPEN]`

## 5. Prompt interface, streaming & views `[MOSTLY SETTLED]`

- **Prompt interface is separate from the cluster.** A dropdown switches between round-1 / round-2 / round-3 versions so prompts can be saved and reused across rounds.
- **Clickable prompt library:** prompts shown on instructor view should be clickable to **inject directly into the prompt box** — usable as a copy/paste-free library. `[SETTLED — intent, build TBD]`
- **Two views:**
  - **Instructor view:** shows prompts *including system prompts*.
  - **Attendee view:** a **generic view with system prompts stripped**, reachable by URL. Replicate the interface on attendee laptops (front-of-room screen size is unknown, don't rely on it). `[SETTLED]`
- **Stream-to-front-of-room** (the "drama"): `[NICE-TO-HAVE]`
  - Must be **sanitized** if displayed.
  - Value: stuck attendees get hints from others' attempts; finished attendees stay engaged.
  - Some content stays **instructor-screen-only** (not projected) by decision.
  - Surface the **prompt that killed the cluster** at the round-3 climax.

## 6. Timing `[ROUGH]`
- ~5 minutes per challenge/work session.
- Round 1: first break-it attempt ≈5+ min (they're genuinely trying); round 2 re-attempt similar.
- Round 3: open-ended until first attendee destroys the shared cluster.
- Rounds 1+2 estimated ≈1 hour combined. Concern raised that this could eat the whole front half. (Workshop slot is 2 hours: 2:20–4:20pm.)

---

## 7. SETTLED decisions (checklist)
- [x] Cold open = burrito-company jailbreak screenshot, company unnamed aloud.
- [x] Stack intro bottom-to-top, security tech omitted until after first attack.
- [x] Start with one shared room bot, no guardrails.
- [x] Linear round progression (no cluster interleaving).
- [x] Carry attack prompts forward across rounds.
- [x] Challenge 1 = data exfil to S3; Challenge 2 = malicious deploy; Challenge 3 = Easter-egg secret fetch.
- [x] Challenge 2 defense = Harbor-only + signing/attestation via Kyverno.
- [x] Prompt interface separate from cluster, dropdown per round, clickable inject.
- [x] Instructor view (with system prompts) vs generic attendee URL view (stripped).

## 8. OPEN / possible spec modifications (decide before building)
- **A. `[DIVERGENCE]` Round→defense mapping.** Transcript = infra (R2) / AI (R3). Prior spec = no-guardrails / CNCF-OSS-guardrails / attendee-configured. Where do LLM Guard + NeMo live, and where does the attendee-configured cluster go? Pick one model and make it canonical.
- **B. Infra-vs-AI time balance.** Whitney's unanswered question: "Do you think we have an hour's worth of material about AI?" Michael agreed infra is taking a lot and doesn't want it to dominate the first hour with little after. Risk: AI-guardrails content (the differentiator) is underbuilt vs infra. **Needs a content audit of the AI half.**
- **C. Challenge 1 framing.** Data-at-rest (secret copied → S3) vs data-in-transit (app-to-app siphon). Decide, because it dictates whether mTLS is in scope.
- **D. mTLS scope-add.** Showing mTLS + NetworkPolicy (vs NetworkPolicy alone) was discussed verbally but is off the abstract. In or out?
- **E. Fork bomb placement.** Round-3 finale (shared-cluster kill, abrupt end) vs round-1 closer. Confirm it stays at all given prevention is config-based, not tool-based.
- **F. Streaming to front of room.** Nice-to-have, sanitization required. In or cut?
- **G. Round-3 abrupt end.** First attendee kills the shared cluster for everyone — accepted as a quirk, but confirm that's the intended ending beat.

---

## 9. Glossary — ASR decode (garbled → actual)
| Transcript said | Actual |
|---|---|
| four-leaf clover / four quads / four files / four form / curve ball / curve / run a curve | **fork bomb** |
| T-Farmer / two barbers / chopper force | **Talon** (Falcosidekick Talon) |
| Southview | **Falco / Falcosidekick** |
| cool armor | **KubeArmor** |
| kyberno | **Kyverno** |
| harbor registry | **Harbor** (internal container registry) |
| MPLS and SEO / mTLS and SO | **mTLS** (+ likely service mesh / SPIFFE) |
| essay / three / safety bucket | **S3 bucket** |
| config map or secret | **ConfigMap / Secret** (Kubernetes) |
| certain manager | **cert-manager** |
| IDP | **Internal Developer Platform** |
| PID / head over-allocation / limiting code | **per-pod PID limits** |
| grapevine password / grep password | **grep'd secret** (Easter-egg file) |
| reverse link list + Euler's | the jailbreak story (bot solved off-task coding/math) |
| burrito box / Mickey Burrito Bot / Wonder burritos | the demo **burrito-ordering agent** |
| BFO | unclear — flag for confirmation |

> Items marked unclear or `[OPEN]` should be confirmed with Michael/Whitney before Claude Code treats them as fixed.
