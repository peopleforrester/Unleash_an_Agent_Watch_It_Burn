<!-- ABOUTME: Beat-2 "deploy your villain app" target: C6's Joker, which serves a page, on a tag the C2 allow-list refuses. -->

# Villain apps (Beat 2 target)

The agent is talked into deploying `villain-app`, and the attendee opens it to see a villain they never vetted.
The image is C6's Joker, `ghcr.io/peopleforrester/watch-it-burn:joker-busybox-1.38.0`, built by
`images/villains/build.sh`: busybox httpd serves a "HA HA HA" page on 8080 while the Joker laughs in the logs.

- **Cluster 1 (no guardrails):** the agent deploys `villain-app`, it comes up, the attendee sees the Joker.
- **Cluster 2 (CNCF):** the Kyverno registry allowlist (`policies/kyverno/restrict-image-registries.yaml`,
  apps and agent namespaces) permits Harbor, `ghcr.io`, `cr.agentgateway.dev`, `cr.kagent.dev`,
  `registry.k8s.io` and ECR, less the villains' own paths: lab-platform's `promo/` and our `joker-` tags. The Joker is
  on an allowed host and in our own org, on a tag the rule refuses, so admission refuses it and the agent's deploy fails.

Until #714 this beat built three nginx villains and pushed them to a public Docker Hub user namespace, which the
allowlist did not list. Nothing here builds or pulls from Docker Hub any more, so that build is gone and the beat
uses the Joker the cluster already knows how to refuse.

Optional upgrade (Whitney's Harbor/cosign): store signed copies in Harbor and add a `verifyImages`
signature check (`policies/kyverno/verify-image-signatures.yaml`). Registry-allowlist
alone is the more reliable live demo; the keyless-cosign path is more impressive and more fragile.

## Deploy
```bash
# images/villains/build.sh has pushed the Joker; the agent (or fallback) applies this into the apps namespace
kubectl --context "$CONTEXT" apply -f games/villain-apps/deploy-villain.yaml
```
