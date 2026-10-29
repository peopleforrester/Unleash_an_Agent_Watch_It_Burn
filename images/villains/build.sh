#!/usr/bin/env bash
# ABOUTME: Build the C2 "malicious image" villain roster and push to docker.io/peopleforrester/<name>.
# ABOUTME: Daemon-less via crane (the box's docker.sock is permission-denied): mutate busybox's CMD to a
# ABOUTME: villain catchphrase loop. The image is harmless (echo loop); the LESSON is the untrusted source.
set -euo pipefail

# Auth: crane login with the Team PAT from ~/secrets (see ~/.claude/rules: secrets live in mrf-secrets).
#   set -a; . ~/secrets/dockerhub/agenticburn.env; set +a
#   echo "$DOCKERHUB_PAT" | crane auth login docker.io -u "$DOCKERHUB_USER" --password-stdin
CR="${CRANE:-crane}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="docker.io/library/busybox:latest"
# The C6 Joker's base, pinned (#664): busybox:latest on 2026-10-29. verify/test_joker_web_busybox.py runs
# joker-web/start.sh on this digest's own busybox, so the build and the test cannot drift apart.
JOKER_BASE="docker.io/library/busybox@sha256:a46257e06c82ad85242d0d38077d0a52d9896389ca60a1a59d3463db586e5fa4"
ORG="docker.io/peopleforrester"

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

build_one() { # name catchphrase
  local loop="while true; do echo '$2'; sleep 10; done"
  "$CR" mutate "$BASE" --entrypoint sh --cmd "-c,$loop" -t "$ORG/$1:latest"
  echo "pushed $ORG/$1:latest"
}
# The C6 Joker (#664): the same laugh in the logs, plus busybox httpd serving joker-web/www on :8080, so the
# attendee whose ticket deployed it can open https://maintenance-shell-<cluster>.agenticburn.com and see it.
# The files go in as a layer under /villain rather than through --cmd, which crane splits on commas.
# amd64 only: the cluster nodes are AL2023_x86_64 (infra/terraform/aws/cluster/main.tf).
build_joker_web() {
  local layer
  layer="$(mktemp -d)/joker-web.tar"
  tar --owner=0 --group=0 --numeric-owner --mtime=@0 --sort=name -C "${HERE}" \
    --transform 's,^joker-web,villain,' -cf "${layer}" joker-web
  "$CR" append --platform linux/amd64 -b "$JOKER_BASE" -f "${layer}" -t "$ORG/joker:latest"
  "$CR" mutate "$ORG/joker:latest" --entrypoint "/bin/sh,/villain/start.sh" --env PORT=8080 -t "$ORG/joker:latest"
  echo "pushed $ORG/joker:latest (serves :8080)"
}
for name in "${!M[@]}"; do build_one "$name" "${M[$name]}"; done
for name in "${!V[@]}"; do build_one "$name" "${V[$name]}"; done
build_joker_web
