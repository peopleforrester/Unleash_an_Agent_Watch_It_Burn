# Talk Abstract: the published DevOpsDays Portland 2026 listing, and the June originals

The canonical abstract is whatever the event has published. Since 2026-09-06 that is the DevOpsDays
Portland listing below, copied verbatim from the pretalx schedule export
(https://talks.devopsdays.org/devopsdays-portland-2026/talk/BYT7TC/, fetched 2026-09-06). The June
World's Fair versions follow as frozen history; the "abstract truth" rule in `BUILD-SPEC.md` now reads
against the Portland text.

> **Scheduled slot (pretalx, 2026-09-06):** Tuesday 2026-09-08, 13:00 to 15:00 Pacific, Room 327,
> Workshops track, 2 hours. Speakers: Michael Forrester, Whitney Lee.

## Version 3, DevOpsDays Portland 2026 (published, canonical)

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

The rest holds: scoped cluster access, a live terminal, the browser-only surface, the CNCF stack named,
and the bill moving before the platform stops a request.

---

## Version 1, As Submitted (Solo, Frozen)

- **Event:** AI Engineer World's Fair 2026, San Francisco, Moscone West, Jun 29 – Jul 2
- **Speaker:** Michael Forrester (Accenture), solo
- **Status:** ACCEPTED (first wave, 1,600+ submissions)
- **Submitted via:** AI Engineer platform (ai.engineer / Accelerant-era form). NOT Sessionize. The org later moved to Sessionize, so this abstract never existed in a Sessionize record.
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

- **Event:** AI Engineer World's Fair 2026, San Francisco, Moscone West, Jun 29 – Jul 2
- **Speakers:** Michael Forrester (Accenture) with co-speaker Whitney Lee
- **Status:** ACCEPTED (first wave, 1,600+ submissions). Accepted as a solo submission; Whitney Lee added as co-speaker after acceptance.
- **Submitted via:** AI Engineer platform (ai.engineer / Accelerant-era form). NOT Sessionize. The org later moved to Sessionize, so this abstract never existed in a Sessionize record.
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
