# ABOUTME: Holds verify/ci_chromium_libs.py (#1047) offline: ldd and apt output parsing, the soname table, the fonts
# ABOUTME: check, the relinked fontconfig rules and the Debian-only sources, each on inputs this test writes itself.
"""Offline. The real run is the verify-suites workflow's e2e job on Tanjiro, and the bare debian:trixie containers of
runs 18178 and 18529, where the script unpacked the missing packages as a non-root user and the four Playwright tier
tests that Tanjiro failed passed (decisions.md). Nothing here runs apt, ldd or a browser, or reaches the internet:
since #1120 the packages come from chromium-libs.lock through the host artifact cache, so the cache tests serve
fixture .debs this test builds with `dpkg-deb --build` from a ThreadingHTTPServer on 127.0.0.1, with a lock of the
test's own, and the lock writer's closure is held on a fixture Packages index.
"""
from __future__ import annotations

import hashlib
import http.server
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import artifact_cache  # noqa: E402
import chromium_libs_lock as L  # noqa: E402
import ci_chromium_libs as c  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + label + (f"\n     {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


print("== ldd's not-found lines ==")
LDD = """\tlinux-vdso.so.1 (0x00007ffd)
\tlibglib-2.0.so.0 => not found
\tlibdl.so.2 => /lib/x86_64-linux-gnu/libdl.so.2 (0x00007f)
\tlibnspr4.so => not found
\tlibglib-2.0.so.0 => not found
"""
check("each not-found library once, in ldd's order, and none that resolved",
      c.missing_sonames(LDD) == ["libglib-2.0.so.0", "libnspr4.so"], str(c.missing_sonames(LDD)))
check("ldd with every library found gives none", c.missing_sonames("\tlibc.so.6 => /lib/libc.so.6 (0x1)\n") == [])

print("== the soname table ==")
# The 21 run 18178 read from ldd in a bare debian:trixie container.
BARE_TRIXIE = ["libglib-2.0.so.0", "libgobject-2.0.so.0", "libnspr4.so", "libnss3.so", "libnssutil3.so",
               "libgio-2.0.so.0", "libatk-1.0.so.0", "libatk-bridge-2.0.so.0", "libdbus-1.so.3", "libX11.so.6",
               "libXcomposite.so.1", "libXdamage.so.1", "libXext.so.6", "libXfixes.so.3", "libXrandr.so.2",
               "libgbm.so.1", "libexpat.so.1", "libxcb.so.1", "libxkbcommon.so.0", "libasound.so.2", "libatspi.so.0"]
check("the table names a package for every library a bare Debian 13 lacks",
      set(BARE_TRIXIE) <= set(c.SONAME_PACKAGE), str(set(BARE_TRIXIE) - set(c.SONAME_PACKAGE)))
got = c.packages_for(["libnss3.so", "libnssutil3.so", "libglib-2.0.so.0", "libgio-2.0.so.0"])
check("two libraries of one package ask for it once, sorted", got == ["libglib2.0-0t64", "libnss3"], str(got))
try:
    c.packages_for(["libnspr4.so", "libnotachrome.so.9"])
    check("a library the table does not name fails", False, "no Failed raised")
except c.Failed as e:
    check("a library the table does not name fails, naming it", "libnotachrome.so.9" in str(e), str(e))

print("== LD_LIBRARY_PATH ==")
root = pathlib.Path("/w/root")
check("the unpacked directories come first, then the job's own",
      c.library_path(root, "/opt/x") == "/w/root/usr/lib/x86_64-linux-gnu:/w/root/lib/x86_64-linux-gnu:/opt/x")
check("with no LD_LIBRARY_PATH before, no empty entry (an empty entry is the current directory)",
      not c.library_path(root, "").endswith(":"))

with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)

    print("== the host's fonts ==")
    etc, fonts = t / "etc-fonts", t / "share-fonts"
    etc.mkdir()
    fonts.mkdir()
    check("no fonts.conf: no fonts", not c.host_has_fonts(etc, (fonts,)))
    (etc / "fonts.conf").write_text("<fontconfig/>")
    check("a fonts.conf and no font file: no fonts", not c.host_has_fonts(etc, (fonts,)))
    (fonts / "truetype" / "x").mkdir(parents=True)
    (fonts / "truetype" / "x" / "README").write_text("not a font")
    check("a file that is not a font does not count", not c.host_has_fonts(etc, (fonts,)))
    (fonts / "truetype" / "x" / "X-Regular.TTF").write_text("")
    check("a fonts.conf and one font file, in any case: fonts", c.host_has_fonts(etc, (fonts, t / "missing")))

    print("== fontconfig-config's rules, relinked ==")
    unpacked = t / "root"
    avail = unpacked / "usr/share/fontconfig/conf.avail"
    conf_d = unpacked / "etc/fonts/conf.d"
    avail.mkdir(parents=True)
    conf_d.mkdir(parents=True)
    (unpacked / "etc/fonts/conf.avail").mkdir()
    for name in ["30-metric-aliases.conf", *c.POSTINST_LINKS]:
        (avail / name).write_text(name)
    (unpacked / "etc/fonts/conf.avail/57-dejavu-sans.conf").write_text("dejavu")
    (conf_d / "30-metric-aliases.conf").symlink_to("/usr/share/fontconfig/conf.avail/30-metric-aliases.conf")
    (conf_d / "57-dejavu-sans.conf").symlink_to("../conf.avail/57-dejavu-sans.conf")
    (conf_d / "README").write_text("readme")
    c.relink(conf_d, unpacked)
    check("an absolute link now reads the unpacked rule",
          (conf_d / "30-metric-aliases.conf").read_text() == "30-metric-aliases.conf",
          os.readlink(conf_d / "30-metric-aliases.conf"))
    check("a relative link is left as it was", os.readlink(conf_d / "57-dejavu-sans.conf")
          == "../conf.avail/57-dejavu-sans.conf" and (conf_d / "57-dejavu-sans.conf").read_text() == "dejavu")
    check("the postinst's default links are added, reading the unpacked rules",
          all((conf_d / n).read_text() == n for n in c.POSTINST_LINKS))
    check("10-hinting-slight is among them (without it a 360px header button clips by a pixel)",
          "10-hinting-slight.conf" in c.POSTINST_LINKS)
    c.relink(conf_d, unpacked)
    check("relinking again changes nothing", all((conf_d / n).read_text() == n for n in c.POSTINST_LINKS))
    (avail / c.POSTINST_LINKS[0]).unlink()
    (conf_d / c.POSTINST_LINKS[0]).unlink()
    try:
        c.relink(conf_d, unpacked)
        check("a postinst rule the unpack lacks fails", False, "no Failed raised")
    except c.Failed as e:
        check("a postinst rule the unpack lacks fails, naming it", c.POSTINST_LINKS[0] in str(e), str(e))

    conf = c.fonts_conf(unpacked, conf_d, t / "cache")
    check("fonts.conf reads the unpacked fonts, the host's, the relinked rules and a cache of the job's own",
          all(s in conf for s in (f"<dir>{unpacked}/usr/share/fonts</dir>", "<dir>/usr/share/fonts</dir>",
                                  f"<cachedir>{t / 'cache'}</cachedir>", f">{conf_d}</include>")), conf)

    print("== the host's Debian release ==")
    rel = t / "os-release"
    rel.write_text('PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\nVERSION_CODENAME=trixie\n')
    check("the codename comes from os-release", c.codename(rel) == "trixie")
    rel.write_text('ID=ubuntu\nVERSION_CODENAME=noble\n')
    try:
        c.codename(rel)
        check("a host that is not Debian fails", False, "no Failed raised")
    except c.Failed as e:
        check("a host that is not Debian fails, naming what it read", "ubuntu" in str(e), str(e))

    print("== no GITHUB_ENV ==")
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_ENV"}
    r = subprocess.run([sys.executable, str(pathlib.Path(c.__file__)), str(t / "out")], env=env,
                       capture_output=True, text=True, timeout=60)
    check("no GITHUB_ENV exits 1, naming it, and unpacks nothing",
          r.returncode == 1 and "GITHUB_ENV" in r.stderr and not (t / "out").exists(),
          f"exit {r.returncode}: {r.stdout}{r.stderr}")

print("== the host's dpkg database ==")
QUERY = ("libc6\tinstalled\t\nlibc6:i386\tinstalled\t\nmawk\tinstalled\tawk\n"
         "libgone1\tconfig-files\t\nfonts-x\tinstalled\tfonts-virtual (= 1), other-virtual\n")
have = c.host_packages(QUERY)
check("installed packages count, with an arch qualifier dropped",
      {"libc6", "mawk", "fonts-x"} <= have, str(sorted(have)))
check("a package left only as config files does not", "libgone1" not in have, str(sorted(have)))
check("each virtual name an installed package provides counts, with its version dropped",
      {"awk", "fonts-virtual", "other-virtual"} <= have, str(sorted(have)))


def pkg(name: str, depends: str = "") -> L.Package:
    return L.Package(name, "1", "0" * 64, f"http://x.invalid/{name}.deb", L.parse_depends(depends))


print("== resolving against the lock and the host ==")
LOCKED = {p.name: p for p in (pkg("libfoo1", "libbar1, libc6, fonts-a | fonts-b"), pkg("libbar1", "awk | gawk"),
                              pkg("fonts-a"), pkg("fonts-b"), pkg("gawk"), pkg("libnew1", "libmissing0"),
                              pkg("libalt1", "fonts-virtual | fonts-a"))}
got = c.resolve(["libfoo1"], LOCKED, {"libc6"})
check("a wanted package and the depends the host lacks, each once, wanted first",
      got == ["libfoo1", "libbar1", "fonts-a", "gawk"], str(got))
got = c.resolve(["libfoo1"], LOCKED, {"libc6", "mawk", "awk", "fonts-b"})
check("a group the host meets with any alternative, or a virtual name it provides, brings nothing in",
      got == ["libfoo1", "libbar1"], str(got))
got = c.resolve(["libalt1"], LOCKED, have)
check("a group met by a virtual name the host's packages provide brings nothing in", got == ["libalt1"], str(got))
check("a wanted package the host has is not unpacked", c.resolve(["libbar1"], LOCKED, {"libbar1"}) == [])
for wanted, needle, what in ((["libnotpinned0"], "pins no libnotpinned0", "a wanted package the lock does not pin"),
                             (["libnew1"], "libmissing0", "a depends the host lacks and the lock does not pin")):
    try:
        c.resolve(wanted, LOCKED, {"libc6"})
        check(f"{what} fails", False, "no Failed raised")
    except c.Failed as e:
        check(f"{what} fails, naming it", needle in str(e), str(e))

print("== the lock writer, on a fixture Packages index ==")
check("a Depends field reads as groups of alternatives, with versions and arch qualifiers dropped",
      L.parse_depends("libc6 (>= 2.34), libx11-6 | libx11-xcb1:any, python3:any (>= 3.11) [amd64]")
      == (("libc6",), ("libx11-6", "libx11-xcb1"), ("python3",)))
INDEX = """Package: libc6
Version: 2.41-12
Priority: optional
SHA256: aa
Filename: pool/main/g/glibc/libc6_2.41-12_amd64.deb

Package: base-files
Version: 13.8
Priority: required
Essential: yes
Pre-Depends: awk
Depends: libc6
SHA256: bb
Filename: pool/main/b/base-files/base-files_13.8_amd64.deb

Package: mawk
Version: 1.3.4
Priority: required
Provides: awk
SHA256: cc
Filename: pool/main/m/mawk/mawk_1.3.4_amd64.deb

Package: gawk
Version: 5.2
Priority: optional
Provides: awk
SHA256: dd
Filename: pool/main/g/gawk/gawk_5.2_amd64.deb

Package: libnss3
Version: 2:3.110-1
Priority: optional
Depends: libc6 (>= 2.34), libnspr4 (>= 2:4.36),
 fontconfig-config | fonts-virtual
SHA256: ee
Filename: pool/main/n/nss/libnss3_3.110-1_amd64.deb

Package: libnspr4
Version: 2:4.36-1
Priority: optional
Depends: awk
SHA256: ff
Filename: pool/main/n/nspr/libnspr4_4.36-1_amd64.deb

Package: fonts-z
Version: 1
Priority: optional
Provides: fonts-virtual
SHA256: 11
Filename: pool/main/f/fonts-z/fonts-z_1_all.deb
"""
idx = L.Index([("debian", st) for st in L.stanzas(INDEX)])
check("a continuation line joins the field before it", idx.depends("libnss3")[-1] == ("fontconfig-config", "fonts-virtual"))
base = idx.base()
check("the base is every required or Essential package and what they need, with awk met by mawk, not gawk",
      base == {"base-files", "mawk", "libc6"}, str(sorted(base)))
built = L.build(idx, ["libnss3"])
check("the closure pins the roots and what they reach outside the base",
      sorted(built.packages) == ["fonts-z", "libnspr4", "libnss3"], str(sorted(built.packages)))
check("a group the base meets is left out of the depends",
      built.packages["libnss3"].depends == (("libnspr4",), ("fontconfig-config", "fonts-virtual", "fonts-z"))
      and built.packages["libnspr4"].depends == (), str(built.packages["libnss3"].depends))
check("a .deb's URL is snapshot.debian.org's, at the lock's timestamp",
      built.packages["libnss3"].url == f"https://snapshot.debian.org/archive/debian/{L.SNAPSHOT}/"
                                       "pool/main/n/nss/libnss3_3.110-1_amd64.deb")
rel = "SHA256:\n aaaa 12 main/binary-amd64/Packages\n bbbb 34 main/binary-amd64/Packages.xz\nX: y\n"
check("the signed InRelease gives the index its SHA-256", L.release_sha256(rel, L.INDEX) == "bbbb")
try:
    L.release_sha256(rel, "contrib/binary-amd64/Packages.xz")
    check("an index the InRelease does not name fails", False, "no LockError raised")
except L.LockError as e:
    check("an index the InRelease does not name fails, naming it", "contrib/binary-amd64" in str(e), str(e))

print("== the checked-in chromium-libs.lock ==")
lock = L.read()
check(f"it is Debian {lock.suite} {lock.arch} at snapshot {lock.snapshot}, the writer's",
      (lock.snapshot, lock.suite, lock.arch) == (L.SNAPSHOT, L.SUITE, L.ARCH))
check("it pins every package the soname table and the font list name",
      set(L.roots()) <= set(lock.packages), str(set(L.roots()) - set(lock.packages)))
open_groups = [(p.name, g) for p in lock.packages.values() for g in p.depends if not any(a in lock.packages for a in g)]
check("it is closed: every depends group it records has a pinned alternative", open_groups == [], str(open_groups))
check("every .deb is at snapshot.debian.org, at the lock's timestamp",
      all(p.url.startswith(("https://snapshot.debian.org/archive/debian/" + L.SNAPSHOT + "/pool/",
                            "https://snapshot.debian.org/archive/debian-security/" + L.SNAPSHOT + "/pool/"))
          and p.url.endswith(".deb") for p in lock.packages.values()), "")
check("it is in the form the writer renders", L.render(lock) == L.LOCK.read_text())
bare = c.resolve(sorted(set(c.SONAME_PACKAGE.values()) | set(c.FONT_PACKAGES)), lock.packages, set())
check(f"on a host with nothing, every pinned package is reached ({len(bare)} of {len(lock.packages)})",
      sorted(bare) == sorted(lock.packages), str(set(lock.packages) - set(bare)))


class Server:
    """Serves self.files by path and counts requests."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.hits = 0
        srv = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                srv.hits += 1
                body = srv.files.get(self.path)
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"


def build_deb(work: pathlib.Path, name: str, files: dict[str, str]) -> bytes:
    tree = work / f"{name}-tree"
    (tree / "DEBIAN").mkdir(parents=True)
    (tree / "DEBIAN" / "control").write_text(f"Package: {name}\nVersion: 1\nArchitecture: amd64\n"
                                             f"Maintainer: test <t@x.invalid>\nDescription: fixture\n")
    for rel, text in files.items():
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text(text)
    out = work / f"{name}.deb"
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(tree), str(out)], check=True,
                   capture_output=True, timeout=60)
    return out.read_bytes()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


print("== unpacking from the host artifact cache ==")
with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    srv = Server()
    debs = {"libfoo1": build_deb(t, "libfoo1", {"usr/lib/x86_64-linux-gnu/libfoo.so.1": "foo"}),
            "libbar1": build_deb(t, "libbar1", {"usr/lib/x86_64-linux-gnu/libbar.so.1": "bar"})}
    for n, b in debs.items():
        srv.files[f"/{n}.deb"] = b
    lock_path = t / "chromium-libs.lock"

    def write_test_lock(sums: dict[str, str] | None = None) -> None:
        sums = {n: sha(b) for n, b in debs.items()} | (sums or {})
        lock_path.write_text(L.render(L.Lock("20260101T000000Z", "trixie", "amd64", {
            "libfoo1": L.Package("libfoo1", "1", sums["libfoo1"], srv.url("/libfoo1.deb"), (("libbar1",), ("libc6",))),
            "libbar1": L.Package("libbar1", "1", sums["libbar1"], srv.url("/libbar1.deb"), ())})))

    write_test_lock()
    rel = t / "os-release"
    rel.write_text("ID=debian\nVERSION_CODENAME=trixie\n")
    cache = artifact_cache.scratch_dir("cilibs-cache-")
    fetch_log = cache / "fetch.log"
    kw = {"lock_path": lock_path, "os_release": rel, "dpkg_query": "libc6\tinstalled\t\n", "arch": "amd64",
          "root": cache, "env": {}, "backoff": ()}

    def lines() -> list[str]:
        return fetch_log.read_text().splitlines() if fetch_log.exists() else []

    try:
        got = c.unpack(["libfoo1"], t / "job1", **kw)
        check("a miss: the wanted package and its depends are unpacked", got == ["libfoo1", "libbar1"]
              and (t / "job1/usr/lib/x86_64-linux-gnu/libfoo.so.1").read_text() == "foo"
              and (t / "job1/usr/lib/x86_64-linux-gnu/libbar.so.1").read_text() == "bar", str(got))
        check("each .deb was fetched once and logged `ok` with its URL and pin",
              srv.hits == 2 and len(lines()) == 2 and all(ln.endswith("\tok") for ln in lines())
              and {ln.split("\t")[2] for ln in lines()} == {sha(b) for b in debs.values()}, str(lines()))
        srv.httpd.shutdown()
        got = c.unpack(["libfoo1"], t / "job2", **kw)
        check("a hit: a new job directory on the same cache unpacks with the server stopped, no request, no log line",
              got == ["libfoo1", "libbar1"] and srv.hits == 2 and len(lines()) == 2
              and (t / "job2/usr/lib/x86_64-linux-gnu/libbar.so.1").read_text() == "bar", str(lines()))
        threading.Thread(target=srv.httpd.serve_forever, daemon=True).start()
        entry = artifact_cache.path_for(sha(debs["libbar1"]), cache)
        entry.write_bytes(debs["libbar1"] + b"x")
        try:
            c.unpack(["libfoo1"], t / "job3", **kw)
            check("a cached .deb that no longer matches fails", False, "no Failed raised")
        except c.Failed as e:
            check("a cached .deb that no longer matches fails, naming the package, the path and both sums",
                  "libbar1 1" in str(e) and str(entry) in str(e) and sha(debs["libbar1"]) in str(e)
                  and sha(debs["libbar1"] + b"x") in str(e), str(e))
        check("and it is not fetched again over it", srv.hits == 2 and entry.read_bytes() == debs["libbar1"] + b"x")
        write_test_lock({"libfoo1": sha(b"other")})
        cold = artifact_cache.scratch_dir("cilibs-cold-")
        try:
            c.unpack(["libfoo1"], t / "job4", **{**kw, "root": cold})
            check("a download that does not match fails", False, "no Failed raised")
        except c.Failed as e:
            check("a download that does not match fails, naming the URL and both sums",
                  srv.url("/libfoo1.deb") in str(e) and sha(b"other") in str(e) and sha(debs["libfoo1"]) in str(e),
                  str(e))
        check("nothing is cached under its pin and nothing unpacked",
              not artifact_cache.path_for(sha(b"other"), cold).exists() and not (t / "job4/usr").exists())
        shutil.rmtree(cold)
        write_test_lock()
        for what, extra, needle in (("a host on another Debian release", {"os_release": t / "bookworm"}, "bookworm"),
                                    ("a host of another architecture", {"arch": "arm64"}, "arm64"),
                                    ("a missing lock", {"lock_path": t / "no.lock"}, "no.lock")):
            (t / "bookworm").write_text("ID=debian\nVERSION_CODENAME=bookworm\n")
            try:
                c.unpack(["libfoo1"], t / "job5", **{**kw, **extra})
                check(f"{what} fails", False, "no Failed raised")
            except c.Failed as e:
                check(f"{what} fails, naming it, before any fetch", needle in str(e) and srv.hits == 3, str(e))
    finally:
        srv.httpd.shutdown()
        srv.httpd.server_close()
        shutil.rmtree(cache)

print("== no apt ==")
code = "\n".join(ln for ln in pathlib.Path(c.__file__).read_text().splitlines() if not ln.lstrip().startswith("#"))
check("ci_chromium_libs.py runs no apt-get and reads no apt list", '"apt-get"' not in code and "apt_dir" not in code)

if failures:
    print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("\nAll ci_chromium_libs checks passed.")
