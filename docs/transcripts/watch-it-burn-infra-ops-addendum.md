<!-- ABOUTME: Planning-transcript-derived infra/ops addendum, captured verbatim as a reconciliation reference. -->
<!-- ABOUTME: Live status of every open item is in watch-it-burn-transcript-reconciliation.md; archive this once they close. -->

> **CAPTURED RECONCILIATION REFERENCE (2026-06-24).** Planning-transcript-derived ops notes, kept verbatim
> below. NOT canonical. Current status of every open item is tracked in
> `watch-it-burn-transcript-reconciliation.md`. Archive this file once all items there are closed.

---

# Watch it Burn — Infra / Ops Addendum

> **Source:** Second planning transcript (stream-of-consciousness brain-dump, multi-thread). Only the workshop-operations content is captured here; the rest of that transcript covers unrelated workstreams.
> **Relationship to other file:** Companion to `watch-it-burn-runofshow-from-transcript.md`. That file = teaching flow & challenge spec. This file = the plumbing to run it.
> **ASR note:** Heavily garbled source. Terms decoded; transcription-uncertain items flagged `(?)`. Confirm before treating as fixed.

---

## 1. Attendee credential distribution `[DESIGN STATED]`

A self-serve credential system, separate from the clusters, that hands each attendee scoped, time-boxed cloud creds.

- **Hosting:** a Railway app. `[SETTLED]`
- **Flow:**
  1. Attendee enters their email address.
  2. Email is **fingerprinted** and bound to a set of AWS credentials (creds tagged to that identity).
  3. Creds are **emailed** to the attendee **and** displayed on the page.
  4. If they lose them, they re-enter/re-authenticate to retrieve again.
- **Expiry:** everything tears down **~40 minutes** after issue — so even if creds leak/are stolen, blast radius is bounded. `[SETTLED]`
- **Scale target:** must work for the full room — **~60–70 attendee clusters** spawned. `[OPEN — exact count: 60 vs 70]`
- **Sample key/schema:** ✅ **Resolved** — Whitney has already provided sample Datadog keys. Distribution system can be tested end-to-end. `[DONE]`

## 2. Datadog wiring `[OPEN — provisioning integration]`

- Sample Datadog keys are **in hand** (from Whitney). Whitney needs full visibility into the **Datadog backend** during the run.
- **At least ONE working Datadog account must be wired into the cluster provisioning process** before the 60–70 clusters are spawned — this is the gating test. `[OPEN — must-have-one]`
- Interim acceptable: insert the Datadog account **manually** into one cluster to validate, but Michael can't wait on manual for the full provision — the provision process itself needs to pull it automatically so spawning the fleet "just happens." `[DECISION: automate, manual only to unblock testing]`
- Action: confirm whether Michael or Whitney owns getting the Datadog account into provisioning vs pointing Datadog the way Whitney wants. `[OPEN — owner]`

## 3. Secrets sharing between presenters `[SETTLED]`

- Stand up a **1Password** account (micro tier `(?)`) for sharing keys between Michael and Whitney. Michael to set up and notify when ready.
- Provisioned clusters get the credential **pre-populated as a secret**.

## 4. Apex / landing + Relay deploy `[IN PROGRESS]`

- Network was **restructured with Relay** `(?)`.
- Deploy sequence Michael called out, in order:
  1. **Deploy the Watch it Burn Apex / Apex Landing Relay** (landing page + relay layer). `(?Runaway = Relay)`
  2. Set **DNS via Namecheap** `(?)` (explicit go-ahead given).
  3. **Terminal console build next**, to check **UI exposure**.
- Sequencing rule stated: finish the Apex deploy **first**, then the research-spike orchestration (§5), then the terminal console build.

## 5. Research-spike orchestration (Whitney → repo) `[PROCESS STATED]`

- Whitney is adding **research spikes as issues / PRDs** to the project repo.
- Michael's job: find them, **kick off sub-agents for deep research, each with validation passes**, write the research into the repo, and **link it back to Whitney's PRDs** per the location/linking instructions she specified.
- Collaboration model: Whitney pushes to the repo directly; her rules land in `.env` rules files. Gotchas should live at the repo "gotcha" level (CLAUDE.md gotchas `(?)`) so they're shared, not siloed.
- Standing instruction to the agent for repo work: **ingest the PRD → research the backend → write a file out to the repo.** Process/level-of-effort matters more to Michael than the polish of the outcome on these.

---

## 6. Open items blocking the run (consolidated)
- [x] ~~Whitney provides a **sample Datadog key/schema**~~ — ✅ done, keys received.
- [ ] **One** Datadog account wired into cluster provisioning (manual to unblock, automated for the fleet). (§2 — must-have)
- [ ] Decide **owner** for Datadog-into-provisioning vs Datadog-pointing. (§2)
- [ ] Confirm attendee/cluster count: **60 or 70**. (§1)
- [ ] Stand up shared **1Password**. (§3 — Michael)
- [ ] Finish **Apex/Relay deploy**, then DNS, then terminal-console UI-exposure check. (§4)
- [ ] Pull in and fan out **Whitney's research-spike PRDs** with validation passes. (§5)

## 7. Decode key (this transcript)
| Transcript said | Actual |
|---|---|
| trials / trial keys | trial **Datadog** accounts |
| data dog | **Datadog** |
| railway app | **Railway** (hosting) |
| one pass / micro grid | **1Password** (micro tier?) |
| the 60 / the 70 | the **60–70 attendee clusters** |
| Watch at Barn Apex / Apex Landing Relay / Runaway | **Watch it Burn Apex / Relay** deploy |
| Name chip ... DNS write | **Namecheap** DNS (?) |
| .env rules / gotcha level | repo rules files / **CLAUDE.md gotchas** (?) |
| PRD / BRD | product/business requirements doc (repo issues) |
| sub agents ... deep research ... validation passes | Claude Code subagent fan-out w/ validation |
