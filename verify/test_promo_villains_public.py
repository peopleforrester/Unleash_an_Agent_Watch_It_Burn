# ABOUTME: Reads every promo/ villain the lab hands out from ghcr.io anonymously (#653): each is public, so a
# ABOUTME: cluster with Kyverno in Audit, or none, pulls it, and each `:v1` serves the digest lab-platform handed over.
# SUITE: e2e (needs the network: ghcr.io is asked for each manifest)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. Challenge 2's beat is the villain running: `kubectl logs deploy/promo-mascot` before the fix. A node pulls
# ghcr.io/peopleforrester/lab-platform/promo/<name>:v1 with no credential, so a private package admits the
# Deployment and leaves the pod in ImagePullBackOff, with nothing to read. The lab names the tag, not the digest,
# so the tag must still serve the digest in verify/promo_villains.py; a rebuild that moves it is a new hand-over.
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ghcr_pull import served_digest  # noqa: E402
from promo_villains import DIGESTS, PROMO, ref  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


print(f"== every villain the lab hands out is public at {PROMO} ==")
for name, want in DIGESTS.items():
    digest, why = served_digest(ref(name))
    check(f"{ref(name)} answers an anonymous pull", digest is not None, why)
    if digest is not None:
        check(f"{ref(name)} serves {want[:19]}..., the digest lab-platform pinned", digest == want, digest)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All promo villain pull checks passed.")
