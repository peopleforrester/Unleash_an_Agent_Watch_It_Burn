#!/usr/bin/env bash
# ABOUTME: Fleet driver. Stamps out N attendee clusters from the cluster/ module against the
# ABOUTME: shared lab VPC, each with its own state, concurrency-capped, parallel. (Packt-modeled.)
set -euo pipefail

# Defined first: the Docker Hub auth probe below logs at source-time, before dispatch, so log() must
# exist by then (a later definition aborted up-fleet with "log: command not found" under set -e).
log() { printf '%s\n' "$*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROVISION_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# The IDP bootstrap script lives in infra/ (the parent of the terraform provisioning dir), NOT under
# infra/terraform/. bootstrap_one runs this; an earlier ${PROVISION_DIR}/deploy-full-idp.sh reference
# pointed at infra/terraform/ and silently failed every fleet bootstrap (found 2026-06-27).
INFRA_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd "${INFRA_DIR}/.." && pwd)"
readonly SCRIPT_DIR PROVISION_DIR INFRA_DIR REPO_ROOT
# §4.2 provider dispatch: pick the cloud (aws|azure|gcp|local) and source its shim, which supplies
# the terraform network/cluster subpaths + the kubeconfig contract. Default aws (the only provider fully
# implemented this pass; azure/gcp/local are stubs — PRD 35 M2/M3/M8).
PROVIDER="${PROVIDER:-aws}"
[[ -r "${SCRIPT_DIR}/providers/${PROVIDER}.sh" ]] || { printf 'unknown PROVIDER=%s (expected aws|azure|gcp|local)\n' "${PROVIDER}" >&2; exit 2; }
# shellcheck source=/dev/null
. "${SCRIPT_DIR}/providers/${PROVIDER}.sh"
readonly PROVIDER
readonly IDP_SCRIPT="${INFRA_DIR}/deploy-full-idp.sh"
# The provisioning app (web UI + the harvester scripts the fleet runs during `ingest`) was extracted to
# a sibling repo (peopleforrester/provisioning-agenticburn). Locate the scripts via WIB_PROVISION_DIR;
# default is the sibling checkout next to this repo. Override if it lives elsewhere on this box.
readonly WIB_PROVISION_DIR="${WIB_PROVISION_DIR:-${REPO_ROOT}/../provisioning-agenticburn}"
# The apex wildcard router (agenticburn.com) was extracted to its own repo (peopleforrester/
# apex-agenticburn); routes.map lives there and Railway deploys it from that repo's MAIN.
readonly WIB_APEX_DIR="${WIB_APEX_DIR:-${REPO_ROOT}/../apex-agenticburn}"
readonly HARVEST_SCRIPT="${WIB_PROVISION_DIR}/scripts/harvest_cluster_access.sh"
readonly GEN_AWS_SCRIPT="${WIB_PROVISION_DIR}/scripts/generate_attendee_aws.py"
readonly PUSH_VTT_SCRIPT="${WIB_PROVISION_DIR}/scripts/push_vtt_aws_creds.sh"
readonly AWS_POOL_DIR="${SCRIPT_DIR}/aws-pool"   # gitignored: holds live access keys
readonly CLUSTER_DIR="${PROVISION_DIR}/${PROVIDER_CLUSTER_SUBDIR}"
readonly LAB_VPC_DIR="${PROVISION_DIR}/${PROVIDER_NETWORK_SUBDIR}"
readonly STATE_DIR="${SCRIPT_DIR}/states"
readonly LOG_DIR="${SCRIPT_DIR}/logs"
readonly NAME_PREFIX="watch-it-burn-attendee"
# Per-ACCOUNT cap (up-fleet runs all accounts concurrently, so total concurrent = #accounts x this).
# 15 x 5 accounts = 75 concurrent cluster builds. Most of each build is an idle ~10-15 min wait on the
# EKS control-plane create (near-zero local cost), so the binding local limit is RAM during the bootstrap
# spike: ~600MB per build tree on this 62GB box, ~45GB at 75-wide, leaves headroom. Raise via env for a
# bigger box; the irreducible floor is the EKS control-plane create (~10-15 min, AWS-side, per cluster).
# Per-account pool width. The run plan documents 8 per account across 5 accounts; this defaulted to 15,
# so following the documented command without setting it gave 75 concurrent builds instead of 40.
#
# The number that matters is the TOTAL across accounts, not the per-account one, and the cost is
# concentrated in the bootstrap phase (helm, kubectl, aws eks get-token per call) rather than the
# ~10-minute control-plane wait. Oversubscribing does not merely slow the run: it risks tripping the
# fixed timeouts inside bootstrap (helm --wait --timeout 10m, kubectl rollout status --timeout=180s)
# and turning host contention into spurious cluster failures that look like real ones.
MAX_PARALLEL="${MAX_PARALLEL:-8}"

# --- Multi-account config (env-overridable) -----------------------------------------------------
# Defaults keep the existing SINGLE-account attendee flow unchanged (TF_PROFILE empty -> the cluster
# module's default profile/region). Set the per-round account profiles when the 5-account fleet exists.
WIB_REGION="${WIB_REGION:-us-west-2}"
# Instructor clusters spread per round across separate accounts so no one account hits an EKS/VPC quota
# wall ("overload"): Round 1 -> account 1, Round 2 -> account 2, Round 3 -> account 3. Switchable here.
WIB_ACCOUNT_R1="${WIB_ACCOUNT_R1:-accen-dev}"
WIB_ACCOUNT_R2="${WIB_ACCOUNT_R2:-accen-dev}"
WIB_ACCOUNT_R3="${WIB_ACCOUNT_R3:-accen-dev}"
# Attendee fleet accounts for `up-fleet` (comma-separated AWS profiles). up-fleet provisions every
# account's slice CONCURRENTLY so the whole fleet comes up in one window. All FIVE accounts carry the
# attendee fleet (250-cluster plan = 5 x 50). The four student accounts have a per-account lab-vpc in
# states/<profile>.tfstate; accen-dev's lab VPC lives in the DEFAULT terraform.tfstate, and read_vpc_for
# falls back to it (see WIB_DEFAULT_ACCOUNT) so accen-dev joins the fleet without a duplicate state.
# Per-account ALB/NLB->100 + vCPU->800 quota increases submitted 2026-06-27 must be APPROVED before a full
# 50/account WITH-bootstrap run (each bootstrapped cluster = 1 ALB + 1 NLB; default cap 50).
WIB_ATTENDEE_ACCOUNTS="${WIB_ATTENDEE_ACCOUNTS:-accen-dev,aws1-student31,aws1-student32,aws1-student33,aws1-student34}"
# The account whose lab VPC is in the DEFAULT lab-vpc state (terraform.tfstate), not states/<acct>.tfstate.
# read_vpc_for + the up-fleet/down-fleet/health pre-checks treat it as having a VPC via that default state.
WIB_DEFAULT_ACCOUNT="${WIB_DEFAULT_ACCOUNT:-accen-dev}"
# Name-number offset so a fleet run can avoid colliding with existing clusters (state is keyed by name
# globally). Cluster n in account-index i is numbered (WIB_NAME_OFFSET + i*per_account + n). Existing
# clusters: accen-dev attendee-001; set the offset above any existing number for a clean test run.
WIB_NAME_OFFSET="${WIB_NAME_OFFSET:-0}"

# --- Instructor roster (§4.6): DATA, not a hardcoded array ---------------------------------------
# The roster lives in roster.tsv as "name|round|tier|instance_type|pids|bootstrap" rows, so changing
# WHAT the fleet provisions (which clusters, which model tier, node type, PID cap) is config, not a
# script edit. load_roster reads WIB_ROSTER_FILE; a built-in default keeps a bare checkout working.
# Round behaviour (R1 wide open, R2 some guards, R3 full) stays a RUNTIME toggle; the roster's pids
# column carries the one provision-time difference (R1 pids=-1 so the C4 fork bomb burns the node).
# All clusters run the identical FULL build; the model default is Nova (gitops), tier column overrides.
INSTRUCTORS=()
load_roster() {
    INSTRUCTORS=()
    if [[ -r "${WIB_ROSTER_FILE}" ]]; then
        local line
        while IFS= read -r line; do
            line="${line//[[:space:]]/}"
            [[ -z "${line}" || "${line}" == \#* ]] && continue
            INSTRUCTORS+=("${line}")
        done < "${WIB_ROSTER_FILE}"
    fi
    [[ "${#INSTRUCTORS[@]}" -gt 0 ]] || INSTRUCTORS=(
        "watch-it-burn-r1-1|1|||-1|full" "watch-it-burn-r1-2|1|||-1|full" "watch-it-burn-r1-3|1|||-1|full"
        "watch-it-burn-r2-1|2||||full"   "watch-it-burn-r2-2|2||||full"   "watch-it-burn-r2-3|2||||full"
        "watch-it-burn-r3-1|3||||full"   "watch-it-burn-r3-2|3||||full"   "watch-it-burn-r3-3|3||||full"
    )
}

# The AWS profile (account) up_one/down_one target. Per-account code paths overwrite it in a subshell.
# It now defaults to WIB_DEFAULT_ACCOUNT rather than "" because the cluster module's `profile` variable
# no longer has a default: relying on an implicit account is what let a forgotten -var silently apply
# into the shared co-tenant account. The resolved value is identical to the old module default, so
# behaviour is unchanged; the difference is that the account is now always stated rather than assumed.
TF_PROFILE="${WIB_DEFAULT_ACCOUNT}"

# When non-empty, up_one passes -var pod_pids_limit=<this>. Empty = the cluster module default (1024,
# the fork-bomb cap). Round 1 (burn) clusters set this to -1 (no per-pod cap) so the C4 fork bomb
# actually exhausts node PIDs and takes the cluster down: that is the Round-1 "watch it burn" moment
# the spec calls for. R2/R3 and attendee clusters keep the 1024 cap so the cap is the working control.
TF_PIDS_LIMIT=""

# When non-empty (burn|full), up_one chains deploy-full-idp.sh right after a successful apply, so a
# provision auto-installs the IDP (ArgoCD + the app-of-apps tracking staging) instead of a separate
# manual bootstrap. This is what makes a fleet provision self-complete; at 250 clusters you do not
# hand-bootstrap each one. Set WIB_NO_BOOTSTRAP=1 to provision bare clusters only. Per-branch clusters
# (a cluster that tracks its own branch, e.g. an experiment branch) are a manual case: bootstrap from
# that branch's checkout, since this default path points the app-of-apps at staging.
BOOTSTRAP_PROFILE=""

# Docker Hub Team auth for node-level containerd, sourced from ~/secrets (mrf-secrets), NEVER committed.
# up_one passes it to the cluster module as -var dockerhub_auth_b64 so every node authenticates docker.io
# pulls (no anonymous 429 at fleet scale) with GHCR as the fallback mirror. Empty => the module omits the
# registry config and a bare apply still works. Override the path with WIB_DOCKERHUB_ENV.
WIB_DOCKERHUB_AUTH_B64=""
_dh_env="${WIB_DOCKERHUB_ENV:-${HOME}/secrets/dockerhub/agenticburn.env}"
if [[ -r "${_dh_env}" ]]; then
    WIB_DOCKERHUB_AUTH_B64="$(
        set -a; . "${_dh_env}"; set +a
        [[ -n "${DOCKERHUB_USER:-}" && -n "${DOCKERHUB_PAT:-}" ]] \
            && printf '%s:%s' "${DOCKERHUB_USER}" "${DOCKERHUB_PAT}" | base64 -w0
    )"
fi
[[ -n "${WIB_DOCKERHUB_AUTH_B64}" ]] \
    && log "Docker Hub Team auth loaded for node bootstrap (containerd docker.io auth + GHCR fallback)" \
    || log "no Docker Hub auth (${_dh_env} missing/unreadable) — nodes will pull docker.io anonymously"

# --- §4.6 cluster-shape parameterization (PRD 35): shape / roster / concurrency as config, not edits ---
# Fleet-wide overrides. Empty = the cluster module default, so UNSET means no behavior change vs today.
# Per-cluster roster columns take precedence over these fleet-wide values.
WIB_INSTANCE_TYPES="${WIB_INSTANCE_TYPES:-}"     # comma list, e.g. "m5.2xlarge" or "m5.xlarge,m5.2xlarge"
WIB_NODE_SIZE="${WIB_NODE_SIZE:-}"               # node count -> min/max/desired
WIB_DISK="${WIB_DISK:-}"                          # root disk GiB -> node_disk_size
# Roster selection: the instructor roster is DATA (roster.tsv), not a hardcoded array. Override the file
# path, or subset by round / per-round count, all without editing this script.
WIB_ROSTER_FILE="${WIB_ROSTER_FILE:-${SCRIPT_DIR}/roster.tsv}"
# The web-terminal login. Deliberately short and speakable: it gets said out loud and typed by a room.
# See bootstrap_terminal_auth for why a shared credential is the right call for single-use clusters.
#
# SPLIT BY ROLE (Michael's ruling 2026-08-30, issue #109). The instructor/presenter clusters and the
# student clusters do NOT share a login: `sprouts` is the ADMIN credential for Michael and Whitney, and
# handing it to a room would also hand the room the presenter consoles. Students get `agentic`.
# Which credential a cluster gets is decided by is_instructor_name (roster cluster = instructor), see
# terminal_creds_for. Override either pair per run with the env vars.
WIB_TERMINAL_USER="${WIB_TERMINAL_USER:-sprouts}"          # instructor / admin clusters
WIB_TERMINAL_PASSWORD="${WIB_TERMINAL_PASSWORD:-sprouts}"
WIB_STUDENT_USER="${WIB_STUDENT_USER:-agentic}"            # attendee / student clusters
WIB_STUDENT_PASSWORD="${WIB_STUDENT_PASSWORD:-agentic}"

# The provisioning app the fleet registers clusters with. This is a fixed, known address, so it is a
# default rather than something an operator has to remember to export. It used to have no default, which
# meant a normal `instructors up` silently skipped registration and the clusters were invisible in
# provisioning until someone noticed and re-ran ingest by hand.
WIB_PROVISIONING_URL="${WIB_PROVISIONING_URL:-https://provisioning.agenticburn.com}"

# Whose cluster the bare roundN.agenticburn.com alias points at. That alias is shared (the run-of-show
# and the BurritoBot round selector both use it), so it has to resolve to one owner's cluster; binding
# it explicitly keeps it stable instead of following whichever roster entry happened to render first.
WIB_PRIMARY_OWNER="${WIB_PRIMARY_OWNER:-michael}"

# Attendee SLOT -> presenter owner, for the two clusters the presenters use as their own STUDENT box.
# These are real attendee clusters (full profile, student credentials, claimable through provisioning);
# they simply belong to a named person, so they are named for that person like the roster is. Slot
# numbers rather than full names so this stays readable and matches the %03d the pool generates.
WIB_PRESENTER_SLOTS="${WIB_PRESENTER_SLOTS:-001=michael,002=whitney}"

# Railway coordinates for that app, used to resolve its ADMIN_TOKEN automatically (see resolve_admin_token).
readonly WIB_PROVISIONING_RW_PROJECT="859f9db0-bbda-4d3c-8026-767d0b9047a9"
readonly WIB_PROVISIONING_RW_ENV="ddb7d7e6-9643-4b55-8dd6-3618a0b6cce4"
readonly WIB_PROVISIONING_RW_SERVICE="watch-it-burn-provisioning"

# Resolve the provisioning app's admin token WITHOUT the operator having to know it exists.
#
# Registration is not optional work: a cluster nobody can look up is not finished. But it was gated on
# two environment variables, so the default outcome of running the tool normally was that it silently
# did not happen, and the failure surfaced later as a presenter finding a blank password. A step that
# only runs when someone remembers to set two variables is not automated, it is documented.
#
# Order: an explicit env var wins (for a one-off or a different environment), then the token is read
# from the live Railway service, then from the local secret store. Cached for the run so a fleet
# provision makes one Railway call rather than one per cluster.
WIB_ADMIN_TOKEN_CACHE=""
resolve_admin_token() {
    [[ -n "${WIB_ADMIN_TOKEN:-}" ]] && { printf '%s' "${WIB_ADMIN_TOKEN}"; return 0; }
    [[ -n "${WIB_ADMIN_TOKEN_CACHE}" ]] && { printf '%s' "${WIB_ADMIN_TOKEN_CACHE}"; return 0; }
    local tok=""
    if command -v railway >/dev/null 2>&1; then
        tok="$(railway variables --json \
                -p "${WIB_PROVISIONING_RW_PROJECT}" \
                -e "${WIB_PROVISIONING_RW_ENV}" \
                -s "${WIB_PROVISIONING_RW_SERVICE}" 2>/dev/null \
              | jq -r '.ADMIN_TOKEN // empty' 2>/dev/null)"
    fi
    # Fallback for a machine with no Railway login: the same value kept in the private secret store.
    if [[ -z "${tok}" && -r "${HOME}/secrets/projects/watch-it-burn-provisioning.env" ]]; then
        tok="$(sed -n 's/^ADMIN_TOKEN=//p' "${HOME}/secrets/projects/watch-it-burn-provisioning.env" | tr -d '"'"'"'[:space:]' | head -1)"
    fi
    [[ -n "${tok}" ]] || return 1
    WIB_ADMIN_TOKEN_CACHE="${tok}"
    printf '%s' "${tok}"
}
WIB_ROUNDS="${WIB_ROUNDS:-}"                      # comma list of rounds to include, e.g. "2,3" (empty = all)
WIB_PER_ROUND="${WIB_PER_ROUND:-}"               # max clusters per round (empty = all)
# Rounds run CONCURRENTLY by default (each round its own subshell so per-round vars cannot clash; the
# single shared terraform init + isolated per-cluster -state make it safe, same as run_pool within a
# round). Set WIB_SERIAL=1 to force the old serial round loop.
WIB_SERIAL="${WIB_SERIAL:-}"
# Dry run: print the terraform apply each cluster WOULD run (and skip bootstrap) instead of provisioning.
# Lets the roster / subset / var-building / concurrency logic be validated offline with no cloud spend.
WIB_DRY_RUN="${WIB_DRY_RUN:-}"
# Per-cluster overrides, set from the roster row before each up_one (siblings of TF_PIDS_LIMIT). Empty =
# fall back to the fleet-wide WIB_* value, then the module default.
TF_INSTANCE_TYPES=""
TF_TIER=""

account_for_round() {
    case "$1" in
        1) printf '%s' "${WIB_ACCOUNT_R1}" ;;
        2) printf '%s' "${WIB_ACCOUNT_R2}" ;;
        3) printf '%s' "${WIB_ACCOUNT_R3}" ;;
        *) log "bad round: $1"; exit 1 ;;
    esac
}

# An instructor/roster cluster is watch-it-burn-r<round>-<n>, as distinct from the numbered attendee
# pool (watch-it-burn-attendee-NNN). Several verbs need to tell them apart, because the attendee path
# derives a pool slot from the trailing number and that is meaningless for the roster.
is_instructor_name() { [[ "$1" =~ ^watch-it-burn-r([123])-[0-9]+$ ]]; }

# --- Memorable attendee hostnames (#142) ---------------------------------------------------------
# An attendee used to be handed a raw load-balancer hostname
# (k8s-agent-console-afa5f8550a-702bee5329c72c51.elb.us-west-2.amazonaws.com). That cannot be read to a
# room, cannot be typed from memory, and cannot be recovered by someone who closed the tab. This gives
# every attendee cluster a themed two-word name instead: soot-sabrina.agenticburn.com.
#
# DETERMINISTIC AND COLLISION-FREE BY CONSTRUCTION, not by hashing. The name is derived from the slot
# number the cluster already carries (watch-it-burn-attendee-042 -> slot 42), indexed into the grid
# below. A hash would need global knowledge to resolve collisions, and `routes` and `ingest` compute the
# name independently: they MUST agree, or the router publishes one name and provisioning hands out
# another. Indexing by slot means both arrive at the same answer with no shared state.
#
# The words are the workshop's own: a Hex & Cauldron menu item, then a witch or wizard the room will
# recognise (Michael, 2026-09-02). soot-sabrina reads as part of the story rather than as infrastructure,
# and it is still an adjective-noun shape that survives being read aloud and typed from memory.
#
# 30 menu words x 24 names = 720 unique names, comfortably past the ~250-attendee ceiling. Changing or
# reordering either list RENAMES existing slots, so only ever append, and never between events. The
# 2026-09-02 swap from the Ubuntu-style adjective-animal grid was a deliberate rename of everything, done
# before the event, and it required regenerating routes and re-ingesting so the router and provisioning
# agreed on the new names.
#
# This is usability, NOT access control. The consoles are unauthenticated: anyone who has a URL can talk
# to that cluster's agent. A non-sequential name raises the cost of guessing and nothing more. If
# enumeration ever matters, the answer is a credential on the console, not a cleverer name.
# Menu words, from the Hex & Cauldron menu in gitops/ai-layer/resources.yaml. Hyphens are stripped
# because the hyphen is the separator between the two halves of the hostname.
readonly WIB_ADJECTIVES=(bane bogbacoa bonfire blackbog cluck croak crowsfoot cursedcorn dragon faejita
                         ghastor ghoul goblin graveyard hagwrinkle hexhen imp kelpie ogre pixie
                         scream slime soot sorcerizo stake tardigrade toadilla toefu werewolf witchhat)
# Witches and wizards the room will recognise, mostly television of the last thirty years.
readonly WIB_ANIMALS=(sabrina willow wanda agatha hermione luna morgana merlin elphaba glinda
                      melisandre yennefer eda luz zelda hilda ambrose bonnie piper phoebe
                      prue rowena mildred potter)
# Slots are walked in a SCATTERED order, not in grid order. Grid order held the first word fixed while
# the second cycled, so the first 24 clusters handed out were all bane-something and the whole point of
# having thirty menu words was lost on the people actually receiving names.
#
# The scatter is a multiplicative stride, which keeps every property that matters: it is pure arithmetic
# on the slot number, so `routes` and `ingest` still compute the same answer with no shared state, and
# because the stride is COPRIME with the grid size it is a bijection, so it is still collision-free by
# construction rather than by hoping. 187 = 11 x 17 shares no factor with 720 = 2^4 x 3^2 x 5, and it
# also lands coprime with 24, which is what makes the second word move as fast as the first. Measured
# over the first twelve slots: twelve distinct menu words and twelve distinct names.
#
# CHANGING EITHER WORD LIST CHANGES THE GRID SIZE, and a stride that is not coprime with the new size
# collapses the range and produces duplicate hostnames. test_fleet_contract.py asserts the coprimality
# and a collision-free sweep of 250 slots, so that failure is caught in CI rather than by two students
# being handed the same URL.
readonly WIB_NAME_STRIDE=187
friendly_attendee_name() {
    local n="${1#0}"; n="${n#0}"            # strip zero padding: 042 -> 42
    [[ "${n}" =~ ^[0-9]+$ ]] || { printf 'attendee-%s' "$1"; return 0; }
    local i=$(( n - 1 ))
    local total=$(( ${#WIB_ADJECTIVES[@]} * ${#WIB_ANIMALS[@]} ))
    local j=$(( (i * WIB_NAME_STRIDE) % total ))
    local a=$(( j / ${#WIB_ANIMALS[@]} ))
    local b=$(( j % ${#WIB_ANIMALS[@]} ))
    printf '%s-%s' "${WIB_ADJECTIVES[$a]}" "${WIB_ANIMALS[$b]}"
    return 0
}

# The public hostname a cluster should be reached on, without the scheme. Roster clusters use their
# owner-and-round name; attendee clusters use their memorable name. One function so `routes` (which
# publishes the name) and `ingest` (which tells provisioning what to hand the student) cannot disagree.
public_host_for() {
    local name="$1" owner="${2:-}"
    if is_instructor_name "${name}"; then
        local rr; rr="$(round_of_instructor_name "${name}")"
        [[ -n "${owner}" && -n "${rr}" ]] && { printf '%s-round%s.agenticburn.com' "${owner}" "${rr}"; return 0; }
        printf '%s.agenticburn.com' "${name#watch-it-burn-}"; return 0
    fi
    # PRESENTER student clusters, driven by the same owner idea as the roster rather than by two
    # hardcoded name cases. The roster already names clusters <owner>-round<n>; these are the same
    # presenter's STUDENT cluster, so they are <owner>-student, and the fleet reads consistently:
    #
    #   michael-round1 / michael-round2 / michael-round3 / michael-student
    #   whitney-round1 / whitney-round2 / whitney-round3 / whitney-student
    #
    # WIB_PRESENTER_SLOTS maps attendee SLOT -> owner, so adding a third presenter is a config change
    # rather than another case arm. Everything outside the map is a real attendee and gets a themed name.
    local slot="${name##*-}" _pair _sl _ow
    for _pair in ${WIB_PRESENTER_SLOTS//,/ }; do
        _sl="${_pair%%=*}"; _ow="${_pair#*=}"
        if [[ "${slot}" == "${_sl}" ]]; then
            printf '%s-student.agenticburn.com' "${_ow}"; return 0
        fi
    done
    printf '%s.agenticburn.com' "$(friendly_attendee_name "${name##*-}")"
    return 0
}

# The terminal login for a cluster, as "user:password", chosen by role (#109). Instructor/roster
# clusters get the admin credential (sprouts); the attendee pool gets the student one (agentic). Keeping
# this in ONE function means the bootstrap that creates the Secret and the bundle that tells the student
# what to type can never disagree, which is the failure mode that hands a room a password that does not
# work. ALWAYS exits 0.
terminal_creds_for() {
    if is_instructor_name "$1"; then
        printf '%s:%s\n' "${WIB_TERMINAL_USER}" "${WIB_TERMINAL_PASSWORD}"
    else
        printf '%s:%s\n' "${WIB_STUDENT_USER}" "${WIB_STUDENT_PASSWORD}"
    fi
    return 0
}

# A QUIET health probe: true only if every ArgoCD Application is Synced+Healthy and no pod is broken.
#
# Deliberately separate from health_one rather than reusing it. health_one is a reporting verb: it logs
# a line per cluster and calls record_fail, and every path ends in a bare `return`, so it always exits
# 0. Using it as a predicate would therefore be wrong twice over: it would treat a DEGRADED cluster as
# healthy and skip provisioning it, and it would write failures for clusters that are merely about to
# be built. A predicate has to be side-effect free and has to actually return a status.
is_cluster_healthy() {
    local name="$1" acct="${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}"
    local kcfg; kcfg="$(mktemp -t "${name}.probe.XXXX")"
    provider_write_kubeconfig "${name}" "${kcfg}" "${acct}" >/dev/null 2>&1 || { rm -f "${kcfg}"; return 1; }
    local apps total healthy broken
    apps="$(KUBECONFIG="${kcfg}" kubectl get applications.argoproj.io -n argocd -o json 2>/dev/null)"
    if [[ -z "${apps}" ]]; then rm -f "${kcfg}"; return 1; fi
    total="$(jq '.items | length' <<<"${apps}" 2>/dev/null || echo 0)"
    [[ "${total}" -gt 0 ]] || { rm -f "${kcfg}"; return 1; }
    healthy="$(jq '[.items[] | select(.status.sync.status=="Synced" and .status.health.status=="Healthy")] | length' <<<"${apps}" 2>/dev/null || echo 0)"
    broken="$(KUBECONFIG="${kcfg}" kubectl get pods -A \
        --field-selector=status.phase!=Running,status.phase!=Succeeded -o name 2>/dev/null | grep -c . || true)"
    rm -f "${kcfg}"
    [[ "${healthy}" == "${total}" && "${broken}" -eq 0 ]]
}

# Gate for the destructive verbs. `reap` and `aws-keys` were already dry-run by default; `down`,
# `down-fleet` and `down-acct` were not, so a mistyped count or a stale state file destroyed clusters
# with no preview and no confirmation. Destroying is the one action with no undo, so it is the one that
# should require saying so. Prints exactly what it WOULD destroy, then exits 0.
require_apply() {
    local verb="$1"; shift
    [[ -n "${WIB_APPLY:-}" ]] && return 0
    log "DRY-RUN: ${verb} would destroy ${#} cluster(s). Set WIB_APPLY=1 to actually destroy."
    local n; for n in "$@"; do log "    - ${n}"; done
    return 1
}

# The round a roster cluster belongs to, from its own name. Lets a verb resolve the right account
# without the caller having to thread the roster through.
# Returns the round, or nothing. ALWAYS exits 0: "this is not a roster cluster" is a normal answer,
# not a failure. Under `set -e` a helper that returns non-zero kills the caller at the assignment
# `rnd="$(round_of_instructor_name ...)"`, with no message, which is exactly how `ingest <attendee-name>`
# silently did nothing at all.
round_of_instructor_name() {
    if [[ "$1" =~ ^watch-it-burn-r([123])-[0-9]+$ ]]; then printf '%s' "${BASH_REMATCH[1]}"; fi
    return 0
}

usage() {
    cat >&2 <<EOF
Usage: ${0##*/} <up|down|status|instructors> [count|names...|<up|down> [round]]

  preflight <n>       BEFORE any run: assert every account resolves to its EXPECTED account id and has
                      vCPU/NLB/EKS/VPC/EIP headroom for <n> clusters each. Read-only; exits non-zero on
                      anything that would block. A quota rejection found mid-build costs the window.

  check-tls <host...> BEFORE doors: per hostname assert https 200, a validating chain whose SAN covers
                      it, at least 7 days of cert life, an http->https redirect, and that the websocket
                      upgrade the terminal needs is accepted. Pass --no-ws for hosts with no terminal.

  ATTENDEE clusters (numbered, pool-distributed, single account):
    up <count>        Provision watch-it-burn-attendee-001 .. -<count> (or pass explicit names).
    up <name...>      Provision the named clusters.
    up-fleet <n>      Provision <n> clusters in EACH \${WIB_ATTENDEE_ACCOUNTS} account, all concurrent
                      (disjoint name ranges). Honors WIB_NAME_OFFSET to skip existing cluster numbers.
    down-fleet <n>    Tear down an up-fleet run: SAME <n> + WIB_NAME_OFFSET, account-aware (each cluster
                      destroyed in its own account). Skips names with no state, so partial fleets are safe.
    down <count|all>  Destroy the first <count>, or all clusters with state.
    down <name...>    Destroy the named clusters.
    health <n>        Sweep IDP health of an up-fleet run (SAME <n> + WIB_NAME_OFFSET): per cluster,
                      assert every ArgoCD app Synced+Healthy and no broken pods. Non-zero if any degraded.
    converge instructors [round]
                      Same repair loop, pointed at the roster instead of the attendee pool. These are the
                      nine clusters the presenters drive from, so a console NLB that has not resolved
                      here ends the workshop rather than costing one attendee a cluster.
    converge <name...>  Repair an explicit set, attendee or roster, mixed.
    converge <n>      Re-check an up-fleet run (SAME <n> + WIB_NAME_OFFSET) and REPAIR what is actually
                      broken: hard-refresh unhealthy ArgoCD apps, and wait out LB assignment and DNS
                      resolution on separate budgets. Loops up to \${WIB_CONVERGE_ROUNDS} (default 3).
                      Run this after 'up-fleet'. Without it a run reports a success rate that is wrong:
                      on the sister Packt fleet 27 of 250 clusters were healthy but had an NLB whose
                      hostname had not propagated yet, so the run scored 89% and 27 clusters were fine.
    harvest <n>      Harvest student-facing access info (console NLB / grafana / ...) of an up-fleet run
                      (SAME <n> + WIB_NAME_OFFSET) to a pool CSV on stdout (feed merge_pool.py).
    aws-keys <n>     Generate per-attendee scoped IAM user+key per cluster in its OWN account (SAME <n>
                      + offset). DRY-RUN unless WIB_APPLY=1; WIB_ACCESS_ENTRIES=1 maps users into clusters.
    reap-lbs          Find load balancers, target groups and volumes tagged for a cluster that no longer
                      exists, in every account, and delete them. The standing net for #157: a teardown
                      that could not reach the cluster API strands them and nothing else looks for them.
                      DRY-RUN unless WIB_APPLY=1.
    reap --keep <f>   Cost reaper: destroy attendee clusters NOT in the keep-list <f> (claimed clusters),
                      across all accounts. DRY-RUN unless WIB_APPLY=1.
    status            List clusters that have state and their EKS status.

  INSTRUCTOR clusters (9 fixed: 3 per round, NOT in the attendee pool):
    instructors up [round|owner]
                              Provision the roster. The argument is a ROUND (1|2|3), an OWNER
                              (michael|whitney, from roster.tsv's owner column), or both|all for
                              everything. `instructors up whitney` builds exactly her three clusters.
                              Regenerates routes AND
                              registers the roster with the provisioning app (set WIB_PROVISIONING_URL +
                              WIB_ADMIN_TOKEN; WIB_NO_INGEST=1 opts out).
    instructors down [round]  Destroy the roster (optionally one round).
    ingest-instructors [round]  Register the roster with the provisioning app on its own (the same step
                              'instructors up' runs). Use after a console NLB was not ready in time.
    Round->account split (avoids per-account overload): R1=\${WIB_ACCOUNT_R1}, R2=\${WIB_ACCOUNT_R2},
    R3=\${WIB_ACCOUNT_R3}. Override via those env vars. Each account needs its own lab-vpc applied to
    states/<profile>.tfstate first (the command prints the exact apply line if missing).

Provisioning AUTO-BOOTSTRAPS the IDP after each cluster comes up (deploy-full-idp.sh): attendees +
R2/R3 instructors with the 'full' profile, R1 instructors with 'burn'. The provision pool runs the
provision and the bootstrap together, so a fleet 'up' self-completes. Set WIB_NO_BOOTSTRAP=1 to
provision bare clusters only (then bootstrap manually; instructor hints print after a bare 'up').
Per-branch clusters (a cluster tracking its own branch) are a manual case: bootstrap from that branch.

Attendee path reads the shared VPC from ../aws/network (must be applied first). Each cluster gets its own
state file under states/, so one cluster's failure or teardown never touches another. MAX_PARALLEL
(default 8) caps concurrency. Attendee profile/region come from the cluster module defaults.

Requires: terraform, jq, aws.
EOF
    exit 2
}

require_tools() {
    local t missing=0
    for t in terraform jq aws; do
        command -v "${t}" >/dev/null 2>&1 || { log "missing tool: ${t}"; missing=1; }
    done
    [[ "${missing}" -eq 0 ]] || exit 1
}

# Pull the shared VPC id and subnet id list (JSON) from the lab-vpc state.
read_vpc() {
    VPC_ID="$(terraform -chdir="${LAB_VPC_DIR}" output -raw vpc_id 2>/dev/null || true)"
    SUBNETS_JSON="$(terraform -chdir="${LAB_VPC_DIR}" output -json private_subnet_ids 2>/dev/null || true)"
    if [[ -z "${VPC_ID}" || -z "${SUBNETS_JSON}" ]]; then
        log "could not read lab VPC outputs. Apply ${LAB_VPC_DIR##*/} first (terraform init && apply)."
        exit 1
    fi
}

# Expand args into a list of cluster names. A single integer means a generated range.
expand_names() {
    if [[ $# -eq 1 && "$1" =~ ^[0-9]+$ ]]; then
        local i
        for i in $(seq 1 "$1"); do printf '%s-%03d\n' "${NAME_PREFIX}" "${i}"; done
    else
        printf '%s\n' "$@"
    fi
}

# Safety: only ever act on our own cluster names. The account is shared with Packt; refuse any
# name that is not a watch-it-burn cluster so the fleet can never touch a co-tenant resource.
assert_ours() {
    local name="$1"
    [[ "${name}" == watch-it-burn-* ]] || { log "REFUSING non-watch-it-burn name: ${name}"; exit 1; }
}

# Record a per-cluster failure so the parent command can report it and exit non-zero. A backgrounded
# job's exit code is otherwise lost in the pool, which would silently half-provision a 60-cluster fleet.
record_fail() { echo "${1}" >>"${LOG_DIR}/.failures"; }

# Install the IDP on a freshly-provisioned cluster: pull an isolated kubeconfig (never the shared
# ~/.kube/config) and run deploy-full-idp.sh with the round's profile. Runs inside up_one, so the
# concurrency pool provisions AND bootstraps each cluster in parallel.
# Flip a round-2/3 cluster's infra guardrails to enforcing after bootstrap. Kyverno ships in Audit
# (kyverno-policies.yaml), so wait for the ClusterPolicy to sync then run the Audit->Enforce toggle.
# NetworkPolicy egress, Falco, and the PID cap come up enforcing from the full app-of-apps and need no
# flip; R1 (burn profile) has no guardrails and never calls this. Mirrors the tail of
# infra/setup-instructor-cluster.sh so a fleet 'up' self-arms (found 2026-07-10: provisioning deployed the
# IDP but never armed the round, leaving Kyverno in Audit so R2 admission never blocked).
arm_infra_guardrails() {
    local name="$1" kcfg="$2" acct="$3" ctx i
    ctx="$(KUBECONFIG="${kcfg}" kubectl config current-context 2>/dev/null)"
    log "  ${name}: waiting for Kyverno policy sync, then flipping Audit->Enforce"
    for i in $(seq 1 40); do
        KUBECONFIG="${kcfg}" AWS_PROFILE="${acct}" kubectl --context "${ctx}" \
            get clusterpolicy require-resource-limits >/dev/null 2>&1 && break
        [[ "${i}" -eq 40 ]] && { log "  ${name}: TIMED OUT waiting for Kyverno sync; guardrails NOT armed"; return 1; }
        sleep 15
    done
    # Wait for the kyverno-policies ArgoCD app to settle (Synced) so the initial-sync churn is over
    # before we flip; RespectIgnoreDifferences then keeps the flip from being reverted by later syncs.
    for i in $(seq 1 20); do
        [[ "$(KUBECONFIG="${kcfg}" AWS_PROFILE="${acct}" kubectl --context "${ctx}" \
            get application kyverno-policies -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null)" == "Synced" ]] && break
        sleep 10
    done

    # Wait for Kyverno's admission webhook to have ENDPOINTS. Patching a ClusterPolicy goes THROUGH that
    # webhook, so while the kyverno pods are still starting every patch fails with
    #   Internal error occurred: failed calling webhook "mutate-policy.kyverno.svc": no endpoints
    #   available for service "kyverno-svc"
    # The policy existing and the app reading Synced are both true well before this is, which is why
    # neither of the waits above caught it. Observed on watch-it-burn-r3-2, 2026-08-26.
    for i in $(seq 1 30); do
        [[ -n "$(KUBECONFIG="${kcfg}" AWS_PROFILE="${acct}" kubectl --context "${ctx}" \
            -n kyverno get endpoints kyverno-svc -o jsonpath='{.subsets[0].addresses[0].ip}' 2>/dev/null)" ]] && break
        [[ "${i}" -eq 30 ]] && log "  ${name}: kyverno webhook still has no endpoints; flipping anyway"
        sleep 10
    done

    # Flip, then VERIFY, and re-flip if it drifted back.
    #
    # The old version reported ENFORCING purely on the toggle's exit code. That is not the same claim:
    # on watch-it-burn-r2-1 (2026-08-26) the toggle patched both policies and read them back as Enforce,
    # the run logged ENFORCING, and require-resource-limits was Audit again minutes later. ArgoCD had
    # reverted it despite ignoreDifferences and RespectIgnoreDifferences being set for that exact path.
    # A half-armed Round 2 that reports success is worse than an honest failure, because the demo then
    # fails in front of the room with nothing having warned anyone.
    #
    # So: confirm the live value AFTER a settling pause, and retry the flip if selfHeal won the race.
    local attempt rl ri
    for attempt in 1 2 3; do
        CONTEXT="${ctx}" KUBECONFIG="${kcfg}" AWS_PROFILE="${acct}" \
            bash "${REPO_ROOT}/challenges/01-cncf-wall/toggle-kyverno-enforce.sh" \
            >>"${LOG_DIR}/${name}.arm.log" 2>&1 || true
        sleep 20   # let any selfHeal reconciliation land before believing the result
        rl="$(KUBECONFIG="${kcfg}" AWS_PROFILE="${acct}" kubectl --context "${ctx}" \
            get clusterpolicy require-resource-limits -o jsonpath='{.spec.rules[0].validate.failureAction}' 2>/dev/null)"
        ri="$(KUBECONFIG="${kcfg}" AWS_PROFILE="${acct}" kubectl --context "${ctx}" \
            get clusterpolicy restrict-image-registries -o jsonpath='{.spec.rules[0].validate.failureAction}' 2>/dev/null)"
        if [[ "${rl}" == "Enforce" && "${ri}" == "Enforce" ]]; then
            log "  ${name}: infra guardrails ENFORCING (Kyverno, verified)"
            return 0
        fi
        log "  ${name}: after attempt ${attempt}, require-resource-limits=${rl:-?} restrict-image-registries=${ri:-?}; retrying"
    done
    log "  ${name}: FAILED to arm Kyverno; live state require-resource-limits=${rl:-?} restrict-image-registries=${ri:-?}"
    log "        (see ${LOG_DIR}/${name}.arm.log). This round will NOT block admission."
    record_fail "${name}:kyverno-not-armed rl=${rl:-?} ri=${ri:-?}"
    return 1
}

bootstrap_one() {
    local name="$1" profile="$2" round="${3:-}"
    local acct_profile="${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}"
    local kcfg; kcfg="$(mktemp -t "${name}.kcfg.XXXX")"
    provider_write_kubeconfig "${name}" "${kcfg}" "${acct_profile}"
    # Datadog keys, read from the central pool on the PROVISIONING box (default account); deploy-full-idp
    # injects them as a plain K8s Secret (the cluster's own account never touches Secrets Manager).
    # Attendee clusters (watch-it-burn-attendee-NNN) get their OWN org, indexed by slot N to match
    # merge_pool.py's row-position join over attendee-only orgs, so the in-cluster org is the SAME one the
    # provisioning page shows the student. Non-attendee (instructor) clusters use the shared workshop org.
    local api app slot
    slot="$(printf '%s' "${name}" | sed -n "s/^${NAME_PREFIX}-0*\([0-9][0-9]*\)$/\1/p")"
    if [[ -n "${slot}" ]]; then
        local pool1 pool2
        pool1="$(AWS_PROFILE="${WIB_DEFAULT_ACCOUNT}" aws secretsmanager get-secret-value --secret-id watch-it-burn/datadog-pool   --region "${WIB_REGION}" --query SecretString --output text 2>/dev/null || echo '[]')"
        pool2="$(AWS_PROFILE="${WIB_DEFAULT_ACCOUNT}" aws secretsmanager get-secret-value --secret-id watch-it-burn/datadog-pool-2 --region "${WIB_REGION}" --query SecretString --output text 2>/dev/null || echo '[]')"
        read -r api app < <(jq -rn --argjson a "${pool1}" --argjson b "${pool2}" --argjson i "$(( slot - 1 ))" \
            '([$a[], $b[]] | map(select((.role // "") | startswith("admin") | not)))[$i] | "\(.["api-key"] // "") \(.["app-key"] // "")"' 2>/dev/null)
        if [[ -z "${api}" || -z "${app}" ]]; then
            log "  BOOTSTRAP FAILED: ${name} could not resolve its per-student Datadog org (slot ${slot}); refusing to fall back to the shared org"
            record_fail "${name}"; rm -f "${kcfg}"; return
        fi
        log "  ${name}: per-student Datadog org (attendee slot ${slot})"
    else
        local _dd
        _dd="$(AWS_PROFILE="${WIB_DEFAULT_ACCOUNT}" aws secretsmanager get-secret-value \
            --secret-id watch-it-burn/datadog --region "${WIB_REGION}" --query SecretString --output text 2>/dev/null || true)"
        api="$(jq -r '."api-key" // empty' <<<"${_dd}" 2>/dev/null)"
        app="$(jq -r '."app-key" // empty' <<<"${_dd}" 2>/dev/null)"
    fi
    if KUBECONFIG="${kcfg}" AWS_PROFILE="${acct_profile}" \
        WITB_DD_API_KEY="${api}" WITB_DD_APP_KEY="${app}" \
        bash "${IDP_SCRIPT}" "${profile}" \
        >"${LOG_DIR}/${name}.bootstrap.log" 2>&1; then
        log "  bootstrapped: ${name} (${profile})"
        bootstrap_student_aws "${name}" "${acct_profile}" "${kcfg}"
        bootstrap_terminal_auth "${name}" "${acct_profile}" "${kcfg}"
        # Arm on the PROFILE, not the round. This was `round == 2 || round == 3`, and an attendee
        # cluster has no round: cmd_up leaves that spec field empty. So every attendee cluster received
        # all ten Kyverno policies from the full profile and none of them were ever flipped out of
        # Audit. Measured 2026-09-03 across the whole attendee fleet, 7 of 7 sat at
        # restrict-image-registries=Audit while r2/r3 were correctly Enforce, which means Challenge 2's
        # villain image DEPLOYS on a student's own cluster: the control they are told stops it does
        # nothing, on the one cluster where they run the challenge themselves.
        #
        # ONLY "full" arms. That is now a three-way distinction, not two:
        #   full     (instructor R2/R3) -> arm: restrict-image-registries flipped to Enforce here.
        #   attendee (the student pool) -> DO NOT arm: it ships kyverno-policies in Audit on purpose, so
        #            C2's villain image deploys and the STUDENT flips it to Enforce (#160). Its C1 and C3
        #            controls are omitted from the profile entirely (app-of-apps-attendee.yaml), so there
        #            is nothing to arm for those either.
        #   burn     (instructor R1)    -> ships no policies at all; the unguarded spectacle.
        # Gating on the profile name keeps attendee and burn both unarmed without a round check.
        [[ "${profile}" == "full" ]] && arm_infra_guardrails "${name}" "${kcfg}" "${acct_profile}"
    else
        log "  BOOTSTRAP FAILED: ${name} (see ${LOG_DIR}/${name}.bootstrap.log)"; record_fail "${name}"
    fi
    rm -f "${kcfg}"
}

# Give this cluster's terminal its own password, so the shell is not open to anyone who can reach the
# load balancer. The credential is enforced by ttyd itself (images/web-terminal/entrypoint.sh), because
# that is the only place upstream reachability cannot route around: the NLB answers on its bare IP, so
# neither a router in front of it nor an unguessable hostname is a control. Measured on the sister Packt
# fleet 2026-07-25, after an attendee reached the instructor's cluster on 2026-07-23.
#
# Idempotent: an existing secret is left alone, so re-running a bootstrap never changes a password an
# attendee has already been handed. The password is persisted next to the AWS pool CSV so `ingest` can
# publish it with the rest of the cluster's access info.
bootstrap_terminal_auth() {
    local name="$1" acct_profile="$2" kcfg="$3"
    local pwfile="${AWS_POOL_DIR}/${name}.terminal" pw i

    for i in $(seq 1 40); do  # the agent namespace is created asynchronously by ArgoCD
        KUBECONFIG="${kcfg}" AWS_PROFILE="${acct_profile}" kubectl get ns agent >/dev/null 2>&1 && break; sleep 6
    done

    # Already provisioned? Keep whatever the cluster is currently enforcing, and make sure the local
    # copy matches it, so a lost pwfile does not silently desync from the live password.
    local live
    live="$(KUBECONFIG="${kcfg}" AWS_PROFILE="${acct_profile}" kubectl get secret terminal-auth -n agent \
        -o jsonpath='{.data.TTYD_CREDENTIAL}' 2>/dev/null | base64 -d 2>/dev/null || true)"
    if [[ -n "${live}" ]]; then
        mkdir -p "${AWS_POOL_DIR}"; printf '%s\n' "${live#*:}" >"${pwfile}"; chmod 600 "${pwfile}"
        log "  terminal-auth already set: ${name}"
        return
    fi

    # A SHARED, SPEAKABLE credential, not a per-cluster random one. The presenters have to be able to
    # say it out loud and have a room of people type it, and a 24-hex-char string cannot survive that.
    # Set WIB_TERMINAL_USER / WIB_TERMINAL_PASSWORD to change it for a run.
    #
    # This is a deliberate trade, decided 2026-08-26. These are single-use clusters that live for the
    # length of one workshop and are destroyed after; the URLs are not published; and the shell behind
    # the credential is an unprivileged user with a scoped ClusterRole, not cluster-admin. The purpose
    # of the credential is to stop a stranger wandering into somebody else's terminal, which it does.
    # It is not protecting anything that outlives the session.
    # Role-split (#109): instructor clusters get sprouts, the attendee pool gets agentic.
    local cred; cred="$(terminal_creds_for "${name}")"
    pw="${cred#*:}"
    if KUBECONFIG="${kcfg}" AWS_PROFILE="${acct_profile}" kubectl create secret generic terminal-auth \
        -n agent --from-literal="TTYD_CREDENTIAL=${cred}" >>"${LOG_DIR}/${name}.bootstrap.log" 2>&1; then
        mkdir -p "${AWS_POOL_DIR}"; printf '%s\n' "${pw}" >"${pwfile}"; chmod 600 "${pwfile}"
        # ttyd reads the credential once at startup, so an already-running terminal keeps serving
        # unauthenticated until it restarts. Roll it now rather than leaving the gap open.
        KUBECONFIG="${kcfg}" AWS_PROFILE="${acct_profile}" kubectl rollout restart deploy/web-terminal \
            -n agent >>"${LOG_DIR}/${name}.bootstrap.log" 2>&1 || true
        log "  terminal-auth created: ${name}"
    else
        log "  WARN: terminal-auth NOT created for ${name}; its terminal is UNAUTHENTICATED"
        record_fail "${name}:terminal-auth"
    fi
}

# Mint this cluster's scoped IAM key and inject it as the `student-aws-creds` secret so the VTT's aws CLI
# is pre-configured at boot, with NO per-cluster manual step. generate_attendee_aws is idempotent: if the
# user already has a key it skips (the secret was created on the first boot), so re-runs are safe.
bootstrap_student_aws() {
    local name="$1" acct_profile="$2" kcfg="$3"
    command -v uv >/dev/null 2>&1 || { log "  WARN: uv missing; cannot mint student AWS creds for ${name}"; return; }
    local awscsv; awscsv="$(mktemp -t "${name}.aws.XXXX")"
    if uv run --with boto3 python "${GEN_AWS_SCRIPT}" \
        --clusters "${name}" --apply --access-entries \
        --profile "${acct_profile}" --region "${WIB_REGION}" \
        --out "${awscsv}" >>"${LOG_DIR}/${name}.bootstrap.log" 2>&1; then
        local ak sk
        ak="$(tail -n +2 "${awscsv}" 2>/dev/null | head -1 | cut -d, -f3)"
        sk="$(tail -n +2 "${awscsv}" 2>/dev/null | head -1 | cut -d, -f4)"
        if [[ -n "${ak}" && -n "${sk}" ]]; then
            # Persist this cluster's creds so `fleet.sh ingest` can push the full pool row later (the mint
            # only returns the secret once). Re-runs skip minting, so the first-boot file survives.
            mkdir -p "${AWS_POOL_DIR}"; cp "${awscsv}" "${AWS_POOL_DIR}/${name}.csv"
            local ctx i; ctx="$(KUBECONFIG="${kcfg}" kubectl config current-context 2>/dev/null)"
            for i in $(seq 1 40); do  # wait for the agent namespace (ArgoCD creates it async)
                KUBECONFIG="${kcfg}" AWS_PROFILE="${acct_profile}" kubectl get ns agent >/dev/null 2>&1 && break; sleep 6
            done
            if KUBECONFIG="${kcfg}" AWS_PROFILE="${acct_profile}" bash "${PUSH_VTT_SCRIPT}" \
                --context "${ctx}" --access-key "${ak}" --secret-key "${sk}" --region "${WIB_REGION}" \
                >>"${LOG_DIR}/${name}.bootstrap.log" 2>&1; then
                log "  student-aws-creds injected: ${name}"
            else
                log "  WARN: student-aws-creds inject failed: ${name}"
            fi
        else
            # Mint was skipped (the IAM user already has a key from a prior provision; AWS only returns
            # the secret once). Do NOT leave student-aws-creds stale: a rebuilt cluster gets a fresh,
            # empty secret, so the VTT aws CLI fails with SignatureDoesNotMatch. Fall back to the
            # persisted pool CSV (the first-boot secret) and push THAT so the VTT is configured.
            local pf="${AWS_POOL_DIR}/${name}.csv" pak psk
            if [[ -f "${pf}" ]]; then
                pak="$(tail -n +2 "${pf}" | head -1 | cut -d, -f3 | tr -d '[:space:]')"
                psk="$(tail -n +2 "${pf}" | head -1 | cut -d, -f4 | tr -d '[:space:]')"
                local ctx i; ctx="$(KUBECONFIG="${kcfg}" kubectl config current-context 2>/dev/null)"
                for i in $(seq 1 40); do
                    KUBECONFIG="${kcfg}" AWS_PROFILE="${acct_profile}" kubectl get ns agent >/dev/null 2>&1 && break; sleep 6
                done
                if [[ -n "${pak}" && -n "${psk}" ]] && KUBECONFIG="${kcfg}" AWS_PROFILE="${acct_profile}" \
                    bash "${PUSH_VTT_SCRIPT}" --context "${ctx}" --access-key "${pak}" --secret-key "${psk}" \
                    --region "${WIB_REGION}" >>"${LOG_DIR}/${name}.bootstrap.log" 2>&1; then
                    log "  ${name}: AWS key pre-existed; re-pushed student-aws-creds from the pool CSV"
                else
                    log "  WARN: ${name}: AWS key pre-existed and pool CSV re-push failed; VTT aws CLI may be unconfigured"
                fi
            else
                log "  WARN: ${name}: AWS key pre-existed but no pool CSV; cannot configure the VTT aws CLI (rotate the key)"
            fi
        fi
    else
        log "  WARN: AWS key mint failed for ${name}; the VTT aws CLI will be unconfigured"
    fi
    rm -f "${awscsv}"
}

# One provisioning path for attendee and instructor clusters (#162). Both build PROVISION_SPEC and call
# _provision_spec_fleet; the only thing that ever differed between them is the per-cluster spec, so that
# is the input and everything downstream is shared.
#
# This replaced three separate copies of the same tail (init, provision, routes, register, report) in
# cmd_up, cmd_up_fleet and cmd_instructors. Those copies had drifted, and one drift was live: cmd_up_fleet
# regenerated routes but never registered, so the 250-cluster path left the whole room unclaimable, a
# sibling of #161 that the single-cluster fix never reached.
#
# Spec format, pipe-delimited, mirroring roster.tsv so an instructor row maps across almost verbatim:
#   account | bootstrap_profile | bootstrap_round | tier | instance_types | pod_pids_limit
declare -gA PROVISION_SPEC

# One cluster's provision, run inside a per-account run_pool worker where TF_PROFILE and the VPC are
# already set. Applies only the per-cluster fields from the spec, then the shared up_one.
_provision_worker() {
    local name="$1" _acct bp bround tier itype pids
    IFS='|' read -r _acct bp bround tier itype pids <<<"${PROVISION_SPEC[$name]}"
    BOOTSTRAP_PROFILE="${bp}"; BOOTSTRAP_ROUND="${bround}"
    TF_TIER="${tier}"; TF_INSTANCE_TYPES="${itype}"; TF_PIDS_LIMIT="${pids}"
    up_one "${name}"
}

# Provision every cluster in PROVISION_SPEC, grouped by account for the VPC read and profile, groups
# concurrent, then the tail every caller needs. reg_label + reg_fn + reg_args go to the registration
# helper unchanged.
_provision_spec_fleet() {
    local reg_label="$1" reg_fn="$2"; shift 2
    require_tools
    mkdir -p "${STATE_DIR}" "${LOG_DIR}"; rm -f "${LOG_DIR}/.failures"
    terraform -chdir="${CLUSTER_DIR}" init -input=false >/dev/null

    # Distinct accounts in first-seen order, then a name group per account.
    local order=() name a acct group
    for name in "${!PROVISION_SPEC[@]}"; do
        a="${PROVISION_SPEC[$name]%%|*}"
        [[ " ${order[*]} " == *" ${a} "* ]] || order+=("${a}")
    done
    for acct in "${order[@]}"; do
        group=()
        for name in "${!PROVISION_SPEC[@]}"; do
            [[ "${PROVISION_SPEC[$name]%%|*}" == "${acct}" ]] && group+=("${name}")
        done
        mapfile -t group < <(printf '%s\n' "${group[@]}" | sort)
        # Preserve cmd_up_fleet's friendly skip: a missing per-account lab VPC is a recorded skip, not a
        # subshell that exits silently mid-run. The default account uses the default state, so it is exempt.
        if [[ -z "${WIB_DRY_RUN}" && "${acct}" != "${WIB_DEFAULT_ACCOUNT}" \
              && ! -f "${LAB_VPC_DIR}/states/${acct}.tfstate" ]]; then
            log "  account '${acct}': NO lab VPC (apply states/${acct}.tfstate first); skipping its slice"
            record_fail "account:${acct}-no-vpc"; continue
        fi
        log "provisioning ${#group[@]} cluster(s) -> account '${acct}'"
        # Per-account subshell so VPC_ID/TF_PROFILE stay local; accounts run concurrently as up-fleet did.
        (
            if [[ -n "${WIB_DRY_RUN}" ]]; then VPC_ID="dry-vpc"; SUBNETS_JSON='[]'; else read_vpc_for "${acct}"; fi
            TF_PROFILE="${acct}"
            run_pool _provision_worker "${group[@]}"
        ) &
        [[ -n "${WIB_SERIAL}" ]] && wait
    done
    wait
    report_failures
    if [[ -z "${WIB_DRY_RUN}" && -z "${WIB_NO_BOOTSTRAP:-}" ]]; then
        cmd_routes || log "routes: run 'fleet.sh routes' manually once the console LBs are up"
    fi
    register_with_provisioning "${reg_label}" "${reg_fn}" "$@"
}

up_one() {
    local name="$1"; assert_ours "${name}"
    # Skip a cluster that already exists AND already passes health. Without this, re-running `up` to
    # grow a fleet or to retry a partial run re-entered the full bootstrap chain for every healthy
    # cluster: helm-install ArgoCD, re-register the repo, re-apply the app-of-apps, re-mint credentials.
    # Bootstrap is the expensive phase and the one with fixed internal timeouts, so doing it fleet-wide
    # and unnecessarily is how host contention turns into spurious failures. This is what makes `up`
    # safe to re-run, so growing 5 -> 50 -> 250 is the same verb rather than three different ones.
    # WIB_FORCE_UP=1 re-applies regardless, for when the intent really is to re-provision.
    if [[ -z "${WIB_DRY_RUN}" && -z "${WIB_FORCE_UP:-}" && -f "${STATE_DIR}/${name}.tfstate" ]]; then
        if is_cluster_healthy "${name}"; then
            log "  ${name}: already healthy, skipping"
            return 0
        fi
    fi
    local prof=(); [[ -n "${TF_PROFILE}" ]] && prof=(-var "profile=${TF_PROFILE}" -var "region=${WIB_REGION}")
    local pids=(); [[ -n "${TF_PIDS_LIMIT}" ]] && pids=(-var "pod_pids_limit=${TF_PIDS_LIMIT}")
    local dh=(); [[ -n "${WIB_DOCKERHUB_AUTH_B64}" ]] && dh=(-var "dockerhub_auth_b64=${WIB_DOCKERHUB_AUTH_B64}")
    # §4.6 shape passthrough. Per-cluster TF_INSTANCE_TYPES (roster) wins over fleet-wide WIB_INSTANCE_TYPES.
    local it=(); local _itypes="${TF_INSTANCE_TYPES:-${WIB_INSTANCE_TYPES}}"
    if [[ -n "${_itypes}" ]]; then
        local _j; _j="$(printf '"%s",' ${_itypes//,/ })"; it=(-var "instance_types=[${_j%,}]")
    fi
    local ns=(); [[ -n "${WIB_NODE_SIZE}" ]] && ns=(-var "node_min_size=${WIB_NODE_SIZE}" -var "node_max_size=${WIB_NODE_SIZE}" -var "node_desired_size=${WIB_NODE_SIZE}")
    local dk=(); [[ -n "${WIB_DISK}" ]] && dk=(-var "node_disk_size=${WIB_DISK}")
    if [[ -n "${WIB_DRY_RUN}" ]]; then
        log "  DRY-RUN ${name}: apply -state=${name}.tfstate ${prof[*]} ${pids[*]} ${it[*]} ${ns[*]} ${dk[*]}${WIB_DOCKERHUB_AUTH_B64:+ -var dockerhub_auth_b64=<redacted>} [tier=${TF_TIER:-<gitops default>}]"
        return 0
    fi
    if terraform -chdir="${CLUSTER_DIR}" apply -auto-approve -no-color \
        -state="${STATE_DIR}/${name}.tfstate" \
        -var "name=${name}" -var "vpc_id=${VPC_ID}" \
        -var "private_subnet_ids=${SUBNETS_JSON}" "${prof[@]}" "${pids[@]}" "${it[@]}" "${ns[@]}" "${dk[@]}" "${dh[@]}" \
        >"${LOG_DIR}/${name}.apply.log" 2>&1; then
        log "  ok: ${name}"
        # Record which account this cluster was actually built in, so teardown never has to guess.
        record_membership "${name}" "${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}"
        # Auto-bootstrap the IDP unless this provision is bare-only.
        [[ -n "${BOOTSTRAP_PROFILE}" ]] && bootstrap_one "${name}" "${BOOTSTRAP_PROFILE}" "${BOOTSTRAP_ROUND:-}"
    else
        log "  FAILED: ${name} (see ${LOG_DIR}/${name}.apply.log)"; record_fail "${name}"
    fi
}

# Delete LB-backed Services + Ingresses BEFORE terraform destroy so the AWS LB Controller removes the
# NLBs/ALBs it created (terraform doesn't manage them). Skipping this orphans ~2 LBs per cluster, whose
# ENIs then block VPC/subnet deletion and cost money (observed: 100 orphaned LBs/account after a fleet
# teardown). Best-effort: if the cluster is already gone/unreachable, just proceed to destroy. `--wait`
# on a LoadBalancer Service blocks on the controller's finalizer, i.e. until the AWS LB is actually gone.
drain_cluster_lbs() {
    local name="$1" acct="${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}"
    local kc; kc="$(mktemp -t "${name}.drain.XXXX")"
    if provider_write_kubeconfig "${name}" "${kc}" "${acct}" \
       && KUBECONFIG="${kc}" kubectl get ns >/dev/null 2>&1; then
        local lbsvcs
        lbsvcs="$(KUBECONFIG="${kc}" kubectl get svc -A -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' 2>/dev/null)"
        if [[ -n "${lbsvcs}" ]]; then
            log "  ${name}: draining $(printf '%s\n' "${lbsvcs}" | grep -c /) LB service(s) + ingresses before destroy"
            while IFS=/ read -r ns svc; do
                [[ -n "${svc}" ]] || continue
                KUBECONFIG="${kc}" kubectl delete svc -n "${ns}" "${svc}" --wait=true --timeout=150s >/dev/null 2>&1 || true
            done <<<"${lbsvcs}"
        fi
        KUBECONFIG="${kc}" kubectl delete ingress -A --all --wait=true --timeout=150s >/dev/null 2>&1 || true
        # PVCs TOO, and for the same reason as the load balancers: the controller that cleans them up
        # lives IN the cluster. Destroy the cluster first and the EBS CSI controller goes with it, so every
        # volume it provisioned strands as `available` and bills forever. Measured 2026-09-01: tearing down
        # five attendee clusters left 20 orphaned volumes, 60 GiB, four per cluster, each still tagged
        # kubernetes.io/cluster/<the deleted cluster>. At 250 attendees that is ~1000 volumes of pure waste.
        # Deleting the PVCs first lets the CSI controller release the volumes while it still exists.
        local pvcs
        pvcs="$(KUBECONFIG="${kc}" kubectl get pvc -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' 2>/dev/null)"
        if [[ -n "${pvcs}" ]]; then
            log "  ${name}: releasing $(printf '%s\n' "${pvcs}" | grep -c /) PVC(s) before destroy"
            KUBECONFIG="${kc}" kubectl delete pvc -A --all --wait=true --timeout=180s >/dev/null 2>&1 || true
        fi
        # PVCs must go while the EBS CSI controller still exists to reclaim their volumes. Destroy the
        # cluster first and the controller goes with it, so every dynamically-provisioned volume orphans
        # as 'available' and bills indefinitely. --wait=false because a PVC whose consumer pod is still
        # terminating blocks on its finalizer, and the short sleep below is enough for the controller to
        # observe the deletions; we are about to destroy the cluster either way.
        KUBECONFIG="${kc}" kubectl delete pvc -A --all --wait=false --timeout=60s >/dev/null 2>&1 || true
        sleep 10
    else
        # The cluster API was unreachable, so NOTHING was drained and the controller will die with the
        # cluster. Previously this branch did not exist and the skip was silent, which is how five
        # clusters' load balancers survived teardown unnoticed (#157). sweep_orphan_lbs will catch the
        # AWS-side result; this line makes the cause visible in the run log rather than only the symptom.
        log "  ${name}: cluster API unreachable, NOTHING drained. Load balancers and volumes will be"
        log "           swept from the AWS side after destroy; expect a lb-leak entry."
    fi
    rm -f "${kc}"
}

# Delete any AWS load balancer still tagged for a cluster, plus the target groups that hang off it.
#
# WHY THIS EXISTS ON TOP OF drain_cluster_lbs. That function deletes the Services and Ingresses so the
# AWS Load Balancer Controller can clean up while it is still alive, which is the correct order and the
# fast path. It is also best-effort in every direction: if the cluster API is unreachable it skips the
# whole block, every kubectl is `|| true`, and the deletes are capped at 150s. Any of those and the
# destroy proceeds anyway, the controller dies with the cluster, and the load balancer bills forever with
# nothing left looking for it. Measured 2026-09-01 (#157): five torn-down clusters left five NLBs and
# five ALBs active, each still holding two target groups.
#
# So this runs AFTER terraform destroy and asserts the AWS-side result rather than trusting the
# Kubernetes-side attempt. At 250 clusters a per-cluster leak is ~100 orphaned load balancers, and the
# cost is not only the ~$16/month each: every one holds ENIs in the shared VPC, so a large enough pile
# starts failing NEW cluster provisioning with subnet IP exhaustion.
sweep_orphan_lbs() {
    local name="$1" acct="${2:-${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}}" found=0
    local arns arn tagged
    arns="$(AWS_PROFILE="${acct}" aws elbv2 describe-load-balancers --region "${WIB_REGION}" \
            --query 'LoadBalancers[].LoadBalancerArn' --output text 2>/dev/null || true)"
    [[ -n "${arns}" ]] || return 0
    for arn in ${arns}; do
        tagged="$(AWS_PROFILE="${acct}" aws elbv2 describe-tags --region "${WIB_REGION}" --resource-arns "${arn}" \
                  --query "TagDescriptions[0].Tags[?Key=='elbv2.k8s.aws/cluster'].Value|[0]" --output text 2>/dev/null || true)"
        [[ "${tagged}" == "${name}" ]] || continue
        found=$(( found + 1 ))
        log "  ${name}: LEAKED load balancer survived teardown, deleting ${arn##*/}"
        AWS_PROFILE="${acct}" aws elbv2 delete-load-balancer --region "${WIB_REGION}" \
            --load-balancer-arn "${arn}" >/dev/null 2>&1 || log "  ${name}: could not delete ${arn##*/}"
    done
    # Target groups outlive their load balancer and are billed at zero, but they count against a per-region
    # quota that a 250-cluster fleet will reach, so they are swept on the same tag.
    local tgs tg
    tgs="$(AWS_PROFILE="${acct}" aws elbv2 describe-target-groups --region "${WIB_REGION}" \
           --query 'TargetGroups[].TargetGroupArn' --output text 2>/dev/null || true)"
    for tg in ${tgs}; do
        tagged="$(AWS_PROFILE="${acct}" aws elbv2 describe-tags --region "${WIB_REGION}" --resource-arns "${tg}" \
                  --query "TagDescriptions[0].Tags[?Key=='elbv2.k8s.aws/cluster'].Value|[0]" --output text 2>/dev/null || true)"
        [[ "${tagged}" == "${name}" ]] || continue
        AWS_PROFILE="${acct}" aws elbv2 delete-target-group --region "${WIB_REGION}" \
            --target-group-arn "${tg}" >/dev/null 2>&1 || true
    done
    if [[ "${found}" -gt 0 ]]; then
        log "  ${name}: swept ${found} leaked load balancer(s). The in-cluster drain did not complete;"
        log "           this is the #157 failure mode and the sweep is the backstop, not the fix."
        record_fail "lb-leak:${name}"
    fi
    return 0
}

# EBS volumes strand the same way load balancers do: the EBS CSI controller dies with the cluster, so a
# PVC released during drain leaves its volume 'available' (detached, still billed) and tagged for the
# cluster. reap-lbs already sweeps these fleet-wide by liveness; this is the per-cluster half that runs
# in down_one so a single teardown cleans up after itself and REPORTS the leak (#210). Observed
# 2026-09-04 on attendee-099: four volumes, 12 GiB, survived a "done" teardown.
sweep_orphan_volumes() {
    local name="$1" acct="${2:-${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}}" found=0
    local vols vol
    vols="$(AWS_PROFILE="${acct}" aws ec2 describe-volumes --region "${WIB_REGION}" \
            --filters "Name=tag:kubernetes.io/cluster/${name},Values=owned" Name=status,Values=available \
            --query 'Volumes[].VolumeId' --output text 2>/dev/null || true)"
    for vol in ${vols}; do
        [[ "${vol}" != "None" ]] || continue
        found=$(( found + 1 ))
        log "  ${name}: LEAKED EBS volume survived teardown, deleting ${vol}"
        AWS_PROFILE="${acct}" aws ec2 delete-volume --region "${WIB_REGION}" --volume-id "${vol}" \
            >/dev/null 2>&1 || log "  ${name}: could not delete ${vol}"
    done
    if [[ "${found}" -gt 0 ]]; then
        log "  ${name}: swept ${found} leaked EBS volume(s)"
        record_fail "vol-leak:${name}"
    fi
    return 0
}

down_one() {
    local name="$1"; assert_ours "${name}"
    [[ -f "${STATE_DIR}/${name}.tfstate" ]] || { log "  no state for ${name}, skipping"; return 0; }
    assert_membership_matches "${name}" "${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}" || return 0
    drain_cluster_lbs "${name}"
    local prof=(); [[ -n "${TF_PROFILE}" ]] && prof=(-var "profile=${TF_PROFILE}" -var "region=${WIB_REGION}")
    if terraform -chdir="${CLUSTER_DIR}" destroy -auto-approve -no-color \
        -state="${STATE_DIR}/${name}.tfstate" \
        -var "name=${name}" -var "vpc_id=${VPC_ID}" \
        -var "private_subnet_ids=${SUBNETS_JSON}" "${prof[@]}" \
        >"${LOG_DIR}/${name}.destroy.log" 2>&1; then
        rm -f "${STATE_DIR}/${name}.tfstate" "$(membership_file "${name}")"; log "  ok: ${name}"
    else
        log "  FAILED: ${name} (see ${LOG_DIR}/${name}.destroy.log)"; record_fail "${name}"
    fi
    # AFTER destroy, in BOTH branches. A failed destroy is precisely when a load balancer is most likely
    # to be stranded, so skipping the sweep on failure would skip it exactly when it is needed.
    sweep_orphan_lbs "${name}" "${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}"
    sweep_orphan_volumes "${name}" "${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}"
}

# Print any recorded failures and return non-zero if there were any. Call after a pool run.
report_failures() {
    [[ -f "${LOG_DIR}/.failures" ]] || { log "  all succeeded"; return 0; }
    local n; n="$(wc -l <"${LOG_DIR}/.failures")"
    log "  ${n} cluster(s) FAILED:"; sed 's/^/    - /' "${LOG_DIR}/.failures" >&2
    return 1
}

# Run a function over names, capped at MAX_PARALLEL.
run_pool() {
    local fn="$1"; shift
    local name running=0 total=$# done=0
    for name in "$@"; do
        "${fn}" "${name}" &
        running=$((running + 1))
        if [[ "${running}" -ge "${MAX_PARALLEL}" ]]; then
            wait -n 2>/dev/null || true
            running=$((running - 1))
            done=$((done + 1))
            log "  progress: ${done}/${total}"
        fi
    done
    wait
    log "  done: ${total}/${total}"
}

# The provisioning-registration envelope, shared by attendee `up` and `instructors up` (#162). Both used
# to inline the same token-resolve, pool-load, and loud-on-failure block, and those two copies drifted:
# `instructors up` grew the envelope while `up` had none, which is why a provisioned attendee fleet was
# invisible to the pool (#161). One helper means one behaviour. What differs between the two callers is
# only WHICH clusters to register, so that is the argument: pass the ingest action as the remaining args
# and this wraps it with everything that must be identical.
#
# register_with_provisioning <human-label> <ingest-fn> [ingest-args...]
# Non-fatal by design (an unreachable provisioning app must never fail a provision) and LOUD when it
# cannot run, because a quiet skip is what made the drift invisible.
register_with_provisioning() {
    local label="$1" ingest_fn="$2"; shift 2
    [[ -z "${WIB_DRY_RUN}" && -z "${WIB_NO_BOOTSTRAP:-}" && -z "${WIB_NO_INGEST:-}" ]] || return 0
    if resolve_admin_token >/dev/null 2>&1; then
        POOL1="$(AWS_PROFILE="${WIB_DEFAULT_ACCOUNT}" aws secretsmanager get-secret-value --secret-id watch-it-burn/datadog-pool   --region "${WIB_REGION}" --query SecretString --output text 2>/dev/null || echo '[]')"
        POOL2="$(AWS_PROFILE="${WIB_DEFAULT_ACCOUNT}" aws secretsmanager get-secret-value --secret-id watch-it-burn/datadog-pool-2 --region "${WIB_REGION}" --query SecretString --output text 2>/dev/null || echo '[]')"
        log "ingest -> ${WIB_PROVISIONING_URL%/}/admin/import"
        "${ingest_fn}" "$@" || log "ingest: re-run the matching 'fleet.sh ingest' once the consoles are up"
    else
        log "ingest: CANNOT RESOLVE the provisioning admin token, so ${label} was NOT registered."
        log "        The clusters are up and routable, but a student claiming one will be told there are"
        log "        none, and a presenter will see a blank terminal password. Fix by logging in to"
        log "        Railway (railway login), or export WIB_ADMIN_TOKEN, then re-run the ingest by hand."
        record_fail "ingest:no-admin-token"
    fi
}

# A small adapter so the attendee path can pass its name list to the shared helper, which expects one
# ingest function. Registers each provisioned attendee cluster in the default account.
_ingest_attendee_names() {
    local _n
    for _n in "$@"; do ingest_one "${_n}" "${WIB_DEFAULT_ACCOUNT}"; done
}

cmd_up() {
    [[ $# -ge 1 ]] || usage
    local names; mapfile -t names < <(expand_names "$@")
    local n bp=""; [[ -n "${WIB_NO_BOOTSTRAP:-}" ]] || bp="attendee"
    declare -gA PROVISION_SPEC=()
    # Attendee clusters are uniform: the default account, full bootstrap unless bare, no round, no
    # per-cluster tier/instance-type/pids overrides. account|profile|round|tier|itype|pids
    for n in "${names[@]}"; do PROVISION_SPEC["${n}"]="${WIB_DEFAULT_ACCOUNT}|${bp}||||"; done
    log "provisioning ${#names[@]} clusters (max ${MAX_PARALLEL} parallel)..."
    _provision_spec_fleet "these clusters" _ingest_attendee_names "${names[@]}"
}

cmd_down() {
    [[ $# -ge 1 ]] || usage
    require_tools
    read_vpc
    terraform -chdir="${CLUSTER_DIR}" init -input=false >/dev/null
    local names
    if [[ "$1" == "all" ]]; then
        mapfile -t names < <(find "${STATE_DIR}" -name '*.tfstate' -exec basename {} .tfstate \; 2>/dev/null)
    else
        mapfile -t names < <(expand_names "$@")
    fi
    [[ "${#names[@]}" -gt 0 ]] || { log "no clusters to destroy"; return 0; }
    require_apply "down" "${names[@]}" || return 0
    rm -f "${LOG_DIR}/.failures"

    # Group by the account each cluster was BUILT in, and destroy each group through that account.
    # Previously this ran every cluster through the default account's profile and VPC, so on a
    # multi-account fleet it destroyed the default account's slice and silently skipped the rest, while
    # still exiting 0. teardown.sh calls exactly this path, so that was the whole fleet teardown.
    local -A by_acct=()
    local n acct
    for n in "${names[@]}"; do
        acct="$(read_membership "${n}")"
        [[ -n "${acct}" ]] || acct="${WIB_DEFAULT_ACCOUNT}"
        by_acct["${acct}"]+="${n} "
    done

    if [[ "${#by_acct[@]}" -le 1 ]]; then
        log "destroying ${#names[@]} clusters (max ${MAX_PARALLEL} parallel)..."
        run_pool down_one "${names[@]}"
    else
        log "destroying ${#names[@]} clusters across ${#by_acct[@]} account(s)..."
        for acct in "${!by_acct[@]}"; do
            local group; read -ra group <<<"${by_acct[${acct}]}"
            log "  account '${acct}': ${#group[@]} cluster(s)"
            (
                read_vpc_for "${acct}"
                TF_PROFILE="${acct}"
                run_pool down_one "${group[@]}"
            ) &
        done
        wait
    fi
    report_failures
}

cmd_status() {
    require_tools
    local f name
    [[ -d "${STATE_DIR}" ]] || { log "no clusters provisioned"; return 0; }
    for f in "${STATE_DIR}"/*.tfstate; do
        [[ -e "${f}" ]] || { log "no clusters provisioned"; return 0; }
        name="$(basename "${f}" .tfstate)"
        local st
        st="$(AWS_PROFILE=accen-dev aws eks describe-cluster --name "${name}" \
            --region us-west-2 --query 'cluster.status' --output text 2>/dev/null || echo "UNKNOWN")"
        printf '%-32s %s\n' "${name}" "${st}"
    done
}

# Read a SPECIFIC account's lab VPC outputs (per-account state). Each account has its own VPC; the
# default single-account path uses read_vpc() instead. Fails loudly with the apply command if absent.
read_vpc_for() {
    local profile="$1"
    local state="${LAB_VPC_DIR}/states/${profile}.tfstate"
    # The default account (accen-dev) keeps its lab VPC in the DEFAULT lab-vpc state (terraform.tfstate),
    # not a per-account states/<acct>.tfstate (it was applied before the multi-account split). Fall back to
    # read_vpc() for it so it joins up-fleet/down-fleet/health like any other account, no duplicate state.
    if [[ ! -f "${state}" && "${profile}" == "${WIB_DEFAULT_ACCOUNT}" ]]; then
        read_vpc; return
    fi
    if [[ ! -f "${state}" ]]; then
        log "no lab VPC for account '${profile}'. Apply it first:"
        log "  terraform -chdir=${LAB_VPC_DIR} apply -state=states/${profile}.tfstate \\"
        log "    -var profile=${profile} -var region=${WIB_REGION}"
        exit 1
    fi
    VPC_ID="$(terraform -chdir="${LAB_VPC_DIR}" output -state="${state}" -raw vpc_id 2>/dev/null || true)"
    SUBNETS_JSON="$(terraform -chdir="${LAB_VPC_DIR}" output -state="${state}" -json private_subnet_ids 2>/dev/null || true)"
    [[ -n "${VPC_ID}" && -n "${SUBNETS_JSON}" ]] || { log "could not read lab VPC outputs for ${profile}"; exit 1; }
}

# fleet.sh only provisions; remind which bootstrap profile each instructor needs (burn vs full).
print_bootstrap_hints() {
    local round_filter="${1:-}" entry name rr tier itype pidscol bp
    log "next: bootstrap each (fleet.sh provisions; deploy-full-idp.sh bootstraps):"
    for entry in "${INSTRUCTORS[@]}"; do
        IFS='|' read -r name rr tier itype pidscol bp owner <<<"${entry}"
        [[ -n "${round_filter}" && "${round_filter}" != "${rr}" ]] && continue
        log "  ${name}: AWS_PROFILE=$(account_for_round "${rr}") KUBECONFIG=<isolated> deploy-full-idp.sh ${bp}"
    done
}

# up_one wrapper (§4.6): look up this cluster's roster row and set the per-cluster TF_* overrides (pids /
# instance_type / tier) before provisioning. Runs inside run_pool's per-cluster subshell, so the globals
# are process-local and cannot clash across concurrent clusters.

# One round in its own subshell (§4.6): per-round TF_PROFILE / VPC globals stay isolated from other
# concurrent rounds. Reads the round's clusters from the roster (capped by WIB_PER_ROUND) and provisions
# or destroys them via the concurrency pool.
# Tear down one round's roster clusters. UP no longer comes through here: it builds PROVISION_SPEC and
# goes through the unified _provision_spec_fleet like the attendee path (#162). This is down-only now, so
# the argument that used to select up/down is gone and the dead reference to the removed _up_from_roster
# is gone with it.
_run_round() {
    local r="$1" entry name rr tier itype pidscol bp names=() n=0
    for entry in "${INSTRUCTORS[@]}"; do
        IFS='|' read -r name rr tier itype pidscol bp owner <<<"${entry}"
        [[ "${rr}" == "${r}" ]] || continue
        [[ -n "${WIB_PER_ROUND}" && "${n}" -ge "${WIB_PER_ROUND}" ]] && break
        names+=("${name}"); n=$((n + 1))
    done
    [[ "${#names[@]}" -gt 0 ]] || return 0
    local acct; acct="$(account_for_round "${r}")"
    log "round ${r} instructors -> account '${acct}': ${names[*]}"
    if [[ -n "${WIB_DRY_RUN}" ]]; then VPC_ID="dry-vpc"; SUBNETS_JSON='[]'; else read_vpc_for "${acct}"; fi
    TF_PROFILE="${acct}"
    run_pool down_one "${names[@]}"
}

# Provision/destroy the instructor roster. Rounds run CONCURRENTLY by default (§4.6), each in its own
# subshell; WIB_SERIAL=1 forces the old serial loop. Round selection: 2nd arg > WIB_ROUNDS env > all.
cmd_instructors() {
    local action="${1:-}" selector="${2:-}"
    case "${action}" in
        up) ;;
        down) _instructors_down "${selector}"; return ;;
        status) cmd_status; return ;;
        *) usage ;;
    esac
    load_roster
    # The second argument is either a ROUND (1|2|3) or an OWNER (michael|whitney|both|all), because the
    # two are the natural ways to slice the roster and neither is ambiguous: a round is a bare digit and
    # an owner never is (#88). Previously only the round existed, so "give me Whitney's three clusters"
    # meant provisioning the whole roster or naming her clusters by hand, and the -1/-2 suffix split was
    # convention held in someone's head rather than in the tool. The owner column in roster.tsv already
    # carries the answer; this exposes it.
    local round_filter="" owner_filter=""
    case "${selector}" in
        "" ) ;;
        [123] ) round_filter="${selector}" ;;
        both|all ) ;;
        * ) owner_filter="${selector,,}" ;;
    esac
    local rounds=(1 2 3) r
    [[ -n "${WIB_ROUNDS}" ]] && IFS=',' read -r -a rounds <<<"${WIB_ROUNDS}"
    [[ -n "${round_filter}" ]] && rounds=("${round_filter}")

    declare -gA PROVISION_SPEC=()
    local entry name rr tier itype pidscol bpcol owner acct bp n
    for r in "${rounds[@]}"; do
        acct="$(account_for_round "${r}")"
        # R1 is the burn profile (BurritoBot + scenario apps, NO enforcing guardrails); R2/R3 are full,
        # armed to Enforce by bootstrap_one. Derived from the round, not the roster bp column, which
        # _run_round used to ignore, leaving Kyverno stuck in Audit (found 2026-07-10). A bare provision
        # sets no profile so nothing bootstraps.
        if [[ -n "${WIB_NO_BOOTSTRAP:-}" ]]; then bp=""; elif [[ "${r}" == "1" ]]; then bp="burn"; else bp="full"; fi
        n=0
        for entry in "${INSTRUCTORS[@]}"; do
            IFS='|' read -r name rr tier itype pidscol bpcol owner <<<"${entry}"
            [[ "${rr}" == "${r}" ]] || continue
            # An owner filter selects that presenter's set. An UNOWNED roster row (empty owner column,
            # the -3 spares) is excluded when filtering by owner: it belongs to nobody, so "Whitney's
            # clusters" must not quietly include it.
            [[ -n "${owner_filter}" && "${owner,,}" != "${owner_filter}" ]] && continue
            [[ -n "${WIB_PER_ROUND}" && "${n}" -ge "${WIB_PER_ROUND}" ]] && break
            # account|profile|round|tier|itype|pids  -- per-cluster tier/itype/pids come from the roster
            PROVISION_SPEC["${name}"]="${acct}|${bp}|${r}|${tier}|${itype}|${pidscol}"
            n=$(( n + 1 ))
        done
    done
    [[ "${#PROVISION_SPEC[@]}" -gt 0 ]] || { log "no roster clusters for the requested round(s)"; return 0; }
    log "provisioning ${#PROVISION_SPEC[@]} instructor cluster(s)..."
    _provision_spec_fleet "the roster" cmd_ingest_instructors "${round_filter}"
    [[ -n "${WIB_NO_BOOTSTRAP:-}" ]] && print_bootstrap_hints "${round_filter}"
}

# Instructor teardown keeps the round-grouped loop: down has no routes/register tail to share, and
# down_one needs TF_PROFILE per account, which the round split already provides.
_instructors_down() {
    local round_filter="${1:-}"
    require_tools
    mkdir -p "${STATE_DIR}" "${LOG_DIR}"; rm -f "${LOG_DIR}/.failures"
    load_roster
    terraform -chdir="${CLUSTER_DIR}" init -input=false >/dev/null
    local rounds=(1 2 3) r
    [[ -n "${WIB_ROUNDS}" ]] && IFS=',' read -r -a rounds <<<"${WIB_ROUNDS}"
    [[ -n "${round_filter}" ]] && rounds=("${round_filter}")
    for r in "${rounds[@]}"; do
        _run_round "${r}" &
        [[ -n "${WIB_SERIAL}" ]] && wait
    done
    wait || true
    report_failures
}

# Provision the attendee fleet across WIB_ATTENDEE_ACCOUNTS concurrently: one per-account pool per
# account, all running at once, with disjoint cluster-number ranges so state files never collide.
cmd_up_fleet() {
    local per_account="${1:-}"
    [[ "${per_account}" =~ ^[0-9]+$ && "${per_account}" -gt 0 ]] || { log "usage: up-fleet <clusters-per-account>"; exit 2; }
    local accounts; IFS=',' read -ra accounts <<<"${WIB_ATTENDEE_ACCOUNTS}"
    local n nm bp=""; [[ -n "${WIB_NO_BOOTSTRAP:-}" ]] || bp="attendee"
    declare -gA PROVISION_SPEC=()
    local allnames=() idx=0 acct start
    for acct in "${accounts[@]}"; do
        acct="${acct// /}"; [[ -n "${acct}" ]] || continue
        start=$(( WIB_NAME_OFFSET + idx * per_account + 1 )); idx=$(( idx + 1 ))
        for n in $(seq "${start}" $(( start + per_account - 1 ))); do
            nm="$(printf '%s-%03d' "${NAME_PREFIX}" "${n}")"
            PROVISION_SPEC["${nm}"]="${acct}|${bp}||||"
            allnames+=("${nm}")
        done
    done
    log "up-fleet: ${#accounts[@]} account(s) x ${per_account} clusters, all concurrent..."
    # Registers now too. cmd_up_fleet used to regenerate routes but never register, so the fleet path
    # provisioned clusters that resolved but that provisioning had never heard of (#161/#162). The
    # shared core does both.
    _provision_spec_fleet "these clusters" _ingest_attendee_names "${allnames[@]}"
}

# Tear down the attendee fleet: mirror of up-fleet (same accounts, per_account count, and WIB_NAME_OFFSET)
# so each cluster is destroyed in ITS account, with ITS account VPC and profile. down_one skips any name
# with no state file, so a partial fleet tears down cleanly. Pass the SAME <per_account> used for up-fleet.
cmd_down_fleet() {
    local per_account="${1:-}"
    [[ "${per_account}" =~ ^[0-9]+$ && "${per_account}" -gt 0 ]] || { log "usage: down-fleet <clusters-per-account>"; exit 2; }
    require_tools
    mkdir -p "${STATE_DIR}" "${LOG_DIR}"; rm -f "${LOG_DIR}/.failures"
    terraform -chdir="${CLUSTER_DIR}" init -input=false >/dev/null
    local accounts; IFS=',' read -ra accounts <<<"${WIB_ATTENDEE_ACCOUNTS}"
    log "down-fleet: ${#accounts[@]} account(s) x ${per_account} clusters (offset ${WIB_NAME_OFFSET})..."
    # Preview the WHOLE cross-account set before destroying any of it. The name range is derived from
    # per_account + WIB_NAME_OFFSET, so a wrong value here silently targets a different span of clusters
    # than the up-fleet that created them; seeing the actual first and last name per account is what
    # catches that before it happens rather than after.
    if [[ -z "${WIB_APPLY:-}" ]]; then
        local _i=0 _a _s
        log "DRY-RUN: down-fleet would destroy ${per_account} cluster(s) in each of ${#accounts[@]} account(s):"
        for _a in "${accounts[@]}"; do
            _a="${_a// /}"; [[ -n "${_a}" ]] || continue
            _s=$(( WIB_NAME_OFFSET + _i * per_account + 1 )); _i=$(( _i + 1 ))
            log "    ${_a}: $(printf '%s-%03d' "${NAME_PREFIX}" "${_s}") .. $(printf '%s-%03d' "${NAME_PREFIX}" $(( _s + per_account - 1 )))"
        done
        log "Set WIB_APPLY=1 to actually destroy."
        return 0
    fi
    local idx=0 acct start n names
    for acct in "${accounts[@]}"; do
        acct="${acct// /}"; [[ -n "${acct}" ]] || continue
        start=$(( WIB_NAME_OFFSET + idx * per_account + 1 ))
        idx=$(( idx + 1 ))
        [[ -f "${LAB_VPC_DIR}/states/${acct}.tfstate" || "${acct}" == "${WIB_DEFAULT_ACCOUNT}" ]] || { log "  account '${acct}': no lab VPC state, skipping"; continue; }
        names=(); for n in $(seq "${start}" $(( start + per_account - 1 ))); do
            names+=("$(printf '%s-%03d' "${NAME_PREFIX}" "${n}")")
        done
        log "  account '${acct}': destroying ${names[0]} .. ${names[-1]}"
        (
            read_vpc_for "${acct}"
            TF_PROFILE="${acct}"
            run_pool down_one "${names[@]}"
        ) &
    done
    wait
    report_failures
}

# Per-cluster IDP health: the REAL "is the platform up" gate (cmd_status only reports EKS control-plane
# state). Pulls an ISOLATED kubeconfig per cluster (never ~/.kube/config) with the account's profile, then
# asserts the ArgoCD app-of-apps is fully converged (every Application Synced AND Healthy) plus a pod
# sanity backstop (no Pending/Failed pods). If all apps are Healthy the workloads they manage are up.
health_one() {
    local name="$1"; assert_ours "${name}"
    local acct_profile="${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}"
    local kcfg; kcfg="$(mktemp -t "${name}.kcfg.XXXX")"
    if ! provider_write_kubeconfig "${name}" "${kcfg}" "${acct_profile}"; then
        log "  ${name}: UNREACHABLE (no kubeconfig)"; record_fail "${name}:unreachable"; rm -f "${kcfg}"; return
    fi
    local apps total healthy pending failed
    apps="$(KUBECONFIG="${kcfg}" kubectl get applications.argoproj.io -n argocd -o json 2>/dev/null)"
    if [[ -z "${apps}" || "$(jq '.items | length' <<<"${apps}" 2>/dev/null)" == "0" ]]; then
        log "  ${name}: NO ArgoCD applications (bootstrap not applied / ArgoCD down)"
        record_fail "${name}:no-argocd"; rm -f "${kcfg}"; return
    fi
    total="$(jq '.items | length' <<<"${apps}")"
    healthy="$(jq '[.items[] | select(.status.sync.status=="Synced" and .status.health.status=="Healthy")] | length' <<<"${apps}")"
    pending="$(KUBECONFIG="${kcfg}" kubectl get pods -A --field-selector=status.phase==Pending -o name 2>/dev/null | wc -l | tr -d ' ')"
    failed="$(KUBECONFIG="${kcfg}" kubectl get pods -A --field-selector=status.phase==Failed -o name 2>/dev/null | wc -l | tr -d ' ')"
    rm -f "${kcfg}"
    if [[ "${healthy}" == "${total}" && "${pending}" == "0" && "${failed}" == "0" ]]; then
        log "  ${name}: HEALTHY (apps ${healthy}/${total} Synced+Healthy, no broken pods)"
    else
        log "  ${name}: DEGRADED (apps ${healthy}/${total} Synced+Healthy, ${pending} pending, ${failed} failed pod(s))"
        # Name the unhealthy apps so the failure line is actionable.
        local bad; bad="$(jq -r '[.items[] | select((.status.sync.status!="Synced") or (.status.health.status!="Healthy")) | .metadata.name] | join(",")' <<<"${apps}")"
        record_fail "${name}:degraded apps=${healthy}/${total} unhealthy=[${bad}] pending=${pending} failed=${failed}"
    fi
}

# Sweep IDP health across the fleet: mirror of up-fleet/down-fleet (same accounts, per_account, offset).
# Pass the SAME <per_account> used for up-fleet. Exits non-zero unless every cluster is HEALTHY.
# --- converge -----------------------------------------------------------------------------------
#
# Why this verb exists. On a 250-cluster run of the sister Packt fleet, 27 clusters (11%) were fully
# built and healthy but had a freshly created NLB whose hostname was not yet resolvable inside the
# health-check window. Without a second pass the run reports 89% success and hands back two dozen
# clusters that are actually fine. The natural response, re-running provisioning for the failures, is
# both slow and wrong: it rebuilds working infrastructure to fix a DNS propagation delay.
#
# So converge re-checks the already-provisioned set and acts only on what is genuinely unhealthy, and
# it is a loop rather than a report. `health` appends names to a dotfile a human then reads; at fleet
# scale a 5% failure rate is a dozen reruns discovered by reading a file.
#
# Two wait budgets, deliberately separate. A load balancer being ASSIGNED a hostname and that hostname
# RESOLVING fail differently and on different timescales, and one timeout covering both cannot tell you
# which happened.
readonly CONVERGE_LB_WAIT="${WIB_CONVERGE_LB_WAIT:-180}"    # seconds for the LB Controller to assign a hostname
readonly CONVERGE_DNS_WAIT="${WIB_CONVERGE_DNS_WAIT:-300}"  # seconds for that hostname to resolve publicly
readonly CONVERGE_ROUNDS="${WIB_CONVERGE_ROUNDS:-3}"

# Does this cluster's attendee entrypoint actually work? Healthy Argo apps do not imply a reachable
# console, and the console NLB is the thing the attendee is handed.
converge_endpoint() {
    local name="$1" kcfg="$2" host="" waited=0
    while [[ "${waited}" -lt "${CONVERGE_LB_WAIT}" ]]; do
        host="$(KUBECONFIG="${kcfg}" kubectl get svc -n agent console \
            -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
        [[ -n "${host}" ]] && break
        sleep 10; waited=$(( waited + 10 ))
    done
    if [[ -z "${host}" ]]; then
        echo "no-lb-hostname"; return 1
    fi
    waited=0
    local resolved=""
    while [[ "${waited}" -lt "${CONVERGE_DNS_WAIT}" ]]; do
        if getent hosts "${host}" >/dev/null 2>&1; then resolved=1; break; fi
        sleep 10; waited=$(( waited + 10 ))
    done
    [[ -n "${resolved}" ]] || { echo "lb-assigned-but-dns-unresolved:${host}"; return 1; }

    # DNS resolving is not the same as the attendee's page working. The NLB answers as soon as its
    # hostname exists, but its target group can still be failing health checks, and the console pod can
    # be Running without the app serving. Both states resolve happily and hand the attendee a 502.
    # The definition of done is the surface they actually open, so assert a real 200. Kept on the same
    # DNS budget rather than a third one: at this point the only thing still settling is registration.
    local code=""
    while [[ "${waited}" -lt "${CONVERGE_DNS_WAIT}" ]]; do
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://${host}/" 2>/dev/null || true)"
        [[ "${code}" == "200" ]] && { echo "${host}"; return 0; }
        sleep 10; waited=$(( waited + 10 ))
    done
    echo "dns-ok-but-http-${code:-none}:${host}"; return 1
}

# Nudge a degraded cluster instead of rebuilding it. A hard refresh is what clears the common case (an
# Application that gave up on a transient sync), and it is safe to run against a healthy cluster.
converge_one() {
    local name="$1"; assert_ours "${name}"
    local acct_profile="${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}"
    local kcfg; kcfg="$(mktemp -t "${name}.conv.XXXX")"
    if ! provider_write_kubeconfig "${name}" "${kcfg}" "${acct_profile}"; then
        log "  ${name}: UNREACHABLE (no kubeconfig)"; record_fail "${name}:unreachable"; rm -f "${kcfg}"; return
    fi
    local apps total healthy bad a
    apps="$(KUBECONFIG="${kcfg}" kubectl get applications.argoproj.io -n argocd -o json 2>/dev/null)"
    if [[ -z "${apps}" || "$(jq '.items | length' <<<"${apps}" 2>/dev/null)" == "0" ]]; then
        log "  ${name}: NO ArgoCD applications; converge cannot help, this needs a bootstrap"
        record_fail "${name}:no-argocd"; rm -f "${kcfg}"; return
    fi
    total="$(jq '.items | length' <<<"${apps}")"
    healthy="$(jq '[.items[] | select(.status.sync.status=="Synced" and .status.health.status=="Healthy")] | length' <<<"${apps}")"
    if [[ "${healthy}" != "${total}" ]]; then
        bad="$(jq -r '.items[] | select((.status.sync.status!="Synced") or (.status.health.status!="Healthy")) | .metadata.name' <<<"${apps}")"
        log "  ${name}: refreshing $(printf '%s\n' "${bad}" | grep -c .) unhealthy app(s)"
        while read -r a; do
            [[ -n "${a}" ]] || continue
            KUBECONFIG="${kcfg}" kubectl -n argocd annotate application "${a}" \
                argocd.argoproj.io/refresh=hard --overwrite >/dev/null 2>&1 || true
        done <<<"${bad}"
    fi
    local ep; ep="$(converge_endpoint "${name}" "${kcfg}")"
    local ok=$?
    rm -f "${kcfg}"
    if [[ "${healthy}" == "${total}" && "${ok}" -eq 0 ]]; then
        log "  ${name}: CONVERGED (apps ${total}/${total}, console ${ep})"
        return 0
    fi
    record_fail "${name}:apps=${healthy}/${total} endpoint=${ep}"
}

# Re-check the provisioned set and repair, up to CONVERGE_ROUNDS times. Takes <clusters-per-account>,
# the same argument shape as `health`, because this is a fleet-scale problem. Each round narrows to
# whatever is still failing, so a converged cluster is never touched twice.
#
# The account a name belongs to is derived from its index, exactly as cmd_health lays them out, so a
# later round can re-check a straggler in the right account without re-deriving the whole plan.
_account_for_name() {
    local name="$1" per_account="$2" num idx
    # Prefer the account this cluster was ACTUALLY built in, recorded at apply time. The arithmetic
    # below reconstructs it from WIB_NAME_OFFSET and per_account, which is only correct if both match
    # the up-fleet that created the cluster. When they do not, the reconstruction points at a different
    # account, the state lookup finds nothing, and a destroy reports success having destroyed nothing.
    local recorded; recorded="$(read_membership "${name}")"
    [[ -n "${recorded}" ]] && { echo "${recorded}"; return 0; }
    # A ROSTER cluster is not in the attendee numbering at all: watch-it-burn-r2-1 would parse as num=1
    # and land in the first account regardless of which account round 2 actually lives in. Resolve it by
    # round, the same way cmd_instructors does.
    if is_instructor_name "${name}"; then
        account_for_round "$(round_of_instructor_name "${name}")"; return 0
    fi
    # per_account is the divisor below, so a caller with no pool size to offer (converge on explicit
    # names, for instance) would divide by zero. With no membership record and no pool geometry there is
    # nothing to reconstruct from, and the default account is the only honest answer.
    if [[ -z "${per_account}" || "${per_account}" -le 0 ]]; then
        echo "${WIB_DEFAULT_ACCOUNT}"; return 0
    fi
    num="${name##*-}"; num="$(( 10#${num} ))"
    idx=$(( (num - WIB_NAME_OFFSET - 1) / per_account ))
    local accounts; IFS=',' read -ra accounts <<<"${WIB_ATTENDEE_ACCOUNTS}"
    local a="${accounts[${idx}]:-}"; echo "${a// /}"
}

# Cluster-to-account membership, persisted beside the state file at apply time.
#
# The account a cluster lives in is a FACT established when it was created, not something to recompute
# later from whatever arguments happen to be in the current invocation. Recomputing it is how a fleet
# gets orphaned: `down-fleet 50` run with a different offset than the `up-fleet 50` that built it looks
# in the wrong account, finds no state, skips every name, and exits 0. The teardown reads as clean while
# the clusters keep running and billing in an account nobody is looking at any more.
membership_file() { printf '%s/%s.account' "${STATE_DIR}" "$1"; }

record_membership() {
    local name="$1" acct="$2"
    [[ -n "${acct}" ]] || return 0
    mkdir -p "${STATE_DIR}"
    printf '%s\n' "${acct}" >"$(membership_file "${name}")"
}

read_membership() {
    local f; f="$(membership_file "$1")"
    if [[ -r "${f}" ]]; then head -1 "${f}" | tr -d '[:space:]'; fi
    return 0   # an unrecorded cluster is a normal answer; see round_of_instructor_name
}

# Refuse to destroy through a profile that disagrees with the recorded one. Without the record we
# cannot check, so an unrecorded cluster (built before this landed) is allowed through with a warning
# rather than blocked, which would make every pre-existing cluster undestroyable.
assert_membership_matches() {
    local name="$1" acct="$2" recorded
    recorded="$(read_membership "${name}")"
    if [[ -z "${recorded}" ]]; then
        log "  ${name}: no recorded account (pre-dates membership tracking); proceeding with '${acct}'"
        return 0
    fi
    if [[ "${recorded}" != "${acct}" ]]; then
        log "  REFUSING ${name}: built in account '${recorded}' but this run targets '${acct}'."
        log "    Destroying through the wrong account silently does nothing and leaves the cluster billing."
        record_fail "${name}:account-mismatch recorded=${recorded} attempted=${acct}"
        return 1
    fi
    return 0
}

cmd_converge() {
    # Accepts THREE forms, because the attendee numbering was the only thing it understood (#85):
    #
    #   converge <n>                 the attendee pool, n per account (the original, unchanged)
    #   converge instructors [round] the roster, optionally one round
    #   converge <name...>           any explicit set, attendee or roster, mixed
    #
    # The roster is a separate name space (watch-it-burn-r<round>-<n>) provisioned from roster.tsv and
    # split across accounts BY ROUND, not by the attendee offset arithmetic. So there was no way to
    # converge the nine clusters the presenters actually drive from, which are the ones whose console NLB
    # not resolving in time ends the workshop rather than costing one attendee a cluster. The repair loop
    # existed and could not be pointed at them.
    local per_account="" all=() idx=0 acct start n
    local accounts; IFS=',' read -ra accounts <<<"${WIB_ATTENDEE_ACCOUNTS}"

    if [[ "${1:-}" == "instructors" ]]; then
        local round_filter="${2:-}"
        load_roster
        local entry nm rnd
        for entry in "${INSTRUCTORS[@]}"; do
            nm="${entry%%|*}"; rnd="$(round_of_instructor_name "${nm}")"
            [[ -z "${round_filter}" || "${rnd}" == "${round_filter}" ]] && all+=("${nm}")
        done
        [[ "${#all[@]}" -gt 0 ]] || { log "converge: no roster clusters match round '${round_filter}'"; exit 2; }
        # Roster clusters resolve their account by round, so the account list this run touches is theirs.
        accounts=()
        for nm in "${all[@]}"; do
            acct="$(account_for_round "$(round_of_instructor_name "${nm}")")"
            [[ " ${accounts[*]} " == *" ${acct} "* ]] || accounts+=("${acct}")
        done
    elif [[ "${1:-}" =~ ^[0-9]+$ && "${1}" -gt 0 ]]; then
        per_account="$1"
        for acct in "${accounts[@]}"; do
            acct="${acct// /}"; [[ -n "${acct}" ]] || continue
            start=$(( WIB_NAME_OFFSET + idx * per_account + 1 )); idx=$(( idx + 1 ))
            for n in $(seq "${start}" $(( start + per_account - 1 ))); do
                all+=("$(printf '%s-%03d' "${NAME_PREFIX}" "${n}")")
            done
        done
    elif [[ $# -ge 1 ]]; then
        all=("$@")
        accounts=()
        for n in "${all[@]}"; do
            acct="$(_account_for_name "${n}" 0)"
            [[ " ${accounts[*]} " == *" ${acct} "* ]] || accounts+=("${acct}")
        done
    else
        log "usage: converge <clusters-per-account> | converge instructors [round] | converge <name...>"
        exit 2
    fi
    command -v kubectl >/dev/null 2>&1 || { log "missing tool: kubectl"; exit 1; }
    require_tools
    mkdir -p "${LOG_DIR}"

    local total="${#all[@]}" round=1 remaining=("${all[@]}") still name a
    while [[ "${round}" -le "${CONVERGE_ROUNDS}" && "${#remaining[@]}" -gt 0 ]]; do
        log "converge round ${round}/${CONVERGE_ROUNDS}: ${#remaining[@]} of ${total} cluster(s)"
        rm -f "${LOG_DIR}/.failures"
        # Group this round's names by account so each pool runs under the right profile.
        for acct in "${accounts[@]}"; do
            acct="${acct// /}"; [[ -n "${acct}" ]] || continue
            local batch=()
            for name in "${remaining[@]}"; do
                a="$(_account_for_name "${name}" "${per_account}")"
                [[ "${a}" == "${acct}" ]] && batch+=("${name}")
            done
            [[ "${#batch[@]}" -gt 0 ]] || continue
            ( TF_PROFILE="${acct}"; run_pool converge_one "${batch[@]}" ) &
        done
        wait
        [[ -f "${LOG_DIR}/.failures" ]] || { remaining=(); break; }
        mapfile -t still < <(cut -d: -f1 "${LOG_DIR}/.failures" | sort -u)
        remaining=("${still[@]}")
        round=$(( round + 1 ))
        [[ "${#remaining[@]}" -gt 0 && "${round}" -le "${CONVERGE_ROUNDS}" ]] && sleep 30
    done

    if [[ "${#remaining[@]}" -eq 0 ]]; then
        log "CONVERGED: ${total}/${total} clusters healthy with a resolvable console endpoint"
        rm -f "${LOG_DIR}/.failures"; return 0
    fi
    log "${#remaining[@]}/${total} cluster(s) did NOT converge after ${CONVERGE_ROUNDS} rounds:"
    sed 's/^/    - /' "${LOG_DIR}/.failures" >&2
    return 1
}

cmd_health() {
    local per_account="${1:-}"
    [[ "${per_account}" =~ ^[0-9]+$ && "${per_account}" -gt 0 ]] || { log "usage: health <clusters-per-account>"; exit 2; }
    command -v kubectl >/dev/null 2>&1 || { log "missing tool: kubectl"; exit 1; }
    require_tools
    mkdir -p "${LOG_DIR}"; rm -f "${LOG_DIR}/.failures"
    local accounts; IFS=',' read -ra accounts <<<"${WIB_ATTENDEE_ACCOUNTS}"
    log "health: ${#accounts[@]} account(s) x ${per_account} clusters (offset ${WIB_NAME_OFFSET})..."
    local idx=0 acct start n names
    for acct in "${accounts[@]}"; do
        acct="${acct// /}"; [[ -n "${acct}" ]] || continue
        start=$(( WIB_NAME_OFFSET + idx * per_account + 1 ))
        idx=$(( idx + 1 ))
        names=(); for n in $(seq "${start}" $(( start + per_account - 1 ))); do
            names+=("$(printf '%s-%03d' "${NAME_PREFIX}" "${n}")")
        done
        ( TF_PROFILE="${acct}"; run_pool health_one "${names[@]}" ) &
    done
    wait
    if report_failures; then log "ALL CLUSTERS HEALTHY"; fi
}

# Harvest one cluster's student-facing access info (console NLB / grafana / etc.) as a pool CSV row.
harvest_one() {
    local name="$1"; assert_ours "${name}"
    local acct_profile="${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}"
    AWS_PROFILE="${acct_profile}" bash "${HARVEST_SCRIPT}" "${name}" "${WIB_REGION}" 2>>"${LOG_DIR}/${name}.harvest.log" \
        || { record_fail "${name}:harvest"; log "  ${name}: harvest FAILED (see ${LOG_DIR}/${name}.harvest.log)"; }
}

# Harvest access info across the fleet into ONE CSV (the aws-pool merge_pool.py ingests). Mirror of
# up-fleet/health (same accounts, per_account, offset). Run AFTER clusters have converged (the NLB needs
# to be provisioned). Header + one row per cluster on stdout: redirect to a file then feed merge_pool.py.
cmd_harvest() {
    local per_account="${1:-}"
    [[ "${per_account}" =~ ^[0-9]+$ && "${per_account}" -gt 0 ]] || { log "usage: harvest <clusters-per-account>"; exit 2; }
    require_tools
    [[ -x "${HARVEST_SCRIPT}" ]] || { log "missing harvester: ${HARVEST_SCRIPT}"; exit 1; }
    mkdir -p "${LOG_DIR}"; rm -f "${LOG_DIR}/.failures"
    local accounts; IFS=',' read -ra accounts <<<"${WIB_ATTENDEE_ACCOUNTS}"
    log "harvest: ${#accounts[@]} account(s) x ${per_account} clusters (offset ${WIB_NAME_OFFSET}) -> stdout CSV"
    # header (matches harvest_cluster_access.sh row order)
    printf 'name,region,console_url,burritbot_url,grafana_url,grafana_password,argocd_url,argocd_password\n'
    local idx=0 acct start n names
    for acct in "${accounts[@]}"; do
        acct="${acct// /}"; [[ -n "${acct}" ]] || continue
        start=$(( WIB_NAME_OFFSET + idx * per_account + 1 ))
        idx=$(( idx + 1 ))
        for n in $(seq "${start}" $(( start + per_account - 1 ))); do
            name="$(printf '%s-%03d' "${NAME_PREFIX}" "${n}")"
            TF_PROFILE="${acct}" harvest_one "${name}"
        done
    done
    report_failures >&2 || true
}

# Generate the per-attendee AWS half of the pool across the fleet: one scoped IAM user + access key per
# cluster, in the cluster's OWN account (mirrors up-fleet's account/range scheme). DRY-RUN by default;
# set WIB_APPLY=1 to actually create. WIB_ACCESS_ENTRIES=1 also maps each user into its cluster (needs
# the cluster to exist). Per-account CSVs land in aws-pool/ (gitignored, live keys). Feed them to
# merge_pool.py. This is the 250-key go-live step (issue: per-attendee AWS creds / B14).
cmd_aws_keys() {
    local per_account="${1:-}"
    [[ "${per_account}" =~ ^[0-9]+$ && "${per_account}" -gt 0 ]] || { log "usage: aws-keys <clusters-per-account>"; exit 2; }
    [[ -f "${GEN_AWS_SCRIPT}" ]] || { log "missing generator: ${GEN_AWS_SCRIPT}"; exit 1; }
    command -v uv >/dev/null 2>&1 || { log "need uv (the generator runs 'uv run --with boto3')"; exit 1; }
    mkdir -p "${AWS_POOL_DIR}"
    local apply=() entries=()
    [[ -n "${WIB_APPLY:-}" ]] && apply=(--apply) || log "DRY-RUN (set WIB_APPLY=1 to actually create IAM users/keys)"
    [[ -n "${WIB_ACCESS_ENTRIES:-}" ]] && entries=(--access-entries)
    local accounts; IFS=',' read -ra accounts <<<"${WIB_ATTENDEE_ACCOUNTS}"
    log "aws-keys: ${#accounts[@]} account(s) x ${per_account} clusters (offset ${WIB_NAME_OFFSET})"
    local idx=0 acct start n names
    for acct in "${accounts[@]}"; do
        acct="${acct// /}"; [[ -n "${acct}" ]] || continue
        start=$(( WIB_NAME_OFFSET + idx * per_account + 1 ))
        idx=$(( idx + 1 ))
        names=""
        for n in $(seq "${start}" $(( start + per_account - 1 ))); do
            names+="$(printf '%s-%03d' "${NAME_PREFIX}" "${n}"),"
        done
        names="${names%,}"
        log "  account '${acct}': $(printf '%s-%03d' "${NAME_PREFIX}" "${start}") .. $(printf '%s-%03d' "${NAME_PREFIX}" $(( start + per_account - 1 )))"
        uv run --with boto3 python "${GEN_AWS_SCRIPT}" \
            --clusters "${names}" --profile "${acct}" --region "${WIB_REGION}" \
            --out "${AWS_POOL_DIR}/${acct}.csv" "${apply[@]}" "${entries[@]}" \
            || { record_fail "aws-keys:${acct}"; log "  ${acct}: aws-keys FAILED"; }
    done
    [[ -n "${WIB_APPLY:-}" ]] && log "per-account CSVs in ${AWS_POOL_DIR}/ (live keys, gitignored) — feed to merge_pool.py"
    report_failures >&2 || true
}

# Lifecycle reaper (cost control): tear down attendee clusters NOT in the claimed keep-list, across all
# accounts. The keep-list is the claimed clusters (e.g. the provisioning app's /admin/export, one
# watch-it-burn-* name per line). Queries each account's LIVE EKS clusters (authoritative), reaps any
# attendee cluster not kept and that has fleet state. DRY-RUN unless WIB_APPLY=1.
# Find and delete load balancers, target groups and EBS volumes whose cluster no longer exists, across
# every account. This is the standing safety net for #157: sweep_orphan_lbs catches a leak at the moment
# of teardown, and this catches everything that leaked before it existed, or through a teardown that
# never ran at all (a killed run, a cluster deleted from the console).
#
# The orphan test is deliberately "tagged for a cluster that is not in eks list-clusters", not an age or
# a name pattern. Age is wrong because a legitimately long-lived instructor cluster looks old, and names
# are wrong because the tag is the only thing that survives the cluster it belonged to.
#
# DRY-RUN by default, like every other destructive verb here. WIB_APPLY=1 to actually delete.
cmd_reap_lbs() {
    # Deliberately NOT require_apply: that helper wants a list of cluster names up front, and this verb
    # has to survey every account before it knows what it would touch. The dry-run guard is the WIB_APPLY
    # check on each delete below, and the summary states which mode ran.
    [[ -n "${WIB_APPLY:-}" ]] || log "reap-lbs: DRY-RUN (set WIB_APPLY=1 to delete). Surveying ${WIB_ATTENDEE_ACCOUNTS}"
    local accounts; IFS=',' read -ra accounts <<<"${WIB_ATTENDEE_ACCOUNTS}"
    local acct live arns arn tagged tgs tg vols vol total=0 swept=0
    for acct in "${accounts[@]}"; do
        # THE LIVE LIST IS THE ONLY THING STANDING BETWEEN THIS VERB AND A LIVE CLUSTER'S FRONT DOOR,
        # so a failure to fetch it must stop the account, never fall through as "nothing is alive".
        #
        # This call used to be `2>/dev/null || true`, which turns any API failure (throttle, expired
        # token, a transient 500) into an EMPTY live list. Every tagged load balancer then fails the
        # liveness grep below, is logged as an orphan, and with WIB_APPLY=1 is deleted. The predicate
        # failed open, in the direction of deletion, on the one input it cannot afford to guess.
        #
        # On 2026-09-03 at 13:20Z the console NLBs for watch-it-burn-r2-1 and r2-2 were deleted by this
        # account's IAM user while both clusters were live and serving. michael-round2 and
        # whitney-round2 returned 502 from the router afterwards, with healthy pods behind a load
        # balancer that no longer existed, five days before Portland. Whatever the misclassification
        # was, an unverified empty list must not be able to reach a delete.
        local live_rc=0
        live="$(AWS_PROFILE="${acct}" aws eks list-clusters --region "${WIB_REGION}" \
                --query 'clusters[]' --output text | tr '\t' '\n')" || live_rc=$?
        if [[ "${live_rc}" -ne 0 ]]; then
            log "  reap-lbs: SKIPPING ${acct}: could not list its EKS clusters (exit ${live_rc})."
            log "            Without that list every tagged load balancer looks like an orphan."
            record_fail "reap-lbs:list-clusters-failed:${acct}"
            continue
        fi
        if [[ -z "${live//[[:space:]]/}" ]]; then
            log "  reap-lbs: SKIPPING ${acct}: it reports ZERO live EKS clusters."
            log "            That is either a genuinely empty account or a lying API, and the two are"
            log "            indistinguishable here. Sweep it with WIB_REAP_EMPTY_ACCOUNT=1 if the"
            log "            account really is empty and you have confirmed that by hand."
            [[ -n "${WIB_REAP_EMPTY_ACCOUNT:-}" ]] || continue
            log "            WIB_REAP_EMPTY_ACCOUNT=1 given; proceeding."
        fi
        arns="$(AWS_PROFILE="${acct}" aws elbv2 describe-load-balancers --region "${WIB_REGION}" \
                --query 'LoadBalancers[].LoadBalancerArn' --output text 2>/dev/null || true)"
        for arn in ${arns}; do
            tagged="$(AWS_PROFILE="${acct}" aws elbv2 describe-tags --region "${WIB_REGION}" --resource-arns "${arn}" \
                      --query "TagDescriptions[0].Tags[?Key=='elbv2.k8s.aws/cluster'].Value|[0]" --output text 2>/dev/null || true)"
            [[ -n "${tagged}" && "${tagged}" != "None" ]] || continue
            printf '%s\n' "${live}" | grep -qx "${tagged}" && continue
            total=$(( total + 1 ))
            log "  ORPHAN lb  ${acct}  ${arn##*/}  (cluster ${tagged} no longer exists)"
            if [[ -n "${WIB_APPLY:-}" ]]; then
                AWS_PROFILE="${acct}" aws elbv2 delete-load-balancer --region "${WIB_REGION}" \
                    --load-balancer-arn "${arn}" >/dev/null 2>&1 && swept=$(( swept + 1 ))
            fi
        done
        tgs="$(AWS_PROFILE="${acct}" aws elbv2 describe-target-groups --region "${WIB_REGION}" \
               --query 'TargetGroups[].TargetGroupArn' --output text 2>/dev/null || true)"
        for tg in ${tgs}; do
            tagged="$(AWS_PROFILE="${acct}" aws elbv2 describe-tags --region "${WIB_REGION}" --resource-arns "${tg}" \
                      --query "TagDescriptions[0].Tags[?Key=='elbv2.k8s.aws/cluster'].Value|[0]" --output text 2>/dev/null || true)"
            [[ -n "${tagged}" && "${tagged}" != "None" ]] || continue
            printf '%s\n' "${live}" | grep -qx "${tagged}" && continue
            total=$(( total + 1 ))
            log "  ORPHAN tg  ${acct}  ${tg##*/}  (cluster ${tagged} no longer exists)"
            [[ -n "${WIB_APPLY:-}" ]] && AWS_PROFILE="${acct}" aws elbv2 delete-target-group \
                --region "${WIB_REGION}" --target-group-arn "${tg}" >/dev/null 2>&1
        done
        # Volumes strand for the same reason: the EBS CSI controller dies with the cluster. These are
        # 'available' (detached) and tagged with the cluster that provisioned them.
        vols="$(AWS_PROFILE="${acct}" aws ec2 describe-volumes --region "${WIB_REGION}" \
                --filters Name=status,Values=available \
                --query 'Volumes[].[VolumeId,Tags[?starts_with(Key, `kubernetes.io/cluster/`)].Key|[0]]' \
                --output text 2>/dev/null || true)"
        while read -r vol key; do
            [[ -n "${vol}" && -n "${key}" && "${key}" != "None" ]] || continue
            printf '%s\n' "${live}" | grep -qx "${key#kubernetes.io/cluster/}" && continue
            total=$(( total + 1 ))
            log "  ORPHAN vol ${acct}  ${vol}  (cluster ${key#kubernetes.io/cluster/} no longer exists)"
            [[ -n "${WIB_APPLY:-}" ]] && AWS_PROFILE="${acct}" aws ec2 delete-volume \
                --region "${WIB_REGION}" --volume-id "${vol}" >/dev/null 2>&1
        done <<<"${vols}"
    done
    if [[ "${total}" -eq 0 ]]; then
        log "reap-lbs: no orphans across ${WIB_ATTENDEE_ACCOUNTS}"
    elif [[ -n "${WIB_APPLY:-}" ]]; then
        log "reap-lbs: found ${total} orphan(s), deleted ${swept} load balancer(s) + their target groups/volumes"
    else
        log "reap-lbs: found ${total} orphan(s). DRY-RUN; set WIB_APPLY=1 to delete."
    fi
    return 0
}

cmd_reap() {
    local keep_file=""
    while [[ $# -gt 0 ]]; do case "$1" in --keep) keep_file="${2:-}"; shift 2 ;; *) shift ;; esac; done
    [[ -n "${keep_file}" && -f "${keep_file}" ]] || { log "usage: reap --keep <file of cluster names to PRESERVE>  (WIB_APPLY=1 to destroy)"; exit 2; }
    require_tools
    mkdir -p "${LOG_DIR}"; rm -f "${LOG_DIR}/.failures"
    declare -A keep=()
    local line
    while IFS= read -r line; do line="${line//[$' \t\r']/}"; [[ "${line}" == watch-it-burn-* ]] && keep["${line}"]=1; done <"${keep_file}"
    log "reap: keeping ${#keep[@]} claimed cluster(s); scanning ${WIB_ATTENDEE_ACCOUNTS}"
    [[ -n "${WIB_APPLY:-}" ]] || log "DRY-RUN (set WIB_APPLY=1 to actually destroy)"
    local accounts; IFS=',' read -ra accounts <<<"${WIB_ATTENDEE_ACCOUNTS}"
    local acct live c
    for acct in "${accounts[@]}"; do
        acct="${acct// /}"; [[ -n "${acct}" ]] || continue
        # Unlike reap-lbs above, an empty list here is SAFE: it skips the account and destroys nothing.
        # It is still worth telling apart from a failed query, because "no attendee clusters" and "the
        # API did not answer" read identically in the log, and a cost reaper that quietly reaped nothing
        # is discovered on the invoice.
        local reap_rc=0
        live="$(AWS_PROFILE="${acct}" aws eks list-clusters --region "${WIB_REGION}" --query 'clusters[]' --output text | tr '\t' '\n' | grep -E '^watch-it-burn-attendee-')" || reap_rc=$?
        # grep exits 1 on no match, which is the genuinely-empty case; anything else is the query failing.
        if [[ "${reap_rc}" -gt 1 ]]; then
            log "  account '${acct}': could not list EKS clusters (exit ${reap_rc}); NOTHING reaped here"
            record_fail "reap:list-clusters-failed:${acct}"
            continue
        fi
        [[ -n "${live}" ]] || { log "  account '${acct}': no attendee clusters"; continue; }
        (
            read_vpc_for "${acct}"; TF_PROFILE="${acct}"
            local -a doomed=()
            for c in ${live}; do
                if [[ -n "${keep[${c}]:-}" ]]; then continue; fi
                if [[ -n "${WIB_APPLY:-}" ]]; then doomed+=("${c}"); else log "  would reap ${c} (${acct})"; fi
            done
            if [[ -n "${WIB_APPLY:-}" && "${#doomed[@]}" -gt 0 ]]; then
                log "  account '${acct}': reaping ${#doomed[@]} cluster(s) at ${MAX_PARALLEL}-way parallelism"
                run_pool down_one "${doomed[@]}"
            fi
        ) &
    done
    wait
    report_failures >&2 || true
}

# Push one converged cluster's full row into the live provisioning pool via /admin/import: harvest the
# console NLB, read the boot-persisted AWS creds, look up the per-student Datadog org by slot (same index
# as bootstrap + merge_pool). No CSV rebuild, no redeploy. POOL1/POOL2 are preloaded by cmd_ingest.
ingest_one() {
    local name="$1" acct_profile="$2"
    # A roster entry with no state file was never provisioned, so there is no console to wait for and
    # nothing to register. Say so and move on: without this, `ingest-instructors` over the full nine-entry
    # roster spends the whole LB wait budget on each of the clusters that do not exist.
    if [[ ! -f "${STATE_DIR}/${name}.tfstate" ]]; then
        log "  ingest ${name}: not provisioned, nothing to register"
        return 0
    fi
    local kcfg; kcfg="$(mktemp -t "${name}.ing.XXXX")"
    provider_write_kubeconfig "${name}" "${kcfg}" "${acct_profile}"
    # WAIT for the console NLB rather than skipping on the first look. Ingest runs immediately after a
    # provision, which is exactly when a freshly created load balancer has no hostname yet, so a single
    # check meant the clusters most likely to need registering were the ones most likely to be skipped.
    # A cluster that genuinely does not exist falls through after the budget and is reported, which is
    # the correct outcome for a roster entry that was never provisioned.
    local console_host="" waited=0
    while [[ "${waited}" -lt "${WIB_INGEST_LB_WAIT:-120}" ]]; do
        console_host="$(KUBECONFIG="${kcfg}" kubectl -n agent get svc console -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)"
        [[ -n "${console_host}" ]] && break
        sleep 10; waited=$(( waited + 10 ))
    done
    # kcfg deliberately stays alive past this point. The terminal credential below is read from the
    # LIVE Secret rather than the local cache file, so every exit path from here removes it explicitly.
    [[ -n "${console_host}" ]] || { rm -f "${kcfg}"; log "  ingest ${name}: console NLB not ready after ${waited}s; skip"; record_fail "ingest:${name}"; return; }
    local ak sk
    ak="$(tail -n +2 "${AWS_POOL_DIR}/${name}.csv" 2>/dev/null | head -1 | cut -d, -f3)"
    sk="$(tail -n +2 "${AWS_POOL_DIR}/${name}.csv" 2>/dev/null | head -1 | cut -d, -f4)"
    [[ -n "${ak}" && -n "${sk}" ]] || { rm -f "${kcfg}"; log "  ingest ${name}: no persisted AWS creds (${AWS_POOL_DIR}/${name}.csv); skip"; record_fail "ingest:${name}"; return; }
    # Datadog org resolution differs by cluster KIND, and getting this wrong is why instructor clusters
    # could not be ingested at all. An attendee cluster resolves by slot: watch-it-burn-attendee-007
    # takes the 7th NON-admin pool entry, matching bootstrap + merge_pool. An instructor cluster
    # (watch-it-burn-r<round>-<n>) has no slot number in that sequence, so the sed below produced an
    # empty slot, the lookup was skipped, and the row went out with every Datadog field blank.
    # Instructor clusters all share the single admin-instructor org, so select it by ROLE, not index.
    local slot dd="{}"
    slot="$(printf '%s' "${name}" | sed -n "s/^${NAME_PREFIX}-0*\([0-9][0-9]*\)$/\1/p")"
    if [[ -n "${slot}" ]]; then
        dd="$(jq -cn --argjson a "${POOL1}" --argjson b "${POOL2}" --argjson i "$(( slot - 1 ))" \
            '(([$a[],$b[]]|map(select((.role//"")|startswith("admin")|not)))[$i]) // {} | {org:(.org//""),email:(.email//""),password:(.password//""),api:(.["api-key"]//""),app:(.["app-key"]//""),site:(.site//"datadoghq.com")}' 2>/dev/null)"
    elif is_instructor_name "${name}"; then
        dd="$(jq -cn --argjson a "${POOL1}" --argjson b "${POOL2}" \
            '(([$a[],$b[]]|map(select((.role//"")=="admin-instructor"))[0]) // {}) | {org:(.org//""),email:(.email//""),password:(.password//""),api:(.["api-key"]//""),app:(.["app-key"]//""),site:(.site//"datadoghq.com")}' 2>/dev/null)"
    fi
    [[ -n "${dd}" ]] || dd='{}'   # never let an empty resolver result reach --argjson
    # ttyd now REFUSES anonymous access (terminal-auth secret), so a row without the terminal password
    # hands the student a console URL and a login box they cannot satisfy. bootstrap_terminal_auth
    # persists the password beside the AWS creds; send it. The provisioning app already accepts
    # terminal_user/terminal_password (scripts/merge_pool.py in provisioning-agenticburn) and shows a
    # visible degradation when the password is absent, so an empty value is reported rather than silent.
    # Username comes from the SAME role split the bootstrap used (#109), never a fleet-wide constant:
    # reporting `sprouts` for an attendee cluster whose Secret says `agentic` hands the student a login
    # that cannot work.
    # READ THE LIVE SECRET, not the local cache file. The cluster enforces whatever TTYD_CREDENTIAL
    # says, so that Secret is the only thing entitled to define the credential we hand a student.
    #
    # This previously took the username from terminal_creds_for and the password from
    # ${name}.terminal, which are two different sources that nothing reconciled. The cache file is
    # written by bootstrap_terminal_auth, so it only tracks the cluster while bootstrap keeps running;
    # a cluster re-secreted afterwards left the file stale with nothing to correct it. Measured
    # 2026-09-03: attendee-001 and attendee-002 cached "sprouts" while both clusters enforced
    # agentic:agentic, so the success page displayed agentic / sprouts. Whitney hit it in a walkthrough
    # and got in only by guessing the password. Deriving BOTH halves from the Secret makes the
    # displayed credential wrong only if the cluster itself is wrong.
    local term_user term_pw live_cred
    live_cred="$(KUBECONFIG="${kcfg}" AWS_PROFILE="${acct_profile}" kubectl -n agent get secret terminal-auth \
        -o jsonpath='{.data.TTYD_CREDENTIAL}' 2>/dev/null | base64 -d 2>/dev/null || true)"
    rm -f "${kcfg}"
    if [[ "${live_cred}" == *:* ]]; then
        term_user="${live_cred%%:*}"; term_pw="${live_cred#*:}"
        # Self-heal the cache so anything still reading the file agrees with the cluster.
        mkdir -p "${AWS_POOL_DIR}"; printf '%s\n' "${term_pw}" >"${AWS_POOL_DIR}/${name}.terminal"
        chmod 600 "${AWS_POOL_DIR}/${name}.terminal"
    else
        # Fall back to the role split plus the cache only when the Secret cannot be read at all (an
        # unreachable API server), and say so, because this is the path that can be stale.
        term_user="$(terminal_creds_for "${name}")"; term_user="${term_user%%:*}"
        term_pw="$(head -1 "${AWS_POOL_DIR}/${name}.terminal" 2>/dev/null | tr -d '[:space:]')"
        term_pw="${term_pw##*:}"   # tolerate either a bare password or a "user:password" pair
        log "  ingest ${name}: WARN could not read terminal-auth from the cluster; falling back to the cached password, which may be stale"
    fi
    [[ -n "${term_pw}" ]] || log "  ingest ${name}: WARN no terminal password; the terminal will prompt and the student cannot log in"
    # The URL the student is actually handed. Two changes from the raw "http://<elb-hostname>" this used
    # to send (#142, #139):
    #   * the MEMORABLE hostname, computed by the same public_host_for() the routes table uses, so the
    #     router publishes and provisioning hands out the same name rather than two different answers;
    #   * https, because the console now terminates TLS. Handing out an http:// link would have quietly
    #     undone the encrypted hop for anyone who followed it.
    # Falls back to the raw console host if no public name resolves, so a cluster still reaches its
    # student rather than being unreachable because a name lookup failed.
    local pub_host; pub_host="$(public_host_for "${name}" "${owner:-}")"
    local console_url="https://${pub_host}"
    [[ -n "${pub_host}" ]] || console_url="https://${console_host}"
    local row; row="$(jq -cn --arg n "${name}" --arg r "${WIB_REGION}" --arg ak "${ak}" --arg sk "${sk}" --arg cu "${console_url}" --arg tu "${term_user}" --arg tp "${term_pw}" --argjson dd "${dd}" \
        '($dd.site // "datadoghq.com") as $site
         | ($site | if . == "datadoghq.com" or . == "datadoghq.eu" then "https://app." + . else "https://" + . end) as $ddurl
         | {name:$n,region:$r,access_key:$ak,secret_key:$sk,console_url:$cu,terminal_user:$tu,terminal_password:$tp,datadog_org:($dd.org//""),datadog_email:($dd.email//""),datadog_password:($dd.password//""),datadog_api_key:($dd.api//""),datadog_app_key:($dd.app//""),datadog_site:$site,datadog_dashboard_url:$ddurl}')"
    # Retry the POST. A single transient failure used to leave one cluster unregistered and everything
    # else looking fine, which is how watch-it-burn-r3-1 ended up missing from provisioning on
    # 2026-08-26 while the other five succeeded. One HTTP blip should not require a human to notice.
    local tok attempt code=""
    tok="$(resolve_admin_token || true)"
    for attempt in 1 2 3; do
        code="$(curl -s -X POST "${WIB_PROVISIONING_URL%/}/admin/import" -H "X-Admin-Token: ${tok}" \
            -H "Content-Type: application/json" --data "{\"clusters\":[${row}]}" \
            --max-time 25 -o /dev/null -w '%{http_code}' 2>/dev/null)"
        [[ "${code}" == "200" ]] && break
        [[ "${attempt}" -lt 3 ]] && sleep $(( attempt * 5 ))
    done
    if [[ "${code}" == "200" ]]; then
        log "  ingested: ${name}"
    else
        log "  ingest POST failed: ${name} (last status ${code:-none} after 3 attempts)"; record_fail "ingest:${name}"
    fi
}

# Harvest + push the fleet (or explicit names) into the live provisioning pool. Numeric arg = per-account
# count form (honors WIB_NAME_OFFSET + WIB_ATTENDEE_ACCOUNTS); otherwise explicit cluster names (default account).
cmd_ingest() {
    [[ $# -ge 1 ]] || { log "usage: ingest <clusters-per-account> | ingest <cluster-name...>"; exit 2; }
    resolve_admin_token >/dev/null 2>&1 || { log "cannot resolve the provisioning admin token (railway login, or export WIB_ADMIN_TOKEN)"; exit 1; }
    require_tools; mkdir -p "${LOG_DIR}"; rm -f "${LOG_DIR}/.failures"
    POOL1="$(AWS_PROFILE="${WIB_DEFAULT_ACCOUNT}" aws secretsmanager get-secret-value --secret-id watch-it-burn/datadog-pool   --region "${WIB_REGION}" --query SecretString --output text 2>/dev/null || echo '[]')"
    POOL2="$(AWS_PROFILE="${WIB_DEFAULT_ACCOUNT}" aws secretsmanager get-secret-value --secret-id watch-it-burn/datadog-pool-2 --region "${WIB_REGION}" --query SecretString --output text 2>/dev/null || echo '[]')"
    log "ingest -> ${WIB_PROVISIONING_URL%/}/admin/import"
    if [[ "$1" =~ ^[0-9]+$ ]]; then
        local per_account="$1" accounts idx=0 acct start n name
        IFS=',' read -ra accounts <<<"${WIB_ATTENDEE_ACCOUNTS}"
        for acct in "${accounts[@]}"; do
            acct="${acct// /}"; [[ -n "${acct}" ]] || continue
            start=$(( WIB_NAME_OFFSET + idx * per_account + 1 )); idx=$(( idx + 1 ))
            for n in $(seq "${start}" $(( start + per_account - 1 ))); do
                ingest_one "$(printf '%s-%03d' "${NAME_PREFIX}" "${n}")" "${acct}"
            done
        done
    else
        # Named clusters. A roster cluster lives in its round's account, which is NOT necessarily the
        # default one; passing WIB_DEFAULT_ACCOUNT for everything made `ingest watch-it-burn-r2-1` look
        # up the wrong account and fail to find the cluster whenever the R1/R2/R3 split is in use.
        local name rnd acct
        for name in "$@"; do
            rnd="$(round_of_instructor_name "${name}")"
            if [[ -n "${rnd}" ]]; then acct="$(account_for_round "${rnd}")"; else acct="${WIB_DEFAULT_ACCOUNT}"; fi
            ingest_one "${name}" "${acct}"
        done
    fi
    report_failures
}

# Every roster cluster in one call, mirroring `instructors up`. Without this the only way to register
# the instructor set was to type six names, so in practice it never happened and the presenters' own
# clusters were missing from provisioning entirely.
cmd_ingest_instructors() {
    local round_filter="${1:-}" entry name rnd
    load_roster
    for entry in "${INSTRUCTORS[@]}"; do
        IFS='|' read -r name rnd _tier _it _pid _bp _owner <<<"${entry}"
        [[ -n "${round_filter}" && "${rnd}" != "${round_filter}" ]] && continue
        ingest_one "${name}" "$(account_for_round "${rnd}")"
    done
}

# Account-aware selective teardown: destroy the named clusters in ONE specific account. Reuses the
# tested read_vpc_for + down_one path so it works for the student accounts (whose VPC/profile the plain
# 'down' does not resolve). Use to tear down most of a fleet while keeping a few (e.g. the 2 admin
# attendee clusters): down-acct accen-dev <names...>  /  down-acct aws1-student31 <names...>.
cmd_down_acct() {
    local profile="${1:-}"; shift || true
    [[ -n "${profile}" && $# -ge 1 ]] || { log "usage: down-acct <profile> <cluster-name...>"; exit 2; }
    require_tools; mkdir -p "${LOG_DIR}"; rm -f "${LOG_DIR}/.failures"
    terraform -chdir="${CLUSTER_DIR}" init -input=false >/dev/null
    read_vpc_for "${profile}"
    TF_PROFILE="${profile}"
    require_apply "down-acct ${profile}" "$@" || return 0
    log "down-acct ${profile}: destroying $# clusters (max ${MAX_PARALLEL} parallel)..."
    run_pool down_one "$@"
    report_failures
}

# Auto-generate the agenticburn.com wildcard-router map (railway/apex/routes.map) from LIVE cluster
# console LBs, then commit + push so the apex Railway service redeploys and every friendly
# *.agenticburn.com URL resolves. This replaces hand-editing routes.map / ADMIN_CLUSTERS: the friendly
# hostnames are STABLE (set once in ADMIN_CLUSTERS), only this host->LB map is dynamic. cmd_up_fleet and
# cmd_instructors call this automatically after a provision; run standalone with 'fleet.sh routes'.
# Friendly hosts: instructor watch-it-burn-r1-1 -> r1-1.agenticburn.com (+ roundN -> first live spare of
# round N); admin attendee watch-it-burn-attendee-001 -> a-001.agenticburn.com. The 250 pool attendees
# reach their cluster via the raw console NLB the provisioning app hands out, so they need no router line.
cmd_routes() {
    require_tools
    local out="${WIB_APEX_DIR}/routes.map"
    local kcfg tmp; kcfg="$(mktemp -t routes.XXXX)"; tmp="$(mktemp -t routesmap.XXXX)"
    {
        echo "# ABOUTME: Host -> cluster LB routing for the agenticburn.com wildcard router."
        echo "# ABOUTME: AUTO-GENERATED by 'fleet.sh routes' from live cluster LBs. Do not hand-edit."
    } > "${tmp}"
    local entry name rr bp acct h short n state
    local -A round_done=()
    for entry in "${INSTRUCTORS[@]}"; do
        IFS='|' read -r name rr _tier _it _pid bp owner <<<"${entry}"
        acct="$(account_for_round "${rr}")"
        provider_write_kubeconfig "${name}" "${kcfg}" "${acct}" || continue
        h="$(KUBECONFIG="${kcfg}" kubectl -n agent get svc console -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)"
        [[ -n "${h}" ]] || { log "  routes: ${name} console LB not ready, skipping"; continue; }
        # The name a presenter actually reads: <owner>-round<N>.agenticburn.com. The r1-1 form is a
        # provisioning artefact, not a name anyone can hold in their head mid-demo, and it says nothing
        # about whose cluster it is.
        #
        # Upstreams are :443 (#139). The cluster console terminates TLS with a cert-manager self-signed
        # certificate and the router connects with tls_insecure_skip_verify, so the Railway-to-AWS hop is
        # encrypted. It carries every attendee prompt and the terminal I/O, and used to cross the public
        # NO SCHEME in the table, only host:443. Caddy cannot parse a scheme out of a PLACEHOLDER upstream
        # at request time, so emitting "https://<lb>:443" here made every cluster route 502 while the router
        # itself stayed healthy (verified live 2026-08-31: the LB answered 200 on both ports directly, and
        # provisioning/start/apex kept serving). TLS is declared statically in the apex Caddyfile transport
        # instead. The two sides must therefore move TOGETHER: :443 here requires the TLS transport there.
        # Single label, deliberately. The certificate is *.agenticburn.com, which covers exactly one
        # level, so michael-round1.agenticburn.com validates and roundone.michael.agenticburn.com does
        # not: it fails the TLS handshake outright rather than warning. Verified 2026-08-27.
        [[ -n "${owner}" ]] && printf '%s-round%s.agenticburn.com  %s:443\n' "${owner}" "${rr}" "${h}" >> "${tmp}"
        # The raw "r1-1" alias is NO LONGER emitted (#142). Nothing functional pointed at it: every hit in
        # the three repos was either a cluster NAME (which is unchanged) or a comment recording where
        # something was observed. BurritoBot's roundOf() matches michael-round2 / round2 / r2-1 from one
        # regex, so dropping the form it no longer sees breaks nothing.
        # roundN is the shared, owner-less alias the run-of-show and the BurritoBot round selector use.
        # Bind it to the FIRST owner's cluster so it is stable rather than whichever entry sorted first.
        [[ -z "${round_done[$rr]:-}" && "${owner}" == "${WIB_PRIMARY_OWNER}" ]] && {
            printf 'round%s.agenticburn.com  %s:443\n' "${rr}" "${h}" >> "${tmp}"; round_done[$rr]=1; }
    done
    # Admin attendee clusters (attendee-NNN with state in the default account) -> a-NNN.agenticburn.com.
    if [[ -d "${STATE_DIR}" ]]; then
        for state in "${STATE_DIR}"/${NAME_PREFIX}-*.tfstate; do
            [[ -e "${state}" ]] || continue
            name="$(basename "${state}" .tfstate)"; n="${name##*-}"
            provider_write_kubeconfig "${name}" "${kcfg}" "${WIB_DEFAULT_ACCOUNT}" || continue
            h="$(KUBECONFIG="${kcfg}" kubectl -n agent get svc console -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)"
            [[ -n "${h}" ]] || continue
            # Memorable name first: this is the one the student is given (#142). "brave-badger" survives
            # being read to a room and typed from memory; "a-042" and a raw ELB hostname do not.
            printf '%s  %s:443\n' "$(public_host_for "${name}")" "${h}" >> "${tmp}"
            # a-NNN stays as an ALIAS only, so a link handed out before the rename still resolves. It is
            # not what anyone is told any more.
            printf 'a-%s.agenticburn.com  %s:443\n' "${n}" "${h}" >> "${tmp}"
        done
    fi
    rm -f "${kcfg}"

    # NEVER SHRINK THE TABLE SILENTLY. This regenerates from whatever roster is loaded and from whichever
    # consoles happen to have an LB right now, so a scoped run, or a run made while LBs are still coming
    # up, produces a SMALLER table than the one already published. Publishing that takes every host it
    # omits to a 404. It has happened: a subset run on 2026-08-26 rewrote the table from three clusters
    # and took two live round URLs down. The published table is the thing to compare against, not the
    # working copy, because the working copy may already be a bad render from a previous attempt.
    local new_count old_count
    new_count="$(grep -c agenticburn.com "${tmp}" || true)"
    old_count="$(git -C "${WIB_APEX_DIR}" show HEAD:"$(basename "${out}")" 2>/dev/null | grep -c agenticburn.com || true)"
    if [[ -z "${WIB_ROUTES_ALLOW_SHRINK:-}" && "${new_count}" -lt "${old_count}" ]]; then
        log "routes: REFUSING to publish ${new_count} host(s), down from ${old_count} already published."
        log "        Hosts that would be dropped:"
        comm -13 <(grep -o '^[^ ]*\.agenticburn\.com' "${tmp}" | sort) \
                 <(git -C "${WIB_APEX_DIR}" show HEAD:"$(basename "${out}")" 2>/dev/null | grep -o '^[^ ]*\.agenticburn\.com' | sort) \
            | sed 's/^/          - /' >&2
        log "        Every one of those becomes a 404. If the shrink is intended (a teardown), re-run"
        log "        with WIB_ROUTES_ALLOW_SHRINK=1. Otherwise wait for the missing consoles and retry."
        rm -f "${tmp}"
        return 1
    fi

    mv "${tmp}" "${out}"
    local lines; lines="${new_count}"
    log "routes: wrote ${lines} host(s) to ${out##*/} (apex repo)"
    if git -C "${WIB_APEX_DIR}" diff --quiet -- "${out}"; then
        log "routes: no change to the table"
    else
        # Commit and push for the RECORD ONLY. This does not apply anything, which is the whole point
        # of the next step.
        git -C "${WIB_APEX_DIR}" add "${out}"
        git -C "${WIB_APEX_DIR}" commit -q -m "routes: regenerate agenticburn.com router map from live fleet (${lines} hosts)" || true
        git -C "${WIB_APEX_DIR}" push origin HEAD 2>&1 | tail -1 || log "routes: apex push to current branch failed"
        git -C "${WIB_APEX_DIR}" push origin HEAD:main 2>&1 | tail -1 || log "routes: could not ff apex main; run 'git -C ${WIB_APEX_DIR} push origin <branch>:main'"
    fi

    # APPLY the table. Pushing is not applying, and assuming otherwise cost a live outage.
    #
    # The apex router keeps its routing table on a persistent volume so a route change can land as a
    # Caddy reload rather than a redeploy that restarts the router every attendee is being proxied
    # through. Its entrypoint therefore keeps the volume's existing table and DELIBERATELY IGNORES the
    # one baked into a new image; it prints a warning saying exactly that. So a commit-and-push leaves
    # the live router serving whatever it was serving before.
    #
    # Observed 2026-08-26: routes.map was correct and pushed to the branch Railway deploys from, and all
    # nine attendee URLs still returned 404 until the table was reloaded by hand.
    #
    # Failure here is loud but non-fatal: an unapplied table is recoverable in one command, whereas
    # aborting a provision because the router is unreachable is not what anyone wants mid-run. If the
    # reload is rejected the router keeps serving the previous table, which is the property that makes
    # this safe to call automatically.
    local reload="${WIB_APEX_DIR}/scripts/reload-routes.sh"
    if [[ -x "${reload}" ]]; then
        log "routes: applying the table to the live router (reload, no redeploy)"
        if bash "${reload}" "${out}" 2>&1 | sed 's/^/    /' >&2; then
            log "routes: applied"
        else
            log "routes: RELOAD FAILED. The table is committed but NOT live; the router is still serving"
            log "        the previous one. Apply it with: bash ${reload}"
            record_fail "routes:reload-failed"
        fi
    else
        log "routes: WARNING no reload script at ${reload}, so the table is NOT live."
        log "        Pushing alone does not apply routes: the router keeps the table on its volume."
    fi
}

main() {
    local cmd="${1:-}"; shift || true
    load_roster   # populate INSTRUCTORS for every command (routes/reap/hints), not just cmd_instructors
    case "${cmd}" in
        up) cmd_up "$@" ;;
        routes) cmd_routes "$@" ;;
        preflight) exec "${SCRIPT_DIR}/preflight.sh" "$@" ;;
        check-tls) exec "${SCRIPT_DIR}/check-tls.sh" "$@" ;;
        up-fleet) cmd_up_fleet "$@" ;;
        down) cmd_down "$@" ;;
        down-acct) cmd_down_acct "$@" ;;
        down-fleet) cmd_down_fleet "$@" ;;
        health) cmd_health "$@" ;;
        converge) cmd_converge "$@" ;;
        harvest) cmd_harvest "$@" ;;
        ingest) cmd_ingest "$@" ;;
        ingest-instructors)
            resolve_admin_token >/dev/null 2>&1 || { log "cannot resolve the provisioning admin token (railway login, or export WIB_ADMIN_TOKEN)"; exit 1; }
            require_tools; mkdir -p "${LOG_DIR}"; rm -f "${LOG_DIR}/.failures"
            POOL1="$(AWS_PROFILE="${WIB_DEFAULT_ACCOUNT}" aws secretsmanager get-secret-value --secret-id watch-it-burn/datadog-pool   --region "${WIB_REGION}" --query SecretString --output text 2>/dev/null || echo '[]')"
            POOL2="$(AWS_PROFILE="${WIB_DEFAULT_ACCOUNT}" aws secretsmanager get-secret-value --secret-id watch-it-burn/datadog-pool-2 --region "${WIB_REGION}" --query SecretString --output text 2>/dev/null || echo '[]')"
            log "ingest -> ${WIB_PROVISIONING_URL%/}/admin/import"
            cmd_ingest_instructors "$@"; report_failures ;;
        aws-keys) cmd_aws_keys "$@" ;;
        reap-lbs) cmd_reap_lbs ;;
        reap) cmd_reap "$@" ;;
        status) cmd_status "$@" ;;
        instructors) cmd_instructors "$@" ;;
        *) usage ;;
    esac
}

main "$@"
