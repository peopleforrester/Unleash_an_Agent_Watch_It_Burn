# ABOUTME: Finds every ghcr.io/peopleforrester/watch-it-burn digest images.lock or a manifest pins, and asks ghcr.io,
# ABOUTME: with no credential, for each digest's cosign sha256-<digest>.sig tag (#1282). Its tests and sign-images.sh read it.
"""Kyverno's verify-image-signatures (policies/kyverno/verify-image-signatures.yaml) denies, at Pod admission on
watch-it-burn-private, any image from ghcr.io/peopleforrester/watch-it-burn* that carries no cosign signature made
with the workshop key. Kyverno 1.19 reads cosign v2's signature from the legacy sha256-<digest>.sig tag next to the
image (the repo's signing script says why it signs with cosign v2), so a pinned digest with no such tag is one a cluster
refuses. Run 19641 on #1276 found two unsigned web-terminal builds that nothing in the gate would have stopped.

lock_pins() and manifest_pins() read images.lock rows and manifest text; unsigned() asks ghcr.io. Each takes its input as
an argument, so verify/test_wib_pins.py drives them on fixtures with a stub opener. repo_pins() reads them from a checkout,
and is the one list both verify/test_wib_digests_signed.py checks and verify/sign-images.sh signs (#1285): run as
`python3 verify/wib_pins.py refs <repo>`, it prints each pinned digest as ghcr.io/<package>@<digest> and where it is
pinned, one per line, and exits 1 when images.lock or the manifests yield none.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

from ghcr_pull import ACCEPT, DROPPED, open_url, read_url

HOST = "ghcr.io"
# The policy's glob is ghcr.io/peopleforrester/watch-it-burn*, which crosses the slash, so the package is taken whole.
PACKAGE = r"peopleforrester/watch-it-burn[A-Za-z0-9._/-]*?"
DIGEST = r"sha256:[0-9a-f]{64}"
# ghcr.io/<package>[:<tag>]@sha256:<hex>, on one line: an image: key, a FROM or ARG, a shell variable, a kubectl --image.
INLINE = re.compile(rf"\bghcr\.io/({PACKAGE})(?::[A-Za-z0-9._-]+)?@({DIGEST})")
# A Helm values or kustomize images: block that splits the reference: a repository, newName or name of the package
# (with ghcr.io in it or on a registry: key next to it), then within the next few lines a tag, newTag or digest that
# holds the digest. gitops/bootstrap/apps/kyverno.yaml names its three counter-fix builds this way.
SPLIT = re.compile(rf"^([ \t]*)(?:-[ \t]+)?(?:repository|newName|name):[ \t]*[\"']?(?:ghcr\.io/)?({PACKAGE})[\"']?[ \t]*\n"
                   rf"(?:\1[ \t]*[^\n]*\n){{0,4}}?\1[ \t]*(?:tag|newTag|digest):[ \t]*[\"']?(?:[A-Za-z0-9._-]+@)?({DIGEST})",
                   re.M)
LOCK_ROW = re.compile(rf"^ghcr\.io/({PACKAGE})(?::[A-Za-z0-9._-]+)?(?:@{DIGEST})?\s+({DIGEST})\s", re.M)


def _line(text: str, at: int) -> int:
    return text.count("\n", 0, at) + 1


def lock_pins(text: str, where: str = "images.lock") -> dict[tuple[str, str], list[str]]:
    """{(package, digest): [images.lock:<line>]} for each row of ours whose digest column holds a digest. A row with
    digest - (tool-pin, never pushed) pins nothing."""
    out: dict[tuple[str, str], list[str]] = {}
    for m in LOCK_ROW.finditer(text):
        out.setdefault((m.group(1), m.group(2)), []).append(f"{where}:{_line(text, m.start())}")
    return out


def manifest_pins(text: str, where: str) -> dict[tuple[str, str], list[str]]:
    """{(package, digest): [<where>:<line>]} for each digest of ours the text pins. A line that is all comment is not
    a pin: a commented-out image is not run."""
    out: dict[tuple[str, str], list[str]] = {}
    for m in INLINE.finditer(text):
        start = text.rfind("\n", 0, m.start()) + 1
        if text[start:m.start()].lstrip().startswith("#"):
            continue
        out.setdefault((m.group(1), m.group(2)), []).append(f"{where}:{_line(text, m.start())}")
    for m in SPLIT.finditer(text):
        key = (m.group(2).rstrip("/"), m.group(3))
        out.setdefault(key, []).append(f"{where}:{_line(text, m.start(3))}")
    return out


# Directories that are not the repo's files: git's own, the pinned tools, the ignored scratch (hecaton's TMPDIR sits
# under tmp/, #1119), a package install and the tier's logs.
NOT_TRACKED = {".git", ".tools", "tmp", "node_modules", ".e2e-logs", ".claude"}


def repo_pins(repo: pathlib.Path) -> tuple[dict[tuple[str, str], list[str]], dict[tuple[str, str], list[str]]]:
    """(images.lock's pins, the manifests' pins) in a checkout at <repo>. A manifest is a YAML, JSON, shell script or
    Dockerfile outside NOT_TRACKED. A test's own fixtures (verify/test_*) are not manifests: verify/test_reset_bot.sh
    pins a made-up digest."""
    lock_file = repo / "images.lock"
    lock = lock_pins(lock_file.read_text(encoding="utf-8")) if lock_file.is_file() else {}
    files = sorted({*repo.rglob("*.yaml"), *repo.rglob("*.yml"), *repo.rglob("*.json"), *repo.rglob("*.sh"),
                    *repo.rglob("Dockerfile"), *repo.rglob("Dockerfile.*")})
    manifests: dict[tuple[str, str], list[str]] = {}
    for p in files:
        rel = p.relative_to(repo)
        if NOT_TRACKED & set(rel.parts) or (rel.parts[0] == "verify" and rel.name.startswith("test_")) \
                or not p.is_file():
            continue
        manifests = merge(manifests, manifest_pins(p.read_text(encoding="utf-8", errors="replace"), str(rel)))
    return lock, manifests


def empty_reading(lock: dict, manifests: dict) -> list[str]:
    """Each source must find something, so a reworded row or a moved manifest reads as that and not as a green check
    or a signing run that signs nothing."""
    out = []
    if not lock:
        out.append("images.lock: no ghcr.io/peopleforrester/watch-it-burn row with a digest; the row pattern in "
                   "verify/wib_pins.py no longer reads it")
    if not manifests:
        out.append("no manifest pins a ghcr.io/peopleforrester/watch-it-burn digest; the patterns in "
                   "verify/wib_pins.py no longer read them")
    return out


def ref(package: str, digest: str) -> str:
    return f"{HOST}/{package}@{digest}"


def merge(*found: dict[tuple[str, str], list[str]]) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    for f in found:
        for key, wheres in f.items():
            out.setdefault(key, []).extend(wheres)
    return out


def sig_tag(digest: str) -> str:
    """The tag cosign v2 writes a digest's signature to, and Kyverno 1.19 reads it from."""
    return digest.replace(":", "-", 1) + ".sig"


def _head(package: str, ref: str, token: str, opener) -> str:
    """'' when ghcr.io answers 200 to a HEAD of <package>'s manifest <ref>, else what it answered."""
    req = urllib.request.Request(f"https://{HOST}/v2/{package}/manifests/{ref}", method="HEAD",
                                 headers={"Authorization": f"Bearer {token}", "Accept": ACCEPT})
    try:
        with open_url(req, timeout=60, opener=opener) as r:
            return "" if r.status == 200 else f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} {e.reason}"
    except (urllib.error.URLError, *DROPPED) as e:
        notes = "".join(f" ({n})" for n in getattr(e, "__notes__", []))
        return f"{type(e).__name__}: {e}{notes}"


def unsigned(pinned: dict[tuple[str, str], list[str]], opener=None) -> list[str]:
    """One line per pin ghcr.io does not serve with its .sig tag, to a client with no credential, as a node pulls and
    Kyverno reads it; [] when every pin is served and signed."""
    problems: list[str] = []
    tokens: dict[str, str] = {}
    for (package, digest), wheres in sorted(pinned.items()):
        at = ", ".join(sorted(set(wheres)))
        if package not in tokens:
            try:
                tokens[package] = json.loads(read_url(f"https://{HOST}/token?scope=repository:{package}:pull",
                                                      opener=opener))["token"]
            except (urllib.error.URLError, *DROPPED, KeyError, ValueError) as e:
                problems.append(f"{HOST}/{package}@{digest} ({at}): no anonymous token for {package}: "
                                f"{type(e).__name__}: {e}")
                continue
        token = tokens[package]
        why = _head(package, digest, token, opener)
        if why:
            problems.append(f"{HOST}/{package}@{digest} ({at}): the image itself is not served ({why})")
            continue
        why = _head(package, sig_tag(digest), token, opener)
        if why:
            problems.append(f"{HOST}/{package}@{digest} ({at}): no {sig_tag(digest)} tag ({why})")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "refs":
        print("usage: wib_pins.py refs <repo>", file=sys.stderr)
        return 2
    lock, manifests = repo_pins(pathlib.Path(argv[2]).resolve())
    problems = empty_reading(lock, manifests)
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        return 1
    for (package, digest), wheres in sorted(merge(lock, manifests).items()):
        print(f"{ref(package, digest)} {','.join(sorted(set(wheres)))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
