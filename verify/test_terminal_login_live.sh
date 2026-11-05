#!/usr/bin/env bash
# ABOUTME: Offline tests for verify/terminal-login-live.sh (#912): with kubectl and curl shimmed, it passes only when the
# ABOUTME: Secret and all three tools take the mrf-secrets login and refuse the old one, and never prints or argv's a value.
#
# Usage: verify/test_terminal_login_live.sh      (no cloud access; kubectl and curl are shims, both logins are placeholders)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE="${HERE}/terminal-login-live.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${HERE}/no-cloud.sh"; no_cloud_guard "${T}/no-cloud"

# The test's own logins. The old one has the shape fleet.sh's pre-#910 default had (user and password one word); the
# new password carries a double quote and a backslash, so the curl config quoting is exercised.
OLD_WORD="placeholderoldword"
NEW_USER="placeholder-new-user"
NEW_PW='placeholder"new\pw'
cat >"${T}/old-fleet.sh" <<EOF
WIB_TERMINAL_USER="\${WIB_TERMINAL_USER:-${OLD_WORD}}"          # instructor / admin clusters
WIB_TERMINAL_PASSWORD="\${WIB_TERMINAL_PASSWORD:-${OLD_WORD}}"
EOF
OLD_SHA="$(printf '%s' "${OLD_WORD}" | sha256sum | cut -d' ' -f1)"
printf 'WIB_TERMINAL_USER=%s\nexport WIB_TERMINAL_PASSWORD=%s\n' "${NEW_USER}" "${NEW_PW}" >"${T}/new.env"
printf 'WIB_TERMINAL_USER=%s\nWIB_TERMINAL_PASSWORD=%s\n' "${OLD_WORD}" "${OLD_WORD}" >"${T}/old.env"

# kubectl: logs its argv; `get secret terminal-auth` answers base64 of ${T}/secret, NotFound when it is absent.
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $*" >>"${CALLS}"
case "$*" in
    *"get secret terminal-auth"*) [[ -f "${T}/secret" ]] || exit 1; printf '%s' "$(base64 -w0 <"${T}/secret")" ;;
    *) exit 1 ;;
esac
S
# curl: logs its argv, reads the credential from the -K config only, and answers as a terminal whose login is
# ${T}/accept (user:password): ttyd 401/200, code-server's login 200 (page again) / 302, Jupyter 403/200.
cat >"${SHIM}/curl" <<'S'
#!/usr/bin/env bash
echo "curl $*" >>"${CALLS}"
cfg=""; url=""
while [[ $# -gt 0 ]]; do
    case "$1" in -K) cfg="$2"; shift 2 ;; -o|-w|--max-time) shift 2 ;; -*) shift ;; *) url="$1"; shift ;; esac
done
python3 - "${cfg}" "${url}" "$(cat "${T}/accept")" <<'P'
import re, sys
cfg, url, accept = sys.argv[1], sys.argv[2], sys.argv[3]
pw = accept.split(":", 1)[1]
opts = {}
for line in open(cfg).read().splitlines():
    m = re.match(r'(\S+) = "(.*)"$', line)
    if m:
        opts[m.group(1)] = re.sub(r'\\(.)', r'\1', m.group(2))
path = re.sub(r'^https?://[^/]+', '', url)
if path == "/terminal/":
    code = "200" if opts.get("user") == accept else "401"
elif path == "/ide/login":
    code = "302" if opts.get("data-urlencode") == f"password={pw}" else "200"
elif path == "/jupyter/api/status":
    code = "200" if opts.get("header") == f"Authorization: token {pw}" else "403"
else:
    code = "404"
print(code, end="")
P
S
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"

# run <env file> [<arg> ...]: the check with the test's old login and digest, output in ${T}/out, exit in rc.
rc=0
run() {
    local env="$1"; shift; : >"${CALLS}"; rc=0
    WIB_OLD_FLEET_SH="${T}/old-fleet.sh" WIB_OLD_LOGIN_SHA256="${OLD_SHA}" WIB_TERMINAL_ENV="${env}" \
        bash "${LIVE}" "$@" >"${T}/out" 2>&1 || rc=$?
}
novalue() { ! grep -qF -e "${OLD_WORD}" -e "${NEW_USER}" -e "${NEW_PW}" -e "new\\pw" "${T}/out" "${CALLS}"; }
B1="https://one.example.test"; B2="https://two.example.test/"

echo "== rotated: the Secret and all three tools take the mrf-secrets login =="
printf '%s:%s' "${NEW_USER}" "${NEW_PW}" >"${T}/secret"; printf '%s:%s' "${NEW_USER}" "${NEW_PW}" >"${T}/accept"
run "${T}/new.env" ctx-a "${B1}"
check "exits 0" '[[ "${rc}" -eq 0 ]]'
check "8 checks pass, none fails" 'grep -q "^8 passed, 0 failed$" "${T}/out"'
check "it says the terminal takes the mrf-secrets login" 'grep -q "TAKES THE MRF-SECRETS LOGIN AND REFUSES THE OLD ONE on ctx-a" "${T}/out"'
check "no value in the output or in any argv" 'novalue'
check "every kubectl call names --context ctx-a" \
    '[[ -n "$(grep "^kubectl" "${CALLS}")" ]] && ! grep "^kubectl" "${CALLS}" | grep -qv -- "--context ctx-a "'
check "curl reads every credential from a -K config" '[[ "$(grep -c "^curl .*-K " "${CALLS}")" -eq 7 ]]'
run "${T}/new.env" ctx-a "${B1}" "${B2}"
check "two base URLs (one with a trailing slash): 15 checks pass" '[[ "${rc}" -eq 0 ]] && grep -q "^15 passed, 0 failed$" "${T}/out"'
check "the trailing slash is not doubled" 'grep -q "two.example.test/terminal/" "${CALLS}" && ! grep -q "test//" "${CALLS}"'

echo "== not rotated: the Secret and the tools still take the old login =="
printf '%s:%s' "${OLD_WORD}" "${OLD_WORD}" >"${T}/secret"; printf '%s:%s' "${OLD_WORD}" "${OLD_WORD}" >"${T}/accept"
run "${T}/new.env" ctx-a "${B1}"
check "exits 1" '[[ "${rc}" -eq 1 ]]'
check "names the Secret as the old login" 'grep -q "FAIL  terminal-auth holds .*(got the old login, want the mrf-secrets login)" "${T}/out"'
check "the old login opening /terminal/ fails" 'grep -q "FAIL  /terminal/ refuses the old login (got 200, want 401)" "${T}/out"'
check "the old password opening code-server fails" 'grep -q "FAIL  /ide/login refuses the old password (got 302, want 200)" "${T}/out"'
check "the old token opening Jupyter fails" 'grep -q "FAIL  /jupyter/ refuses the old token (got 200, want 403)" "${T}/out"'
check "7 fail, 1 passes (no login is still refused)" 'grep -q "^1 passed, 7 failed$" "${T}/out"'
check "no value in the output or in any argv" 'novalue'

echo "== half rotated: the Secret is new, the terminal was not restarted =="
printf '%s:%s' "${NEW_USER}" "${NEW_PW}" >"${T}/secret"
run "${T}/new.env" ctx-a "${B1}"
check "exits 1 with the Secret passing and the tools failing" \
    '[[ "${rc}" -eq 1 ]] && grep -q "PASS  terminal-auth holds" "${T}/out" && grep -q "^2 passed, 6 failed$" "${T}/out"'

echo "== no Secret =="
rm -f "${T}/secret"; printf '%s:%s' "${NEW_USER}" "${NEW_PW}" >"${T}/accept"
run "${T}/new.env" ctx-a "${B1}"
check "exits 1 naming an open terminal" '[[ "${rc}" -eq 1 ]] && grep -q "got no Secret (the terminal is open)" "${T}/out"'

echo "== refusals before any cluster call =="
run "${T}/missing.env" ctx-a "${B1}"
check "no presenter login: exits 1 naming mrf-secrets" '[[ "${rc}" -eq 1 ]] && grep -q "it lives in mrf-secrets" "${T}/out"'
check "  and calls neither kubectl nor curl" '[[ ! -s "${CALLS}" ]]'
run "${T}/old.env" ctx-a "${B1}"
check "mrf-secrets still holds the old login: exits 1" '[[ "${rc}" -eq 1 ]] && grep -q "still the old one" "${T}/out"'
check "  and calls neither kubectl nor curl, printing no value" '[[ ! -s "${CALLS}" ]] && novalue'
: >"${CALLS}"; rc=0
WIB_OLD_FLEET_SH="${T}/old-fleet.sh" WIB_OLD_LOGIN_SHA256="$(printf 'x' | sha256sum | cut -d' ' -f1)" \
    WIB_TERMINAL_ENV="${T}/new.env" bash "${LIVE}" ctx-a "${B1}" >"${T}/out" 2>&1 || rc=$?
check "an old login that misses the guard's digest: exits 1 naming the digest" \
    '[[ "${rc}" -eq 1 ]] && grep -q "does not match the digest" "${T}/out" && [[ ! -s "${CALLS}" ]]'
: >"${T}/empty-fleet.sh"; : >"${CALLS}"; rc=0
WIB_OLD_FLEET_SH="${T}/empty-fleet.sh" WIB_TERMINAL_ENV="${T}/new.env" bash "${LIVE}" ctx-a "${B1}" >"${T}/out" 2>&1 || rc=$?
check "no old default lines to read: exits 1 saying so" \
    '[[ "${rc}" -eq 1 ]] && grep -q "could not read the old login" "${T}/out" && [[ ! -s "${CALLS}" ]]'
run "${T}/new.env"
check "no arguments: usage, exit 2" '[[ "${rc}" -eq 2 ]] && grep -q "^usage:" "${T}/out"'
run "${T}/new.env" ctx-a
check "a context and no URL: usage, exit 2" '[[ "${rc}" -eq 2 ]]'
run "${T}/new.env" "" "${B1}"
check "an empty context: exit 2, no fallback to the current-context" '[[ "${rc}" -eq 2 ]] && [[ ! -s "${CALLS}" ]]'

echo "== the default old-login digest is the one the guard holds =="
d="$(sed -nE 's/^OLD_SHA256="\$\{WIB_OLD_LOGIN_SHA256:-([0-9a-f]{64})\}"$/\1/p' "${LIVE}")"
check "terminal-login-live.sh's default digest is in verify/test_no_presenter_login.py" \
    '[[ -n "${d}" ]] && grep -q "\"${d}\"" "${HERE}/test_no_presenter_login.py"'

check "no cloud tool was called" 'no_cloud_clean'
echo
echo "${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
