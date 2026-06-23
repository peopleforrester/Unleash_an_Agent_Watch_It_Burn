# Observability Priorities

This document defines which observability outcomes are required for the workshop to run versus which would be nice to have. Each milestone's design conversation reads this file in Step 0 and updates it in Step 3 if priorities shifted.

**Last updated:** 2026-06-23 (M1 design conversation)

---

## Must-Haves

These must work before the workshop runs. A milestone that produces a child PRD for one of these items cannot be cut or deferred.

1. **AI agent trace chain in Datadog APM** — Traces showing `guard-proxy → agentgateway → kagent → Bedrock` as a connected waterfall. Attendees see the full AI agent call chain. This is the primary story.

2. **Cost metrics flowing to Datadog** — At least one metric (LLM cost, token count, or request count) appears in Datadog after running a beat. Proves the cost-counter pipeline works end-to-end.

3. **Service Map rendering** — The Datadog Service Map shows `guard-proxy → agentgateway → kagent → Bedrock`, each node health-indicated. This is the "see everything" moment in the demo. (Milestone 6)

4. **Security beat traces** — The re-leak trap (before/after sanitization at guard-proxy) and the rogue MCP tool-call chain (Beat 3) are both visible as trace waterfalls in Datadog APM. (Milestone 3)

5. **Falco alert visible in Datadog** — When exfil or abuse is attempted, the Falco alert appears in Datadog (OOTB Falco dashboard or events stream). (Milestone 4)

6. **Log-trace correlation pivots** — "View related logs" works from a trace; "View Trace in APM" works from a log. Both directions confirmed live. (Milestone 6)

7. **UST at full fidelity** — `service`, `env` (`production`), and `version` are consistent across traces, metrics, and logs for all instrumented components. Required for Service Map edges and correlation pivots to function. (Milestones 1, 5, 6)

---

## Nice-to-Haves

These enrich the story but can be cut if time or complexity demands it. Decide per-milestone whether to build, defer to dress rehearsal, or skip.

1. **Custom story dashboards** — Wasted Tokens Over Time, Model Tier Cost Race (group by `gen_ai.request.model`), Tool Call Heatmap, Guardrail Toggle Timeline. Each requires its upstream data to be flowing first. (Milestone 7)

2. **Imported community dashboards** — For stack components without an official Datadog integration (e.g., ArgoCD, Kyverno, cert-manager, Backstage). Import only if the data is confirmed flowing. Do NOT hand-build custom dashboards for never-center-stage components. (Milestone 7)

3. **Kyverno policy decision traces** — Enable `otelConfig=grpc` on the Kyverno admission controller to get policy-decision spans into the same trace tree. Useful context but not in the main narrative. (Milestone 5 decision)

4. **Istio L7 metrics** — Deploying a per-namespace waypoint for full L7 visibility. L4-only ztunnel metrics are sufficient for the workshop story; L7 is additional depth. (Milestone 5 decision)

5. **EKS + CloudWatch cross-account integration** — Almost certainly facilitator-only, not per-attendee. Low narrative value; high setup cost. Likely skip. (Milestone 5 decision)

6. **KubeArmor dashboard** — Community dashboard survey only; KubeArmor is not in the main narrative. (Milestone 5)

---

## Scope Guardrails

These apply to every milestone's design conversation:

- Do NOT build or import a dashboard for a component before confirming its data is flowing.
- Do NOT instrument a component with a library that Datadog does not support (e.g., OpenInference).
- Do NOT use `deployment.environment` (deprecated) — use `deployment.environment.name` throughout.
- Do NOT set `peer.service` or span kinds as a retrofit — set them during initial instrumentation or they will be missing from the Service Map.
- Do NOT build non-provisional dashboards on `witb_cost_usd` / `witb_tokens_total` / `witb_requests_total` before Milestone 2 completes the gen_ai semconv migration — these metric names may change.
