# Watch It Burn, start here (for Whitney)

Everything you need to start. The platform is built (live verification is on the provisioning track);
the docs below are current and the talk materials are drafts for your input.

## The talk

"Build a Platform, Unleash an Agent on it... and Watch it Burn!" Attendees drive an AI agent against a
real Kubernetes platform and watch what the guardrails catch and what slips through. We regroup and
hand them a governance map for their own platform.

## Confirmed slot

Day 1 (Workshop Day), 2:20 to 4:20pm, Track 5. Two hours. Co-speakers: Michael Forrester and you.
Note: the public schedule currently lists Michael solo; Michael has emailed the organizers to add you.

## The repo

All of it (platform as code, plus these docs) lives here:
https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn

The repo is private. To open the link you need to be a GitHub collaborator. If you cannot get in, send
Michael your GitHub username and he will add you.

## The shape of the 2 hours (three clusters, three canonical attacks)

Clusters 1 and 2 run the same three attacks (your structure): (1) exfiltrate customer data, (2) deploy
a villain app, (3) fork-bomb the cluster.

1. Cluster 1, no guardrails: all three succeed; the live cost counter climbs; the fork bomb kills it.
2. Cluster 2, the CNCF controls a mature team runs: the same three are blocked, each by a DIFFERENT
   control (NetworkPolicy egress, Kyverno registry-allowlist, a per-pod PID limit), but the bill still moved.
3. Cluster 3, each attendee's own: they switch on the agent-specific guardrails (input/output/MCP) and
   play the AI-layer games (beat-the-bouncer, tower-defense, trace re-leak hunt, poisoned MCP). Then the map.

Telemetry is Datadog-primary (you drive it; each attendee gets their own); Grafana/Tempo is the fallback.
Demo cluster URLs live on agenticburn.com. The full attack-to-control mapping is in "Control rationale" (doc 9).

## Your part

Working co-speaker split (confirm or change it): Michael takes architecture, the security thesis, and
the cost argument; you take the live attack narration, the observability view (Datadog), and the
attendee experience. You also introduce the CNCF security projects at Cluster 2 as they turn on. The
run-of-show marks every hand-off.

## What is in this folder (numbered in reading order)

- **2, Abstract:** the accepted talk abstract (source of truth for what we promised).
- **3, Run of Show (demo flow):** the minute-by-minute 2-hour runbook with hand-offs and toggles.
- **4, Slide Outline:** the deck outline, slide by slide, with speaker cues.
- **5, Cold Open Script:** the word-for-word opening for the first three minutes (the hook).
- **6, Build Spec (technical reference):** the full platform build spec. Background, not required reading.
- **7, Stack Walkthrough:** the mental-model map, every technology, its role, where it is wired, and
  what mechanism invokes what. This is the answer to "what is the mechanism?", start here for the tech.
- **8, Challenges (games):** the three canonical attacks + the Cluster-3 games + the scoring overlays.
- **9, Control rationale:** for each attack, which control actually stops it and where a sharp attendee pushes.
- **Comment Archive (backup):** a verbatim backup of your comments + every reply, so nothing is lost.
- **Archive (older versions):** superseded drafts, moved out of the way.

## A few things worth your input (the open agenda; also tracked in the repo)

- The co-speaker split above, and your narration story for the Cluster-3 AI-guardrail layer.
- Central observability for narration: each attendee is in their own Datadog and it lags, so how do we
  show the room a live view? (The games resolve on signals the room sees directly to work around this.)
- Whether attack 1 gets a "sniff the stream" variant so Istio mTLS gets its own beat.
- Villain app: registry-allowlist only, or add cosign/Harbor signing.

Decided already: staying on VPC-CNI + Istio (not Cilium); the trace re-leak trap is explained in docs 7 and 9.
