# Roadmap

Forward-looking implementation order. Completed work lives in `PROGRESS.md`, not here.

---

## Observability Suite (Short-term — pre-workshop)

Child PRDs are created via the meta-PRD ([PRD #7](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7)), one per milestone, and built as each is written. Entries are added as each child PRD is created.

- Observability meta-PRD ([PRD #7](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7)) — defines and sequences the child observability PRDs as MVP-first milestones (thin end-to-end vertical increments)

**Build order (MVP-first milestones; each verifiable in the Datadog UI; child PRDs added as created):**

1. MVP: OTel Collector + Datadog connected, UST wired on AI-layer components ([PRD #13](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/13)) — proves Datadog works; locks cross-cutting decisions (collector shape, UST vocabulary, account model)
   - Instrumentation spec: guard-proxy HTTP SERVER span + sanitization tracing ([#19](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/19)) — sub-issue of PRD #13
2. Migrate to OTel GenAI semconv — replace Michael's custom witb_*/tier conventions with gen_ai.* in Datadog LLM Observability ([PRD #20](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/20))
3. Security-beat traces — before/after sanitization (re-leak trap) + rogue MCP tool chain ([PRD #22](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/22))
4. Falco alerts in Datadog — verify Falcosidekick→Event Stream, rename canary rule, confirm C3+C4 rules visible ([PRD #23](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/23))
5. EKS infra & named integrations — Agent DaemonSet, per-component synthesis ([PRD #26](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/26))
6. UST, Service Map & correlation — full-fidelity tagging, Service Map view, log/trace/metric pivots ([PRD #27](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/27))
7. Platform component UST backlog — add `tags.datadoghq.com/*` pod annotations to ArgoCD, Kyverno, Falco, cert-manager, Istio ambient to complete the Service Map ([PRD #28](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/28)) — gated on PRD #27 merging
8. Dashboards — import Datadog community dashboards for components without an OOTB Datadog dashboard; decide custom/story dashboards (build now / defer / skip)
9. Attendee accounts & credentials — per-attendee org provisioning, credential store, distribution, per-cluster secrets

**Optional enhancements (post-M5, if time allows before workshop):**

- Add Istio ambient waypoint proxy for L7 mTLS in exfil challenge ([#25](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/25)) — blocked by M5 (Istio L4 integration active)
