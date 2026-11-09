# ABOUTME: Every ghcr.io/peopleforrester/watch-it-burn digest images.lock or a manifest pins has its cosign
# ABOUTME: sha256-<digest>.sig tag on ghcr.io, read with no credential, so an unsigned pin goes red before main (#1282).
# SUITE: e2e (needs the network: ghcr.io is asked, with no credential, for each pinned digest and its .sig tag)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it, #572)
"""Why (#1282). watch-it-burn-private runs Kyverno's verify-image-signatures with Deny on Pod CREATE for
ghcr.io/peopleforrester/watch-it-burn*, and the web-terminal Deployment is Recreate, so a pin moved to an unsigned
build stops the private terminal's pod on promotion and its replacement is denied. Run 19641 on #1276 found the two
newest web-terminal builds unsigned. The signing script's --check mode reads signatures but is run by hand, with cosign,
and verify/test_image_version_tags.py checks only that a tag serves its pinned digest.

This reads every digest of ours images.lock pins (its digest column) and every one a manifest pins: a tracked YAML,
JSON, shell script or Dockerfile that names ghcr.io/peopleforrester/watch-it-burn...@sha256:..., or a Helm values or
kustomize block that splits it into repository and tag. A test's own fixtures (verify/test_*) are not manifests:
verify/test_reset_bot.sh pins a made-up digest. For each digest it does an anonymous HEAD of the image and of
sha256-<digest>.sig, the tag cosign v2 writes and Kyverno 1.19 reads, and fails naming each one ghcr.io does not serve.
verify/wib_pins.py's repo_pins() does the reading, and verify/sign-images.sh signs what it reads (#1285).

A 200 on the .sig tag says a signature was pushed, not that the workshop key made it. The signing script's --check
mode (cosign 2.x) and the Kyverno CLI check the key. verify/test_wib_pins.py holds the reading and the verdict to
fixtures offline.
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
from wib_pins import empty_reading, merge, repo_pins, unsigned  # noqa: E402

# The same reading verify/sign-images.sh signs (#1285), so the list this checks is the list that script signs.
lock, manifests = repo_pins(REPO)
failures: list[str] = empty_reading(lock, manifests)
pinned = merge(lock, manifests)
print(f"{len(pinned)} digest(s) of ghcr.io/peopleforrester/watch-it-burn: {len(lock)} pinned in images.lock, "
      f"{len(manifests)} in manifests")
problems = unsigned(pinned)
for (package, digest), wheres in sorted(pinned.items()):
    bad = any(p.startswith(f"ghcr.io/{package}@{digest} ") for p in problems)
    print(f"  {'FAIL' if bad else 'PASS'}  {digest[:19]}...  {', '.join(sorted(set(wheres)))}")
failures += problems

print()
if failures:
    print(f"FAILED: {len(failures)} pinned digest(s) unserved or unsigned, or a reading that found nothing:")
    for f in failures:
        print(f"  - {f}")
    print("Sign them with the workshop key and cosign 2.x: verify/sign-images.sh signs and verifies every digest "
          "this reads, by digest.")
    sys.exit(1)
print("Every pinned watch-it-burn digest is served with its sha256-<digest>.sig tag, anonymously.")
