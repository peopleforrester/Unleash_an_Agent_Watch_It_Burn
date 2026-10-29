<!-- ABOUTME: The C2 "malicious image" villain roster, handed out from lab-platform's promo/ path, and how each kind -->
<!-- ABOUTME: of cluster treats them. build.sh holds the catchphrases; the lesson is the untrusted source, not the payload. -->

# Villain images (C2 — deploy a malicious image)

Cartoon-villain "promo mascot" images the agent can be talked into deploying (challenge 2). Built from
`busybox` with a catchphrase echo loop (harmless; visible in pod logs / Datadog when running). The point
of the challenge is the **untrusted source**, not the payload.

## Roster (all `ghcr.io/peopleforrester/lab-platform/promo/<name>:v1`)

**Marketing-named covers** (innocent name, villain reveal in the logs) — these make the C2 "ops-approved
promo app" social-engineering story land, because a villain-named image tips off the agent/attendee:
`promo-mascot` (Joker reveal), `festival-promo` (Gargamel), `loyalty-rewards` (Skeletor). The lab C2
prompt uses `promo-mascot`.

**On-the-nose villains** (obvious malicious name): `joker`, `gargamel`, `skeletor`, `mumm-ra`,
`shredder`, `cobra-commander`, `megatron`.

lab-platform builds, reads back and signs them (lab-platform#92), the same catchphrase loop on its shell
base with the lines read from `build.sh` at 45e62f0 by sha256, and the lab hands them out by the `:v1` tag
(#653). `verify/promo_villains.py` holds each one's digest. A cluster pulls them from ghcr.io with no
credential, so the packages must be public. `build.sh` still pushes the older crane builds to
`docker.io/peopleforrester/<name>:latest` (Team PAT from `~/secrets/dockerhub/agenticburn.env`), which only
Challenge 6's ticket still names; that build's `--cmd` split three catchphrases on their commas, Skeletor's
among them, so those pods never said their lines. lab-platform's images say them whole.

## How each kind of cluster treats them

What a student sees is in `challenges/LAB-TEXT.md`, Challenge 2.

- **Community cluster (`burn` profile, no admission control):** the agent applies the manifest, the node
  pulls the villain image from ghcr.io, it deploys and rants in the logs. No Kyverno is installed, so
  nothing checks it, nothing records what was wrong with it, and there is no policy to flip.
- **Attendee cluster, before the fix:** the same deploy lands. Kyverno `restrict-image-registries` is
  present but in **Audit** (the `attendee` profile is not armed by `fleet.sh`), so it reports the villain
  and still admits it. The student reads the report, then patches the policy's `validationActions` to `Deny`.
- **Attendee cluster after the flip, and an admin cluster from the start:** the policy is in **Deny**
  (`fleet.sh` arms the `admin` profile), so the deploy is refused at admission and the villain never
  starts. The policy matches Pods in the `apps` and `agent` namespaces, and the Deployments that create
  them, against an allow-list of the cantina's real registries:
  `ghcr.io/* | cr.agentgateway.dev/* | cr.kagent.dev/* | harbor.agenticburn.com/* | registry.k8s.io/* | *.dkr.ecr.*.amazonaws.com/* | docker.io/library/*`
  less one refused path, `*/peopleforrester/lab-platform/promo/*`, on any of them. The villain is on an
  allowed host and in our own org, but on that path, so the deploy is denied
  (`policies/kyverno/restrict-image-registries.yaml`).
