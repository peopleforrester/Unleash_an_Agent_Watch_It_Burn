# Watch It Burn, Design Decisions & Reconciliation

> **Amended 2026-06-28** by [docs/UI-FEEDBACK-2026-06-28.md](UI-FEEDBACK-2026-06-28.md) — point-by-point UI feedback from the Michael + Whitney walkthrough (BurritoBot, VTT, provisioning). Read it alongside this doc.


Source of truth for the *evolved* design captured in the Michael + Whitney planning
transcript (`docs/transcripts/watch-it-burn-planning.md`), reconciled against what was
already built and live-verified (`BUILD-SPEC.md` rev3, `PROJECT_STATE.md`).

The transcript post-dates rev3 and **changes the workshop shape**. rev3's components are
validated, but the *structure* below supersedes rev3's single-aggregate-beat / 90-min framing.
A rev4 of BUILD-SPEC should fold these in.

## What changed vs the build (headline)

- **Content is 60 minutes** (cut from 120 on 2026-06-25). The booked room is a 2-hour window (Day 1, 2:20–4:20pm, Track 5). Compress to ~1–2 of the CNCF "80%" + 2–4 AI-specific guardrails.
- **Structure is a three-cluster spectacle**, not one aggregate beat.
- **Cost / wasted-token DoS is now a central theme**, brand new vs rev3.
- **Observability (input + output + tool calls on a live dashboard) is the headline payoff**, not just a lens, "even with no guardrails, seeing the prompts and tool calls melts their brains."

## The three-cluster run-of-show (the core design decision)

1. **Cluster 1, no guardrails (facilitator-run, disposable).** Attendees attack via the **chatbot only** (no kubectl). Gets wrecked in ~5 min. On-screen **cost counter** shows Bedrock spend climbing → teaches "wasted tokens are the new DoS." Run **3 instances**, rotated as they burn ("URL one's gone, here's two…"). A **minimal floor** keeps it from dying in one trivial prompt.
2. **Cluster 2, CNCF guardrails only (pre-AI: Kyverno/Argo/Falco).** The destruction is blocked (no blast radius; agent can only read) **but the cost is still incurred** → "Kyverno is the last mile and the *most expensive*, you already burned GPU + API by the time admission denies it."
3. **Cluster 3, each attendee's own (full stack + AI guardrails they switch on).** Always-deployed kagent. Attendees turn guardrails on themselves (it's a workshop), in order:
   - **Step 1, output sanitization:** blocks dangerous tool calls (e.g. `kubectl delete`) downstream; human-in-the-loop escalation + notification. Catches the badly-scoped-agent mistake.
   - **Step 2, input sanitization:** a small **classifier model + block list** catches "delete" intent **before the LLM** → no wasted Bedrock spend. Security *and* cost.
   - **Step 3, MCP tool restriction:** a malicious/misconfigured MCP server (the "cloud-native clown file" that drops a manifest Argo picks up) → block via **MCP registry + MCP gateway + AI gateway**; don't run unregistered MCP tools. (Stat hook: ~67% of public MCP servers have security holes, Snyk.)
   - Plus **AI gateway + caching** for the cost story.

## Confirmed design decisions

- **Agent:** kagent, **Bedrock** backend (Claude or Nova, "certain level of sophistication," avoid attaching a GPU). Web chat interface **and** direct kubectl. System prompt = a **chaos-engineering agent** whose job is to break the guardrails.
- **Pre-provisioned platform:** everything is up before attendees connect; **ArgoCD sync-waves** order by dependency. **Crossplane was tried and removed.**
- **Guardrail tech preference:** kagent + **vLLM integration calling a classifier model on Bedrock**. Nemo Guardrails / LLM Guardrails are acceptable/standard but Michael prefers the kagent+vLLM→classifier path (not bound to CNCF-only tooling since the event is AI Engineer, not a CNCF conf).
- **Cost as a first-class teaching point:** live Bedrock cost counter; wasted-token DoS; metering/caching/rate-limiting/AI-gateway framed as "old problems, AI doesn't change them."
- **Attendee takeaway:** the repo is theirs ("feed it to Copilot/Claude Code/codex; deploy a near-production experience"); README has run instructions.
- **Access pattern:** drive demo (burn) clusters via chatbot only; drive your own Cluster 3 via chatbot **and** kubectl.

## Gamification / spectacle

- Stream attendees' **system prompts live on screen**; "if the screen goes black, somebody won." Sanitize the streamed prompts (code of conduct).
- Possible external **red-team hook** ("do your most sophisticated attack against the CNCF tooling").

## Decisions resolved 2026-06-17 (Michael)

- **Model:** Claude on Bedrock (haiku-4-5 verified; final tier TBD).
- **Guardrail impl:** kagent / CNCF-native preferred, NOT a bespoke vLLM→Bedrock classifier.
- **Backstage:** nice-to-have (include if feasible).
- **External red-team:** No.
- **Fleet counts:** 3× Cluster 1, 3× Cluster 2, 3× instructor Cluster 3 (one per model tier, run side
  by side for the chaos-engineering comparison), per-attendee Cluster 3 + a few
  reserve. (Was "~10 disposable", now 3× Cluster 1, rotated as they burn.)
- **Minimal restriction floor** on every cluster: no one-shot trivial kill (Cluster 1 burns gradually),
  and follow-along attendees can't accidentally nuke the instructor clusters.

## Still open

- Final Claude tier (haiku-4-5 vs larger), sophistication vs per-attendee cost.
- Co-speaker split with Whitney.
- OTel re-leak advanced beat, build vs slide-only.
- The exact "minimal floor" mechanism (RBAC / quota / admission).
- AI gateway + caching product choices.

## Reconciliation with what is already live-verified (rev3 build)

| Transcript element | Built / verified? |
|---|---|
| Cluster 2 CNCF blocks (Kyverno admission, RBAC, ArgoCD drift) | ✅ verified live (Beat 1 / `verify/beat-01.sh`) |
| kagent agent on Bedrock, web/A2A | ✅ verified live (answered via Bedrock) |
| Output sanitization (block exfil/secret) | ✅ verified live (LLM Guard Regex via guard-proxy) |
| Input sanitization (block injection) | ✅ verified live (LLM Guard PromptInjection), but transcript wants a **cost-saving classifier + block list**, not just injection detection |
| MCP tool restriction | 🔄 in progress (evil-mcp-shim + RemoteMCPServer deployed; toolNames allowlist is the control) |
| Three-cluster spectacle + ~10 disposable burn clusters | ❌ not built (rev3 was per-attendee spokes, no facilitator burn clusters) |
| Live cost counter / wasted-token DoS | ❌ not built (new theme) |
| Tool-call blocking with HITL + notification | ❌ partial (guard-proxy blocks; no HITL/notify yet) |
| System-prompt streaming display | ❌ not built |

## Implied tasks / next steps (for triage with Michael)

1. **Rev4 the BUILD-SPEC** to the 2-hour three-cluster run-of-show + cost theme (supersede rev3's structure; keep verified components).
2. **Update the abstract** (Michael said he would, the run-of-show is now concrete).
3. Design the **disposable burn-cluster fleet** (~10) + fast re-provision (the 15-min re-provision caveat).
4. Build the **live Bedrock cost counter** + on-screen display.
5. Build the **input classifier + block list** (classifier on Bedrock via kagent/vLLM), cost-saving guard.
6. Build **output tool-call blocking + human-in-the-loop + notification**.
7. Finish **MCP tool-restriction** beat (in progress) + the malicious-MCP "clown file → Argo" demo.
8. Build the **system-prompt streaming** UI (gamified) + its sanitization.
9. Decide the **open questions** above (Backstage, model, guardrail impl, red-team).
