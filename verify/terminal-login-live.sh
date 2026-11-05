#!/usr/bin/env bash
# ABOUTME: Live check for #912: a roster cluster's terminal takes the presenter login from mrf-secrets and refuses the
# ABOUTME: old one, on ttyd (/terminal/), code-server (/ide/) and Jupyter (/jupyter/). Prints verdicts, never a value.
#
# Usage: verify/terminal-login-live.sh <kube-context> <base-url> [<base-url> ...]
#   e.g. verify/terminal-login-live.sh watch-it-burn-private https://burritobot-private.burritobot.co
#        verify/terminal-login-live.sh watch-it-burn-community https://<its console load balancer name>
#
# Run it where mrf-secrets is checked out: the new login is read by fleet.sh's own presenter_login (#910), from
# WIB_TERMINAL_USER and WIB_TERMINAL_PASSWORD when set, else from WIB_TERMINAL_ENV (default
# ~/secrets/projects/watch-it-burn-terminal.env). The old login is the one fleet.sh carried as its default before
# #910 (ce43342c), read from git history, which is public; it is checked against the digest
# verify/test_no_presenter_login.py guards, so a wrong revision fails here rather than passing a check on the wrong
# value. Both reach curl through a config on a file descriptor, never on its command line, and neither is printed.
#
# Checks: the cluster's terminal-auth Secret holds the mrf-secrets login (and not the old one); each base URL answers
# /terminal/ with 401 unauthenticated, 401 to the old login and 200 to the new; /ide/login refuses the old password
# (no redirect) and takes the new (302); /jupyter/api/status answers 403 to the old token and 200 to the new.
# Exits 1 on any failed check, 2 on a usage error, and fails loudly when either login cannot be read.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
FLEET="${WIB_FLEET_SH:-${REPO}/infra/terraform/fleet/fleet.sh}"
# The fleet.sh revision just before #910 removed the default, and the digest of the old login word (user and password
# were the same word) that verify/test_no_presenter_login.py holds.
OLD_REV="ce43342c^"
OLD_SHA256="${WIB_OLD_LOGIN_SHA256:-b86ed20f4e99fefb9e3a0b4e5fbbbe692903b109197c7943be07494af87bf537}"

[[ $# -ge 2 ]] || { echo "usage: $0 <kube-context> <base-url> [<base-url> ...]" >&2; exit 2; }
CONTEXT="$1"; shift
[[ -n "${CONTEXT}" ]] || { echo "no kube-context given; this check never falls back to the current-context" >&2; exit 2; }

fail=0; pass=0
check() { if [[ "$2" == "$3" ]]; then pass=$((pass+1)); echo "  PASS  $1 (got $2)"; else fail=$((fail+1)); echo "  FAIL  $1 (got $2, want $3)"; fi; }

# The old login, from WIB_OLD_FLEET_SH (a test's own copy) or git history.
if [[ -n "${WIB_OLD_FLEET_SH:-}" ]]; then
    old_src="$(cat "${WIB_OLD_FLEET_SH}" 2>/dev/null)"
else
    old_src="$(git -C "${REPO}" show "${OLD_REV}:infra/terraform/fleet/fleet.sh" 2>/dev/null)"
fi
old_user="$(sed -nE 's/^WIB_TERMINAL_USER="\$\{WIB_TERMINAL_USER:-([^}]*)\}".*/\1/p' <<<"${old_src}")"
old_pw="$(sed -nE 's/^WIB_TERMINAL_PASSWORD="\$\{WIB_TERMINAL_PASSWORD:-([^}]*)\}".*/\1/p' <<<"${old_src}")"
if [[ -z "${old_user}" || -z "${old_pw}" ]]; then
    echo "FAIL  could not read the old login's two default lines from fleet.sh at ${OLD_REV} (a shallow clone has no history)" >&2
    exit 1
fi
if [[ "$(printf '%s' "${old_user}" | sha256sum | cut -d' ' -f1)" != "${OLD_SHA256}" ]]; then
    echo "FAIL  the old login read from ${OLD_REV} does not match the digest verify/test_no_presenter_login.py guards" >&2
    exit 1
fi
old="${old_user}:${old_pw}"

# The new login, by fleet.sh's presenter_login: its own messages (which file, which key) pass through, values do not.
new="$(bash -c 'source "$1" >/dev/null 2>&1 </dev/null; presenter_login' _ "${FLEET}")" || {
    echo "FAIL  no presenter login to check against: it lives in mrf-secrets (projects/watch-it-burn-terminal.env)" >&2
    exit 1
}
new_pw="${new#*:}"
if [[ "${new}" == "${old}" || "${new_pw}" == "${old_pw}" ]]; then
    echo "FAIL  the presenter login in mrf-secrets is still the old one; generate a new one there first" >&2
    exit 1
fi

# A value inside a curl config string: backslash and double quote escaped.
cq() { local v="${1//\\/\\\\}"; printf '"%s"' "${v//\"/\\\"}"; }
# status <url> [<curl config line> ...]: the HTTP status, the credential coming in on the config.
status() {
    local url="$1"; shift
    curl -ks -o /dev/null -w '%{http_code}' --max-time 15 -K <(printf '%s\n' "$@") "${url}" 2>/dev/null || true
}

echo "== ${CONTEXT}: the terminal-auth Secret =="
cur="$(kubectl --context "${CONTEXT}" -n agent get secret terminal-auth -o jsonpath='{.data.TTYD_CREDENTIAL}' 2>/dev/null \
    | base64 -d 2>/dev/null)"
if [[ -z "${cur}" ]]; then which="no Secret (the terminal is open)"
elif [[ "${cur}" == "${new}" ]]; then which="the mrf-secrets login"
elif [[ "${cur}" == "${old}" ]]; then which="the old login"
else which="another login"
fi
check "terminal-auth holds the presenter login from mrf-secrets" "${which}" "the mrf-secrets login"

for base in "$@"; do
    base="${base%/}"
    echo "== ${base} =="
    check "/terminal/ refuses no login" "$(status "${base}/terminal/")" 401
    check "/terminal/ refuses the old login" "$(status "${base}/terminal/" "user = $(cq "${old}")")" 401
    check "/terminal/ opens with the new login" "$(status "${base}/terminal/" "user = $(cq "${new}")")" 200
    check "/ide/login refuses the old password" \
        "$(status "${base}/ide/login" "data-urlencode = $(cq "password=${old_pw}")")" 200
    check "/ide/login takes the new password" \
        "$(status "${base}/ide/login" "data-urlencode = $(cq "password=${new_pw}")")" 302
    check "/jupyter/ refuses the old token" \
        "$(status "${base}/jupyter/api/status" "header = $(cq "Authorization: token ${old_pw}")")" 403
    check "/jupyter/ takes the new token" \
        "$(status "${base}/jupyter/api/status" "header = $(cq "Authorization: token ${new_pw}")")" 200
done

echo
echo "${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]] || exit 1
echo "THE TERMINAL TAKES THE MRF-SECRETS LOGIN AND REFUSES THE OLD ONE on ${CONTEXT}"
