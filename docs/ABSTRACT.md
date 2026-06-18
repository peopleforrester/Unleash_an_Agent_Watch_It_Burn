# AI Engineer World's Fair 2026 — Accepted Talk Abstract

Frozen reference. This file captures the accepted abstract as submitted (Version 1, solo) and a co-speaker variant adding Whitney Lee (Version 2). The talk content, title, description, and speaker pitch are unchanged between versions. Only the speaker attribution differs.

This is the canonical "Proposed Amended Description" the build must make literally true (see `BUILD-SPEC.md` §2 and the "abstract truth" rule). If the build and this abstract disagree on behavior, the abstract wins.

> **Scheduled slot (confirmed on the AI Engineer schedule):** 2 hours, Day 1 (Workshop Day), 2:20–4:20pm, Track 5. The Format field below reads "1–2 hours" as submitted; the booked slot is the full 2 hours. The public schedule currently lists Michael solo; organizers have been emailed to add Whitney as co-speaker.

---

## Version 1 — As Submitted (Solo, Frozen)

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

## Version 2 — With Whitney Lee as Co-Speaker

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

- The abstract lists the four attacker objectives: **deploy a non-compliant workload, escalate privileges, modify infrastructure outside Git, exfiltrate data through an agent response.** The rev3 build maps these as: the first three are the aggregate **Beat 1 (CNCF wall)**; the exfil is **Beat 2 (output sanitization)**. The bad-MCP / excessive-agency beat (Beat 3) is an extension beyond the literal abstract text and must not contradict it.
- The abstract names **ArgoCD, Kyverno, Falco, Prometheus** as the pre-built stack — all present in the build. Observability is the narration lens; the abstract's "Prometheus for observability" is satisfied by the kube-prometheus-stack + trace backend.
- The abstract's promised takeaways — **a concrete governance map** and **the exact list of failure modes your platform isn't covering** — are the `facilitation/governance-map.md` and `facilitation/self-assessment.md` artifacts.
- The "Eight Guardrails Framework" in the speaker pitch is Michael's framing and is NOT a public/proprietary term to expose in attendee-facing copy beyond the pitch itself (see BUILD-SPEC §11 banned-terms note).
