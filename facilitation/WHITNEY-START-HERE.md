# Watch It Burn, start here (for Whitney)

Everything you need to start working on the AI Engineer World's Fair workshop. The platform is built
and verified; the talk materials below are drafts for your input.

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

## The shape of the 2 hours (three clusters)

1. Cluster 1, no guardrails: the room attacks an unprotected cluster and it gets wrecked, while a live
   counter shows the cloud bill climbing.
2. Cluster 2, the controls a mature team already runs: the same attack is blocked, but the bill still moved.
3. Cluster 3, each attendee's own: they switch on the agent-specific guardrails one at a time and watch
   each one change the behavior and the cost. Then a final twist (the trace re-leak trap) and the map.

## Your part

Working co-speaker split (confirm or change it): Michael takes architecture, the security thesis, and
the cost argument; you take the live attack narration, the observability view, and the attendee
experience. The run-of-show marks every hand-off.

## What is attached in this folder

- Watch It Burn, Abstract: the accepted talk abstract (the source of truth for what we promised).
- Watch It Burn, Run of Show (demo flow): the minute-by-minute 2-hour runbook with hand-offs and the toggles. This is the demo flow.
- Watch It Burn, Slide Outline: the deck outline, slide by slide, with speaker cues.
- Watch It Burn, Cold Open Script: the word-for-word opening for the first three minutes (the hook).
- Watch It Burn, Build Spec (technical reference): the full platform build spec. Background, not required reading; it explains how the platform is constructed if you want the detail.

## A few things worth your input

- The co-speaker split above.
- Whether the trace re-leak trap runs live or stays a narrated slide.
- Anything in the run-of-show that you would pace differently.
