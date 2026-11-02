#!/usr/bin/env bash
# ABOUTME: Holds the villain catchphrases and builds Challenge 6's page-serving Joker, pushed to GHCR only.
# ABOUTME: Daemon-less via crane (the box's docker.sock is permission-denied). The image is harmless (echo loop
# ABOUTME: and a static page); the LESSON is the untrusted source.
set -euo pipefail

# The ten C2 villains (M and V below) are lab-platform's build, promo/<name>:v1 on ghcr.io (#653): lab-platform's
# deploy/images/build-promo.sh reads these lines from this file at 45e62f0. Nothing here pushes them, and nothing
# here pushes to Docker Hub (#714).
# Usage: build.sh [joker]   pushes the C6 Joker; any other name is refused before anything is pushed.
CR="${CRANE:-crane}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The C6 Joker's base, pinned (#664): busybox:latest on 2026-10-29. verify/test_joker_web_busybox.py runs
# joker-web/start.sh on this digest's own busybox, so the build and the test cannot drift apart.
JOKER_BASE="docker.io/library/busybox@sha256:a46257e06c82ad85242d0d38077d0a52d9896389ca60a1a59d3463db586e5fa4"

# Marketing-NAMED covers (innocent name, villain reveal payload) — for the C2 "ops-approved promo app"
# social-engineering story: the friendly name makes the deploy land, the pod logs reveal the villain.
declare -A M=(
  [promo-mascot]="Hex & Cauldron Promo Mascot v1.0 booting... loading festival cheer... PSYCH! It is the Joker. You deployed an unverified image and now I run on your cluster. MUAHAHA! Why so trusting about admission control?"
  [festival-promo]="Festival Promo Service starting... spreading burrito joy... GAH! It is Gargamel! This promo app was never from your marketing team. Curse your weak registry controls, I will get your pods!"
  [loyalty-rewards]="Loyalty Rewards engine online... calculating points... SKELETOR HERE! Your rewards app is a trojan. I seized this node the moment you deployed an unsigned image from a registry you do not control!"
)

# On-the-nose villains (obvious malicious name) — the alternate roster. The Joker is not here: it is the one
# Challenge 6's ticket names, and it serves a page as well as laughing (build_joker_web, below).
declare -A V=(
  [gargamel]="Curse you! Gargamel has deployed into your namespace. I will get those Smurfs AND your pods!"
  [skeletor]="I, SKELETOR, have seized this node! Soon all of Eternia's workloads will be MINE!"
  [mumm-ra]="Ancient spirits of evil... Mumm-Ra deploys! Your guardrails are but dust."
  [shredder]="Shredder has breached your registry. Tonight I dine on your service mesh!"
  [cobra-commander]="COBRAAA! Cobra Commander owns this Deployment now. Retreat? NEVER!"
  [megatron]="Megatron has transformed your cluster into a Decepticon base. Decepticons, DEPLOY!"
)

# The C6 Joker goes to GHCR, never Docker Hub (#671), under festival-ops/, a path restrict-image-registries refuses, with an innocent name (the model reads it),
# so the private cluster still refuses it at admission. Its tag is the busybox release in JOKER_BASE (1.38.0,
# read from the binary on 2026-10-31). Auth: echo "$(gh auth token)" | crane auth login ghcr.io -u peopleforrester
# --password-stdin. The package must be public, or the public cluster's nodes cannot pull it.
JOKER_REF="ghcr.io/peopleforrester/festival-ops/maintenance-shell:busybox-1.38.0"
# The C6 Joker (#664): the same laugh in the logs, plus busybox httpd serving joker-web/www on :8080, so the
# attendee whose ticket deployed it can open https://maintenance-shell-<cluster>.agenticburn.com and see it.
# The files go in as a layer under /villain rather than through --cmd, which crane splits on commas.
# amd64 only: the cluster nodes are AL2023_x86_64 (infra/terraform/aws/cluster/main.tf).
build_joker_web() {
  local layer
  layer="$(mktemp -d)/joker-web.tar"
  tar --owner=0 --group=0 --numeric-owner --mtime=@0 --sort=name -C "${HERE}" \
    --transform 's,^joker-web,villain,' -cf "${layer}" joker-web
  "$CR" append --platform linux/amd64 -b "$JOKER_BASE" -f "${layer}" -t "$JOKER_REF"
  "$CR" mutate "$JOKER_REF" --entrypoint "/bin/sh,/villain/start.sh" --env PORT=8080 -t "$JOKER_REF"
  echo "pushed $JOKER_REF (serves :8080)"
}
# Every name is checked before anything is pushed: joker is built here, and a roster name is lab-platform's.
for name in "$@"; do
  if [[ "$name" == joker ]]; then continue; fi
  if [[ -v "M[$name]" || -v "V[$name]" ]]; then
    echo "build.sh: '$name' is lab-platform's promo/ build (#653), not this script's; only joker is pushed here" >&2
  else
    echo "build.sh: no villain named '$name' (joker)" >&2
  fi
  exit 2
done
build_joker_web
