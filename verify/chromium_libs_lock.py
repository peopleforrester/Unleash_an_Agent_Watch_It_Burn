# ABOUTME: Writes verify/chromium-libs.lock (#1120): every Debian package ci_chromium_libs.py may unpack, with its
# ABOUTME: version, the SHA-256 the signed Packages index gives and a snapshot.debian.org URL that never goes away.
"""Usage: python3 verify/chromium_libs_lock.py [--check]

Run by hand when the pinned Playwright's headless shell needs another library, or Debian's snapshot moves forward. It
reads the Packages indexes of the suite and snapshot ci_chromium_libs.py names (SUITE, SNAPSHOT), each from an
InRelease that gpgv checks against Debian's archive keyring and whose SHA-256 the index must match. From them it
resolves what `apt-get --no-install-recommends install` of the roots (every package SONAME_PACKAGE names, and
FONT_PACKAGES) brings in on top of a bare Debian: the Essential and required packages and what they depend on, which
every Debian host has. Each package in that closure becomes one line of the lock, with the packages of the lock it
depends on, so ci_chromium_libs.py can choose, offline, the ones the host lacks.

The indexes are read live: they are what the pins come from, not a pinned artifact. The .debs are not downloaded
here; ci_chromium_libs.py fetches each through the host artifact cache, which checks it against the pin.

--check rebuilds the lock in memory and exits 1 when it differs from the checked-in file.
"""
from __future__ import annotations

import hashlib
import lzma
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Iterable, Mapping

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import ci_chromium_libs as c  # noqa: E402

KEYRING = "/usr/share/keyrings/debian-archive-keyring.gpg"
ARCH = "amd64"


def archives(suite: str = c.SUITE, snapshot: str = c.SNAPSHOT) -> list[tuple[str, str]]:
    """(archive base URL, suite) for the main archive, its updates and its security archive at the snapshot."""
    debian = f"https://snapshot.debian.org/archive/debian/{snapshot}"
    security = f"https://snapshot.debian.org/archive/debian-security/{snapshot}"
    return [(debian, suite), (debian, f"{suite}-updates"), (security, f"{suite}-security")]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "wib-chromium-libs-lock"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def stanzas(text: str) -> list[dict[str, str]]:
    """The deb822 paragraphs of a Packages index, each field's continuation lines joined."""
    out = []
    for para in re.split(r"\n\s*\n", text):
        fields: dict[str, str] = {}
        key = ""
        for line in para.splitlines():
            if line[:1] in (" ", "\t") and key:
                fields[key] += "\n" + line.strip()
            elif ":" in line:
                key, _, value = line.partition(":")
                fields[key] = value.strip()
        if fields.get("Package"):
            out.append(fields)
    return out


def release_sha256(release: str, member: str) -> str:
    """The SHA-256 the (verified) Release text gives for member, such as main/binary-amd64/Packages.xz."""
    m = re.search(r"^SHA256:\n((?:[ \t].*\n?)+)", release, re.M)
    for line in (m.group(1).splitlines() if m else []):
        parts = line.split()
        if len(parts) == 3 and parts[2] == member:
            return parts[0]
    raise c.Failed(f"the Release file lists no SHA-256 for {member}")


def verified_release(inrelease: bytes, url: str) -> str:
    """The Release text of an InRelease that gpgv accepts against Debian's archive keyring."""
    with tempfile.TemporaryDirectory() as t:
        signed, out = pathlib.Path(t) / "InRelease", pathlib.Path(t) / "Release"
        signed.write_bytes(inrelease)
        p = subprocess.run(["gpgv", "--keyring", KEYRING, "--output", str(out), str(signed)],
                           capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            raise c.Failed(f"gpgv does not accept {url} against {KEYRING}: {p.stderr.strip()}")
        return out.read_text()


def index(base: str, suite: str) -> list[dict[str, str]]:
    """The packages of suite's main component for ARCH, each with the URL its Filename has under base."""
    url = f"{base}/dists/{suite}/InRelease"
    release = verified_release(fetch(url), url)
    member = f"main/binary-{ARCH}/Packages.xz"
    want = release_sha256(release, member)
    data = fetch(f"{base}/dists/{suite}/{member}")
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise c.Failed(f"{base}/dists/{suite}/{member} has SHA-256 {got}; its signed Release gives {want}")
    pkgs = stanzas(lzma.decompress(data).decode())
    for p in pkgs:
        p["URL"] = f"{base}/{p['Filename']}"
    return pkgs


def newer(a: str, b: str) -> bool:
    """Whether Debian version a sorts after b, by dpkg's own comparison."""
    return subprocess.run(["dpkg", "--compare-versions", a, "gt", b]).returncode == 0


def merge(indexes: Iterable[list[dict[str, str]]]) -> dict[str, dict[str, str]]:
    """One stanza per package: the highest version across the suites (an update or a security fix wins)."""
    out: dict[str, dict[str, str]] = {}
    for pkgs in indexes:
        for p in pkgs:
            have = out.get(p["Package"])
            if have is None or newer(p["Version"], have["Version"]):
                out[p["Package"]] = p
    return out


def clauses(p: Mapping[str, str]) -> list[list[str]]:
    """Pre-Depends and Depends as clauses of alternative package names, versions and arch qualifiers dropped."""
    out = []
    for field in ("Pre-Depends", "Depends"):
        for clause in filter(None, (s.strip() for s in p.get(field, "").split(","))):
            out.append([re.sub(r"\s*\(.*?\)|\s*\[.*?\]|:\w+$", "", alt).strip() for alt in clause.split("|")])
    return out


def providers(pkgs: Mapping[str, Mapping[str, str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, p in sorted(pkgs.items()):
        for prov in filter(None, (s.strip() for s in p.get("Provides", "").split(","))):
            out.setdefault(re.sub(r"\s*\(.*?\)", "", prov).strip(), []).append(name)
    return out


def satisfied(clause: list[str], have: set[str], provided: Mapping[str, list[str]]) -> bool:
    return any(alt in have or any(q in have for q in provided.get(alt, [])) for alt in clause)


def choose(clause: list[str], pkgs: Mapping[str, Mapping[str, str]], provided: Mapping[str, list[str]]) -> str:
    """The package apt would take for an unsatisfied clause: the first alternative that is a real package, else the
    first provider of the first alternative anything provides."""
    for alt in clause:
        if alt in pkgs:
            return alt
    for alt in clause:
        if provided.get(alt):
            return provided[alt][0]
    raise c.Failed(f"no package in the index is or provides any of {' | '.join(clause)}")


def closure(roots: Iterable[str], pkgs: Mapping[str, Mapping[str, str]], have: set[str]) -> dict[str, list[str]]:
    """Each package installing roots brings in on top of have, with the packages it depends on among them."""
    provided = providers(pkgs)
    deps: dict[str, list[str]] = {}
    todo = [r for r in roots if r not in have]
    missing = [r for r in todo if r not in pkgs]
    if missing:
        raise c.Failed(f"the index has no package {', '.join(missing)}")
    while todo:
        name = todo.pop()
        if name in deps:
            continue
        mine = deps[name] = []
        for clause in clauses(pkgs[name]):
            if satisfied(clause, have, provided):
                continue
            already = [a for a in clause if a in deps or a in todo]
            pick = already[0] if already else choose(clause, pkgs, provided)
            if pick not in mine:
                mine.append(pick)
            if pick not in deps:
                todo.append(pick)
    return {k: sorted(v) for k, v in sorted(deps.items())}


def base(pkgs: Mapping[str, Mapping[str, str]]) -> set[str]:
    """What every Debian host has: the Essential and required packages and everything they depend on."""
    seeds = {n for n, p in pkgs.items() if p.get("Essential") == "yes" or p.get("Priority") == "required"}
    return seeds | set(closure(sorted(seeds), pkgs, set()))


def render(pkgs: Mapping[str, Mapping[str, str]], deps: Mapping[str, list[str]], roots: list[str]) -> str:
    head = [
        "# ABOUTME: Every Debian package verify/ci_chromium_libs.py may unpack for Playwright's headless shell (#1120),",
        "# ABOUTME: each pinned by the SHA-256 Debian's signed Packages index gives. Written by verify/chromium_libs_lock.py.",
        "#",
        f"# Debian {c.SUITE}, {c.SUITE}-updates and {c.SUITE}-security for {ARCH}, as snapshot.debian.org holds them at "
        f"{c.SNAPSHOT}.",
        f"# The roots are {', '.join(roots)}.",
        "# Each line: package, version, SHA-256 of the .deb, its URL, and the packages of this lock it depends on",
        "# (\"-\" for none). What a bare Debian already has (its Essential and required packages) is not here.",
    ]
    lines = [f"{n} {pkgs[n]['Version']} {pkgs[n]['SHA256']} {pkgs[n]['URL']} {','.join(d) or '-'}"
             for n, d in deps.items()]
    return "\n".join(head + lines) + "\n"


def build() -> str:
    pkgs = merge(index(b, s) for b, s in archives())
    roots = sorted(set(c.SONAME_PACKAGE.values()) | set(c.FONT_PACKAGES))
    return render(pkgs, closure(roots, pkgs, base(pkgs)), roots)


def main(argv: list[str]) -> int:
    if argv not in ([], ["--check"]):
        print(__doc__.splitlines()[0], file=sys.stderr)
        return 2
    try:
        text = build()
    except (c.Failed, OSError) as e:
        print(f"chromium_libs_lock: {e}", file=sys.stderr)
        return 1
    if argv == ["--check"]:
        same = c.LOCK.read_text() == text
        print(f"chromium_libs_lock: {c.LOCK} {'matches' if same else 'differs from'} the snapshot's indexes")
        return 0 if same else 1
    c.LOCK.write_text(text)
    print(f"chromium_libs_lock: wrote {len(text.splitlines()) - 7} packages to {c.LOCK}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
