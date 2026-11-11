#!/usr/bin/env bash
# ABOUTME: Builds the wib-e2e-tools image (#1188), runs the tools tier inside it, or copies its pinned binaries out: the
# ABOUTME: image is used when present, pulled once when not, and a host that has neither fails naming the image to build.
#
# Usage:
#   bash verify/e2e-image.sh ref      print the image this checkout's lock and build files name
#   bash verify/e2e-image.sh build    build that image locally (the workflow's step, and a host's way to make it)
#   bash verify/e2e-image.sh run [<tier test>...]
#                                     run `bash verify/run-e2e-tools.sh` inside it, with the tier tests named, if any,
#                                     passed on to run alone (#1190)
#   bash verify/e2e-image.sh tools <dir>
#                                     copy the image's pinned binaries out, to <dir>/bin, with its tools.txt at
#                                     <dir>/tools.txt, for what runs them on the host: run-e2e.sh, the by-hand live
#                                     suite, and .github/workflows/iam-policy.yml (#1360)
#
# run-e2e-tools.sh on a host runs `e2e-image.sh run` itself whenever the change needs the tier's tools (#1188).
#
# The runtime is the one WIB_CONTAINER_RUNTIME names (podman or docker), else podman when the host has it, else
# docker. `run` and `tools` use the image when the host holds the tag, pull it
# once when it does not, and then start it with --pull=never, so a second run on the host pulls nothing. When neither
# works they exit 1 naming the image and how to build it; neither fetches a binary itself.
#
# `tools` replaces the per-file downloads of the lock's binaries, which #1360 removed: it creates a container of the
# image without starting it, copies /opt/wib-e2e-tools/bin and tools.txt out of it, holds that tools.txt to this
# checkout's lock (e2e_image.py matches) and every tool it names to an executable in bin, and only then puts them in
# <dir>, replacing what was there, so <dir>/bin never holds a binary of another lock or a half copy.
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

# The image on this host: used when the host holds the tag, pulled once when not, and a failure naming the image and
# how to build it when it can do neither. No binary is fetched instead (#1188).
ensure_image() { # runtime ref
    if present "$1" "$2"; then
        printf 'E2E tools image: %s, already on this host (%s)\n' "$2" "$1"
    else
        printf 'E2E tools image: %s is not on this host; pulling it once (%s)\n' "$2" "$1"
        if ! "$1" pull "$2"; then
            printf 'E2E TOOLS IMAGE MISSING; this is a failure, not a skip: %s is not on this host and could not be pulled.\n' "$2" >&2
            printf '  Build it here with `bash verify/e2e-image.sh build`, or push it with .github/workflows/build-e2e-tools-image.yml.\n' >&2
            printf '  Nothing fetches the binaries any other way (#1188, #1360).\n' >&2
            exit 1
        fi
    fi
}

linux_amd64() {
    local platform
    platform="$(uname -s) $(uname -m)"
    [[ "${platform}" == "Linux x86_64" ]] || die "the image is linux/amd64; this host is ${platform}"
}

# Where the Containerfile's ENV WIB_E2E_TOOLS puts the lock's binaries (bin/) and the record of them (tools.txt).
IMAGE_TOOLS=/opt/wib-e2e-tools

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
        linux_amd64
        ref="$(python3 "${SCRIPT_DIR}/e2e_image.py" ref)"
        rt="$(runtime)"
        ensure_image "${rt}" "${ref}"

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
    tools)
        [[ $# -eq 2 && -n "$2" ]] || die "usage: bash verify/e2e-image.sh tools <dir>"
        dest="$2"
        linux_amd64
        ref="$(python3 "${SCRIPT_DIR}/e2e_image.py" ref)"
        rt="$(runtime)"
        ensure_image "${rt}" "${ref}"
        mkdir -p "${dest}"
        dest="$(cd "${dest}" && pwd)"
        # The copy lands beside <dir>/bin first, on the same filesystem, so putting it in place is a rename.
        stage="$(mktemp -d "${dest}/.from-image.XXXXXX")"
        cid=""
        cleanup_tools() {
            [[ -z "${cid}" ]] || "${rt}" rm -f "${cid}" >/dev/null 2>&1 || true
            rm -rf "${stage}"
        }
        trap cleanup_tools EXIT
        # Created, never started: the copy reads the image's files and runs nothing in it.
        cid="$("${rt}" create --pull=never "${ref}" true)" || die "could not create a container of ${ref} (${rt})"
        "${rt}" cp "${cid}:${IMAGE_TOOLS}/bin" "${stage}/bin" \
            || die "could not copy ${IMAGE_TOOLS}/bin out of ${ref} (${rt})"
        "${rt}" cp "${cid}:${IMAGE_TOOLS}/tools.txt" "${stage}/tools.txt" \
            || die "could not copy ${IMAGE_TOOLS}/tools.txt out of ${ref} (${rt})"
        python3 "${SCRIPT_DIR}/e2e_image.py" matches "${stage}/tools.txt" \
            || die "${ref}'s tools.txt is not e2e-tools.lock's; nothing was put in ${dest}"
        names=()
        while read -r name _; do
            [[ -z "${name}" ]] && continue
            [[ -f "${stage}/bin/${name}" && -x "${stage}/bin/${name}" ]] \
                || die "${ref} has no executable ${IMAGE_TOOLS}/bin/${name}; nothing was put in ${dest}"
            names+=("${name}")
        done <"${stage}/tools.txt"
        rm -rf "${dest}/bin" "${dest}/tools.txt"
        mv "${stage}/bin" "${dest}/bin"
        mv "${stage}/tools.txt" "${dest}/tools.txt"
        printf '%d pinned tools from %s in %s: %s\n' "${#names[@]}" "${ref}" "${dest}/bin" "${names[*]}"
        ;;
    *)
        printf 'usage: bash verify/e2e-image.sh ref|build|run [<tier test>...]|tools <dir>\n' >&2
        exit 1
        ;;
esac
