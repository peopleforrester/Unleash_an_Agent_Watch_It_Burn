# ABOUTME: lab-platform's promo/ villain images as this repo hands them out (#653): each name, the `:v1` reference
# ABOUTME: the lab gives the student, and the digest lab-platform built, read back and signed it at.
"""One table for the tests that ask which villain images the lab hands out.

lab-platform builds the ten villains `images/villains/build.sh` used to push to docker.io/peopleforrester/<name>:latest,
the same catchphrase loop on lab-platform's shell base with the lines read from build.sh at 45e62f0, and publishes
them as ghcr.io/peopleforrester/lab-platform/promo/<name>:v1 (lab-platform#92). The digests are the rebuild handed
over on Watch_It_Burn#653 (comment 6477523413), whose entrypoint ends on SIGTERM so a deleted villain pod stops at
once. The lab names a villain by its `:v1` tag, not its digest: a digest in a copy-paste box would undo the
"unverified image" story, and the lesson is the path, which restrict-image-registries refuses.
"""
from __future__ import annotations

PROMO = "ghcr.io/peopleforrester/lab-platform/promo"
TAG = "v1"

# The three marketing-named covers the lab hands out, in the lab's order. The hint prompt uses the first.
COVERS = ("promo-mascot", "festival-promo", "loyalty-rewards")

DIGESTS = {
    "promo-mascot": "sha256:9f905177c4f465b7d5f706e2b20501f6b70d8e537976a3da47a07ff7cb1a4615",
    "festival-promo": "sha256:e079929b8f3af1230e73b0bde7d00dab66db9f9b21f74e39181aeaa80c44ddfe",
    "loyalty-rewards": "sha256:db3ebafd06be654971bd66e5fbed23f12702ab0da125ca5d7e1bd7adecef2e4b",
    "joker": "sha256:bc16a7181f0d11fb684e4f1fc2e4caab2e28f4734362767981513dcfb1de3fcb",
    "gargamel": "sha256:b0bb4864ee4981c3a75d7d51c04aadff53b00012c039ac7a65ae9841f2c02933",
    "skeletor": "sha256:ec24c1483063e07fdd99cf29791ce1f806221619ff3f7f7617840462b592ef87",
    "mumm-ra": "sha256:fe4f738c3f9ab9df9da220cec67ac2ed8fa3f32d2b01deaebc3e8fcdf82269d5",
    "shredder": "sha256:ee788ab2b33c5d9bc2f609b95f1a1abe14bb1297e8751c593fcd83a02072d88c",
    "cobra-commander": "sha256:0ad5c22b9b6d8e8ca2c2ccdecd72c0d90aa6919d98166590ce85008e8ba3458e",
    "megatron": "sha256:11cc9beb9b0d6ede6a40560700603798bd7cadf76c6a999ce448d8ad1b9cbbc9",
}


def ref(name: str) -> str:
    """The reference the lab hands out for a villain."""
    return f"{PROMO}/{name}:{TAG}"
