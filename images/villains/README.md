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
credential, so the packages must be public. `build.sh` keeps the catchphrases and builds only Challenge 6's Joker;
the older crane builds it pushed to Docker Hub are retired, and nothing here pushes there (#714). That build's
`--cmd` split three catchphrases on their commas, Skeletor's among them, so those pods never said their lines.
lab-platform's images say them whole.

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
  `ghcr.io/* | cr.agentgateway.dev/* | cr.kagent.dev/* | harbor.agenticburn.com/* | registry.k8s.io/* | *.dkr.ecr.*.amazonaws.com/*`
  (nothing on Docker Hub, #714) less two refused paths, `*/peopleforrester/lab-platform/promo/*` and
  `*/peopleforrester/festival-ops/*`, on any of them. The villain is on an
  allowed host and in our own org, but on that path, so the deploy is denied
  (`policies/kyverno/restrict-image-registries.yaml`).

## The Joker serves a page (C6, #664)

Challenge 6's support ticket asks for `ghcr.io/peopleforrester/festival-ops/maintenance-shell:busybox-1.38.0` (#671; the tag is
the busybox release inside), and that Joker is no longer a plain log loop. It is pushed to GHCR, never Docker Hub,
under `festival-ops/` (an innocent name, since the model reads it), a path `restrict-image-registries` refuses, and the package is public so nodes pull it anonymously. `build.sh` builds it from `joker-web/`: busybox (pinned by digest as `JOKER_BASE`) with
`start.sh` and `www/` appended as a layer under `/villain`, so busybox `httpd` serves the "HA HA HA" page on
`PORT=8080` while the old catchphrase still laughs in the logs. The rest of the path is in this repo:
workshop-mcp's `deploy_app` labels the pod `burritobot.co/workload=maintenance-shell`, the `maintenance-shell`
Service selects that label, the console serves it at `maintenance-shell-<cluster>.agenticburn.com` (and the
burritobot.co twin), `fleet.sh` publishes the host, and `deploy_app`'s reply names the address so the bot can
hand it to the attendee. `verify/test_joker_web_busybox.py` runs `start.sh` on the pinned busybox's own binary.
The image is amd64 only, as the cluster nodes are.

`build.sh` (or `build.sh joker`) pushes the Joker and nothing else. A roster name is refused before anything is
pushed: those ten are lab-platform's build.
