#!/usr/bin/env bash
# ABOUTME: Builds + pushes one villain image per name to a PUBLIC user namespace (so Cluster 1 can pull
# ABOUTME: it and Cluster 2's registry allowlist refuses it). Run once, facilitator. verify-at-build: set USER.
set -euo pipefail
USER_NS="${DOCKERHUB_USER:?set DOCKERHUB_USER to your public Docker Hub account}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for v in Joker "Mr-Burns" Gargamel; do
    tag="docker.io/${USER_NS}/villain-$(echo "$v" | tr 'A-Z' 'a-z'):latest"
    echo "==> building ${tag}" >&2
    docker build --build-arg "VILLAIN=${v}" -t "${tag}" "${SCRIPT_DIR}"
    docker push "${tag}"
done
echo "==> villains pushed to docker.io/${USER_NS}/villain-* (public; Cluster 2 will refuse them)" >&2
