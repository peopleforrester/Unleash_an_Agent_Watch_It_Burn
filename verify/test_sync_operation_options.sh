#!/usr/bin/env bash
# ABOUTME: Every Argo CD sync a script starts by writing .operation carries the Application's own syncOptions (#583):
# ABOUTME: roll-console.sh behaviourally (aws and kubectl are shims), and every tracked script by a scan.
#
# Argo CD v3.5.2's controller reads a sync's options from the operation alone (controller/sync.go, syncOp.SyncOptions).
# Its API server and its automated sync copy them in from spec.syncPolicy; an operation written with kubectl gets
# none. On ai-layer such a sync runs without RespectIgnoreDifferences, so git lands on every ignored field:
# agentgateway's BEDROCK_NOVA_MODEL went back to the untagged system id on watch-it-burn-community by 2026-11-02.
#
# Usage: verify/test_sync_operation_options.sh      (offline)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
ROLL="${REPO}/infra/terraform/fleet/roll-console.sh"
T="$(mktemp -d -p "${REPO}" .sync-op-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"; CALLS="${T}/calls"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $*" >>"${CALLS}"
case "$*" in
  *"eks list-clusters"*) echo "watch-it-burn-community" ;;
esac
exit 0
S
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $*" >>"${CALLS}"
case "$*" in
  *"config current-context"*) echo "arn:aws:eks:us-west-2:111122223333:cluster/watch-it-burn-community" ;;
  *"-n argocd get app ai-layer -o json"*) [[ -f "${T}/app.json" ]] || exit 1; cat "${T}/app.json" ;;
  *"get cm console-conf console-src -o json"*) echo '{"data":{"index.html":"MARKER-583"}}' ;;
esac
exit 0
S
printf '#!/usr/bin/env bash\nexit 0\n' >"${SHIM}/sleep"
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"
OPTS='["CreateNamespace=true","ServerSideApply=true","Force=true","RespectIgnoreDifferences=true"]'

echo "== roll-console.sh: the ai-layer sync carries ai-layer's syncOptions =="
printf '{"metadata":{"name":"ai-layer"},"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true},"syncOptions":%s}}}' \
  "${OPTS}" >"${T}/app.json"
: >"${CALLS}"; bash "${ROLL}" MARKER-583 >"${T}/out" 2>&1; rc=$?
check "it exits 0 and cycles the console" '[[ "${rc}" -eq 0 ]] && grep -q "synced + console cycled" "${T}/out"'
check "the operation it writes names the revision and every syncOption of ai-layer" \
  'grep -qF "patch app ai-layer --type merge -p {\"operation\":{\"sync\":{\"revision\":\"staging\",\"syncOptions\":${OPTS}}}}" "${CALLS}"'
check "no sync operation it writes lacks syncOptions" \
  '! grep "patch app ai-layer" "${CALLS}" | grep "operation" | grep -vq "syncOptions"'

echo "== roll-console.sh: when ai-layer's syncOptions cannot be read it does not sync =="
rm -f "${T}/app.json"; : >"${CALLS}"; bash "${ROLL}" MARKER-583 >"${T}/out" 2>&1; rc=$?
check "it writes no operation and cycles nothing" '! grep -q "patch app ai-layer" "${CALLS}" && ! grep -q "delete pod" "${CALLS}"'
check "it says why and exits non-zero" '[[ "${rc}" -ne 0 ]] && grep -q "could not read ai-layer.s syncOptions" "${T}/out"'
printf '{"metadata":{"name":"ai-layer"},"spec":{"syncPolicy":{"syncOptions":[]}}}' >"${T}/app.json"
: >"${CALLS}"; bash "${ROLL}" MARKER-583 >"${T}/out" 2>&1; rc=$?
check "an Application with an empty syncOptions list is refused the same way" \
  '[[ "${rc}" -ne 0 ]] && ! grep -q "patch app ai-layer" "${CALLS}"'

echo "== every tracked script that writes an Application's .operation sync carries syncOptions =="
# A `patch app` or `patch application` command, joined across its backslash continuations, that writes a sync
# operation must name syncOptions or build it with fleet.sh's sync_operation. Removing an operation is not a sync.
out="$(cd "${REPO}" && git ls-files -z -- '*.sh' | python3 -c '
import re, sys
bad = []
for path in sys.stdin.read().split("\0"):
    if not path or path.startswith("verify/test_"):
        continue
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        continue
    joined = re.sub(r"\\\n\s*", " ", text)
    for n, line in enumerate(joined.splitlines(), 1):
        if not re.search(r"\bpatch\s+app(lication)?\b", line) or "operation" not in line:
            continue
        if re.search(r"\"op\"\s*:\s*\"remove\"", line):
            continue
        if "syncOptions" not in line and "sync_operation" not in line:
            bad.append(f"{path}: {line.strip()[:160]}")
print("\n".join(bad))
')"
check "no bare sync operation is written anywhere${out:+ (found: ${out})}" '[[ -z "${out}" ]]'
check "the scan sees both writers it guards, so it is not passing on nothing" \
  '(cd "${REPO}" && grep -q "sync_operation" infra/terraform/fleet/fleet.sh && grep -q "syncOptions: \$o" infra/terraform/fleet/roll-console.sh)'

echo
echo "  ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
