# ABOUTME: Offline half of #603's live check: verify/images_live.py's judge on fixture pods, so a running image with
# ABOUTME: no images.lock row fails, a row by name:tag or digest passes, and EKS add-ons and room deploys are left out.
"""test_images_lock_live.py reads both KubeCon clusters. This holds its judge to known cases, so its failing means an
image has no row and its passing means each one has.
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from images_live import covered, image_id_digest, lock_keys, norm, uncovered  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


D1, D2, D3, D4 = ("sha256:" + c * 64 for c in "1234")
LOCK = f"""# a comment
debian:bookworm-slim {D1} upstream:https://github.com/debuerreotype/docker-debian-artifacts 2026-11-04
ghcr.io/example/app:1.0@{D2} {D2} repo:example/app -
{{{{.Values.imageRegistry}}}}/mirror/thing:stable-3333 ghcr.io/example/mirror/thing@{D3} upstream:https://example.com -
REGISTRY/evil@sha256:REPLACE_AT_BUILD - not-an-image:placeholder -
"""


def pod(name: str, image: str, image_id: str = "", ns: str = "default", uid: str = "", owner: str = "",
        init: bool = False) -> dict:
    meta: dict = {"name": name, "namespace": ns, "uid": uid or f"uid-{name}"}
    if owner:
        meta["ownerReferences"] = [{"uid": owner}]
    key = "initContainers" if init else "containers"
    skey = "initContainerStatuses" if init else "containerStatuses"
    return {"kind": "Pod", "metadata": meta, "spec": {key: [{"name": "c", "image": image}]},
            "status": {skey: [{"name": "c", "imageID": image_id}]}}


print("== normalising a reference ==")
check("docker.io/library/debian:bookworm-slim is debian:bookworm-slim", norm("docker.io/library/debian:bookworm-slim")
      == "debian:bookworm-slim")
check("an untagged name is :latest", norm("busybox") == "busybox:latest")
check("a digest is dropped", norm(f"ghcr.io/example/app:1.0@{D2}") == "ghcr.io/example/app:1.0")
check("a registry port is not a tag", norm("localhost:5000/app") == "localhost:5000/app:latest")
check("imageID's digest is read from name@sha256", image_id_digest(f"docker.io/library/debian@{D1}") == D1)
check("imageID's digest is read when bare", image_id_digest(D4) == D4)
check("an empty imageID has no digest", image_id_digest("") == "")

refs, digests = lock_keys(LOCK)
print("== what images.lock covers ==")
check("a row by name:tag covers it at any digest", covered("debian:bookworm-slim", "", refs, digests))
check("Docker Hub's long form of a row's name is covered", covered("docker.io/library/debian:bookworm-slim", "", refs,
                                                                  digests))
check("a pinned ref is covered by its digest under another tag", covered(f"ghcr.io/example/app:other@{D2}", "", refs,
                                                                         digests))
check("a templated row's name@sha256 digest covers the tag a cluster runs it under",
      covered("ghcr.io/example/mirror/thing:stable-3333", "", refs, digests))
check("it does so when imageID names the Docker Hub original at another digest",
      covered("ghcr.io/example/mirror/thing:stable-3333", f"docker.io/example/thing@{D4}", refs, digests))
check("the templated row's name at another tag and digest is not covered",
      not covered("ghcr.io/example/mirror/thing:stable-9999", f"docker.io/example/thing@{D4}", refs, digests))
check("an image no row names, at a digest no row has, is not covered",
      not covered("registry.example.com/agent:7.0", f"registry.example.com/agent@{D4}", refs, digests))
check("debian at another tag is not covered by the bookworm-slim row", not covered("debian:trixie-slim", "", refs,
                                                                                     digests))
check("a not-an-image: row covers nothing", not covered("REGISTRY/evil:latest", "", refs, digests))

print("== a cluster's pods ==")
eks = "602401143452.dkr.ecr.us-west-2.amazonaws.com/eks/coredns:v1.14.7-eksbuild.22"
room_deploy = {"kind": "Deployment", "metadata": {"name": "tron", "namespace": "agent", "uid": "d1",
                                                  "managedFields": [{"manager": "workshop-mcp", "operation": "Apply"}]}}
room_rs = {"kind": "ReplicaSet", "metadata": {"name": "tron-1", "namespace": "agent", "uid": "rs1",
                                              "ownerReferences": [{"uid": "d1"}],
                                              "managedFields": [{"manager": "kube-controller-manager"}]}}
argo_rs = {"kind": "ReplicaSet", "metadata": {"name": "web-1", "namespace": "agent", "uid": "rs2",
                                              "managedFields": [{"manager": "kube-controller-manager"}]}}
objects = [
    pod("ok", "debian:bookworm-slim", f"docker.io/library/debian@{D1}"),
    pod("init-ok", f"ghcr.io/example/app:1.0@{D2}", init=True),
    pod("dd", "registry.example.com/agent:7.0", f"registry.example.com/agent@{D4}"),
    pod("coredns", eks, f"{eks.split(':v')[0]}@{D4}", ns="kube-system"),
    pod("tron-1-abc", "trongame/tron:latest", "", ns="agent", owner="rs1"),
    pod("web-1-abc", "nginx:9", "", ns="agent", owner="rs2"),
    room_deploy, room_rs, argo_rs,
]
missing, left_out = uncovered(LOCK, objects)
names = {w for w, _, _ in missing}
check("the image with no row is named, with its pod", "default/dd" in names, str(missing))
check("an image with no row under an object workshop-mcp did not apply is named", "agent/web-1-abc" in names,
      str(missing))
check("covered images, an init container's among them, are not named", not names & {"default/ok", "default/init-ok"},
      str(missing))
check("an EKS add-on is left out, and listed as one", ("kube-system/coredns" not in names)
      and (eks, "EKS add-on") in left_out, str(left_out))
check("a pod a workshop-mcp Deployment owns through its ReplicaSet is left out, and listed",
      "agent/tron-1-abc" not in names and any(i == "trongame/tron:latest" for i, _ in left_out), str(left_out))
check("exactly the two uncovered pods are named", names == {"default/dd", "agent/web-1-abc"}, str(names))
cyc = [{"kind": "ReplicaSet", "metadata": {"uid": "a", "ownerReferences": [{"uid": "b"}]}},
       {"kind": "ReplicaSet", "metadata": {"uid": "b", "ownerReferences": [{"uid": "a"}]}},
       pod("loop", "nginx:9", owner="a")]
check("an owner cycle ends, and its pod is judged", {w for w, _, _ in uncovered(LOCK, cyc)[0]} == {"default/loop"})

print("== the repo's images.lock ==")
repo_lock = (HERE.parent / "images.lock").read_text(encoding="utf-8")
r_refs, r_digests = lock_keys(repo_lock)
for image, image_id in (
        ("ghcr.io/kagent-dev/kagent/golang-adk:0.10.1", ""),
        ("quay.io/prometheus-operator/prometheus-config-reloader:v0.94.0", ""),
        ("registry.datadoghq.com/agent:7.83.0", ""),
        ("registry.datadoghq.com/cluster-agent:7.83.0", ""),
        ("public.ecr.aws/eks/aws-load-balancer-controller:v2.14.0", "")):
    check(f"images.lock covers {image}, which run 17350 found running with no row", covered(image, image_id, r_refs,
                                                                                            r_digests))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("images_live.py judges every fixture as expected.")
