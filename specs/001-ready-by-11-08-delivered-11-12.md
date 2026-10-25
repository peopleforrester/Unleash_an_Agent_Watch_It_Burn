<!-- ABOUTME: Spec 001 for the BurritoBot talk: the platform live and the abstract's promises met by 11-08, delivered with Whitney Lee on 11-12. -->
<!-- ABOUTME: Derived from okrs.yaml repo objective talk-folders.1 (talks grouping approved 2026-10-17). -->

---
spec: talks/burritobot/001
source: personal-knowledge specs/talks/burritobot/001-ready-by-11-08-delivered-11-12.md @ sha256:4e127440568a302d374bc5eff51bd87a158485a5604267e65db19bdaed41474b
status: approved
approved: 2026-10-17 by Michael ("yes approve talks, write the specs")
chain:
  vision_subtracks: [V3b, V3a]
  objective: 2026q4.H
  sub_objectives: [TALK.DELIVER, TALK.CAMPAIGN, TALK.REUSE]
  repo_objective: talk-folders.1
  krs: [kubecon-na-burritobot, mrf-talk-campaigns, mrf-talk-clips]
  metrics: ["abstract points READY (target 9 of 9 or cut from the talk with Whitney's agreement)"]
platform: peopleforrester/Unleash_an_Agent_Watch_It_Burn (Michael, 2026-10-19)
repo_plan: none; PROJECT_STATE.md, docs/ABSTRACT.md and the readiness document (#456) carry the work
schedule: facilitation/kubecon-na-2026-run-of-show.md, section "Dates to hold (#447)" (Michael's revision, 2026-10-24)
priority: 1 (dates for people only; the cold read once the platform is live, two timed run-throughs by 2026-11-08, delivery 2026-11-12)
---

# BurritoBot: ready by 11-08, delivered 11-12

## Why

"BurritoBot Said Let's Dance, the Platform Said No" is the accepted KubeCon NA
breakout with Whitney Lee (Sessionize 1249553), Thursday 2026-11-12, 13:50 to
14:20 MST, Grand Ballroom BDF. It is the largest stage of the quarter and the
only co-presented talk, so a live demo that fails costs both presenters.

The talk's platform is `peopleforrester/Unleash_an_Agent_Watch_It_Burn`, the
repo used at DevOpsDays Portland. It runs on AWS, not GCP (Michael,
2026-10-23). Issue numbers below are that repo's.

## Where it stands (2026-10-19, read from Unleash_an_Agent_Watch_It_Burn#456)

- The readiness against the accepted abstract is not assessed yet. #456 holds
  a first read of the nine points, each mapped to this repo's design and its
  open issues (#447 to #455).
- The three scope calls (MCP server, what "full IDP" means on stage, who
  hacks) are with Michael and Whitney on talks-knowledge#29. This repo's design
  looks to settle points 2, 3 and 4.
- The delivery identity (which AWS account runs it, a new Datadog org pool) is
  #454 and needs Michael.
- KubeCon registry items still pending: speaker promo video (due 10-13), the
  speaker-change and AV cutoffs (10-16). Those are conference-knowledge's to
  close; this repo supplies the content.

## Milestones

The dates are held in this repo's `facilitation/kubecon-na-2026-run-of-show.md`,
section "Dates to hold (#447)". Michael revised them on #447 on 2026-10-24:
work that agents build has no forecast date and is built straight through in
the order below (M1, M3, M4, M5), with the fallback recorded the moment the
live run works. Only the steps people do carry dates. Datadog (abstract point
7, under M3) joins when Whitney has a new org pool, expected the week of
2026-10-26.

| # | Done when | Moves | Date |
|---|---|---|---|
| M1 | The delivery platform comes up from this repo's provisioning (`fleet.sh`) for a rehearsal (#447). It runs on AWS, in the account chosen in #454; infrastructure/aws-management owns AWS accounts, so file there if it blocks | `kubecon-na-burritobot` | no date (agent-built, first in build order) |
| M2 | Whitney's cold read of the KubeCon run-of-show (#448) runs against the live platform, and her findings are filed (#447) | `kubecon-na-burritobot` | **once the platform is live** (M1) |
| M3 | Every abstract point is READY or has been cut with Whitney's agreement and recorded, in the readiness document (#456) | TALK.DELIVER | no date (agent-built, after M1) |
| M4 | Recorded fallback (#452) captured, so the talk survives a dead network | TALK.DELIVER | no date (agent-built, as soon as the live run works) |
| M5 | Deck built and the 16:9 PDF uploaded to Sessionize (#449) | TALK.DELIVER | no date (agent-built, last in build order) |
| M6 | Two full timed run-throughs with Whitney, demo included (#447) | `kubecon-na-burritobot` | **by 2026-11-08** |
| M7 | Delivered | `kubecon-na-burritobot` | **2026-11-12** |
| M8 | Campaign: at least two articles, a clip posted to YouTube and as native LinkedIn video, the repo made public after the public-repo checks. mrf-engagement-orchestrator executes the posting | `mrf-talk-campaigns`, `mrf-talk-clips` | by 2026-12-12 |
| M9 | Delivery logged in talks-knowledge's register as a delivery of this talk's repo. The repo was delivered at DevOpsDays Portland, so its GitHub name stays; its local folder is `talks/unleash-an-agent-and-watch-it-burn/` under the layout (repo-management#22) | TALK.REUSE | after M7 |

## Boundaries

Event logistics (travel, registration, the KubeCon cutoffs) belong to
conference-knowledge and kubecon-events. The AWS accounts the platform runs on,
and their billing, belong to infrastructure/aws-management. Costs go to
Financal_Management_Tool.

## Corrections

- 2026-10-19 (personal-knowledge#153): the talk's platform is
  `peopleforrester/Unleash_an_Agent_Watch_It_Burn`, the repo used at DevOpsDays
  Portland, by Michael's decision of 2026-10-19.
  `peopleforrester/Kubecon-NA-2026-Whitney-BurritoBot`, which this spec named
  when sent as its #114, was never the official repo and is archived (local
  checkout `_archive/talks/Kubecon-NA-2026-Whitney-BurritoBot`). The work that
  still applies was carried to Unleash_an_Agent_Watch_It_Burn #447 to #456.
  Milestone dates, the KRs and the metric are unchanged. "Where it stands" now
  reads the new repo; the 2026-10-17 reading (674 static tests, the GCP
  `invalid_grant`, ABSTRACT-READINESS 2 ready, 4 partial, 3 missing) was of the
  archived repo. Issue numbers now refer to the new repo. M1 no longer names
  GCP, because the delivery account is open in #454. M3 drops the archived
  repo's #58 and #112 and M4 drops its Grafana screenshot (#20): they belonged
  to the archived platform, and GenAI observability on stage is abstract point
  7 under M3. M9 no longer moves a repo into `talks/burritobot/`, because this
  repo was already delivered and is never renamed.
- 2026-10-19 (personal-knowledge#148, from hecaton#97): V6c removed from the
  chain's `vision_subtracks`. talk-folders.1 serves TALK.DELIVER, TALK.CAMPAIGN
  and TALK.REUSE, which carry V3a, V3b and V3c only, so the header named a
  subtrack its repo objective does not reach. No milestone, date or scope
  changed.
- 2026-10-23 (personal-knowledge#167): the platform runs on AWS, not GCP
  (Michael, 2026-10-23: "We're not using GCP. We're using AWS."). "Why" now
  says so, M1 names the AWS account chosen in #454, and Boundaries gives cloud
  accounts and billing to infrastructure/aws-management only, dropping
  gcp-management. None of the archived repo's issues (#17, #83, #18, #20, #58,
  #103, #112) is cited as a live item here: #17, the dead GCP identity, is
  carried to #454, and the others belonged to the archived GCP platform, so
  they are dropped. The GCP mentions in the 2026-10-19 entry above describe the
  archived repo and stay as history. No milestone, date, KR or metric changed.
- 2026-10-24 (personal-knowledge#174, from Unleash_an_Agent_Watch_It_Burn#447):
  the milestone dates now follow Michael's 2026-10-24 revision on #447 ("no
  forecast dates for work agents build"), held in this repo's
  `facilitation/kubecon-na-2026-run-of-show.md`, section "Dates to hold
  (#447)" (49aa5b5), which the header's new `schedule:` line names. M1
  (2026-10-23), M3 (2026-10-31), M4 (2026-11-01) and M5 (2026-11-04) lose
  their dates and keep their build order. M2 moves from 2026-10-26 to "once the
  platform is live". M6 (by 2026-11-08) and M7 (2026-11-12) keep their dates.
  The `priority:` line now lists only the dates for people. The milestones'
  scope, the KRs, the metric and the title are unchanged, and KR
  `kubecon-na-burritobot` stays due 2026-11-08, the date of M6. #447 asked
  for the spec to name this repo; it already did since the 2026-10-19 entry
  above, so only the dates and the pointer to the run-of-show changed.
