#!/usr/bin/env bash
# ABOUTME: Pre-doors check that an attendee hostname actually works over HTTPS: cert, redirect, and the
# ABOUTME: websocket upgrade the terminal depends on. Read-only, no cluster access needed.
#
# This is the check most likely to catch a room-wide failure, and the one most likely to fail FALSELY
# if written naively, so the traps are handled explicitly rather than discovered on the morning:
#
#   * The websocket probe MUST pin HTTP/1.1. curl negotiates HTTP/2 via ALPN where the Upgrade header
#     is not valid, so a perfectly working terminal reports 404 or 400 and reads as broken.
#   * Never write `|| echo 000` after a `%{http_code}` format. curl already emits 000 on failure, so the
#     fallback produces "000000", which matches no comparison and silently skips the check.
#   * Cert expiry is checked with a MARGIN. A certificate that expires the morning after the workshop
#     passes a naive "is it valid now" test and is still a problem worth knowing about.
set -euo pipefail

MARGIN_DAYS="${WIB_CERT_MARGIN_DAYS:-7}"
fail=0
ok()   { printf '  PASS  %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; fail=1; }
note() { printf '  note  %s\n' "$*"; }

WS_PATH="${WIB_WS_PATH:-/terminal/}"
CHECK_WS=1
CLOSED_TERMINAL=0

usage() {
    cat >&2 <<EOF
Usage: ${0##*/} [--no-ws | --closed-terminal] <hostname> [hostname...]

  --no-ws   Skip the websocket probe. Use for hosts that legitimately have no terminal (the
            provisioning app, the apex router), where a 404 there means "correct", not "broken".
            Override the path instead with WIB_WS_PATH=/some/path/.
  --closed-terminal
            The host is a cluster console whose terminal the router closes: the public bot,
            attackme, on either domain (apex-agenticburn#43, #44). Both upgrade probes must get
            the router's 404, so a router that stops closing it fails here instead of passing.

Asserts, per hostname:
  * https:// returns 200
  * the TLS chain validates and the SAN covers this host
  * the certificate is valid for at least ${MARGIN_DAYS} more days
  * http:// redirects to https://
  * a websocket Upgrade on ${WS_PATH} is accepted (pinned to HTTP/1.1)
  * the same Upgrade on ttyd's shell protocol (tty) with no credential is NOT accepted

Read-only. Exits non-zero if any host fails.
EOF
    exit 2
}

while [[ "${1:-}" == --* ]]; do
    case "$1" in
        --no-ws) CHECK_WS=0; shift ;;
        --closed-terminal) CLOSED_TERMINAL=1; shift ;;
        -h|--help) usage ;;
        *) echo "unknown flag: $1" >&2; usage ;;
    esac
done

[[ "${CHECK_WS}" -eq 0 && "${CLOSED_TERMINAL}" -eq 1 ]] \
    && { echo "--no-ws and --closed-terminal contradict: one skips the probe the other asserts" >&2; usage; }
[[ $# -ge 1 ]] || usage
command -v openssl >/dev/null 2>&1 || { echo "openssl not found" >&2; exit 1; }

for host in "$@"; do
    echo "== ${host} =="

    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://${host}/" 2>/dev/null)"
    [[ "${code}" == "200" ]] && ok "https 200" || bad "https returned '${code:-no response}'"

    # -verify_return_error turns a chain failure into a non-zero exit instead of a printed warning.
    if cert="$(echo | openssl s_client -servername "${host}" -connect "${host}:443" \
                 -verify_return_error 2>/dev/null | openssl x509 -noout -dates -ext subjectAltName 2>/dev/null)"; then
        ok "TLS chain validates"
        # A wildcard (*.agenticburn.com) legitimately covers bane-sabrina.agenticburn.com, so compare on the
        # parent domain rather than requiring the literal host to appear in the SAN list.
        parent="${host#*.}"
        if grep -q -e "DNS:${host}" -e "DNS:\*\.${parent}" <<<"${cert}"; then
            ok "SAN covers ${host}"
        else
            bad "SAN does NOT cover ${host} (browsers will warn)"
        fi
        not_after="$(sed -n 's/^notAfter=//p' <<<"${cert}")"
        if [[ -n "${not_after}" ]]; then
            exp="$(date -d "${not_after}" +%s 2>/dev/null || echo 0)"
            now="$(date +%s)"
            days=$(( (exp - now) / 86400 ))
            if (( exp > 0 && days >= MARGIN_DAYS )); then
                ok "cert valid ${days} more day(s)"
            else
                bad "cert expires in ${days} day(s), under the ${MARGIN_DAYS}-day margin (${not_after})"
            fi
        fi
    else
        bad "TLS chain does NOT validate"
    fi

    redirect="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "http://${host}/" 2>/dev/null)"
    case "${redirect}" in
        30[1278]) ok "http redirects to https (${redirect})" ;;
        200)      note "http serves 200 directly (no redirect); fine behind a TLS-terminating router" ;;
        *)        bad "http returned '${redirect:-no response}'" ;;
    esac

    # --http1.1 is load-bearing here, see the header.
    if [[ "${CHECK_WS}" -eq 0 ]]; then
        note "websocket probe skipped (--no-ws)"
        echo
        continue
    fi
    ws="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 --http1.1 \
        -H "Connection: Upgrade" -H "Upgrade: websocket" \
        -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: $(openssl rand -base64 16)" \
        "https://${host}${WS_PATH}" 2>/dev/null)"
    if [[ "${CLOSED_TERMINAL}" -eq 1 ]]; then
        # The public bot (#651's Night Before line). The router answers 404 on the terminal's path before the
        # console sees it, so both upgrades, the plain one and the shell's own tty one, must get that 404.
        shell="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 --http1.1 \
            -H "Connection: Upgrade" -H "Upgrade: websocket" -H "Sec-WebSocket-Protocol: tty" \
            -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: $(openssl rand -base64 16)" \
            "https://${host}${WS_PATH}" 2>/dev/null)" || true
        if [[ "${ws}" == 404 && "${shell}" == 404 ]]; then
            ok "the router closes the terminal: both websocket upgrades on ${WS_PATH} get 404"
        else
            bad "the terminal is NOT closed on ${host}: the upgrade got '${ws:-no response}' and the tty upgrade '${shell:-no response}', not 404 (the router's @terminal_on_public_bot)"
        fi
        echo
        continue
    fi
    case "${ws}" in
        101) ok "websocket upgrade accepted (101)" ;;
        401) ok "websocket endpoint reachable, auth required (401) — expected once ttyd has a credential" ;;
        *)   bad "websocket upgrade returned '${ws:-no response}' (expected 101, or 401 when credentialed)" ;;
    esac

    # The shell's own protocol, with no credential (#770). The probe above asks for no subprotocol, and ttyd binds
    # such a socket to its HTTP handler, which never starts a shell, so it answers 101 to anyone: that 101 says the
    # upgrade gets through, not that the terminal is closed. ttyd's shell is only on the `tty` subprotocol, which
    # checks the Basic credential at the upgrade, so a credentialed terminal never answers 101 here (ttyd drops the
    # socket, which the console's nginx turns into a 502). A 101 means the terminal hands a shell to anyone who can
    # reach the host. verify/test_ttyd_ws_auth.py holds ttyd's side of this. `|| true` because curl exits non-zero
    # on a dropped socket; what it printed is still the code.
    shell="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 --http1.1 \
        -H "Connection: Upgrade" -H "Upgrade: websocket" -H "Sec-WebSocket-Protocol: tty" \
        -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: $(openssl rand -base64 16)" \
        "https://${host}${WS_PATH}" 2>/dev/null)" || true
    if [[ "${shell}" == "101" ]]; then
        bad "the terminal's shell protocol (tty) accepted an upgrade with NO credential (101): anyone who knows ${host} gets a shell"
    else
        ok "the terminal's shell protocol (tty) refuses an upgrade with no credential (${shell:-no response})"
    fi
    echo
done

if [[ "${fail}" -eq 0 ]]; then
    echo "TLS CHECKS GREEN for $# host(s)."
    exit 0
fi
echo "TLS CHECKS FAILED — see above." >&2
exit 1
