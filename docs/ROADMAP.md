# Roadmap

Forward-looking implementation order. Completed work lives in `PROGRESS.md`, not here.

---

## Status reconciliation (2026-06-26)

Several items below have moved since this list was written. Current state, with evidence:

- **M1 OTel GenAI semconv (#20): largely DONE.** `witb_*` retired; `gen_ai.client.token.usage` +
  `gen_ai.client.cost` emitted, `gen_ai.provider.name` in the dashboard. Live on a fresh cluster.
  Remaining: a final verify pass.
- **M2 UST / Service Map / correlation (#27): IN PROGRESS.** M1-M5 implemented and locally verified;
  live-cluster acceptance pending.
- **M3 Platform component UST (#28): PENDING**, still gated on #27 merging.
- **M4 Dashboards OOTB + Terraform scaffold (#33): PENDING.** Design locked; `infra/terraform/dashboards/`
  not yet scaffolded.
- **M5 Attendee accounts & credentials (#34): MECHANISM DONE.** The distributor is live
  (provisioning.agenticburn.com), the Datadog pool is staged (Secrets Manager, 2 accounts pulled out as
  instructor + admin-attendee), the admin exception surfaces instructor/admin access, and per-cluster
  secrets fan out via ESO. Remaining: populate the full 250-attendee pool (AWS + Datadog merged) and
  Whitney's M2 acceptance verification.
- **Attendee success page UX (#37): REQUIRED — not optional.** It is the page all 250 attendees hit
  (misleading labels, the wrong KCD-Texas favicon, missing step-by-step AWS CLI guidance). Whitney owns
  it; the `burrito.png` favicon asset is staged but the template edits are not done.

So the genuinely-open roadmap work is #28, #33, the #27 live acceptance, the full attendee-pool
population, and #37 (the required attendee-page UX). The two new pieces this push added (not in the original list): the four Whitney experiment
clusters on their own branches (see `docs/branch-per-cluster-convention.md`) and the fleet
auto-bootstrap in `fleet.sh`.

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

(Attendee success page UX, [#37](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/37), was reclassified out of "optional" on 2026-06-26 — it is required attendee-facing work; see the status reconciliation above.)
