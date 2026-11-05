# ABOUTME: Judge for #603's live check: does every image a cluster runs have an images.lock row, by its name:tag or
# ABOUTME: by the digest it runs at, leaving out EKS's own add-on images and what the room deploys through the bot.
"""Shared by test_images_lock_live.py (both KubeCon clusters) and test_images_lock_live_judge.py (fixtures).

images.lock is filled from what the repo names (test_images_lock.py) and what its charts render
(test_images_lock_render.py). An operator can still start a container neither of those sees: kagent's Go agent
runtime, the Prometheus operator's config reloader, the Datadog operator's Agent and Cluster Agent. Run 17350's live
check found those on both clusters with no row. This reads what each pod runs and finds the containers no row covers.

A container is covered when a row's ref, Docker Hub's host and library/ taken off and any @digest dropped, is
the container's image the same way; or, for a templated row whose digest is name@sha256, when the image is that name
at the ref's tag; or when the digest the container names after @, or the one its status reports in imageID, is a
row's digest or the digest pinned in a row's ref. The name and tag come first because a node that once pulled the
Docker Hub original of a lab-platform mirror/ copy can report that original's name and digest in imageID: KubeArmor
on watch-it-burn-private does.

Two kinds of pod are not the repo's to retain, and are left out by name:
- EKS's own add-ons (the VPC CNI, CoreDNS, kube-proxy, the EBS CSI driver, the pod identity agent), which EKS pulls
  from its regional ECR account for us-west-2, 602401143452, at the versions the cluster's Kubernetes version
  takes. They need an AWS login to pull, and they go with EKS, not with an account of ours.
- What the room asks the bot to deploy (Challenge 2's deploy_app), whose image is the room's choice: a pod whose
  owner chain reaches an object workshop-mcp applied (its fieldManager, gitops/ai-layer/workshop-mcp-server.py).
"""
from __future__ import annotations

import re

from docker_hub import HUB_HOSTS
from images_saved import lock_rows, saved_digest

SHA = re.compile(r"sha256:[0-9a-f]{64}")
EKS_ADDON_REGISTRY = re.compile(r"^602401143452\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/")
ROOM_MANAGER = "workshop-mcp"


def norm(image: str) -> str:
    """An image reference with any @digest dropped and Docker Hub's host (docker_hub.HUB_HOSTS) and library/ taken off.

    A node reports the Docker Hub name it first pulled an image by, so the host is read here, never pulled."""
    ref = image.split("@", 1)[0]
    host, slash, rest = ref.partition("/")
    if slash and host.lower() in HUB_HOSTS:
        ref = rest
    if ref.startswith("library/"):
        ref = ref[len("library/"):]
    if ":" not in ref.rsplit("/", 1)[-1]:
        ref += ":latest"
    return ref


def lock_keys(lock_text: str) -> tuple[set[str], set[str]]:
    """(the normalised refs, the digests) images.lock covers a running container by."""
    refs: set[str] = set()
    digests: set[str] = set()
    for ref, digest, source, _saved in lock_rows(lock_text):
        if source.startswith("not-an-image:"):
            continue
        refs.add(norm(ref))
        if "@" in ref and SHA.fullmatch(ref.rsplit("@", 1)[1]):
            digests.add(ref.rsplit("@", 1)[1])
        if "@" in digest and SHA.fullmatch(saved_digest(digest)):
            # A templated or kustomize row: the image runs under the digest's name at the ref's tag.
            last = ref.split("@", 1)[0].rsplit("/", 1)[-1]
            if ":" in last:
                refs.add(norm(f"{digest.rsplit('@', 1)[0]}:{last.split(':', 1)[1]}"))
        if SHA.fullmatch(saved_digest(digest)):
            digests.add(saved_digest(digest))
    return refs, digests


def image_id_digest(image_id: str) -> str:
    """The sha256 digest in a container status's imageID ("name@sha256:...", "docker-pullable://...", or bare)."""
    m = SHA.search(image_id.rsplit("@", 1)[-1]) if image_id else None
    return m.group(0) if m else ""


def covered(image: str, image_id: str, refs: set[str], digests: set[str]) -> bool:
    if norm(image) in refs:
        return True
    if "@" in image and image.rsplit("@", 1)[1] in digests:
        return True
    return image_id_digest(image_id) in digests


def room_uids(objects: list[dict]) -> set[str]:
    """The uids of every object workshop-mcp applied, and of everything owned by one, down any depth."""
    by_uid = {o.get("metadata", {}).get("uid"): o for o in objects}
    room: set[str] = set()

    def is_room(uid: str, seen: frozenset[str] = frozenset()) -> bool:
        if uid in room:
            return True
        o = by_uid.get(uid)
        if o is None or uid in seen:
            return False
        meta = o.get("metadata", {})
        if any(f.get("manager") == ROOM_MANAGER for f in meta.get("managedFields") or []):
            return True
        return any(is_room(r.get("uid"), seen | {uid}) for r in meta.get("ownerReferences") or [])

    for uid in by_uid:
        if uid and is_room(uid):
            room.add(uid)
    return room


def uncovered(lock_text: str, objects: list[dict]) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
    """From a cluster's pods and the objects that own them: ([(namespace/pod, image, imageID)] with no row,
    [(image, why)] left out as EKS's or the room's)."""
    refs, digests = lock_keys(lock_text)
    room = room_uids(objects)
    missing: list[tuple[str, str, str]] = []
    left_out: list[tuple[str, str]] = []
    for o in objects:
        if o.get("kind") != "Pod":
            continue
        meta, spec, status = o.get("metadata", {}), o.get("spec", {}), o.get("status", {})
        ids = {s.get("name"): s.get("imageID", "")
               for key in ("containerStatuses", "initContainerStatuses", "ephemeralContainerStatuses")
               for s in status.get(key) or []}
        for key in ("containers", "initContainers", "ephemeralContainers"):
            for c in spec.get(key) or []:
                image = c.get("image", "")
                if EKS_ADDON_REGISTRY.match(image):
                    left_out.append((image, "EKS add-on"))
                elif meta.get("uid") in room:
                    left_out.append((image, "deployed by the room through workshop-mcp"))
                elif not covered(image, ids.get(c.get("name"), ""), refs, digests):
                    missing.append((f"{meta.get('namespace')}/{meta.get('name')}", image, ids.get(c.get("name"), "")))
    return missing, left_out
