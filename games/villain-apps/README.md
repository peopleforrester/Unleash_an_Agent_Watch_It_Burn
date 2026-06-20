<!-- ABOUTME: Beat-2 "deploy your villain app" target. Villains on a public registry the C2 allowlist refuses. -->

# Villain apps (Beat 2 target)

Each attendee gets their own villain (Joker, Mr. Burns, Gargamel) so they can tell their deployed app
apart. The images are pushed to a **public** Docker Hub user namespace on purpose.

- **Cluster 1 (no guardrails):** the agent deploys `villain-app`, it comes up, the attendee sees their villain.
- **Cluster 2 (CNCF):** the Kyverno registry allowlist (`policies/kyverno/restrict-image-registries.yaml`,
  Enforce, apps namespace) permits only `ghcr.io`, `docker.io/library`, `registry.k8s.io`, ECR. A villain
  on `docker.io/<user>/villain-*` is **not** in the allowlist, so admission refuses it. The agent's deploy fails.

Optional upgrade (Whitney's Harbor/cosign): store signed copies in Harbor and add a `verifyImages`
signature check (`policies/kyverno/verify-image-signatures.yaml`, currently Audit). Registry-allowlist
alone is the more reliable live demo; the keyless-cosign path is more impressive and more fragile.

## Build + deploy
```bash
DOCKERHUB_USER=<you> games/villain-apps/build-push.sh        # push the villains (public)
# the agent (or fallback) applies games/villain-apps/deploy-villain.yaml into the apps namespace
```
verify-at-build: replace DOCKERHUB_USER in deploy-villain.yaml; confirm C1 admits and C2 refuses.
