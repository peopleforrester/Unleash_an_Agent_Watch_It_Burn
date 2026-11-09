#!/usr/bin/env bash
# ABOUTME: Behavioural test for `fleet.sh start-check` (#1227): against two real desks (ticket_site.py) and a fake beacon on
# ABOUTME: 127.0.0.1, it fails while either deployments page lists a row or the count is above zero, and passes after reset.
#
# Usage: verify/test_fleet_start_check.sh      (offline: every server is local, railway is a stub)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
FLEET="${REPO}/infra/terraform/fleet/fleet.sh"
TICKET_SITE="${REPO}/gitops/ai-layer/ticket_site.py"
T="$(mktemp -d)"
PIDS=()
trap 'for p in "${PIDS[@]}"; do kill "${p}" 2>/dev/null; done; rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# Offline means offline (#859): aws, kubectl, eksctl, terraform and helm are stubs that log the call and fail.
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${HERE}/no-cloud.sh"; no_cloud_guard "${T}/no-cloud"

# A desk: the real ticket_site.py, its handler wrapped only to write each request's method and path to <dir>/requests.
# It listens on 127.0.0.1, so its own POST /desk-reset, which answers only the loopback, is the reset fleet.sh desk-reset
# makes from inside the pod.
cat >"${T}/desk.py" <<'PY'
import importlib.util, pathlib, sys
d = pathlib.Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("ticket_site", sys.argv[1])
ts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ts)

class H(ts.Handler):
    def log_message(self, *a):
        pass

    def note(self):
        with open(d / "requests", "a") as f:
            f.write(f"{self.command} {self.path}\n")

    def do_GET(self):
        self.note()
        super().do_GET()

    def do_POST(self):
        self.note()
        super().do_POST()

s = ts.Server(("127.0.0.1", 0), H)
(d / "port").write_text(str(s.server_address[1]))
s.serve_forever()
PY
# The beacon: GET /beacon/view renders data-count as provisioning-agenticburn's app.py does, POST /beacon/reset zeroes it
# for the token in ${T}/beacon/want, POST /seed sets it. Each request's method and path go to ${T}/beacon/requests.
cat >"${T}/beacon.py" <<'PY'
import http.server, json, pathlib, sys
d = pathlib.Path(sys.argv[1])
state = {"count": 0}

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, body, ctype):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def note(self):
        with open(d / "requests", "a") as f:
            f.write(f"{self.command} {self.path}\n")

    def do_POST(self):
        self.note()
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode() if n else ""
        if self.path == "/seed":
            state["count"] = int(raw)
            return self.reply(200, "seeded", "text/plain")
        if self.path != "/beacon/reset":
            return self.reply(404, "no", "text/plain")
        if self.headers.get("X-Admin-Token", "") != (d / "want").read_text().strip():
            return self.reply(403, "<h1>Forbidden</h1>", "text/html")
        cleared, state["count"] = state["count"], 0
        return self.reply(200, json.dumps({"cleared": cleared}), "application/json")

    def do_GET(self):
        self.note()
        if self.path != "/beacon/view":
            return self.reply(404, "no", "text/plain")
        if (d / "mode").read_text().strip() == "notview":
            return self.reply(200, "<html>a router page</html>", "text/html")
        return self.reply(200, f'<html><div class="total" data-count="{state["count"]}">{state["count"]}</div></html>',
                          "text/html")

s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
(d / "port").write_text(str(s.server_address[1]))
s.serve_forever()
PY

start() {   # $1 dir, then the server's command; waits for <dir>/port
    local dir="$1"; shift
    mkdir -p "${dir}"; : >"${dir}/requests"
    "$@" & PIDS+=("$!")
    for _ in $(seq 100); do [[ -s "${dir}/port" ]] && break; sleep 0.1; done
    [[ -s "${dir}/port" ]] || { echo "  FAIL  ${dir##*/} did not start"; exit 1; }
}
start "${T}/pub" python3 "${T}/desk.py" "${TICKET_SITE}" "${T}/pub"
start "${T}/priv" python3 "${T}/desk.py" "${TICKET_SITE}" "${T}/priv"
mkdir -p "${T}/beacon"; echo ok >"${T}/beacon/mode"
TOKEN="tok-$(od -An -N12 -tx1 /dev/urandom | tr -dc '0-9a-f')"
printf '%s' "${TOKEN}" >"${T}/beacon/want"
start "${T}/beacon" python3 "${T}/beacon.py" "${T}/beacon"
PUB="http://127.0.0.1:$(cat "${T}/pub/port")"
PRIV="http://127.0.0.1:$(cat "${T}/priv/port")"
BEACON="http://127.0.0.1:$(cat "${T}/beacon/port")"

# Set a fake's state directly, as a deploy and a beacon post would. A deploy row is POST /landed, the report deploy_app
# makes; a removed row is the same row, which the page still lists, greyed.
land() { curl -fsS -o /dev/null -X POST -H 'Content-Type: application/json' \
    --data "{\"name\":\"$2\",\"ok\":true,\"image\":\"registry.burritobot.co/burritobot/maintenance-shell\",\"kind\":\"Deployment\"}" \
    "$1/landed" || echo "  (could not land a row on $1)"; }
seed() { curl -fsS -o /dev/null -X POST --data "$1" "${BEACON}/seed" || echo "  (could not seed the beacon)"; }
desk_reset() { curl -fsS -o /dev/null -X POST -H 'Content-Type: application/json' --data '{}' "$1/desk-reset" \
    || echo "  (could not reset the desk at $1)"; }
rows() { curl -fsS "$1/deployments.json" | jq length; }

mkdir -p "${T}/bin" "${T}/home"
printf '#!/bin/sh\nexit 1\n' >"${T}/bin/railway"; chmod +x "${T}/bin/railway"
# Run the real entry point, `fleet.sh start-check`, with the two desks as its deployments hosts. Prints rc=<n>; its output
# goes to ${T}/log. Each fake's request log is emptied first, so ${T}/*/requests hold the check's requests alone.
FLEET_ENV=(env -u WIB_ADMIN_TOKEN HOME="${T}/home" PATH="${T}/bin:${PATH}" WIB_BEACON_VIEW_URL="${BEACON}/beacon/view")
start_check() {
    : >"${T}/pub/requests"; : >"${T}/priv/requests"; : >"${T}/beacon/requests"
    ( cd "$(dirname "${FLEET}")" && "${FLEET_ENV[@]}" WIB_START_DEPLOYMENTS="${HOSTS:-${PUB} ${PRIV}}" \
        bash "${FLEET}" start-check "$@" >"${T}/log" 2>&1; echo "rc=$?" )
}
only_gets() { ! grep -hv '^GET ' "${T}/pub/requests" "${T}/priv/requests" "${T}/beacon/requests" | grep -q .; }
read_all() { grep -qx 'GET /deployments.json' "${T}/pub/requests" && grep -qx 'GET /deployments.json' "${T}/priv/requests" &&
    grep -qx 'GET /beacon/view' "${T}/beacon/requests"; }

echo "== the start state passes =="
check "both pages empty and the count at zero passes" \
  '[[ "$(start_check)" == rc=0 ]] && grep -q "start-check: every deployments page lists no deploy and the beacon view reads zero" "${T}/log"'
check "  it read /deployments.json on both pages and the beacon view, with GETs alone" 'read_all && only_gets'
check "  and names each read as a PASS" \
  'grep -qF "PASS  ${PUB}/deployments.json lists 0 deploy rows" "${T}/log" &&
   grep -qF "PASS  ${PRIV}/deployments.json lists 0 deploy rows" "${T}/log" &&
   grep -qF "PASS  ${BEACON}/beacon/view reads 0 beacons" "${T}/log"'

echo "== a row on either page fails it =="
land "${PUB}" joker-agatha-the-gargoyle; land "${PUB}" joker-edgar-the-kelpie
check "two rows on the public page fail, naming the page and its 2 rows" \
  '[[ "$(start_check)" == rc=1 ]] && grep -qF "FAIL  ${PUB}/deployments.json lists 2 deploy row(s)" "${T}/log" &&
   grep -qF "PASS  ${PRIV}/deployments.json lists 0 deploy rows" "${T}/log" && grep -q "NOT at the start state" "${T}/log"'
check "  it posted nothing, and the rows are still there" 'only_gets && [[ "$(rows "${PUB}")" == 2 ]]'
desk_reset "${PUB}"
land "${PRIV}" joker-morwenna-the-banshee
check "a row on the private page alone fails, naming that page and its 1 row" \
  '[[ "$(start_check)" == rc=1 ]] && grep -qF "FAIL  ${PRIV}/deployments.json lists 1 deploy row(s)" "${T}/log" &&
   grep -qF "PASS  ${PUB}/deployments.json lists 0 deploy rows" "${T}/log" && only_gets && [[ "$(rows "${PRIV}")" == 1 ]]'
desk_reset "${PRIV}"
land "${PUB}" joker-agatha-the-gargoyle
# The cluster's own read (#1050) lists no Deployment, so the desk marks the row removed: the page shows it greyed.
curl -fsS -o /dev/null -X POST -H 'Content-Type: application/json' \
    --data "{\"taken_at\": $(( $(date +%s) + 5 )), \"ok\": true, \"kinds\": {\"Deployment\": []}}" "${PUB}/cluster-read" \
    || echo "  (could not post the cluster read)"
check "a row the page shows greyed, removed, still counts as a row" \
  '[[ -n "$(curl -fsS "${PUB}/deployments.json" | jq -r ".[0].removed_at")" ]] &&
   [[ "$(start_check)" == rc=1 ]] && grep -qF "FAIL  ${PUB}/deployments.json lists 1 deploy row(s)" "${T}/log" && only_gets'
desk_reset "${PUB}"

echo "== a count above zero fails it =="
seed 321
check "a count of 321 fails, naming the view and the count" \
  '[[ "$(start_check)" == rc=1 ]] && grep -qF "FAIL  ${BEACON}/beacon/view reads 321 beacon(s)" "${T}/log" &&
   grep -q "run '"'"'./fleet.sh beacon-reset'"'"'" "${T}/log"'
check "  both empty pages still PASS, it posted nothing, and the count is still 321" \
  '[[ "$(grep -c "PASS  .*lists 0 deploy rows" "${T}/log")" -eq 2 ]] && only_gets &&
   [[ "$(curl -fsS "${BEACON}/beacon/view" | grep -o "data-count=\"[0-9]*\"")" == "data-count=\"321\"" ]]'
seed 1
check "a count of 1 fails" '[[ "$(start_check)" == rc=1 ]] && grep -qF "reads 1 beacon(s)" "${T}/log"'

echo "== every failing read is named, together =="
seed 4; land "${PUB}" joker-agatha-the-gargoyle; land "${PRIV}" joker-edgar-the-kelpie; land "${PRIV}" joker-morwenna-the-banshee
check "rows on both pages and a count of 4 fail, and the last line names all three reads with what each held" \
  '[[ "$(start_check)" == rc=1 ]] &&
   tail -n 1 "${T}/log" | grep -qF "${PUB}/deployments.json 1 row(s); ${PRIV}/deployments.json 2 row(s); ${BEACON}/beacon/view 4 beacon(s)"'
check "  the first page's FAIL points at desk-reset; the other's says desk-reset clears only the first" \
  'grep -A1 -F "FAIL  ${PUB}/deployments.json" "${T}/log" | grep -F "run '"'"'./fleet.sh desk-reset'"'"'" >/dev/null &&
   grep -A1 -F "FAIL  ${PRIV}/deployments.json" "${T}/log" | grep -F "desk-reset clears only ${PUB};" >/dev/null'
check "  and nothing changed: 1 row, 2 rows, 4 beacons" \
  '[[ "$(rows "${PUB}")" == 1 && "$(rows "${PRIV}")" == 2 ]] &&
   [[ "$(curl -fsS "${BEACON}/beacon/view" | grep -o "data-count=\"[0-9]*\"")" == "data-count=\"4\"" ]]'

echo "== after the resets it passes =="
desk_reset "${PUB}"; desk_reset "${PRIV}"
( cd "$(dirname "${FLEET}")" && "${FLEET_ENV[@]}" WIB_ADMIN_TOKEN="${TOKEN}" WIB_PROVISIONING_URL="${BEACON}" \
    bash "${FLEET}" beacon-reset >"${T}/reset.log" 2>&1 ) || { echo "  (beacon-reset failed)"; sed 's/^/    /' "${T}/reset.log"; }
check "fleet.sh beacon-reset zeroed the fake beacon" 'grep -q "beacon-reset: done; the beacon view reads zero" "${T}/reset.log"'
check "after the desks' /desk-reset and beacon-reset, start-check passes" \
  '[[ "$(start_check)" == rc=0 ]] && read_all && only_gets'

echo "== a read it cannot make fails, naming it =="
check "an unreachable deployments host fails" \
  '[[ "$(HOSTS="${PUB} http://127.0.0.1:9" start_check)" == rc=1 ]] && grep -qF "FAIL  could not read http://127.0.0.1:9/deployments.json" "${T}/log"'
check "a host whose /deployments.json is a 404 fails, naming the code" \
  '[[ "$(HOSTS="${PUB} ${BEACON}" start_check)" == rc=1 ]] && grep -qF "${BEACON}/deployments.json answered 404, not 200" "${T}/log"'
echo notview >"${T}/beacon/mode"
check "a beacon page with no data-count fails as not the beacon view" \
  '[[ "$(start_check)" == rc=1 ]] && grep -q "shows no data-count, so it is not the beacon view" "${T}/log"'
echo ok >"${T}/beacon/mode"
check "an argument is a usage error" '[[ "$(start_check --empty)" == rc=2 ]] && grep -q "usage: start-check" "${T}/log"'

echo "== the default hosts and the hints =="
DEFAULTS="$(cd "$(dirname "${FLEET}")" && env -u WIB_START_DEPLOYMENTS -u WIB_BEACON_VIEW_URL bash -c \
    'source "'"${FLEET}"'" >/dev/null 2>&1; printf "%s|%s" "${WIB_START_DEPLOYMENTS}" "${WIB_BEACON_VIEW_URL}"')"
check "by default it reads the one page, deployments.burritobot.co, alone (#1220)" \
  '[[ "${DEFAULTS%%|*}" == "https://deployments.burritobot.co" ]]'
check "  not the private cluster's own page, which redirects to it since #1220" \
  '[[ "${DEFAULTS%%|*}" != *deployments-burritobot-private* ]] &&
   grep -qF "deployments-burritobot-private.burritobot.co" "${REPO}/gitops/ai-layer/components/public-desk/private-desk-redirect.conf"'
check "and the beacon view beacon-reset checks, beacon.burritobot.co/beacon/view" \
  '[[ "${DEFAULTS#*|}" == "https://beacon.burritobot.co/beacon/view" ]]'
check "start-check runs no POST and no kubectl: its body names neither" \
  '! sed -n "/^cmd_start_check()/,/^}/p" "${FLEET}" | grep -E -- "-X POST|kubectl|--data" >/dev/null'

echo "== wiring =="
check "fleet.sh dispatches start-check" 'grep -qF "        start-check) cmd_start_check \"\$@\" ;;" "${FLEET}"'
check "the usage text names start-check" 'grep -q "^    start-check " "${FLEET}"'

echo "== offline means offline =="
check "no check above called aws, kubectl, eksctl, terraform or helm" 'no_cloud_clean'

echo; echo "  ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]] || { echo "  (last log)"; sed "s/^/    /" "${T}/log"; }
exit $(( fail > 0 ))
