# ABOUTME: The web-terminal build's push step (#816), and sample-app's tag keeper (#828): a version tag the repo pins is
# ABOUTME: put on its pinned digest, never pushed over, and a build is pushed only to a version tag ghcr.io lacks.
"""Push a version tag once, and keep it on the digest the repo pins.

    GHCR_USER=... GHCR_TOKEN=... python3 scripts/ghcr_version_tag.py <local-image|-> <ghcr.io/owner/repo:tag> <pin-file>...

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
when the tag does not serve the pinned digest after the put. A change to what runs in the terminal under the same
ttyd version is not shipped by this step: it needs a tag of its own, which is the tag scheme's question, not this one.

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

    def _call(self, method: str, ref: str, body: bytes | None = None, ctype: str | None = None):
        headers = {"Authorization": f"Bearer {self.token}", "Accept": ACCEPT}
        if ctype:
            headers["Content-Type"] = ctype
        req = urllib.request.Request(f"{self.base}/v2/{self.repo}/manifests/{ref}", data=body, method=method,
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


def docker_push(local: str, ref: str) -> None:
    subprocess.run(["docker", "tag", local, ref], check=True)
    subprocess.run(["docker", "push", ref], check=True)


def keep(local: str | None, ref: str, pin_files: list[str], registry: Registry,
         push: Callable[[str, str], None] = docker_push) -> str:
    """Act on ref as the table in the docstring says, and return the line the workflow log prints.

    local is None when there is no build: then only a pinned ref is acted on."""
    _, _, tag = split(ref)
    texts = {p: pathlib.Path(p).read_text(encoding="utf-8") for p in pin_files}
    want = pinned(ref, texts)
    got = registry.served(tag)
    if want is not None:
        if got == want:
            return f"{ref} serves the pinned {want}; the build is not pushed over it"
        m = registry.manifest(want)
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
        print(keep(local, ref, pin_files, Registry(f"https://{host}", repo, user, password)))
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
