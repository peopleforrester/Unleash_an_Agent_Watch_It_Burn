# Roadmap

Forward-looking implementation order. Completed work lives in `PROGRESS.md`, not here.

---

## Observability Suite (Short-term — pre-workshop)

These PRDs are created via the meta-PRD (`prds/00-observability-meta.md`) and implemented in dependency order.

- [Observability Meta-PRD](../prds/00-observability-meta.md) — defines and sequences the 8 child observability PRDs; milestone per child PRD
- Per-component telemetry survey PRD — foundational; documents what each IDP component natively emits and how to capture it; informs all other observability PRDs
- OTel Collector config and telemetry collection strategy PRD — authoritative pipeline spec; depends on component survey
- Datadog deployment and configuration PRD — Agent DaemonSet, named integrations, UI verification; depends on Collector config
- UST strategy and implementation PRD — tag vocabulary, OTEL_RESOURCE_ATTRIBUTES per workload, service map; depends on Datadog deployment
- Log/metric/trace correlation PRD — end-to-end correlation verification; likely needs live-cluster spike; depends on UST
- GenAI semconv and LLM Observability PRD — gen_ai.* spans, prompt/response capture, before/after sanitization, cost counter fix; depends on Collector config
- Custom dashboards PRD — which dashboards to build and what data each requires; depends on all pipeline PRDs
- Attendee accounts, credentials, and K8s secrets PRD — trial org provisioning, credential distribution, per-cluster K8s secrets; relatively decoupled, late in sequence
