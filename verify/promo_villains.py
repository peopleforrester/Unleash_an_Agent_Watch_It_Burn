# ABOUTME: lab-platform's promo/ villain images as this repo hands them out (#653): each name, the `:v1` reference
# ABOUTME: the lab gives the student, and the digest lab-platform built, read back and signed it at.
"""One table for the tests that ask which villain images the lab hands out.

lab-platform builds the ten villains `images/villains/build.sh` used to push to Docker Hub as peopleforrester/<name>:latest,
the same catchphrase loop on lab-platform's shell base with the lines read from build.sh at 45e62f0, and publishes
them as ghcr.io/peopleforrester/lab-platform/promo/<name>:v1 (lab-platform#92). Watch_It_Burn#653 (comment
6477523413) handed over the rebuild whose entrypoint ends on SIGTERM, so a deleted villain pod stops at once. The
digests are lab-platform#372's signed rebuild of every v1 image with its interactive shell banner
(ENV=/etc/villain-banner.sh), as lab-platform's decisions.md entry 2026-11-07T15:50:00Z (commit 1c44d6fe) lists them
after reading each back from ghcr.io with no credential and verifying it against the workshop key. ghcr.io served all
ten at 16:17Z that day (Watch_It_Burn#1070, #1047), when lab-platform's deploy/watch-it-burn/images.tsv still named the
2026-10-30 digests; its repin is lab-platform#375. The
lab names a villain by its `:v1` tag, not its digest: a digest in a copy-paste box would undo the
"unverified image" story, and the lesson is the path, which restrict-image-registries refuses.
"""
from __future__ import annotations

PROMO = "ghcr.io/peopleforrester/lab-platform/promo"
TAG = "v1"

# The three marketing-named covers the lab hands out, in the lab's order. The hint prompt uses the first.
COVERS = ("promo-mascot", "festival-promo", "loyalty-rewards")

DIGESTS = {
    "promo-mascot": "sha256:1df5e2eaf9b4a4a97d5e76da5e1a11b69070e18ab1b32bf0b31ad26f20398a8a",
    "festival-promo": "sha256:ab939401423fbd0867c89f7baf2ebf1a5fb56b57227283477e8aeabdd7d884ed",
    "loyalty-rewards": "sha256:eff3e1c69c877342dbf184e04cd612f955de2d1dae3735b5436307df5e211419",
    "joker": "sha256:e89333b47392cbf5e9ff78994515771c0d80400c0dda70b40d4fafa0bd119dd8",
    "gargamel": "sha256:07ff44b8c5fa640d35e9366ebc6a8c2f7228289c5627cc83a4ef2dfc13947f1f",
    "skeletor": "sha256:df82eb5399016d409aa0c755b1d7b8aadb67dd7a6d2ef3f43dccb0a3876a019a",
    "mumm-ra": "sha256:229d305f985f6de4d273f2445c7fcd64b783eb6ff348e21c3fb334d82b1e473f",
    "shredder": "sha256:64b56a04d191104b772a93ce434abf42d8e43bcea7994e6b9580ec0e5f03e998",
    "cobra-commander": "sha256:9278f02f07c9cf2c192b5587fb4653e407c180ee1f12a7036242800538067e78",
    "megatron": "sha256:74e54fa48ff89bc225fec962fc38469c98b913af434654bed7496c7642055dae",
}


def ref(name: str) -> str:
    """The reference the lab hands out for a villain."""
    return f"{PROMO}/{name}:{TAG}"
