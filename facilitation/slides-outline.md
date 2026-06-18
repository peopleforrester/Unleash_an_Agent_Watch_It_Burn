*Slide outline for the 2-hour workshop. Story-driven, opens with the why. Titles are agent-forward and do not reveal which attacks get blocked or leak; that lands live. No punchline giveaways, no non-public framework names. Attendee-facing.*

# Slides Outline

2-hour slot (Day 1, 2:20–4:20pm, Track 5). Speaker cue per slide: (M) Michael, (W) Whitney, (M+W) both.
Slides marked "built live" carry only a title; the work happens on the cluster.

**Narrative arc:** a real failure (why) leads to a promise (we built you a platform to break), which
plays out across three clusters (it burns, it gets blocked but still costs, you guard it yourself),
turns once more (the door you did not think to guard), and lands on a map you take home.

## 1. Title (M)
- "Build a Platform, Unleash an Agent on it... and Watch it Burn!"
- Michael Forrester (Accenture), Whitney Lee. AI Engineer World's Fair 2026.

## 2. The night an agent deleted my cluster (M) [THE WHY]
- Open cold with the story: I gave an AI coding agent real access to a Kubernetes cluster. It deleted
  the cluster.
- That sent me looking for what actually stops an agent, versus what we only assume stops it.
- One line of stakes: this is no longer hypothetical for anyone in this room.

## 3. You are already doing this (M)
- Teams are handing agents access to real infrastructure right now.
- The honest question: when your agent does something it should not, does anything actually catch it?

## 4. So we built you a platform to break (M)
- You each get a real internal developer platform and an agent with access to it.
- Your job for the next two hours is to make the agent break something. We watch what holds.

## 5. The platform you get (M)
- A running IDP: Argo CD, Kyverno, Falco, Prometheus, Grafana, Tempo, Loki, cert-manager,
  External Secrets, Backstage. You did not build it, and it is yours to keep.

## 6. How we watch it happen (W)
- One dashboard shows the agent's input, its output, and the tools it calls.
- The same view carries every attack, so you see exactly where each one lands or dies.

## 7. Cluster 1: take the guardrails off (W) (built live)
- Point the room at an unprotected cluster and let it rip.

## 8. The bill nobody mentions (M)
- A live counter shows the cloud spend climbing the whole time the agent thrashes.
- Wasted tokens are a denial-of-service problem, not just a security one.

## 9. Cluster 2: the controls you should already have (W narrates, M on cost) (built live)
- The same attack, now against the platform controls. Watch it get stopped.
- Then look at the counter: you were protected, and you still paid.

## 10. Cluster 3: your cluster, your guardrails (W + M) (built live)
- On your own cluster, switch on the agent-specific guardrails one at a time: output, then input,
  then tool restriction.
- Watch each one change the agent's behavior, and the spend, on the dashboard.

## 11. The door you did not think to guard (W narrates, M on the fix) (built live)
- You filtered the response. The same secret can still leak somewhere you were not watching.
- The trace re-leak trap, and the symmetric fix.

## 12. The map (M)
- Every attack, the control that stops it, the layer it lives in, and whether you already run that control.

## 13. Most of this you already have (M)
- The large share is governed by tools many teams already run.
- A small share is not, and that small share is where agents change the threat model.

## 14. Take it home (M+W)
- The repo is the whole platform as code.
- A governance map and a self-assessment checklist to run against your own platform on Monday.

## 15. Thanks and questions (M+W)
- Repo link and contact.

---

## Build notes (not slides)
- This is the outline. The deck (Google Slides / Keynote) is built from it; slides 7, 9, 10, 11 are
  live demos with only a title card.
- Optional next step: per-slide speaker notes for Whitney, and a 2-minute cold-open script for slide 2.
