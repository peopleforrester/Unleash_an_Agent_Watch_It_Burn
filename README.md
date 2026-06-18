# Build a Platform, Unleash an Agent on it... and Watch it Burn!

A hands-on workshop at AI Engineer World's Fair 2026 (San Francisco, Moscone West).
Presented by Michael Forrester (Accenture) with Whitney Lee.

## What this is

You get a Kubernetes cluster that already runs a full internal developer platform: Argo CD for
GitOps, Kyverno for admission policy, Falco for runtime security, Prometheus and Grafana for
observability, plus secrets management, certificates, and a Backstage portal. You also get an AI
agent with access to that cluster.

The exercise is to make the agent do damage. Ask it to deploy a workload the policies forbid. Ask
it to give itself more permissions. Ask it to change infrastructure without going through Git. Ask
it to read a secret and hand the value back to you. Some of those attempts are stopped by the
platform. The rest get through, until you switch on guardrails meant for agents specifically.

## What you learn

Most of what an agent will try against a real platform is already handled by tools many teams run
today, such as admission control, RBAC, and GitOps. Turn the right control on and the attack stops.

What those tools cannot see is the agent's input, its output, and the tools it is allowed to reach.
That is the part agents change, and it is where this workshop spends its time. You will also watch
an unguarded agent run up a real cloud bill, because wasted tokens are their own denial-of-service
problem, and you will see which guardrail stops the spend rather than paying for it after the fact.

## How the session runs

The workshop uses three clusters over about 60 minutes.

1. **No guardrails.** We point an agent at an unprotected cluster and let the room attack it. It
   comes apart within a few minutes, and a counter on screen shows the cloud bill rising the whole
   time. We keep spares, because these do not survive.
2. **CNCF guardrails.** The same attack runs against a cluster with the platform controls in place.
   The damage is blocked, but the bill still moved, because the request reached the model before
   admission rejected it.
3. **Your own cluster.** You drive your own agent and switch on the agent-specific guardrails one at
   a time: output filtering, then input filtering, then tool restriction. You watch each one change
   the agent's behavior on the dashboard.

You work in a browser. There is a chat window to your agent and a terminal to your cluster. No local
install is required.

## What you take home

- This repository. It is the platform as code, so you can hand it to a coding agent and stand up
  something close to production.
- A governance map that lists each attack, the control that stops it, the layer it sits in, and
  whether existing tooling already covers it.
- A checklist you can run against your own platform to find the gaps.

## The stack

Everything here is CNCF or open source. Argo CD delivers the whole platform to every cluster from a
single app-of-apps.

- GitOps: Argo CD
- Policy: Kyverno
- Runtime security: Falco and Falcosidekick
- Secrets and certificates: External Secrets Operator, cert-manager
- Observability: Prometheus, Grafana, Tempo, Loki, OpenTelemetry, Grafana Alloy
- Developer portal: Backstage
- Agent: kagent (a CNCF project) on Amazon Bedrock
- AI guardrails: LLM Guard

Pinned versions are in [`VERSIONS.lock`](VERSIONS.lock).

## Repository layout

| Path | Contents |
|---|---|
| `gitops/` | Argo CD app-of-apps: the whole platform as code |
| `gitops/ai-layer/` | the agent and the AI guardrails (kagent, LLM Guard, MCP) |
| `policies/kyverno/` | the admission policies |
| `security/`, `observability-idp/`, `backstage/` | the platform foundation |
| `agent/`, `beats/` | guardrail sources and the attack content |
| `infra/` | cluster provisioning and bootstrap scripts |
| `verify/` | the verification scripts |
| `facilitation/` | governance map, self-assessment, run-of-show |
| `docs/` | the build spec, the abstract, and the design decisions |

## Safety

Everything here is synthetic. Planted secrets are obviously fake and carry a `FAKE-` prefix. No real
credential goes into a cluster, a trace, or a recording. The clusters are disposable on purpose.
