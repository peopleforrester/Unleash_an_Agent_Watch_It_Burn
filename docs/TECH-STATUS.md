<!-- ABOUTME: Status checklist of every technology in the stack: built+tested, verify-at-build (needs a -->
<!-- ABOUTME: live cluster), or to-build. Companion to the Stack Walkthrough (which covers roles, not status). -->

# Tech status checklist

Legend: **[x] built+tested** (manifests/code + offline render-gate green) | **[~] verify-at-build**
(built, but the live behavior is only confirmed on a real cluster, the provisioning track) |
**[ ] to-build**. Offline suite: 15 test files, 118 checks green (`verify/run-tests.sh`).

## Platform + CNCF controls

- [x] Argo CD app-of-apps (full + burn profiles); [~] Synced/Healthy on a live cluster
- [x] Kyverno policies: require-limits (Audit->Enforce toggle), disallow-privileged, require-probes,
  require-labels, require-networkpolicy, restrict-image-registries, block-argocd-drift
- [x] Kyverno verify-image-signatures (cosign, Audit); [~] attestor (Fulcio/Rekor) + Enforce
- [ ] Kyverno **registry-allowlist in Enforce** for the villain-app block (next)
- [x] Falco + custom rules (agent-pod detections, fork-bomb); [x] Falcosidekick -> Talon wired
- [x] Falco Talon (terminate pod on fork bomb); [~] chart version (app v0.3.0)
- [x] NetworkPolicy default-deny + egress allowlist (no internet -> S3 blocked); [~] VPC CIDR + Bedrock endpoint
- [x] PID limit nodeadm config (podPidsLimit); [~] launch-template delivery on AL2023
- [x] Istio ambient + STRICT mTLS (= SPIFFE identity); [~] ztunnel footprint on t3.large
- [x] External Secrets Operator, cert-manager, Backstage; [~] ESO store backing, certs live
- [ ] **Harbor** registry (planned; registry-allowlist works without it)

## Agent + AI guardrails

- [x] kagent Agent + Bedrock ModelConfig (Haiku default; Sonnet/Opus tiers); [~] Bedrock access + A2A usage fields
- [x] guard-proxy: input block-list + classifier (progressive), output Regex, cost meter, rate-limit/cost-cap, prompt-stream
- [x] LLM Guard wiring; [~] verdict envelope on the live image
- [x] agentgateway MCP authz config; [~] enforcement on OSS v1.3.0 with kagent
- [x] kagent toolNames allowlist + requireApproval (HITL); [~] runtime enforcement
- [x] evil-mcp-shim + clown-file (Beat 3 BEFORE)

## Observability

- [x] OTel Collector -> Datadog (primary); [~] Datadog account + API key (Whitney)
- [x] Prometheus/Grafana/Tempo/Loki/Alloy (analog fallback), slimmed; [~] live trace view
- [x] Cost counter (real metering) + Prometheus /metrics + agent-observability dashboard

## Demo, games, access

- [x] Chat UI + moderated prompt-stream display
- [x] ESO/S3 exfil "basketball" game (manifests + scripts); [~] difficulty-level spikes
- [ ] Fake **customer-data streaming app** (attack-1 target) (next)
- [ ] **Villain images** per attendee (attack-2 target) (next)
- [x] Cluster-3 game infra (beat-the-bouncer, tower-defense, trace re-leak, poisoned MCP); framing in doc 8

## Infra + ops

- [x] eksctl cluster configs (1.35, EBS CSI, OIDC); [~] live provision + fleet sizing
- [x] Namecheap demo-DNS tool (agenticburn.com); [~] DNS write deferred to post-provision
- [x] verify harness (run-all + beat-01/02/03 + beat-cost) + offline test suite; [~] live beat assertions
- [x] teardown + cost-report scripts

## The three canonical attacks (Clusters 1 -> 2)

- [x] Attack 1, exfiltrate: egress allowlist is the C2 block (S3 path); reply-leak is the C3 beat
- [ ] Attack 2, villain app: registry-allowlist Enforce + villain images (next)
- [x] Attack 3, fork bomb: PID limit blocks; Falco + Talon respond
