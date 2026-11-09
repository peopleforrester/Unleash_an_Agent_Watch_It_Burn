#!/usr/bin/env bash
# ABOUTME: Behavioural test for `fleet.sh beacon-reset` (#1226): it POSTs /beacon/reset to a local fake beacon with the
# ABOUTME: admin token in X-Admin-Token, passes only when the view then reads zero, and never prints the token.
#
# Usage: verify/test_fleet_beacon_reset.sh      (offline: the beacon is a fake on 127.0.0.1, railway and aws are stubs)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d)"
FAKE_PID=""
trap '[[ -n "${FAKE_PID}" ]] && kill "${FAKE_PID}" 2>/dev/null; rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# Offline means offline (#859): aws, kubectl, eksctl, terraform and helm are stubs that log the call and fail.
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${HERE}/no-cloud.sh"; no_cloud_guard "${T}/no-cloud"

# A token made here, per run, so no token is in the repo, this test included.
TOKEN="tok-$(od -An -N12 -tx1 /dev/urandom | tr -dc '0-9a-f')"
[[ "${#TOKEN}" -gt 20 ]] || { echo "  FAIL  could not make a test token"; exit 1; }

# The fake provisioning app: POST /beacon/reset and GET /beacon/view, as provisioning-agenticburn's app.py serves
# them. ${T}/mode, read on each request, picks how it answers: ok (a reset to zero), stuck (the reset answers 200 and
# the count stays), noview (the view answers 500), notview (a 200 page with no data-count). It answers 403 unless the
# X-Admin-Token header is ${T}/want, and writes each request's method, path and token to ${T}/requests.
cat >"${T}/fake.py" <<'PY'
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
            f.write(f"{self.command} {self.path} {self.headers.get('X-Admin-Token', '-')}\n")

    def do_POST(self):
        self.note()
        if self.path != "/beacon/reset":
            return self.reply(404, "no", "text/plain")
        if self.headers.get("X-Admin-Token", "") != (d / "want").read_text().strip():
            return self.reply(403, "<h1>Forbidden</h1>", "text/html")
        cleared = state["count"]
        if (d / "mode").read_text().strip() != "stuck":
            state["count"] = 0
        return self.reply(200, json.dumps({"cleared": cleared}), "application/json")

    def do_GET(self):
        self.note()
        mode = (d / "mode").read_text().strip()
        if self.path == "/seed":
            state["count"] = int((d / "seed").read_text())
            return self.reply(200, "seeded", "text/plain")
        if self.path != "/beacon/view":
            return self.reply(404, "no", "text/plain")
        if mode == "noview":
            return self.reply(500, "boom", "text/plain")
        if mode == "notview":
            return self.reply(200, "<html>a router page</html>", "text/html")
        return self.reply(200, f'<html><div class="total" data-count="{state["count"]}">{state["count"]}</div></html>',
                          "text/html")

s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
(d / "port").write_text(str(s.server_address[1]))
s.serve_forever()
PY
echo ok >"${T}/mode"; printf '%s' "${TOKEN}" >"${T}/want"
python3 "${T}/fake.py" "${T}" & FAKE_PID=$!
for _ in $(seq 50); do [[ -s "${T}/port" ]] && break; sleep 0.1; done
[[ -s "${T}/port" ]] || { echo "  FAIL  the fake beacon did not start"; exit 1; }
FAKE="http://127.0.0.1:$(cat "${T}/port")"

# No Railway login reaches the test: a railway stub that answers nothing, ahead of the host's on PATH, and an empty
# HOME with no secrets env file, so the token is only what each case gives.
mkdir -p "${T}/bin" "${T}/home"
printf '#!/bin/sh\nexit 1\n' >"${T}/bin/railway"; chmod +x "${T}/bin/railway"

# The Secrets Manager copy (#1239) is a fake aws ahead of the no-cloud stub: it writes its profile and every argument
# to ${T}/aws-calls, and answers get-secret-value with ${T}/secret as SecretString when that file exists. Without it,
# it answers as the CLI does for a secret that is not there: an error on stderr, carrying a marker the log must not
# show, and exit 254. curl is a shim that writes its arguments to ${T}/curl-calls and runs the host's curl, so each
# case can check the token was on no command line.
cat >"${T}/bin/aws" <<EOF
#!/bin/sh
printf 'AWS_PROFILE=%s %s\n' "\${AWS_PROFILE:-}" "\$*" >>"${T}/aws-calls"
case "\$*" in
  "secretsmanager get-secret-value "*)
    if [ -f "${T}/secret" ]; then cat "${T}/secret"; echo; exit 0; fi
    echo "AWS-STDERR-MARKER ResourceNotFoundException: Secrets Manager can't find the specified secret." >&2
    exit 254 ;;
esac
echo "fake aws: unexpected call" >&2; exit 1
EOF
REAL_CURL="$(command -v curl)"
printf '#!/bin/sh\nprintf "%%s\\n" "$*" >>"%s"\nexec "%s" "$@"\n' "${T}/curl-calls" "${REAL_CURL}" >"${T}/bin/curl"
chmod +x "${T}/bin/aws" "${T}/bin/curl"
: >"${T}/aws-calls"; : >"${T}/curl-calls"

# Run the real entry point, `fleet.sh beacon-reset`, against the fake: $1 the beacon count before, $2 the mode, the
# rest the verb's arguments. Prints rc=<n>; stdout and stderr go to ${T}/log. TOK is the WIB_ADMIN_TOKEN the verb gets;
# without it the verb gets none, whatever the caller's environment exports.
reset() {   # $1 seed count, $2 mode, then args
    local seed="$1" mode="$2" tok=(); shift 2
    [[ -n "${TOK:-}" ]] && tok=("WIB_ADMIN_TOKEN=${TOK}")
    printf '%s' "${seed}" >"${T}/seed"; echo ok >"${T}/mode"
    curl -fsS -o /dev/null "${FAKE}/seed" || echo "  (could not seed the fake)"
    echo "${mode}" >"${T}/mode"; : >"${T}/requests"; : >"${T}/aws-calls"; : >"${T}/curl-calls"
    ( cd "$(dirname "${FLEET}")" && env -u WIB_ADMIN_TOKEN "${tok[@]}" HOME="${HOME_DIR:-${T}/home}" PATH="${T}/bin:${PATH}" \
        WIB_PROVISIONING_URL="${PROV_URL:-${FAKE}}" WIB_BEACON_VIEW_URL="${FAKE}/beacon/view" \
        bash "${FLEET}" beacon-reset "$@" >"${T}/log" 2>&1; echo "rc=$?" )
}
no_token() { ! grep -qF "${TOKEN}" "${T}/log"; }

echo "== beacon-reset zeroes the count and checks the view =="
check "a reset to zero passes" '[[ "$(TOK="${TOKEN}" reset 273 ok)" == rc=0 ]]'
check "the fake got POST /beacon/reset with the token in X-Admin-Token" \
  'grep -qxF "POST /beacon/reset ${TOKEN}" "${T}/requests"'
check "then it read /beacon/view" 'grep -q "^GET /beacon/view " "${T}/requests"'
check "the reset came before the read" \
  '[[ "$(grep -n "^POST /beacon/reset" "${T}/requests" | cut -d: -f1)" -lt "$(grep -n "^GET /beacon/view" "${T}/requests" | cut -d: -f1)" ]]'
check "the output names the beacons cleared and the zero read" \
  'grep -q "cleared 273 beacon(s)" "${T}/log" && grep -q "beacon-reset: done; the beacon view reads zero" "${T}/log"'
check "the token is not in the output" 'no_token'
check "an already-zero count passes" '[[ "$(TOK="${TOKEN}" reset 0 ok)" == rc=0 ]] && no_token'

echo "== it fails, naming the cause =="
check "a refused reset (403) fails" '[[ "$(TOK="${TOKEN}-wrong" reset 5 ok)" == rc=1 ]]'
check "  and names the 403 and the token to check" \
  'grep -q "refused the reset (403)" "${T}/log" && grep -q "WIB_ADMIN_TOKEN" "${T}/log"'
check "  and never reads the view as a pass" '! grep -q "reads zero" "${T}/log" && no_token && ! grep -qF "${TOKEN}-wrong" "${T}/log"'
check "a count that stays above zero fails" '[[ "$(TOK="${TOKEN}" reset 7 stuck)" == rc=1 ]]'
check "  and names the count it still reads" 'grep -q "still reads 7 beacon(s) after the reset" "${T}/log" && no_token'
check "a view that cannot be read fails" '[[ "$(TOK="${TOKEN}" reset 4 noview)" == rc=1 ]]'
check "  and names the view" 'grep -qF "could not read ${FAKE}/beacon/view" "${T}/log" && no_token'
check "a 200 page with no data-count fails as not the beacon view" \
  '[[ "$(TOK="${TOKEN}" reset 4 notview)" == rc=1 ]] && grep -q "shows no data-count" "${T}/log"'
check "an unreachable provisioning app fails, naming it" \
  '[[ "$(PROV_URL="http://127.0.0.1:9" TOK="${TOKEN}" reset 4 ok)" == rc=1 ]] &&
   grep -qF "could not reach http://127.0.0.1:9/beacon/reset" "${T}/log" && no_token'
check "an argument is a usage error" '[[ "$(TOK="${TOKEN}" reset 4 ok extra)" == rc=2 ]] && grep -q "usage: beacon-reset" "${T}/log"'

echo "== the token comes from resolve_admin_token =="
check "with no token anywhere it fails" '[[ "$(reset 4 ok)" == rc=1 ]]'
check "  naming WIB_ADMIN_TOKEN, a Railway login and the secrets env file" \
  'grep -q "cannot resolve the provisioning admin token" "${T}/log" && grep -q "WIB_ADMIN_TOKEN" "${T}/log" &&
   grep -q "railway login" "${T}/log" && grep -qF "~/secrets/projects/watch-it-burn-provisioning.env" "${T}/log"'
check "  and the Secrets Manager secret, its account and region" \
  'grep -qF "Secrets Manager secret watch-it-burn/provisioning-admin-token in accen-dev us-west-2" "${T}/log"'
check "  and posts nothing" '! grep -q "^POST" "${T}/requests"'
check "  and shows none of aws's error text" '! grep -q "AWS-STDERR-MARKER" "${T}/log"'
mkdir -p "${T}/home2/secrets/projects"; printf 'ADMIN_TOKEN="%s"\n' "${TOKEN}" >"${T}/home2/secrets/projects/watch-it-burn-provisioning.env"
check "a token from the secrets env file passes" \
  '[[ "$(HOME_DIR="${T}/home2" reset 3 ok)" == rc=0 ]] &&
   grep -qxF "POST /beacon/reset ${TOKEN}" "${T}/requests" && no_token'

echo "== the Secrets Manager copy, a dispatched run's route (#1239) =="
printf '%s' "${TOKEN}" >"${T}/secret"
check "a token from the secret, as a plain string, passes" \
  '[[ "$(reset 321 ok)" == rc=0 ]] && grep -qxF "POST /beacon/reset ${TOKEN}" "${T}/requests" &&
   grep -q "beacon-reset: done; the beacon view reads zero" "${T}/log"'
check "  read in the default account and the secrets region, the token's secret by name, its SecretString as text" \
  'grep -qxF "AWS_PROFILE=accen-dev secretsmanager get-secret-value --secret-id watch-it-burn/provisioning-admin-token --region us-west-2 --query SecretString --output text" "${T}/aws-calls"'
check "  with the token in no output" 'no_token'
check "  and on no command line, aws's or curl's" '! grep -qF "${TOKEN}" "${T}/aws-calls" && [[ -s "${T}/curl-calls" ]] && ! grep -qF "${TOKEN}" "${T}/curl-calls"'
printf '{"ADMIN_TOKEN": "%s"}' "${TOKEN}" >"${T}/secret"
check "a token from the secret, as JSON with an ADMIN_TOKEN key, passes" \
  '[[ "$(reset 5 ok)" == rc=0 ]] && grep -qxF "POST /beacon/reset ${TOKEN}" "${T}/requests" && no_token &&
   ! grep -qF "${TOKEN}" "${T}/aws-calls" && ! grep -qF "${TOKEN}" "${T}/curl-calls"'
printf '{"other": "x"}' >"${T}/secret"
check "a JSON secret with no ADMIN_TOKEN key fails as no token, posting nothing" \
  '[[ "$(reset 5 ok)" == rc=1 ]] && grep -q "cannot resolve the provisioning admin token" "${T}/log" && ! grep -q "^POST" "${T}/requests"'
printf '%s-stale' "${TOKEN}" >"${T}/secret"
check "a stale copy in the secret is refused (403) and named" \
  '[[ "$(reset 5 ok)" == rc=1 ]] && grep -q "refused the reset (403)" "${T}/log" &&
   grep -qF "watch-it-burn/provisioning-admin-token" "${T}/log" && ! grep -qF "${TOKEN}" "${T}/log"'
check "the secrets env file comes before the secret: aws is not called" \
  '[[ "$(HOME_DIR="${T}/home2" reset 3 ok)" == rc=0 ]] && grep -qxF "POST /beacon/reset ${TOKEN}" "${T}/requests" && [[ ! -s "${T}/aws-calls" ]]'
check "an exported WIB_ADMIN_TOKEN comes before the secret: aws is not called" \
  '[[ "$(TOK="${TOKEN}" reset 3 ok)" == rc=0 ]] && [[ ! -s "${T}/aws-calls" ]]'
rm -f "${T}/secret"

echo "== wiring =="
check "fleet.sh dispatches beacon-reset" 'grep -qF "        beacon-reset) cmd_beacon_reset \"\$@\" ;;" "${FLEET}"'
check "the usage text names beacon-reset" 'grep -q "^    beacon-reset " "${FLEET}"'
check "the token goes to curl on stdin, not on its command line" \
  'sed -n "/^cmd_beacon_reset()/,/^}/p" "${FLEET}" | grep -F -- "-H @-" >/dev/null &&
   ! sed -n "/^cmd_beacon_reset()/,/^}/p" "${FLEET}" | grep -E "curl[^|]*X-Admin-Token" >/dev/null'

echo "== offline means offline =="
check "no check above called aws, kubectl, eksctl, terraform or helm" 'no_cloud_clean'

echo; echo "  ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]] || { echo "  (last log)"; sed "s/^/    /" "${T}/log"; }
exit $(( fail > 0 ))
