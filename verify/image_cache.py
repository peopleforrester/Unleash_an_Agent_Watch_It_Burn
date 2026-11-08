# ABOUTME: Serves a container image pinned by digest from an OCI layout in the host artifact cache (#1122), keyed by the
# ABOUTME: manifest digest; every blob comes through artifact_cache.get by its own sha256, and a hit fetches nothing.
"""The Jokers' build (images/villains/build-loopback.sh, which test_joker_build_digest.py and push-jokers.yml run) and
test_joker_web_busybox.py each pulled build.sh's pinned busybox base from ghcr.io on every run, by digest (#1115).

layout(ref) takes a reference that ends in @sha256:<digest> and returns <root>/oci/sha256/<digest>, an OCI image
layout (oci-layout, index.json, blobs/sha256/<hex>) in the host artifact cache (artifact_cache.py, #1117, which
resolves the root and refuses one inside a worktree):
  - A hit is a layout that is already there. Every blob in it is hashed again, and the index, the manifest it names and
    each blob that manifest names must be there; a blob that does not hash to its name fails, naming the file and both
    sums, and a layout that names another manifest or lacks a blob fails by name. Neither is fetched again, and the
    layout is left where it is for a person to look at. A hit reads no registry.
  - A miss takes a lock on the digest, looks again, and then fetches the manifest and each blob through
    artifact_cache.get_retrying() by its own sha256, which checks each one before it is kept, retries what the network
    broke, and writes each fetch to the fetch log. For an index (a manifest list), the image for `platform` is taken
    and the other platforms are not fetched. The layout is assembled in a temp directory beside its place, from hard
    links to those blobs, and renamed into place whole, so no reader sees a half-built layout.
The registry is read anonymously, as a node with no pull secret reads a public package: a 401 that names a Bearer
realm is answered with that realm's anonymous token, and a blob's redirect is followed without it.

image(layout_dir) reads a layout back: the image manifest (the platform's, for an index), its config and its layers'
paths, each in the layout.

Command line (build-loopback.sh runs it):
  image_cache.py layout <ref@sha256:...> [platform]   print the layout's path, fetching it on a miss
Any failure prints one line starting IMAGE CACHE FAILED to stderr and exits 1."""
from __future__ import annotations

import fcntl
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import BinaryIO

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import artifact_cache  # noqa: E402

SUBDIR = "oci"
PLATFORM = "linux/amd64"
INDEX_TYPES = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")
MANIFEST_TYPES = ("application/vnd.oci.image.manifest.v1+json",
                  "application/vnd.docker.distribution.manifest.v2+json")
ACCEPT = ", ".join(INDEX_TYPES + MANIFEST_TYPES)
UA = "wib-image-cache"
REF = re.compile(r"(?P<host>[A-Za-z0-9.-]+(?::\d+)?)/(?P<repo>[a-z0-9]+(?:[._/-][a-z0-9]+)*)"
                 r"(?::[\w][\w.-]{0,127})?@sha256:(?P<hex>[0-9a-f]{64})")
REF_NAME = "org.opencontainers.image.ref.name"


class ImageCacheError(artifact_cache.ArtifactCacheError):
    """The image could not be served; the message names the reference or the layout."""


class LayoutMismatch(ImageCacheError, artifact_cache.ArtifactMismatch):
    """A layout in the cache does not hold what its digest pins."""


def parse_ref(ref: str) -> tuple[str, str, str]:
    """(registry host, repository, manifest hex digest) of <host>/<repo>[:tag]@sha256:<hex>."""
    m = REF.fullmatch(ref)
    if not m:
        raise ImageCacheError(f"{ref!r} is not a pinned image reference: want <registry>/<repository>[:tag]"
                              "@sha256:<64 lowercase hex digits>")
    return m.group("host"), m.group("repo"), m.group("hex")


def layout_path(hexdigest: str, root: pathlib.Path) -> pathlib.Path:
    return root / SUBDIR / "sha256" / hexdigest


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)
_TOKENS: dict[str, str] = {}


def _copy(r, out: BinaryIO) -> None:
    while chunk := r.read(artifact_cache.CHUNK):
        out.write(chunk)


def _token(challenge: str) -> str:
    """An anonymous token from the realm a `WWW-Authenticate: Bearer realm=...,service=...,scope=...` names."""
    if not challenge.lower().startswith("bearer "):
        raise ImageCacheError(f"the registry asks for {challenge.split(' ', 1)[0] or 'no'} authentication, not a "
                              "Bearer token; only anonymous pulls are made")
    params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm = params.pop("realm", "")
    if not realm:
        raise ImageCacheError(f"the registry's Bearer challenge names no realm: {challenge}")
    url = realm + "?" + urllib.parse.urlencode(params)
    if url not in _TOKENS:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=artifact_cache.TIMEOUT) as r:
            body = json.load(r)
        _TOKENS[url] = body.get("token") or body.get("access_token") or ""
        if not _TOKENS[url]:
            raise ImageCacheError(f"the token realm {realm} answered with no token")
    return _TOKENS[url]


def registry_fetch(url: str, out: BinaryIO) -> None:
    """An artifact_cache Fetcher for a registry's /v2/<repo>/manifests/<digest> or /blobs/<digest>."""
    headers = {"Accept": ACCEPT, "User-Agent": UA}
    for _ in range(2):
        try:
            with _OPENER.open(urllib.request.Request(url, headers=headers), timeout=artifact_cache.TIMEOUT) as r:
                _copy(r, out)
                return
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                # A blob store's signed URL: its own credential is in the URL, and a second one is refused.
                loc = urllib.parse.urljoin(url, e.headers["Location"])
                with urllib.request.urlopen(urllib.request.Request(loc, headers={"User-Agent": UA}),
                                            timeout=artifact_cache.TIMEOUT) as r:
                    _copy(r, out)
                return
            if e.code == 401 and "Authorization" not in headers:
                headers["Authorization"] = "Bearer " + _token(e.headers.get("WWW-Authenticate", ""))
                continue
            raise
    raise ImageCacheError(f"{url} refused the anonymous token")


def _media_type(doc: dict) -> str:
    return doc.get("mediaType") or (INDEX_TYPES[0] if "manifests" in doc else MANIFEST_TYPES[0])


def _hex(desc: dict, where: str) -> str:
    digest = desc.get("digest", "") if isinstance(desc, dict) else ""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ImageCacheError(f"{where} names a blob by {digest!r}, not a sha256 digest")
    return digest.removeprefix("sha256:")


def _platform_child(index: dict, platform: str, where: str) -> dict:
    os_, _, arch = platform.partition("/")
    for d in index.get("manifests", []):
        p = d.get("platform", {})
        if p.get("os") == os_ and p.get("architecture") == arch:
            return d
    have = ", ".join(f"{d.get('platform', {}).get('os')}/{d.get('platform', {}).get('architecture')}"
                     for d in index.get("manifests", []))
    raise ImageCacheError(f"{where} is an index with no {platform} image (it has {have or 'none'})")


def _blob_hexes(read, top: str, platform: str, where: str) -> list[str]:
    """Every blob the layout needs, the top manifest first: read(hex) returns a blob's bytes."""
    out = [top]
    doc = json.loads(read(top))
    if _media_type(doc) in INDEX_TYPES:
        child = _hex(_platform_child(doc, platform, where), where)
        out.append(child)
        doc = json.loads(read(child))
    if not isinstance(doc.get("config"), dict) or not isinstance(doc.get("layers"), list):
        raise ImageCacheError(f"{where}'s manifest has no config and layers")
    out += [_hex(doc["config"], where)] + [_hex(layer, where) for layer in doc["layers"]]
    return out


def check_layout(dest: pathlib.Path, hexdigest: str, platform: str = PLATFORM) -> pathlib.Path:
    """The layout at dest, every blob hashed again and every blob the pinned manifest needs present."""
    blobs = dest / "blobs" / "sha256"
    try:
        index = json.loads((dest / "index.json").read_text())
    except (OSError, ValueError) as e:
        raise LayoutMismatch(f"layout {dest} has no readable index.json ({e}); it is left in place and not fetched "
                             "again") from e
    named = [d.get("digest") for d in index.get("manifests", [])]
    if named != [f"sha256:{hexdigest}"]:
        raise LayoutMismatch(f"layout {dest} names {named}, not the pinned manifest sha256:{hexdigest}; it is left in "
                             "place and not fetched again")
    for f in sorted(blobs.iterdir()) if blobs.is_dir() else []:
        got = artifact_cache.sha256_of(f)
        if got != f.name:
            raise LayoutMismatch(f"layout blob {f} does not match its name: expected SHA-256 {f.name}, got {got}; the "
                                 "layout is left in place and not fetched again")

    def present(h: str) -> pathlib.Path:
        p = blobs / h
        if not p.is_file():
            raise LayoutMismatch(f"layout {dest} lacks the blob sha256:{h} its manifest names; it is left in place "
                                 "and not fetched again")
        return p

    for h in _blob_hexes(lambda h: present(h).read_bytes(), hexdigest, platform, str(dest)):
        present(h)
    return dest


def layout(ref: str, platform: str = PLATFORM, *, root: pathlib.Path | None = None,
           fetch: artifact_cache.Fetcher = registry_fetch, env: Mapping[str, str] | None = None) -> pathlib.Path:
    """The OCI layout of the image ref pins, checked again on a hit and fetched blob by blob only on a miss."""
    host, repo, hexdigest = parse_ref(ref)
    root = artifact_cache.resolve_root(env) if root is None else root
    dest = layout_path(hexdigest, root)
    if dest.exists():
        return check_layout(dest, hexdigest, platform)
    d = dest.parent
    try:
        d.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(d / f".{hexdigest}.lock", os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as e:
        raise ImageCacheError(f"cache miss for {ref} and {d} is not writable: {e}") from e
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if dest.exists():
            return check_layout(dest, hexdigest, platform)
        base = f"https://{host}/v2/{repo}"
        manifests = {hexdigest}

        def read(h: str) -> bytes:
            # The pinned digest and an index's child are manifests; the rest are blobs. get() checks each one.
            kind = "manifests" if h in manifests else "blobs"
            return artifact_cache.get_retrying(h, f"{base}/{kind}/sha256:{h}", root=root, fetch=fetch, env=env).read_bytes()

        top = json.loads(read(hexdigest))
        if _media_type(top) in INDEX_TYPES:
            manifests.add(_hex(_platform_child(top, platform, ref), ref))
        need = _blob_hexes(read, hexdigest, platform, ref)
        for h in need[len(manifests):]:
            read(h)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix=f".{hexdigest}.", suffix=".part", dir=d))
        try:
            (tmp / "blobs" / "sha256").mkdir(parents=True)
            for h in need:
                src, dst = artifact_cache.path_for(h, root), tmp / "blobs" / "sha256" / h
                try:
                    os.link(src, dst)
                except OSError:
                    # A cache on another owner's files may refuse a hard link (fs.protected_hardlinks): copy it;
                    # check_layout() below hashes every blob in the layout either way.
                    shutil.copyfile(src, dst)
            (tmp / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}')
            size = artifact_cache.path_for(hexdigest, root).stat().st_size
            (tmp / "index.json").write_text(json.dumps({
                "schemaVersion": 2, "mediaType": INDEX_TYPES[0],
                "manifests": [{"mediaType": _media_type(top), "digest": f"sha256:{hexdigest}", "size": size,
                               "annotations": {REF_NAME: ref}}]}, indent=2) + "\n")
            check_layout(tmp, hexdigest, platform)
            tmp.chmod(0o755)
            os.rename(tmp, dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return dest
    finally:
        os.close(lock_fd)


def image(dest: pathlib.Path, platform: str = PLATFORM) -> dict:
    """{"manifest": the image manifest, "config": its config, "layers": each layer's path}, read from a layout."""
    blobs = dest / "blobs" / "sha256"
    index = json.loads((dest / "index.json").read_text())
    doc = json.loads((blobs / _hex(index["manifests"][0], str(dest))).read_bytes())
    if _media_type(doc) in INDEX_TYPES:
        doc = json.loads((blobs / _hex(_platform_child(doc, platform, str(dest)), str(dest))).read_bytes())
    return {"manifest": doc, "config": json.loads((blobs / _hex(doc["config"], str(dest))).read_bytes()),
            "layers": [blobs / _hex(layer, str(dest)) for layer in doc["layers"]]}


def main(argv: list[str]) -> int:
    try:
        if len(argv) in (2, 3) and argv[0] == "layout":
            print(layout(argv[1], *argv[2:]))
            return 0
        raise ImageCacheError("usage: image_cache.py layout <ref@sha256:...> [platform]")
    except (artifact_cache.ArtifactCacheError, OSError, ValueError, urllib.error.URLError) as e:
        print(f"IMAGE CACHE FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
