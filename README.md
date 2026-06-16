*What this workshop is, its public-safe thesis, the three beats, the repo layout, and how to build it. Attendee- and public-facing.*

# Build a Platform, Unleash an Agent on it… and Watch it Burn!

A hands-on workshop for **AI Engineer World's Fair 2026** (San Francisco, Moscone West). Speakers: Michael Forrester (Accenture) with Whitney Lee. Slot: 1–2 hours.

## What it is

Every attendee gets their own real Kubernetes cluster and a scoped AI agent already running on a pre-built Internal Developer Platform on a CNCF stack. You then unleash that agent through a sequence of attacks and watch — live, through a single trace view — what the platform stops and what it doesn't.

Some attacks bounce off controls a mature platform already runs. The rest expose gaps those controls can't see, because the attack rides in natural language and in tool calls rather than in the Kubernetes control plane. We close each gap live by switching on an agent-specific guardrail, then you take home a governance map and a self-assessment checklist for your own platform.

## The thesis (the inverted 80/20)

Most of what an agent will try against a real platform is **already covered** by controls you likely already have — admission policy, RBAC, GitOps reconciliation. That's the big surface, and it's the setup, not the story.

The thin slice that *isn't* covered — input it can't vet, output it can't scrub, tools it shouldn't call — is small in area but it's exactly where agents change the threat model. That thin slice is the whole point.

## The three beats

1. **The CNCF wall** — the agent tries to deploy a non-compliant workload, escalate its own privileges, and change infrastructure outside Git. Three distinct walls (admission, RBAC, GitOps), and one of them flips from watch-only to blocking live. This is the big surface your platform already handles.
2. **Sanitization, both directions** — what rides in on the prompt, and what rides out in the response. Two controls switched on live: one for input, one for output. The control plane never sees either.
3. **When the agent's own tools turn on it** — the agent is wired to an untrusted tool server whose poisoned tool description induces it to call something it never should. One tool-authorization control, switched on live (or shown recorded, depending on a build-time verification).

Observability is not a separate beat — it's the lens every beat is narrated through. In the extended 2-hour slot it earns one dedicated moment: the trace re-leak trap, where the telemetry you use to watch the agent turns out to be a second place a blocked secret can leak.

## Repo layout

```
README.md             # this file
PROJECT_STATE.md      # durable build state — read this and the spec to build
docs/BUILD-SPEC.md    # the single source of truth for the build (rev3)
VERSIONS.lock         # pinned versions/digests (written at build time)
research/             # grounding notes, dated, with sources
infra/                # host/hub + spoke sizing, cost, bootstrap
  SIZING.md           # node sizing, cost as a function of N, LLM Guard placement
platform/             # ArgoCD, Kyverno, Falco, observability manifests
agent/                # the scoped agent, its RBAC, gateway + guardrail config
beats/                # the three beats: instructions, prompts, toggles, fallbacks
verify/               # the verification harness (before/after for every beat)
access/               # per-attendee web terminal + quickstart handout
facilitation/         # runbook, slides outline, governance map, self-assessment
fallback/recordings/  # asciinema per beat (recorded fallback)
teardown/             # teardown + cost report
```

## How to run the build

The build is spec-driven and runs phase by phase. Do not start a phase until the prior phase's verification passes.

1. Read **`docs/BUILD-SPEC.md`** in full — it is the single source of truth (architecture, version pins, the nine build phases, and their verification blocks).
2. Read **`PROJECT_STATE.md`** for current state, the architecture decision (separate cluster per attendee, hub-and-spoke), and the open decisions still owned by Michael.
3. Check **`infra/SIZING.md`** for node sizing, cost as a function of attendee count, and the resource budget per attendee cluster before you provision anything.
4. Follow the phases in order. Each phase has acceptance criteria; stop on the first failed verification and report it.

Architecture in one line: a small shared **hub** cluster runs GitOps and observability; each attendee gets their own isolated **spoke** cluster, delivered the full platform stack from the hub. Cost and provisioning scale with the number of attendees — see `infra/SIZING.md`.

## For attendees on the day

You need a browser. No local install. See `access/quickstart.md` for how to reach your terminal and talk to your agent.
