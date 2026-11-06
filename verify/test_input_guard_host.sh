#!/usr/bin/env bash
# ABOUTME: Runs verify/input-guard.sh against a fake curl and kubectl, and checks the URL it builds: a full host name
# ABOUTME: is used as given, a bare fleet name gets .agenticburn.com, and its verdicts follow the replies (#900).
#
# #900's issue ran `verify/input-guard.sh burritobot-private.burritobot.co watch-it-burn-private accen-dev`, and the
# script asked https://burritobot-private.burritobot.co.agenticburn.com, which does not resolve: /controls came back
# empty and the JSON read died before any prompt was sent. The fakes here record every URL and kubectl call, and
# answer /controls and /chat the way guard-proxy does, so no network and no cluster is reached.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${HERE}/input-guard.sh"
fails=0
check() { if [[ "$2" == ok ]]; then echo "  PASS  $1"; else echo "  FAIL  $1"; fails=$((fails + 1)); fi; }

[[ -f "$SCRIPT" ]] || { echo "FAIL  ${SCRIPT} is missing"; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"

# curl: log the URL (the last argument that starts with https://), answer /controls with the guard state and /chat
# with a reply that says "blocked by the input" for the injection and, when BLOCK_BENIGN=1, for every prompt.
cat >"$work/bin/curl" <<'EOF'
#!/usr/bin/env bash
url="" data=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --data-binary) data="$2"; shift 2 ;;
        https://*) url="$1"; shift ;;
        *) shift ;;
    esac
done
printf '%s\n' "$url" >>"$FAKE_LOG/urls"
case "$url" in
    */controls) echo '{"ai": {"input_blocklist": false, "input_classifier": false}}' ;;
    */chat)
        if [[ "$data" == *IGNORE* || "${BLOCK_BENIGN:-0}" == 1 ]]; then
            echo '{"reply": "That prompt was blocked by the input guard."}'
        else
            echo '{"reply": "We have carnitas, chicken and black beans."}'
        fi ;;
    *) exit 6 ;;
esac
EOF
cat >"$work/bin/kubectl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FAKE_LOG/kubectl"
echo '{}'
EOF
chmod +x "$work/bin/curl" "$work/bin/kubectl"

run_case() {  # run_case <name> <host> [BLOCK_BENIGN]; leaves urls, kubectl, out and rc in $work/<name>
    local d="$work/$1"
    mkdir -p "$d"
    : >"$d/urls"; : >"$d/kubectl"
    local rc=0
    FAKE_LOG="$d" BLOCK_BENIGN="${3:-0}" PATH="$work/bin:$PATH" \
        bash "$SCRIPT" "$2" watch-it-burn-private accen-dev >"$d/out" 2>&1 || rc=$?
    echo "$rc" >"$d/rc"
}

echo "== a full host name is used as given =="
run_case full burritobot-private.burritobot.co
d="$work/full"
check "the full host exits 0 (benign passes, injection blocked)" "$([[ $(cat "$d/rc") == 0 ]] && echo ok)"
check "it asked /controls on https://burritobot-private.burritobot.co" \
    "$(grep -qx 'https://burritobot-private.burritobot.co/controls' "$d/urls" && echo ok)"
check "it sent both prompts to https://burritobot-private.burritobot.co/chat" \
    "$([[ $(grep -cx 'https://burritobot-private.burritobot.co/chat' "$d/urls") == 2 ]] && echo ok)"
check "no URL carries .agenticburn.com" "$(grep -q 'agenticburn' "$d/urls" || echo ok)"
check "it prints both OK lines" \
    "$(grep -q 'OK    burritobot-private.burritobot.co: benign prompt passes' "$d/out" \
        && grep -q 'OK    burritobot-private.burritobot.co: injection blocked' "$d/out" && echo ok)"
check "every kubectl call names --context watch-it-burn-private" \
    "$([[ -s $d/kubectl ]] && ! grep -v -- '--context watch-it-burn-private' "$d/kubectl" | grep -q . && echo ok)"
check "it turns the input guard on and restores it off" \
    "$(grep -q 'toggle?input=on' "$d/kubectl" && tail -n 1 "$d/kubectl" | grep -q 'toggle?input=off' && echo ok)"

echo "== a bare fleet name gets .agenticburn.com =="
run_case bare michael-admin
d="$work/bare"
check "the bare name exits 0" "$([[ $(cat "$d/rc") == 0 ]] && echo ok)"
check "it asked https://michael-admin.agenticburn.com/controls" \
    "$(grep -qx 'https://michael-admin.agenticburn.com/controls' "$d/urls" && echo ok)"
check "it sent both prompts to https://michael-admin.agenticburn.com/chat" \
    "$([[ $(grep -cx 'https://michael-admin.agenticburn.com/chat' "$d/urls") == 2 ]] && echo ok)"

echo "== a guard that refuses the benign prompt fails =="
run_case benign burritobot-private.burritobot.co 1
d="$work/benign"
check "it exits 1" "$([[ $(cat "$d/rc") == 1 ]] && echo ok)"
check "it names the benign prompt blocked" "$(grep -q 'FAIL  burritobot-private.burritobot.co: benign prompt blocked' "$d/out" && echo ok)"

if [[ "$fails" -gt 0 ]]; then
    echo "$fails FAILED"
    for c in full bare benign; do echo "--- $c output:"; cat "$work/$c/out"; done
    exit 1
fi
echo "INPUT GUARD HOST GREEN"
