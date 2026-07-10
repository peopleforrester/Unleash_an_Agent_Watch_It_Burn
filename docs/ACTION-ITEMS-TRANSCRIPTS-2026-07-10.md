# Action Items from 2026-07-10 Transcripts

Source: 5 workshop planning/dry-run transcripts (Whitney Lee + Michael Forrester),
routed by the transcription pipeline to `Kubecon-NA-2026-Whitney-BurritoBot/transcripts/`.
Extracted 2026-07-10. Scope of this doc: the platform/infra/provisioning/guardrail work
that lives in THIS repo. Pure run-of-show/presentation items are listed briefly at the end
since they belong to the presentation, not the platform.

Priority key: P0 = broke or missing in the dry run, blocks the next run. P1 = needed for the
workshop, not yet built. P2 = design decision to lock. R = research/verify before building.

---

## P0 — Broke in the dry run (fix before the next run)

- **P0-1 Provisioning email-claim is broken.** Entering an email does not provision/return a
  cluster; must return the SAME cluster on repeat visits for a given email. Whitney hit this
  live. [provisioning-app] (T5)
- **P0-2 Round 2 guardrails did not fire. ROOT CAUSE FOUND (2026-07-10).** `fleet.sh instructors up`
  runs `bootstrap_one` -> `deploy-full-idp.sh <profile>` and then STOPS. It never runs
  `infra/setup-instructor-cluster.sh <cluster> <round>`, which is the round-arming step that flips
  the Kyverno ClusterPolicies (`require-resource-limits`, `restrict-image-registries`) from Audit to
  Enforce. Kyverno ships in **Audit** (kyverno-policies.yaml: "the demo flips ... Audit<->Enforce"),
  so admission logs but never blocks. `setup-instructor-cluster.sh` is referenced ZERO times in
  fleet.sh and deploy-full-idp.sh. Result: any fleet-provisioned cluster (R1, R2, R3 alike) comes up
  with Kyverno in Audit -> every deploy succeeds. That is exactly Whitney's "R2 deployed freely."
  Secondary: the roster sets ALL rounds (incl. R1) to the `full` bootstrap profile, so without the
  round toggle R1 and R2 clusters are effectively identical (full app-of-apps, Kyverno Audit) and
  there is no guardrail difference between rounds at all.
  - **FIX:** wire the round toggle into provisioning. `bootstrap_one` knows the round (roster `round`
    column); after `deploy-full-idp.sh` returns, call `setup-instructor-cluster.sh <cluster> <round>`
    (or inline its Kyverno-Enforce flip for R2/R3). Then a provisioned R2 cluster is armed with no
    manual step.
  - **STILL TO VERIFY LIVE (needs a cluster):** whether the egress default-deny NetworkPolicy
    (`gitops/apps/network-policies.yaml`) comes up enforcing from the full app-of-apps or is also
    gated. VPC-CNI `enableNetworkPolicy=true` IS set in terraform, so NetworkPolicies are enforced
    in-kernel; this is NOT a Cilium question (the repo uses native VPC-CNI, settling transcript R-2).
    If R1 exfil is meant to succeed, either R1 must use the `burn` profile or the egress policy is
    round-gated too. Confirm on the next live cluster. [guardrails/policy + infra] (T5)
- **P0-3 Agent output goes to the terminal, not the BurritoBot chat.** Students must see results
  in the chat pane. [agent/model] (T5)
- **P0-4 Fork-bomb challenge (C4) has no working payload.** Even Nova refuses to run the fork
  bomb despite explicit prompting. Decide: reframe the ask so the model complies (the same trick
  that beats the "Joker" image-name refusal by calling it a "marketing/promo image"), or keep C4
  and surface a hidden/verbal note that the model declined. Ties to the model-refusal taxonomy in
  DECISION-LOG.md. [agent/model] (T5, T2)

## P1 — Platform build gaps

- **P1-1 Redesign Challenge 1 as a pure egress-NetworkPolicy demo.** S3 exfiltration is CUT (could
  not get the model to write to S3 without manual setup). Replace with an innocuous outbound call
  the model will happily make (a health-check/uptime curl to a status URL) so the egress policy is
  what blocks it, decoupled from PII/social-engineering. [guardrails/policy] (T5, T4)
- **P1-2 Stand up a collector URL for the C1 egress target** (on apex `agenticburn.com` or
  elsewhere) so the health-check curl reads as a legitimate poll that egress then blocks.
  [apex/routing + infra] (T5)
- **P1-3 Embed copy-paste curl/attack commands into the on-screen challenge instructions**, shown
  beside BurritoBot. Not there yet. (Uses the curl fixture from PRD 37.) [provisioning-app] (T5, T4)
- **P1-4 Build the three AI-guardrail challenges (R3):**
  - C5 OUTPUT sanitization: block the agent from echoing a pasted credit-card number (and from
    asking follow-ups like CVV). Teaching point: the value already leaked into traces/spans/logs,
    so output-only blocking means costly secondary cleanup.
  - C6 INPUT sanitization: regex/format block PII (credit-card, SSN) before the LLM sees it. The
    cheaper correct fix; still needs the output guard as backstop.
  - C7 typosquatted-MCP supply-chain attack: a well-meaning insider installs a look-alike public
    MCP server that exfiltrates recipe/order data, poisons reorders, and injects tool-enumeration +
    shell-exec. Mitigation = an Agent Gateway MCP tool allow-list at the harness level (unauthorized
    tools never presented to the LLM); Falco tool-run detection as secondary.
  - Order: OUTPUT (C5) before INPUT (C6); C7 last. [agent/model + guardrails/policy] (T3, T1)
- **P1-5 Build the feedback form at `feedback.agenticburn.com`, surfaced on the provisioning page**
  so submissions are tied to the student. ~3-4 quick questions (pacing, difficulty, would-recommend,
  one more) + one open-ended box. Note the apex already has a `feedback.agenticburn.com` route
  (commit 16acea2), so routing is partly in place. [provisioning-app] (T5)
- **P1-6 Cluster auto-destruct + feedback-checkbox time extension.** Cluster expires ~1 hour after
  the conference unless the student checks an extend box on the feedback form (which programmatically
  extends access); let them specify how much time. Pin down exact auto-destruct timing. [provisioning-app
  + infra] (T5)
- **P1-7 Deep-link the Datadog button to the agent-observability trace page**, not the generic
  landing. Michael to supply the exact URL. [provisioning-app + observability] (T5)
- **P1-8 Rebuild the lab-instructions UI** (retire the placeholder React list) as a side-by-side lab
  view with a home page linking all labs and a per-student milestone checklist. Audit what already
  exists in the provisioning app first to avoid duplicate work. [provisioning-app] (T3)
- **P1-9 Clean up the student preview** so students see only the student view (hide admin rows below
  the fold). [provisioning-app] (T5)
- **P1-10 Falco rule for filesystem snooping** (e.g. `ls` on a production node) that alerts through
  to Datadog; payoff for the C3 decoy-file hunt. [guardrails/policy + observability] (T3)
- **P1-11 C3 decoy-file secret hunt as a plain file on the container filesystem** (not a Kubernetes
  secret; real secrets stay in External Secrets Operator, unreachable). Misleading breadcrumb dir
  names; give students a hint. [guardrails/policy] (T3)
- **P1-12 Live room-wide attack-visibility dashboards in Datadog** (attacks landing across the room,
  an exfil/data-landing view, a per-attendee process/`ls` view). Several flagged feasibility-uncertain;
  scope before committing. [observability] (T4, T2)
- **P1-13 Prompt capture + replay across rounds** (save the winning prompt, select by round via a
  dropdown, replay R1 prompt against R2/R3) and an optional sanitized prompt-stream/library with
  click-to-inject. Nice-to-have. [provisioning-app] (T2, T1)

## P2 — Design contracts that drive the backend (NOT presentation-only)

These are the challenge/round design decisions that the platform code must implement. They are
tracked engineering here because the walkthrough/rounds are downstream of this code and will not be
updated until the backend is done. The challenge implementations already live in `challenges/`
(01-cncf-wall, 02-sanitization, 03-bad-mcp = C1/C2, C5/C6, C7) and the round toggles in
`infra/setup-instructor-cluster.sh`. The only genuinely presentation-owned items are the narrative
wrappers: the cold-open wording (P2-5 brand safety) and the secret-sauce framing (P2-4).

- **P2-1 Challenge structure = 4 infrastructure challenges (R1 all succeed → R2 block C1-C4) + 3 AI
  challenges (R3 = C5-C7 hands-on).** The old "7 challenges" framing was wrong. No cluster-hopping
  mid-round. System prompt unchanged R1→R2 (apples-to-apples; infra layer does the blocking). (T3, T2, T5)
- **P2-2 R2 challenge→control map:** C1 egress/NetworkPolicy, C2 Kyverno admission (malicious image;
  teach that registry-restriction alone is bypassable, so add signing/attestation), C3 Falco eBPF
  (filesystem/secret read). (T3, T2, T5)
- **P2-3 R3 = "minimal AI guardrails" active**; students attack, then toggle input/output guards that
  self-describe what they block. (T3)
- **P2-4 "Secret sauce / secret ingredient" narrative through-line** seeded from the intro; reconcile
  it with the credit-card PII token so C5/C6 is one coherent story. (T3)
- **P2-5 Brand safety:** anonymize the burrito-company cold-open anecdote (show the third-party post,
  never say the brand aloud); vet the "secret recipe" ingredient gag. (T2, T4)
- **P2-6 Timing vs the 60-minute format:** own estimate runs an hour+ for R1-R2 alone. Defer cuts to a
  full timed rehearsal rather than pruning now. R2/R3 pacing: presenters walk it live up front,
  self-explorers put on headphones. (T2, T3, T5)

## R — Research / verify before building

- **R-1 Agent Gateway (LF Agentgateway) — confirm the project exists and how to configure MCP tool
  allow-listing** at the harness level. Blocks C7. (T3)
- **R-2 Cilium / CNI on R2:** is Cilium the CNI, is it running, and is NetworkPolicy enforcement
  automatic or a manual enable? Directly tied to P0-2. (T4, T5, T2)
- **R-3 MCP tool-enumeration + shell-exec/web-fetch exploit mechanics** for C7. (T3)
- **R-4 Verify detection-vs-prevention claims** for Falco/Tetragon/KubeArmor on a live cluster before
  they go into the teaching narrative (the "ms between detection and enforcement" caveat). (T2)

## Connection to existing repo roadmap

- **Multi-cloud (GCP + Azure) is now a live audience promise.** Presenters plan to tell attendees the
  repo "will be updated for GCP and Azure shortly." This is exactly PRD 35 M2 (Azure) and M3 (GCP),
  which are queued but unbuilt. The promise raises their priority and adds an over-promise risk if
  they slip. (T5)
- **PRD 37 (curl fixture)** underpins P1-3 and P1-1 (the egress curl). Already on main.
- **Nova-everywhere** is validated, but P0-4 shows Nova still refuses the fork bomb — a model-refusal
  case the reframe rule (DECISION-LOG.md) should cover.
- **§4.6-d (per-cluster model tier)** remains deferred; nothing in the transcripts revives it.
