# ABOUTME: Reads every mirror/ copy a chart here names from ghcr.io anonymously (#623): each is public, so a cluster
# ABOUTME: infra/deploy-full-idp.sh builds, which passes no imageRegistry, pulls it, and each serves its digest.
# SUITE: e2e (needs the network: ghcr.io is asked for each manifest)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. An app file names a copy as "{{ .Values.imageRegistry }}/mirror/...", and a root that passes no value,
# infra/deploy-full-idp.sh's among them, renders it at ghcr.io/peopleforrester/lab-platform. A node there pulls
# with no credential, so the copy must answer an anonymous pull. The copy's tag ends in the first twelve
# characters of its linux/amd64 digest and the mirror never moves a tag, so each must still serve that digest.
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import LAB_PLATFORM_GHCR  # noqa: E402
from ghcr_pull import served_digest  # noqa: E402
from mirror_copies import COPIES  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


print(f"== every mirror/ copy a chart names is public at {LAB_PLATFORM_GHCR} ==")
for c in COPIES:
    digest, why = served_digest(f"{LAB_PLATFORM_GHCR}/{c.path}")
    check(f"{c.path} answers an anonymous pull", digest is not None, why)
    if digest is not None:
        check(f"{c.path} serves {c.digest[:19]}..., the digest it was copied by", digest == c.digest, digest)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All mirror copy checks passed.")
