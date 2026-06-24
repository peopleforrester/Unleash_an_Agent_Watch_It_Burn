# Roadmap

Forward-looking implementation order. Completed work lives in `PROGRESS.md`, not here.

---

## Observability Suite (Short-term — pre-workshop)

Child PRDs are created via the meta-PRD ([PRD #7](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7)), one per milestone, and built as each is written. Entries are added as each child PRD is created.

- Observability meta-PRD ([PRD #7](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7)) — defines and sequences the child observability PRDs as MVP-first milestones (thin end-to-end vertical increments)

**Build order (MVP-first milestones; each verifiable in the Datadog UI; child PRDs added as created):**

1. MVP: OTel Collector + Datadog connected, UST wired on AI-layer components ([PRD #13](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/13)) — proves Datadog works; locks cross-cutting decisions (collector shape, UST vocabulary, account model)
2. Migrate to OTel GenAI semconv — replace Michael's custom witb_*/tier conventions with gen_ai.* in Datadog LLM Observability ([PRD #20](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/20))
3. Security-beat traces — before/after sanitization (re-leak trap) + rogue MCP tool chain ([PRD #22](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/22))
4. Falco alerts in Datadog — runtime detection visible
5. EKS infra & named integrations — Agent DaemonSet, per-component synthesis (issue #11)
6. UST, Service Map & correlation — full-fidelity tagging, Service Map view, log/trace/metric pivots
7. Dashboards — import community/Grafana dashboards (from the Milestone 5 survey) for components without an official Datadog dashboard; decide custom/story dashboards (build now / defer to dress rehearsal / skip)
8. Attendee accounts & credentials — per-attendee org provisioning, credential store, distribution, per-cluster secrets
