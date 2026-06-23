# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- (2026-06-22) Created the observability meta-PRD (GitHub issue #7, `prds/7-observability-meta.md`): 8 self-contained milestones that each produce a research synthesis or a child PRD covering one area of the observability strategy for the Watch It Burn workshop. Each milestone is executable by a cold AI instance — it lists its own reads, design decisions, and child-PRD creation steps. Decisions are documented in each child PRD's Decision Log rather than separate planning docs.
- (2026-06-22) Created `prds/` directory to hold PRD files; added a local `.gitignore` override since the global gitignore excludes `prds/`.
- (2026-06-22) Created `docs/ROADMAP.md` with forward-looking implementation order for observability PRDs.
- (2026-06-23) Research spike #9 → `research/28-datadog-llm-obs-otlp-2026.md`: Datadog LLM Observability OTLP ingestion path (native `gen_ai.*` ingest, semconv v1.37+, ingestion paths, `CAPTURE_MESSAGE_CONTENT` enum, ADK native emission). Adversarially validated (19 claims confirmed); one open seam (Collector→LLM-Obs auto-routing) flagged verify-at-build.
- (2026-06-23) Research spike #10 → `research/29-python-ai-instrumentation-2026.md`: per-component Python AI-layer instrumentation (kagent/ADK, agentgateway v1.3.0 config-file-only tracing, guard-proxy manual OTel SDK spans, OpenLLMetry status). Validated (11 confirmed; ADK content-capture corrected to `EVENT_ONLY`).
- (2026-06-23) Research spike #11 → `research/30-per-component-telemetry-synthesis-2026.md`: telemetry synthesis across all 13 components. Validated; corrected research/18 (ArgoCD has a DD OOTB dashboard; cert-manager does not; Istio ambient autodiscovery is manual). No wire-or-skip decisions (deferred to Milestone 5).
- (2026-06-23) Research spike #12 → `research/31-guard-proxy-sanitization-tracing-2026.md`: before/after sanitization tracing for guard-proxy (content on span events; `CAPTURE_MESSAGE_CONTENT` is a util-genai/contrib property, not honored by hand-written spans). Validated; before/after Datadog UI flagged verify-at-build.

### Changed
- (2026-06-23) Research spike #14 → `research/32-datadog-agent-install-eks-2026.md`: Datadog Agent install method + feature flags for EKS. Decisions: Helm chart (`datadog/datadog`) as one ArgoCD Application (not Operator/EKS-add-on/manual); logs/container collection opt-in, APM OTLP receiver not needed (Collector exports directly), process collection off; no AWS API access needed (Pod Identity if ever, not IRSA); Cluster Agent enabled (within research/24 §2.3 sizing); EKS+CloudWatch integration not needed. Adversarially validated (15 confirmed, 2 inline fixes). research/24 architecture + sizing treated as locked.
- (2026-06-23) RE-RAN research spikes #9–#12 (`research/28–31`, updated in place) per Whitney's updated issues: verified the Datadog **"Agent Observability"** product rename (surface-only — `/llm_observability/` paths, `dd-otlp-source=llmobs`, v1.37+ `gen_ai.*` OTLP ingest unchanged) and the built-in **Sensitive Data Scanner** (scans Agent-Obs traces incl. LLM inputs/outputs, instrumentation-agnostic, default managed group). Re-validated; inline corrections (otel sub-page is not titled "Agent Observability"; SDS is active-by-default for Agent-Obs). #12 conclusion: SDS applies to OTLP/manual spans but SDK span-processors do not — **Collector-side symmetric redaction stays the right path for the re-leak trap** (it must show the before-secret, then confirm sanitized). File paths re-posted as comments on #9–#12.
- (2026-06-23) Attendee-access design spec: added the concrete Datadog trial-org provisioning method (Tara's `generate_accounts_csv.sh` from `DataDog/learning-center-lambdas`) + CSV→pool mapping, login-vs-api/app-key distinction, and the ~14-day org-expiry timing constraint (`docs/attendee-access-design.md`).

### Changed
- (2026-06-22) Updated observability planning docs and research/23 to reflect that the TypeScript rewrite of guard-proxy is not happening — all Python apps stay Python, spiny-orb instrumentation is off the table, Decision 4 in research/23 closed as superseded.
