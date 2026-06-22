# Roadmap

Forward-looking implementation order. Completed work lives in `PROGRESS.md`, not here.

---

## Observability Suite (Short-term — pre-workshop)

Child PRDs are created via the meta-PRD ([PRD #7](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7)), one per milestone, then implemented in the order below. Entries are added as each child PRD is created.

- Observability meta-PRD ([PRD #7](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7)) — defines and sequences the child observability PRDs

**Implementation order (child PRDs added as created):**

1. OTel Collector config & telemetry collection strategy — foundational pipeline; gated by the per-component synthesis (research/28)
2. Datadog deployment & integrations — Agent/DDOT, named integrations, UI verification; depends on Collector config
3. UST strategy — tag vocabulary + Service Map; can only be validated after collection exists
4. Log/metric/trace correlation — end-to-end pivot verification; depends on UST
5. GenAI semconv & LLM Observability — gen_ai.* spans, prompt/response capture, sanitization, cost-counter fix; depends on Collector config
6. Custom dashboards — depends on all upstream data sources flowing
7. Attendee accounts & credentials — trial-org provisioning, credential distribution, per-cluster K8s secrets; relatively decoupled, late in sequence
