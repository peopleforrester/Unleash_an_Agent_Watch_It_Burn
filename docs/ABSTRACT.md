# Talk Abstract: the published KubeCon NA 2026 and DevOpsDays Portland 2026 listings, and the June originals

The canonical abstract is whatever the event has published. Two listings are published, one per format:

- **The 30-minute KubeCon NA 2026 breakout** (Version 4 below), Sessionize session 1249553, with Whitney
  Lee. Michael made this repo the breakout's repo on 2026-10-19 (#456). Its readiness against this text is
  `docs/KUBECON-ABSTRACT-READINESS.md`; its run-of-show is `facilitation/kubecon-na-2026-run-of-show.md`.
- **The 2-hour workshop**, the DevOpsDays Portland listing (Version 3 below), copied verbatim from the
  pretalx schedule export (https://talks.devopsdays.org/devopsdays-portland-2026/talk/BYT7TC/, fetched
  2026-09-06). The "abstract truth" rule in `BUILD-SPEC.md` reads against this text.

The June World's Fair versions follow as frozen history.

> **Slot, room and track:** conference-knowledge (`events/registry.yaml`, entries `kubecon-na-2026` and
> `devopsdays-portland-2026`) is the record for the scheduled slots. Speakers: Michael Forrester, Whitney Lee.

## Version 4, KubeCon + CloudNativeCon North America 2026 (published, accepted breakout)

- **Session:** Sessionize session 1249553, a 30-minute breakout on the main program. Accepted 2026-08-04
  (talks-knowledge `talks/register.md`, the BurritoBot entry).
- **Source of this text:** transcribed verbatim from the public Sessionize speaker profile
  (https://sessionize.com/peopleforrester) on 2026-09-10, in talks-knowledge
  `abstracts/recovered/sessionize-public-profile.md` section 5. Copied here on 2026-10-24 from talks-knowledge
  main at `5a9af49`. The quoted title and text are a verbatim record: do not edit them.
- **Not the CFP draft.** `presentations/kubecon-na-2026/docs/CFP-SUBMISSION.md` in the archived
  Kubecon-NA-2026-Whitney-BurritoBot repo is an earlier draft under another title ("Can Your Chatbot Run
  kubectl? Guardrails for LLMs on Kubernetes"). It was not submitted, and nothing here is held to it.

### Title

BurritoBot Said Let's Dance, the Platform Said No

### Abstract (as published)

In 2026, a developer asked a burrito chain's chatbot to reverse a linked list before ordering their meal. The bot delivered a solution, then asked what they wanted.

A user does not need to be malicious to embarrass an enterprise, just a little bit weird. The model will help, enthusiastically. But that burrito bot sits in a production cluster that someone (probably you) is responsible for, wired into real tools and data. More than reputation is at stake.

In this session we build a chatbot for a fictional burrito chain connected to an under-protected MCP server and deploy on a full IDP (internal developer platform). It starts wide open, and we let the audience hack it live.

We show you the relevant Kubernetes security layers you should already have. Then we turn on LLM-specific guardrails, like pre- and mid-inference prompt analysis. Finally we show good GenAI observability practices. By the end the chatbot is selling burritos. Nothing more.

Bring your weirdest off-topic question.

### Reconciliation vs the build

One row per point the text promises, with its state and file evidence, in
`docs/KUBECON-ABSTRACT-READINESS.md`. That file is kept current until delivery.

---

## Version 3, DevOpsDays Portland 2026 (published, canonical for the 2-hour workshop)

### Title

Build a Platform, Unleash an Agent on It… and Watch It Burn

### Abstract (as published)

We built a burrito-ordering AI agent, put it on Kubernetes with scoped cluster access and a live terminal, and let a room of engineers try to break it.  It is tons of fun.
Over three rounds they push the agent to steal customer data, deploy malicious workloads, and take the cluster down. Forkbombs anyone!

The first round has nothing protecting the agent, and it usually falls apart in about one prompt.

The second runs the same attacks against an ordinary CNCF platform floor, which blocks most of them, though a few run up a bill before they get stopped.

In the third round attendees switch on the remaining guardrails themselves and watch how the agent's behavior and its token cost change.

Running it taught us that for most shops, AI doesn't create just brand-new security problems it also makes the ones you already have more expensive. Token spend becomes its own denial-of-service vector for example. Most of what your platform already does holds up against an agent (or for an agent), and the gap that's left is smaller and stranger than people assume.  This workshop covers the base guardrails as well as that enhanced gap that you must have for AI workloads.

We ran this at AI Engineer World's Fair on June 29th 2026. This version covers what held up, what broke, and what we've changed since.  We have made vast improvements including model triage, provisioning and sandboxing (as an option).   This will be a very evolved, much more polished, and much more expanded presentation than the one we ran at AI Engineer World's Fair. This will be much more hands-on instead of just a web interface. They will actually get access to their own cluster.

### Description (as published)

You get a Kubernetes cluster already running a full internal developer platform with 34 components.  You also get an AI agent with access to that cluster and a BurritoBot Web Interface to that Agent.
Your job is to make the agent do damage. Ask it to deploy a workload the policies forbid. Ask it to give itself more permissions. Ask it to change infrastructure without going through Git. Ask it to read a secret and hand you back the value. Some of those attempts get stopped by the platform. The rest get through, until you switch on guardrails built for agents specifically.
The session runs across three clusters. The first has nothing protecting the agent: all three attacks land, a counter on screen shows the cloud bill climbing, and a fork bomb takes the cluster down. The second runs the same attacks against the platform controls, where each one is blocked by a different thing (a NetworkPolicy egress rule, a Kyverno registry allowlist, a per-pod PID limit), though the bill still moves because the request reached the model before anything stopped it. In the third you drive your own agent, switch on the agent-specific guardrails (output filtering, input filtering, tool restriction), and watch each one change the agent's behavior on the dashboard.
The part most teams miss: almost everything an agent tries against a real platform is already handled by tools you probably run today, like admission control, RBAC, and GitOps. What those tools can't see is the agent's input, its output, and the tools it's allowed to reach. That's the part agents change, and it's where this workshop spends its time.  By the end of this workshop you will know what infrastructure guardrails help and where you need AI specific guardrails to fill the gaps.

You work entirely in a browser, with a chat window to your agent and a terminal to your cluster. Nothing to install.
Everything is CNCF or open source: Argo CD, Kyverno, Falco, Istio ambient, LLM Guard, agentgateway, kagent on Bedrock, and the rest of a 35-component platform.

### Reconciliation vs the build (2026-09-06)

The published text was written before the run of show settled, and four claims in it no longer match
what attendees get. None changes the promise ("break the agent, then switch on the guardrails yourself");
the delivery narration should say what actually happens rather than what the listing says.

| Published claim | What the build does | Where |
|---|---|---|
| "three rounds", "three clusters" | Eight challenges, demo-then-do, on one cluster per attendee plus the instructor round clusters | `docs/RUN-OF-SHOW-2026-08.md` |
| "a fork bomb takes the cluster down", "a per-pod PID limit" | The fork bomb was retired (#114); Challenge 4 is denial-of-wallet, stopped by the budget cap | `gitops/ai-layer/web/lab.html`, C4 |
| "34 components" / "35-component platform" | About 39 Argo applications on the attendee profile; say "about forty" or leave the number out | `gitops/bootstrap/attendee/app-of-apps-attendee.yaml` |
| "sandboxing (as an option)" | Deferred; no sandbox in the Portland build | memory: agent sandbox deferred |
| "Everything is CNCF or open source: ... LLM Guard, agentgateway, kagent" | Open source yes, CNCF no. agentgateway and the A2A protocol are **AAIF** projects under the Linux Foundation; kagent is CNCF (donated by Solo.io); LLM Guard is Protect AI's and has no foundation at all | `docs/STACK-WALKTHROUGH.md`, "Who governs what" |

The rest holds: scoped cluster access, a live terminal, the browser-only surface, the platform floor
named, and the bill moving before the platform stops a request. Say the governance line the accurate
way from the stage: the CNCF floor, the AAIF agent protocols, and a guardrail layer with no foundation
behind it.

---

## Version 1, As Submitted (Solo, Frozen)

- **Event, submission and status:** AI Engineer World's Fair 2026, accepted. Venue, dates, the submission platform and the acceptance record live in conference-knowledge (`events/registry.yaml`, entry `aiewf-2026-watch-it-burn`).
- **Speaker:** Michael Forrester (Accenture), solo
- **Source of this text:** Reconstructed from the Mar 14, 2026 "CFP submissions this week" conversation, where the talk was redesigned mid-session into the pre-built-platform / break-it-with-an-agent format. This was never saved as its own file before today. Verify against the version actually submitted in the AI Engineer platform before treating as canonical.

### Title

Build a Platform, Unleash an Agent on it.... and Watch it Burn!

> Note: an interim edit in the source conversation retitled this to "Break This Platform: Can Your Agent Get Past the Governance Stack?" before it settled back. The "...Watch it Burn!" title is the locked, accepted one.

### Format

Workshop (1–2 hours)

### Tracks

AI Safety, AI Infrastructure, Applied AI

### Description

You get a Kubernetes cluster with an Internal Developer Platform already running: ArgoCD for GitOps, Kyverno for admission control, Falco for runtime detection, Prometheus for observability. Everything is instrumented. Everything is enforced. You also get an AI agent with cluster access. Your job is to get the agent to break something. Deploy a non-compliant workload. Escalate privileges. Modify infrastructure outside Git. Exfiltrate data through an agent response. Some of you will fail because the governance stack catches it. Some of you will succeed because it doesn't. Afterward we regroup and map what got blocked, what slipped through, and why. The 80% that existing CNCF tools already govern becomes obvious. The 20% gap where agent-specific tooling is missing becomes undeniable. You leave with a concrete governance map and the exact list of failure modes your own platform probably isn't covering yet.

### Speaker pitch (opening)

I gave an AI coding agent full Kubernetes cluster access. It deleted my cluster. That incident led to an Eight Guardrails Framework I now enforce across Claude Code hooks, Git hooks, and Kubernetes admission policies.

---

## Version 2, With Whitney Lee as Co-Speaker

- **Event, submission and status:** AI Engineer World's Fair 2026, accepted. Venue, dates, the submission platform and the acceptance record live in conference-knowledge (`events/registry.yaml`, entry `aiewf-2026-watch-it-burn`).
- **Speakers:** Michael Forrester (Accenture) with co-speaker Whitney Lee
- **Source of this text:** Reconstructed from the Mar 14, 2026 "CFP submissions this week" conversation, where the talk was redesigned mid-session into the pre-built-platform / break-it-with-an-agent format. Verify against the version actually submitted in the AI Engineer platform before treating as canonical.

### Title

Build a Platform, Unleash an Agent on it.... and Watch it Burn!

> Note: an interim edit in the source conversation retitled this to "Break This Platform: Can Your Agent Get Past the Governance Stack?" before it settled back. The "...Watch it Burn!" title is the locked, accepted one.

### Format

Workshop (1–2 hours)

### Tracks

AI Safety, AI Infrastructure, Applied AI

### Description

You get a Kubernetes cluster with an Internal Developer Platform already running: ArgoCD for GitOps, Kyverno for admission control, Falco for runtime detection, Prometheus for observability. Everything is instrumented. Everything is enforced. You also get an AI agent with cluster access. Your job is to get the agent to break something. Deploy a non-compliant workload. Escalate privileges. Modify infrastructure outside Git. Exfiltrate data through an agent response. Some of you will fail because the governance stack catches it. Some of you will succeed because it doesn't. Afterward we regroup and map what got blocked, what slipped through, and why. The 80% that existing CNCF tools already govern becomes obvious. The 20% gap where agent-specific tooling is missing becomes undeniable. You leave with a concrete governance map and the exact list of failure modes your own platform probably isn't covering yet.

### Speaker pitch (opening)

I gave an AI coding agent full Kubernetes cluster access. It deleted my cluster. That incident led to an Eight Guardrails Framework I now enforce across Claude Code hooks, Git hooks, and Kubernetes admission policies.

---

## Reconciliation notes vs the current build (BUILD-SPEC rev3)

- **Abstract-truth target (resolved 2026-06-19):** the **staged three-cluster design IS abstract-truth**. The abstract's "everything is instrumented / everything is enforced" reads against the **governed** clusters (Cluster 2 CNCF-only and Cluster 3); Cluster 1 deliberately enforces nothing (that is the burn). "An AI agent with cluster access" means a **scoped** ServiceAccount, never cluster-admin. `verify/run-all.sh` asserts the staged before/after across the three clusters as the truth, not a literal "everything enforced on every cluster." See `docs/BUILD-PLAN.md`.
- The abstract lists the four attacker objectives: **deploy a non-compliant workload, escalate privileges, modify infrastructure outside Git, exfiltrate data through an agent response.** The rev3 build maps these as: the first three are the aggregate **Beat 1 (CNCF wall)**; the exfil is **Beat 2 (output sanitization)**. The bad-MCP / excessive-agency beat (Beat 3) is an extension beyond the literal abstract text and must not contradict it.
- The abstract names **ArgoCD, Kyverno, Falco, Prometheus** as the pre-built stack, all present in the build. Observability is the narration lens; the abstract's "Prometheus for observability" is satisfied by the kube-prometheus-stack + trace backend.
- The abstract's promised takeaways, **a concrete governance map** and **the exact list of failure modes your platform isn't covering**, are the `facilitation/governance-map.md` and `facilitation/self-assessment.md` artifacts.
- The "Eight Guardrails Framework" in the speaker pitch is Michael's framing and is NOT a public/proprietary term to expose in attendee-facing copy beyond the pitch itself (see BUILD-SPEC §11 banned-terms note).
