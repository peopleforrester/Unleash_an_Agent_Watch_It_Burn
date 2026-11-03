#!/usr/bin/env bash
# ABOUTME: Loads, removes or shows question 926's one-row Datadog pool (#832): watch-it-burn/datadog's own keys as the
# ABOUTME: first non-admin row of watch-it-burn/datadog-pool, so a single attendee cluster can be brought up with no pool.
#
# Usage: datadog-pool-row.sh show      roles in both pool secrets (never a key) and what attendee-001 resolves to
#        datadog-pool-row.sh load      put the row in front of watch-it-burn/datadog-pool, before `fleet.sh up`
#        datadog-pool-row.sh remove    take it out again, after `fleet.sh down`, leaving the pools as they were
#
# Why it exists. fleet.sh's bootstrap gives watch-it-burn-attendee-NNN the Nth non-admin row of
# watch-it-burn/datadog-pool and -pool-2 (datadog_keys_for) and refuses the cluster when there is none ("BOOTSTRAP
# FAILED ... refusing to fall back to the shared org"). Datadog no longer issues per-student trial orgs (#629), so no
# KubeCon pool was ever loaded, and every one-cluster attendee bring-up (question 961 for #655, #532 and #608; #544;
# #461) stops there. Question 926 chose the answer: a one-row pool copied from watch-it-burn/datadog, so the cluster's
# own org is Whitney's sandbox org. The platform already ships that way on one org (#587: no datadog-admin-secret,
# the one-org collector config, converge leaves it alone, datadog-orgs.sh passes "one org by design").
#
# What it touches. Only rows whose "loaded-by" is this script's name: `load` replaces any it finds (so a second load
# is a no-op) and puts one in front of the first secret, so it is non-admin row 1 whatever else the pools hold;
# `remove` takes them out and leaves every other row as it was. A pool secret that `load` had to create is deleted
# again by `remove` once it holds nothing else. The account and region are fleet.sh's own (WIB_DEFAULT_ACCOUNT,
# WIB_SECRETS_REGION, same defaults), so this writes exactly what datadog_keys_for reads.
#
# Keys never reach a command line: the secrets are read into a private temporary directory and written back with
# --secret-string file://, and jq reads them from those files. The output names a key only by its last four characters.
set -euo pipefail

PROFILE="${WIB_DEFAULT_ACCOUNT:-accen-dev}"
REGION="${WIB_SECRETS_REGION:-${WIB_HOME_REGION:-us-west-2}}"
readonly ADMIN_SECRET="watch-it-burn/datadog"
readonly POOLS=(watch-it-burn/datadog-pool watch-it-burn/datadog-pool-2)
readonly MARK="datadog-pool-row.sh"
readonly CREATED_DESC="Created by ${MARK} load (#832); ${MARK} remove deletes it once it holds no other row."
# fleet.sh datadog_keys_for's selection, word for word: every row of both pools, admin rows dropped, then by slot.
readonly NON_ADMIN='[.[][]] | map(select((.role // "") | startswith("admin") | not))'

log() { printf '%s\n' "$*"; }
die() { printf 'datadog-pool-row: %s\n' "$*" >&2; exit 1; }

D="$(mktemp -d)"; chmod 700 "${D}"; trap 'rm -rf "${D}"' EXIT

aws_sm() { AWS_PROFILE="${PROFILE}" aws secretsmanager "$@" --region "${REGION}"; }

# read_secret <id> <file>: the SecretString into <file>. Returns 3 when the secret does not exist; any other failure
# (no credentials, access denied, a wrong region) stops the script, since reading it as empty would write over a pool.
read_secret() {
    local id="$1" out="$2" rc=0
    aws_sm get-secret-value --secret-id "${id}" --query SecretString --output text >"${out}" 2>"${D}/err" || rc=$?
    [[ "${rc}" -eq 0 ]] && return 0
    grep -q ResourceNotFoundException "${D}/err" && return 3
    die "cannot read ${id} (profile ${PROFILE}, region ${REGION}): $(tr '\n' ' ' <"${D}/err")"
}

# load_pools: p0.json and p1.json hold the two pools (an array each); missing0/missing1 mark a secret that is absent.
load_pools() {
    local i rc
    for i in 0 1; do
        rm -f "${D}/missing${i}"; rc=0
        read_secret "${POOLS[$i]}" "${D}/p${i}.json" || rc=$?
        [[ "${rc}" -eq 3 ]] && { printf '[]' >"${D}/p${i}.json"; : >"${D}/missing${i}"; }
        jq -e 'type == "array"' "${D}/p${i}.json" >/dev/null 2>&1 || die "${POOLS[$i]} is not a JSON array; not touching it"
    done
}

# write_pool <index> <file>: put <file> into the pool secret, creating it when load_pools found it missing.
write_pool() {
    local i="$1" f="$2"
    if [[ -f "${D}/missing${i}" ]]; then
        aws_sm create-secret --name "${POOLS[$i]}" --description "${CREATED_DESC}" \
            --secret-string "file://${f}" >/dev/null || die "cannot create ${POOLS[$i]}"
        log "  created ${POOLS[$i]}"
    else
        aws_sm put-secret-value --secret-id "${POOLS[$i]}" --secret-string "file://${f}" >/dev/null \
            || die "cannot write ${POOLS[$i]}"
    fi
}

# slot1 <p0> <p1>: the api-key attendee-001 resolves to, as fleet.sh resolves it, or nothing.
slot1() { jq -rs "(${NON_ADMIN})[0][\"api-key\"] // empty" "$1" "$2"; }

tail4() { local k; k="$(cat)"; [[ -n "${k}" ]] && printf '...%s' "${k: -4}" || printf 'nothing'; }

admin_key() {
    read_secret "${ADMIN_SECRET}" "${D}/admin.json" || die "${ADMIN_SECRET} does not exist; there is no org to copy"
    jq -e '(."api-key" // "") != "" and (."app-key" // "") != ""' "${D}/admin.json" >/dev/null 2>&1 \
        || die "${ADMIN_SECRET} has no api-key and app-key; there is no org to copy"
}

cmd_show() {
    load_pools
    local i
    for i in 0 1; do
        if [[ -f "${D}/missing${i}" ]]; then log "${POOLS[$i]}: does not exist"; continue; fi
        log "${POOLS[$i]}: $(jq -c --arg m "${MARK}" \
            '{rows: length, roles: (map(.role // "(none)") | group_by(.) | map({(.[0]): length}) | add // {}),
              loaded_by_this_script: (map(select(."loaded-by" == $m)) | length)}' "${D}/p${i}.json")"
    done
    local s1; s1="$(slot1 "${D}/p0.json" "${D}/p1.json")"
    if [[ -z "${s1}" ]]; then
        log "watch-it-burn-attendee-001 resolves no Datadog org: fleet.sh up refuses it. Run '${0##*/} load' first."
    elif read_secret "${ADMIN_SECRET}" "${D}/admin.json" 2>/dev/null \
        && [[ "${s1}" == "$(jq -r '."api-key" // empty' "${D}/admin.json")" ]]; then
        log "watch-it-burn-attendee-001 resolves to ${ADMIN_SECRET}'s key ($(tail4 <<<"${s1}")): question 926's one org."
    else
        log "watch-it-burn-attendee-001 resolves to a pool row's own key ($(tail4 <<<"${s1}")), not ${ADMIN_SECRET}'s."
    fi
}

cmd_load() {
    admin_key
    load_pools
    local others
    others="$(jq -s --arg m "${MARK}" "(${NON_ADMIN}) | map(select(.\"loaded-by\" != \$m)) | length" "${D}/p0.json" "${D}/p1.json")"
    # The row: the instructor org's two keys and site. role "attendee" (anything not starting "admin" is an attendee
    # row to fleet.sh); org, email and password stay empty, because nobody gets a Datadog login with it (#647).
    jq -c --arg m "${MARK}" --slurpfile a "${D}/admin.json" \
        '[{role: "attendee", "loaded-by": $m, "api-key": $a[0]."api-key", "app-key": $a[0]."app-key",
           site: ($a[0].site // "datadoghq.com"), org: "", email: "", password: ""}]
         + map(select(."loaded-by" != $m))' "${D}/p0.json" >"${D}/new0.json"
    write_pool 0 "${D}/new0.json"
    if jq -e --arg m "${MARK}" 'any(.[]; ."loaded-by" == $m)' "${D}/p1.json" >/dev/null; then
        jq -c --arg m "${MARK}" 'map(select(."loaded-by" != $m))' "${D}/p1.json" >"${D}/new1.json"
        write_pool 1 "${D}/new1.json"
    fi
    # Read it back the way fleet.sh will.
    load_pools
    [[ "$(slot1 "${D}/p0.json" "${D}/p1.json")" == "$(jq -r '."api-key"' "${D}/admin.json")" ]] \
        || die "wrote ${POOLS[0]}, but attendee-001 does not resolve to ${ADMIN_SECRET}'s key on reading it back"
    log "loaded: ${POOLS[0]} row 1 is ${ADMIN_SECRET}'s key ($(jq -r '."api-key"' "${D}/admin.json" | tail4))."
    log "  watch-it-burn-attendee-001 now resolves to it, on one org (question 926). Run '${0##*/} remove' after 'fleet.sh down'."
    [[ "${others}" -eq 0 ]] || log "  note: the pools also hold ${others} other non-admin row(s); attendee-002 and on now take them one slot later."
}

cmd_remove() {
    load_pools
    local i n removed=0
    for i in 0 1; do
        n="$(jq --arg m "${MARK}" 'map(select(."loaded-by" == $m)) | length' "${D}/p${i}.json")"
        [[ "${n}" -gt 0 ]] || continue
        removed=$(( removed + n ))
        jq -c --arg m "${MARK}" 'map(select(."loaded-by" != $m))' "${D}/p${i}.json" >"${D}/new${i}.json"
        if [[ "$(jq length "${D}/new${i}.json")" -eq 0 ]] \
            && [[ "$(aws_sm describe-secret --secret-id "${POOLS[$i]}" --query Description --output text 2>/dev/null)" == "${CREATED_DESC}" ]]; then
            aws_sm delete-secret --secret-id "${POOLS[$i]}" --force-delete-without-recovery >/dev/null \
                || die "cannot delete ${POOLS[$i]}, which ${MARK} load created"
            log "  deleted ${POOLS[$i]}: ${MARK} load created it and it holds no other row"
        else
            write_pool "${i}" "${D}/new${i}.json"
        fi
    done
    if [[ "${removed}" -eq 0 ]]; then
        log "nothing to remove: no row in ${POOLS[*]} was loaded by ${MARK}"
        return 0
    fi
    load_pools
    [[ "$(jq -s --arg m "${MARK}" '[.[][] | select(."loaded-by" == $m)] | length' "${D}/p0.json" "${D}/p1.json")" -eq 0 ]] \
        || die "removed ${removed} row(s), but reading the pools back still finds one"
    log "removed: ${removed} row(s) loaded by ${MARK}; every other pool row is as it was."
}

case "${1:-}" in
    show)   cmd_show ;;
    load)   cmd_load ;;
    remove) cmd_remove ;;
    *)      sed -n '4,6p' "$0" | sed 's/^# //' >&2; exit 2 ;;
esac
