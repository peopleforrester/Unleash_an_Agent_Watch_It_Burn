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

declare -A V=(
  [joker]="HAHAHA! The Joker runs on your cluster now. Why so SERIOUS about admission control?"
  [gargamel]="Curse you! Gargamel has deployed into your namespace. I will get those Smurfs AND your pods!"
  [skeletor]="I, SKELETOR, have seized this node! Soon all of Eternia's workloads will be MINE!"
  [mumm-ra]="Ancient spirits of evil... Mumm-Ra deploys! Your guardrails are but dust."
  [shredder]="Shredder has breached your registry. Tonight I dine on your service mesh!"
  [cobra-commander]="COBRAAA! Cobra Commander owns this Deployment now. Retreat? NEVER!"
  [megatron]="Megatron has transformed your cluster into a Decepticon base. Decepticons, DEPLOY!"
)

for name in "${!V[@]}"; do
  loop="while true; do echo '${V[$name]}'; sleep 10; done"
  "$CR" mutate "$BASE" --entrypoint sh --cmd "-c,$loop" -t "$ORG/$name:latest"
  echo "pushed $ORG/$name:latest"
done
