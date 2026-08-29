# ABOUTME: Guards the web-terminal kubeconfig against the expiring-token regression: it MUST point kubectl
# ABOUTME: at the rotated tokenFile, never bake a one-time --token snapshot that dies ~1h after pod start.
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
ENTRY = REPO / "images" / "web-terminal" / "entrypoint.sh"
src = ENTRY.read_text()

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# The bug: `set-credentials me --token="$(cat .../token)"` freezes a snapshot of a projected SA token that
# the kubelet rotates in place, so kubectl in the terminal (and every guard toggle that shells out to
# `kubectl exec`) breaks ~1h after pod start. The fix reads the token FILE on every call instead.
baked_token = re.search(r"set-credentials\s+me\s+--token=", src)
check("kubeconfig does NOT bake a one-time --token snapshot (expiring-token bug)", baked_token is None)

check("kubeconfig points kubectl at the rotated tokenFile",
      re.search(r"users\.me\.tokenFile", src) is not None)

# tokenFile must reference the in-pod projected SA token path so client-go re-reads the rotated token.
check("tokenFile references the ServiceAccount token path",
      re.search(r'tokenFile"?\s+"?\$?\{?SA\}?/token', src) is not None
      or "/var/run/secrets/kubernetes.io/serviceaccount/token" in src)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll terminal-kubeconfig checks passed.")
