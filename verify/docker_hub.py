# ABOUTME: Whether an image reference is a Docker Hub pull, and where image references sit in a YAML document.
# ABOUTME: Shared by test_no_docker_hub.py (what this repo names) and test_no_docker_hub_render.py (what charts render).
"""#714 removes every Docker Hub pull. A reference is a Docker Hub pull when its registry is one of Docker Hub's
names, or when it names no registry at all: nginx:1.27, busybox and curlimages/curl are pulled from Docker Hub
exactly as docker.io/library/nginx is. A reference's first path component is its registry only when it holds a "."
or a ":" or is localhost, which is how containerd and Docker read it."""
from __future__ import annotations

import yaml

# Docker Hub's registry names, as a reference can spell them. registry.hub.docker.com is the v1 API name.
HUB_HOSTS = ("docker.io", "index.docker.io", "registry-1.docker.io", "registry.hub.docker.com")
# A string that names Docker Hub's registry: in a container's args, env or command it is a pull handed to a program.
HUB_NAMES = HUB_HOSTS + ("hub.docker.com",)


def registry(ref: str) -> str:
    """The registry a reference names; "" when it names none, which is Docker Hub."""
    first, slash, _ = ref.partition("/")
    if slash and ("." in first or ":" in first or first == "localhost"):
        return first
    return ""


def docker_hub(ref: str) -> bool:
    """Whether pulling ref goes to Docker Hub: an explicit Docker Hub host, or no host at all."""
    host = registry(ref.strip())
    return host == "" or host.lower() in HUB_HOSTS


def names_hub(text: str) -> bool:
    return any(h in text for h in HUB_NAMES)


def image_fields(node, where: str = ""):
    """(where, reference) for every image field in a parsed YAML document.

    An `image:` string is one, and so is a Helm values map `image: {registry, repository, tag}` joined the way the
    charts here join it. An Argo CD Application's `values:` string is Helm values too, so it is parsed and read the
    same way; one that is not YAML (a Go template the root fills in) is read for its `image:` lines."""
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{where}.{k}" if where else str(k)
            if k == "image" and isinstance(v, str):
                yield here, v
            elif k == "image" and isinstance(v, dict) and isinstance(v.get("repository"), str):
                reg, repo, tag = v.get("registry"), v["repository"], v.get("tag")
                ref = f"{reg}/{repo}" if isinstance(reg, str) and reg else repo
                yield here, f"{ref}:{tag}" if isinstance(tag, str) and tag else ref
            elif k == "values" and isinstance(v, str) and "image" in v:
                try:
                    docs = list(yaml.load_all(v, Loader=yaml.BaseLoader))
                except yaml.YAMLError:
                    docs = [{"image": line.split(":", 1)[1].strip().strip("\"'")} for line in v.splitlines()
                            if line.strip().startswith("image:") and line.split(":", 1)[1].strip()]
                for d in docs:
                    yield from image_fields(d, here)
            else:
                yield from image_fields(v, here)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from image_fields(v, f"{where}[{i}]")


def pod_spec(obj: dict):
    """The pod spec a live object runs or stamps out: a Pod's own, a controller's template, a CronJob's job's."""
    spec = obj.get("spec") if isinstance(obj.get("spec"), dict) else {}
    if obj.get("kind") == "Pod":
        return spec
    if obj.get("kind") == "CronJob":
        spec = ((spec.get("jobTemplate") or {}).get("spec")) or {}
    return ((spec.get("template") or {}).get("spec")) or None


def stamps_pods(obj: dict) -> bool:
    """Whether a live object can still start a pod from its spec. A Deployment keeps each old ReplicaSet at 0 replicas
    as revision history, and a finished Job starts no more pods, so neither pulls what its template names."""
    spec = obj.get("spec") if isinstance(obj.get("spec"), dict) else {}
    if obj.get("kind") == "ReplicaSet":
        return int(spec.get("replicas") or 0) > 0
    if obj.get("kind") == "Job":
        done = {c.get("type") for c in ((obj.get("status") or {}).get("conditions") or [])
                if c.get("status") == "True"}
        return not done & {"Complete", "Failed"}
    return True


def live_hub_images(objects: list[dict]) -> list[tuple[str, str]]:
    """(kind/namespace/name container, image) for each container a live object names on Docker Hub (#714).

    The spec is what a node pulls by. A container's status.image is not read: containerd reports the first name it
    holds an image by, so a node that pulled the Docker Hub original before a ghcr.io copy replaced it reports that
    name for the copy, with no pull. A controller's template is read too, so a Deployment scaled to 0 is still caught;
    an old ReplicaSet and a finished Job are not (stamps_pods)."""
    found = []
    for obj in objects:
        spec = pod_spec(obj) if stamps_pods(obj) else None
        if not isinstance(spec, dict):
            continue
        meta = obj.get("metadata") or {}
        where = f"{obj.get('kind')}/{meta.get('namespace', '')}/{meta.get('name', '')}"
        for key in ("initContainers", "containers", "ephemeralContainers"):
            for c in spec.get(key) or []:
                image = c.get("image") if isinstance(c, dict) else None
                if isinstance(image, str) and docker_hub(image):
                    found.append((f"{where} {key}:{c.get('name')}", image))
    return found
