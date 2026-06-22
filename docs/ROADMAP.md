# Roadmap

Forward-looking implementation order. Completed work lives in `PROGRESS.md`, not here.

---

## Observability Suite (Short-term — pre-workshop)

Child PRDs are created via the meta-PRD ([PRD #7](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7)), one per vertical slice, and built as each is written. Entries are added as each child PRD is created.

- Observability meta-PRD ([PRD #7](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7)) — defines and sequences the child observability PRDs as MVP-first vertical slices

**Build order (MVP-first vertical slices; each verifiable in the Datadog UI; child PRDs added as created):**

1. MVP: telemetry in one Datadog account, visible in the UI — locks cross-cutting decisions (collector shape, UST vocabulary, account model, Weaver)
2. LLM call & tool-call waterfall — core demo trace
3. Security-beat traces — before/after sanitization (re-leak trap) + rogue MCP tool chain
4. Falco alerts in Datadog — runtime detection visible
5. EKS infra & named integrations — Agent DaemonSet, per-component synthesis (research/28)
6. UST, Service Map & correlation — full-fidelity tagging, Service Map view, log/trace/metric pivots
7. Custom dashboards — backed by data confirmed flowing from earlier slices
8. Attendee accounts & credentials — per-attendee org provisioning, credential store, distribution, per-cluster secrets
