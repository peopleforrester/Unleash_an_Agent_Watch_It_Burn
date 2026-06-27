#!/usr/bin/env bash
# ABOUTME: Fleet driver. Stamps out N attendee clusters from the cluster/ module against the
# ABOUTME: shared lab VPC, each with its own state, concurrency-capped, parallel. (Packt-modeled.)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROVISION_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly SCRIPT_DIR PROVISION_DIR
readonly CLUSTER_DIR="${PROVISION_DIR}/cluster"
readonly LAB_VPC_DIR="${PROVISION_DIR}/lab-vpc"
readonly STATE_DIR="${SCRIPT_DIR}/states"
readonly LOG_DIR="${SCRIPT_DIR}/logs"
readonly NAME_PREFIX="watch-it-burn-attendee"
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
# Attendee fleet accounts for `up-fleet` (comma-separated AWS profiles). The 250-cluster plan is 5
# accounts x 50 clusters; up-fleet provisions every account's slice CONCURRENTLY so the whole fleet
# comes up in one window instead of N serial batches. Each account needs its own lab-vpc applied to
# states/<profile>.tfstate first. Disjoint name ranges keep state files from colliding. All five
# accounts are stood up (lab-vpc applied 2026-06-27); profiles live in ~/.aws (us-west-2). Per-account
# ALB/NLB->100 + vCPU->800 quota increases submitted 2026-06-27 and must be APPROVED before a full
# 50/account run (each cluster = 1 ALB + 1 NLB; default cap is 50).
WIB_ATTENDEE_ACCOUNTS="${WIB_ATTENDEE_ACCOUNTS:-accen-dev,aws1-student31,aws1-student32,aws1-student33,aws1-student34}"

# --- Instructor roster: 9 fixed clusters, 3 per round. "name|round|bootstrap-profile" -----------
# These are facilitator-run and NOT in the attendee pool. fleet.sh PROVISIONS them; deploy-full-idp.sh
# BOOTSTRAPS them with the listed profile (burn = Round-1 no-guardrails subset; full = everything).
#   R1 (burn): the fork bomb destroys these -> one live + two spares, router rotates burn.agenticburn.com
#   R2 (full): infra guardrails on (wall.agenticburn.com); spares / parallel stations
#   R3 (full): the cost-race tiers. NAMES are the Bedrock model tiers, but the MODEL is set per cluster
#     in the gitops kagent ModelConfig, NOT here. Default workshop model is Sonnet; the tier demo is
#     optional (see haiku/sonnet/opus). If we drop tiers, rename these to sonnet-1/2/3.
INSTRUCTORS=(
  "watch-it-burn-burn-1|1|burn"
  "watch-it-burn-burn-2|1|burn"
  "watch-it-burn-burn-3|1|burn"
  "watch-it-burn-wall-1|2|full"
  "watch-it-burn-wall-2|2|full"
  "watch-it-burn-wall-3|2|full"
  "watch-it-burn-haiku|3|full"
  "watch-it-burn-sonnet|3|full"
  "watch-it-burn-opus|3|full"
)

# When non-empty, up_one/down_one target this AWS profile (account). Empty = module default account.
TF_PROFILE=""

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

account_for_round() {
    case "$1" in
        1) printf '%s' "${WIB_ACCOUNT_R1}" ;;
        2) printf '%s' "${WIB_ACCOUNT_R2}" ;;
        3) printf '%s' "${WIB_ACCOUNT_R3}" ;;
        *) log "bad round: $1"; exit 1 ;;
    esac
}

log() { printf '%s\n' "$*" >&2; }

usage() {
    cat >&2 <<EOF
Usage: ${0##*/} <up|down|status|instructors> [count|names...|<up|down> [round]]

  ATTENDEE clusters (numbered, pool-distributed, single account):
    up <count>        Provision watch-it-burn-attendee-001 .. -<count> (or pass explicit names).
    up <name...>      Provision the named clusters.
    up-fleet <n>      Provision <n> clusters in EACH \${WIB_ATTENDEE_ACCOUNTS} account, all concurrent
                      (disjoint name ranges). The 250-cluster path: 5 accounts x 50 in one window.
    down <count|all>  Destroy the first <count>, or all clusters with state.
    down <name...>    Destroy the named clusters.
    status            List clusters that have state and their EKS status.

  INSTRUCTOR clusters (9 fixed: 3 per round, NOT in the attendee pool):
    instructors up [round]    Provision the roster (optionally just round 1|2|3).
    instructors down [round]  Destroy the roster (optionally one round).
    Round->account split (avoids per-account overload): R1=\${WIB_ACCOUNT_R1}, R2=\${WIB_ACCOUNT_R2},
    R3=\${WIB_ACCOUNT_R3}. Override via those env vars. Each account needs its own lab-vpc applied to
    states/<profile>.tfstate first (the command prints the exact apply line if missing).

Provisioning AUTO-BOOTSTRAPS the IDP after each cluster comes up (deploy-full-idp.sh): attendees +
R2/R3 instructors with the 'full' profile, R1 instructors with 'burn'. The provision pool runs the
provision and the bootstrap together, so a fleet 'up' self-completes. Set WIB_NO_BOOTSTRAP=1 to
provision bare clusters only (then bootstrap manually; instructor hints print after a bare 'up').
Per-branch clusters (a cluster tracking its own branch) are a manual case: bootstrap from that branch.

Attendee path reads the shared VPC from ../lab-vpc (must be applied first). Each cluster gets its own
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
bootstrap_one() {
    local name="$1" profile="$2"
    local prof="${TF_PROFILE:-accen-dev}"
    local kcfg; kcfg="$(mktemp -t "${name}.kcfg.XXXX")"
    AWS_PROFILE="${prof}" aws eks update-kubeconfig --kubeconfig "${kcfg}" \
        --name "${name}" --region "${WIB_REGION}" >/dev/null 2>&1
    if KUBECONFIG="${kcfg}" AWS_PROFILE="${prof}" \
        bash "${PROVISION_DIR}/deploy-full-idp.sh" "${profile}" \
        >"${LOG_DIR}/${name}.bootstrap.log" 2>&1; then
        log "  bootstrapped: ${name} (${profile})"
    else
        log "  BOOTSTRAP FAILED: ${name} (see ${LOG_DIR}/${name}.bootstrap.log)"; record_fail "${name}"
    fi
    rm -f "${kcfg}"
}

up_one() {
    local name="$1"; assert_ours "${name}"
    local prof=(); [[ -n "${TF_PROFILE}" ]] && prof=(-var "profile=${TF_PROFILE}" -var "region=${WIB_REGION}")
    local pids=(); [[ -n "${TF_PIDS_LIMIT}" ]] && pids=(-var "pod_pids_limit=${TF_PIDS_LIMIT}")
    if terraform -chdir="${CLUSTER_DIR}" apply -auto-approve -no-color \
        -state="${STATE_DIR}/${name}.tfstate" \
        -var "name=${name}" -var "vpc_id=${VPC_ID}" \
        -var "private_subnet_ids=${SUBNETS_JSON}" "${prof[@]}" "${pids[@]}" \
        >"${LOG_DIR}/${name}.apply.log" 2>&1; then
        log "  ok: ${name}"
        # Auto-bootstrap the IDP unless this provision is bare-only.
        [[ -n "${BOOTSTRAP_PROFILE}" ]] && bootstrap_one "${name}" "${BOOTSTRAP_PROFILE}"
    else
        log "  FAILED: ${name} (see ${LOG_DIR}/${name}.apply.log)"; record_fail "${name}"
    fi
}

down_one() {
    local name="$1"; assert_ours "${name}"
    [[ -f "${STATE_DIR}/${name}.tfstate" ]] || { log "  no state for ${name}, skipping"; return 0; }
    local prof=(); [[ -n "${TF_PROFILE}" ]] && prof=(-var "profile=${TF_PROFILE}" -var "region=${WIB_REGION}")
    if terraform -chdir="${CLUSTER_DIR}" destroy -auto-approve -no-color \
        -state="${STATE_DIR}/${name}.tfstate" \
        -var "name=${name}" -var "vpc_id=${VPC_ID}" \
        -var "private_subnet_ids=${SUBNETS_JSON}" "${prof[@]}" \
        >"${LOG_DIR}/${name}.destroy.log" 2>&1; then
        rm -f "${STATE_DIR}/${name}.tfstate"; log "  ok: ${name}"
    else
        log "  FAILED: ${name} (see ${LOG_DIR}/${name}.destroy.log)"; record_fail "${name}"
    fi
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

cmd_up() {
    [[ $# -ge 1 ]] || usage
    require_tools
    mkdir -p "${STATE_DIR}" "${LOG_DIR}"
    rm -f "${LOG_DIR}/.failures"
    read_vpc
    log "init cluster module..."
    terraform -chdir="${CLUSTER_DIR}" init -input=false >/dev/null
    local names; mapfile -t names < <(expand_names "$@")
    log "provisioning ${#names[@]} clusters (max ${MAX_PARALLEL} parallel)..."
    # Attendee clusters bootstrap with the full profile unless WIB_NO_BOOTSTRAP=1 (bare provision).
    [[ -n "${WIB_NO_BOOTSTRAP:-}" ]] || BOOTSTRAP_PROFILE="full"
    run_pool up_one "${names[@]}"
    BOOTSTRAP_PROFILE=""
    report_failures
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
    rm -f "${LOG_DIR}/.failures"
    log "destroying ${#names[@]} clusters (max ${MAX_PARALLEL} parallel)..."
    run_pool down_one "${names[@]}"
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
    local round_filter="${1:-}" entry name rr bp
    log "next: bootstrap each (fleet.sh provisions; deploy-full-idp.sh bootstraps):"
    for entry in "${INSTRUCTORS[@]}"; do
        IFS='|' read -r name rr bp <<<"${entry}"
        [[ -n "${round_filter}" && "${round_filter}" != "${rr}" ]] && continue
        log "  ${name}: AWS_PROFILE=$(account_for_round "${rr}") KUBECONFIG=<isolated> deploy-full-idp.sh ${bp}"
    done
}

# Provision/destroy the fixed instructor roster, grouped by round so each account's VPC is read once.
cmd_instructors() {
    local action="${1:-}" round_filter="${2:-}"
    case "${action}" in up|down) ;; status) cmd_status; return ;; *) usage ;; esac
    require_tools
    mkdir -p "${STATE_DIR}" "${LOG_DIR}"; rm -f "${LOG_DIR}/.failures"
    terraform -chdir="${CLUSTER_DIR}" init -input=false >/dev/null
    local r acct entry name rr bp names
    for r in 1 2 3; do
        [[ -n "${round_filter}" && "${round_filter}" != "${r}" ]] && continue
        names=()
        for entry in "${INSTRUCTORS[@]}"; do
            IFS='|' read -r name rr bp <<<"${entry}"
            [[ "${rr}" == "${r}" ]] && names+=("${name}")
        done
        [[ "${#names[@]}" -gt 0 ]] || continue
        acct="$(account_for_round "${r}")"
        log "round ${r} instructors -> account '${acct}': ${names[*]}"
        read_vpc_for "${acct}"
        TF_PROFILE="${acct}"
        # Round 1 burn clusters provision with NO per-pod PID cap so the fork bomb lands (the burn).
        [[ "${r}" == "1" ]] && TF_PIDS_LIMIT="-1" || TF_PIDS_LIMIT=""
        # Auto-bootstrap: Round 1 = burn (no guardrails), R2/R3 = full. Skipped if WIB_NO_BOOTSTRAP=1.
        if [[ "${action}" == "up" && -z "${WIB_NO_BOOTSTRAP:-}" ]]; then
            BOOTSTRAP_PROFILE=$([[ "${r}" == "1" ]] && echo burn || echo full)
        fi
        if [[ "${action}" == "up" ]]; then run_pool up_one "${names[@]}"; else run_pool down_one "${names[@]}"; fi
        TF_PROFILE=""; TF_PIDS_LIMIT=""; BOOTSTRAP_PROFILE=""
    done
    report_failures
    # Print manual-bootstrap hints only when auto-bootstrap was skipped.
    [[ "${action}" == "up" && -n "${WIB_NO_BOOTSTRAP:-}" ]] && print_bootstrap_hints "${round_filter}"
}

# Provision the attendee fleet across WIB_ATTENDEE_ACCOUNTS concurrently: one per-account pool per
# account, all running at once, with disjoint cluster-number ranges so state files never collide.
cmd_up_fleet() {
    local per_account="${1:-}"
    [[ "${per_account}" =~ ^[0-9]+$ && "${per_account}" -gt 0 ]] || { log "usage: up-fleet <clusters-per-account>"; exit 2; }
    require_tools
    mkdir -p "${STATE_DIR}" "${LOG_DIR}"; rm -f "${LOG_DIR}/.failures"
    terraform -chdir="${CLUSTER_DIR}" init -input=false >/dev/null
    local accounts; IFS=',' read -ra accounts <<<"${WIB_ATTENDEE_ACCOUNTS}"
    log "up-fleet: ${#accounts[@]} account(s) x ${per_account} clusters, all concurrent..."
    local idx=0 acct start n names
    for acct in "${accounts[@]}"; do
        acct="${acct// /}"; [[ -n "${acct}" ]] || continue
        start=$(( idx * per_account + 1 ))
        idx=$(( idx + 1 ))
        # Pre-check the account's lab VPC so a missing one is a recorded skip, not a silent subshell exit.
        if [[ ! -f "${LAB_VPC_DIR}/states/${acct}.tfstate" ]]; then
            log "  account '${acct}': NO lab VPC (apply states/${acct}.tfstate first); skipping its slice"
            record_fail "account:${acct}-no-vpc"; continue
        fi
        names=(); for n in $(seq "${start}" $(( start + per_account - 1 ))); do
            names+=("$(printf '%s-%03d' "${NAME_PREFIX}" "${n}")")
        done
        log "  account '${acct}': ${names[0]} .. ${names[-1]}"
        # Per-account pool in a subshell so VPC_ID/TF_PROFILE/BOOTSTRAP_PROFILE stay local; all run at once.
        (
            read_vpc_for "${acct}"
            TF_PROFILE="${acct}"
            [[ -n "${WIB_NO_BOOTSTRAP:-}" ]] || BOOTSTRAP_PROFILE="full"
            run_pool up_one "${names[@]}"
        ) &
    done
    wait
    report_failures
}

main() {
    local cmd="${1:-}"; shift || true
    case "${cmd}" in
        up) cmd_up "$@" ;;
        up-fleet) cmd_up_fleet "$@" ;;
        down) cmd_down "$@" ;;
        status) cmd_status "$@" ;;
        instructors) cmd_instructors "$@" ;;
        *) usage ;;
    esac
}

main "$@"
