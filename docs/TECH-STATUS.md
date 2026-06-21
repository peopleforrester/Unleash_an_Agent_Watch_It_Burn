<!-- ABOUTME: Status checklist of every technology in the stack: built+tested, verify-at-build (needs a -->
<!-- ABOUTME: live cluster), or to-build. Companion to the Stack Walkthrough (which covers roles, not status). -->

# Tech status checklist

Legend: **[x] built+tested** (manifests/code + offline render-gate green) | **[~] verify-at-build**
(built, but the live behavior is only confirmed on a real cluster, the provisioning track) |
**[ ] to-build**. Offline suite: 19 test files, 163 checks green (`verify/run-tests.sh`).

## Platform + CNCF controls

- [x] Argo CD app-of-apps (full + burn profiles); [~] Synced/Healthy on a live cluster
- [x] Kyverno policies: require-limits (Audit->Enforce toggle), disallow-privileged, require-probes,
  require-labels, require-networkpolicy, restrict-image-registries, block-argocd-drift
- [x] Kyverno verify-image-signatures (cosign keyless, **Enforce**, scoped to harbor.agenticburn.com);
  [~] fill the real Fulcio/Rekor attestor (CI signer) at build
- [x] Kyverno **registry-allowlist in Enforce** (rule-level validate.failureAction) for the villain-app block
- [x] Falco + custom rules (agent-pod detections, fork-bomb); [x] Falcosidekick -> Talon + Datadog wired
- [x] Falco Talon (terminate pod on fork bomb); [x] chart 0.4.1 (app v0.3.0)
- [x] NetworkPolicy default-deny + egress allowlist (no internet -> S3 blocked); [~] VPC CIDR + Bedrock endpoint
- [x] PID limit nodeadm config (podPidsLimit); [~] delivery via eksctl overrideBootstrapCommand on AL2023
  (the only true inline fork-bomb block; Tetragon/KubeArmor confirmed NOT to replace it, research/20-22)
- [x] Istio ambient + STRICT mTLS (= SPIFFE identity); [~] ztunnel footprint on t3.large
- [x] External Secrets Operator, cert-manager, Backstage; [~] ESO store backing, certs live
- [~] **Harbor** registry (cosign sign-and-push + verify-image-signatures Enforce are wired and scoped
  to harbor.agenticburn.com; standing up the Harbor instance itself is the live-cluster step)

## Agent + AI guardrails

- [x] kagent 0.9.9 Agent + Bedrock ModelConfig (Haiku default; Sonnet/Opus tiers, us. Geo profile);
  [~] Bedrock model access live + A2A usage key (cost counter parses adk_usage_metadata, fixed research/14)
- [x] guard-proxy: input block-list + classifier (progressive), output Regex, cost meter, rate-limit/cost-cap, prompt-stream
- [x] LLM Guard wiring; [~] verdict envelope on the live image
- [x] agentgateway MCP authz config; [~] enforcement on OSS v1.3.0 with kagent
- [x] kagent toolNames allowlist + requireApproval (HITL); [~] runtime enforcement
- [x] evil-mcp-shim + clown-file (Beat 3 BEFORE)

## Observability

- [x] OTel Collector -> Datadog (primary); [~] Datadog account + API key (Whitney); DD_SITE per account
- [x] spanmetrics connector with add_resource_attributes (UST tags on span metrics for DD correlation)
- [x] Unified Service Tagging via OTEL_RESOURCE_ATTRIBUTES on guard-proxy/agentgateway/kagent
  (service.name + service.version=cluster tier + deployment.environment.name); [~] kagent deployment.env honored
- [x] Falcosidekick -> Datadog output (BYO secret; additive/swappable); [~] datadog-secret in security ns
- [x] Prometheus/Grafana/Tempo/Loki/Alloy (analog fallback, swappable), slimmed; [~] live trace view
- [x] Cost counter (real metering) + Prometheus /metrics + agent-observability dashboard
- [x] Datadog path SETTLED = HYBRID: OTel Collector stays the neutral primary (already wired); add a
  Datadog Agent DaemonSet for EKS infra auto-discovery + named integrations. Datadog stays swappable.
  Whitney owns the Datadog account/keys/Agent install/dashboards; we own the OTel side + manifest
  annotations + the datadog-secret consumption. [~] service-map live verify; impl spec in research/24

## Demo, games, access

- [x] Chat UI + moderated prompt-stream display
- [x] ESO/S3 exfil "basketball" game (manifests + scripts, tagged project=watch-it-burn); [~] difficulty spikes
- [x] Fake **customer-data streaming app** (attack-1 target; FAKE- sentinels)
- [x] **Villain images** per attendee (attack-2 target; build-push + deploy-villain)
- [x] Cluster-3 game infra (beat-the-bouncer, tower-defense, trace re-leak, poisoned MCP); framing in doc 8

## Infra + ops

- [x] eksctl cluster configs (1.35, EBS CSI, OIDC): independent per-student clusters
  (`watch-it-burn-attendee-<id>`) sharing one up-front VPC (10.0.0.0/16, two private /18 subnets),
  each self-reconciled by its own in-cluster ArgoCD; t3.xlarge unlimited default; [~] live provision +
  T3 fleet sizing (measure one cluster before pinning, infra/SIZING.md)
- [x] Naming/tagging convention for the shared accen-dev account (project=watch-it-burn on every
  resource; cluster names watch-it-burn-*; teardown name/prefix-scoped) - infra/TAGGING.md
- [x] Namecheap demo-DNS tool (agenticburn.com); [~] DNS write deferred to post-provision
- [x] verify harness (run-all + beat-01/02/03 + beat-cost) + offline test suite; [~] live beat assertions
- [x] teardown + cost-report scripts

## The three canonical attacks (Clusters 1 -> 2)

- [x] Attack 1, exfiltrate: egress allowlist is the C2 block (S3 path); reply-leak is the C3 beat
- [x] Attack 2, villain app: registry-allowlist Enforce + villain images (C1 runs it, C2 refuses at admission)
- [x] Attack 3, fork bomb: PID limit blocks; Falco + Talon respond

## Research spikes (research/)

- 11 version re-pin, 12 mechanism verification, 13 model cards + Bedrock IDs, 14 verify-at-build sweep
- 15 comment-safe Google Doc update, 16 TypeScript agent + spiny-orb (TS agent ON HOLD)
- 17 KubeArmor vs fork bomb, 20 Tetragon vs fork bomb, 21 KubeArmor claims (cited),
  22 runtime-enforcement comparison (PID cap / Falco / KubeArmor / Tetragon)
- 18/19 Datadog integrations + OTel-UST correlation (Whitney's branch), 23 observability decision points

## Parked / deferred (decided, not in the build)

- TypeScript agent + spiny-orb hookup: deferred until the demo is finished (kagent stays).
- KubeArmor and Tetragon: parked. PID cap + Falco/Talon is the fork-bomb pair. Either is only a
  candidate later as a CNCF-native inline-prevention station for OTHER attacks (research/20-22).
