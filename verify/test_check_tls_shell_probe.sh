#!/usr/bin/env bash
# ABOUTME: Behavioural test for check-tls.sh's shell-protocol probe (#770): a terminal that answers 101 to ttyd's tty
# ABOUTME: subprotocol with no credential fails the check, while a refused one, and the plain upgrade's 101, pass.
#
# Usage: verify/test_check_tls_shell_probe.sh      (offline: curl and openssl are stubbed)
#
# Why (#770). check-tls.sh's websocket probe asks for no subprotocol, and ttyd answers that 101 to anyone because it
# binds such a socket to its HTTP handler, which starts no shell (verify/test_ttyd_ws_auth.py). So that 101 cannot
# tell an open terminal from a closed one. The second probe asks for `tty`, the protocol the shell is on: with no
# credential a credentialed ttyd never answers 101 there, so a 101 is a terminal open to anyone.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_TLS="${HERE}/../infra/terraform/fleet/check-tls.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

mkdir -p "${T}/bin"
# curl answers by what is asked: the tty upgrade gets $TTY_CODE (exit $TTY_RC, as curl exits on a dropped socket), any
# other upgrade $WS_CODE, http:// a redirect and https:// 200. Each call's arguments are logged.
cat >"${T}/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${CURL_LOG}"
case " $* " in
  *"Sec-WebSocket-Protocol: tty"*) printf '%s' "${TTY_CODE}"; exit "${TTY_RC:-0}" ;;
  *"Upgrade: websocket"*)          printf '%s' "${WS_CODE}" ;;
  *" http://"*)                    printf '301' ;;
  *)                               printf '200' ;;
esac
EOF
# openssl: a random key, an empty handshake, and a certificate that covers the host for a year.
cat >"${T}/bin/openssl" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  rand)     echo "c3R1YmJlZC1rZXktMTIzNA==" ;;
  s_client) cat >/dev/null ;;
  x509)     cat >/dev/null; echo "notAfter=$(date -u -d '+365 days' '+%b %d %H:%M:%S %Y GMT')"; echo "DNS:*.agenticburn.com" ;;
esac
EOF
chmod +x "${T}/bin/curl" "${T}/bin/openssl"

run() {   # $1 the plain upgrade's code, $2 the tty upgrade's code, $3 curl's exit on the tty probe; prints rc=<n>
    : >"${T}/curl.log"
    PATH="${T}/bin:${PATH}" CURL_LOG="${T}/curl.log" WS_CODE="$1" TTY_CODE="$2" TTY_RC="${3:-0}" \
        bash "${CHECK_TLS}" burritobot-private.agenticburn.com >"${T}/log" 2>&1
    echo "rc=$?"
}

echo "== check-tls.sh fails a terminal whose shell protocol opens with no credential =="
check "a credentialed terminal (plain upgrade 101, tty refused 502 by nginx) passes" \
  '[[ "$(run 101 502)" == rc=0 ]] && grep -q "PASS  the terminal.s shell protocol (tty) refuses an upgrade with no credential (502)" "${T}/log"'
check "a ttyd that drops the tty socket outright (curl prints 000, exits 52) passes, and the script runs on" \
  '[[ "$(run 101 000 52)" == rc=0 ]] && grep -q "refuses an upgrade with no credential (000)" "${T}/log" &&
   grep -q "TLS CHECKS GREEN" "${T}/log"'
check "a terminal that answers the tty upgrade with 101 fails, and says anyone gets a shell" \
  '[[ "$(run 101 101)" == rc=1 ]] &&
   grep -q "FAIL  the terminal.s shell protocol (tty) accepted an upgrade with NO credential (101): anyone who knows burritobot-private.agenticburn.com gets a shell" "${T}/log"'
check "the tty probe sends no credential" \
  '! grep "Sec-WebSocket-Protocol: tty" "${T}/curl.log" | grep -qi -e "authorization" -e " -u " -e "--user"'
check "the tty probe is pinned to HTTP/1.1 and goes to the terminal path" \
  'grep "Sec-WebSocket-Protocol: tty" "${T}/curl.log" | grep -q -- "--http1.1 .*https://burritobot-private.agenticburn.com/terminal/$"'
check "the plain upgrade probe still asks for no subprotocol" \
  'grep "Upgrade: websocket" "${T}/curl.log" | grep -v "Sec-WebSocket-Protocol" | grep -q "https://burritobot-private.agenticburn.com/terminal/$"'
check "--no-ws skips both upgrade probes" \
  ': >"${T}/curl.log"; PATH="${T}/bin:${PATH}" CURL_LOG="${T}/curl.log" WS_CODE=101 TTY_CODE=101 \
     bash "${CHECK_TLS}" --no-ws burritobot-private.agenticburn.com >"${T}/log" 2>&1 && ! grep -q "Upgrade: websocket" "${T}/curl.log"'

echo; echo "  ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]] || { echo "  (last log)"; sed "s/^/    /" "${T}/log"; }
exit $(( fail > 0 ))
