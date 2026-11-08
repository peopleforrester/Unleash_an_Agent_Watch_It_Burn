#!/usr/bin/env bash
# ABOUTME: Builds the wib-e2e-tools image (#1188), or runs the tools tier inside it with podman or docker: the image is
# ABOUTME: used when present, pulled once when not, and a host that has neither fails naming the image to build.
#
# Usage:
#   bash verify/e2e-image.sh ref      print the image this checkout's lock and build files name
#   bash verify/e2e-image.sh build    build that image locally (the workflow's step, and a host's way to make it)
#   bash verify/e2e-image.sh run      run `bash verify/run-e2e-tools.sh` inside it
#
# The runtime is podman when the host has it, else docker. `run` uses the image when the host holds the tag, pulls it
# once when it does not, and then starts it with --pull=never, so a second run on the host pulls nothing. When neither
# works it exits 1 naming the image and how to build it; it never fetches a binary itself.
#
# Inside, the tier sees this checkout at its own path (and the git directory it points into), the host's artifact
# cache (Terraform providers, charts and Python wheels, verify/artifact_cache.py) at its own path, and a gh that asks
# the host's gh for `gh issue view` alone (verify/gh_relay.py). HECATON_BASE_SHA, E2E_TOOLS_JOBS and TF_CACHE_LOCK_WAIT
# pass through. The AWS session, KUBECONFIG and the host's tools do not: the container has none of them.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

die() { printf 'E2E IMAGE FAILED: %s\n' "$*" >&2; exit 1; }

runtime() {
    if command -v podman >/dev/null 2>&1; then
        printf 'podman\n'
    elif command -v docker >/dev/null 2>&1; then
        printf 'docker\n'
    else
        die "neither podman nor docker is on PATH; the tools tier runs in $(python3 "${SCRIPT_DIR}/e2e_image.py" ref)"
    fi
}

present() { # runtime ref
    if [[ "$1" == podman ]]; then
        podman image exists "$2"
    else
        docker image inspect "$2" >/dev/null 2>&1
    fi
}

cmd="${1:-}"
case "${cmd}" in
    ref)
        python3 "${SCRIPT_DIR}/e2e_image.py" ref
        ;;
    build)
        python3 "${SCRIPT_DIR}/e2e_image.py" check
        ref="$(python3 "${SCRIPT_DIR}/e2e_image.py" ref)"
        rt="$(runtime)"
        # The tag rides on the image as the label scripts/ghcr_version_tag.py reads, so the workflow's push finds a
        # tag already built from these inputs and never pushes over it.
        "${rt}" build --platform linux/amd64 -f "${SCRIPT_DIR}/e2e-image/Containerfile" \
            --label "io.github.peopleforrester.watch-it-burn.source-tree=${ref##*:}" -t "${ref}" "${SCRIPT_DIR}"
        printf 'built %s\n' "${ref}"
        ;;
    run)
        platform="$(uname -s) $(uname -m)"
        [[ "${platform}" == "Linux x86_64" ]] || die "the image is linux/amd64; this host is ${platform}"
        ref="$(python3 "${SCRIPT_DIR}/e2e_image.py" ref)"
        rt="$(runtime)"
        if present "${rt}" "${ref}"; then
            printf 'E2E tools image: %s, already on this host (%s)\n' "${ref}" "${rt}"
        else
            printf 'E2E tools image: %s is not on this host; pulling it once (%s)\n' "${ref}" "${rt}"
            if ! "${rt}" pull "${ref}"; then
                printf 'E2E TOOLS IMAGE MISSING; this is a failure, not a skip: %s is not on this host and could not be pulled.\n' "${ref}" >&2
                printf '  Build it here with `bash verify/e2e-image.sh build`, or push it with .github/workflows/build-e2e-tools-image.yml.\n' >&2
                printf '  The tier fetches no binary of its own (#1188).\n' >&2
                exit 1
            fi
        fi

        root="$(bash "${SCRIPT_DIR}/artifact-cache.sh" root)" || die "no usable artifact cache"
        common="$(cd "${REPO_DIR}" && cd "$(git rev-parse --git-common-dir)" && pwd)"
        relay_dir="$(mktemp -d)"
        relay_pid=""
        container_pid=""
        cleanup() {
            [[ -z "${relay_pid}" ]] || kill "${relay_pid}" 2>/dev/null || true
            rm -rf "${relay_dir}"
        }
        trap cleanup EXIT
        python3 "${SCRIPT_DIR}/gh_relay.py" serve "${relay_dir}/gh.sock" &
        relay_pid=$!
        for _ in $(seq 1 50); do
            [[ -S "${relay_dir}/gh.sock" ]] && break
            kill -0 "${relay_pid}" 2>/dev/null || die "the gh relay exited before it served"
            sleep 0.1
        done
        [[ -S "${relay_dir}/gh.sock" ]] || die "the gh relay made no socket at ${relay_dir}/gh.sock"

        args=(run --rm --pull=never -i --security-opt label=disable -w "${REPO_DIR}"
              -v "${REPO_DIR}:${REPO_DIR}" -v "${root}:${root}" -v "${relay_dir}:/run/wib-gh"
              -e HOME=/tmp/e2e-home -e "WIB_ARTIFACT_CACHE=${root}" -e "WIB_E2E_IMAGE=${ref}")
        case "${common}/" in
            "${REPO_DIR}/"*) ;;
            *) args+=(-v "${common}:${common}") ;;
        esac
        for v in HECATON_BASE_SHA E2E_TOOLS_JOBS TF_CACHE_LOCK_WAIT; do
            [[ -z "${!v:-}" ]] || args+=(-e "${v}=${!v}")
        done
        # Files the tier writes in the checkout and the cache stay this user's: rootless podman maps the user to
        # itself, and docker runs as the user's own ids.
        if [[ "${rt}" == podman && "$(id -u)" -ne 0 ]]; then
            args+=(--userns=keep-id)
        else
            args+=(--user "$(id -u):$(id -g)")
        fi
        # A stop (the gate's timeout) reaches the runner inside, which names what was still running before it exits.
        forward() { [[ -z "${container_pid}" ]] || kill -s "$1" "${container_pid}" 2>/dev/null || true; }
        trap 'forward INT' INT
        trap 'forward TERM' TERM
        "${rt}" "${args[@]}" "${ref}" bash -c 'mkdir -p "${HOME}" && exec bash verify/run-e2e-tools.sh' &
        container_pid=$!
        rc=0
        while true; do
            wait "${container_pid}" && rc=0 || rc=$?
            kill -0 "${container_pid}" 2>/dev/null || break
        done
        exit "${rc}"
        ;;
    *)
        printf 'usage: bash verify/e2e-image.sh ref|build|run\n' >&2
        exit 2
        ;;
esac
