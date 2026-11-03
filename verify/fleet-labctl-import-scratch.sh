#!/usr/bin/env bash
# ABOUTME: #655's import check, by hand: fleet.sh ingest and ingest-instructors into lab-platform's own labctl and
# ABOUTME: schema on a scratch Postgres, then a claim, a re-ingest and `ingest pool`, each checked against labctl.
#
# Usage: bash verify/fleet-labctl-import-scratch.sh [lab-platform-commit]
#
# What it settles is the row fleet.sh sends and what labctl does with it, the five points #655 lists: a blank role is
# an attendee, the header's @csv quoting reads, terminal_user/terminal_password/role are known columns, labctl's exit
# code is the verdict, and a re-import updates a claimed row without moving its claim. labctl, the migrations and the
# claim function are lab-platform's own, built from the commit given (default: the one run 16719 checked).
#
# What it does not touch: no cluster, no AWS, and not lab-platform's production database. The cluster reads fleet.sh
# makes before the import (the console NLB, the attendee's AWS key file, the terminal Secret) are shims, the same
# shape verify/test_fleet_terminal_harvest.sh gives them, so the row is the one fleet.sh builds from those values.
#
# Needs: gh signed in with read access to peopleforrester/lab-platform (private), go, jq, psql and the Postgres
# server binaries (initdb, pg_ctl). A missing one is named and the script exits 1. Nothing here skips: every check
# that fails is named and the script exits 1. Not part of either tier, because the gate host has no go, no Postgres
# server and no access to the private repo.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
LP_COMMIT="${1:-4fc24e6c4c84e67c45fcadfeac4a92957434a3db}"
EVENT="wib-655-scratch"

PGBIN="$(pg_config --bindir 2>/dev/null || true)"
[[ -x "${PGBIN}/initdb" ]] || PGBIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)"
missing=()
for t in gh go jq psql; do command -v "${t}" >/dev/null 2>&1 || missing+=("${t}"); done
[[ -x "${PGBIN}/initdb" && -x "${PGBIN}/pg_ctl" ]] || missing+=("initdb and pg_ctl (Postgres server binaries)")
if [[ "${#missing[@]}" -gt 0 ]]; then
  printf 'MISSING: %s\n' "${missing[@]}" >&2; exit 1
fi

W="$(mktemp -d -t wib655.XXXXXX)"
PORT=""
cleanup() { [[ -n "${PORT}" ]] && "${PGBIN}/pg_ctl" -D "${W}/pg" -m fast stop >/dev/null 2>&1; rm -rf "${W}"; }
trap cleanup EXIT
mkdir -p "${W}/src" "${W}/bin" "${W}/shim" "${W}/prov/scripts" "${W}/states" "${W}/logs" "${W}/pool" "${W}/gocache"

echo "== lab-platform ${LP_COMMIT}: labctl, migrate and the register-lab step, built from source =="
gh api "repos/peopleforrester/lab-platform/tarball/${LP_COMMIT}" >"${W}/lp.tgz"
tar -xzf "${W}/lp.tgz" -C "${W}/src"
LP="$(echo "${W}"/src/*/)"
# register-lab is a step of `labctl event up`, which also builds clusters, so it is called here on its own: the same
# store.RegisterLab call, with the same fields, that cmd/labctl/event.go makes for burn@2.1.0.
mkdir -p "${LP}/cmd/reglab655"
cat >"${LP}/cmd/reglab655/main.go" <<'GO'
package main

import (
	"context"
	"fmt"
	"os"

	"github.com/peopleforrester/lab-platform/internal/eventplan"
	"github.com/peopleforrester/lab-platform/internal/store"
)

func main() {
	ctx := context.Background()
	l, err := eventplan.Lookup("burn@2.1.0")
	if err == nil {
		var st *store.Store
		if st, err = store.New(ctx, os.Getenv("DATABASE_URL")); err == nil {
			t, rerr := l.Resolved()
			if err = rerr; err == nil {
				_, err = st.RegisterLab(ctx, store.LabSpec{Slug: l.Slug, Version: l.Version, Tier: t.Tier,
					Blueprint: t.Blueprint, DisplayName: l.DisplayName, Interfaces: l.Interfaces})
				fmt.Printf("lab %s registered: %s on %s\n", l.Ref(), t.Tier, t.Blueprint)
			}
		}
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "reglab:", err)
		os.Exit(1)
	}
}
GO
for c in labctl migrate reglab655; do
  ( cd "${LP}" && GOCACHE="${W}/gocache" go build -o "${W}/bin/${c}" "./cmd/${c}" )
done

echo "== a scratch Postgres with lab-platform's migrations =="
"${PGBIN}/initdb" -D "${W}/pg" -U lp --auth=trust >"${W}/initdb.log" 2>&1
# labctl's driver takes host and port from the URL's authority, so the server listens on loopback TCP. The port is
# drawn until one is free; a port another server holds fails pg_ctl's start, and the next one is tried.
for _ in 1 2 3 4 5 6 7 8; do
  p=$(( 40000 + RANDOM % 20000 ))
  if "${PGBIN}/pg_ctl" -D "${W}/pg" -w -l "${W}/pg.log" \
       -o "-p ${p} -k ${W} -c listen_addresses=127.0.0.1" start >/dev/null 2>&1; then PORT="${p}"; break; fi
done
[[ -n "${PORT}" ]] || { echo "FAIL: the scratch Postgres would not start; ${W}/pg.log:" >&2; cat "${W}/pg.log" >&2; exit 1; }
"${PGBIN}/createdb" -h 127.0.0.1 -p "${PORT}" -U lp lab
export DATABASE_URL="postgres://lp@127.0.0.1:${PORT}/lab?sslmode=disable" USER="wib655"
MIGRATIONS_DIR="${LP}/migrations" "${W}/bin/migrate"
"${W}/bin/reglab655"
export PATH="${W}/shim:${PATH}"
ln -s "${W}/bin/labctl" "${W}/shim/labctl"
labctl add-customer agenticburn "Agentic Burn" agenticburn.example >/dev/null
labctl create-event agenticburn burn@2.1.0 "${EVENT}" 5 4 >/dev/null
Q() { psql -h 127.0.0.1 -p "${PORT}" -U lp -d lab -X -A -t -c "$1"; }

# The cluster reads before the import. aws answers the Datadog pool secrets with an empty pool, as a loaded-but-empty
# secret would; kubectl names a console NLB; the harvester writes HARVEST_CRED as the terminal Secret's value.
cat >"${W}/shim/aws" <<'S'
#!/usr/bin/env bash
case "$*" in *"secretsmanager get-secret-value"*) printf '[]\n' ;; esac
exit 0
S
cat >"${W}/shim/kubectl" <<'S'
#!/usr/bin/env bash
case "$*" in *"get svc console"*) printf 'k8s-agent-console-abc.elb.us-west-2.amazonaws.com' ;; esac
exit 0
S
printf '#!/usr/bin/env bash\nexit 0\n' >"${W}/shim/terraform"
cat >"${W}/prov/scripts/harvest_terminal_credential.sh" <<'S'
#!/usr/bin/env bash
printf '%s\n' "${HARVEST_CRED:?}" >"$3/$1.terminal"
S
chmod +x "${W}"/shim/aws "${W}"/shim/kubectl "${W}"/shim/terraform "${W}/prov/scripts/harvest_terminal_credential.sh"
ATT=watch-it-burn-attendee-001
for n in "${ATT}" watch-it-burn-community watch-it-burn-private; do
  touch "${W}/states/${n}.tfstate"
  printf 'user,cluster,access_key,secret_key\nu,%s,AKIATEST%s,secret%s\n' "${n}" "${n##*-}" "${n##*-}" >"${W}/pool/${n}.csv"
done
fleet() { # $1: terminal login the harvester returns; the rest: fleet.sh's arguments. Output to ${W}/out, rc echoed.
  local cred="$1"; shift
  local rc=0
  HARVEST_CRED="${cred}" WIB_EVENT="${WIB_EVENT_OVERRIDE:-${EVENT}}" WIB_PROVISION_DIR="${W}/prov" \
    WIB_STATE_DIR="${W}/states" WIB_LOG_DIR="${W}/logs" WIB_AWS_POOL_DIR="${W}/pool" WIB_INGEST_LB_WAIT=10 \
    WIB_REGION=us-west-2 WIB_DEFAULT_ACCOUNT=accen-dev bash "${FLEET}" "$@" >"${W}/out" 2>&1 || rc=$?
  sed 's/^/    | /' "${W}/out"
  return "${rc}"
}
fails=0
check() { if eval "$2"; then echo "  ok   $1"; else echo "  FAIL $1"; fails=$((fails + 1)); fi; }
pool() { labctl pool --customer agenticburn --event "${EVENT}"; }

echo "== fleet.sh ingest ${ATT}, with a terminal password holding a comma and a quote =="
rc=0; fleet 'agentic:p,a"ss' ingest "${ATT}" || rc=$?
check "ingest exits 0 and logs labctl's 1 added" '[[ ${rc} -eq 0 ]] && grep -q "1 added, 0 updated" "${W}/out"'
check "the password is stored byte for byte (header and row quoted as @csv writes them)" \
  '[[ "$(Q "select access->>'"'"'terminal_password'"'"' from environment where provider_handle='"'"'${ATT}'"'"'")" == "p,a\"ss" ]]'
check "and terminal_user beside it" \
  '[[ "$(Q "select access->>'"'"'terminal_user'"'"' from environment where provider_handle='"'"'${ATT}'"'"'")" == agentic ]]'

echo "== fleet.sh ingest-instructors =="
rc=0; fleet agentic:agentic ingest-instructors || rc=$?
check "ingest-instructors exits 0, each roster cluster as role=instructor" \
  '[[ ${rc} -eq 0 ]] && [[ "$(grep -c "(role=instructor)" "${W}/out")" -eq 2 ]]'
pool | sed 's/^/    | /'
check "the attendee (sent with a blank role) is claimable" 'pool | grep -qx "${ATT},claimable,us-west-2,,"'
check "each roster cluster is held as instructor" \
  '[[ "$(pool | grep -c "^watch-it-burn-\(community\|private\),instructor,")" -eq 2 ]]'

echo "== three addresses claim through claim_environment, the function the claim page calls =="
EV="$(Q "select id from event where slug='${EVENT}'")"
got() { Q "select coalesce(e.provider_handle,'') from claim_environment('${EV}', '$1') c left join environment e on e.id = c.environment_id"; }
check "the first claim gets the attendee cluster" '[[ "$(got a@example.com)" == "${ATT}" ]]'
check "the second gets nothing: the roster rows are not in the pool" '[[ -z "$(got b@example.com)" ]]'
check "the third gets nothing either" '[[ -z "$(got c@example.com)" ]]'

echo "== re-ingest the claimed cluster by name, then ingest pool, each with a new terminal password =="
rc=0; fleet agentic:rotated-1 ingest "${ATT}" || rc=$?
check "re-ingest by name exits 0 with 0 added, 1 updated" '[[ ${rc} -eq 0 ]] && grep -q "0 added, 1 updated" "${W}/out"'
rc=0; fleet agentic:rotated-2 ingest pool || rc=$?
check "ingest pool re-ingests all three rows the pool lists" \
  '[[ ${rc} -eq 0 ]] && grep -q "re-ingesting 3 row(s)" "${W}/out" && [[ "$(grep -c "0 added, 1 updated" "${W}/out")" -eq 3 ]]'
check "the claim is unmoved: still claimed by the same address" 'pool | grep -qx "${ATT},claimed,us-west-2,,a@example.com"'
check "and the new terminal login is merged into the claimed row" \
  '[[ "$(Q "select access->>'"'"'terminal_password'"'"' from environment where provider_handle='"'"'${ATT}'"'"'")" == rotated-2 ]]'
check "the roster rows are still held" '[[ "$(pool | grep -c ",instructor,")" -eq 2 ]]'

echo "== a refused import is read from labctl's exit code =="
rc=0; WIB_EVENT_OVERRIDE=no-such-event fleet agentic:agentic ingest "${ATT}" || rc=$?
check "fleet.sh exits 1, naming labctl's refusal after three attempts, and records ingest:<name>" \
  '[[ ${rc} -eq 1 ]] && grep -q "after 3 attempts: labctl: store: no event" "${W}/out" && grep -q "ingest:${ATT}" "${W}/out"'

echo
if [[ "${fails}" -eq 0 ]]; then echo "ALL #655 IMPORT CHECKS GREEN (lab-platform ${LP_COMMIT})"; exit 0; fi
echo "${fails} #655 import check(s) FAILED (lab-platform ${LP_COMMIT})"; exit 1
