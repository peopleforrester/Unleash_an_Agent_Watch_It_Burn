# ABOUTME: The web-terminal build's push step (#816, #838), and sample-app's tag keeper (#828): a pinned version tag stays on
# ABOUTME: its pinned digest, a build of new source goes to a tag ghcr.io lacks, and a reproducible one to its pin (#775).
"""Push a version tag once, and keep it on the digest the repo pins.

    GHCR_USER=... GHCR_TOKEN=... python3 scripts/ghcr_version_tag.py <local-image|crane:<ref>|-> <ghcr.io/owner/repo:tag> <pin-file>...

Why (#816). The web-terminal tag names the ttyd inside (#714): web-terminal-ttyd-1.7.7. Its build is not
reproducible, so every run of .github/workflows/build-web-terminal.yml used to push a new digest over that same tag.
Between 2026-11-02 and 2026-11-03 the tag was seen at d6acd503, 0b72ecc7, 7e5f8986 and cb00c5b7, each pushed by a
push to staging or main that touched images/web-terminal or the workflow. gitops/ai-layer/resources.yaml pins tag@digest, so clusters
kept the pinned, signed digest, but the tag no longer named it, and verify/test_image_version_tags.py went red.

What it does, by what the pin files and ghcr.io say:

  a pin file pins <tag>@D, and the tag serves D    nothing; the build is not pushed
  a pin file pins <tag>@D, and the tag serves E    D's manifest, byte for byte, is put to the tag, so it serves D
                                                   again; the build is not pushed
  a pin file pins <tag>@D, and ghcr.io lacks it    D's manifest is put to the tag the same way, so it serves D
  no pin file pins <tag>, and ghcr.io lacks it     the build is pushed: a new ttyd version's first push
  no pin file pins <tag>, and ghcr.io has it       nothing: a later run (the main promotion, say) leaves the first
                                                   push in place, for its digest to be pinned and signed

It exits 1 when the pin files pin the tag at more than one digest, when the pinned digest is not in the registry, or
when the tag does not serve the pinned digest after the put.

A rebuild under the same version (#838). With only the table above, a change to images/web-terminal that kept ttyd at
1.7.7 (kubectl, a package) was built and never pushed, since web-terminal-ttyd-1.7.7 already existed. So a build is
shipped by its source, not only by its version. The workflow labels the image it builds with
io.github.peopleforrester.watch-it-burn.source-tree, the git tree id of images/web-terminal, which changes exactly
when a file under it does. Given a local image, the script reads that label from it and walks the version's tags in
order (web-terminal-ttyd-1.7.7, then web-terminal-ttyd-1.7.7-1, -2 and on), each at the digest a pin file pins it at
or else the one ghcr.io serves, until one is neither pinned nor on ghcr.io:

  a tag's image carries the build's source tree    that tag is the build's, and the table above acts on it: the
                                                   build is never pushed over it
  no tag's image does                              the table acts on the first free tag, so the build is pushed
                                                   there: web-terminal-ttyd-1.7.7 for a new ttyd version's first
                                                   build, web-terminal-ttyd-1.7.7-<n> for its n-th rebuild

A pinned tag passed on the way is kept on its pinned digest by the table's rows too. The suffix counts rebuilds; the
version before it is still the one ttyd reports (#714), and verify/test_image_version_tags.py holds a pinned -<n> tag
to the label. A workflow-only edit leaves the tree as it was, so it pushes nothing; the main promotion of a source
staging already pushed finds staging's tag. The workflow runs one build at a time, so two runs cannot take one -<n>.

A local image of "crane:<ref>" is a reproducible build (#775): <ref> is an image in a registry crane reads, the
loopback one .github/workflows/push-jokers.yml has images/villains/build.sh build both Jokers into. crane reads its
digest, and one row is added to the table for it:

  a pin file pins <tag>@D, the registry has no     the build's digest is read: when it is D, crane copies the
  manifest at D, and the build is crane:<ref>      build to the tag, so it serves D; when it is not, nothing is
                                                   pushed and the script exits 1 naming both digests

Every other row acts as above, so a Joker tag that serves its pin is left alone and a moved one is put back. That row
is how the breakout's Joker, festival-ops/maintenance-shell:busybox-1.38.0-internal, reaches ghcr.io: images.lock
pinned its digest before its first push, and no run may write to ghcr.io.

A local image of "-" means there is no build (#828). .github/workflows/keep-sample-app-tag.yml runs the script that
way for sample-app-nginx-<v>, which #814 pinned in backstage/k8s/templated-test-svc.yaml and images.lock at the
digest the old sample-app tag served, a tag ghcr.io did not have yet (404). The pinned rows of the table act as
above, so the missing tag is put on its pinned digest; an unpinned tag is refused, since there is nothing to push.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Callable

ACCEPT = ", ".join(("application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.docker.distribution.manifest.v2+json"))
# The label the workflow's build sets to `git rev-parse HEAD:images/web-terminal` (#838).
SOURCE_TREE = "io.github.peopleforrester.watch-it-burn.source-tree"


class Refused(Exception):
    """A state this step will not act on; the message says what a person has to do."""


def split(ref: str) -> tuple[str, str, str]:
    """host, repository, tag of host/owner/name:tag."""
    m = re.fullmatch(r"([^/]+)/([a-z0-9._/-]+):([\w][\w.-]{0,127})", ref)
    if not m:
        raise Refused(f"{ref} is not a host/repository:tag reference")
    return m.group(1), m.group(2), m.group(3)


def pinned(ref: str, texts: dict[str, str]) -> str | None:
    """The one digest the pin files pin ref at, or None when none pins it."""
    found = {d for text in texts.values() for d in re.findall(rf"{re.escape(ref)}@(sha256:[0-9a-f]{{64}})", text)}
    if len(found) > 1:
        raise Refused(f"the pin files ({', '.join(texts)}) pin {ref} at {len(found)} digests: {sorted(found)}")
    return next(iter(found), None)


class Registry:
    """The few OCI distribution calls this step makes, as one user with pull and push on one repository."""

    def __init__(self, base: str, repo: str, user: str, password: str) -> None:
        self.base, self.repo = base.rstrip("/"), repo
        basic = base64.b64encode(f"{user}:{password}".encode()).decode()
        req = urllib.request.Request(f"{self.base}/token?scope=repository:{repo}:pull,push",
                                     headers={"Authorization": f"Basic {basic}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            self.token = json.load(r)["token"]

    def _call(self, method: str, ref: str, body: bytes | None = None, ctype: str | None = None, kind: str = "manifests"):
        headers = {"Authorization": f"Bearer {self.token}", "Accept": ACCEPT}
        if ctype:
            headers["Content-Type"] = ctype
        req = urllib.request.Request(f"{self.base}/v2/{self.repo}/{kind}/{ref}", data=body, method=method,
                                     headers=headers)
        return urllib.request.urlopen(req, timeout=60)

    def served(self, ref: str) -> str | None:
        """The digest ref (a tag or a digest) serves, or None on a 404."""
        try:
            with self._call("HEAD", ref) as r:
                return r.headers.get("Docker-Content-Digest")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def manifest(self, digest: str) -> tuple[bytes, str] | None:
        """The exact bytes and media type of the manifest at digest, or None on a 404."""
        try:
            with self._call("GET", digest) as r:
                body, ctype = r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        if "sha256:" + hashlib.sha256(body).hexdigest() != digest:
            raise Refused(f"the registry's manifest for {digest} does not hash to {digest}")
        return body, ctype

    def put(self, tag: str, body: bytes, ctype: str) -> None:
        with self._call("PUT", tag, body, ctype):
            pass

    def labels(self, digest: str) -> dict[str, str]:
        """The labels of the linux/amd64 image at digest, an index or a single manifest, read from its config blob."""
        m = self.manifest(digest)
        if m is None:
            raise Refused(f"the registry has no manifest at {digest}, so its labels cannot be read")
        doc = json.loads(m[0])
        if "manifests" in doc:
            amd64 = [x["digest"] for x in doc["manifests"]
                     if x.get("platform", {}).get("os") == "linux" and x["platform"].get("architecture") == "amd64"]
            if len(amd64) != 1:
                raise Refused(f"the index at {digest} has {len(amd64)} linux/amd64 images, not one")
            return self.labels(amd64[0])
        config = doc["config"]["digest"]
        with self._call("GET", config, kind="blobs") as r:
            blob = r.read()
        if "sha256:" + hashlib.sha256(blob).hexdigest() != config:
            raise Refused(f"the registry's config blob {config} does not hash to {config}")
        # An image built with no LABEL at all has "Labels": null in its config.
        return json.loads(blob).get("config", {}).get("Labels") or {}


def docker_push(local: str, ref: str) -> None:
    subprocess.run(["docker", "tag", local, ref], check=True)
    subprocess.run(["docker", "push", ref], check=True)


def docker_labels(local: str) -> dict[str, str]:
    out = subprocess.run(["docker", "image", "inspect", "--format", "{{json .Config.Labels}}", local], check=True,
                         capture_output=True, text=True).stdout
    return json.loads(out) or {}


def crane_bin() -> str:
    return os.environ.get("CRANE") or "crane"


def crane_digest(local: str) -> str:
    """The digest of a build in a registry crane reads (the workflow's loopback one)."""
    r = subprocess.run([crane_bin(), "digest", local], capture_output=True, text=True)
    if r.returncode != 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", r.stdout.strip()):
        raise Refused(f"crane could not read the digest of the build {local}: {(r.stdout + r.stderr).strip()[:300]}")
    return r.stdout.strip()


def crane_push(local: str, ref: str) -> None:
    """Copy the build to ref, manifest and layers byte for byte, as GHCR_USER with GHCR_TOKEN."""
    host, _, _ = split(ref)
    subprocess.run([crane_bin(), "auth", "login", host, "-u", os.environ["GHCR_USER"], "--password-stdin"],
                   input=os.environ["GHCR_TOKEN"], text=True, check=True)
    subprocess.run([crane_bin(), "copy", local, ref], check=True)


def keep(local: str | None, ref: str, pin_files: list[str], registry: Registry,
         push: Callable[[str, str], None] = docker_push,
         built: Callable[[str], str] | None = None) -> str:
    """Act on ref as the table in the docstring says, and return the line the workflow log prints.

    local is None when there is no build: then only a pinned ref is acted on. built reads a reproducible build's
    digest (crane:<ref>); with it, a pinned digest the registry lacks is pushed from a build that has that digest."""
    _, _, tag = split(ref)
    texts = {p: pathlib.Path(p).read_text(encoding="utf-8") for p in pin_files}
    want = pinned(ref, texts)
    got = registry.served(tag)
    if want is not None:
        if got == want:
            return f"{ref} serves the pinned {want}; the build is not pushed over it"
        m = registry.manifest(want)
        if m is None and local is not None and built is not None:
            have = built(local)
            if have != want:
                raise Refused(f"{', '.join(pin_files)} pin {ref}@{want}, which the registry lacks, and the build "
                              f"{local} is {have}: nothing is pushed. Fix the build or re-pin, not both blindly")
            push(local, ref)
            after = registry.served(tag)
            if after != want:
                raise Refused(f"the build at {want} was pushed to {ref}, and it serves {after}")
            before = "was not on the registry" if got is None else f"served {got}"
            return f"{ref} {before}; the build, at the pinned {want}, is pushed to it"
        if m is None:
            raise Refused(f"{', '.join(pin_files)} pin {ref}@{want}, and the registry has no manifest at {want}")
        registry.put(tag, *m)
        after = registry.served(tag)
        if after != want:
            raise Refused(f"{ref} was put back on {want}, and it serves {after}")
        if got is None:
            return f"{ref} was not on the registry; it now serves the pinned {want}, and no build is pushed"
        return f"{ref} served {got}; it is back on the pinned {want}, and the build is not pushed"
    if local is None:
        raise Refused(f"no pin file ({', '.join(pin_files)}) pins {ref} at a digest, and there is no build to push")
    if got is not None:
        return (f"{ref} is already on ghcr.io at {got}, and nothing pins it yet: the build is not pushed over it. "
                f"Pin {ref}@{got} in gitops/ai-layer/resources.yaml and images.lock, and sign it")
    push(local, ref)
    return f"pushed {ref}; pin its digest in gitops/ai-layer/resources.yaml and images.lock, and sign it"


def ship(local: str, ref: str, pin_files: list[str], registry: Registry,
         push: Callable[[str, str], None] = docker_push,
         labels_of: Callable[[str], dict[str, str]] = docker_labels) -> str:
    """Find the tag of ref's version that local's source tree was built under, or the first free one, and act on it
    with keep(), as the docstring's #838 table says. Return the lines the workflow log prints."""
    tree = labels_of(local).get(SOURCE_TREE)
    if not tree:
        raise Refused(f"{local} carries no {SOURCE_TREE} label, so its source cannot be told from a tag's: the "
                      f"workflow's build sets it to the git tree id of the image's directory")
    split(ref)
    texts = {p: pathlib.Path(p).read_text(encoding="utf-8") for p in pin_files}
    lines: list[str] = []
    n = 0
    while True:
        candidate = ref if n == 0 else f"{ref}-{n}"
        want = pinned(candidate, texts)
        digest = want or registry.served(split(candidate)[2])
        if digest is None:
            lines.append(f"no tag of {ref} was built from source tree {tree}; {candidate} is the first free one")
            break
        if registry.labels(digest).get(SOURCE_TREE) == tree:
            lines.append(f"{candidate} at {digest} was built from source tree {tree}")
            break
        if want is not None:
            lines.append(keep(None, candidate, pin_files, registry, push))
        n += 1
    lines.append(keep(local, candidate, pin_files, registry, push))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__.splitlines()[2].strip(), file=sys.stderr)
        return 2
    local, ref, pin_files = (None if argv[0] == "-" else argv[0]), argv[1], argv[2:]
    user, password = os.environ.get("GHCR_USER", ""), os.environ.get("GHCR_TOKEN", "")
    if not user or not password:
        print("GHCR_USER and GHCR_TOKEN must both be set", file=sys.stderr)
        return 1
    try:
        host, repo, _ = split(ref)
        registry = Registry(f"https://{host}", repo, user, password)
        if local and local.startswith("crane:"):
            print(keep(local[len("crane:"):], ref, pin_files, registry, push=crane_push, built=crane_digest))
        else:
            print(ship(local, ref, pin_files, registry) if local else keep(None, ref, pin_files, registry))
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
