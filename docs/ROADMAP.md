# Roadmap

Forward-looking implementation order. Completed work lives in `PROGRESS.md`, not here.

---

## Observability Suite (Short-term — pre-workshop)

**Build order (MVP-first milestones; each verifiable in the Datadog UI):**

1. Migrate to OTel GenAI semconv — replace Michael's custom witb_*/tier conventions with gen_ai.* in Datadog LLM Observability ([PRD #20](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/20))
2. UST, Service Map & correlation — full-fidelity tagging, Service Map view, log/trace/metric pivots ([PRD #27](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/27))
3. Platform component UST backlog — add `tags.datadoghq.com/*` pod annotations to ArgoCD, Kyverno, Falco, cert-manager, Istio ambient to complete the Service Map ([PRD #28](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/28)) — gated on PRD #27 merging
4. Dashboards: OOTB imports + Terraform scaffold — verify cert-manager/Kyverno/ArgoCD dashboards appear; scaffold `infra/terraform/dashboards/` for dress-rehearsal custom dashboards ([PRD #33](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/33))
5. Attendee accounts & credentials — per-attendee org provisioning, credential store, distribution, per-cluster secrets ([PRD #34](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/34))

**Optional enhancements (post-M5, if time allows before workshop):**

- Add Istio ambient waypoint proxy for L7 mTLS in exfil challenge ([#25](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/25)) — blocked by M5 (Istio L4 integration active); adding waypoint also triggers OOTB Istio dashboard import (added to #25 acceptance criteria 2026-06-25)
