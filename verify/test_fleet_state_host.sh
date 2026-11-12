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
  *" apply "*) echo "apply ${name}" >>"${T}/calls"; echo "${name} $*" >>"${T}/applyargs"
    echo '{"resources":[{"mode":"managed"}]}' >"$(printf '%s\n' "$@" | sed -n 's/^-state=//p')"; exit 0 ;;
  *" destroy "*) echo "destroy ${name}" >>"${T}/calls"; exit 0 ;;
  *" output "*) echo "output $*" >>"${T}/tfout" ;;&
  *" output "*"vpc_id"*) printf 'vpc-test' ;;
  *" output "*"private_subnet_ids"*) printf '["subnet-a","subnet-b"]' ;;
esac
exit 0
S
# aws: the lab VPC by its tags is VPCS_TAGGED (unset, one), and its private subnets are listed out of CIDR order,
# as AWS may list them (#1377).
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
case "$*" in
  *"iam list-user-tags"*) echo "An error occurred (NoSuchEntity) when calling the ListUserTags operation" >&2; exit 254 ;;
  *"ec2 describe-vpcs"*) echo "describe-vpcs $* [${AWS_PROFILE:-}]" >>"${T}/awscalls"; echo "${VPCS_TAGGED-vpc-aws}" ;;
  *"ec2 describe-subnets"*) echo "describe-subnets $*" >>"${T}/awscalls"
    printf '10.0.64.0/18\tsubnet-zone-b\n10.0.0.0/18\tsubnet-zone-a\n' ;;
  *"eks list-clusters"*) echo 0 ;;
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
    rm -rf "${T}/logs"; mkdir -p "${T}/logs"; : >"${T}/calls"; : >"${T}/applyargs"; : >"${T}/tfout"; : >"${T}/awscalls"
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

NET="${T}/repo/infra/terraform/aws/network"
# fleet.sh sourced in the scratch copy, as on the host $1, with the default states/; prints the function's own
# output, what $2 sets with its return (rc=), and the shell's exit (exit=), which a reader that exits 1 ends early.
vpcfn() { : >"${T}/tfout"; : >"${T}/awscalls"
    ( cd "${FLEETDIR}" && env WIB_STATE_HOST="$1" bash -c 'source "'"${FLEET}"'" >/dev/null 2>&1; set +e
      '"$2"'; rc=$?; echo "VPC_ID=${VPC_ID:-} SUBNETS_JSON=${SUBNETS_JSON:-} rc=${rc}"' 2>&1; echo "exit=$?" ); }

echo "== off the state host, accen-dev's home-region lab VPC is read from AWS, not a local state (#1377) =="
# Netcup kept its own aws/network/terraform.tfstate (lineage 02c0c252) beside tanjiro-wsl2's (005d8893) only
# because the backup schedule's us-west-2 standbys took their subnets from it. Off the state host fleet.sh reads
# that VPC from AWS by its tags, so netcup's copy can go.
rm -rf "${NET}/terraform.tfstate" "${NET}/states"
out="$(vpcfn elsewhere-host read_vpc)"
check "read_vpc finds the VPC by its tags, with the private subnets in CIDR order (zone a first)" \
    '[[ "${out}" == *"VPC_ID=vpc-aws SUBNETS_JSON=[\"subnet-zone-a\", \"subnet-zone-b\"] rc=0"* ]]'
check "asked as accen-dev in us-west-2, by the network root's Name and project tags" \
    'grep -F "describe-vpcs" "${T}/awscalls" | grep -F "Name=tag:Name,Values=watch-it-burn-lab-vpc" | grep -F "Name=tag:project,Values=watch-it-burn" | grep -F -- "--region us-west-2" | grep -qF "[accen-dev]"'
check "and the subnets by the VPC and the internal-elb role tag" \
    'grep -F "describe-subnets" "${T}/awscalls" | grep -F "Name=vpc-id,Values=vpc-aws" | grep -qF "Name=tag:kubernetes.io/role/internal-elb,Values=1"'
check "no terraform output was read" '[[ ! -s "${T}/tfout" ]]'
check "and it says where the state is" '[[ "${out}" == *"read from AWS (its state is on elsewhere-host)"* ]]'
echo '{"resources":[{"mode":"managed"}]}' >"${NET}/terraform.tfstate"
out="$(vpcfn elsewhere-host read_vpc)"
check "a local copy left on this host is not read" '[[ "${out}" == *"VPC_ID=vpc-aws "* && ! -s "${T}/tfout" ]]'
out="$(vpcfn elsewhere-host 'read_vpc_for accen-dev')"
check "read_vpc_for accen-dev reads it the same way" '[[ "${out}" == *"VPC_ID=vpc-aws SUBNETS_JSON=[\"subnet-zone-a\", \"subnet-zone-b\"] rc=0"* ]]'
out="$(vpcfn elsewhere-host 'read_vpc_id_for accen-dev')"
check "and read_vpc_id_for, which scopes the security-group sweep, prints its id" '[[ "${out}" == "vpc-aws"* ]]'
out="$(vpcfn "${HERE_HOST}" read_vpc)"
check "on the state host the state is read, and AWS is not asked" \
    '[[ "${out}" == *"VPC_ID=vpc-test "* ]] && grep -q "output .*vpc_id" "${T}/tfout" && [[ ! -s "${T}/awscalls" ]]'
rm -f "${NET}/terraform.tfstate"
out="$(VPCS_TAGGED='' vpcfn elsewhere-host read_vpc)"
check "no tagged VPC exits 1, naming the state host" '[[ "${out}" == *"0 VPC(s) are tagged Name=watch-it-burn-lab-vpc"*"apply or fix it on elsewhere-host"*"exit=1" ]] && [[ "${out}" != *"rc="* ]]'
out="$(VPCS_TAGGED="vpc-1 vpc-2" vpcfn elsewhere-host read_vpc)"
check "two tagged VPCs exit 1, naming both" '[[ "${out}" == *"2 VPC(s) are tagged Name=watch-it-burn-lab-vpc there: vpc-1 vpc-2"*"exit=1" ]] && [[ "${out}" != *"rc="* ]]'
mkdir -p "${NET}/states"; echo '{}' >"${NET}/states/aws1-student31.tfstate"; echo '{}' >"${NET}/states/accen-dev.us-east-2.tfstate"
out="$(vpcfn elsewhere-host 'read_vpc_for aws1-student31')"
check "another account's lab VPC is still read from its own state" \
    '[[ "${out}" == *"VPC_ID=vpc-test "* ]] && grep -qF "states/aws1-student31.tfstate" "${T}/tfout" && [[ ! -s "${T}/awscalls" ]]'
out="$(WIB_REGION=us-east-2 vpcfn elsewhere-host 'read_vpc_for accen-dev')"
check "and accen-dev's outside the home region from states/<acct>.<region>.tfstate, where the schedule applies it" \
    '[[ "${out}" == *"VPC_ID=vpc-test "* ]] && grep -qF "states/accen-dev.us-east-2.tfstate" "${T}/tfout" && [[ ! -s "${T}/awscalls" ]]'
rm -rf "${NET}/states"

echo "== the us-west-2 standbys still build off the state host, with no lab VPC state there =="
# What backups.py's region step runs for us-west-2 (region_steps): its standbys' roster rows and fleet.sh
# instructors up all with WIB_REGION=us-west-2, as on netcup.
grep -vE '^[[:space:]]*(#|$)' "${FLEETDIR}/roster.tsv" | awk -F'|' -v OFS='|' '
    $2 == "community" { $1 = "watch-it-burn-community-b03"; print }
    $2 == "admin"     { $1 = "watch-it-burn-private-b03"; print }' >"${T}/standbys.tsv"
check "the scratch roster holds both us-west-2 night-before standbys" '[[ "$(wc -l <"${T}/standbys.tsv")" -eq 2 ]]'
rm -rf "${STATES}"
( export WIB_ROSTER_FILE="${T}/standbys.tsv" WIB_REGION=us-west-2 WIB_NO_ROUTES=1 WIB_NO_VERIFY=1 WIB_NO_LINK=1
  run elsewhere-host instructors up all )
check "exits 0" 'grep -qx "rc=0" "${T}/out"'
check "applied both standbys" \
    'grep -qx "apply watch-it-burn-community-b03" "${T}/calls" && grep -qx "apply watch-it-burn-private-b03" "${T}/calls"'
check "in the VPC AWS names" \
    '[[ "$(grep -c -- "-var vpc_id=vpc-aws " "${T}/applyargs")" -eq 2 ]]'
check "community-b03's node in zone a, the first private subnet, as backups.tsv says" \
    'grep "^watch-it-burn-community-b03 " "${T}/applyargs" | grep -qF -- "-var node_subnet_ids=[\"subnet-zone-a\"]"'
check "private-b03's in zone b" \
    'grep "^watch-it-burn-private-b03 " "${T}/applyargs" | grep -qF -- "-var node_subnet_ids=[\"subnet-zone-b\"]"'
check "and no lab VPC state was read" '! grep -q "aws/network" "${T}/tfout"'

echo "== down-infra of that VPC is refused off the state host =="
echo '{"resources":[{"mode":"managed"}]}' >"${NET}/terraform.tfstate"
run elsewhere-host down-infra accen-dev
check "exits non-zero" 'grep -q "^rc=" "${T}/out" && ! grep -qx "rc=0" "${T}/out"'
check "refused, naming the state host" \
    'grep -q "accen-dev: REFUSING to destroy the lab VPC in us-west-2: its state is on elsewhere-host alone" "${T}/out"'
check "no destroy ran, and the local copy is untouched" \
    '! grep -q "^destroy" "${T}/calls" && [[ -s "${NET}/terraform.tfstate" ]]'
run elsewhere-host down-infra aws1-student31
check "another account is not held to it" '! grep -q "REFUSING" "${T}/out" && grep -q "aws1-student31: no lab VPC state, nothing to destroy" "${T}/out"'
run "${HERE_HOST}" down-infra accen-dev
check "on the state host it destroys from terraform.tfstate" 'grep -qx "destroy terraform" "${T}/calls" && grep -qx "rc=0" "${T}/out"'
rm -f "${NET}/terraform.tfstate"

echo "== offline means offline =="
check "no check above called aws, kubectl, eksctl, terraform or helm outside the shims" 'no_cloud_clean'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
