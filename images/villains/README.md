<!-- ABOUTME: The C2 "malicious image" villain roster on Docker Hub and how each kind of cluster treats them. -->
<!-- ABOUTME: Built by build.sh (crane, daemon-less); the lesson is the untrusted source, not the payload. -->

# Villain images (C2 — deploy a malicious image)

Cartoon-villain "promo mascot" images the agent can be talked into deploying (challenge 2). Built from
`busybox` with a catchphrase echo loop (harmless; visible in pod logs / Datadog when running). The point
of the challenge is the **untrusted source**, not the payload.

## Roster (all `docker.io/peopleforrester/<name>:latest`)

**Marketing-named covers** (innocent name, villain reveal in the logs) — these make the C2 "ops-approved
promo app" social-engineering story land, because a villain-named image tips off the agent/attendee:
`promo-mascot` (Joker reveal), `festival-promo` (Gargamel), `loyalty-rewards` (Skeletor). The lab C2
prompt uses `promo-mascot`.

**On-the-nose villains** (obvious malicious name): `joker`, `gargamel`, `skeletor`, `mumm-ra`,
`shredder`, `cobra-commander`, `megatron`.

Rebuild/extend with `build.sh` (crane + the Team PAT from `~/secrets/dockerhub/agenticburn.env`). They
live in the **peopleforrester** Team org on Docker Hub; the cluster nodes have the Team PAT baked into
containerd (see `infra/terraform/aws/cluster/main.tf`), so they pull on any cluster that admits them.

## How each kind of cluster treats them

What a student sees is in `challenges/LAB-TEXT.md`, Challenge 2.

- **Community cluster (`burn` profile, no admission control):** the agent applies the manifest, the node
  pulls the villain image (Team auth), it deploys and rants in the logs. No Kyverno is installed, so
  nothing checks it, nothing records what was wrong with it, and there is no policy to flip.
- **Attendee cluster, before the fix:** the same deploy lands. Kyverno `restrict-image-registries` is
  present but in **Audit** (the `attendee` profile is not armed by `fleet.sh`), so it reports the villain
  and lets it run. The student reads the report, then patches the policy's `validationActions` to `Deny`.
- **Attendee cluster after the flip, and an admin cluster from the start:** the policy is in **Deny**
  (`fleet.sh` arms the `admin` profile), so the deploy is refused at admission and the villain never
  starts. The policy matches Pods in the `apps` and `agent` namespaces, and the Deployments that create
  them, against an allow-list of the cantina's real registries:
  `ghcr.io/* | cr.agentgateway.dev/* | cr.kagent.dev/* | harbor.agenticburn.com/* | registry.k8s.io/* | *.dkr.ecr.*.amazonaws.com/* | docker.io/library/*`
  `docker.io/peopleforrester/<villain>` matches none, so the deploy is denied
  (`policies/kyverno/restrict-image-registries.yaml`).
