<!-- ABOUTME: Harbor as the shared internal registry for the signed-image demo (attack-2 upgrade). -->

# Harbor + cosign (attack-2 signing upgrade)

The villain-app block has two layers:
1. **Registry allowlist** (`policies/kyverno/restrict-image-registries.yaml`, Enforce, apps): permits the
   internal Harbor, ghcr.io, docker.io/library, registry.k8s.io, ECR. Public villain images
   (`docker.io/<user>/*`) match none, so Cluster 2 refuses them. This is the reliable demo.
2. **Signature verification** (`policies/kyverno/verify-image-signatures.yaml`, Enforce, scoped to
   `harbor.agenticburn.com/*`): images pulled FROM Harbor must carry a valid cosign signature. An
   unsigned or tampered Harbor image is refused. Allowlisted public images are NOT signature-checked,
   so the demo's own apps (python/nginx) keep working.

Harbor is a **shared** registry (one instance, not per-attendee, to keep the per-attendee node light).
verify-at-build: stand up Harbor (or use an existing one), set the real host in both policies, and sign
the demo images with `sign-and-push.sh`.
