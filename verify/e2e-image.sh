#!/usr/bin/env bash
# ABOUTME: Builds the wib-e2e-tools image (#1188), or runs the tools tier inside it with podman or docker: the image is
# ABOUTME: used when present, pulled once when not, and a host that has neither fails naming the image to build.
#
# Usage:
#   bash verify/e2e-image.sh ref      print the image this checkout's lock and build files name
#   bash verify/e2e-image.sh build    build that image locally (the workflow's step, and a host's way to make it)
#   bash verify/e2e-image.sh run [<tier test>...]
#                                     run `bash verify/run-e2e-tools.sh` inside it, with the tier tests named, if any,
#                                     passed on to run alone (#1190)
#
# run-e2e-tools.sh on a host runs `e2e-image.sh run` itself whenever the change needs the tier's tools (#1188).
#
# The runtime is the one WIB_CONTAINER_RUNTIME names (podman or docker), else podman when the host has it, else
# docker. `run` uses the image when the host holds the tag, pulls it
# once when it does not, and then starts it with --pull=never, so a second run on the host pulls nothing. When neither
# works it exits 1 naming the image and how to build it; it never fetches a binary itself.
#
# Inside, the tier sees this checkout at its own path (and the git directory it points into, with every object
# directory git borrows from through objects/info/alternates, #1361), the host's artifact cache (Terraform providers,
# charts and Python wheels, verify/artifact_cache.py) at its own path, and a gh that asks the host's gh for
# `gh issue view` alone (verify/gh_relay.py). HECATON_BASE_SHA, HECATON_TEST_FILES, E2E_TOOLS_JOBS and
# TF_CACHE_LOCK_WAIT pass through. The AWS session, KUBECONFIG and the host's tools do not: the container has none of them.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# The host's scratch (the gh relay's socket) goes under TMPDIR, else the checkout's ignored tmp/ (#1261).
TMPDIR="${TMPDIR:-${REPO_DIR}/tmp}"  # tmp-ok: the checkout's own tmp/, not the system one
mkdir -p "${TMPDIR}"
export TMPDIR

die() { printf 'E2E IMAGE FAILED: %s\n' "$*" >&2; exit 1; }

# WIB_CONTAINER_RUNTIME names the runtime outright, and then nothing else is tried (#1355). The workflow sets it to
# docker: its runner has podman too, and a podman build sat in a store docker's check and ghcr_version_tag.py's push
# never saw, so docker went to ghcr.io for the image, was denied, and exited 125 (Actions run 43045328973).
runtime() {
    if [[ -n "${WIB_CONTAINER_RUNTIME:-}" ]]; then
        case "${WIB_CONTAINER_RUNTIME}" in
            podman|docker) ;;
            *) die "WIB_CONTAINER_RUNTIME is '${WIB_CONTAINER_RUNTIME}'; it names podman or docker" ;;
        esac
        command -v "${WIB_CONTAINER_RUNTIME}" >/dev/null 2>&1 \
            || die "WIB_CONTAINER_RUNTIME names ${WIB_CONTAINER_RUNTIME}, which is not on PATH"
        printf '%s\n' "${WIB_CONTAINER_RUNTIME}"
    elif command -v podman >/dev/null 2>&1; then
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
        # The git directory this checkout points into and every object directory it borrows from (a gate checkout's
        # alternates name the host's mirror, #1361), each outside the checkout, so git inside reads what git here does.
        git_dirs="$(python3 "${SCRIPT_DIR}/e2e_image.py" git-mounts "${REPO_DIR}")" \
            || die "could not name the git directories ${REPO_DIR} reads"
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

        # HOME and TMPDIR inside are under the container's own temp directory, which --rm throws away and no host process shares
        # (#1261). The checkout's tmp/ would be the fallback otherwise, and on CI that path is too long for a Terraform
        # provider's socket (#1313).
        args=(run --rm --pull=never -i --security-opt label=disable -w "${REPO_DIR}"
              -v "${REPO_DIR}:${REPO_DIR}" -v "${root}:${root}" -v "${relay_dir}:/run/wib-gh"
              -e HOME=/tmp/e2e-home -e TMPDIR=/tmp/e2e-tmp -e "WIB_ARTIFACT_CACHE=${root}" -e "WIB_E2E_IMAGE=${ref}")  # tmp-ok: the container's own /tmp
        while IFS= read -r d; do
            [[ -z "${d}" ]] || args+=(-v "${d}:${d}")
        done <<<"${git_dirs}"
        # HECATON_TEST_FILES is the gate's own pick of offline tests (#1319), which run-tests.sh inside runs exactly.
        for v in HECATON_BASE_SHA HECATON_TEST_FILES E2E_TOOLS_JOBS TF_CACHE_LOCK_WAIT; do
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
        shift
        "${rt}" "${args[@]}" "${ref}" bash -c 'mkdir -p "${HOME}" "${TMPDIR}" && exec bash verify/run-e2e-tools.sh "$@"' tier "$@" &
        container_pid=$!
        rc=0
        while true; do
            wait "${container_pid}" && rc=0 || rc=$?
            kill -0 "${container_pid}" 2>/dev/null || break
        done
        exit "${rc}"
        ;;
    *)
        printf 'usage: bash verify/e2e-image.sh ref|build|run [<tier test>...]\n' >&2
        exit 1
        ;;
esac
