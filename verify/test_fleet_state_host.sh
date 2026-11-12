#!/usr/bin/env bash
# ABOUTME: fleet.sh writes the KubeCon pair's states on the state host alone (#1374): up and down refuse
# ABOUTME: watch-it-burn-community and watch-it-burn-private elsewhere. Offline: terraform and aws are shims.
#
# Why. The states are local files. On 2026-11-12 netcup's checkout held the pair's states of 2026-10-28 (lineages
# 62a548e7 and 4c56acdb, an old private node group, no guardrail) beside tanjiro-wsl2's, rebuilt on 2026-11-07
# and applied since (fe0877ee and d3a8d599). An apply of the pair from netcup would have planned against the old
# copy. So fleet.sh names one host, WIB_STATE_HOST, and writes the pair's states there alone.
#
# What is run is fleet.sh's own `instructors up all` and `instructors down all`, from a scratch copy of the fleet
# directory, so its default states/ (the one the guard holds) is a temp dir and not this checkout's.
set -uo pipefail
export TMPDIR="${TMPDIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/tmp}"; mkdir -p "${TMPDIR}"  # never the system temp dir, RAM on netcup (#1261)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${HERE}/../infra/terraform/fleet"
T="$(mktemp -d -t fleet-state-host.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${HERE}/no-cloud.sh"; no_cloud_guard "${T}/no-cloud"
# A test-owned presenter terminal login (#910): `instructors up` refuses to build without one. A placeholder.
export WIB_TERMINAL_USER=placeholder-presenter WIB_TERMINAL_PASSWORD=placeholder-presenter-pw

for f in fleet.sh event.sh roster.tsv backups.tsv; do
    [[ -f "${SRC}/${f}" ]] || { echo "FAIL: ${SRC}/${f} is missing; this test copies it"; exit 1; }
done
FLEETDIR="${T}/repo/infra/terraform/fleet"
mkdir -p "${FLEETDIR}" "${T}/repo/infra/terraform/aws/cluster" "${T}/repo/infra/terraform/aws/network"
cp "${SRC}"/{fleet.sh,event.sh,roster.tsv,backups.tsv} "${FLEETDIR}/"
cp -r "${SRC}/providers" "${FLEETDIR}/"
FLEET="${FLEETDIR}/fleet.sh"
STATES="${FLEETDIR}/states"

# terraform: every apply and destroy is recorded by cluster name; an apply writes a one-resource state.
cat >"${SHIM}/terraform" <<'S'
#!/usr/bin/env bash
name="$(printf '%s\n' "$@" | sed -n 's/^-state=.*\/\(.*\)\.tfstate$/\1/p')"
case " $* " in
  *" apply -refresh-only "*) exit 0 ;;
  *" apply "*) echo "apply ${name}" >>"${T}/calls"
    echo '{"resources":[{"mode":"managed"}]}' >"$(printf '%s\n' "$@" | sed -n 's/^-state=//p')"; exit 0 ;;
  *" destroy "*) echo "destroy ${name}" >>"${T}/calls"; exit 0 ;;
  *" output "*"vpc_id"*) printf 'vpc-test' ;;
  *" output "*"private_subnet_ids"*) printf '["subnet-a","subnet-b"]' ;;
esac
exit 0
S
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
case "$*" in
  *"iam list-user-tags"*) echo "An error occurred (NoSuchEntity) when calling the ListUserTags operation" >&2; exit 254 ;;
esac
exit 0
S
REAL_JQ="$(command -v jq)"
printf '#!/usr/bin/env bash\ncase "$*" in *--argjson*) exec %q "$@" ;; esac\nexit 0\n' "${REAL_JQ}" >"${SHIM}/jq"
chmod +x "${SHIM}"/*
export T PATH="${SHIM}:${PATH}"
HERE_HOST="$(hostname -s 2>/dev/null || hostname)"

run() { # $1 the state host to name; the rest, the fleet.sh verb. Output and exit in ${T}/out.
    local host="$1"; shift
    rm -rf "${T}/logs"; mkdir -p "${T}/logs"; : >"${T}/calls"
    ( cd "${FLEETDIR}" && env WIB_STATE_HOST="${host}" WIB_LOG_DIR="${T}/logs" WIB_PER_ROLE=1 WIB_NO_INGEST=1 \
        WIB_NO_BOOTSTRAP=1 WIB_APPLY=1 bash "${FLEET}" "$@" ) >"${T}/out" 2>&1
    echo "rc=$?" >>"${T}/out"
}

echo "== the guard itself =="
refusal() { ( cd "${FLEETDIR}" && env WIB_STATE_HOST="$1" ${3:+WIB_STATE_DIR="$3"} bash -c \
    'source "'"${FLEET}"'" >/dev/null 2>&1; state_host_refusal "$0"' "$2" ); }
check "names the state host and this one for watch-it-burn-community on another host" \
    '[[ "$(refusal elsewhere-host watch-it-burn-community)" == *"written on elsewhere-host alone and this host is ${HERE_HOST}"* ]]'
check "and for watch-it-burn-private" '[[ -n "$(refusal elsewhere-host watch-it-burn-private)" ]]'
check "says nothing on the state host" '[[ -z "$(refusal "${HERE_HOST}" watch-it-burn-community)" ]]'
check "says nothing for a standby, which backups.py builds on netcup" \
    '[[ -z "$(refusal elsewhere-host watch-it-burn-community-b01)" && -z "$(refusal elsewhere-host watch-it-burn-private-b03)" ]]'
check "says nothing for an attendee cluster" '[[ -z "$(refusal elsewhere-host watch-it-burn-attendee-001)" ]]'
check "says nothing for a scratch WIB_STATE_DIR, which only the shim tests set" \
    '[[ -z "$(refusal elsewhere-host watch-it-burn-community "${T}/scratch")" ]]'
check "the committed state host is tanjiro-wsl2's hostname, tanjiro-debian" \
    'grep -qx "readonly WIB_STATE_HOST=\"\${WIB_STATE_HOST:-tanjiro-debian}\"" "${SRC}/fleet.sh"'

echo "== instructors up on another host builds neither KubeCon cluster and fails =="
rm -rf "${STATES}"
run elsewhere-host instructors up all
check "exits non-zero" 'grep -q "^rc=" "${T}/out" && ! grep -qx "rc=0" "${T}/out"'
check "no apply ran" '[[ ! -s "${T}/calls" ]]'
check "no state was written" '! ls "${STATES}"/*.tfstate >/dev/null 2>&1'
check "each cluster is refused by name, naming the state host" \
    'grep -q "REFUSING watch-it-burn-community: watch-it-burn-community.s state is written on elsewhere-host alone" "${T}/out" &&
     grep -q "REFUSING watch-it-burn-private: " "${T}/out"'

echo "== instructors up on the state host builds both =="
rm -rf "${STATES}"
run "${HERE_HOST}" instructors up all
check "exits 0" 'grep -qx "rc=0" "${T}/out"'
check "applied both" 'grep -qx "apply watch-it-burn-community" "${T}/calls" && grep -qx "apply watch-it-burn-private" "${T}/calls"'
check "and wrote both states in the checkout's states/" \
    '[[ -f "${STATES}/watch-it-burn-community.tfstate" && -f "${STATES}/watch-it-burn-private.tfstate" ]]'

echo "== instructors down on another host destroys neither and keeps both states =="
run elsewhere-host instructors down all
check "exits non-zero" 'grep -q "^rc=" "${T}/out" && ! grep -qx "rc=0" "${T}/out"'
check "no destroy ran" '! grep -q "^destroy" "${T}/calls"'
check "both states are still there" \
    '[[ -f "${STATES}/watch-it-burn-community.tfstate" && -f "${STATES}/watch-it-burn-private.tfstate" ]]'
check "each cluster is refused by name" \
    'grep -q "REFUSING watch-it-burn-community: " "${T}/out" && grep -q "REFUSING watch-it-burn-private: " "${T}/out"'

echo "== offline means offline =="
check "no check above called aws, kubectl, eksctl, terraform or helm outside the shims" 'no_cloud_clean'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
