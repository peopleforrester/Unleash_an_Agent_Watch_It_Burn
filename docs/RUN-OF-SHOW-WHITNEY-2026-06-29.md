# Run-of-Show Reaffirmation, Michael + Whitney, 2026-06-29

Captured from a Michael + Whitney working conversation (voice transcript at the end of this file,
verbatim, as history). This reconciles that conversation against the built repo and confirms which
run-of-show elements are covered and which are gaps. It supplements (does not replace)
`facilitation/runbook.md` and `docs/RUN-OF-SHOW-AND-BACKLOG-2026-06-27.md`.

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
| R1 | Exfiltrate customer data to S3 | YES (scenario) | `challenges/c1-exfil-s3` |
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

## Source transcript

(verbatim transcript removed from history)
