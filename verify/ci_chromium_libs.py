# ABOUTME: Gives the e2e tools job on Tanjiro the shared libraries Playwright's Chromium needs and the host lacks (#1047):
# ABOUTME: the missing Debian packages are unpacked into a job directory, never installed, and LD_LIBRARY_PATH names them.
"""Usage: GITHUB_ENV=<file> python3 verify/ci_chromium_libs.py <directory>

Why (#1047). The tools tier's Playwright tests launch the Chrome Headless Shell that verify/playwright_browsers.py
pins. On Tanjiro's runner it would not start: "error while loading shared libraries: libnspr4.so" (Actions run
42372183956 at staging ae188261). A bare Debian 13 lacks 21 of the libraries it links against: NSS, GLib, ATK, D-Bus,
the X client libraries, GBM, xkbcommon and ALSA. Tanjiro takes nothing from apt by hecaton or a run; its OS packages
belong to infrastructure-end-device-management (hecaton's docs/conventions/fleet-host-boundary.md). So this script
installs nothing. It maps the missing libraries to their packages, takes from verify/chromium-libs.lock those and
what they depend on that the host's dpkg does not have installed, unpacks each with `dpkg-deb -x` under <directory>,
and writes LD_LIBRARY_PATH into $GITHUB_ENV so the steps after it load them. Nothing the host already has is
unpacked, and no host library is shadowed.

Each .deb is pinned in the lock by the SHA-256 Debian's signed Packages index gives, at a snapshot.debian.org URL
that stays put (verify/chromium_libs_lock.py writes the lock), and is served through the host artifact cache
(verify/artifact_cache.py, #1120): a host downloads each once, every hit is checked against its pin, and a mismatch
fails without a second download. apt is never run, so a warm cache makes no network fetch at all.

With every library found the shell still stops on its first text when fontconfig has no fonts. So a host with no
/etc/fonts/fonts.conf or no font file gets fontconfig-config and a few font packages unpacked the same way, and
FONTCONFIG_FILE names a fonts.conf that reads them. Before writing anything, the shell renders a page of text to a
PNG with what was unpacked, so the step fails, not a test after it.

Where the host already has every library and a font, the script writes nothing: once EDM's build carries them, this
step does no work.

Nothing here falls back. No GITHUB_ENV, a browser the pinned Playwright does not list, a missing library this table
does not name, a package the lock does not pin, a host that is not Debian SUITE, a .deb the cache cannot serve
verified, or a library `ldd` still cannot find afterwards exits 1, naming which.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
from typing import NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import artifact_cache  # noqa: E402
from playwright_browsers import BROWSERS, PLAYWRIGHT, TIMEOUT, UV, ensure, listing  # noqa: E402

# The Debian release and snapshot.debian.org timestamp verify/chromium-libs.lock pins its packages from.
SUITE = "trixie"
SNAPSHOT = "20261107T000000Z"
SNAPSHOT_URLS = (f"https://snapshot.debian.org/archive/debian/{SNAPSHOT}/pool/",
                 f"https://snapshot.debian.org/archive/debian-security/{SNAPSHOT}/pool/")
LOCK = pathlib.Path(__file__).resolve().parent / "chromium-libs.lock"

# The headless shell Playwright's chromium.launch() starts, within its install location.
SHELL_ENTRY = "chromium-headless-shell"
SHELL_BINARY = pathlib.Path("chrome-headless-shell-linux64") / "chrome-headless-shell"

# Every library chrome-headless-shell v1248 links against that a bare debian:trixie lacks (ldd in the container, run
# 18178), and the Debian 13 package that ships it. The lock holds what these packages depend on.
SONAME_PACKAGE = {
    "libasound.so.2": "libasound2t64",
    "libatk-1.0.so.0": "libatk1.0-0t64",
    "libatk-bridge-2.0.so.0": "libatk-bridge2.0-0t64",
    "libatspi.so.0": "libatspi2.0-0t64",
    "libdbus-1.so.3": "libdbus-1-3",
    "libexpat.so.1": "libexpat1",
    "libgbm.so.1": "libgbm1",
    "libgio-2.0.so.0": "libglib2.0-0t64",
    "libglib-2.0.so.0": "libglib2.0-0t64",
    "libgobject-2.0.so.0": "libglib2.0-0t64",
    "libnspr4.so": "libnspr4",
    "libnss3.so": "libnss3",
    "libnssutil3.so": "libnss3",
    "libX11.so.6": "libx11-6",
    "libxcb.so.1": "libxcb1",
    "libXcomposite.so.1": "libxcomposite1",
    "libXdamage.so.1": "libxdamage1",
    "libXext.so.6": "libxext6",
    "libXfixes.so.3": "libxfixes3",
    "libxkbcommon.so.0": "libxkbcommon0",
    "libXrandr.so.2": "libxrandr2",
}
LIB_DIRS = ["usr/lib/x86_64-linux-gnu", "lib/x86_64-linux-gnu"]
# A host with no fonts gets fontconfig's rules and the families Debian's rules name first for sans-serif, serif and
# monospace (DejaVu), their metric-compatible Liberation set, and colour emoji; netcup, where the tier is green, has
# all of them.
FONT_PACKAGES = ["fontconfig-config", "fonts-dejavu-core", "fonts-liberation", "fonts-noto-color-emoji"]
# fontconfig-config's postinst links these from debconf's defaults (hinting style slight, no bitmaps except emoji).
# Without 10-hinting-slight, glyph advances round differently and the BurritoBot header button is 81px wide in its
# 80px box at a 360px viewport (test_mobile_titles_e2e.py, run 18178).
POSTINST_LINKS = ["10-hinting-slight.conf", "70-no-bitmaps-except-emoji.conf"]
FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".pfb", ".pcf", ".woff", ".woff2"}
NOT_FOUND = re.compile(r"^\s*(\S+)\s+=>\s+not found\s*$", re.M)


class Failed(Exception):
    pass


def missing_sonames(ldd_output: str) -> list[str]:
    """The libraries `ldd` printed as not found, each once, in the order printed."""
    return list(dict.fromkeys(NOT_FOUND.findall(ldd_output)))


def packages_for(sonames: list[str]) -> list[str]:
    """The Debian packages that ship sonames, sorted; a soname the table does not name fails, naming it."""
    unknown = [s for s in sonames if s not in SONAME_PACKAGE]
    if unknown:
        raise Failed(f"ldd finds no {', '.join(unknown)}, and SONAME_PACKAGE in {__file__} names no package for "
                     f"{'it' if len(unknown) == 1 else 'them'}")
    return sorted({SONAME_PACKAGE[s] for s in sonames})


def library_path(root: pathlib.Path, existing: str) -> str:
    """LD_LIBRARY_PATH with the unpacked library directories first, then whatever the job already had."""
    return ":".join([str(root / d) for d in LIB_DIRS] + ([existing] if existing else []))


def run(cmd: list[str], what: str, env: dict | None = None, cwd: pathlib.Path | None = None) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, env=env, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise Failed(f"{what} did not finish in {TIMEOUT}s: {' '.join(cmd)}")
    if p.returncode != 0:
        raise Failed(f"{what} exited {p.returncode}: {' '.join(cmd)}\n{p.stdout}{p.stderr}")
    return p.stdout


def shell_binary() -> pathlib.Path:
    """The installed Chrome Headless Shell of the pinned Playwright, installed first if it is missing."""
    problems = ensure()
    if problems:
        raise Failed("\n".join(problems))
    out = run([*UV, "playwright", "install", "--dry-run", *BROWSERS], f"`playwright install --dry-run` ({PLAYWRIGHT})")
    found = [loc / SHELL_BINARY for name, loc in listing(out) if SHELL_ENTRY in name]
    if len(found) != 1 or not found[0].is_file():
        raise Failed(f"{PLAYWRIGHT} lists {len(found)} {SHELL_ENTRY} install(s), not one installed binary: {found}")
    return found[0]


def ldd(binary: pathlib.Path, env: dict | None = None) -> list[str]:
    return missing_sonames(run(["ldd", str(binary)], "ldd", env=env))


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.splitlines()[0], file=sys.stderr)
        return 2
    github_env = os.environ.get("GITHUB_ENV", "")
    if not github_env:
        print("ci_chromium_libs: GITHUB_ENV is not set; nothing to write LD_LIBRARY_PATH to", file=sys.stderr)
        return 1
    root = pathlib.Path(argv[0]).resolve()
    unpacked = root / "root"
    try:
        binary = shell_binary()
        missing = ldd(binary)
        need_fonts = not host_has_fonts()
        if not missing and not need_fonts:
            print(f"ci_chromium_libs: {binary} finds every library it links against, and the host has fonts; "
                  "nothing to unpack")
            return 0
        wanted = sorted(set(packages_for(missing)) | (set(FONT_PACKAGES) if need_fonts else set()))
        print(f"ci_chromium_libs: {binary} lacks {', '.join(missing) or 'no library'}"
              f"{'; the host has no fonts' if need_fonts else ''}; unpacking {', '.join(wanted)} from {LOCK.name}")
        pkgs = unpack(wanted, unpacked)
        env: dict[str, str] = {}
        if missing:
            env["LD_LIBRARY_PATH"] = library_path(unpacked, os.environ.get("LD_LIBRARY_PATH", ""))
            still = ldd(binary, env={**os.environ, **env})
            if still:
                raise Failed(f"after unpacking {', '.join(pkgs)}, ldd still finds no {', '.join(still)}")
        if need_fonts:
            env["FONTCONFIG_FILE"] = str(write_fonts_conf(unpacked, root))
        probe(binary, root, {**os.environ, **env})
    except Failed as e:
        print(f"ci_chromium_libs: {e}", file=sys.stderr)
        return 1
    with open(github_env, "a") as f:
        f.writelines(f"{k}={v}\n" for k, v in env.items())
    print(f"ci_chromium_libs: unpacked {len(pkgs)} package(s) ({', '.join(pkgs)}) under {unpacked}; "
          f"the shell rendered a page with them; wrote {', '.join(f'{k}={v}' for k, v in env.items())}")
    return 0


def unpack(wanted: list[str], unpacked: pathlib.Path, lock: dict[str, Deb] | None = None,
           installed: set[str] | None = None, cache_root: pathlib.Path | None = None) -> list[str]:
    """Unpacks under unpacked each package of the lock that installing wanted needs and the host lacks, every .deb
    served through the host artifact cache and checked against its pin there. Returns them, in unpack order."""
    lock = read_lock() if lock is None else lock
    codename_matches()
    pkgs = plan(wanted, lock, installed_packages() if installed is None else installed)
    if not pkgs:
        raise Failed(f"the host has every package of {LOCK.name} that {', '.join(wanted)} need, yet the shell lacks "
                     "them")
    unpacked.mkdir(parents=True, exist_ok=True)
    for name in pkgs:
        deb = lock[name]
        try:
            path = artifact_cache.get(deb.sha256, deb.url, root=cache_root)
        except artifact_cache.ArtifactCacheError as e:
            raise Failed(f"{name} {deb.version}: {e}") from e
        run(["dpkg-deb", "-x", str(path), str(unpacked)], f"dpkg-deb -x {name} {deb.version} ({path})")
    return pkgs


class Deb(NamedTuple):
    version: str
    sha256: str
    url: str
    depends: tuple[str, ...]


def read_lock(path: pathlib.Path | None = None) -> dict[str, Deb]:
    """The lock's packages by name. A malformed line, a SHA-256 that is not one, a URL off the pinned snapshot, or a
    dependency the lock does not hold fails, naming the line."""
    path = LOCK if path is None else path
    out: dict[str, Deb] = {}
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 5:
            raise Failed(f"{path}:{n} has {len(parts)} fields, not 5 (package version sha256 url depends): {line}")
        name, version, sha256, url, deps = parts
        if not artifact_cache.SHA256.fullmatch(sha256):
            raise Failed(f"{path}:{n} pins {name} to {sha256!r}, which is not a SHA-256")
        if not url.startswith(SNAPSHOT_URLS):
            raise Failed(f"{path}:{n} fetches {name} from {url}, not from Debian's snapshot at {SNAPSHOT}")
        if name in out:
            raise Failed(f"{path}:{n} pins {name} a second time")
        out[name] = Deb(version, sha256, url, tuple(d for d in deps.split(",") if d != "-"))
    for name, deb in out.items():
        stray = [d for d in deb.depends if d not in out]
        if stray:
            raise Failed(f"{path} has {name} depend on {', '.join(stray)}, which it does not pin")
    return out


def plan(wanted: list[str], lock: dict[str, Deb], installed: set[str]) -> list[str]:
    """The lock's packages that installing wanted needs on a host with installed, each after what it depends on.
    A package the host has is not unpacked, and neither is what it depends on: dpkg has those installed already."""
    unknown = [w for w in wanted if w not in lock and w not in installed]
    if unknown:
        raise Failed(f"{LOCK} pins no {', '.join(unknown)}; rewrite it with verify/chromium_libs_lock.py")
    order: list[str] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen or name in installed:
            return
        seen.add(name)
        for dep in lock[name].depends:
            visit(dep)
        order.append(name)

    for w in sorted(wanted):
        visit(w)
    return order


def installed_packages() -> set[str]:
    """The packages dpkg has installed on the host, by name."""
    out = run(["dpkg-query", "-W", "-f", "${Package}\t${db:Status-Abbrev}\n"], "dpkg-query -W")
    return {name for name, _, status in (line.partition("\t") for line in out.splitlines()) if status.startswith("ii")}


def codename_matches(os_release: pathlib.Path = pathlib.Path("/etc/os-release")) -> None:
    """The lock is Debian SUITE's; any other host fails here, before a package of another release is unpacked."""
    got = codename(os_release)
    if got != SUITE:
        raise Failed(f"{os_release} names Debian {got}; {LOCK.name} pins Debian {SUITE}'s packages")


def codename(os_release: pathlib.Path = pathlib.Path("/etc/os-release")) -> str:
    """The Debian release the host runs, from VERSION_CODENAME; a host that names none, or is not Debian, fails."""
    fields = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', os_release.read_text() if os_release.is_file() else "", re.M))
    if fields.get("ID") != "debian" or not fields.get("VERSION_CODENAME"):
        raise Failed(f"{os_release} names ID={fields.get('ID')!r} VERSION_CODENAME={fields.get('VERSION_CODENAME')!r}; "
                     "the packages this unpacks are Debian's")
    return fields["VERSION_CODENAME"]


def host_has_fonts(etc: pathlib.Path = pathlib.Path("/etc/fonts"),
                   dirs: tuple[pathlib.Path, ...] = (pathlib.Path("/usr/share/fonts"),
                                                     pathlib.Path("/usr/local/share/fonts"))) -> bool:
    """Whether fontconfig has a configuration and at least one font file to read. Without one, the shell's Skia
    stops on its first text ("SkFontMgr_FontConfigInterface.cpp:163] Not implemented", run 18178)."""
    if not (etc / "fonts.conf").is_file():
        return False
    return any(p.suffix.lower() in FONT_SUFFIXES for d in dirs if d.is_dir() for p in d.rglob("*"))


def relink(conf_d: pathlib.Path, unpacked: pathlib.Path) -> None:
    """fontconfig-config's conf.d links point at /usr/share/fontconfig; point each into the unpacked tree instead,
    and add the links its postinst makes from debconf's defaults, which an unpack never runs (POSTINST_LINKS)."""
    for link in conf_d.iterdir():
        target = os.readlink(link) if link.is_symlink() else ""
        if target.startswith("/") and not pathlib.Path(target).is_relative_to(unpacked):
            link.unlink()
            link.symlink_to(unpacked / target.lstrip("/"))
    avail = unpacked / "usr/share/fontconfig/conf.avail"
    for name in POSTINST_LINKS:
        if not (avail / name).is_file():
            raise Failed(f"fontconfig-config unpacked no {avail / name} for its postinst's default link")
        if not (conf_d / name).is_symlink() and not (conf_d / name).exists():
            (conf_d / name).symlink_to(avail / name)


def fonts_conf(unpacked: pathlib.Path, conf_d: pathlib.Path, cache: pathlib.Path) -> str:
    """A fonts.conf that reads the unpacked fonts and rules, and the host's own font directories."""
    dirs = "\n".join(f"  <dir>{d}</dir>" for d in (unpacked / "usr/share/fonts", "/usr/share/fonts",
                                                   "/usr/local/share/fonts"))
    return ('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n<fontconfig>\n'
            f"{dirs}\n  <cachedir>{cache}</cachedir>\n"
            f'  <include ignore_missing="yes">{conf_d}</include>\n</fontconfig>\n')


def write_fonts_conf(unpacked: pathlib.Path, root: pathlib.Path) -> pathlib.Path:
    conf_d = unpacked / "etc/fonts/conf.d"
    if conf_d.is_dir():
        relink(conf_d, unpacked)
    else:
        conf_d = pathlib.Path("/etc/fonts/conf.d")
    if not any(p.suffix.lower() in FONT_SUFFIXES for p in (unpacked / "usr/share/fonts").rglob("*")):
        raise Failed(f"unpacking {', '.join(FONT_PACKAGES)} left no font file under {unpacked / 'usr/share/fonts'}")
    path = root / "fonts.conf"
    path.write_text(fonts_conf(unpacked, conf_d, root / "fontconfig-cache"))
    return path


def probe(binary: pathlib.Path, root: pathlib.Path, env: dict) -> None:
    """The shell renders a page of text to a PNG with what was unpacked, or this fails with what it printed."""
    shot = root / "probe.png"
    cmd = [str(binary), "--no-sandbox", f"--screenshot={shot}", "--window-size=320,120",
           "data:text/html,<p style='font-family:sans-serif'>ci_chromium_libs probe</p><p>monospace <code>x</code></p>"]
    run(cmd, "the shell's text render", env=env)
    if not shot.is_file() or shot.stat().st_size == 0:
        raise Failed(f"the shell exited 0 but wrote no screenshot at {shot}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
