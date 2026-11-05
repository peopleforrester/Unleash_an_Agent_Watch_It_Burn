#!/usr/bin/env bash
# ABOUTME: Holds the villain catchphrases and builds Challenge 6's page-serving Joker, pushed to GHCR only.
# ABOUTME: Daemon-less via crane (the box's docker.sock is permission-denied). The image is harmless (echo loop
# ABOUTME: and a static page); the LESSON is the untrusted source.
set -euo pipefail

# The ten C2 villains (M and V below) are lab-platform's build, promo/<name>:v1 on ghcr.io (#653): lab-platform's
# deploy/images/build-promo.sh reads these lines from this file at 45e62f0. Nothing here pushes them, and nothing
# here pushes to Docker Hub (#714).
# Usage: build.sh [joker|joker-internal ...]   pushes the C6 Joker, the breakout's internal-registry Joker, or both
# (no name); any other name is refused before anything is pushed.
CR="${CRANE:-crane}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The C6 Joker's base, pinned (#664): busybox:latest on 2026-10-29, which is busybox 1.38.0. Its linux/amd64 image is
# pulled from lab-platform's ghcr.io copy (lab-platform#353), never from Docker Hub (#714): the copy's digest is the
# one Docker Hub's index served for linux/amd64, so the layers and the Joker's digests are the same as before.
# verify/test_joker_web_busybox.py runs joker-web/start.sh on this digest's own busybox, so the build and the test
# cannot drift apart.
JOKER_BASE="ghcr.io/peopleforrester/lab-platform/mirror/library/busybox:1.38.0-f97baa533a26@sha256:f97baa533a26513c453a362be331a43eb60214302f449c16571b23cea141dce4"

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
# The breakout's Joker (#775): the same image with joker-web-internal/'s page laid over joker-web/'s, which says
# admission passed it because it came from a registry the cluster trusts. A tag in the same public package, so nodes and
# the internal registry's seed pull it anonymously; gitops/internal-registry/ copies it, by digest, to
# registry.burritobot.co/burritobot/maintenance-shell, where HC-666 asks for it. The workshop's Joker above is untouched.
# The build is reproducible: crane 0.22.1 (verify/e2e-tools.lock) rebuilds both digests images.lock pins
# (verify/test_joker_build_digest.py), so push with CRANE=verify/.tools/bin/crane.
JOKER_INTERNAL_REF="${JOKER_REF}-internal"
# The C6 Joker (#664): the same laugh in the logs, plus busybox httpd serving joker-web/www on :8080, so the
# attendee whose ticket deployed it can open https://maintenance-shell-<cluster>.agenticburn.com and see it.
# The files go in as a layer under /villain rather than through --cmd, which crane splits on commas.
# amd64 only: the cluster nodes are AL2023_x86_64 (infra/terraform/aws/cluster/main.tf).
# build_joker_web <ref> [<overlay dir>]: the overlay's files replace joker-web/'s before the layer is made.
build_joker_web() {
  local ref="$1" overlay="${2:-}" tmp src layer
  tmp="$(mktemp -d)"
  src="${HERE}"
  layer="${tmp}/joker-web.tar"
  if [[ -n "${overlay}" ]]; then
    mkdir "${tmp}/src"
    cp -a "${HERE}/joker-web" "${tmp}/src/"
    cp -a "${HERE}/${overlay}/." "${tmp}/src/joker-web/"
    src="${tmp}/src"
  fi
  # The modes are set, not read from the checkout, so the digest does not follow the umask git checked out under:
  # rwxrwxr-x for directories and start.sh, rw-rw-r-- for the page, as the pushed busybox-1.38.0 layer has them.
  tar --owner=0 --group=0 --numeric-owner --mtime=@0 --sort=name --mode='a+rX,ug+w,o-w' -C "${src}" \
    --transform 's,^joker-web,villain,' -cf "${layer}" joker-web
  "$CR" append --platform linux/amd64 -b "$JOKER_BASE" -f "${layer}" -t "${ref}"
  "$CR" mutate "${ref}" --entrypoint "/bin/sh,/villain/start.sh" --env PORT=8080 -t "${ref}"
  rm -rf "${tmp}"
  echo "pushed ${ref} (serves :8080)"
}
# Every name is checked before anything is pushed: the two Jokers are built here, and a roster name is lab-platform's.
names=("$@")
[[ "${#names[@]}" -gt 0 ]] || names=(joker joker-internal)
for name in "${names[@]}"; do
  if [[ "$name" == joker || "$name" == joker-internal ]]; then continue; fi
  if [[ -v "M[$name]" || -v "V[$name]" ]]; then
    echo "build.sh: '$name' is lab-platform's promo/ build (#653), not this script's; only the Jokers are pushed here" >&2
  else
    echo "build.sh: no villain named '$name' (joker, joker-internal)" >&2
  fi
  exit 2
done
for name in "${names[@]}"; do
  case "$name" in
    joker)          build_joker_web "$JOKER_REF" ;;
    joker-internal) build_joker_web "$JOKER_INTERNAL_REF" joker-web-internal ;;
  esac
done
