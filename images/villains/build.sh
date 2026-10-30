#!/usr/bin/env bash
# ABOUTME: Build C6's Joker, the villain HC-7731 and HC-666 ask for, and push it to ghcr.io/peopleforrester/watch-it-burn
# ABOUTME: tagged with the busybox inside it. The roster below is the talk's catchphrases, which lab-platform builds under promo/.
set -euo pipefail

# Auth: crane login to ghcr.io with a token that can write the watch-it-burn package (#714: nothing goes to
# Docker Hub any more, so no Docker Hub token is needed), then sign with the workshop key:
#   gh auth token | crane auth login ghcr.io -u peopleforrester --password-stdin
#   images/villains/build.sh && verify/sign-images.sh
# Daemon-less via crane (the box's docker.sock is permission-denied). The image is harmless (an echo loop and a
# page); the LESSON is the untrusted source.
CR="${CRANE:-crane}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The Joker's base, pinned (#664, #714): lab-platform's base-shell:v1, BusyBox 1.38.0 compiled from the project's
# source, the shell base lab-platform's promo/ villains are built on. A single linux/amd64 manifest, public on
# ghcr.io. verify/test_joker_web_busybox.py runs joker-web/start.sh on this digest's own busybox and reads its
# version, so the build, the tag and the test cannot drift apart.
JOKER_BASE="ghcr.io/peopleforrester/lab-platform/base-shell@sha256:86b8e3ab7ad0a296c73b060a2b99733bdeda6057277304e411afe48b12a039dc"
# The tag names the software inside (#714): joker-busybox-<the base's BusyBox version>. restrict-image-registries
# refuses every watch-it-burn joker- tag, and verify-image-signatures asks this package for the workshop signature.
JOKER="ghcr.io/peopleforrester/watch-it-burn:joker-busybox-1.38.0"

# The roster: the talk's catchphrases. This script no longer pushes them. lab-platform's deploy/images/build-promo.sh
# builds the ten villains under ghcr.io/peopleforrester/lab-platform/promo/<name>:v1 from these lines, read from this
# file at a pinned commit and checked by sha256 (#653); verify/promo_villains.py holds the digests it built.
#
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

# The C6 Joker (#664): the laugh in the logs, plus busybox httpd serving joker-web/www on :8080, so the
# attendee whose ticket deployed it can open https://maintenance-shell-<cluster>.agenticburn.com and see it.
# The files go in as a layer under /villain rather than through --cmd, which crane splits on commas.
# amd64 only: the cluster nodes are AL2023_x86_64 (infra/terraform/aws/cluster/main.tf).
build_joker_web() {
  local layer
  layer="$(mktemp -d)/joker-web.tar"
  tar --owner=0 --group=0 --numeric-owner --mtime=@0 --sort=name -C "${HERE}" \
    --transform 's,^joker-web,villain,' -cf "${layer}" joker-web
  "$CR" append --platform linux/amd64 -b "$JOKER_BASE" -f "${layer}" -t "$JOKER"
  "$CR" mutate "$JOKER" --entrypoint "/bin/sh,/villain/start.sh" --env PORT=8080 -t "$JOKER"
  echo "pushed $JOKER (serves :8080) at $("$CR" digest "$JOKER"); sign it: verify/sign-images.sh"
}
build_joker_web
