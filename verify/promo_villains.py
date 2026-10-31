# ABOUTME: lab-platform's promo/ villain images as this repo hands them out (#653): each name, the `:v1` reference
# ABOUTME: the lab gives the student, and the digest lab-platform built, read back and signed it at.
"""One table for the tests that ask which villain images the lab hands out.

lab-platform builds the ten villains `images/villains/build.sh` used to push to docker.io/peopleforrester/<name>:latest,
the same catchphrase loop on lab-platform's shell base with the lines read from build.sh at 45e62f0, and publishes
them as ghcr.io/peopleforrester/lab-platform/promo/<name>:v1 (lab-platform#92). Watch_It_Burn#653 (comment
6477523413) handed over the rebuild whose entrypoint ends on SIGTERM, so a deleted villain pod stops at once. The
digests are lab-platform#55's republish of every v1 image under umask 022 on 2026-10-30 (its decisions.md entry
2026-10-30T18:04:37Z), as its deploy/watch-it-burn/images.tsv pins them and ghcr.io served them on 2026-10-31. The
lab names a villain by its `:v1` tag, not its digest: a digest in a copy-paste box would undo the
"unverified image" story, and the lesson is the path, which restrict-image-registries refuses.
"""
from __future__ import annotations

PROMO = "ghcr.io/peopleforrester/lab-platform/promo"
TAG = "v1"

# The three marketing-named covers the lab hands out, in the lab's order. The hint prompt uses the first.
COVERS = ("promo-mascot", "festival-promo", "loyalty-rewards")

DIGESTS = {
    "promo-mascot": "sha256:68618daa2a2f24ac5200f565f9952e22f093484940434155d3a9766a4b97eefa",
    "festival-promo": "sha256:8e6664b6d5eaf20e4a88a620235e606a635fb982bfb73d5df57a642fcca1916f",
    "loyalty-rewards": "sha256:771409bb3c5c9cc1cb77b1eaa9ba545da35e65b319c71913abdcdec02dfbda8b",
    "joker": "sha256:66c4daed3ab1872890aef2633f8c8eab677298ffbac565d01727c7bb95c33763",
    "gargamel": "sha256:30ac651d19e9b8e5d9bad3f4471bed4bd38bfce88c2b47a23d3b339c14bbdc97",
    "skeletor": "sha256:7b973b14d4d5478dac29fb610ab143bd9dd86afda54a0b06f544a7aac77b14b3",
    "mumm-ra": "sha256:fa04589a143d5211a5e6de33697274c684a72ac39ccf2a2759aa4047dd25f28e",
    "shredder": "sha256:7924c59ffada76cf04a36b34d3c614e2539f5650e77f85a4560558f127d799d4",
    "cobra-commander": "sha256:159184b4597fb16f6eed3a74a818bece58f877909e9dedd37ecdc805f1a18178",
    "megatron": "sha256:0a2db8d4b1674e42e6e66969991a5d02b027d1c1a863b69db0b6daefbbafe37e",
}


def ref(name: str) -> str:
    """The reference the lab hands out for a villain."""
    return f"{PROMO}/{name}:{TAG}"
