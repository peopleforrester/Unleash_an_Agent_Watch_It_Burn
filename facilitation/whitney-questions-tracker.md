<!-- ABOUTME: Tracker for Whitney's Google Doc comments: what we answered (and where) vs what is still -->
<!-- ABOUTME: open for a Michael + Whitney conversation. The pointer-replies in the Docs are not full answers. -->

# Whitney comment tracker

Status of every comment Whitney left (Run of Show = RoS, Build Spec = BS). "Answered" means a concrete
build change or a written answer exists at the cited place. "OPEN" means it needs a Michael + Whitney
conversation, not just a doc. The `[Build update]` reply-pointers in the Docs are summaries, not the
full answer; the real answers live in `docs/STACK-WALKTHROUGH.md` and the files below.

| # | Doc | Her point (short) | Status | Where / next step |
|---|---|---|---|---|
| 1 | RoS | No clear story for Cluster 3; "I don't know these technologies" | **OPEN** | STACK-WALKTHROUGH helps; she still needs a narration script + a walk-through working session |
| 2 | RoS | Will the gateway block prompts in Datadog? show prompt before/after gateway | **OPEN** | guard-proxy sits in front so it is demoable; confirm against her Datadog |
| 3 | RoS | Public endpoint; trade endpoints; break each other's cluster | **Captured** | added as optional partner-break challenge (runbook); public-endpoint mechanism OPEN |
| 4 | RoS | "also cost" on the dashboard | **Answered** | cost panel in `agent-observability` dashboard |
| 5 | RoS | Each attendee their own Datadog; no central view to narrate from | **OPEN** | Datadog wired primary; the central-narration-view limitation is unsolved |
| 6 | RoS | MCP restriction mechanism? kmcp? platform level? | **Answered** | STACK-WALKTHROUGH (kagent toolNames + agentgateway authz) |
| 7 | RoS | Input san same tech? kgateway? caching? | **Answered** | WALKTHROUGH (guard-proxy + LLM Guard; agentgateway not kgateway); caching in BUILD-SPEC §1 |
| 8 | RoS | Output san tech? an Agent Gateway? | **Answered** | WALKTHROUGH (guard-proxy + LLM Guard Regex sidecar) |
| 9 | RoS | Maintenance cost, not just spend | **Answered** | BUILD-SPEC §1 thesis augment |
| 10 | RoS | Be specific about the walls; S3 exfil basketball | **Captured** | walls in governance-map; ESO/S3 game in runbook; difficulty spike OPEN |
| 11 | RoS | Tour CNCF projects as they turn on; she explains some | **Answered** | runbook reveal structure (Cluster 2 tour) |
| 12 | RoS | Platform tour should be guards-OFF | **Answered** | runbook 0:00 section |
| 13 | RoS | Datadog not Grafana; Falco later; plant secrets to challenge | **Answered/Captured** | Datadog primary; CNCF intro deferred; secrets-as-challenge in the games |
| 14 | RoS | "trace re-leak trap, what's this?" | **Answered** | WALKTHROUGH naming clarifications |
| 15 | RoS | "I'll talk about the CNCF guardrails added here?" | **Answered** | yes, the Cluster 2 tour is her segment (runbook) |
| 16 | RoS | CNCF vision (Harbor/signing/mesh/SPIFFE/OTel); prompt the agent re guardrails | **Partly** | image-signing policy added; "tell agent its jail" in thesis; **service mesh (Istio) + SPIFFE/SPIRE scope is OPEN** |
| 17 | RoS | Attack paths / challenge ladder; funny secrets; scrape Datadog fast | **Captured/OPEN** | challenge ladder in runbook; **Datadog lag for live viewing is an OPEN staging problem** |
| 18 | BS | "I don't see building the agent itself" | **OPEN** | agent IS built (kagent Agent spec); do we document/demo *building* it? |
| 19 | BS | "Datadog and OTel" | **Answered** | Datadog wired primary in the collector |

## The open list to talk through (the real agenda for the next Michael + Whitney sync)

1. **Her narration story + comfort with the AI-guardrail layer** (#1) — a working session against the walkthrough.
2. **Central observability for narration + Datadog real-time lag** (#5, #17) — how do we show the room a live view when each attendee is in their own Datadog?
3. **Datadog before/after-gateway prompt visibility** (#2) — design + confirm.
4. **Service mesh (Istio) + SPIFFE/SPIRE scope** (#16) — how far do we take it? (research spike says SPIFFE narrated, not live.)
5. **Do we cover/demo building the agent itself** (#18)?
6. **Difficulty spikes for the games + challenge ladder** (#3, #10, #17) — confirm each level is achievable as intended.
