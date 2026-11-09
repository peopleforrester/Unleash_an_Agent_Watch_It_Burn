# ABOUTME: The Backstage app's own yarn 4 and its conditional-checksums plugin on a loopback registry (#1167): a
# ABOUTME: platform-conditional package whose cached or fetched zip differs from the lock fails the install, unlinked.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS, no network: node and the committed yarn release, on fixtures served locally)
"""The end-to-end half of verify/test_yarn_pins.py.

A registry on 127.0.0.1 (yarn_pins.Registry) serves two native-style fixture packages, each with an `os` and `cpu`
field: wib-native for this host's platform and wib-elsewhere for aix on ppc64. A project lists both as
optionalDependencies, as the Backstage app's dependencies list @esbuild/linux-x64 and its siblings, so yarn.lock gives
both a `conditions:` line. The project carries the app's yarn-plugins/conditional-checksums.cjs, named by YARN_PLUGINS
as run-e2e.sh names it, and a lock made by yarn_pins.record(), the path `yarn_pins.py write` takes.

  - the premise: yarn.lock records no checksum for either conditional package, and without the plugin a cached zip
    whose bytes changed installs with no error;
  - the lock: record() gives each package a checksum in the cache's `<cacheKey>/<sha512>` form;
  - cold: the install fetches wib-native, the plugin reports it matches, it is installed, and wib-elsewhere's tarball
    is never asked for;
  - warm: a fresh project installs `--immutable` from the cache with no request;
  - a cached zip whose bytes changed fails with YN0018 naming the package, the lock and both checksums, makes no
    request, leaves the zip as it was, and links nothing;
  - a fetched copy that differs (a registry serving other bytes under the same name and version) fails the same way
    after one fetch, and links nothing;
  - a package the lock has no line for fails, naming it.

Needs node. A missing tool is a failure, not a skip.
"""
from __future__ import annotations

import hashlib
import io
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import zipfile

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
sys.path.insert(0, str(VERIFY))
import artifact_cache  # noqa: E402
import yarn_pins as yp  # noqa: E402

BACKSTAGE = REPO / "images/watch-it-burn-backstage"
PLUGIN = BACKSTAGE / yp.PLUGIN_REL
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    shutil.rmtree(SCRATCH, ignore_errors=True)
    if failures:
        print(f"\nFAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nAll conditional-checksum end-to-end checks passed.")
    sys.exit(0)


print("== prerequisites ==")
check(f"node is on PATH ({shutil.which('node')})", shutil.which("node") is not None)
release = BACKSTAGE / ".yarn/releases"
yarn_release = sorted(release.glob("yarn-4.*.cjs"))
check(f"the Backstage app commits a yarn 4 release ({[p.name for p in yarn_release]})", len(yarn_release) == 1)
check(f"the app commits the plugin ({yp.PLUGIN_REL})", PLUGIN.is_file())
SCRATCH = artifact_cache.scratch_dir("wib-yarn-pins-e2e-")
if failures:
    finish()
YARN = yarn_release[0]
host = subprocess.run(["node", "-p", "process.platform + ' ' + process.arch"], capture_output=True, text=True,
                      check=True).stdout.split()
PLATFORM, ARCH = host[0], host[1]


def tgz(name: str, value: int) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for n, d in (("package/package.json", f'{{"name":"{name}","version":"1.0.0","main":"index.js"}}'.encode()),
                     ("package/index.js", f"module.exports = {value};\n".encode())):
            info = tarfile.TarInfo(n)
            info.size, info.mtime = len(d), 0
            t.addfile(info, io.BytesIO(d))
    return buf.getvalue()


def packages(native_value: int) -> dict:
    return {("wib-native", "1.0.0"): ({"os": [PLATFORM], "cpu": [ARCH]}, tgz("wib-native", native_value)),
            ("wib-elsewhere", "1.0.0"): ({"os": ["aix"], "cpu": ["ppc64"]}, tgz("wib-elsewhere", 7))}


NATIVE = "wib-native@npm:1.0.0"
ELSEWHERE = "wib-elsewhere@npm:1.0.0"
TAR_ELSEWHERE = "/wib-elsewhere/-/wib-elsewhere-1.0.0.tgz"
GLOBAL = SCRATCH / "yarn-global"


def project(name: str, reg: yp.Registry, lockfile: str, lock_rows: dict | None) -> pathlib.Path:
    d = SCRATCH / name
    (d / "yarn-plugins").mkdir(parents=True)
    (d / "package.json").write_text('{"name":"wib-pins-user","private":true,'
                                    '"optionalDependencies":{"wib-native":"1.0.0","wib-elsewhere":"1.0.0"}}')
    (d / ".yarnrc.yml").write_text(yp.yarnrc(reg.url))
    (d / "yarn.lock").write_text(lockfile)
    shutil.copy2(PLUGIN, d / yp.PLUGIN_REL)
    if lock_rows is not None:
        (d / yp.LOCK_REL).write_text(yp.render_lock(lock_rows, YARN.name))
    return d


def yarn(d: pathlib.Path, *args: str, plugin: bool = True, global_folder: pathlib.Path = GLOBAL):
    env = yp.yarn_env(global_folder)
    if plugin:
        env["YARN_PLUGINS"] = str(d / yp.PLUGIN_REL)
    r = subprocess.run(["node", str(YARN), "install", *args], cwd=d, capture_output=True, text=True, env=env,
                       timeout=300)
    return r, r.stdout + r.stderr


def installed(d: pathlib.Path) -> str:
    f = d / "node_modules" / "wib-native" / "index.js"
    return f.read_text() if f.is_file() else ""


with yp.Registry(packages(42)) as reg:
    print("== the lock: record() zips each package with the app's yarn and reads its checksum ==")
    try:
        sums = yp.record([NATIVE, ELSEWHERE], reg.url, YARN, SCRATCH / "record")
    except yp.YarnPinsError as e:
        check("record() succeeds", False, str(e))
        finish()
    check(f"each package gets a checksum in the cache's form ({sums})",
          all(s.startswith("10c0/") and len(s) == 5 + 128 for s in sums.values()) and len(sums) == 2)
    rows = {loc: (s, yp.integrity_of(packages(42)[yp.npm_base(loc)][1])) for loc, s in sums.items()}

    print(f"== cold: the plugin checks wib-native ({PLATFORM}/{ARCH}) as it is fetched; wib-elsewhere is never fetched ==")
    reg.requests.clear()
    cold = project("cold", reg, "", rows)
    r, out = yarn(cold, "--no-immutable")
    check(f"`yarn install` with the plugin succeeds (exit {r.returncode})", r.returncode == 0, out[-1200:])
    check("the plugin reports the one enabled conditional package matches the lock",
          f"1 platform-conditional package(s) match {yp.LOCK_REL}" in out, out[-800:])
    check(f"wib-native's tarball was fetched and wib-elsewhere's was not ({reg.requests})",
          "/wib-native/-/wib-native-1.0.0.tgz" in reg.requests and TAR_ELSEWHERE not in reg.requests)
    check("wib-native is installed", installed(cold) == "module.exports = 42;\n", installed(cold))
    lockfile = (cold / "yarn.lock").read_text()
    entries = {e["resolution"]: e for e in yp.lock_entries(lockfile)}
    check("the premise: yarn.lock gives both a `conditions:` line and records a checksum for neither",
          all(entries.get(loc, {}).get("conditions") and not entries[loc]["checksum"] for loc in (NATIVE, ELSEWHERE)),
          lockfile)
    zips = sorted((GLOBAL / "cache").glob("wib-native-npm-1.0.0-*.zip"))
    check(f"wib-native's zip is in the global cache ({[z.name for z in zips]})", len(zips) == 1)
    if failures:
        finish()
    ZIP = zips[0]

    print("== warm: a fresh project installs --immutable from the cache, checked, with no request ==")
    reg.requests.clear()
    warm = project("warm", reg, lockfile, rows)
    r, out = yarn(warm, "--immutable")
    check(f"`yarn install --immutable` succeeds (exit {r.returncode})", r.returncode == 0, out[-1200:])
    check(f"no request to the registry ({reg.requests})", reg.requests == [])
    check("the plugin checked it", f"1 platform-conditional package(s) match {yp.LOCK_REL}" in out, out[-800:])
    check("wib-native is installed", installed(warm) == "module.exports = 42;\n", installed(warm))

    print("== a cached zip whose bytes changed ==")
    original = ZIP.read_bytes()
    with zipfile.ZipFile(ZIP) as src:
        items = [(i, src.read(i.filename)) for i in src.infolist()]
    with zipfile.ZipFile(ZIP, "w") as out_zip:
        for i, d in items:
            out_zip.writestr(i, d.replace(b"42", b"43"))
    tampered = ZIP.read_bytes()
    reg.requests.clear()
    bare = project("tampered-no-plugin", reg, lockfile, rows)
    r, out = yarn(bare, "--immutable", plugin=False)
    check(f"the premise: without the plugin, yarn 4 installs it with no error (exit {r.returncode})",
          r.returncode == 0 and installed(bare) == "module.exports = 43;\n", out[-800:])
    bad = project("tampered", reg, lockfile, rows)
    r, out = yarn(bad, "--immutable")
    got = f"10c0/{hashlib.sha512(tampered).hexdigest()}"
    check(f"with the plugin, `yarn install --immutable` fails (exit {r.returncode}) with YN0018, naming the package, "
          "the lock and both checksums",
          r.returncode != 0 and "YN0018" in out and NATIVE in out and yp.LOCK_REL in out and rows[NATIVE][0] in out
          and got in out, out[-1500:])
    check(f"no request to the registry ({reg.requests})", reg.requests == [])
    check("the cached zip is left as it was found", ZIP.read_bytes() == tampered)
    check("and nothing is linked: wib-native is not installed", installed(bad) == "", installed(bad))
    ZIP.write_bytes(original)

    print("== a package the lock has no line for ==")
    short = project("unrecorded", reg, lockfile, {ELSEWHERE: rows[ELSEWHERE]})
    r, out = yarn(short, "--immutable")
    check(f"the install fails (exit {r.returncode}) naming wib-native and saying the lock records nothing for it",
          r.returncode != 0 and "YN0018" in out and f"{NATIVE}: {yp.LOCK_REL} records no checksum for it" in out,
          out[-1200:])
    check("and nothing is linked", installed(short) == "", installed(short))

with yp.Registry(packages(43)) as other:
    print("== a fetched copy that differs: a registry serving other bytes under the same name and version ==")
    fresh_global = SCRATCH / "yarn-global-2"
    moved = project("fetched-other", other, lockfile, rows)
    r, out = yarn(moved, "--immutable", global_folder=fresh_global)
    check(f"the install fetches it ({other.requests})", "/wib-native/-/wib-native-1.0.0.tgz" in other.requests)
    check(f"and fails (exit {r.returncode}) with YN0018, naming the package and the lock's checksum",
          r.returncode != 0 and "YN0018" in out and NATIVE in out and rows[NATIVE][0] in out, out[-1500:])
    check("and nothing is linked", installed(moved) == "", installed(moved))

finish()
