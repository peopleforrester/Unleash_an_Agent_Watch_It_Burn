*Slide outline for the 2-hour workshop. Titles are agent-forward and do not reveal which attacks get blocked or leak; that lands live. No punchline giveaways, no non-public framework names. Attendee-facing.*

# Slides Outline

2-hour slot (Day 1, 2:20–4:20pm, Track 5). Speaker cue per slide: (M) Michael, (W) Whitney, (M+W) both.
Slides marked "built live" have no content beyond the title; the work happens on the cluster.

## 1. Title (M)
- "Build a Platform, Unleash an Agent on it... and Watch it Burn!"
- Michael Forrester (Accenture), Whitney Lee. AI Engineer World's Fair 2026.

## 2. You already gave an agent the keys (M)
- Teams are handing AI agents access to real infrastructure.
- The question is what stops the agent when it does something it should not.

## 3. The platform you get (M)
- A running internal developer platform: Argo CD, Kyverno, Falco, Prometheus, Grafana, Tempo, Loki,
  cert-manager, External Secrets, Backstage.
- You did not build it, and it is yours to take home.

## 4. How we watch (W)
- One dashboard shows the agent's input, its output, and its tool calls.
- The same view carries every attack in the room.

## 5. Three clusters, one question (M)
- Cluster 1: no guardrails. Cluster 2: the platform controls. Cluster 3: your own, with agent
  guardrails you switch on.
- No outcomes on the slide.

## 6. Cluster 1: take the guardrails off (W), built live
- The room attacks an unprotected cluster through the chat.

## 7. What an unguarded agent costs (M)
- A live counter shows the cloud bill climbing while the agent runs.
- Wasted tokens are a denial-of-service problem.

## 8. Cluster 2: the controls you should already have (W narrates, M on cost), built live
- The same attack runs against the platform controls.
- Note where the cost counter ends up.

## 9. Cluster 3: your cluster, your guardrails (W + M), built live
- Switch on output filtering, then input filtering, then tool restriction.
- Watch each one change the agent's behavior, and the cost, on the dashboard.

## 10. The second open door (W narrates, M on the fix), built live, uses the back half of the slot
- You filtered the response. The question is whether you covered every place the response gets written.
- The trace re-leak trap.

## 11. The map (M)
- Each attack, the control that stops it, the layer it sits in, and whether you already run it.

## 12. Most of this is already handled (M)
- The large share is covered by tools many teams already run.
- A small share is not, and that is where agents change the picture.

## 13. Take it home (M+W)
- The repo is the platform as code.
- A governance map and a self-assessment checklist to run against your own platform.

## 14. Thanks and questions (M+W)
- Repo link and contact.
