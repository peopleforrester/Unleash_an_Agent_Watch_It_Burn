# Run-of-Show Reaffirmation, Michael + Whitney, 2026-06-29

Captured from a Michael + Whitney working conversation (voice transcript at the end of this file,
verbatim, as history). This reconciles that conversation against the built repo and confirms which
run-of-show elements are covered and which are gaps. It supplements (does not replace)
`facilitation/runbook.md` and `docs/RUN-OF-SHOW-AND-BACKLOG-2026-06-27.md`.

> **UPDATE 2026-06-29 (supersedes parts of this doc):** the **S3 exfil is CUT**. Challenge 1 is now a
> **chat/screen leak** of customer data: the "Wendolyn, the new ops witch" prompt gets the agent to run a
> maintenance command and print customer PII into the chat and the trace (excessive agency). There is **no
> S3 bucket exfil and no S3 "attack the room" view**. Treat every S3 reference below as **invalid for now**.
> The verbatim source transcript that drove the original S3 framing was moved out of the repo.

## The flow they described

### Round 1, open cluster, attack the BurritoBot, watch the room burn
- A secret ingredient is the hook: a "bat spit secret recipe" planted on the cluster. Two attack goals:
  pull the secret recipe, and exfiltrate customer data (e.g. social-engineer a customer's delivery
  address) out to an S3 bucket.
- Other attacks: deploy a malicious image (the "Joker" / "grill zone" image), and run executable code
  in the cluster (exec, `ls`, live process activity).
- LIVE observability is the payoff: a shared view (Datadog, plus maybe an S3 / AWS view) where the room
  sees attacks land in real time, a malicious image deployed, customer data populating an S3 bucket,
  process/`ls` calls across clusters. Even an attendee who hasn't broken through sees others succeed.
- Gamified: "you can only order a burrito once you accomplish your objective." Facilitators give hints
  and show one known-working exploit prompt so nobody is stuck.

### Round 2, turn the CNCF guardrails on LIVE, one at a time, re-run the same attack
The thread is: take an attack that WORKED in R1, switch on one platform control, re-run the exact same
attack, watch it stop. In order:
1. NetworkPolicy: turn on egress restriction, re-run the R1 exfiltration prompt, data can no longer
   leave the cluster. (Cilium CNI / eBPF discussed; L3 vs L7.)
2. Image-source restriction: restrict pulls to a trusted registry (Harbor/GCR), re-run the malicious
   image, BurritoBot agrees but the image can't be pulled/run.
3. Falco (+ Kyverno): enable runtime detection/enforcement, re-run exec/`ls`, it's detected and blocked.
- Framing: the CNCF wall contains blast radius but the prompt still gets through some of the time, and
  the cost was already incurred. That motivates Round 3's AI guardrails.

### Round 3, your own cluster, three in-browser tabs, self-paced challenges 5/6/7
- Provisioning hands each attendee an in-browser BurritoBot, in-browser VTT terminal, and in-browser
  debug, three tabs, all in-browser. Local kubectl stays tiny optional print with an "experienced users
  only" warning; recommend just using the terminal (no time to set up local).
- Self-paced: a quick mental model, then left-pane step-by-step (5a/b/c...) in the VTT.
- Challenge 5, output sanitization: show the secret recipe leaking, turn the output guard on, re-run,
  it's blocked. Challenge 6, input classifier (PII-in-logs + cost). Challenge 7, evil MCP server.

## Coverage map (element to build state)

| Round | Element | Built? | Where / task |
|---|---|---|---|
| R1 | Open BurritoBot, attackable | YES | ai-layer (workshop-agent + console) |
| R1 | "Bat spit" secret recipe planted + grep attack | YES | `challenges/02-sanitization/plant-fake-recipe.yaml`, `challenges/c3-secret-grep` |
| R1 | Leak customer data to the screen (S3 exfil CUT) | YES | `challenges/c1-exfil-s3` (chat/screen leak; Wendolyn prompt) |
| R1 | Fork bomb / the burn | YES | `challenges/c4-fork-bomb`; R1 clusters provision with `pod_pids_limit=-1` |
| R1 | Malicious image (Joker / grill zone) attack | GAP | no dedicated deploy-malicious-image scenario yet |
| R1 | Live "attack the room" view: S3 fills, process/`ls` feed, attack dashboard | GAP | Datadog Service Map exists; no S3 view, no Falco live-event feed, custom dashboards not fanned out (#25) |
| R1 | Gamified objective-gating ("order only if you succeed") + hints | GAP | order flow + easter egg exist; not gated on attack success |
| R2 | Turn guardrails on LIVE and re-run the SAME R1 attack | PARTIAL/MISMATCH | built beat-01 is resource-limits admission + RBAC + GitOps drift, not the exfil/image/exec thread |
| R2 | NetworkPolicy egress toggle vs the exfil attack | GAP | `gitops/apps/network-policies.yaml` deployed; no live toggle + re-run framing |
| R2 | Image-source/registry restriction toggle vs the malicious image | GAP | no registry-allowlist policy/toggle confirmed |
| R2 | Falco + Kyverno exec/`ls` block toggle | GAP | falco/falco-talon deployed; no live enforce toggle + re-run framing |
| R3 | Three in-browser tabs (BurritoBot / VTT / debug) | YES | VTT (#7) + BurritoBot (#8); multi-terminal in VTT |
| R3 | Local kubectl optional, tiny print + warning | YES (mostly) | `success.html` optional `<details>`; add "experienced users only" warning |
| R3 | Self-paced left-pane challenge instructions | YES | VTT challenge flow (#32) |
| R3 | Challenge 5 output sanitization (bat spit blocked) | YES | `challenges/02-sanitization/toggle-output-guard-on.sh` (#20) |
| R3 | Challenge 6 input classifier (PII/cost) | YES | `challenges/02-sanitization/toggle-input-classifier-on.sh` |
| R3 | Challenge 7 evil MCP | YES | `challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh` |

## Gaps to schedule
1. R2 re-frame as attack-mirrored live toggles: NetworkPolicy(egress)->exfil, registry-restriction->image,
   Falco/Kyverno->exec. This is the R2 half of #6/B11; the built beat-01 controls can stay as bonus walls.
2. R1 malicious-image (Joker/grill zone) attack scenario.
3. R1 live "attack the room" observability: S3-fill view, Falco process/`ls` feed, the curated attack
   dashboard fanned out per org (ties to #25).
4. R1 gamified objective-gating + hint system (order unlocks on objective success).
5. R3 "experienced users only" warning on the optional local-kubectl section.

## Rehearsal 2026-06-29 — confirmed design + fixes punch list

Captured from the Michael + Whitney run-through. Supersedes the S3 framing above.

### Confirmed design (the live shape)
- **Round model.** R1 = NO guardrails (attacks succeed, "watch it burn"). R2 = infra guardrails ON
  (same attacks, blocked by the platform). R3 + attendee = your own cluster; the AI guardrails
  (C5/C6/C7) are self-serve in the terminal.
- **System prompt is IDENTICAL across rounds.** Not changed R1->R2->R3. The agent still says "yes" to
  the attack; the only difference is the infra/AI guardrail blocking it. Apples-to-apples: we do NOT tell
  the agent the guardrail exists, so it tries and fails.
- **C1 = egress (network policy), NOT PII-to-screen.** S3 is dead, gone for good. The PII screen-leak is
  an AI/agency failure, not a network one, so it never exercised the egress NetworkPolicy. C1 is now the
  MARKETING-INTEL EXFIL: the agent POSTs confidential (non-PII) marketing intel to a partner webhook;
  the egress policy blocks it in R2/R3, open in R1. (Customer-PII version was refused by the model;
  marketing data is palatable.) **C1a (PII-to-screen) is DROPPED — keep only C1b (marketing exfil).**
- **C2 = malicious image deploy.** The model refuses an obviously-evil name ("Joker") but happily deploys
  it under a benign "promo/marketing" name (it does not evaluate the name). Kyverno registry allowlist
  (Enforce) blocks the deploy on R2/R3/attendee. Teaching: only trusted registries.
- **C3 = filesystem snoop for the secret recipe.** R1 finds the ingredient list; R2/R3/attendee must NOT.
- **C4 = fork bomb.** The MODEL will not run it, no matter the prompt. It "fails for a different reason."
  Tell attendees: challenge 4 was a fork bomb, the model refuses it, that is why it does not run (not the
  guardrail).
- **Datadog button** should deep-link to the agent-observability / a live trace (not the Datadog home).
- **Provisioning**: fake email -> claim cluster -> 3 buttons (BurritoBot / terminal / Datadog). Student
  view only (admin rows hidden).
- **Feedback form** (feedback.agenticburn.com): radio boxes (pacing; difficulty; recommend-to-a-friend) +
  one open-ended box + a keep-alive checkbox (extend access / do not reap in 1h).
- **Lifecycle reaper**: a cluster self-destructs ~1h after the workshop unless the attendee ticks the
  keep-alive checkbox on the feedback form.

### Fixes punch list (verify / explore / correct)
**Verify — built, confirmed live:**
- C2 image block Enforcing + joker deploy denied on r2/r3/attendee (leftover promo-mascot cleaned on all 11).
- C5 recipe leak + redact-on-reprint (confirmed in rehearsal).
- R2 banner = infra-only. falcosidekick OOM fixed (Falco->Datadog restored, all 11).

**Correct — in flight / needed:**
- **C1 deploy not landing**: ai-layer reports Synced + Healthy, but the live workshop-mcp-src ConfigMap,
  Agent-CR systemMessage clause, and marketing.json are NOT updated (ArgoCD repo-server render staleness).
  Force a clean re-render + Agent-CR recreate so C1 marketing-exfil goes live on all 11.
- **C1a removal**: drop the PII-to-screen step from lab.html; keep only the marketing exfil.
- **Egress R1-off**: add allow-all egress on the r1 clusters so the C1 exfil SUCCEEDS in R1 (the "before");
  R2/R3 keep the allowlist (blocked). Egress half of ROS-gap #40.
- **C3 block-by-default**: the filesystem snoop must not work on R2/R3/attendee (Falco hard-block via
  Talon/KubeArmor, or no bait seeded on guarded clusters).
- **C4 instruction note**: state the model refuses the fork bomb (so it won't run; not a guardrail).
- **Datadog deep-link**: point the Datadog button at the agent-observability trace page.

**Explore:**
- **Supply-chain info leak**: the agent volunteers inventory/supplier intel (per-burrito counts, named
  providers). Egregious disclosure; candidate extra teaching/attack.
- **"Printed to terminal not chat"**: when asked to print customer data, the agent did something other
  than chat-print — verify the behavior.
- **Provisioning student view**: confirm admin rows are hidden in the student view.

## Source transcript

The verbatim Michael + Whitney voice transcript that originally lived here has been **moved out of the
repo** (it drove the now-superseded S3 framing and was causing stale-context confusion). It is preserved
in git history and in the session scratchpad archive
(`repo-transcripts-archive/RUN-OF-SHOW-WHITNEY-2026-06-29.embedded-transcript.md`). Do not re-embed it;
this reconciliation doc is the live record.
