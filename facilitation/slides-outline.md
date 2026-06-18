*Slide outline for the 2-hour workshop. Story-driven, opens with a two-tier why (personal incident, then enterprise stakes). Titles are agent-forward and do not reveal which attacks get blocked or leak; that lands live. No punchline giveaways, no non-public framework names. Attendee-facing.*

# Slides Outline

2-hour slot (Day 1, 2:20–4:20pm, Track 5). Speaker cue per slide: (M) Michael, (W) Whitney, (M+W) both.
Slides marked "built live" carry only a title; the work happens on the cluster.

**Narrative arc:** a personal failure (why, tier 1) scales to enterprise stakes (why, tier 2), which
sets up a promise (we built you a platform to break). That plays out across three clusters (it burns,
it gets blocked but still costs, you guard it yourself), turns once more (the door you did not think
to guard), and lands on a map you take home.

## 1. Title (M)
- "Build a Platform, Unleash an Agent on it... and Watch it Burn!"
- Michael Forrester (Accenture), Whitney Lee. AI Engineer World's Fair 2026.

## 2. The night an agent deleted my cluster (M) [WHY, tier 1: personal]
- Open cold with the story: I gave an AI coding agent real access to a Kubernetes cluster. It deleted
  the cluster.
- It stung, but it was my sandbox. The recovery was a weekend rebuild.

## 3. Now give it production stakes (M) [WHY, tier 2: enterprise]
- That was a sandbox. Change one thing: the agent has that access in production.
- The blast radius is no longer a rebuild. It is the business:
  - Customer data read and sent somewhere it should not go.
  - Revenue lost to an outage the agent caused.
  - Reputation and trust, gone in one incident.
  - Compliance and regulatory exposure from an action no human approved.
  - A cloud bill that runs the entire time the agent thrashes.
- And it is not one cluster. It is a shared enterprise network of hundreds of thousands of identities
  and their agents, none of which you fully control. You have to guard your system against the system.

## 4. You are already doing this (M)
- Teams are handing agents access to real infrastructure right now.
- The honest question: when your agent does something it should not, does anything catch it before it
  costs you?

## 5. So we built you a platform to break (M)
- You each get a real internal developer platform and an agent with access to it.
- Your job for the next two hours is to make the agent break something. We watch what holds.

## 6. The platform you get (M)
- A running IDP: Argo CD, Kyverno, Falco, Prometheus, Grafana, Tempo, Loki, cert-manager,
  External Secrets, Backstage. You did not build it, and it is yours to keep.

## 7. How we watch it happen (W)
- One dashboard shows the agent's input, its output, and the tools it calls.
- The same view carries every attack, so you see exactly where each one lands or dies.

## 8. Cluster 1: take the guardrails off (W) (built live)
- Point the room at an unprotected cluster and let it rip.

## 9. The bill nobody mentions (M)
- A live counter shows the cloud spend climbing the whole time the agent thrashes.
- Wasted tokens are a denial-of-service problem, not just a security one. (Callback to slide 3.)

## 10. Cluster 2: the controls you should already have (W narrates, M on cost) (built live)
- The same attack, now against the platform controls. Watch it get stopped.
- Then look at the counter: you were protected, and you still paid.

## 11. Cluster 3: your cluster, your guardrails (W + M) (built live)
- On your own cluster, switch on the agent-specific guardrails one at a time: output, then input,
  then tool restriction.
- Watch each one change the agent's behavior, and the spend, on the dashboard.

## 12. The door you did not think to guard (W narrates, M on the fix) (built live)
- You filtered the response. The same secret can still leak somewhere you were not watching.
- The trace re-leak trap, and the symmetric fix.

## 13. The map (M)
- Every attack, the control that stops it, the layer it lives in, and whether you already run that control.

## 14. Most of this you already have (M)
- The large share is governed by tools many teams already run.
- A small share is not, and that small share is where agents change the threat model at the scale from slide 3.

## 15. Take it home (M+W)
- The repo is the whole platform as code.
- A governance map and a self-assessment checklist to run against your own platform on Monday.

## 16. Thanks and questions (M+W)
- Repo link and contact.

---

## Build notes (not slides)
- This is the outline. The deck (Google Slides / Keynote) is built from it; slides 8, 10, 11, 12 are
  live demos with only a title card.
- Optional next step: per-slide speaker notes for Whitney, and a cold-open script for slides 2 and 3 (now written: facilitation/cold-open-script.md)
  (the two-tier hook is the most important three minutes of the talk).
