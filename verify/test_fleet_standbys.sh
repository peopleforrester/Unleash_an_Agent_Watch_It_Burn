#!/usr/bin/env bash
# ABOUTME: Behavioural test of fleet.sh's side of the standbys (#643): `routes roster` keeps a promoted standby on
# ABOUTME: the role's hostname, a run outside us-west-2 reads its own lab VPC state, and the bootstrap is told the region.
#
# Usage: verify/test_fleet_standbys.sh      (offline: kubectl, aws, the record and the reload are stubbed)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .fleet-standbys-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 TMPDIR="${T}"

fixture() {   # an apex checkout publishing the two roster consoles, and an empty state dir
    rm -rf "${T}/apex" "${T}/states" "${T}/logs"; mkdir -p "${T}/apex" "${T}/states" "${T}/logs"
    git init -q -b main "${T}/apex"
    git -C "${T}/apex" config user.email fixture@test; git -C "${T}/apex" config user.name fixture
    printf '# old\nattackme.agenticburn.com  old:443\nburritobot-private.agenticburn.com  old:443\n' >"${T}/apex/routes.map"
    git -C "${T}/apex" add -A; git -C "${T}/apex" commit -qm base
}
# cmd_routes against a sourced fleet.sh. Each console answers with an LB named for its cluster; every kubeconfig
# fetch is recorded as "<cluster> <region>", so the test can see which cluster, in which region, it read.
routes() {
    ( cd "$(dirname "${FLEET}")" && WIB_APEX_DIR="${T}/apex" WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" \
        bash -c '
        source "'"${FLEET}"'" >/dev/null 2>&1
        load_roster
        require_tools() { :; }
        provider_write_kubeconfig() { printf "%s\n" "$1" >"$2"; printf "%s %s\n" "$1" "${4:-}" >>"'"${T}"'/fetches"; }
        kubectl() { printf "lb-%s.elb.test" "$(cat "${KUBECONFIG}")"; }
        publish_routes_table() { :; }
        apply_routes_table() { :; }
        cmd_routes roster' 2>"${T}/log"; echo "rc=$?" )
}
row() { awk -v h="$1" '$1 == h { print $2 }' "${T}/apex/routes.map"; }

echo "== no promotion: routes roster sends each hostname to its roster cluster =="
fixture; : >"${T}/fetches"
out="$(routes)"
check "it succeeds" '[[ "${out}" == *rc=0* ]]'
check "attackme goes to watch-it-burn-community" '[[ "$(row attackme.agenticburn.com)" == lb-watch-it-burn-community.elb.test:443 ]]'
check "read in the fleet's region" 'grep -qx "watch-it-burn-community us-west-2" "${T}/fetches"'

echo "== a promoted standby keeps the role's hostname =="
fixture; : >"${T}/fetches"
printf 'community\twatch-it-burn-community-b01\n' >"${T}/states/promoted.tsv"
out="$(routes)"
check "it succeeds, and is not refused as a shrink" '[[ "${out}" == *rc=0* ]]'
check "attackme goes to the standby's console" '[[ "$(row attackme.agenticburn.com)" == lb-watch-it-burn-community-b01.elb.test:443 ]]'
check "so do its burritobot.co twin and its service hosts" \
  '[[ "$(row attackme.burritobot.co)" == lb-watch-it-burn-community-b01.elb.test:443 &&
     "$(row grafana-attackme.agenticburn.com)" == lb-watch-it-burn-community-b01.elb.test:443 ]]'
check "the standby's LB is read in its own region, us-east-2 (backups.tsv)" \
  'grep -qx "watch-it-burn-community-b01 us-east-2" "${T}/fetches"'
check "the failed roster cluster is not asked at all" '! grep -q "^watch-it-burn-community " "${T}/fetches"'
check "burritobot-private, not promoted, stays on its roster cluster" \
  '[[ "$(row burritobot-private.agenticburn.com)" == lb-watch-it-burn-private.elb.test:443 ]]'
check "the log says so" 'grep -q "attackme.agenticburn.com is promoted to watch-it-burn-community-b01 (us-east-2)" "${T}/log"'

echo "== a holder backups.tsv does not list is not trusted =="
fixture; : >"${T}/fetches"
printf 'admin\twatch-it-burn-private-b99\n' >"${T}/states/promoted.tsv"
out="$(routes)"
check "burritobot-private stays on its roster cluster" \
  '[[ "${out}" == *rc=0* && "$(row burritobot-private.agenticburn.com)" == lb-watch-it-burn-private.elb.test:443 ]]'
check "and the log names the holder it did not use" 'grep -q "promoted to watch-it-burn-private-b99, which backups.tsv does not list" "${T}/log"'

echo "== a run outside the home region reads that region's lab VPC state =="
vpc() {   # $1 WIB_REGION, $2 account, $3 the function; prints its output
    ( cd "$(dirname "${FLEET}")" && WIB_REGION="$1" bash -c 'source "'"${FLEET}"'" >/dev/null 2>&1; '"$3"' "'"$2"'"' 2>&1 )
}
check "the default account at home keeps the default state" \
  '[[ "$(vpc us-west-2 accen-dev lab_vpc_state_for)" == */aws/network/terraform.tfstate ]]'
check "another account at home keeps states/<account>.tfstate" \
  '[[ "$(vpc us-west-2 aws1-student31 lab_vpc_state_for)" == */aws/network/states/aws1-student31.tfstate ]]'
check "in us-east-2 the default account has states/accen-dev.us-east-2.tfstate" \
  '[[ "$(vpc us-east-2 accen-dev lab_vpc_state_for)" == */aws/network/states/accen-dev.us-east-2.tfstate ]]'
check "the default account at home always has a VPC to read" \
  '( cd "$(dirname "${FLEET}")" && WIB_REGION=us-west-2 bash -c "source \"${FLEET}\" >/dev/null 2>&1; lab_vpc_present accen-dev" )'
check "in a region with no state it has none" \
  '! ( cd "$(dirname "${FLEET}")" && WIB_REGION=us-east-2 bash -c "source \"${FLEET}\" >/dev/null 2>&1; lab_vpc_present accen-dev" )'
out="$(vpc us-east-2 accen-dev read_vpc_for)"
check "read_vpc_for there fails with the apply that makes it" \
  'grep -q "no lab VPC for account .accen-dev. in us-east-2" <<<"${out}" &&
   grep -q "apply -state=states/accen-dev.us-east-2.tfstate" <<<"${out}" && grep -q -- "-var region=us-east-2" <<<"${out}"'
check "a us-east-2 run still reads the Datadog keys from us-west-2" \
  '[[ "$(cd "$(dirname "${FLEET}")" && WIB_REGION=us-east-2 bash -c "source \"${FLEET}\" >/dev/null 2>&1; echo \${WIB_SECRETS_REGION}")" == us-west-2 ]]'

echo "== the bootstrap is told the cluster's region =="
( cd "$(dirname "${FLEET}")" && WIB_REGION=us-east-1 WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" bash -c '
    source "'"${FLEET}"'" >/dev/null 2>&1
    provider_write_kubeconfig() { :; }
    datadog_keys_for() { echo "a b - -"; }
    run_idp_script() { echo "${REGION:-unset}" >"'"${T}"'/idp-region"; }
    bootstrap_student_aws() { :; }; bootstrap_terminal_auth() { :; }; pin_bedrock_profiles() { :; }; arm_infra_guardrails() { :; }
    bootstrap_one watch-it-burn-community-b02 burn' >/dev/null 2>&1 )
check "deploy-full-idp.sh runs with REGION=us-east-1, not its us-west-2 default" '[[ "$(cat "${T}/idp-region" 2>/dev/null)" == us-east-1 ]]'

echo "== a standby is planned as its role, in its own region =="
# attackme's standbys must leak node IMDS like attackme (#113), or the credential-theft beat dies on a promotion;
# the private bot's keep the control.
plan() {   # $1 cluster, $2 WIB_REGION; prints up_one's dry-run plan line
    ( cd "$(dirname "${FLEET}")" && WIB_REGION="$2" WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" bash -c '
        source "'"${FLEET}"'" >/dev/null 2>&1; require_tools() { :; }; WIB_DRY_RUN=1 up_one "'"$1"'" 2>&1' )
}
out="$(plan watch-it-burn-community-b01 us-east-2)"
check "a community standby plans imds_hop_limit=2 and role=community" \
  '[[ "${out}" == *"-var imds_hop_limit=2"* && "${out}" == *"-var role=community"* ]]'
check "under attackme's hostname, in us-east-2" \
  '[[ "${out}" == *"-var hostname=attackme.agenticburn.com"* && "${out}" == *"-var region=us-east-2"* ]]'
out="$(plan watch-it-burn-private-b02 us-east-1)"
check "a private standby plans imds_hop_limit=1 and role=admin, in us-east-1" \
  '[[ "${out}" == *"-var imds_hop_limit=1"* && "${out}" == *"-var role=admin"* && "${out}" == *"-var region=us-east-1"* ]]'

echo "== standbys stay out of the router when they are built =="
src="$(sed -n '/^_provision_spec_fleet() {/,/^}/p' "${FLEET}")"
check "_provision_spec_fleet skips routes under WIB_NO_ROUTES" \
  'grep -q "\-z \"\${WIB_NO_ROUTES:-}\" ]]; then" <<<"${src}" && grep -B2 "cmd_routes ||" <<<"${src}" | grep -q WIB_NO_ROUTES'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
