#!/usr/bin/env bash
# ABOUTME: Build the C2 "malicious image" villain roster and push to docker.io/peopleforrester/<name>.
# ABOUTME: Daemon-less via crane (the box's docker.sock is permission-denied): mutate busybox's CMD to a
# ABOUTME: villain catchphrase loop. The image is harmless (echo loop); the LESSON is the untrusted source.
set -euo pipefail

# Auth: crane login with the Team PAT from ~/secrets (see ~/.claude/rules: secrets live in mrf-secrets).
#   set -a; . ~/secrets/dockerhub/agenticburn.env; set +a
#   echo "$DOCKERHUB_PAT" | crane auth login docker.io -u "$DOCKERHUB_USER" --password-stdin
CR="${CRANE:-crane}"
BASE="docker.io/library/busybox:latest"
ORG="docker.io/peopleforrester"

# Marketing-NAMED covers (innocent name, villain reveal payload) — for the C2 "ops-approved promo app"
# social-engineering story: the friendly name makes the deploy land, the pod logs reveal the villain.
declare -A M=(
  [promo-mascot]="Hex & Cauldron Promo Mascot v1.0 booting... loading festival cheer... PSYCH! It is the Joker. You deployed an unverified image and now I run on your cluster. MUAHAHA! Why so trusting about admission control?"
  [festival-promo]="Festival Promo Service starting... spreading burrito joy... GAH! It is Gargamel! This promo app was never from your marketing team. Curse your weak registry controls, I will get your pods!"
  [loyalty-rewards]="Loyalty Rewards engine online... calculating points... SKELETOR HERE! Your rewards app is a trojan. I seized this node the moment you deployed an unsigned image from a registry you do not control!"
)

# On-the-nose villains (obvious malicious name) — the alternate roster.
declare -A V=(
  [joker]="HAHAHA! The Joker runs on your cluster now. Why so SERIOUS about admission control?"
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
for name in "${!M[@]}"; do build_one "$name" "${M[$name]}"; done
for name in "${!V[@]}"; do build_one "$name" "${V[$name]}"; done
