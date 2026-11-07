# ABOUTME: Holds verify/ci_chromium_libs.py (#1047) offline: ldd and apt output parsing, the soname table, the fonts
# ABOUTME: check, the relinked fontconfig rules and the Debian-only sources, each on inputs this test writes itself.
"""Offline. The real run is the verify-suites workflow's e2e job on Tanjiro, and run 18178's bare debian:trixie
container, where the script unpacked 49 packages as a non-root user and the four Playwright tier tests that Tanjiro
failed passed (decisions.md). Nothing here runs apt, ldd or a browser.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
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

print("== apt-get -s install's Inst lines ==")
SIM = """NOTE: This is only a simulation!
Inst libnspr4 (2:4.36-1 Debian:13.1/stable [amd64])
Inst libnss3 (2:3.110-1 Debian:13.1/stable [amd64])
Conf libnspr4 (2:4.36-1 Debian:13.1/stable [amd64])
Inst libnspr4 (2:4.36-1 Debian:13.1/stable [amd64])
"""
check("each package apt would install, once, and no Conf line", c.to_unpack(SIM) == ["libnspr4", "libnss3"],
      str(c.to_unpack(SIM)))
check("a simulation with nothing to install gives none", c.to_unpack("0 upgraded, 0 newly installed\n") == [])

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

    print("== Debian's archive as the only source ==")
    rel = t / "os-release"
    rel.write_text('PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\nVERSION_CODENAME=trixie\n')
    check("the codename comes from os-release", c.codename(rel) == "trixie")
    rel.write_text('ID=ubuntu\nVERSION_CODENAME=noble\n')
    try:
        c.codename(rel)
        check("a host that is not Debian fails", False, "no Failed raised")
    except c.Failed as e:
        check("a host that is not Debian fails, naming what it read", "ubuntu" in str(e), str(e))
    src = c.debian_sources("trixie")
    check("the sources are trixie, trixie-updates and trixie-security, each signed by Debian's keyring",
          "Suites: trixie trixie-updates" in src and "Suites: trixie-security" in src
          and src.count("Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg") == 2, src)

    print("== no GITHUB_ENV ==")
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_ENV"}
    r = subprocess.run([sys.executable, str(pathlib.Path(c.__file__)), str(t / "out")], env=env,
                       capture_output=True, text=True, timeout=60)
    check("no GITHUB_ENV exits 1, naming it, and unpacks nothing",
          r.returncode == 1 and "GITHUB_ENV" in r.stderr and not (t / "out").exists(),
          f"exit {r.returncode}: {r.stdout}{r.stderr}")

if failures:
    print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("\nAll ci_chromium_libs checks passed.")
