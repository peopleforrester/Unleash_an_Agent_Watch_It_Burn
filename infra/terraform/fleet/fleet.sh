#!/usr/bin/env bash
# ABOUTME: Fleet driver. Stamps out N attendee clusters from the cluster/ module against the
# ABOUTME: shared lab VPC, each with its own state, concurrency-capped, parallel. (Packt-modeled.)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROVISION_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# The IDP bootstrap script lives in infra/ (the parent of the terraform provisioning dir), NOT under
# infra/terraform/. bootstrap_one runs this; an earlier ${PROVISION_DIR}/deploy-full-idp.sh reference
# pointed at infra/terraform/ and silently failed every fleet bootstrap (found 2026-06-27).
INFRA_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd "${INFRA_DIR}/.." && pwd)"
readonly SCRIPT_DIR PROVISION_DIR INFRA_DIR REPO_ROOT
readonly IDP_SCRIPT="${INFRA_DIR}/deploy-full-idp.sh"
readonly HARVEST_SCRIPT="${REPO_ROOT}/lab-distribution/scripts/harvest_cluster_access.sh"
readonly GEN_AWS_SCRIPT="${REPO_ROOT}/lab-distribution/scripts/generate_attendee_aws.py"
readonly PUSH_VTT_SCRIPT="${REPO_ROOT}/lab-distribution/scripts/push_vtt_aws_creds.sh"
readonly AWS_POOL_DIR="${SCRIPT_DIR}/aws-pool"   # gitignored: holds live access keys
readonly CLUSTER_DIR="${PROVISION_DIR}/cluster"
readonly LAB_VPC_DIR="${PROVISION_DIR}/lab-vpc"
readonly STATE_DIR="${SCRIPT_DIR}/states"
readonly LOG_DIR="${SCRIPT_DIR}/logs"
readonly NAME_PREFIX="watch-it-burn-attendee"
# Per-ACCOUNT cap (up-fleet runs all accounts concurrently, so total concurrent = #accounts x this).
# 15 x 5 accounts = 75 concurrent cluster builds. Most of each build is an idle ~10-15 min wait on the
# EKS control-plane create (near-zero local cost), so the binding local limit is RAM during the bootstrap
# spike: ~600MB per build tree on this 62GB box, ~45GB at 75-wide, leaves headroom. Raise via env for a
# bigger box; the irreducible floor is the EKS control-plane create (~10-15 min, AWS-side, per cluster).
MAX_PARALLEL="${MAX_PARALLEL:-15}"

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

# --- Instructor roster: 9 fixed clusters, 3 per round. "name|round|bootstrap-profile" -----------
# Facilitator-run, NOT in the attendee pool. ALL NINE ARE THE IDENTICAL FULL Sonnet-4.6 BUILD (same as
# the attendee clusters): same app-of-apps, same ai-layer, same model. The 3-per-round are interchangeable
# hot spares (if one dies mid-talk, fall back to another). The ROUND BEHAVIOUR (R1 wide open, R2 some
# guards, R3 full + student-toggled) is a RUNTIME state flipped by the guard-toggle scripts + round
# selector, NOT a different build. The ONE provision-time difference is R1's PID cap: cmd_instructors
# sets pod_pids_limit=-1 on round 1 so the C4 fork bomb actually exhausts node PIDs ("watch it burn");
# R2/R3 keep the 1024 cap. (History: R1 used to be a stripped "burn" profile and R3 ran per-model tiers
# haiku/opus; both dropped, all Sonnet, all full.)
INSTRUCTORS=(
  "watch-it-burn-r1-1|1|full"
  "watch-it-burn-r1-2|1|full"
  "watch-it-burn-r1-3|1|full"
  "watch-it-burn-r2-1|2|full"
  "watch-it-burn-r2-2|2|full"
  "watch-it-burn-r2-3|2|full"
  "watch-it-burn-r3-1|3|full"
  "watch-it-burn-r3-2|3|full"
  "watch-it-burn-r3-3|3|full"
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
                      (disjoint name ranges). Honors WIB_NAME_OFFSET to skip existing cluster numbers.
    down-fleet <n>    Tear down an up-fleet run: SAME <n> + WIB_NAME_OFFSET, account-aware (each cluster
                      destroyed in its own account). Skips names with no state, so partial fleets are safe.
    down <count|all>  Destroy the first <count>, or all clusters with state.
    down <name...>    Destroy the named clusters.
    health <n>        Sweep IDP health of an up-fleet run (SAME <n> + WIB_NAME_OFFSET): per cluster,
                      assert every ArgoCD app Synced+Healthy and no broken pods. Non-zero if any degraded.
    harvest <n>      Harvest student-facing access info (console NLB / grafana / ...) of an up-fleet run
                      (SAME <n> + WIB_NAME_OFFSET) to a pool CSV on stdout (feed merge_pool.py).
    aws-keys <n>     Generate per-attendee scoped IAM user+key per cluster in its OWN account (SAME <n>
                      + offset). DRY-RUN unless WIB_APPLY=1; WIB_ACCESS_ENTRIES=1 maps users into clusters.
    reap --keep <f>   Cost reaper: destroy attendee clusters NOT in the keep-list <f> (claimed clusters),
                      across all accounts. DRY-RUN unless WIB_APPLY=1.
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
    local acct_profile="${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}"
    local kcfg; kcfg="$(mktemp -t "${name}.kcfg.XXXX")"
    AWS_PROFILE="${acct_profile}" aws eks update-kubeconfig --kubeconfig "${kcfg}" \
        --name "${name}" --region "${WIB_REGION}" >/dev/null 2>&1
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
    else
        log "  BOOTSTRAP FAILED: ${name} (see ${LOG_DIR}/${name}.bootstrap.log)"; record_fail "${name}"
    fi
    rm -f "${kcfg}"
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

up_one() {
    local name="$1"; assert_ours "${name}"
    local prof=(); [[ -n "${TF_PROFILE}" ]] && prof=(-var "profile=${TF_PROFILE}" -var "region=${WIB_REGION}")
    local pids=(); [[ -n "${TF_PIDS_LIMIT}" ]] && pids=(-var "pod_pids_limit=${TF_PIDS_LIMIT}")
    local dh=(); [[ -n "${WIB_DOCKERHUB_AUTH_B64}" ]] && dh=(-var "dockerhub_auth_b64=${WIB_DOCKERHUB_AUTH_B64}")
    if terraform -chdir="${CLUSTER_DIR}" apply -auto-approve -no-color \
        -state="${STATE_DIR}/${name}.tfstate" \
        -var "name=${name}" -var "vpc_id=${VPC_ID}" \
        -var "private_subnet_ids=${SUBNETS_JSON}" "${prof[@]}" "${pids[@]}" "${dh[@]}" \
        >"${LOG_DIR}/${name}.apply.log" 2>&1; then
        log "  ok: ${name}"
        # Auto-bootstrap the IDP unless this provision is bare-only.
        [[ -n "${BOOTSTRAP_PROFILE}" ]] && bootstrap_one "${name}" "${BOOTSTRAP_PROFILE}"
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
    if AWS_PROFILE="${acct}" aws eks update-kubeconfig --kubeconfig "${kc}" --name "${name}" --region "${WIB_REGION}" >/dev/null 2>&1 \
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
    fi
    rm -f "${kc}"
}

down_one() {
    local name="$1"; assert_ours "${name}"
    [[ -f "${STATE_DIR}/${name}.tfstate" ]] || { log "  no state for ${name}, skipping"; return 0; }
    drain_cluster_lbs "${name}"
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
        # Round 1 clusters provision with NO per-pod PID cap so the fork bomb lands (the burn). This is
        # the ONLY per-round provision difference; R2/R3 keep the module-default 1024 cap.
        [[ "${r}" == "1" ]] && TF_PIDS_LIMIT="-1" || TF_PIDS_LIMIT=""
        # Auto-bootstrap: ALL rounds get the identical FULL build (R1 is no longer a stripped "burn"
        # profile; its open/guardrails-off state is a runtime toggle). Skipped if WIB_NO_BOOTSTRAP=1.
        if [[ "${action}" == "up" && -z "${WIB_NO_BOOTSTRAP:-}" ]]; then
            BOOTSTRAP_PROFILE="full"
        fi
        if [[ "${action}" == "up" ]]; then run_pool up_one "${names[@]}"; else run_pool down_one "${names[@]}"; fi
        TF_PROFILE=""; TF_PIDS_LIMIT=""; BOOTSTRAP_PROFILE=""
    done
    report_failures
    # Auto-regenerate the agenticburn.com router map so instructor friendly URLs resolve (no manual step).
    [[ "${action}" == "up" && -z "${WIB_NO_BOOTSTRAP:-}" ]] && { cmd_routes || log "routes: run 'fleet.sh routes' manually once LBs are up"; }
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
        start=$(( WIB_NAME_OFFSET + idx * per_account + 1 ))
        idx=$(( idx + 1 ))
        # Pre-check the account's lab VPC so a missing one is a recorded skip, not a silent subshell exit.
        # The default account uses the default lab-vpc state, so it has no per-account state file (allowed).
        if [[ ! -f "${LAB_VPC_DIR}/states/${acct}.tfstate" && "${acct}" != "${WIB_DEFAULT_ACCOUNT}" ]]; then
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
    # Auto-regenerate the agenticburn.com router map so every cluster's friendly URL resolves (no manual step).
    cmd_routes || log "routes: run 'fleet.sh routes' manually once LBs are up"
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
    if ! AWS_PROFILE="${acct_profile}" aws eks update-kubeconfig --kubeconfig "${kcfg}" \
            --name "${name}" --region "${WIB_REGION}" >/dev/null 2>&1; then
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
        live="$(AWS_PROFILE="${acct}" aws eks list-clusters --region "${WIB_REGION}" --query 'clusters[]' --output text 2>/dev/null | tr '\t' '\n' | grep -E '^watch-it-burn-attendee-' || true)"
        [[ -n "${live}" ]] || { log "  account '${acct}': no attendee clusters"; continue; }
        (
            read_vpc_for "${acct}"; TF_PROFILE="${acct}"
            for c in ${live}; do
                if [[ -n "${keep[${c}]:-}" ]]; then continue; fi
                if [[ -n "${WIB_APPLY:-}" ]]; then log "  reaping ${c} (${acct})"; down_one "${c}"
                else log "  would reap ${c} (${acct})"; fi
            done
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
    local kcfg; kcfg="$(mktemp -t "${name}.ing.XXXX")"
    AWS_PROFILE="${acct_profile}" aws eks update-kubeconfig --kubeconfig "${kcfg}" --name "${name}" --region "${WIB_REGION}" >/dev/null 2>&1
    local console_host; console_host="$(KUBECONFIG="${kcfg}" kubectl -n agent get svc console -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)"
    rm -f "${kcfg}"
    [[ -n "${console_host}" ]] || { log "  ingest ${name}: console NLB not ready; skip"; record_fail "ingest:${name}"; return; }
    local ak sk
    ak="$(tail -n +2 "${AWS_POOL_DIR}/${name}.csv" 2>/dev/null | head -1 | cut -d, -f3)"
    sk="$(tail -n +2 "${AWS_POOL_DIR}/${name}.csv" 2>/dev/null | head -1 | cut -d, -f4)"
    [[ -n "${ak}" && -n "${sk}" ]] || { log "  ingest ${name}: no persisted AWS creds (${AWS_POOL_DIR}/${name}.csv); skip"; record_fail "ingest:${name}"; return; }
    local slot; slot="$(printf '%s' "${name}" | sed -n "s/^${NAME_PREFIX}-0*\([0-9][0-9]*\)$/\1/p")"
    local dd="{}"
    [[ -n "${slot}" ]] && dd="$(jq -cn --argjson a "${POOL1}" --argjson b "${POOL2}" --argjson i "$(( slot - 1 ))" \
        '(([$a[],$b[]]|map(select((.role//"")|startswith("admin")|not)))[$i]) // {} | {org:(.org//""),email:(.email//""),password:(.password//""),api:(.["api-key"]//""),app:(.["app-key"]//""),site:(.site//"datadoghq.com")}' 2>/dev/null)"
    [[ -n "${dd}" ]] || dd='{}'   # never let an empty resolver result reach --argjson
    local row; row="$(jq -cn --arg n "${name}" --arg r "${WIB_REGION}" --arg ak "${ak}" --arg sk "${sk}" --arg cu "http://${console_host}" --argjson dd "${dd}" \
        '($dd.site // "datadoghq.com") as $site
         | ($site | if . == "datadoghq.com" or . == "datadoghq.eu" then "https://app." + . else "https://" + . end) as $ddurl
         | {name:$n,region:$r,access_key:$ak,secret_key:$sk,console_url:$cu,datadog_org:($dd.org//""),datadog_email:($dd.email//""),datadog_password:($dd.password//""),datadog_api_key:($dd.api//""),datadog_app_key:($dd.app//""),datadog_site:$site,datadog_dashboard_url:$ddurl}')"
    if curl -s -X POST "${WIB_PROVISIONING_URL%/}/admin/import" -H "X-Admin-Token: ${WIB_ADMIN_TOKEN}" \
        -H "Content-Type: application/json" --data "{\"clusters\":[${row}]}" --max-time 25 -o /dev/null -w '%{http_code}' | grep -q '^200$'; then
        log "  ingested: ${name}"
    else
        log "  ingest POST failed: ${name}"; record_fail "ingest:${name}"
    fi
}

# Harvest + push the fleet (or explicit names) into the live provisioning pool. Numeric arg = per-account
# count form (honors WIB_NAME_OFFSET + WIB_ATTENDEE_ACCOUNTS); otherwise explicit cluster names (default account).
cmd_ingest() {
    [[ $# -ge 1 ]] || { log "usage: ingest <clusters-per-account> | ingest <cluster-name...>"; exit 2; }
    : "${WIB_PROVISIONING_URL:?set WIB_PROVISIONING_URL (e.g. https://provisioning.agenticburn.com)}"
    : "${WIB_ADMIN_TOKEN:?set WIB_ADMIN_TOKEN (the provisioning app ADMIN_TOKEN)}"
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
        local name
        for name in "$@"; do ingest_one "${name}" "${WIB_DEFAULT_ACCOUNT}"; done
    fi
    report_failures
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
    local out="${REPO_ROOT}/railway/apex/routes.map"
    local kcfg tmp; kcfg="$(mktemp -t routes.XXXX)"; tmp="$(mktemp -t routesmap.XXXX)"
    {
        echo "# ABOUTME: Host -> cluster LB routing for the agenticburn.com wildcard router."
        echo "# ABOUTME: AUTO-GENERATED by 'fleet.sh routes' from live cluster LBs. Do not hand-edit."
    } > "${tmp}"
    local entry name rr bp acct h short n state
    local -A round_done=()
    for entry in "${INSTRUCTORS[@]}"; do
        IFS='|' read -r name rr bp <<<"${entry}"
        acct="$(account_for_round "${rr}")"
        AWS_PROFILE="${acct}" aws eks update-kubeconfig --kubeconfig "${kcfg}" --name "${name}" --region "${WIB_REGION}" >/dev/null 2>&1 || continue
        h="$(KUBECONFIG="${kcfg}" kubectl -n agent get svc console -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)"
        [[ -n "${h}" ]] || { log "  routes: ${name} console LB not ready, skipping"; continue; }
        short="${name#watch-it-burn-}"
        printf '%s.agenticburn.com  %s:80\n' "${short}" "${h}" >> "${tmp}"
        [[ -z "${round_done[$rr]:-}" ]] && { printf 'round%s.agenticburn.com  %s:80\n' "${rr}" "${h}" >> "${tmp}"; round_done[$rr]=1; }
    done
    # Admin attendee clusters (attendee-NNN with state in the default account) -> a-NNN.agenticburn.com.
    if [[ -d "${STATE_DIR}" ]]; then
        for state in "${STATE_DIR}"/${NAME_PREFIX}-*.tfstate; do
            [[ -e "${state}" ]] || continue
            name="$(basename "${state}" .tfstate)"; n="${name##*-}"
            AWS_PROFILE="${WIB_DEFAULT_ACCOUNT}" aws eks update-kubeconfig --kubeconfig "${kcfg}" --name "${name}" --region "${WIB_REGION}" >/dev/null 2>&1 || continue
            h="$(KUBECONFIG="${kcfg}" kubectl -n agent get svc console -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)"
            [[ -n "${h}" ]] && printf 'a-%s.agenticburn.com  %s:80\n' "${n}" "${h}" >> "${tmp}"
        done
    fi
    rm -f "${kcfg}"
    mv "${tmp}" "${out}"
    local lines; lines="$(grep -c agenticburn.com "${out}")"
    log "routes: wrote ${lines} host(s) to ${out#${REPO_ROOT}/}"
    if git -C "${REPO_ROOT}" diff --quiet -- "${out}"; then
        log "routes: no change"; return 0
    fi
    # Commit + push so the apex service (watches railway/apex/** on main) redeploys with the new map.
    git -C "${REPO_ROOT}" add "${out}"
    # NOTE: no [skip ci] in this message — Railway's GitHub deploy honors it and would NOT redeploy the
    # apex, leaving routes.map stale. Let the push trigger the apex rebuild.
    git -C "${REPO_ROOT}" commit -q -m "routes: regenerate agenticburn.com router map from live fleet (${lines} hosts)" || true
    git -C "${REPO_ROOT}" push origin HEAD 2>&1 | tail -1 || log "routes: push to current branch failed"
    # The apex router (agenticburn.com wildcard) deploys from MAIN; promote routes.map so it redeploys.
    git -C "${REPO_ROOT}" push origin HEAD:main 2>&1 | tail -1 || log "routes: could not ff main; run 'git push origin <branch>:main' so the apex picks up routes.map"
}

main() {
    local cmd="${1:-}"; shift || true
    case "${cmd}" in
        up) cmd_up "$@" ;;
        routes) cmd_routes "$@" ;;
        up-fleet) cmd_up_fleet "$@" ;;
        down) cmd_down "$@" ;;
        down-acct) cmd_down_acct "$@" ;;
        down-fleet) cmd_down_fleet "$@" ;;
        health) cmd_health "$@" ;;
        harvest) cmd_harvest "$@" ;;
        ingest) cmd_ingest "$@" ;;
        aws-keys) cmd_aws_keys "$@" ;;
        reap) cmd_reap "$@" ;;
        status) cmd_status "$@" ;;
        instructors) cmd_instructors "$@" ;;
        *) usage ;;
    esac
}

main "$@"
