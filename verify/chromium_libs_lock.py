# ABOUTME: Writes and reads chromium-libs.lock (#1120): every Debian 13 package ci_chromium_libs.py may unpack, pinned by
# ABOUTME: the SHA-256 the archive's signed Packages index gives, at a fixed snapshot.debian.org URL, with its depends.
"""Usage: python3 verify/chromium_libs_lock.py write

ci_chromium_libs.py used to ask apt, per job, which packages bring in the libraries and fonts Chromium lacks, and
download them (#1047). That is a fresh fetch of the same packages on every job, against an archive whose versions
move. Since #1120 the packages are pinned here instead, and ci_chromium_libs.py resolves against this lock and the
host's dpkg database, with no apt and no index fetch, and takes each .deb from the host artifact cache by its sum.

`write` reads Debian's archive at one snapshot.debian.org timestamp (SNAPSHOT): the InRelease of trixie,
trixie-updates and trixie-security, each checked with gpgv against Debian's archive keyring, then each suite's
main/binary-amd64/Packages.xz, by the SHA-256 the signed InRelease gives it, through the host artifact cache. A package
in more than one suite is taken at its highest version (`dpkg --compare-versions`). From the roots, the packages
SONAME_PACKAGE and FONT_PACKAGES in ci_chromium_libs.py name, it follows Pre-Depends and Depends (never Recommends, as
`apt-get install --no-install-recommends` did) and pins every package reached. The base system is left out: every
Priority required or Essential package and what those depend on, which a minimal Debian 13 (debian:trixie) always has.
A dependency group the base satisfies is left out of the lock's depends too.

A group of alternatives keeps every name, so ci_chromium_libs.py sees it satisfied when the host has any of them; the
writer pins the first that is a real package, or, when the first is virtual, the first package (by name) that
provides it, appended to the group. The URLs are snapshot.debian.org's, which keeps every version it has seen, so a
pin never goes missing when Debian moves past it the way deb.debian.org's pool does.

The lock is linux amd64 and Debian 13 (trixie) only, as ci_chromium_libs.py checks; a version constraint in a depends
is not kept, since every package here and on the host comes from the one release.
"""
from __future__ import annotations

import lzma
import pathlib
import re
import subprocess
import sys
import urllib.request
from typing import NamedTuple

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import artifact_cache  # noqa: E402

LOCK = VERIFY / "chromium-libs.lock"
SNAPSHOT = "20261107T000000Z"
SUITE = "trixie"
ARCH = "amd64"
# (archive on snapshot.debian.org, suite)
SOURCES = (("debian", SUITE), ("debian", f"{SUITE}-updates"), ("debian-security", f"{SUITE}-security"))
KEYRING = "/usr/share/keyrings/debian-archive-keyring.gpg"
INDEX = f"main/binary-{ARCH}/Packages.xz"
TIMEOUT = 60

HEADER = """\
# ABOUTME: The Debian 13 packages ci_chromium_libs.py may unpack for Playwright's Chromium (#1047), each pinned by the
# ABOUTME: SHA-256 Debian's signed Packages index gives its .deb (#1120); written by `chromium_libs_lock.py write`.
#
# The first data line names the snapshot, suite and architecture. Then one package a line: name, version, SHA-256 of
# the .deb, its snapshot.debian.org URL, and its depends as comma-separated groups of |-separated alternatives ("-"
# for none), with the base system and version constraints left out. ci_chromium_libs.py resolves against these and the
# host's dpkg database and takes each .deb from the host artifact cache by its sum; it never runs apt.
"""


class Package(NamedTuple):
    name: str
    version: str
    sha256: str
    url: str
    depends: tuple[tuple[str, ...], ...]


class Lock(NamedTuple):
    snapshot: str
    suite: str
    arch: str
    packages: dict[str, Package]


class LockError(RuntimeError):
    """chromium-libs.lock is missing or malformed; the message names the line."""


def parse_depends(field: str) -> tuple[tuple[str, ...], ...]:
    """A Depends field as groups of alternative names, each with its version constraint and arch qualifier dropped."""
    groups = []
    for group in field.split(","):
        alts = tuple(re.sub(r"\(.*?\)|\[.*?\]|<.*?>", "", a).strip().split(":", 1)[0] for a in group.split("|"))
        alts = tuple(a for a in alts if a)
        if alts:
            groups.append(alts)
    return tuple(groups)


def render_depends(groups: tuple[tuple[str, ...], ...]) -> str:
    return ",".join("|".join(g) for g in groups) or "-"


def read(path: pathlib.Path = LOCK) -> Lock:
    if not path.is_file():
        raise LockError(f"{path} is missing; `python3 verify/chromium_libs_lock.py write` writes it")
    lines = [ln.split() for ln in path.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines or len(lines[0]) != 4 or lines[0][0] != "snapshot":
        raise LockError(f"{path} does not start with a `snapshot <timestamp> <suite> <arch>` line")
    _, snapshot, suite, arch = lines[0]
    packages: dict[str, Package] = {}
    for fields in lines[1:]:
        if len(fields) != 5 or not artifact_cache.SHA256.fullmatch(fields[2]) or fields[0] in packages:
            raise LockError(f"{path} has a malformed or repeated line {' '.join(fields)!r}: "
                            "want name, version, SHA-256, URL, depends")
        name, version, sha, url, deps = fields
        packages[name] = Package(name, version, sha, url, () if deps == "-" else
                                 tuple(tuple(g.split("|")) for g in deps.split(",")))
    if not packages:
        raise LockError(f"{path} pins no package")
    return Lock(snapshot, suite, arch, packages)


def render(lock: Lock) -> str:
    rows = [f"snapshot {lock.snapshot} {lock.suite} {lock.arch}"]
    rows += [f"{p.name} {p.version} {p.sha256} {p.url} {render_depends(p.depends)}"
             for p in sorted(lock.packages.values())]
    return HEADER + "".join(f"{r}\n" for r in rows)


def stanzas(text: str) -> list[dict[str, str]]:
    """The fields of each stanza of a Packages index; a continuation line joins the field before it."""
    out = []
    for block in text.split("\n\n"):
        fields: dict[str, str] = {}
        key = ""
        for line in block.splitlines():
            if line[:1] in (" ", "\t") and key:
                fields[key] += "\n" + line.strip()
            elif ":" in line:
                key, _, value = line.partition(":")
                fields[key] = value.strip()
        if "Package" in fields:
            out.append(fields)
    return out


def release_sha256(inrelease: str, name: str) -> str:
    """The SHA-256 a signed InRelease gives the index file name."""
    m = re.search(r"^SHA256:\n((?:[ \t].*\n?)+)", inrelease, re.M)
    for line in (m.group(1) if m else "").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] == name:
            return parts[0]
    raise LockError(f"the InRelease names no SHA-256 for {name}")


def newer(a: str, b: str) -> bool:
    return subprocess.run(["dpkg", "--compare-versions", a, "gt", b], timeout=TIMEOUT).returncode == 0


class Index:
    """One package per name, at its highest version across the suites, and which names each package provides."""

    def __init__(self, entries: list[tuple[str, dict[str, str]]]):
        self.pkgs: dict[str, tuple[str, dict[str, str]]] = {}
        for archive, st in entries:
            have = self.pkgs.get(st["Package"])
            if have is None or newer(st["Version"], have[1]["Version"]):
                self.pkgs[st["Package"]] = (archive, st)
        self.providers: dict[str, list[str]] = {}
        for name, (_, st) in self.pkgs.items():
            for virt in (g[0] for g in parse_depends(st.get("Provides", ""))):
                self.providers.setdefault(virt, []).append(name)

    def depends(self, name: str) -> tuple[tuple[str, ...], ...]:
        st = self.pkgs[name][1]
        return parse_depends(st.get("Pre-Depends", "")) + parse_depends(st.get("Depends", ""))

    def choose(self, group: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
        """(package to pin, the group as the lock records it) for one group of alternatives."""
        for alt in group:
            if alt in self.pkgs:
                return alt, group
            if self.providers.get(alt):
                provider = sorted(self.providers[alt])[0]
                return provider, group + ((provider,) if provider not in group else ())
        raise LockError(f"no package in the index is or provides any of {' | '.join(group)}")

    def satisfied_by(self, group: tuple[str, ...], names: set[str]) -> str | None:
        """The first of names that is an alternative of group or provides one, or None."""
        for alt in group:
            if alt in names:
                return alt
            for provider in sorted(self.providers.get(alt, [])):
                if provider in names:
                    return provider
        return None

    def closure(self, roots: list[str], base: set[str] | None = None) -> dict[str, tuple[tuple[str, ...], ...]]:
        """Each package reached from roots, outside base, with its depends groups that base does not satisfy. A group
        already met by a root or a package reached is recorded with that package, not resolved again, so a virtual
        name (awk) is met by the provider the set already holds (mawk) rather than the first by name (gawk)."""
        base = base or set()
        out: dict[str, tuple[tuple[str, ...], ...]] = {}
        queue = list(roots)
        while queue:
            name = queue.pop(0)
            if name in out or name in base:
                continue
            if name not in self.pkgs:
                raise LockError(f"{name} is not in the index")
            kept = []
            for group in self.depends(name):
                if self.satisfied_by(group, base):
                    continue
                have = self.satisfied_by(group, set(roots) | set(out) | set(queue) | {name})
                if have:
                    kept.append(group + ((have,) if have not in group else ()))
                    continue
                pick, recorded = self.choose(group)
                kept.append(recorded)
                queue.append(pick)
            out[name] = tuple(kept)
        return out

    def base(self) -> set[str]:
        roots = [n for n, (_, st) in self.pkgs.items()
                 if st.get("Priority") == "required" or st.get("Essential") == "yes"]
        return set(self.closure(roots))


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "wib-chromium-libs-lock"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode()


def load_index() -> Index:
    """The three suites' Packages indexes at SNAPSHOT, each checked against its InRelease, whose signature is checked."""
    entries = []
    scratch = artifact_cache.scratch_dir("chromium-libs-lock-")
    try:
        for archive, suite in SOURCES:
            base = f"https://snapshot.debian.org/archive/{archive}/{SNAPSHOT}/dists/{suite}"
            release = scratch / f"{suite}.InRelease"
            release.write_text(fetch_text(f"{base}/InRelease"))
            v = subprocess.run(["gpgv", "--keyring", KEYRING, str(release)], capture_output=True, text=True,
                               timeout=TIMEOUT)
            if v.returncode != 0:
                raise LockError(f"gpgv does not accept {base}/InRelease against {KEYRING}: {v.stderr.strip()}")
            sha = release_sha256(release.read_text(), INDEX)
            xz = artifact_cache.get_retrying(sha, f"{base}/{INDEX}")
            entries += [(archive, st) for st in stanzas(lzma.decompress(xz.read_bytes()).decode())]
    finally:
        import shutil
        shutil.rmtree(scratch)
    return Index(entries)


def build(index: Index, roots: list[str]) -> Lock:
    packages = {}
    for name, deps in index.closure(roots, index.base()).items():
        archive, st = index.pkgs[name]
        packages[name] = Package(name, st["Version"], st["SHA256"],
                                 f"https://snapshot.debian.org/archive/{archive}/{SNAPSHOT}/{st['Filename']}", deps)
    return Lock(SNAPSHOT, SUITE, ARCH, packages)


def roots() -> list[str]:
    from ci_chromium_libs import FONT_PACKAGES, SONAME_PACKAGE
    return sorted(set(SONAME_PACKAGE.values()) | set(FONT_PACKAGES))


def main(argv: list[str]) -> int:
    if argv != ["write"]:
        print(__doc__.splitlines()[0], file=sys.stderr)
        return 2
    try:
        lock = build(load_index(), roots())
    except (LockError, artifact_cache.ArtifactCacheError) as e:
        print(f"chromium_libs_lock: {e}", file=sys.stderr)
        return 1
    LOCK.write_text(render(lock))
    print(f"wrote {LOCK}: {len(lock.packages)} packages from snapshot {SNAPSHOT} ({SUITE} {ARCH})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
